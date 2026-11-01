"""Le RÉSUMÉ agrégé du pipeline commercial, publié pour M8 (`m2.pipeline_constate`, D2 de
`docs/architecture/M8-ENTREPOT-SOURCES.md`).

Module pur : aucune entrée-sortie, aucune horloge. M8 ne lit aucun outil de M2 : M2 publie, sur le bus, les comptes que
`previsions.analyser` établit sur TOUS les leads, sans rien de ce qui identifie un lead, un contact, un vendeur ou un
propriétaire.

Ce qui part : les comptes par statut, les ouverts, les convertis, les perdus, les résolus, le taux de conversion des
résolus et la valeur pondérée DÉCLARÉE par les vendeurs. Le taux et la valeur pondérée valent `None` quand M2 refuse de
conclure (échantillon sous le seuil, aucune valeur déclarée) : un refus n'est jamais un zéro. La valeur est le CENTRE de
l'estimation, sans intervalle : c'est une estimation commerciale, pas un montant comptable.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from . import encodage

__all__ = ["charge_pipeline", "version_pipeline"]

_CENTIEMES = Decimal(1).scaleb(-2)
_EN_POURCENT = Decimal(1).scaleb(2)


def _taux_pct(mesure: Mapping[str, Any]) -> str | None:
    valeur = mesure.get("valeur")
    if valeur is None:
        return None
    return format((Decimal(valeur) * _EN_POURCENT).quantize(_CENTIEMES, rounding=ROUND_HALF_EVEN), "f")


def _valeur_ponderee(bloc: Mapping[str, Any]) -> str | None:
    ponderee = bloc.get("valeur_ponderee")
    if not isinstance(ponderee, Mapping):
        return None
    return format(Decimal(ponderee["centre"]).quantize(_CENTIEMES, rounding=ROUND_HALF_EVEN), "f")


def version_pipeline(contenu: Mapping[str, Any]) -> str:
    """La version des DONNÉES (16 hexadécimaux) : tout sauf l'identifiant et le jour.

    Les mêmes données redonnent la même version."""
    sans_id = {
        cle: valeur for cle, valeur in contenu.items() if cle not in ("evenement_id", "date_reference", "constate_le")
    }
    return encodage.empreinte(["m2.pipeline_constate.v1", sans_id])[:16]


def charge_pipeline(analyse: Mapping[str, Any], date_reference: str, constate_le: str) -> dict[str, Any]:
    """La charge de `m2.pipeline_constate` à partir du résultat de `previsions.analyser` (clé `resultat`).
    `constate_le` : l'instant du constat ; il entre dans l'identifiant (jamais dans la version des données) pour qu'un
    retour
    à une version antérieure (A, puis B, puis A) ne se confonde pas avec la première publication."""
    resultat = analyse["resultat"]
    pipeline, entonnoir = resultat["pipeline"], resultat["entonnoir"]
    contenu: dict[str, Any] = {
        "date_reference": date_reference,
        "total": pipeline["total"],
        "ouverts": pipeline["ouverts"],
        "par_statut": {statut: nombre for statut, nombre in pipeline["par_statut"].items()},
        "convertis_un_jour": entonnoir["convertis_un_jour"],
        "perdus": entonnoir["perdus"],
        "resolus": entonnoir["resolus"],
        "taux_conversion_resolus_pct": _taux_pct(resultat["taux_conversion_des_resolus"]),
        "valeur_ponderee_cad": _valeur_ponderee(resultat["valeur_ponderee"]),
    }
    version = version_pipeline(contenu)
    marque = encodage.empreinte(["m2.pipeline_constate.constate_le", constate_le])[:8]
    return {
        "evenement_id": f"m2-pipeline-{date_reference}-{version}-{marque}",
        "constate_le": constate_le,
        "version_donnees": version,
        **contenu,
    }
