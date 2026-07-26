from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED_FIELDS = {
    "campagne",
    "periode",
    "fenetre_id",
    "budget",
    "cout",
    "impressions",
    "clics",
    "conversions",
}
ALLOWED_PLATFORMS = {"google_ads", "meta"}


def load_fixture(path: str) -> dict:
    fixture_path = Path(path)
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("fixture ads invalide")
    if data.get("fictif") is not True:
        raise ValueError("Le champ 'fictif' doit être true pour les fixtures ads")

    plateforme = data.get("plateforme")
    if not isinstance(plateforme, str) or plateforme != plateforme.lower() or plateforme not in ALLOWED_PLATFORMS:
        raise ValueError("plateforme invalide (attendu: google_ads ou meta en minuscules)")

    campagnes = data.get("campagnes")
    if not isinstance(campagnes, list):
        raise ValueError("campagnes doit être une liste")

    normalized = []
    for campagne in campagnes:
        if not isinstance(campagne, dict):
            raise ValueError("campagne invalide")
        missing = sorted(REQUIRED_FIELDS - set(campagne.keys()))
        if missing:
            raise ValueError(f"champs campagne manquants: {', '.join(missing)}")
        normalized.append(dict(campagne))

    return {
        "fictif": True,
        "plateforme": plateforme,
        "campagnes": normalized,
    }


def load_fixtures(base_dir: str) -> list[dict]:
    base = Path(base_dir)
    fixtures = []
    for path in sorted(base.glob("*.yaml")):
        fixtures.append(load_fixture(str(path)))
    return fixtures
