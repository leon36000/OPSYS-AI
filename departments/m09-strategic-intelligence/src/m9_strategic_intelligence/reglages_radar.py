"""Lecture des seuils du radar de risques par la couche UNIQUE des réglages de direction (CFG-1).

Adaptateur (il lit le manifeste du département et la base de l'instance) ; les règles, elles, sont pures
(``risques``). Précédence (``opsys.reglages.lecture``) : valeur ADOPTÉE par le propriétaire > valeur déjà écrite dans
``department.yaml`` (``configuration.radar``) > ABSENCE. Une absence n'est jamais remplacée : la règle correspondante du
radar est « non évaluée » et dit quoi déclarer. Une valeur lue mais refusée par sa déclaration (type, bornes) est rendue
à part : traitée comme non déclarée, avec le code du refus, jamais corrigée.

Aucune proposition n'est lue : une proposition « recommandation, non validée » n'est jamais un seuil en vigueur.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from opsys.reglages import lecture
from opsys.reglages.declaration import Reglage, ReglageRefuse, valider_valeur
from opsys.reglages.declaration import lire as lire_declarations

from .risques import REGLAGES

_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_BLOC = ("configuration", "radar")


def declarations(donnees: Any) -> dict[str, Reglage]:
    """Les réglages que le manifeste déclare, par clé (``m9.nom``)."""
    return {r.cle: r for r in lire_declarations(donnees.get("reglages"), "manifeste", donnees["code"], donnees["id"])}


def lire() -> dict[str, Any]:
    """``{"seuils": {nom: valeur validée}, "seuils_refuses": {nom: code}}`` à passer au radar (``**``)."""
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    configuration = donnees.get("configuration")
    du_fichier = configuration.get(_BLOC[1]) if isinstance(configuration, dict) else None
    fusionne = lecture.superposer(donnees, _BLOC, du_fichier)
    declares = declarations(donnees)
    seuils: dict[str, Any] = {}
    refuses: dict[str, str] = {}
    if not isinstance(fusionne, dict):
        return {"seuils": seuils, "seuils_refuses": refuses}
    for nom, reglage in REGLAGES.items():
        brut = fusionne.get(nom)
        declaration = declares.get(reglage.cle)
        if brut is None or declaration is None:
            continue
        try:
            seuils[nom] = valider_valeur(declaration, brut)
        except ReglageRefuse as refus:
            refuses[nom] = refus.code
    return {"seuils": seuils, "seuils_refuses": refuses}
