"""Deux outils M10 différents ne doivent pas append un maillon avec une tête périmée."""

from __future__ import annotations

import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from m10_memoire import outils as m10
from pg_parite import base_pg, serveur_pg  # noqa: F401

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.maillons import EcritureConcurrente

RACINE = Path(__file__).resolve().parents[1]
AFFAIRE = "LEAD-REGISTRE-RACE-FICTIF"
JOUR = "2026-09-15"
HORODATAGE = "2026-09-16T03:00:00Z"


@pytest.fixture(autouse=True)
def _base_pg_m10(base_pg, monkeypatch):  # noqa: F811 - fixture PostgreSQL importée ci-dessus
    moteur = importlib.import_module("opsys.stockage.moteur")
    stockage.liberer()
    monkeypatch.setenv(stockage.ENV_URL, base_pg)
    monkeypatch.setattr(moteur, "url_base", lambda: base_pg)
    monkeypatch.setattr(stockage, "url_base", lambda: base_pg)
    yield
    stockage.liberer()


def _capacites():
    return Capacites(
        charger_departements(RACINE / "departments"),
        stockage.transaction,
        filtre={"m10-memoire"},
        memoire=False,
    )


def _semer_wct():
    wct = {
        "wct_id": "WCT-REGISTRE-RACE-FICTIF",
        "intervention_id": "INT-REGISTRE-RACE-FICTIF",
        "lead_id": AFFAIRE,
        "technicien_id": "TECH-FICTIF",
        "horodatage_completion": "2026-09-15T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "b" * 64,
        "consommateurs_cibles": ["M10"],
        "devis_id": "DEV-FICTIF",
    }
    with stockage.transaction():
        _, code = m10.wct.memoriser_wct(wct, m10._REGISTRE_EVENEMENTS)
    assert code is None


def test_deux_ecrivains_publics_refusent_un_append_au_rang_perime(monkeypatch):
    _semer_wct()
    depart = threading.Barrier(3)
    deux_predecesseurs_lus = threading.Barrier(2)
    candidat_commis = threading.Event()
    code = importlib.import_module("m10_memoire.registre").encodage
    empreinte_orig = code.empreinte
    types_synchronises = set()
    mutex_synchronisation = threading.Lock()
    append_type = type(stockage.maillons("m10-memoire", "affaires"))
    append_orig = append_type.append

    def empreinte_synchronisee(corps, precedent):
        type_entree = corps.get("type_entree")
        if type_entree in {"fait_candidat", "fait_consolide"}:
            with mutex_synchronisation:
                synchroniser = type_entree not in types_synchronises
                types_synchronises.add(type_entree)
            if synchroniser:
                deux_predecesseurs_lus.wait(timeout=20)
        return empreinte_orig(corps, precedent)

    def append_ordonne(registre, maillon, *, rang_attendu=None):
        if threading.current_thread().name == "consolidator":
            assert candidat_commis.wait(20)
        return append_orig(registre, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(code, "empreinte", empreinte_synchronisee)
    monkeypatch.setattr(append_type, "append", append_ordonne)

    def appeler(nom, outil, args):
        threading.current_thread().name = nom
        depart.wait(timeout=20)
        reponse = _capacites().appeler(outil, args)
        if nom == "candidate":
            candidat_commis.set()
        return reponse

    args_candidat = {
        "affaire_id": AFFAIRE,
        "departement": "m03-estimation",
        "faits": [{"cle": "FICTIF-CLE-1", "outil": "m3_creer_estimation", "resultat": "ok", "code": None}],
        "horodatage": HORODATAGE,
    }
    args_consolidation = {"affaire_id": AFFAIRE, "jour": JOUR, "horodatage": HORODATAGE}
    with ThreadPoolExecutor(max_workers=2) as pool:
        candidat = pool.submit(appeler, "candidate", "m10_deposer_faits_candidats", args_candidat)
        consolidation = pool.submit(appeler, "consolidator", "m10_consolider_affaire", args_consolidation)
        depart.wait(timeout=20)
        resultats, erreurs = [], []
        for futur in (candidat, consolidation):
            try:
                resultats.append(futur.result(timeout=40))
            except EcritureConcurrente as exc:
                erreurs.append(exc)

    assert len(resultats) == 1 and resultats[0]["ok"], resultats
    assert len(erreurs) == 1 and isinstance(erreurs[0], EcritureConcurrente), erreurs
    assert m10._REGISTRE_AFFAIRES.valider_chaine() == (True, "")
    assert len(m10._REGISTRE_AFFAIRES.lire()) == 1
