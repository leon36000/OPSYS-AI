"""Lecture d'administration de Mnémo : l'état du modèle de soi, du graphe et des leçons, pour la console et la CLI.

LECTURE seule, métadonnées et libellés produits par le code (jamais le texte libre d'un tiers). La dimension
financière du modèle de soi est incluse : l'administration la lit. Le graphe n'est rendu que par pseudonymes courts.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from . import lecons, registres, service, soi
from .graphe import GrapheSql


def vue_admin(cnx: Connection) -> dict[str, Any]:
    maintenant = service.maintenant()
    modele = soi.vue(
        registres.soi(), lecteur=soi.LECTEUR_ADMIN, maintenant=maintenant, etats_voulus=("confirme", "propose")
    )
    graphe = GrapheSql(cnx)
    attente = [
        {
            "arete_id": a.arete_id,
            "type": a.type,
            "de": f"{a.de.type}:{a.de.libelle}",
            "vers": f"{a.vers.type}:{a.vers.libelle}",
            "valide_de": a.valide_de,
            "source": a.source_ref,
            "sensible": a.sensible,
        }
        for a in graphe.en_attente(50)
    ]
    return {
        "genere_le": service.instant_iso(maintenant),
        "soi": modele,
        "graphe": {**graphe.etat(), "en_attente": attente},
        "lecons": lecons.vue(registres.lecons()),
        "mention_professionnelle": soi.MENTION_PROFESSIONNELLE,
    }
