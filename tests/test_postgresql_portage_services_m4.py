"""Services M4 (recalcul certifié, relecture courante, historique, politiques, capacités) sur SQLite ET PostgreSQL.

Défaut latent L8 du rapport de qualification PostgreSQL : ces services exigeaient `BEGIN IMMEDIATE` (écouteur `begin`
de l'engine) et l'identité d'un FICHIER SQLite. Sous PostgreSQL : verrou consultatif d'instance détenu par la session
et vérifié à chaque pas (`stockage.exclusion`), identité de base (nom, OID, identifiant de système).
Preuves : l'exclusion
est réelle (un autre processus ne peut pas prendre le verrou), elle est vérifiée et non supposée (retirée, la portée
refuse), le recalcul certifié publie puis rejoue sur les deux moteurs, et N processus concurrents ne produisent ni panne
ni double publication.

Données fictives, aucun réseau.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
from collections import Counter
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from pg_concurrence import lancer, octroyer_politique, recalculer_certifie
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import func, select, text

from opsys import moteur_recalcul_m4 as moteur
from opsys import service_capability as sc
from opsys import service_politiques, service_recalcul_m4, stockage
from opsys.console.securite import Session
from opsys.stockage import exclusion
from opsys.stockage.schema import REGISTRES, SERVICE_POLITIQUES, SERVICE_RECALCUL_INTENTIONS, SERVICE_RECALCUL_RESULTATS

FICTIF = True
N = 4
RACINE = Path(__file__).resolve().parent


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location("portage_m4_" + nom, RACINE / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cm = _charger("test_cascade_marge_m5_m8_m10")
BASE = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=cm.DT_TZ)
LEAD, DEVIS, CHANTIER = "LEAD-E2-fictif", "DEVIS-E2-fictif", "CH-E2-fictif"


def _intention(etiquette: str) -> str:
    return hashlib.sha256(f"portage-{etiquette}".encode()).hexdigest()


@pytest.fixture
def base(url_base, monkeypatch):  # noqa: F811
    """La base du test (SQLite ou PostgreSQL) devient celle de l'instance ; stockage durable M2 et M5."""
    monkeypatch.setenv(stockage.ENV_URL, url_base)
    stockage.migrer(url_base)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    try:
        yield url_base
    finally:
        m2_outils.reinitialiser_registre()
        stockage.liberer()


def _chantier() -> str:
    deps = cm.charger_departements() if hasattr(cm, "charger_departements") else None
    from opsys.departements import charger_departements

    deps = deps or charger_departements()
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), 8.0)
    wct_id, _ = cm._chantier_termine(deps, BASE, LEAD, DEVIS, CHANTIER, 40.0, certifie=True)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    return wct_id


def _empreinte_portable() -> str:
    """Contenu de toutes les tables (lignes triées par leur représentation) : portable, sans rowid ni sqlite_master."""
    from sqlalchemy import inspect

    h = hashlib.sha256()
    with stockage.transaction() as cnx:
        for table in sorted(inspect(cnx).get_table_names()):
            if table.startswith("connaissances_fts") or table == "sqlite_sequence":
                continue
            h.update(table.encode())
            for ligne in sorted(repr(tuple(r)) for r in cnx.exec_driver_sql(f'SELECT * FROM "{table}"').all()):
                h.update(ligne.encode())
    return h.hexdigest()


def _recalculer(wct_id, intention):
    session = cm._session_admin_certifie()
    with stockage.transaction() as cnx:
        return moteur.recalculer(cnx, session, acteur=cm.ADMIN_CERTIFIE, wct_id=wct_id, devis_id=DEVIS,
                                 intention_id=_intention(intention))


