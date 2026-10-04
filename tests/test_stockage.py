"""Base de l'instance (ADR-0009) : codec typé, maillons durables, transaction par appel d'outil."""

from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import inspect, select, text

from opsys import stockage
from opsys.capacites import Capacites
from opsys.outils import Autonomie, Outil
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES


def _revision_tete():
    return ScriptDirectory.from_config(stockage._config()).get_current_head()


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


# -- codec -------------------------------------------------------------------------------------
def test_codec_restitue_les_types_metier():
    valeur = {
        "montant": Decimal("1234.50"),
        "couple": ("a", 1),
        "quand": dt.datetime(2026, 9, 28, 12, 30, tzinfo=dt.UTC),
        "jour": dt.date(2026, 9, 28),
        "liste": [1, 2.5, None, True, "é"],
        "imbrique": {"__opsys__": "piège", "x": Decimal("0.1")},
    }
    assert codec.decoder(codec.encoder(valeur)) == valeur
    assert type(codec.decoder(codec.encoder(valeur))["couple"]) is tuple


def test_codec_refuse_ce_qu_il_ne_sait_pas_restituer():
    with pytest.raises(TypeError):
        codec.encoder({"objet": object()})
    with pytest.raises(ValueError):
        codec.encoder({"nan": float("nan")})
    with pytest.raises(TypeError):
        codec.encoder({1: "clé non textuelle"})


# -- maillons durables -------------------------------------------------------------------------
def test_maillons_se_comportent_comme_une_liste_et_survivent(base):
    maillons = stockage.maillons("m04-field-ops", "principal")
    assert len(maillons) == 0 and not maillons
    with stockage.transaction():
        maillons.append({"n": 0, "montant": Decimal("10.00")})
        maillons.extend([{"n": 1}, {"n": 2}])
    relu = stockage.maillons("m04-field-ops", "principal")  # nouvelle instance : rien en cache
    assert len(relu) == 3 and relu
    assert relu[-1] == {"n": 2} and relu[0]["montant"] == Decimal("10.00")
    assert [m["n"] for m in relu] == [0, 1, 2]
    assert relu[1:] == [{"n": 1}, {"n": 2}]
    copie = copy.deepcopy(relu)
    assert type(copie) is list and copie == list(relu)
    with pytest.raises(IndexError):
        relu[3]


def test_registres_cloisonnes_par_departement_et_par_nom(base):
    with stockage.transaction():
        stockage.maillons("m04-field-ops", "principal").append({"a": 1})
        stockage.maillons("m06-material-control", "principal").append({"b": 2})
        stockage.maillons("m04-field-ops", "secondaire").append({"c": 3})
    assert list(stockage.maillons("m04-field-ops", "principal")) == [{"a": 1}]
    assert list(stockage.maillons("m06-material-control", "principal")) == [{"b": 2}]


def test_une_erreur_annule_toute_la_transaction(base):
    maillons = stockage.maillons("m04-field-ops", "principal")
    with pytest.raises(RuntimeError), stockage.transaction():
        maillons.append({"n": 0})
        raise RuntimeError("panne au milieu")
    assert len(maillons) == 0


def test_transaction_imbriquee_n_annule_que_sa_part(base):
    maillons = stockage.maillons("m04-field-ops", "principal")
    with stockage.transaction():
        maillons.append({"n": "externe"})
        with pytest.raises(ValueError), stockage.transaction():
            maillons.append({"n": "interne"})
            raise ValueError("échec interne")
    assert list(maillons) == [{"n": "externe"}]


def test_la_migration_est_idempotente(base):
    stockage.migrer(base)
    stockage.migrer(base)
    with stockage.transaction() as cnx:
        assert cnx.execute(select(REGISTRES.c.rang)).all() == []


# -- une transaction par appel d'outil ---------------------------------------------------------
_SCHEMA = {"type": "object", "properties": {"echouer": {"type": "boolean"}}, "required": ["echouer"]}


def _ecrire(echouer: bool) -> dict:
    stockage.maillons("m09-demo", "principal").append({"ecrit": True})
    if echouer:
        raise ValueError("refus métier après une écriture")
    return {"ecrit": True}


def test_un_outil_en_echec_ne_laisse_aucune_ecriture(base, departements_demo, session, monkeypatch):
    monkeypatch.setattr(
        "opsys.capacites._outils_memoire",
        lambda: (Outil("opsys_ecrire", "Écrit puis échoue au besoin.", _SCHEMA, _ecrire, Autonomie.T0),),
    )
    cap = Capacites(departements_demo, session, appelant="m09-demo")
    assert cap.appeler("opsys_ecrire", {"echouer": True})["ok"] is False
    assert len(stockage.maillons("m09-demo", "principal")) == 0
    assert cap.appeler("opsys_ecrire", {"echouer": False})["ok"] is True
    assert len(stockage.maillons("m09-demo", "principal")) == 1


