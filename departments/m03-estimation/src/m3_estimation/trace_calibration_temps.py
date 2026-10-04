"""Trace hashée des entrées ayant effectivement produit une durée M3.

La sémantique n'est qualifiée que par déclaration exacte du barème; cette trace ne réalise
aucune calibration et aucune valeur n'est réinjectée dans le barème.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from . import registre, verdicts

__all__ = ["construire_trace", "empreinte_bareme"]

_LONGUEUR_NOM_MAX = 64
_SEMANTIQUE_TEMPS_QUALIFIEE = "duree_ecoulee_intervention"


def _nom_borne(valeur: Any) -> str | None:
    """Ne conserve que des noms courts, non vides, sans caractères de contrôle."""
    if not isinstance(valeur, str) or not valeur or len(valeur) > _LONGUEUR_NOM_MAX:
        return None
    if valeur != valeur.strip() or not all(caractere.isprintable() for caractere in valeur):
        return None
    return valeur


def _source_canonique(valeur: Any) -> Any:
    """Représentation typée injective pour le hash, sans copier le barème dans la trace."""
    if isinstance(valeur, Decimal):
        return ["decimal", format(valeur, "f")]
    if isinstance(valeur, dict):
        if any(not isinstance(cle, str) for cle in valeur):
            raise TypeError("clé source non textuelle")
        return ["dict", [[cle, _source_canonique(element)] for cle, element in sorted(valeur.items())]]
    if isinstance(valeur, list):
        return ["list", [_source_canonique(element) for element in valeur]]
    if valeur is None:
        return ["none"]
    if isinstance(valeur, bool):
        return ["bool", valeur]
    if isinstance(valeur, str):
        return ["str", valeur]
    if isinstance(valeur, int):
        return ["int", valeur]
    if isinstance(valeur, float) and math.isfinite(valeur):
        return ["float", repr(valeur)]
    raise TypeError("type source non canonique")


def empreinte_bareme(bareme: dict[str, Any]) -> str:
    """Empreinte publique identique à celle portée par les traces M3."""
    return registre._encoder_canonique(_source_canonique(bareme))


def construire_trace(
    *,
    bareme: dict[str, Any],
    type_service: str,
    quantite: Any,
    taux_minutes_par_unite: Decimal,
    duree_estimee_minutes: str,
    taux_minutes_par_unite_source: Decimal | None = None,
    calibration_version_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Construit les champs de temps d'une estimation réussie, ou un verdict avant écriture."""
    try:
        if not isinstance(taux_minutes_par_unite, Decimal) or not taux_minutes_par_unite.is_finite():
            raise TypeError("taux de temps absent ou invalide")
        empreinte = empreinte_bareme(bareme)
        quantite_exacte = format(Decimal(str(quantite)), "f")
        unite_brute = bareme.get("unite") if isinstance(bareme, dict) else None
        unite = _nom_borne(unite_brute)
        version_brute = bareme.get("version") if isinstance(bareme, dict) else None
        version = _nom_borne(version_brute)
        type_borne = _nom_borne(type_service)
        etat_unite = "presente" if unite is not None else ("absente" if unite_brute is None else "invalide")
        etat_type = "presente" if type_borne is not None else ("absente" if type_service is None else "invalide")
        etat_version = "presente" if version is not None else ("absente" if version_brute is None else "invalide")
    except (ArithmeticError, TypeError, ValueError, RecursionError):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="source du barème non canonique pour la trace de temps"
        )

    schema = 3 if calibration_version_id is not None else 2
    if schema == 3 and (
        not isinstance(taux_minutes_par_unite_source, Decimal)
        or not taux_minutes_par_unite_source.is_finite()
        or taux_minutes_par_unite_source <= 0
        or not isinstance(calibration_version_id, str)
        or len(calibration_version_id) != 64
        or any(c not in "0123456789abcdef" for c in calibration_version_id)
    ):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="provenance de promotion calibration invalide"
        )
    resultat = {
        "version_schema": schema,
        "type_service": type_borne,
        "etat_type_service": etat_type,
        "quantite": quantite_exacte,
        "unite_quantite": unite,
        "etat_unite": etat_unite,
        "bareme_version": version,
        "etat_bareme_version": etat_version,
        "taux_minutes_par_unite": format(taux_minutes_par_unite, "f"),
        "duree_estimee_minutes": duree_estimee_minutes,
        "empreinte_bareme": empreinte,
        "provenance": "bareme_fourni",
        "semantique_temps": (
            _SEMANTIQUE_TEMPS_QUALIFIEE
            if isinstance(bareme, dict) and bareme.get("semantique_temps") == _SEMANTIQUE_TEMPS_QUALIFIEE
            else "non_qualifiee"
        ),
    }
    if schema == 3:
        resultat["taux_minutes_par_unite_source"] = format(taux_minutes_par_unite_source, "f")
        resultat["calibration_version_id"] = calibration_version_id
    return resultat, None
