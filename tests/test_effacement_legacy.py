"""Régression causale F4 : ancienneté freelist, lecteur réel et garde de maintenance."""
from __future__ import annotations

import importlib
import secrets
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import delete, insert

from opsys import cles_chiffrement as coffre
from opsys import stockage
from opsys.stockage.schema import CLES_CHIFFREMENT

storage = importlib.import_module("opsys.stockage.moteur")
DATE = "2026-10-22T19:00:00+00:00"
PORTEE = "qa-fictif/legacy"


@pytest.fixture
def base(tmp_path, monkeypatch):
    path = tmp_path / "coffre.db"
    url = "sqlite:///" + str(path)
    monkeypatch.setenv("OPSYS_BASE_URL", url)
    assert stockage.migrer(url) == "0027"
    yield path, url
    stockage.liberer()


def _present(path, key):
    return any(key in p.read_bytes() or key.hex().encode() in p.read_bytes()
               for suffix in ["", "-wal", "-shm", "-journal"]
               if (p := Path(str(path) + suffix)).exists())


def _etat(url, purge_id):
    with storage.transaction(url) as cnx:
        return coffre.lire_effacement(cnx, purge_id)


def test_legacy_pages_rebalance_ne_garde_pas_ancienne_cle_apres_termine(base):
    path, url = base
    def ident(i):
        return f"personne-fictive-{i:05d}-" + "x" * 75
    victim = ident(5000)
    with storage.transaction(url) as cnx:
        cnx.exec_driver_sql("PRAGMA secure_delete=OFF")  # Histoire QA uniquement, pas réglage produit.
        assert cnx.exec_driver_sql("PRAGMA secure_delete").scalar_one() == 0
        rows = [{"portee": PORTEE, "identifiant": ident(i), "cle": secrets.token_hex(32), "cree_le": DATE}
                for i in range(10000) if i != 5000]
        cnx.execute(insert(CLES_CHIFFREMENT), rows)
        key = coffre.obtenir_ou_creer(cnx, PORTEE, victim, DATE)
    with storage.transaction(url) as cnx:
        assert cnx.exec_driver_sql("PRAGMA secure_delete").scalar_one() == 0
        cnx.execute(delete(CLES_CHIFFREMENT).where(CLES_CHIFFREMENT.c.identifiant != victim))
        meme_cle = coffre.lire(cnx, PORTEE, victim) == key
        assert meme_cle
        assert cnx.exec_driver_sql("PRAGMA freelist_count").scalar_one() > 0
    with storage.transaction(url) as cnx:
        reponse = coffre.demander_effacement(cnx, PORTEE, victim, DATE, demande_id="approbation-fictive")
    assert _etat(url, reponse["purge_id"])["etat_fichiers"] == "termine"
    residu = _present(path, key)
    assert not residu, "clé fictive encore présente malgré l'attestation termine"
    with storage.transaction(url) as cnx:
        assert cnx.exec_driver_sql("PRAGMA quick_check").scalar_one() == "ok"
        assert coffre.lire(cnx, PORTEE, victim) is None


def test_lecteur_bloque_reconstruction_puis_reprise_preserve_nouvelle_generation(base):
    path, url = base
    with storage.transaction(url) as cnx:
        key = coffre.obtenir_ou_creer(cnx, PORTEE, "personne-fictive", DATE)
    reader = sqlite3.connect(path)
    reader.execute("BEGIN")
    reader.execute("SELECT cle FROM cles_chiffrement").fetchall()
    try:
        with storage.transaction(url) as cnx:
            reponse = coffre.demander_effacement(cnx, PORTEE, "personne-fictive", DATE)
        assert _etat(url, reponse["purge_id"])["etat_fichiers"] == "en_attente"
        residu = _present(path, key)
        assert residu
        with storage.transaction(url) as cnx:
            nouvelle = coffre.obtenir_ou_creer(cnx, PORTEE, "personne-fictive", DATE)
        distincte = nouvelle != key
        assert distincte
    finally:
        reader.close()
    assert coffre.finaliser_effacement(reponse["purge_id"], url)["etat_fichiers"] == "termine"
    residu = _present(path, key)
    assert not residu
    with storage.transaction(url) as cnx:
        meme_nouvelle = coffre.lire(cnx, PORTEE, "personne-fictive") == nouvelle
        assert meme_nouvelle


def test_budget_strict_refuse_sans_fausse_cloture_puis_reprise(base):
    _, url = base
    # Connexion externe : job validé mais aucun callback automatique, contrat de reprise explicite.
    with storage.moteur(url).begin() as cnx:
        coffre.obtenir_ou_creer(cnx, PORTEE, "personne-fictive", DATE)
        reponse = coffre.demander_effacement(cnx, PORTEE, "personne-fictive", DATE)
    budget = coffre.BudgetNettoyage(max_octets_base=4096)
    pending = coffre.finaliser_effacement(reponse["purge_id"], url, budget=budget)
    assert pending["etat_fichiers"] == "en_attente"
    assert pending["motif"] == "budget_taille"
    bref = coffre.BudgetNettoyage(max_secondes=1e-12)
    interrompu = coffre.finaliser_effacement(reponse["purge_id"], url, budget=bref)
    assert interrompu["etat_fichiers"] == "en_attente"
    assert interrompu["motif"] == "budget_duree"
    with pytest.raises(ValueError, match="budget"):
        coffre.BudgetNettoyage(max_secondes=float("nan"))
    with pytest.raises(ValueError, match="budget"):
        coffre.BudgetNettoyage(max_octets_base=True)
    assert coffre.finaliser_effacement(reponse["purge_id"], url)["etat_fichiers"] == "termine"
