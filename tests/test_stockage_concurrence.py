"""`opsys.stockage.concurrence` : relecture après conflit et verrous consultatifs, cas négatifs et d'abus, sur SQLite ET
sur un vrai PostgreSQL 17 (ignorés avec la raison exacte sans Docker). Les courses en vrais processus sont dans
`test_postgresql_portage_concurrence.py` ; ici, la mécanique : ce qui est rejoué, ce qui ne l'est JAMAIS, ce qui
remonte.
Données fictives, aucun réseau."""

from __future__ import annotations

import pytest
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, text
from sqlalchemy.exc import IntegrityError

from opsys import contexte, stockage
from opsys.outils import Autonomie, Outil, executer_atomique, executer_atomique_console
from opsys.stockage import concurrence
from opsys.stockage.maillons import EcritureConcurrente

FICTIF = True
M = MetaData()
ESSAI = Table("concurrence_essai", M, Column("id", Integer, primary_key=True), Column("nom", String(20), unique=True),
              Column("age", Integer))


def _table(cnx):
    cnx.exec_driver_sql("CREATE TABLE concurrence_essai (id integer primary key, nom varchar(20) unique, age integer, "
                        "CHECK (age IS NULL OR age >= 0))")


def test_sur_sqlite_le_corps_s_execute_directement_sans_point_de_sauvegarde_ni_rejeu(tmp_path):
    url = "sqlite:///" + str(tmp_path / "s.db")
    stockage.migrer(url)
    appels = []

    def corps():
        appels.append(1)
        raise EcritureConcurrente("rang pris")  # SQLite : écrivain unique, ce cas est un VRAI conflit de logique

    with stockage.transaction(url), pytest.raises(EcritureConcurrente):
        concurrence.relire_si_conflit(corps)
    assert appels == [1]  # aucun rejeu : le comportement SQLite est inchangé
    stockage.liberer(url)


def test_une_violation_d_unicite_est_rejouee_puis_le_corps_voit_l_etat_valide(url_base):  # noqa: F811
    if not url_base.startswith("postgresql"):
        pytest.skip("le rejeu ne vaut que sur PostgreSQL (SQLite : écrivain unique)")
    with stockage.transaction(url_base) as cnx:
        _table(cnx)
        cnx.execute(insert(ESSAI).values(id=1, nom="a", age=1))
    passages = []

    def corps():
        passages.append(1)
        if len(passages) == 1:
            # première passe : on tente le doublon que la course aurait produit -> 23505, point de sauvegarde annulé
            stockage.connexion_courante().execute(insert(ESSAI).values(id=2, nom="a", age=2))
        return stockage.connexion_courante().execute(select(ESSAI.c.nom).order_by(ESSAI.c.id)).scalars().all()

    with stockage.transaction(url_base):
        assert concurrence.relire_si_conflit(corps) == ["a"]  # la seconde passe lit l'état, la transaction reste saine
    assert len(passages) == 2


def test_une_violation_de_contrainte_check_n_est_jamais_rejouee_ni_avalee(url_base):  # noqa: F811
    if not url_base.startswith("postgresql"):
        pytest.skip("le rejeu ne vaut que sur PostgreSQL")
    with stockage.transaction(url_base) as cnx:
        _table(cnx)
    passages = []

    def corps():
        passages.append(1)
        stockage.connexion_courante().execute(insert(ESSAI).values(id=1, nom="z", age=-1))  # CHECK : un défaut

    with stockage.transaction(url_base), pytest.raises(IntegrityError):
        concurrence.relire_si_conflit(corps)
    assert passages == [1]


def test_un_conflit_qui_persiste_remonte_apres_le_nombre_d_essais_prevu(url_base):  # noqa: F811
    if not url_base.startswith("postgresql"):
        pytest.skip("le rejeu ne vaut que sur PostgreSQL")
    passages = []

    def corps():
        passages.append(1)
        raise EcritureConcurrente("toujours pris")

    with stockage.transaction(url_base), pytest.raises(EcritureConcurrente):
        concurrence.relire_si_conflit(corps, essais=3)
    assert len(passages) == 3  # ni boucle infinie, ni avalement


def test_le_sqlstate_est_lu_derriere_l_erreur_sqlalchemy(url_base):  # noqa: F811
    if not url_base.startswith("postgresql"):
        pytest.skip("SQLSTATE propre à PostgreSQL")
    with stockage.transaction(url_base) as cnx:
        _table(cnx)
        cnx.execute(insert(ESSAI).values(id=1, nom="a", age=1))
        with pytest.raises(IntegrityError) as exc, cnx.begin_nested():
            cnx.execute(insert(ESSAI).values(id=2, nom="a", age=1))
        assert concurrence.sqlstate(exc.value) == concurrence.SQLSTATE_UNICITE
        assert concurrence.est_conflit_rejouable(exc.value) is True
        with pytest.raises(IntegrityError) as exc2, cnx.begin_nested():
            cnx.execute(insert(ESSAI).values(id=3, nom="b", age=-5))
        assert concurrence.est_conflit_rejouable(exc2.value) is False  # CHECK (23514) : pas une course
    assert concurrence.est_conflit_rejouable(ValueError("x")) is False
    assert concurrence.est_conflit_rejouable(EcritureConcurrente("x")) is True


