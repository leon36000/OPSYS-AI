"""PLAN T4.13 : l'adaptateur « saisie manuelle » du port `FournisseurMeteo`, sans réseau ni horloge.

La saisie se cite (qui, d'où, à quelle heure) ; une mesure absente vaut `null`, jamais zéro ; les nombres JSON décimaux
sont lus comme des décimaux EXACTS. Données fictives (`fictif: true`).
"""

from __future__ import annotations

import ast
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from m4_field_ops import meteo, meteo_manuelle

FICTIF = True
_SRC = Path(meteo_manuelle.__file__).resolve()
EMISE_LE = "2026-10-04T18:00:00-04:00"
LIEU = {"latitude_microdegres": 45_800_000, "longitude_microdegres": -73_400_000}


def _saisie(**surcharges):
    saisie = {
        "saisi_par": "nathan",
        "source": "bulletin fictif d'Environnement Canada, Lanaudière",
        "emise_le": EMISE_LE,
        "points": [
            {
                "heure": "2026-10-05T09:00",
                "vent_kmh": 62,
                "rafales_kmh": 80.5,
                "temperature_c": 7,
                "precipitation_mm_h": 0.4,
                "probabilite_precipitation_pct": 30,
                "verglas": False,
            },
            {"heure": "2026-10-05T10:00", "vent_kmh": 58},
        ],
    }
    saisie.update(surcharges)
    return saisie


def _creer(saisie):
    fournisseur, verdict = meteo_manuelle.creer_fournisseur_manuel(saisie)
    assert verdict is None, verdict
    return fournisseur


@pytest.fixture(autouse=True)
def _sans_reseau(sockets_bloques):
    """Ce module n'ouvre jamais un socket."""


def test_une_saisie_valide_donne_un_fournisseur_du_port():
    fournisseur = _creer(_saisie())
    assert isinstance(fournisseur, meteo.FournisseurMeteo)
    assert fournisseur.descripteur() == {
        "fournisseur": "saisie_manuelle",
        "saisi_par": "nathan",
        "reference": "bulletin fictif d'Environnement Canada, Lanaudière",
    }
    assert all(isinstance(v, str) and v for v in fournisseur.descripteur().values())


def test_la_prevision_cite_qui_d_ou_et_a_quelle_heure_et_n_a_aucune_attribution():
    previsions, verdict = _creer(_saisie()).previsions(LIEU, "2026-10-05", "2026-10-05")
    assert verdict is None
    assert previsions["citation"] == {
        "source": "saisie_manuelle",
        "emise_le": EMISE_LE,
        "heure_type": "heure_d_emission_saisie",
        "saisi_par": "nathan",
        "reference": "bulletin fictif d'Environnement Canada, Lanaudière",
        "attribution": None,
    }
    assert meteo.valider_previsions(previsions) is None


def test_les_nombres_decimaux_sont_lus_en_decimaux_exacts_jamais_en_flottants():
    previsions, _ = _creer(_saisie()).previsions(LIEU, "2026-10-05", "2026-10-05")
    premier = previsions["points"][0]
    assert premier["rafales_kmh"] == Decimal("80.5") and isinstance(premier["rafales_kmh"], Decimal)
    assert premier["precipitation_mm_h"] == Decimal("0.4")
    assert premier["vent_kmh"] == 62 and isinstance(premier["vent_kmh"], Decimal)
    assert premier["verglas"] is False


def test_une_mesure_absente_n_est_pas_un_zero():
    previsions, _ = _creer(_saisie()).previsions(LIEU, "2026-10-05", "2026-10-05")
    second = previsions["points"][1]
    assert second["vent_kmh"] == 58 and second["temperature_c"] is None and second["verglas"] is None


def test_la_saisie_ne_depend_ni_du_lieu_ni_des_dates_et_ne_garde_rien():
    fournisseur = _creer(_saisie())
    un, _ = fournisseur.previsions(LIEU, "2026-10-05", "2026-10-05")
    autre, _ = fournisseur.previsions(
        {"latitude_microdegres": 0, "longitude_microdegres": 0}, "2030-01-01", "2030-01-02"
    )
    assert un == autre
    un["points"][0]["vent_kmh"] = 999  # modifier le résultat ne change pas le fournisseur
    assert fournisseur.previsions(LIEU, "2026-10-05", "2026-10-05")[0]["points"][0]["vent_kmh"] == 62


