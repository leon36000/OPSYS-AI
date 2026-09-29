"""Tests du brouillon de soumission client (PLAN T2.3, `soumission.py`)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, soumission, verdicts  # noqa: E402


def _devis_reel(**surcharges):
    """Un devis réellement produit par devis_durable.creer_devis (Decimal, prix calculés)."""
    devis, verdict = devis_durable.creer_devis(
        devis_id="M3-DEVIS-soumission-001",
        lead_id="lead-soumission-1",
        chantier_id=None,
        lignes=[
            {
                "description": "Gouttière alu 5 po",
                "quantite": "30",
                "unite": "pi_lin",
                "cout_unitaire": "10.00",
                "reference_besoin_materiau": None,
            }
        ],
        taux_marge="0.35",
        horodatage="2026-09-28T14:00:00-04:00",
        registre_cible=[],
    )
    assert verdict is None
    devis.update(surcharges)
    return devis


def test_brouillon_html_contient_les_champs_client():
    devis = _devis_reel()
    html, verdict = soumission.generer_brouillon_html(devis)
    assert verdict is None
    assert "M3-DEVIS-soumission-001" in html
    assert "Gouttière alu 5 po" in html
    assert str(devis["prix_total"]) in html
    assert str(devis["lignes"][0]["prix_unitaire"]) in html
    assert "BROUILLON" in html
    assert "<!doctype html>" in html


def test_brouillon_html_najamais_le_cout_ni_la_marge():
    """Séparation coût/prix (audit M3 §2.1) : même un devis 'interne' complet (Decimal en main)
    ne doit jamais laisser fuiter cout_unitaire/cout_ligne/cout_total/taux_marge dans le HTML."""
    devis = _devis_reel()
    html, verdict = soumission.generer_brouillon_html(devis)
    assert verdict is None
    assert str(devis["cout_total"]) not in html
    assert str(devis["taux_marge"]) not in html
    for ligne in devis["lignes"]:
        assert str(ligne["cout_unitaire"]) not in html


def test_description_est_echappee_contre_linjection_html():
    devis = _devis_reel()
    devis["lignes"][0]["description"] = "<script>alert(1)</script>"
    html, verdict = soumission.generer_brouillon_html(devis)
    assert verdict is None
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_devis_sans_lignes_est_rejete():
    devis = _devis_reel()
    devis["lignes"] = []
    html, verdict = soumission.generer_brouillon_html(devis)
    assert html is None
    assert verdict is not None
    assert verdict["code"] == "REJ-DEVIS-LIGNES-VIDES"
    assert verdicts.est_verdict(verdict["code"])


@pytest.mark.parametrize(
    "devis_invalide",
    [
        {},
        {"devis_id": "D1"},
        "pas-un-dict",
        None,
    ],
)
def test_devis_structurellement_invalide_est_rejete(devis_invalide):
    html, verdict = soumission.generer_brouillon_html(devis_invalide)
    assert html is None
    assert verdict is not None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_ligne_sans_les_cles_client_attendues_est_rejetee():
    devis = _devis_reel()
    devis["lignes"] = [{"description": "seulement une description"}]
    html, verdict = soumission.generer_brouillon_html(devis)
    assert html is None
    assert verdict is not None
    assert verdict["code"] == "REJ-DEVIS-LIGNE-INVALIDE"


def test_rien_nest_recalcule_les_montants_sont_repris_tels_quels():
    devis = _devis_reel()
    html, verdict = soumission.generer_brouillon_html(devis)
    assert verdict is None
    # prix_unitaire = 10.00 * 1.35 = 13.50 ; prix_ligne = 13.50 * 30 = 405.00 — déjà calculés par
    # devis_durable.creer_devis, ce module ne fait que les afficher.
    assert devis["lignes"][0]["prix_unitaire"] == Decimal("13.50")
    assert devis["prix_total"] == Decimal("405.00")
    assert "13.50" in html
    assert "405.00" in html


# -- contenu_client : la porte commune du HTML et du PDF (PLAN T2.3-f) ------------------------------
def test_contenu_client_ne_garde_que_la_liste_blanche_et_ne_touche_a_aucune_valeur():
    devis = _devis_reel()
    devis["cout_secret"] = "5150.99"
    devis["lignes"][0]["cout_ligne_secret"] = "4242.42"
    contenu, verdict = soumission.contenu_client(devis)
    assert verdict is None
    assert set(contenu) == {"devis_id", "statut", "horodatage", "lignes", "prix_total"}
    assert set(contenu["lignes"][0]) == {
        "reference_ligne", "description", "quantite", "unite", "prix_unitaire", "prix_ligne",
    }
    assert contenu["prix_total"] == devis["prix_total"] and isinstance(contenu["prix_total"], Decimal)
    assert contenu["lignes"][0]["prix_unitaire"] == devis["lignes"][0]["prix_unitaire"]
    assert "cout_unitaire" not in contenu["lignes"][0] and "taux_marge" not in contenu


def test_contenu_client_rend_les_memes_verdicts_que_le_brouillon_html():
    for devis_invalide in ({}, None, {"devis_id": "D1"}):
        contenu, verdict = soumission.contenu_client(devis_invalide)
        assert contenu is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"
    sans_lignes = _devis_reel(lignes=[])
    assert soumission.contenu_client(sans_lignes)[1]["code"] == "REJ-DEVIS-LIGNES-VIDES"
    ligne_pauvre = _devis_reel(lignes=[{"description": "seulement une description"}])
    assert soumission.contenu_client(ligne_pauvre)[1]["code"] == "REJ-DEVIS-LIGNE-INVALIDE"


def test_la_mention_brouillon_du_html_est_la_constante_partagee_avec_le_pdf():
    html, verdict = soumission.generer_brouillon_html(_devis_reel())
    assert verdict is None
    assert soumission.MENTION_BROUILLON in html
    assert soumission.MENTION_BROUILLON.startswith("BROUILLON")
