"""Ingestion des avis clients depuis les fixtures S008a.

Doctrine D-043 : lecture seule — jamais d'écriture sur la source.
Zéro réseau (urllib, socket, requests interdits).
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Chemin canonique vers la fixture (S008a — immuable en lecture)
# parents[0]=reputation/ parents[1]=src/ parents[2]=M7-marketing/
_FIXTURE_DEFAULT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "avis"
    / "avis-anonymises.v1.yaml"
)


def charger_avis(chemin: Path | None = None) -> list[dict]:
    """Charge la liste des avis depuis la fixture YAML.

    Paramètres
    ----------
    chemin : Path optionnel — permet de surcharger le chemin en test.
             Par défaut : fixtures/avis/avis-anonymises.v1.yaml (S008a).

    Retourne
    --------
    list[dict] : les avis bruts, chacun portant au minimum :
        id, fictif, note (int 1-5), plateforme, date (str), texte (str).

    Lève
    ----
    FileNotFoundError : si la fixture est absente.
    ValueError        : si le contenu YAML est invalide ou vide.
    """
    path = Path(chemin) if chemin is not None else _FIXTURE_DEFAULT
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Fixture invalide (attendu dict) : {path}")
    avis = data.get("avis", [])
    if not isinstance(avis, list):
        raise ValueError(f"Clé 'avis' absente ou invalide dans : {path}")
    return avis
