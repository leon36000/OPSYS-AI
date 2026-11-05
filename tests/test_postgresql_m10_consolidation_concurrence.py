"""Course de consolidation M10 sur PostgreSQL jetable et appels publics simultanés."""

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
ARGS = {"affaire_id": "LEAD-RACE-FICTIF", "jour": "2026-09-15", "horodatage": "2026-09-16T03:00:00Z"}


@pytest.fixture(autouse=True)
def _base_pg_m10(base_pg, monkeypatch):  # noqa: F811 - pytest fixture imported above
    moteur = importlib.import_module("opsys.stockage.moteur")
    stockage.liberer()
    monkeypatch.setenv(stockage.ENV_URL, base_pg)
    monkeypatch.setattr(moteur, "url_base", lambda: base_pg)
    monkeypatch.setattr(stockage, "url_base", lambda: base_pg)
    yield
    stockage.liberer()


def _capacites() -> Capacites:
    return Capacites(
        charger_departements(RACINE / "departments"),
        stockage.transaction,
        filtre={"m10-memoire"},
        memoire=False,
    )


def _semer_wct_fictif() -> None:
    wct = {
        "wct_id": "WCT-RACE-FICTIF",
        "intervention_id": "INT-RACE-FICTIF",
        "lead_id": ARGS["affaire_id"],
        "technicien_id": "TECH-FICTIF",
        "horodatage_completion": "2026-09-15T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"],
        "devis_id": "DEV-FICTIF",
    }
    with stockage.transaction():
        _, code = m10.wct.memoriser_wct(wct, m10._REGISTRE_EVENEMENTS)
    assert code is None


def _deux_appels_publics_simultanes():
    depart = threading.Barrier(3)

    def appeler():
        capacites = _capacites()
        depart.wait(timeout=20)
        return capacites.appeler("m10_consolider_affaire", ARGS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futur_a = pool.submit(appeler)
        futur_b = pool.submit(appeler)
        depart.wait(timeout=20)
        resultats, erreurs = [], []
        # Les exceptions des workers sont extraites dans le thread du test afin qu'elles
        # restent observables et ne soient pas transformées en résultats métier.
        for futur in (futur_a, futur_b):
            try:
                resultats.append(futur.result(timeout=40))
            except EcritureConcurrente as exc:
                erreurs.append(exc)
        return resultats, erreurs


def test_sans_verrou_les_deux_snapshots_vides_font_echouer_un_appel_public(monkeypatch):
    _semer_wct_fictif()
    barriere_lectures = threading.Barrier(2)
    compteur = 0
    mutex = threading.Lock()
    lire = m10._REGISTRE_AFFAIRES.lire

    def lire_apres_barriere():
        nonlocal compteur
        lignes = lire()
        if not lignes:
            with mutex:
                compteur += 1
                attendre = compteur <= 2
            if attendre:
                barriere_lectures.wait(timeout=20)
        return lignes

    monkeypatch.setattr(m10._REGISTRE_AFFAIRES, "lire", lire_apres_barriere)
    monkeypatch.setattr(m10, "verrou_consultatif", lambda *_args, **_kwargs: None)
    resultats, erreurs = _deux_appels_publics_simultanes()
    faits = [x for x in m10._REGISTRE_AFFAIRES.lire() if x.get("cle_consolidation") == "LEAD-RACE-FICTIF:2026-09-15"]

    assert len(erreurs) == 1 and isinstance(erreurs[0], EcritureConcurrente), erreurs
    assert len(resultats) == 1 and resultats[0]["ok"] is True, resultats
    assert len(faits) == 1


def test_verrou_rend_deux_appels_publics_concurrents_idempotents():
    _semer_wct_fictif()
    resultats, erreurs = _deux_appels_publics_simultanes()
    faits = [x for x in m10._REGISTRE_AFFAIRES.lire() if x.get("cle_consolidation") == "LEAD-RACE-FICTIF:2026-09-15"]

    assert erreurs == []
    assert len(resultats) == 2 and all(x["ok"] for x in resultats), resultats
    valeurs = [x["resultat"] for x in resultats]
    assert sorted(x["ecrit"] for x in valeurs) == [False, True], valeurs
    assert len(faits) == 1
