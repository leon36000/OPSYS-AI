from __future__ import annotations

import math
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
# Montants en dollars (nombre fini, zéro ou plus) et comptes (entiers, zéro ou plus) : un booléen n'est ni l'un
# ni l'autre.
CHAMPS_MONTANTS = ("budget", "cout")
CHAMPS_COMPTES = ("impressions", "clics", "conversions")


def _nombre_fini_positif(valeur) -> bool:
    return (
        not isinstance(valeur, bool) and isinstance(valeur, (int, float)) and math.isfinite(valeur) and valeur >= 0
    )


def _compte_valide(valeur) -> bool:
    return not isinstance(valeur, bool) and isinstance(valeur, int) and valeur >= 0


def load_fixture(path: str) -> dict:
    fixture_path = Path(path)
    with open(fixture_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("fixture ads invalide")
    if data.get("fictif") is not True:
        raise ValueError("Le champ 'fictif' doit être true pour les fixtures ads")

    plateforme = data.get("plateforme")
    if not isinstance(plateforme, str):
        raise ValueError("plateforme invalide (attendu: string)")
    if plateforme != plateforme.lower():
        raise ValueError("plateforme invalide (attendu: minuscules)")
    if plateforme not in ALLOWED_PLATFORMS:
        raise ValueError("plateforme invalide (attendu: google_ads ou meta)")

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
        # Présence ne suffit pas : un budget texte levait TypeError, un coût NaN rendait tous les verdicts
        # « conformes ».
        for champ in CHAMPS_MONTANTS:
            if not _nombre_fini_positif(campagne[champ]):
                raise ValueError(f"{champ} invalide (attendu: nombre fini, zéro ou plus)")
        for champ in CHAMPS_COMPTES:
            if not _compte_valide(campagne[champ]):
                raise ValueError(f"{champ} invalide (attendu: entier, zéro ou plus)")
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