def test_le_verrou_consultatif_exige_la_transaction_courante_et_un_moteur_qualifie(url_base, monkeypatch):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        concurrence.verrou_consultatif(cnx, "essai")  # rien sous SQLite ; le verrou sous PostgreSQL
        concurrence.verrou_consultatif(cnx, "essai")  # ré-entrant dans la même transaction
    with pytest.raises(RuntimeError, match="transaction courante"):
        concurrence.verrou_consultatif(object(), "essai")  # une connexion étrangère à la transaction courante

    class Faux:
        class dialect:  # noqa: N801
            name = "mysql"

    faux = Faux()
    monkeypatch.setattr(concurrence, "connexion_courante", lambda: faux)
    with pytest.raises(ValueError, match="backend non qualifié"):
        concurrence.verrou_consultatif(faux, "essai")


def test_sur_postgresql_le_verrou_consultatif_refuse_un_instantane_plus_ancien_que_l_attente(url_base, monkeypatch):  # noqa: F811
    if not url_base.startswith("postgresql"):
        pytest.skip("propre à PostgreSQL")
    with stockage.moteur(url_base).connect().execution_options(isolation_level="REPEATABLE READ") as cnx, cnx.begin():
        monkeypatch.setattr(concurrence, "connexion_courante", lambda: cnx)
        with pytest.raises(ValueError, match="READ COMMITTED"):
            concurrence.verrou_consultatif(cnx, "essai")


def test_les_cles_de_verrou_sont_stables_distinctes_et_sur_64_bits():
    a, b = concurrence.cle_verrou("console-ecriture"), concurrence.cle_verrou("cron-operateur")
    assert a == concurrence.cle_verrou("console-ecriture") and a != b
    assert all(-(2**63) <= x < 2**63 for x in (a, b))


# -- executer_atomique_console : seul le port d'ÉCRITURE HUMAINE de la console est verrouillé et rejoué ----------------
def _outil(corps, autonomie=Autonomie.T1):
    return Outil("m9_essai_conflit", "Outil d'essai.", {"type": "object", "properties": {}}, corps, autonomie)


def test_executer_atomique_ordinaire_n_est_ni_verrouille_ni_rejoue_un_conflit_remonte_tel_quel(url_base):  # noqa: F811
    """Les appels d'agent (et tout appelant de `executer_atomique`) gardent exactement leur comportement."""
    appels = []

    def corps():
        appels.append(1)
        raise EcritureConcurrente("rang pris")

    console = contexte.IdentiteAppelante("admin.fictif", "admin", source="console")
    with (stockage.transaction(url_base), contexte.appele_par_appareil(console), pytest.raises(EcritureConcurrente)):
        executer_atomique(_outil(corps), {})
    assert appels == [1]


def test_un_port_de_console_perdant_une_course_est_rejoue_sur_postgresql_seulement(url_base):  # noqa: F811
    appels = []

    def corps():
        appels.append(1)
        if len(appels) == 1:
            raise EcritureConcurrente("rang pris")
        return {"x": 1}

    console = contexte.IdentiteAppelante("admin.fictif", "admin", source="console")
    with stockage.transaction(url_base), contexte.appele_par_appareil(console):
        if url_base.startswith("postgresql"):
            assert executer_atomique_console(_outil(corps), {}) == {"ok": True, "resultat": {"x": 1}}
            assert len(appels) == 2
        else:
            with pytest.raises(EcritureConcurrente):  # SQLite : jamais rejoué, comportement inchangé
                executer_atomique_console(_outil(corps), {})
            assert len(appels) == 1


def test_un_port_qui_traduit_lui_meme_le_conflit_garde_le_verrou_mais_pas_le_rejeu(url_base):  # noqa: F811
    """`rejouer=False` (ex. import d'avis M7 : 409 « rechargez », jamais de rejeu automatique)."""
    appels = []

    def corps():
        appels.append(1)
        raise EcritureConcurrente("rang pris")

    console = contexte.IdentiteAppelante("admin.fictif", "admin", source="console")
    with (stockage.transaction(url_base), contexte.appele_par_appareil(console), pytest.raises(EcritureConcurrente)):
        executer_atomique_console(_outil(corps), {}, rejouer=False)
    assert appels == [1]


def test_une_lecture_de_console_ne_prend_pas_le_verrou_d_ecriture(url_base):  # noqa: F811
    if not url_base.startswith("postgresql"):
        pytest.skip("propre à PostgreSQL")
    cle = concurrence.cle_verrou("console-ecriture")

    def lecture():
        return {"lu": True}

    autre = stockage.moteur(url_base).connect()
    try:
        console = contexte.IdentiteAppelante("admin.fictif", "admin", source="console")
        with stockage.transaction(url_base), contexte.appele_par_appareil(console):
            executer_atomique_console(_outil(lecture, Autonomie.T0), {})
            with autre.begin():
                assert autre.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": cle}).scalar_one() is True
            executer_atomique_console(_outil(lecture, Autonomie.T1), {})  # une écriture, elle, prend le verrou
            with autre.begin():
                assert autre.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": cle}).scalar_one() is False
    finally:
        autre.close()
