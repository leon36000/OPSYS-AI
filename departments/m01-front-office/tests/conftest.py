"""Fixtures communes aux tests de M1 (PLAN T4.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

FIXTURE_QUALIFICATION = (
    Path(__file__).resolve().parents[1] / "fixtures" / "qualification" / "profil-fictif.v1.yaml"
)


@pytest.fixture
def profil_fictif() -> dict:
    """Le profil de qualification FICTIF (`fictif: true`) : questions par service et poids du score."""
    donnees = yaml.safe_load(FIXTURE_QUALIFICATION.read_text(encoding="utf-8"))
    assert donnees["fictif"] is True, "fixture non marquée fictive : refusée"
    return donnees


@pytest.fixture
def declarer_qualification(profil_fictif):
    """Fabrique : écrit dans le profil de l'instance de test les questions et/ou les poids de la fixture fictive.

    Sans cet appel, l'instance de test n'a ni question ni poids : c'est le cas « à configurer » que le code doit dire,
    jamais combler."""

    def _declarer(*, questions: bool = True, poids: bool = True) -> dict:
        from opsys import taxonomie

        if questions:
            taxonomie.enregistrer_questions_qualification(profil_fictif["questions_qualification"])
        if poids:
            taxonomie.enregistrer_poids_score_lead(profil_fictif["poids_score_lead"])
        return profil_fictif

    return _declarer


@pytest.fixture
def politique_photos(monkeypatch):
    """Fabrique : fixe l'état de la politique « photos » que M1 lit (le document réel change avec la décision de
    Nathan, un test ne doit pas en dépendre). `politique_photos("valide")` ouvre la garde ; `("proposition")` la ferme.
    """

    def _fixer(statut: str) -> None:
        import m1_front_office.outils as outils

        monkeypatch.setattr(outils, "_politique_photos_texte", lambda: f"STATUT_VALIDATION: {statut}\n")

    return _fixer
