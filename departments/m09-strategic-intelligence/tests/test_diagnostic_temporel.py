"""Diagnostic temporel interne : dossiers réellement composés, données fictives."""
import hashlib
import importlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from m9_strategic_intelligence import dossier_direction, registre

REFERENCE = "2026-10-18T12:00:00Z"


def _module():
    name = "m9_strategic_intelligence.diagnostic_temporel"
    assert importlib.util.find_spec(name) is not None, "diagnostic temporel interne absent"
    module = importlib.import_module(name)
    racine = Path(__file__).resolve().parents[3]
    assert Path(module.__file__).resolve().is_relative_to(racine)
    assert Path(dossier_direction.__file__).resolve().is_relative_to(racine)
    return module


def _dossier(*horodatages):
    chaine = registre.RegistreSnapshots()
    for index, horodatage in enumerate(horodatages or ["2026-10-17T12:00:00Z"]):
        chaine.ajouter({
            "module_source": "M5-fictif", "horodatage": horodatage,
            "valeurs": {"fictif": "true", "chantier": "WCT-temporel-fictif", "cout_declare": str(index + 1)},
        })
    assert chaine.valider_chaine() == (True, "")
    return dossier_direction.construire_dossier(
        chaine, "Quel coût déclaré du chantier fictif est reçu ?", ["M5-fictif", "M6-fictif"],
        budget_caracteres=6000,
    )


def _diagnostic(dossier, reference=REFERENCE, budget=6000):
    return _module().diagnostiquer_dossier(dossier, reference, budget_caracteres=budget)


def test_presence_du_diagnostic_dans_le_checkout_isole():
    assert callable(_module().diagnostiquer_dossier)


