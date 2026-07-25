"""Tests — construction de réponses PROPOSÉES (Brand Core, statut PROPOSE, jamais auto-publiées).

TDD RED capturé : ces tests ont été écrits AVANT l'implémentation de response_builder.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ajout du module src/reputation au sys.path
# ---------------------------------------------------------------------------
_M7 = Path(__file__).resolve().parents[2]
_REPUTATION = _M7 / "src" / "reputation"
for _p in (str(_REPUTATION),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import response_builder  # noqa: E402

# Plage valide du niveau de validation dans la file 0-6
_NIVEAU_VALIDATION_MIN = 0
_NIVEAU_VALIDATION_MAX = 6

# ---------------------------------------------------------------------------
# Données de test
# ---------------------------------------------------------------------------

_BRAND = {
    "name": "OPSYS-AI",
    "tagline": "Systèmes complets d'automatisation d'entreprise par IA",
    "tone": "professionnel, factuel, français d'abord",
    "colors": ["#000000", "#FFFFFF"],
    "langue": "fr",
}

_AVIS_BASE = {"id": "avis-001", "note": 5, "texte": "Excellent service."}


# ---------------------------------------------------------------------------
# Tests — statut PROPOSE invariant (acceptance M7-S009)
# ---------------------------------------------------------------------------

def test_reponse_statut_toujours_propose():
    """La réponse porte toujours approval_status == 'PROPOSE'."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    assert rep["approval_status"] == "PROPOSE"


def test_reponse_statut_propose_pour_litige():
    """Catégorie litige → statut PROPOSE (pas de publication automatique)."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "litige", _BRAND)
    assert rep["approval_status"] == "PROPOSE"


def test_reponse_statut_propose_pour_urgence():
    """Catégorie urgence → statut PROPOSE."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "urgence", _BRAND)
    assert rep["approval_status"] == "PROPOSE"


def test_reponse_statut_propose_pour_neutre():
    """Catégorie neutre → statut PROPOSE."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "neutre", _BRAND)
    assert rep["approval_status"] == "PROPOSE"


# ---------------------------------------------------------------------------
# Tests — structure de la réponse
# ---------------------------------------------------------------------------

def test_reponse_contient_champs_obligatoires():
    """La réponse contient les champs attendus."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    for champ in ("id", "avis_id", "categorie", "texte", "brand_name",
                  "approval_status", "niveau_validation"):
        assert champ in rep, f"Champ manquant : {champ}"


def test_reponse_avis_id_tracable():
    """avis_id correspond à l'identifiant de l'avis source."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    assert rep["avis_id"] == _AVIS_BASE["id"]


def test_reponse_categorie_tracee():
    """La catégorie classifiée est tracée dans la réponse."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "urgence", _BRAND)
    assert rep["categorie"] == "urgence"


def test_reponse_brand_name_present_dans_texte():
    """Le nom de la marque (Brand Core) apparaît dans le texte de la réponse."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    assert _BRAND["name"] in rep["texte"]


def test_reponse_texte_non_vide():
    """Le texte de la réponse n'est pas vide."""
    for cat in ("litige", "urgence", "eloge", "neutre"):
        rep = response_builder.construire_reponse(_AVIS_BASE, cat, _BRAND)
        assert isinstance(rep["texte"], str) and len(rep["texte"]) > 0


def test_reponse_niveau_validation_dans_file():
    """niveau_validation est un int dans [_NIVEAU_VALIDATION_MIN, _NIVEAU_VALIDATION_MAX]."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    assert isinstance(rep["niveau_validation"], int)
    assert _NIVEAU_VALIDATION_MIN <= rep["niveau_validation"] <= _NIVEAU_VALIDATION_MAX


def test_reponse_niveau_validation_personnalisable():
    """On peut surcharger le niveau de validation."""
    rep = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND, niveau_validation=3)
    assert rep["niveau_validation"] == 3


# ---------------------------------------------------------------------------
# Tests — determinisme
# ---------------------------------------------------------------------------

def test_reponse_deterministe():
    """Mêmes paramètres → même réponse (même id, même texte)."""
    rep1 = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    rep2 = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    assert rep1["id"] == rep2["id"]
    assert rep1["texte"] == rep2["texte"]


def test_reponse_id_different_par_categorie():
    """Catégorie différente → id différent (uuid5 dépend de la catégorie)."""
    rep_eloge = response_builder.construire_reponse(_AVIS_BASE, "eloge", _BRAND)
    rep_neutre = response_builder.construire_reponse(_AVIS_BASE, "neutre", _BRAND)
    assert rep_eloge["id"] != rep_neutre["id"]


# ---------------------------------------------------------------------------
# Tests — robustesse / erreurs
# ---------------------------------------------------------------------------

def test_avis_sans_id_leve_valueerror():
    """ValueError si l'avis ne porte pas d'id."""
    with pytest.raises(ValueError, match="id"):
        response_builder.construire_reponse({"note": 5}, "eloge", _BRAND)


def test_categorie_inconnue_leve_valueerror():
    """ValueError si la catégorie est inconnue."""
    with pytest.raises(ValueError, match="[Cc]atégorie"):
        response_builder.construire_reponse(_AVIS_BASE, "inconnu", _BRAND)


def test_brand_sans_name_leve_valueerror():
    """ValueError si brand ne porte pas de 'name'."""
    brand_sans_nom = {"tagline": "x", "tone": "y", "colors": [], "langue": "fr"}
    with pytest.raises(ValueError, match="name"):
        response_builder.construire_reponse(_AVIS_BASE, "eloge", brand_sans_nom)


# ---------------------------------------------------------------------------
# Tests — zero réseau
# ---------------------------------------------------------------------------

def test_response_builder_zero_reseau():
    """response_builder.py n'importe pas urllib ni socket."""
    import ast as _ast

    source = (_REPUTATION / "response_builder.py").read_text(encoding="utf-8")
    tree = _ast.parse(source)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert "urllib" not in alias.name
                assert "socket" not in alias.name
        elif isinstance(node, _ast.ImportFrom):
            module = node.module or ""
            assert "urllib" not in module
            assert "socket" not in module


# ---------------------------------------------------------------------------
# Tests — charger_brand
# ---------------------------------------------------------------------------

def test_charger_brand_retourne_dict():
    """charger_brand() retourne un dict avec les champs Brand Core."""
    brand = response_builder.charger_brand()
    assert isinstance(brand, dict)
    assert "name" in brand
    assert "tone" in brand


def test_charger_brand_fichier_absent_leve_erreur():
    """FileNotFoundError si le profil brand est absent."""
    with pytest.raises(FileNotFoundError):
        response_builder.charger_brand(chemin=Path("/inexistant/profile.yaml"))