# -- exclusion et identité ---------------------------------------------------------------------------------------------
def test_l_exclusion_est_engagee_puis_verifiee_sur_les_deux_moteurs(base):
    with stockage.transaction() as cnx:
        if cnx.dialect.name == "postgresql":
            assert exclusion.exclusion_engagee(cnx) is False  # rien n'est supposé : le verrou n'est pas encore pris
            exclusion.engager(cnx)
        assert exclusion.exclusion_engagee(cnx) is True
        assert exclusion.transaction_driver_ouverte(cnx) is True
    with stockage.transaction() as cnx:
        if cnx.dialect.name == "postgresql":
            assert exclusion.exclusion_engagee(cnx) is False  # le verrou d'une transaction terminée n'existe plus


def test_sur_postgresql_un_autre_processus_ne_peut_pas_prendre_le_verrou_d_instance_tant_que_la_portee_vit(base):
    if not base.startswith("postgresql"):
        pytest.skip("propre à PostgreSQL (sous SQLite : BEGIN IMMEDIATE, voir test_lecture_m4_verrou_qa)")
    cle = exclusion.cle_verrou(exclusion.NOM_VERROU_ECRITURE)
    autre = stockage.moteur(base).connect()
    try:
        with stockage.transaction() as cnx:
            exclusion.engager(cnx)
            with autre.begin():
                assert autre.execute(select(func.pg_try_advisory_xact_lock(cle))).scalar_one() is False
        with autre.begin():
            assert autre.execute(select(func.pg_try_advisory_xact_lock(cle))).scalar_one() is True
    finally:
        autre.close()


def test_un_rollback_vers_un_point_anterieur_au_verrou_le_relache_et_le_controle_le_voit(base):
    if not base.startswith("postgresql"):
        pytest.skip("propre à PostgreSQL")
    with stockage.transaction() as cnx:
        try:
            with cnx.begin_nested():
                exclusion.engager(cnx)
                assert exclusion.exclusion_engagee(cnx) is True
                raise RuntimeError("annulation voulue")
        except RuntimeError:
            pass
        assert exclusion.exclusion_engagee(cnx) is False  # la portée ne peut plus croire qu'elle est exclusive


def test_l_identite_de_base_est_stable_dans_la_transaction_et_distincte_entre_deux_bases(base, serveur_pg, tmp_path):  # noqa: F811
    with stockage.transaction() as cnx:
        premiere = exclusion.identite_base(cnx)
        assert exclusion.identite_base(cnx) == premiere
        assert sc._base(cnx) == premiere
    if base.startswith("postgresql"):
        nom, autre_url = serveur_pg.nouvelle_base()
        try:
            with stockage.transaction(autre_url) as cnx:
                assert exclusion.identite_base(cnx)[:1] == ("postgresql",)
                assert exclusion.identite_base(cnx) != premiere  # autre nom, autre OID
        finally:
            stockage.liberer(autre_url)
            serveur_pg.supprimer(nom)
    else:
        autre_url = "sqlite:///" + str(tmp_path / "autre.db")
        stockage.migrer(autre_url)
        with stockage.transaction(autre_url) as cnx:
            assert exclusion.identite_base(cnx) != premiere
        stockage.liberer(autre_url)


# -- recalcul certifié -------------------------------------------------------------------------------------------------
def test_le_recalcul_certifie_publie_se_rejoue_et_ne_reecrit_rien_sur_les_deux_moteurs(base):
    wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    reponse = _recalculer(wct_id, "premiere")
    assert reponse["statut"] == "publiee"
    assert reponse["attestation"]["operation"] == "m4.recalculer_v3"
    assert reponse["attestation"]["acteur"] == cm.ADMIN_CERTIFIE
    service_recalcul_m4.valider_reference_v2(reponse["attestation"])
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(SERVICE_RECALCUL_RESULTATS)).scalar_one() == 1
    avant = _empreinte_portable()
    rejeu = _recalculer(wct_id, "premiere")
    assert rejeu["statut"] == "deja_executee"
    assert rejeu["historique"]["attestation"] == reponse["attestation"]  # la preuve rejouée est identique
    assert _empreinte_portable() == avant  # relecture : zéro écriture
    second = _recalculer(wct_id, "deuxieme")
    assert second == {"statut": "rien_a_faire", "raison": "etat_certifie_a_jour"}
    assert _empreinte_portable() == avant


