"""Tests de la garde Loi 25 « photos » (PLAN T2.3, `politique_photos.py`) — fail-closed par
défaut : toute forme absente, ambiguë ou non exactement `valide` refuse la collecte."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import politique_photos, verdicts  # noqa: E402


def test_statut_valide_est_lu_correctement():
    assert politique_photos.lire_statut_validation("STATUT_VALIDATION: valide") == "valide"
    assert politique_photos.politique_est_validee("STATUT_VALIDATION: valide") is True
    assert politique_photos.verifier_collecte_photo_autorisee("STATUT_VALIDATION: valide") is None


def test_statut_valide_tolere_labsence_despace_apres_les_deux_points():
    assert politique_photos.politique_est_validee("STATUT_VALIDATION:valide") is True


def test_statut_valide_au_milieu_dun_document_plus_long():
    texte = "> PROPOSITION\n\nSTATUT_VALIDATION: valide\n\n# Politique\n\nContenu quelconque.\n"
    assert politique_photos.politique_est_validee(texte) is True


def test_statut_a_linterieur_dune_citation_markdown_nest_pas_reconnu():
    """Le marqueur doit être une ligne EXACTE, jamais préfixée par une citation ('> ') — sinon un
    exemple cité en prose pourrait être confondu avec le vrai statut."""
    texte = "> STATUT_VALIDATION: valide\n\n# Politique\n"
    assert politique_photos.politique_est_validee(texte) is False


@pytest.mark.parametrize(
    "texte",
    [
        "",
        "STATUT_VALIDATION: proposition",
        "STATUT_VALIDATION: VALIDE",  # casse différente : jamais normalisée, refuse
        "statut_validation: valide",  # clé en minuscules : forme non reconnue -> absent
        "un document quelconque sans marqueur du tout",
        "STATUT_VALIDATION: valide-en-attente",  # préfixe seulement, jamais une correspondance exacte
    ],
    ids=["vide", "proposition", "majuscules", "cle_minuscule", "sans_marqueur", "suffixe_partiel"],
)
def test_toute_forme_non_exactement_valide_refuse(texte):
    assert politique_photos.politique_est_validee(texte) is False
    verdict = politique_photos.verifier_collecte_photo_autorisee(texte)
    assert verdict is not None
    assert verdict["code"] == "REJ-PHOTO-POLITIQUE-NON-VALIDEE"
    assert verdicts.est_verdict(verdict["code"])


def test_entree_non_textuelle_refuse_sans_exception():
    for entree in (None, 42, ["valide"], {"statut": "valide"}):
        assert politique_photos.lire_statut_validation(entree) is None
        assert politique_photos.politique_est_validee(entree) is False
        verdict = politique_photos.verifier_collecte_photo_autorisee(entree)
        assert verdict is not None
        assert verdict["code"] == "REJ-PHOTO-POLITIQUE-NON-VALIDEE"


def test_deux_marqueurs_contradictoires_refusent_fail_closed():
    """Deux occurrences du marqueur (ex. un exemple cité PUIS le vrai statut) sont ambiguës :
    fail-closed, jamais un choix arbitraire du premier ou du dernier."""
    texte = "STATUT_VALIDATION: valide\n...\nSTATUT_VALIDATION: proposition"
    assert politique_photos.lire_statut_validation(texte) is None
    assert politique_photos.politique_est_validee(texte) is False


def test_detail_du_verdict_nomme_le_statut_constate():
    verdict = politique_photos.verifier_collecte_photo_autorisee("STATUT_VALIDATION: proposition")
    assert "proposition" in verdict["detail"]


def test_detail_du_verdict_dit_absent_quand_aucun_marqueur():
    verdict = politique_photos.verifier_collecte_photo_autorisee("aucun marqueur ici")
    assert "absent" in verdict["detail"]


def test_code_appartient_au_catalogue_ferme():
    assert "REJ-PHOTO-POLITIQUE-NON-VALIDEE" in verdicts.CODES_M3_LIST


def test_document_reel_du_depot_est_a_letat_proposition_et_donc_refuse():
    """Constat sur le VRAI document livré par cette tranche (docs/compliance/politiques/
    POLITIQUE-photos-non-contractuelles.md) : au moment de cette livraison, il n'est PAS encore
    validé par Nathan — la garde doit donc refuser. Si ce test échoue après une validation
    humaine réelle du document, c'est le comportement ATTENDU (autorisation), pas une régression."""
    chemin = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "compliance"
        / "politiques"
        / "POLITIQUE-photos-non-contractuelles.md"
    )
    assert chemin.is_file(), f"document de politique introuvable : {chemin}"
    texte = chemin.read_text(encoding="utf-8")
    statut = politique_photos.lire_statut_validation(texte)
    assert statut == "proposition", (
        f"statut mesuré {statut!r} — si le document a été validé entretemps, ce test doit être "
        "mis à jour pour refléter la nouvelle réalité, jamais contourné"
    )
    assert politique_photos.verifier_collecte_photo_autorisee(texte) is not None
