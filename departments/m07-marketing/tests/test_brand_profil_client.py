"""Tests — chargement fail-closed du profil de marque du CLIENT (PLAN T4.3, M7-audit.md §2.1).

`brand/profile.yaml` ne doit plus jamais être utilisable tel quel comme identité publiable :
tant qu'il porte encore `PLACEHOLDER_NOM`, tout chargement doit être refusé, jamais un faux vert.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from m7_marketing.brand import profil_client

BRAND_VALIDE = {
    "name": "Entreprise Test Fictive",
    "tagline": "Tagline de test",
    "tone": "professionnel",
    "colors": ["#111111"],
    "langue": "fr",
}


# ---------------------------------------------------------------------------
# verifier_profil_configure — fonction pure
# ---------------------------------------------------------------------------
def test_profil_valide_et_configure_accepte():
    profil, motif = profil_client.verifier_profil_configure(dict(BRAND_VALIDE))
    assert motif is None
    assert profil["name"] == "Entreprise Test Fictive"


def test_profil_avec_placeholder_refuse():
    brand = dict(BRAND_VALIDE, name=profil_client.PLACEHOLDER_NOM)
    profil, motif = profil_client.verifier_profil_configure(brand)
    assert profil is None
    assert motif == profil_client.REFUS_NON_CONFIGURE


def test_profil_champ_requis_manquant_refuse():
    incomplet = {k: v for k, v in BRAND_VALIDE.items() if k != "colors"}
    profil, motif = profil_client.verifier_profil_configure(incomplet)
    assert profil is None
    assert "colors" in motif


# ---------------------------------------------------------------------------
# charger_profil_client — E/S fichier
# ---------------------------------------------------------------------------
def test_charger_profil_client_fichier_absent():
    profil, motif = profil_client.charger_profil_client(Path("/inexistant/profile.yaml"))
    assert profil is None
    assert "introuvable" in motif


def test_charger_profil_client_fichier_valide(tmp_path):
    chemin = tmp_path / "profile.yaml"
    chemin.write_text(yaml.safe_dump(BRAND_VALIDE), encoding="utf-8")
    profil, motif = profil_client.charger_profil_client(chemin)
    assert motif is None
    assert profil["name"] == "Entreprise Test Fictive"


def test_charger_profil_client_fichier_encore_placeholder(tmp_path):
    brand = dict(BRAND_VALIDE, name=profil_client.PLACEHOLDER_NOM)
    chemin = tmp_path / "profile.yaml"
    chemin.write_text(yaml.safe_dump(brand), encoding="utf-8")
    profil, motif = profil_client.charger_profil_client(chemin)
    assert profil is None
    assert motif == profil_client.REFUS_NON_CONFIGURE


def test_charger_profil_client_racine_non_mapping(tmp_path):
    chemin = tmp_path / "profile.yaml"
    chemin.write_text("- juste\n- une\n- liste\n", encoding="utf-8")
    profil, motif = profil_client.charger_profil_client(chemin)
    assert profil is None
    assert "mapping" in motif


def test_charger_profil_client_defaut_reel_est_encore_non_configure():
    """Preuve directe sur le fichier RÉEL versionné du dépôt (M7-audit.md §2.1) : tant que
    Nathan n'a pas fourni le nom commercial réel, le profil par défaut est refusé, jamais utilisé
    silencieusement sous une identité inventée ou celle d'OPSYS-AI."""
    profil, motif = profil_client.charger_profil_client()
    assert profil is None
    assert motif == profil_client.REFUS_NON_CONFIGURE


def test_defaut_reel_nest_jamais_opsys_ai():
    """Même sans passer par le chargeur fail-closed : le fichier lui-même ne doit plus jamais
    contenir l'identité d'OPSYS-AI (SOUL.md « jamais OPSYS-AI, jamais une autre marque »)."""
    brut = yaml.safe_load(profil_client._PROFIL_PAR_DEFAUT.read_text(encoding="utf-8"))
    assert brut["name"] != "OPSYS-AI"
    assert "OPSYS-AI" not in brut["name"]
