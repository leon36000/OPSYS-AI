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

CANDIDAT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def pg(base_pg, monkeypatch):  # noqa: F811 - fixture PostgreSQL importée ci-dessus
    moteur = importlib.import_module("opsys.stockage.moteur")
    stockage.liberer()
    monkeypatch.setenv(stockage.ENV_URL, base_pg)
    monkeypatch.setattr(moteur, "url_base", lambda: base_pg)
    monkeypatch.setattr(stockage, "url_base", lambda: base_pg)
    yield
    stockage.liberer()


def _ecarts(groupe):
    sortie, test, train = [], 0, 0
    for i in range(100):
        chantier = f"FICTIF-{groupe}-{i:03d}"
        if cote(chantier) == "test":
            if test >= 2:
                continue
            test += 1
        else:
            if train >= 4:
                continue
            train += 1
        sortie.append(Ecart(chantier, groupe, Decimal(10), Decimal(12), f"{i + (0 if groupe == 'MAT-A' else 100):064x}",
                            "2026-09-15T12:00:00Z", "pi"))
        if test == 2 and train == 4:
            return sortie
    raise AssertionError("cohorte fictive insuffisante")


def _cap():
    return Capacites(charger_departements(CANDIDAT / "departments"), stockage.transaction,
                     filtre={"m10-memoire"}, memoire=False)


def _setup(monkeypatch):
    monkeypatch.setattr(soi_graphe, "_ecarts", lambda: (_ecarts("MAT-A"), []))
    monkeypatch.setattr(soi_graphe, "_refus_recurrents", lambda: [])
    monkeypatch.setattr(soi_graphe.soi, "rejets_par_dimension", lambda _registre: [])
    monkeypatch.setattr(apprentissage_marketing, "groupes_pour_lecons", lambda _faits: [])
    first = _cap().appeler("m10_extraire_lecons", {})
    assert first["ok"] is True and first["resultat"]["proposees"]
    ident = first["resultat"]["proposees"][0]
    monkeypatch.setattr(
        soi_graphe, "_ecarts",
        lambda: (_ecarts("MAT-A") if threading.current_thread().name == "evaluator" else _ecarts("MAT-B"), []),
    )
    return ident


def test_public_evaluation_et_extraction_concurrentes_preservent_chaine(monkeypatch):
    ident = _setup(monkeypatch)
    depart = threading.Barrier(3)
    evaluation_a_append = threading.Event()
    extraction_tente_verrou = threading.Event()
    extraction_terminee = threading.Event()
    verrou_orig = soi_graphe.verrou_consultatif
    type_maillons = type(stockage.maillons("m10-memoire", "lecons"))
    append_orig = type_maillons.append

    def verrou_ordonne(cnx, nom, *, partage=False):
        if threading.current_thread().name == "extractor":
            # Débloque l'évaluateur avant d'attendre le verrou détenu par son appel.
            extraction_tente_verrou.set()
            evaluation_a_append.set()
        return verrou_orig(cnx, nom, partage=partage)

    def append_ordonne(registre, maillon, *, rang_attendu=None):
        if threading.current_thread().name == "evaluator":
            evaluation_a_append.set()
            # Sans verrou d'extraction, celle-ci doit pouvoir append puis terminer en premier.
            while not extraction_tente_verrou.wait(0.01) and not extraction_terminee.wait(0.01):
                pass
        return append_orig(registre, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(soi_graphe, "verrou_consultatif", verrou_ordonne)
    monkeypatch.setattr(type_maillons, "append", append_ordonne)

    def run(name, tool, args):
        threading.current_thread().name = name
        depart.wait(timeout=20)
        if name == "extractor":
            assert evaluation_a_append.wait(20)
        response = _cap().appeler(tool, args)
        if name == "extractor":
            extraction_terminee.set()
        return response

    with ThreadPoolExecutor(max_workers=2) as pool:
        evaluation = pool.submit(run, "evaluator", "m10_evaluer_lecon", {"lecon_id": ident})
        extraction = pool.submit(run, "extractor", "m10_extraire_lecons", {})
        depart.wait(timeout=20)
        a, b = evaluation.result(timeout=40), extraction.result(timeout=40)

    assert a["ok"] and b["ok"], (a, b)
    assert soi_graphe.registres.lecons().valider_chaine() == (True, "")