def test_la_saisie_n_est_pas_modifiee():
    saisie = _saisie()
    avant = copy.deepcopy(saisie)
    _creer(saisie)
    assert saisie == avant


def test_jugee_par_meteo_la_saisie_bloque_un_revetement_sous_vent_fort():
    regles = {
        "seuils": {"vent_kmh": {"validation": 25, "blocage": 40}},
        "sans_objet": ["pluie", "gel", "verglas", "chaleur"],
    }
    saisie = _saisie(points=[{"heure": f"2026-10-05T{h:02d}:00", "vent_kmh": 62} for h in range(8, 18)])
    previsions, _ = _creer(saisie).previsions(LIEU, "2026-10-05", "2026-10-05")
    resultat = meteo.evaluer_creneau(regles, previsions, "2026-10-05", 480, 1020)
    assert resultat["statut"] == meteo.STATUT_BLOQUANT
    assert resultat["prevision"]["citation"]["saisi_par"] == "nathan"


@pytest.mark.parametrize(
    ("saisie", "morceau"),
    [
        (None, "un objet"),
        ([], "un objet"),
        ({"saisi_par": "nathan"}, "un objet"),
        ({**_saisie(), "en_trop": 1}, "un objet"),
        (_saisie(saisi_par=""), "saisi_par"),
        (_saisie(saisi_par="  "), "saisi_par"),
        (_saisie(saisi_par=None), "saisi_par"),
        (_saisie(source=""), "source"),
        (_saisie(source=42), "source"),
        (_saisie(emise_le="hier soir"), "emise_le"),
        (_saisie(emise_le="2026-10-04T18:00:00"), "emise_le"),
        (_saisie(emise_le=None), "emise_le"),
        (_saisie(points="9 h : vent 60"), "points : une liste"),
        (_saisie(points=[]), "au moins un point"),
        (_saisie(points=["9 h"]), "clés permises"),
        (_saisie(points=[{"heure": "2026-10-05T09:30", "vent_kmh": 60}]), "minutes à zéro"),
        (_saisie(points=[{"heure": "2026-10-05T09:00", "humidex": 30}]), "clés permises"),
        (_saisie(points=[{"heure": "2026-10-05T09:00", "vent_kmh": True}]), "nombre entier ou décimal exact"),
        (_saisie(points=[{"heure": "2026-10-05T09:00", "vent_kmh": "60"}]), "nombre entier ou décimal exact"),
        (_saisie(points=[{"heure": "2026-10-05T09:00", "vent_kmh": float("nan")}]), "nombre entier ou décimal exact"),
        (_saisie(points=[{"heure": "2026-10-05T09:00", "vent_kmh": float("inf")}]), "nombre entier ou décimal exact"),
        (_saisie(points=[{"heure": "2026-10-05T09:00", "verglas": "oui"}]), "true, false ou null"),
        (_saisie(points=[{"heure": "2026-10-05T09:00"}, {"heure": "2026-10-05T09:00"}]), "heure en double"),
    ],
)
def test_une_saisie_mal_formee_est_refusee_avec_la_raison_et_ne_cree_rien(saisie, morceau):
    fournisseur, verdict = meteo_manuelle.creer_fournisseur_manuel(saisie)
    assert fournisseur is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE" and "prévision saisie" in verdict["detail"]
    assert morceau in verdict["detail"]


def test_le_module_n_ouvre_aucune_connexion_et_ne_lit_aucune_horloge():
    for noeud in ast.walk(ast.parse(_SRC.read_text(encoding="utf-8"))):
        if isinstance(noeud, ast.Import):
            assert all(a.name not in {"socket", "urllib", "http", "time", "random", "os"} for a in noeud.names)
        if isinstance(noeud, ast.ImportFrom):
            assert (noeud.module or "") not in {"socket", "urllib", "http", "time", "random", "os", "opsys"}
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "monotonic", "urandom"}
    assert json.dumps(_creer(_saisie()).descripteur())  # sérialisable
