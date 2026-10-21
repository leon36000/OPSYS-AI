"""Détection des champs interdits dans un objet JSON (clés uniquement)."""
import unicodedata
from typing import Any

from . import verdicts

CHAMPS_INTERDITS = frozenset({
    "prix", "montant", "date_ferme", "date_ferme_imposee",
    "engagement", "engagement_financier",
})

__all__ = ["CHAMPS_INTERDITS", "scanner_frontieres", "verifier_frontieres"]


def _normaliser_cle(cle: Any) -> str:
    """Normalise une clé pour comparaison avec les champs interdits.

    - Convertit en chaîne (str)
    - Met en minuscules
    - Supprime les diacritiques (décomposition NFD, suppression des Mn)
    - Remplace les espaces et tirets par des underscores.
    """
    s = str(cle).lower()
    # Décomposition canonique NFD
    nfd = unicodedata.normalize('NFD', s)
    # Suppression des caractères de catégorie Mn (marques de diacritique)
    sans_diacritiques = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    # Remplacement des espaces et tirets par underscore
    normalise = sans_diacritiques.replace(' ', '_').replace('-', '_')
    return normalise


def scanner_frontieres(objet: Any) -> list[str]:
    """Retourne la liste triée des chemins des clés interdites présentes dans l'objet.

    Le scan est récursif sur les dictionnaires, listes et tuples.
    La clé est normalisée avant comparaison, et le chemin utilise la clé normalisée.
    """
    violations: list[str] = []

    def _scan(element: Any, chemin: str):
        if isinstance(element, dict):
            for cle_brute, valeur in element.items():
                cle_norm = _normaliser_cle(cle_brute)
                # Construire le chemin pour cette clé
                nouveau_chemin = f"{chemin}.{cle_norm}" if chemin else cle_norm
                # Vérifier si la clé normalisée est interdite
                if cle_norm in CHAMPS_INTERDITS:
                    violations.append(nouveau_chemin)
                # Descendre dans la valeur
                _scan(valeur, nouveau_chemin)
        elif isinstance(element, (list, tuple)):
            for idx, item in enumerate(element):
                # Suffixe d'indexation : [i] sans point avant
                suffixe = f"[{idx}]"
                nouveau_chemin = chemin + suffixe if chemin else suffixe
                _scan(item, nouveau_chemin)
        # Les autres types ne sont pas explorés

    _scan(objet, "")
    violations.sort()
    return violations


def verifier_frontieres(objet: Any) -> tuple[bool, dict | None]:
    """Vérifie si l'objet contient des champs interdits.

    Retourne (True, None) si aucune violation, sinon (False, verdict_dict).
    """
    violations = scanner_frontieres(objet)
    if not violations:
        return True, None
    detail = ", ".join(violations)
    verdict = verdicts.construire_verdict("REJ-FRONTIERE-VIOLEE", detail=detail)
    return False, verdict
