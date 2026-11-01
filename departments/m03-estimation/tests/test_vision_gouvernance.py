"""Gouvernance des mesures de vision (M3.3, M3.5) : un candidat n'est jamais une mesure. Données fictives."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import _commun_vision as cv  # noqa: E402
from m3_estimation import vision_contrat, vision_doubles, vision_gouvernance  # noqa: E402

FICTIF = True
LE = "2026-10-02T10:00:00-04:00"


def _politique(**plus):
    brut = {
        "seuil_confiance": "0.80",
        "tolerance_absolue": "0.05",
        "tolerance_relative": "0.10",
        "declaree_par": "proprio",
        "declaree_le": LE,
    }
    brut.update(plus)
    politique, verdict = vision_gouvernance.lire_politique(brut)
    assert verdict is None, verdict
    return politique


def _candidat(confiance="0.90", photo=None, **detection):
    detecteur = vision_doubles.DetecteurScripte({"synth-1": [cv.detection(confiance=confiance, **detection)]})
    sortie, verdict = vision_contrat.executer(
        photo or cv.photo(), detecteur, ["objet_test"], politique_validee=False, modeles_qualifies=frozenset()
    )
    assert verdict is None
    return sortie["candidats"][0]  # surface 0,5 m2


def _reference(valeur="0.5", **plus):
    r = {
        "reference_id": "mesure-manuelle-7",
        "source": "mesure_manuelle",
        "valeur": valeur,
        "unite": "m2",
        "mesure_par": "estimateur.fictif",
        "mesure_le": LE,
    }
    r.update(plus)
    return r


def _humain(decision="valider", **plus):
    v = {"valide_par": "proprio", "valide_le": LE, "approbation_ref": "appr-1", "decision": decision}
    v.update(plus)
    return v


# ------------------------------------------------------------------------------------------ la politique est déclarée
def test_sans_politique_declaree_rien_ne_se_valide_et_le_verdict_dit_quoi_declarer():
    for brut in (
        None,
        {},
        "texte",
        {
            "seuil_confiance": None,
            "tolerance_absolue": None,
            "tolerance_relative": None,
            "declaree_par": None,
            "declaree_le": None,
        },
    ):
        politique, verdict = vision_gouvernance.lire_politique(brut)
        assert politique is None and verdict["code"] == "REJ-VISION-POLITIQUE-ABSENTE"
        assert "seuil_confiance" in verdict["detail"] and "tolerance" in verdict["detail"]


@pytest.mark.parametrize(
    "modif",
    [
        {"seuil_confiance": "0"},
        {"seuil_confiance": "1.01"},
        {"seuil_confiance": 0.8},
        {"seuil_confiance": "-0.1"},
        {"tolerance_absolue": "0"},
        {"tolerance_relative": "0"},
        {"tolerance_relative": "1.5"},
        {"tolerance_absolue": None, "tolerance_relative": None},
        {"declaree_par": ""},
        {"declaree_par": "a b"},
        {"declaree_le": "hier"},
        {"declaree_le": "2026-10-02T10:00:00"},
        {"intrus": 1},
    ],
)
def test_politique_invalide_refusee(modif):
    brut = {
        "seuil_confiance": "0.80",
        "tolerance_absolue": "0.05",
        "tolerance_relative": "0.10",
        "declaree_par": "proprio",
        "declaree_le": LE,
    }
    brut.update(modif)
    politique, verdict = vision_gouvernance.lire_politique(brut)
    assert politique is None and verdict["code"] == "REJ-VISION-POLITIQUE-ABSENTE"


def test_une_seule_tolerance_suffit_et_la_politique_a_une_empreinte():
    politique = _politique(tolerance_relative=None)
    assert politique["tolerance_relative"] is None and len(politique["empreinte"]) == 64


# ------------------------------------------------------------------------------------------ évaluation, sans décision
def test_sous_le_seuil_de_confiance_le_candidat_est_rejete_et_rien_n_est_retenu():
    e = vision_gouvernance.evaluer(_candidat("0.79"), _politique())
    assert e["statut"] == "rejetee_confiance" and e["valeur_retenue"] is None and e["utilisable_comme_mesure"] is False


def test_au_seuil_exactement_le_candidat_reste_candidat_jamais_mesure():
    e = vision_gouvernance.evaluer(_candidat("0.80"), _politique())
    assert e["statut"] == "candidate" and e["valeur_retenue"] is None and e["utilisable_comme_mesure"] is False


def test_sans_echelle_un_candidat_n_est_pas_une_mesure_et_ne_se_valide_pas():
    c = _candidat(photo=cv.photo(sans_echelle=True))
    assert vision_gouvernance.evaluer(c, _politique())["statut"] == "sans_echelle"
    decision, verdict = vision_gouvernance.decider_par_reference(c, _politique(), _reference("0.5"))
    assert decision is None and verdict["code"] == "REJ-VISION-DECISION-INVALIDE"
    decision, verdict = vision_gouvernance.decider_par_humain(c, _politique(), _humain())
    assert decision is None and verdict["code"] == "REJ-VISION-DECISION-INVALIDE"


def test_un_candidat_sous_le_seuil_ne_se_valide_pas_meme_avec_une_reference_concordante():
    c = _candidat("0.50")
    decision, verdict = vision_gouvernance.decider_par_reference(c, _politique(), _reference("0.5"))
    assert decision is None and verdict["code"] == "REJ-VISION-DECISION-INVALIDE"
    _, verdict = vision_gouvernance.decider_par_humain(c, _politique(), _humain())
    assert verdict["code"] == "REJ-VISION-DECISION-INVALIDE"


# ------------------------------------------------------------------------------------------ voie : mesure de référence
def test_dans_la_tolerance_declaree_le_candidat_est_valide_par_la_reference():
    c = _candidat()
    decision, verdict = vision_gouvernance.decider_par_reference(c, _politique(), _reference("0.52"))
    assert verdict is None and decision["statut"] == "validee_par_reference"
    assert decision["valeur_retenue"] == c["valeur"] == "0.5000" and decision["ecart"] == "0.0200"
    assert decision["utilisable_comme_mesure"] is True and decision["origine_valeur"] == "vision_validee_par_reference"
    assert decision["incertitude_emploi"] == "0.0500"  # la plus petite des tolérances : min(0,05 ; 0,10 x 0,52 = 0,052)
    assert decision["reference"]["reference_id"] == "mesure-manuelle-7" and "non_verite" in decision


def test_a_la_limite_de_la_tolerance_le_candidat_est_valide_au_dela_il_est_rejete():
    politique = _politique(tolerance_relative=None)  # tolérance absolue 0,05
    ok, _ = vision_gouvernance.decider_par_reference(_candidat(), politique, _reference("0.55"))
    assert ok["statut"] == "validee_par_reference"
    ko, _ = vision_gouvernance.decider_par_reference(_candidat(), politique, _reference("0.5501"))
    assert ko["statut"] == "rejetee_ecart_reference" and ko["tolerances_manquees"] == ["tolerance_absolue"]
    assert ko["valeur_retenue"] is None and ko["utilisable_comme_mesure"] is False


def test_toutes_les_tolerances_declarees_doivent_tenir():
    politique = _politique(tolerance_absolue="1", tolerance_relative="0.01")
    ko, _ = vision_gouvernance.decider_par_reference(_candidat(), politique, _reference("0.52"))
    assert ko["statut"] == "rejetee_ecart_reference" and ko["tolerances_manquees"] == ["tolerance_relative"]


@pytest.mark.parametrize(
    "modif",
    [
        {"valeur": "0"},
        {"valeur": 0.5},
        {"valeur": "-1"},
        {"unite": "m"},
        {"source": "inventee"},
        {"reference_id": "a b"},
        {"mesure_par": ""},
        {"mesure_le": "hier"},
        {"intrus": 1},
        {"incertitude_absolue": "x"},
    ],
)
def test_reference_mal_formee_refusee(modif):
    ref = _reference()
    ref.update(modif)
    _, verdict = vision_gouvernance.decider_par_reference(_candidat(), _politique(), ref)
    assert verdict["code"] == "REJ-VISION-DECISION-INVALIDE"


def test_reference_incomplete_refusee():
    ref = _reference()
    del ref["mesure_par"]
    _, verdict = vision_gouvernance.decider_par_reference(_candidat(), _politique(), ref)
    assert verdict["code"] == "REJ-VISION-DECISION-INVALIDE"
    assert (
        vision_gouvernance.decider_par_reference(_candidat(), _politique(), None)[1]["code"]
        == "REJ-VISION-DECISION-INVALIDE"
    )


# ------------------------------------------------------------------------------------------ voie : personne
def test_une_personne_peut_valider_refuser_ou_corriger():
    c = _candidat()
    valide, _ = vision_gouvernance.decider_par_humain(c, _politique(), _humain())
    assert valide["statut"] == "validee_par_humain" and valide["valeur_retenue"] == "0.5000"
    assert (
        valide["origine_valeur"] == "vision_validee_par_humain"
        and valide["incertitude_emploi"] == c["incertitude"]["absolue"]
    )
    assert valide["humain"] == {"valide_par": "proprio", "valide_le": LE, "approbation_ref": "appr-1"}

    refuse, _ = vision_gouvernance.decider_par_humain(c, _politique(), _humain("refuser"))
    assert refuse["statut"] == "rejetee_par_humain" and refuse["valeur_retenue"] is None
    assert refuse["utilisable_comme_mesure"] is False

    corrige, _ = vision_gouvernance.decider_par_humain(c, _politique(), _humain(valeur_corrigee="0.62"))
    assert corrige["valeur_retenue"] == "0.6200" and corrige["origine_valeur"] == "humain_corrige"
    assert corrige["incertitude_emploi"] is None  # la vision n'a plus de part dans cette valeur


@pytest.mark.parametrize(
    "modif",
    [
        {"decision": "peut-etre"},
        {"valide_par": ""},
        {"valide_le": "hier"},
        {"approbation_ref": "a b"},
        {"intrus": 1},
        {"valeur_corrigee": "0"},
        {"valeur_corrigee": 0.6},
        {"decision": "refuser", "valeur_corrigee": "0.6"},
    ],
)
def test_validation_humaine_mal_formee_refusee(modif):
    _, verdict = vision_gouvernance.decider_par_humain(_candidat(), _politique(), _humain(**modif))
    assert verdict["code"] == "REJ-VISION-DECISION-INVALIDE"


# ------------------------------------------------------------------------------------------ intégrité
def test_un_candidat_retouche_est_refuse_meme_si_sa_valeur_semble_meilleure():
    c = _candidat()
    falsifie = copy.deepcopy(c)
    falsifie["valeur"] = "500.0000"
    for decider, arg in (
        (vision_gouvernance.decider_par_reference, _reference("500")),
        (vision_gouvernance.decider_par_humain, _humain()),
    ):
        decision, verdict = decider(falsifie, _politique(), arg)
        assert decision is None and verdict["code"] == "REJ-VISION-CANDIDAT-ALTERE"
    falsifie = copy.deepcopy(c)
    falsifie["confiance"] = "1.0000"  # gonfler la confiance pour passer le seuil
    assert (
        vision_gouvernance.decider_par_humain(falsifie, _politique(), _humain())[1]["code"]
        == "REJ-VISION-CANDIDAT-ALTERE"
    )


def test_une_decision_est_deterministe_et_a_une_empreinte_stable():
    a, _ = vision_gouvernance.decider_par_reference(_candidat(), _politique(), _reference("0.52"))
    b, _ = vision_gouvernance.decider_par_reference(_candidat(), _politique(), _reference("0.52"))
    c, _ = vision_gouvernance.decider_par_reference(_candidat(), _politique(), _reference("0.53"))
    assert a == b and a["empreinte"] != c["empreinte"]
