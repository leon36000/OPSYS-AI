"""Dossier de comparaison métier M10 : sources exactes, JSON strict, refus sans couper."""
from __future__ import annotations

import json
import math
from typing import Any

from . import catalogue_references, validation

PROFONDEUR_JSON_MAX = 8
BUDGET_CARACTERES = 5400
_TYPES_FAITS = frozenset({
    "decision_enregistree", "evenement_memorise", "fait_consolide", "fait_candidat", "provenance_documentaire",
})
_METADONNEES = frozenset({"ligne_id", "precedent_ligne_id", "confidentialite", "type_entree", "horodatage"})


def _refus(code: str) -> tuple[None, dict[str, Any]]:
    details = {
        "REJ-DOSSIER-REVISION-INCONNUE": "Aucun signalement réel de révision ne correspond à cette référence.",
        "REJ-DOSSIER-REVISION-RETENU": "Une pièce est retenue par la confidentialité ; aucun fait n'est restitué.",
        "REJ-DOSSIER-REVISION-TYPE-FAIT-INTERDIT": "La source est un contrôle ou hors mémoire métier, non comparable.",
        "REJ-DOSSIER-REVISION-JSON-INVALIDE": (
            "Les champs doivent être JSON strict, floats finis, profondeur au plus 8."
        ),
        "REJ-DOSSIER-REVISION-BUDGET-DEPASSE": "Le dossier complet dépasse 5400 caractères ; aucun fait n'est coupé.",
        "REJ-DOSSIER-REVISION-REGISTRE-INVALIDE": (
            "Chaîne Affaires invalide ou source illisible ; comparaison indisponible."
        ),
    }
    return None, validation.construire_verdict(code, details[code])


def _json_valide(valeur: Any, profondeur: int = 0) -> bool:
    if profondeur > PROFONDEUR_JSON_MAX:
        return False
    if valeur is None or type(valeur) in (bool, int):
        return True
    if type(valeur) is float:
        return math.isfinite(valeur)
    if type(valeur) is str:
        return not any(0xD800 <= ord(c) <= 0xDFFF for c in valeur)
    if type(valeur) is list:
        return all(_json_valide(v, profondeur + 1) for v in valeur)
    if type(valeur) is dict:
        return all(type(k) is str and _json_valide(k) and _json_valide(v, profondeur + 1) for k, v in valeur.items())
    return False


def lire_revision(registre_snapshot: Any, revision_ligne_id: Any) -> tuple[dict | None, dict | None]:
    """Deux faits de la révision demandée ; aucun accès stockage/développement ni coercition JSON."""
    index, refus = catalogue_references.indexer_snapshot_affaires(registre_snapshot)
    if refus is not None:
        return _refus("REJ-DOSSIER-REVISION-REGISTRE-INVALIDE")
    resolution, refus = catalogue_references.resoudre_revision(index, revision_ligne_id)
    if refus is not None:
        if refus["code"] == "REJ-CATALOGUE-REVISION-INCONNUE":
            return _refus("REJ-DOSSIER-REVISION-INCONNUE")
        if refus["code"] == "REJ-CATALOGUE-REVISION-RETENUE":
            return _refus("REJ-DOSSIER-REVISION-RETENU")
        return _refus("REJ-DOSSIER-REVISION-REGISTRE-INVALIDE")
    projection = resolution["projection"]
    faits = []
    for maillon, cle_reference in zip(resolution["faits"], ("reference_a", "reference_b"), strict=True):
        if maillon["type_entree"] not in _TYPES_FAITS:
            return _refus("REJ-DOSSIER-REVISION-TYPE-FAIT-INTERDIT")
        champs = {k: v for k, v in maillon.items() if k not in _METADONNEES}
        if not _json_valide(champs):
            return _refus("REJ-DOSSIER-REVISION-JSON-INVALIDE")
        faits.append({"reference": projection[cle_reference], "type_entree": maillon["type_entree"],
                      "horodatage": maillon["horodatage"], "champs": champs})
    resultat = {"revision": projection, "faits": faits}
    taille = len(json.dumps({"ok": True, "resultat": {"accepte": True, "resultat": resultat}},
                           ensure_ascii=False, allow_nan=False))
    if taille > BUDGET_CARACTERES:
        return _refus("REJ-DOSSIER-REVISION-BUDGET-DEPASSE")
    return resultat, None
