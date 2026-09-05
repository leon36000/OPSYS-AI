"""#595 : SonarCloud ne facturait AUCUN fichier comme test, faute de déclaration — chaque analyse de
main dépassait le plafond LOC de l'organisation et échouait depuis le 2026-08-28 (mesuré via
/api/ce/activity). Ce test fige la déclaration des tests dans .sonarcloud.properties : si quelqu'un
la retire ou la rétrécit, il rougit avant que SonarCloud ne retombe en panne silencieuse."""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _proprietes() -> dict[str, str]:
    props: dict[str, str] = {}
    for ligne in (RACINE / ".sonarcloud.properties").read_text(encoding="utf-8").splitlines():
        s = ligne.strip()
        if not s or s.startswith("#"):
            continue
        cle, _, valeur = s.partition("=")
        props[cle.strip()] = valeur.strip()
    return props


def test_les_tests_sont_declares_comme_code_de_test_pour_sonarcloud():
    motifs = _proprietes().get("sonar.test.inclusions", "").split(",")
    assert "**/tests/**" in motifs
    assert "**/test_*.py" in motifs
    assert "**/conftest.py" in motifs


def test_l_exclusion_cpd_des_socles_de_modules_est_conservee():
    # Régression : l'ajout ne doit pas faire disparaître la clé déjà justifiée dans le fichier.
    assert "Modules M/**/encodage.py" in _proprietes()["sonar.cpd.exclusions"]