@pytest.mark.parametrize(("stamp", "ecart", "statut"), [
    ("2026-10-17T12:00:00Z", 86400, "ANTERIEURE_REFERENCE"),
    ("2026-10-18T12:00:00+00:00", 0, "A_REFERENCE"),
    ("2026-10-19T12:00:00Z", -86400, "OBSERVATION_FUTURE"),
    ("2026-10-19T08:00:00-04:00", -86400, "OBSERVATION_FUTURE"),
    ("2026-10-18T12:00:00.000001Z", -0.000001, "OBSERVATION_FUTURE"),
])
def test_age_signe_sans_verdict_de_fraicheur(stamp, ecart, statut):
    dossier = _dossier(stamp)
    avant = deepcopy(dossier)
    resultat = _diagnostic(dossier)
    assert resultat["type"] == "DIAGNOSTIC_TEMPOREL_DOSSIER"
    assert resultat["dossier_id"] == dossier["dossier_id"]
    assert resultat["etat_id"] == dossier["etat_id"]
    assert resultat["reference_source"] == REFERENCE
    assert resultat["reference_utc"] == "2026-10-18T12:00:00+00:00"
    assert resultat["actualite_metier"] == "NON_EVALUEE"
    assert resultat["modules_manquants"] == ["M6-fictif"]
    assert resultat["observations"] == [{
        "module_source": "M5-fictif", "index": 0,
        "hash_maillon": dossier["preuves"][0]["hash_maillon"],
        "horodatage_source": stamp, "ecart_secondes": ecart, "diagnostic": statut,
    }]
    assert resultat["limites"]
    sans_id = {k: v for k, v in resultat.items() if k != "diagnostic_id"}
    attendu = hashlib.sha256(json.dumps(
        sans_id, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    assert resultat["diagnostic_id"] == attendu
    assert dossier == avant and dossier["actualite"] == "NON_EVALUEE"


def test_arrivee_hors_ordre_garde_observation_m9_et_son_age_futur():
    dossier = _dossier("2026-10-19T12:00:00Z", "2026-10-17T12:00:00Z")
    observation = _diagnostic(dossier)["observations"][0]
    assert observation["index"] == 0 and observation["ecart_secondes"] == -86400
    assert observation["diagnostic"] == "OBSERVATION_FUTURE"


def test_reference_changee_change_diagnostic_sans_reselectionner():
    dossier = _dossier("2026-10-19T12:00:00Z")
    futur = _diagnostic(dossier)
    present = _diagnostic(dossier, "2026-10-19T12:00:00Z")
    assert futur["diagnostic_id"] != present["diagnostic_id"]
    assert futur["dossier_id"] == present["dossier_id"] == dossier["dossier_id"]
    assert present["observations"][0]["ecart_secondes"] == 0


def test_egalite_d_instants_et_representation_reference_conservee():
    dossier = _dossier()
    a = _diagnostic(dossier)
    b = _diagnostic(dossier, "2026-10-18T08:00:00-04:00")
    assert a["observations"] == b["observations"]
    assert a["reference_utc"] == b["reference_utc"]
    assert a["reference_source"] != b["reference_source"]


@pytest.mark.parametrize("reference", [
    None, True, 3, "", "2026-10-18", "2026-10-18T12:00:00", "hier", " 2026-10-18T12:00:00Z",
])
def test_reference_absente_ou_incomparable_refusee(reference):
    with pytest.raises(ValueError, match="REJ-DIAGNOSTIC-REFERENCE"):
        _diagnostic(_dossier(), reference)


def test_observation_historique_sans_fuseau_reste_historique_mais_non_comparable():
    dossier = _dossier("2026-10-17T12:00:00")
    avant = deepcopy(dossier)
    with pytest.raises(ValueError, match="REJ-DIAGNOSTIC-OBSERVATION"):
        _diagnostic(dossier)
    assert dossier == avant


def test_identifiants_conserves_sur_valeurs_modifiees_ne_suffisent_pas():
    dossier = _dossier()
    dossier["faits_selectionnes"]["M5-fictif"]["valeurs"]["cout_declare"] = "2000"
    dossier["preuves"][0]["valeurs"]["cout_declare"] = "2000"
    with pytest.raises(ValueError, match="REJ-DIAGNOSTIC-DOSSIER"):
        _diagnostic(dossier)


def test_empreinte_externe_recalculee_ne_repare_pas_etat_perime():
    dossier = _dossier()
    dossier["faits_selectionnes"]["M5-fictif"]["valeurs"]["cout_declare"] = "2000"
    dossier["preuves"][0]["valeurs"]["cout_declare"] = "2000"
    dossier["dossier_id"] = hashlib.sha256(json.dumps(
        {k: v for k, v in dossier.items() if k != "dossier_id"},
        sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    with pytest.raises(ValueError, match="REJ-DIAGNOSTIC-ETAT"):
        _diagnostic(dossier)


def test_resultat_detache_et_stable_sans_lecture_durable():
    dossier = _dossier()
    resultat = _diagnostic(dossier)
    original = deepcopy(resultat)
    dossier["preuves"][0]["valeurs"]["cout_declare"] = "9999"
    dossier["modules_manquants"].clear()
    assert resultat == original


@pytest.mark.parametrize("budget", [True, 0, -1, "6000", 20])
def test_borne_refuse_sans_tronquer_ni_modifier_dossier(budget):
    dossier = _dossier()
    avant = deepcopy(dossier)
    with pytest.raises(ValueError, match="REJ-DIAGNOSTIC-BORNE"):
        _diagnostic(dossier, budget=budget)
    assert dossier == avant


def test_citations_contradictoires_preservees_et_non_arbitrees():
    dossier = _dossier("2026-10-17T12:00:00Z", "2026-10-17T08:00:00-04:00")
    avant = deepcopy(dossier)
    assert len(dossier["contradictions"]) == 1 and len(dossier["preuves"]) == 2
    assert _diagnostic(dossier)["observations"][0]["index"] == 1
    assert dossier == avant


def _recalculer_dossier_id(dossier):
    dossier["dossier_id"] = hashlib.sha256(json.dumps(
        {k: v for k, v in dossier.items() if k != "dossier_id"},
        sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()


def test_refuse_contradiction_orpheline_meme_si_les_empreintes_restant_coherentes():
    dossier = _dossier("2026-10-17T12:00:00Z", "2026-10-17T08:00:00-04:00")
    assert dossier["faits_selectionnes"]["M5-fictif"]["index"] == 1
    dossier["preuves"] = [p for p in dossier["preuves"] if p["index"] != 0]
    _recalculer_dossier_id(dossier)
    with pytest.raises(ValueError, match="REJ-DIAGNOSTIC-DOSSIER"):
        _diagnostic(dossier)


@pytest.mark.parametrize("cas", ["absents", "texte", "booleen", "manquants_vides", "attendus_invalides"])
def test_refuse_metadonnees_modules_malformees_ou_incoherentes(cas):
    dossier = _dossier()
    if cas == "absents":
        dossier.pop("modules_manquants")
    elif cas == "texte":
        dossier["modules_manquants"] = "M6-fictif"
    elif cas == "booleen":
        dossier["modules_manquants"] = [False]
    elif cas == "manquants_vides":
        dossier["modules_manquants"] = []
    else:
        dossier["modules_attendus"] = [False]
    _recalculer_dossier_id(dossier)
    with pytest.raises(ValueError, match="REJ-DIAGNOSTIC-DOSSIER"):
        _diagnostic(dossier)
