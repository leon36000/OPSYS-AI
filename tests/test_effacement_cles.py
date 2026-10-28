"""F4 : suppression logique et nettoyage courant distincts ; données entièrement fictives."""
from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_mock_engine, event

from opsys import cles_chiffrement as coffre
from opsys import stockage

storage = importlib.import_module("opsys.stockage.moteur")
PORTEE = "qa-fictif/retention"
ID = "personne-fictive"
DATE = "2026-10-22T19:00:00+00:00"


@pytest.fixture
def base(tmp_path, monkeypatch):
    path = tmp_path / "coffre.db"
    url = "sqlite:///" + str(path)
    monkeypatch.setenv("OPSYS_BASE_URL", url)
    assert stockage.migrer(url) == ScriptDirectory.from_config(stockage._config()).get_current_head()
    with storage.transaction(url) as cnx:
        key = coffre.obtenir_ou_creer(cnx, PORTEE, ID, DATE)
    yield path, url, key
    stockage.liberer()


def _present(path, key):
    return any(key in p.read_bytes() or key.hex().encode() in p.read_bytes()
               for suffix in ["", "-wal", "-shm", "-journal"]
               if (p := Path(str(path) + suffix)).exists())


def _etat(url, purge_id):
    with storage.transaction(url) as cnx:
        return coffre.lire_effacement(cnx, purge_id)


def test_api_destruction_logique_et_supports_separes():
    assert callable(getattr(coffre, "demander_effacement", None)), "API durable manquante"
    assert callable(getattr(coffre, "finaliser_effacement", None))
    assert callable(getattr(coffre, "lire_effacement", None))


def test_commit_nettoie_apres_commit_et_reponse_initiale_immuable(base):
    path, url, key = base
    with storage.transaction(url) as cnx:
        reponse = coffre.demander_effacement(cnx, PORTEE, ID, DATE, demande_id="approbation-fictive")
        assert coffre.lire(cnx, PORTEE, ID) is None
        assert reponse["etat_fichiers"] == "en_attente"
        assert coffre.lire_effacement(cnx, reponse["purge_id"])["etat_fichiers"] == "en_attente"
    assert reponse["etat_fichiers"] == "en_attente"
    final = _etat(url, reponse["purge_id"])
    assert final["etat_fichiers"] == "termine"
    assert final["cle_detruite"] is True
    assert not _present(path, key)


def test_rollback_exterieur_annule_cle_file_et_hook(base):
    _, url, key = base
    purge_id = uuid.uuid4().hex
    with pytest.raises(ValueError, match="rollback-fictif"), storage.transaction(url) as cnx:
        coffre.demander_effacement(cnx, PORTEE, ID, DATE, purge_id=purge_id)
        raise ValueError("rollback-fictif")
    with storage.transaction(url) as cnx:
        assert coffre.lire(cnx, PORTEE, ID) == key
        assert coffre.lire_effacement(cnx, purge_id) is None


def test_savepoint_ne_finalise_pas_et_rollback_ne_fuit_pas(base):
    _, url, key = base
    abandon = uuid.uuid4().hex
    with storage.transaction(url) as cnx:
        with pytest.raises(ValueError, match="savepoint-fictif"), storage.transaction(url) as inner:
            coffre.demander_effacement(inner, PORTEE, ID, DATE, purge_id=abandon)
            raise ValueError("savepoint-fictif")
        assert coffre.lire(cnx, PORTEE, ID) == key
        with storage.transaction(url) as inner:
            reponse = coffre.demander_effacement(inner, PORTEE, ID, DATE)
        assert coffre.lire_effacement(cnx, reponse["purge_id"])["etat_fichiers"] == "en_attente"
    assert _etat(url, abandon) is None
    assert _etat(url, reponse["purge_id"])["etat_fichiers"] == "termine"