def test_un_refus_du_moteur_n_ecrit_rien_sur_les_deux_moteurs(base):
    wct_id = _chantier()  # aucune politique `m4.recalculer_v3` : refus typé
    avant = _empreinte_portable()
    with pytest.raises(moteur.RefusRecalculM4) as exc:
        _recalculer(wct_id, "sans-politique")
    assert exc.value.code == moteur.POLITIQUE_ABSENTE
    assert _empreinte_portable() == avant


def test_la_portee_du_moteur_refuse_quand_l_exclusion_d_ecriture_n_est_pas_engagee(base, monkeypatch):
    """Vérifiée, pas supposée : on neutralise `engager` -> la portée refuse (PostgreSQL ; SQLite : écouteur retiré)."""
    wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    avant = _empreinte_portable()
    if base.startswith("postgresql"):
        monkeypatch.setattr(moteur, "engager", lambda cnx: None)
    else:
        from sqlalchemy import event as sqla_event

        from opsys.stockage.moteur import _debuter_sqlite
        sqla_event.remove(stockage.moteur(base), "begin", _debuter_sqlite)
    with pytest.raises(moteur.RefusRecalculM4) as exc:
        _recalculer(wct_id, "sans-verrou")
    assert exc.value.code == moteur.VERROU_ECRITURE_ABSENT
    assert _empreinte_portable() == avant


def test_n_processus_demandent_la_meme_intention_une_publication_les_autres_relisent(base):
    wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    issues = lancer(recalculer_certifie, [(wct_id, DEVIS, _intention("commune"))] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"publiee": 1, "deja_executee": N - 1}, issues
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(SERVICE_RECALCUL_INTENTIONS)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(SERVICE_RECALCUL_RESULTATS)).scalar_one() == 1


def test_n_processus_avec_des_intentions_differentes_une_seule_publication_les_autres_n_ont_rien_a_faire(base):
    wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    issues = lancer(recalculer_certifie, [(wct_id, DEVIS, _intention(f"i{i}")) for i in range(N)])
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"publiee": 1, "rien_a_faire": N - 1}, issues


# -- politiques de service (opérateur console) -------------------------------------------------------------------------
def _admin_console():
    from opsys import identite

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin FICTIF", "mot-de-passe-fictif-1234", ["admin"])


def test_n_processus_octroient_la_meme_politique_une_seule_revision(base):
    _admin_console()
    issues = lancer(octroyer_politique, [("m4.verifier_v3",)] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"octroyee": 1, "refus": N - 1}, issues
    assert {i[1] for i in issues if i[0] == "refus"} == {"DEJA_ACTIVE"}
    with stockage.transaction() as cnx:
        revisions = cnx.execute(select(SERVICE_POLITIQUES.c.revision)
                                .where(SERVICE_POLITIQUES.c.operation == "m4.verifier_v3")).scalars().all()
        assert revisions == [1]  # une seule révision : jamais deux écrivains sur la même clé


def test_un_moteur_non_qualifie_est_refuse_par_l_operateur():
    from types import SimpleNamespace

    cnx = SimpleNamespace(engine=SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    session = Session("admin.fictif", frozenset({"admin"}), "csrf-fictif", 4102444800)
    with pytest.raises(service_politiques.RefusOperateur) as exc:
        service_politiques.octroyer(cnx, session, "m4.verifier_v3", motif="moteur fictif")
    assert exc.value.code == "BACKEND_NON_QUALIFIE"


def test_les_registres_du_scenario_vivent_dans_la_meme_table_sur_les_deux_moteurs(base):
    """Garde-fou du test lui-même : le scénario écrit bien dans `registres_maillons` de la base testée."""
    _chantier()
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one() > 10
        assert cnx.execute(text("SELECT 1")).scalar_one() == 1
