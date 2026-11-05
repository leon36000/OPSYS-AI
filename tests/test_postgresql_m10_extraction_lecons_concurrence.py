"""Deux extractions N2 simultanées ne doublent pas une leçon candidate."""

from __future__ import annotations

import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from m10_memoire import apprentissage_marketing, soi_graphe
from pg_parite import base_pg, serveur_pg  # noqa: F401

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.mnemo.lecons import Ecart, cote
from opsys.stockage.maillons import EcritureConcurrente

RACINE = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _base_pg_m10(base_pg, monkeypatch):  # noqa: F811 - fixture PostgreSQL imported above
    moteur = importlib.import_module("opsys.stockage.moteur")
    stockage.liberer()
    monkeypatch.setenv(stockage.ENV_URL, base_pg)
    monkeypatch.setattr(moteur, "url_base", lambda: base_pg)
    monkeypatch.setattr(stockage, "url_base", lambda: base_pg)
    yield
    stockage.liberer()


def _ecarts_fictifs():
    selection, nb_test, nb_train = [], 0, 0
    for i in range(100):
        chantier = f"CHANTIER-FICTIF-{i:03d}"
        if cote(chantier) == "test":
            if nb_test == 2:
                continue
            nb_test += 1
        else:
            if nb_train == 4:
                continue
            nb_train += 1
        selection.append(Ecart(chantier, "MATERIAU-FICTIF", Decimal("10"), Decimal("12"), f"{i:064x}",
                               "2026-09-15T12:00:00+00:00", "pi"))
        if nb_test == 2 and nb_train == 4:
            return selection
    raise AssertionError("la cohorte fictive devrait satisfaire l'échantillon déclaré")


def _deux_extractions():
    depart = threading.Barrier(3)

    def appeler():
        capacites = Capacites(
            charger_departements(RACINE / "departments"),
            stockage.transaction,
            filtre={"m10-memoire"},
            memoire=False,
        )
        depart.wait(timeout=20)
        return capacites.appeler("m10_extraire_lecons", {})

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(appeler), pool.submit(appeler)
        depart.wait(timeout=20)
        resultats, erreurs = [], []
        for futur in (a, b):
            try:
                resultats.append(futur.result(timeout=40))
            except EcritureConcurrente as exc:
                erreurs.append(exc)
        return resultats, erreurs


def _installer_ecarts(monkeypatch):
    ecarts = _ecarts_fictifs()
    monkeypatch.setattr(soi_graphe, "_ecarts", lambda: (ecarts, []))
    monkeypatch.setattr(soi_graphe, "_refus_recurrents", lambda: [])
    monkeypatch.setattr(soi_graphe.soi, "rejets_par_dimension", lambda _registre: [])
    monkeypatch.setattr(apprentissage_marketing, "groupes_pour_lecons", lambda _faits: [])


def test_sans_verrou_etat_vide_concurrent_provoque_un_conflit_append(monkeypatch):
    _installer_ecarts(monkeypatch)
    barriere = threading.Barrier(2)
    appels_etat = 0
    mutex = threading.Lock()
    etat = soi_graphe.lecons.etat

    def etat_barriere(registre):
        nonlocal appels_etat
        courant = etat(registre)
        if not courant.lecons:
            with mutex:
                appels_etat += 1
                attendre = appels_etat <= 2
            if attendre:
                barriere.wait(timeout=20)
        return courant

    monkeypatch.setattr(soi_graphe.lecons, "etat", etat_barriere)
    monkeypatch.setattr(soi_graphe, "verrou_consultatif", lambda *_args, **_kwargs: None)
    resultats, erreurs = _deux_extractions()
    propositions = [x for x in soi_graphe.registres.lecons().lire()
                    if x.get("type_entree") == soi_graphe.lecons.TYPE_PROPOSEE]

    assert len(erreurs) == 1 and isinstance(erreurs[0], EcritureConcurrente), erreurs
    assert len(resultats) == 1 and resultats[0]["ok"] is True, resultats
    assert len(propositions) == 1


def test_verrou_extraction_rend_les_rejeux_concurrents_idempotents(monkeypatch):
    _installer_ecarts(monkeypatch)
    resultats, erreurs = _deux_extractions()
    propositions = [x for x in soi_graphe.registres.lecons().lire()
                    if x.get("type_entree") == soi_graphe.lecons.TYPE_PROPOSEE]

    assert erreurs == []
    assert len(resultats) == 2 and all(x["ok"] for x in resultats), resultats
    assert sorted(x["resultat"]["proposees"] != [] for x in resultats) == [False, True], resultats
    assert len(propositions) == 1