# -- PostgreSQL en option : même comportement --------------------------------------------------
@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_postgresql_se_comporte_comme_sqlite(monkeypatch):
    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            stockage.migrer(url)
            maillons = stockage.maillons("m05-financecore", "principal")
            with stockage.transaction():
                maillons.append({"montant": Decimal("99.99")})
            with pytest.raises(RuntimeError), stockage.transaction():
                maillons.append({"n": "perdu"})
                raise RuntimeError("annulé")
            assert list(stockage.maillons("m05-financecore", "principal")) == [{"montant": Decimal("99.99")}]
        finally:
            stockage.liberer()


# -- exploitation : opsys-metier base migrer | etat ---------------------------------------------------
def test_cli_base_migrer_et_etat(tmp_path, monkeypatch, capsys):
    import json

    from opsys import cli

    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    try:
        assert cli.main(["base", "migrer"]) == 0
        # L'état de migration inclut la configuration durable STT après l'élargissement tokens.
        assert json.loads(capsys.readouterr().out)["revision"] == _revision_tete()
        with stockage.transaction():
            stockage.maillons("m04-field-ops", "principal").append({"n": 1})
        assert cli.main(["base", "etat"]) == 0
        etat_base = json.loads(capsys.readouterr().out)
        assert etat_base["moteur"] == "sqlite" and etat_base["revision"] == _revision_tete()
        assert etat_base["registres"] == [{"departement": "m04-field-ops", "registre": "principal", "maillons": 1}]
    finally:
        stockage.liberer()


def test_etat_masque_le_mot_de_passe():
    from opsys.cli import _url_masquee

    assert (
        _url_masquee("postgresql+psycopg://opsys:secret@hote:5432/opsys")
        == "postgresql+psycopg://opsys:***@hote:5432/opsys"
    )


def test_migration_0015_preserve_les_lignes_sqlite_0014_et_stocke_les_tokens_sur_64_bits(tmp_path):
    url = f"sqlite:///{tmp_path / 'opsys-0014.db'}"
    with stockage.moteur(url).begin() as cnx:
        configuration = stockage._config()
        configuration.attributes["connection"] = cnx
        command.upgrade(configuration, "0014")
        cnx.execute(text(
            "INSERT INTO usage_tokens (jour,departement,modele,appels,tokens_entree,tokens_sortie,tokens_cache_lus) "
            "VALUES ('2026-10-01','m09-demo','modele-test',2,101,202,303)"
        ))
        cnx.execute(text(
            "INSERT INTO agents_configurables "
            "(id,departement,responsabilite,palier_modele,outils,budget_jour,budget_mois,limite_tours,"
            "limite_reessais,limite_concurrence,declencheurs,actif,supprime,revision,cree_le,modifie_le,"
            "modifie_par,mutation_id,mutation_hash) VALUES "
            "('profil-test','m09-demo','test','standard','[]',100,1000,2,0,1,'[]',1,0,1,'t','t','admin','m1','h')"
        ))
        cnx.execute(text(
            "INSERT INTO agents_politique_entreprise "
            "(id,budget_jour,budget_mois,revision,modifie_le,modifie_par) VALUES (1,100,1000,1,'t','admin')"
        ))
        cnx.execute(text(
            "INSERT INTO agents_reservations "
            "(id,agent_id,departement,execution_id,cle_idempotence,tokens_plafond,tokens_reels,jour,mois,tours,"
            "reessais,attempt_id,cycle_id,candidate_index,stream_ordinal,is_fallback_retry,statut,cree_le,modifie_le) "
            "VALUES ('a','profil-test','m09-demo','exec','key',10,9,'2026-10-01','2026-10',1,0,'exec:0',"
            "'exec:0:0',0,0,0,'conciliee','t','t')"
        ))
        cnx.execute(text(
            "INSERT INTO agents_reservations_historique "
            "(id,reservation_id,evenement,tokens_reels,raison,cree_le) "
            "VALUES ('b','a','conciliee',9,'historique conservé','t')"
        ))

    assert stockage.migrer(url) == _revision_tete()
    with stockage.moteur(url).begin() as cnx:
        assert "connecteurs_stt" in inspect(cnx).get_table_names()
        assert tuple(cnx.execute(text(
            "SELECT appels,tokens_entree,tokens_sortie,tokens_cache_lus FROM usage_tokens"
        )).one()) == (2, 101, 202, 303)
        assert tuple(cnx.execute(text(
            "SELECT budget_jour,budget_mois FROM agents_configurables WHERE id='profil-test'"
        )).one()) == (100, 1000)
        assert tuple(cnx.execute(text(
            "SELECT budget_jour,budget_mois FROM agents_politique_entreprise WHERE id=1"
        )).one()) == (100, 1000)
        assert tuple(cnx.execute(text(
            "SELECT tokens_plafond,tokens_reels FROM agents_reservations WHERE id='a'"
        )).one()) == (10, 9)
        assert tuple(cnx.execute(text(
            "SELECT tokens_reels FROM agents_reservations_historique WHERE id='b'"
        )).one()) == (9,)
        cnx.execute(text(
            "UPDATE agents_politique_entreprise SET budget_jour=3000000000,budget_mois=4000000000 WHERE id=1"
        ))
        assert cnx.execute(text(
            "SELECT budget_jour FROM agents_politique_entreprise WHERE id=1"
        )).scalar_one() == 3_000_000_000