def test_lecteur_busy_reprise_sans_delete_et_nouvelle_cle_preservee(base):
    path, url, key = base
    reader = sqlite3.connect(path)
    reader.execute("BEGIN")
    reader.execute("SELECT cle FROM cles_chiffrement").fetchall()
    try:
        with storage.transaction(url) as cnx:
            reponse = coffre.demander_effacement(cnx, PORTEE, ID, DATE)
        pending = _etat(url, reponse["purge_id"])
        assert pending["etat_fichiers"] == "en_attente"
        assert pending["motif"] == "wal_occupe"
        assert _present(path, key)
        with storage.transaction(url) as cnx:
            nouvelle = coffre.obtenir_ou_creer(cnx, PORTEE, ID, DATE)
        assert nouvelle != key
    finally:
        reader.close()
    statements = []
    engine = storage.moteur(url)
    def observe(_cnx, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert coffre.finaliser_effacement(reponse["purge_id"], url)["etat_fichiers"] == "termine"
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert not any(s.lstrip().upper().startswith("DELETE") for s in statements)
    with storage.transaction(url) as cnx:
        assert coffre.lire(cnx, PORTEE, ID) == nouvelle
    assert not _present(path, key)


def test_crash_apres_commit_laisse_file_durable_reprenante(base):
    _, url, _ = base
    purge_id = uuid.uuid4().hex
    code = """import os
from opsys import cles_chiffrement as c
from opsys.stockage.moteur import transaction, apres_validation
with transaction() as cnx:
 apres_validation(lambda: os._exit(0))
 c.demander_effacement(cnx,'qa-fictif/retention','personne-fictive','2026-10-22T19:00:00+00:00',purge_id=os.environ['QA_PURGE_ID'])
raise AssertionError('crash non execute')
"""
    env = dict(os.environ, QA_PURGE_ID=purge_id)
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=15, check=False)
    assert result.returncode == 0
    assert _etat(url, purge_id)["etat_fichiers"] == "en_attente"
    assert coffre.reprendre_effacements(url, limite=1)[0]["etat_fichiers"] == "termine"


def test_refuse_maintenance_avant_commit_et_backend_non_qualifie(base):
    _, url, key = base
    with storage.transaction(url) as cnx:
        with pytest.raises(RuntimeError, match="transaction"):
            coffre.finaliser_effacement(uuid.uuid4().hex, url)
        assert coffre.lire(cnx, PORTEE, ID) == key
    from opsys.cles_chiffrement import _nettoyer_fichiers_courants
    pg = create_mock_engine("postgresql://", lambda *_args, **_kwargs: None)
    assert _nettoyer_fichiers_courants(pg) == (False, "backend_non_qualifie")


def test_reprise_identite_operation_ne_detruit_pas_nouvelle_cle_et_downgrade_refuse(base):
    _, url, _ = base
    purge_id = uuid.uuid4().hex
    with storage.transaction(url) as cnx:
        premier = coffre.demander_effacement(cnx, PORTEE, ID, DATE, purge_id=purge_id, demande_id="demande-fictive")
    with storage.transaction(url) as cnx:
        nouvelle = coffre.obtenir_ou_creer(cnx, PORTEE, ID, DATE)
        autre = coffre.demander_effacement(cnx, PORTEE, ID, DATE, purge_id=purge_id, demande_id="demande-fictive")
        assert autre["purge_id"] == premier["purge_id"]
        assert coffre.lire(cnx, PORTEE, ID) == nouvelle
        with pytest.raises(ValueError, match="autre"):
            coffre.demander_effacement(
                cnx, PORTEE, "autre-identite", DATE, purge_id=purge_id, demande_id="demande-fictive",
            )
    revision_avant = stockage.revision_courante(url)
    config = stockage._config()
    with pytest.raises(RuntimeError, match="effacements"), storage.moteur(url).begin() as cnx:
        config.attributes["connection"] = cnx
        command.downgrade(config, "0026")
    assert stockage.revision_courante(url) == revision_avant
