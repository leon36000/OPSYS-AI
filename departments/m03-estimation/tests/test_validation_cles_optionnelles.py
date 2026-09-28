"""PLAN T2.2 — clés OPTIONNELLES du LeadQualifie (``source``, ``utm``, ``campagne``) côté M3.

M2 accepte ces trois clés si elles sont fournies. M3 doit les traiter à l'identique : absentes,
ni erreur ni valeur par défaut ; présentes, même forme exigée que chez M2 ; toute autre clé reste
refusée. M3 ne s'en sert pas pour estimer : l'accusé de validation ne les porte pas. Les copies
de M3 sont épinglées contre la SOURCE de M2 par AST (décision #109 : aucun import inter-modules).
"""

import ast
import sys
from pathlib import Path

import pytest

_RACINE_M3 = Path(__file__).resolve().parents[1]
_SRC_M3 = _RACINE_M3 / "src"
if str(_SRC_M3) not in sys.path:
    sys.path.insert(0, str(_SRC_M3))

_SOURCE_M2 = (
    Path(__file__).resolve().parents[3]
    / "departments" / "m02-revenue-crm" / "src" / "m2_revenue_crm" / "contrats.py"
)

from m3_estimation import contrats
from m3_estimation import validation

_CLES_ACCUSE = {"lead_id", "type_travaux", "ville", "empreinte_marqueur_m2", "nombre_photos"}


def _constante_m2(nom):
    """Tuple littéral de chaînes affecté à ``nom`` au niveau module de la source de M2."""
    arbre = ast.parse(_SOURCE_M2.read_text(encoding="utf-8"), filename=str(_SOURCE_M2))
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and any(
            isinstance(cible, ast.Name) and cible.id == nom for cible in noeud.targets
        ):
            valeur = ast.literal_eval(noeud.value)
            assert isinstance(valeur, tuple) and all(isinstance(v, str) for v in valeur), (
                f"{nom} de M2 n'est pas un tuple littéral de chaînes : {valeur!r}"
            )
            return list(valeur)
    pytest.fail(f"constante {nom} introuvable dans {_SOURCE_M2} — fail-closed")


def _entrees(**optionnels):
    contrat = {
        "lead_id": "lead-0001",
        "conversation_id": "conv-0001",
        "type_travaux": "renovation_totale",
        "ville": "Laval",
        "canal": "formulaire",
        "contact": {"nom": "Tremblay"},
        "urgence_declaree": False,
    }
    contrat.update(optionnels)
    marqueur = {
        "readiness_ok": True,
        "lead_id": "lead-0001",
        "hash_tete_registre": "f" * 64,
        "horodatage": "2026-09-28T10:30:00-04:00",
        "empreinte": "0" * 64,
    }
    photos = [{"id_photo": "ph-0001", "horodatage": "2026-09-28T10:31:00-04:00"}]
    return contrat, marqueur, photos


def test_champs_contrat_optionnels_copie_m2_ne_derive_pas():
    assert list(contrats.CHAMPS_CONTRAT_OPTIONNELS) == _constante_m2("CHAMPS_CONTRAT_OPTIONNELS")


def test_champs_utm_copie_cles_utm_de_m2_ne_derive_pas():
    assert list(contrats.CHAMPS_UTM) == _constante_m2("CLES_UTM")


def test_les_trois_cles_optionnelles_fournies_sont_acceptees_et_absentes_de_l_accuse():
    accuse, verdict = validation.valider_entrees(*_entrees(
        source="facebook",
        campagne="printemps-gouttieres",
        utm={"utm_source": "facebook", "utm_medium": "cpc", "utm_campaign": "printemps",
             "utm_content": "video-1"},
    ))
    assert verdict is None
    assert set(accuse) == _CLES_ACCUSE


@pytest.mark.parametrize("cle, valeur", [
    ("source", "google"),
    ("campagne", "automne"),
    ("utm", {"utm_source": "google"}),
])
def test_chaque_cle_optionnelle_seule_est_acceptee(cle, valeur):
    accuse, verdict = validation.valider_entrees(*_entrees(**{cle: valeur}))
    assert verdict is None
    assert set(accuse) == _CLES_ACCUSE


def test_absence_des_cles_optionnelles_n_est_pas_une_faute():
    accuse, verdict = validation.valider_entrees(*_entrees())
    assert verdict is None
    assert accuse["lead_id"] == "lead-0001"


@pytest.mark.parametrize("cle, valeur", [
    ("source", ""),
    ("source", 3),
    ("campagne", None),
    ("campagne", ""),
    ("utm", {}),
    ("utm", "utm_source=facebook"),
    ("utm", {"utm_source": ""}),
    ("utm", {"utm_source": 1}),
    ("utm", {"utm_term": "gouttieres"}),
], ids=["source-vide", "source-entier", "campagne-none", "campagne-vide", "utm-vide",
        "utm-chaine", "utm-valeur-vide", "utm-valeur-entier", "utm-sous-cle-inconnue"])
def test_forme_invalide_d_une_cle_optionnelle_fournie_est_refusee(cle, valeur):
    accuse, verdict = validation.valider_entrees(*_entrees(**{cle: valeur}))
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert repr(cle) in verdict["detail"]


def test_une_cle_inconnue_reste_refusee_a_cote_des_optionnelles():
    accuse, verdict = validation.valider_entrees(*_entrees(source="google", utm_source="google"))
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "inconnues=['utm_source']" in verdict["detail"]


def test_une_cle_gelee_manquante_n_est_pas_compensee_par_les_optionnelles():
    contrat, marqueur, photos = _entrees(source="google", utm={"utm_source": "google"},
                                         campagne="hiver")
    del contrat["ville"]
    accuse, verdict = validation.valider_entrees(contrat, marqueur, photos)
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "manquantes=['ville']" in verdict["detail"]
