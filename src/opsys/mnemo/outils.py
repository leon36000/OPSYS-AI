"""Outils COMMUNS de lecture de Mnémo : `opsys_soi_lire` et `opsys_lecons_actives`.

T0 / N0, exposés sur le serveur MCP de CHAQUE département (comme `opsys_connaissances_rechercher`), jamais à un
appareil. Le département appelant est fixé par la plateforme. Aucun droit n'est élargi :

- `opsys_soi_lire` rend le modèle de soi à tous les départements, sauf la dimension financière (marges observées), que
  seuls M3, M5, M8, M9 et M10 lisent (les départements qui lisent déjà de la marge) ; une dimension non lisible n'est ni
  rendue ni nommée, seulement comptée ;
- `opsys_lecons_actives` rend les leçons PROMUES qui visent le département appelant, plus celle en canari si la clé
  d'application tombe dans sa part. Lire une leçon ne l'applique pas : le département décide.

L'écriture (proposition, confirmation, décision) est l'affaire des outils `m10_*` du département M10.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .. import stockage
from ..departements import Departement
from ..outils import Autonomie, Niveau, Outil
from . import lecons, service, soi

NOM_SOI = "opsys_soi_lire"
NOM_LECONS = "opsys_lecons_actives"
REGISTRE_SOI = "soi"
REGISTRE_LECONS = "lecons"


def construire(departements: Mapping[str, Departement]) -> tuple[Outil, ...]:
    def lire_soi(
        dimension: str | None = None, etats: list[str] | None = None, avec_valeur: bool = False, decalage: int = 0
    ) -> dict[str, Any]:
        service.refuser_appareil()
        appelant = service.departement_appelant()
        registre = service.Lecture(stockage.maillons("m10-memoire", REGISTRE_SOI))
        vue = soi.vue(
            registre,
            lecteur=appelant,
            maintenant=service.maintenant(),
            dimension=dimension,
            etats_voulus=tuple(etats) if etats else ("confirme", "propose"),
            decalage=decalage,
        )
        return soi.avec_pagination(
            service.borner(soi.compacter(vue, avec_valeur=avec_valeur), ("enonces", "revisions_en_attente"))
        )

    def lecons_actives(cle_application: str) -> dict[str, Any]:
        service.refuser_appareil()
        appelant = service.departement_appelant()
        registre = service.Lecture(stockage.maillons("m10-memoire", REGISTRE_LECONS))
        reponse = lecons.appliquer_a(registre, appelant, cle_application)
        reponse["avertissement"] = (
            "Une leçon promue est lisible, pas appliquée : c'est ton département qui décide de s'en "
            "servir, par ses propres règles. Les paramètres sont calculés par le code."
        )
        return service.borner(reponse, ("lecons",))

    return (
        Outil(
            nom=NOM_SOI,
            description=(
                "Lit le MODÈLE DE SOI de l'entreprise (ce qu'elle est : services, zones, équipes, capacité, règles et "
                "préférences de la direction, vocabulaire, ton de marque…) : chaque énoncé porte sa source, sa "
                "confiance "
                "calculée, sa date et son état (proposé, confirmé, obsolète). Seul un énoncé « confirme » a été "
                "validé par "
                "une personne ; un énoncé « propose » est une hypothèse, pas un fait. Une dimension « inconnu » n'a "
                "aucune "
                "source : ne l'invente pas. Les révisions en attente montrent ce que de nouveaux faits contredisent."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": list(_dimensions())},
                    "etats": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(soi.ETATS)},
                        "description": "défaut : confirme et propose",
                    },
                    "avec_valeur": {"type": "boolean", "description": "joindre la valeur structurée de chaque énoncé"},
                    "decalage": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "reprendre à ce rang (voir `suivant`)",
                    },
                },
                "additionalProperties": False,
            },
            fonction=lire_soi,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom=NOM_LECONS,
            description=(
                "Lit les LEÇONS promues par la direction qui visent ton département (apprentissage continu "
                "gouverné), plus "
                "la leçon en canari si ta clé d'application tombe dans sa part. Chaque leçon porte son paramètre "
                "calculé "
                "par le code, sa source, son évaluation hors ligne. Lire n'applique rien."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "cle_application": {
                        "type": "string",
                        "description": "identifiant stable du cas "
                        "(chantier, affaire) : un même cas reçoit toujours la même réponse",
                    }
                },
                "required": ["cle_application"],
                "additionalProperties": False,
            },
            fonction=lecons_actives,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
    )


def _dimensions() -> tuple[str, ...]:
    from .soi_dimensions import DIMENSIONS

    return tuple(DIMENSIONS)


__all__ = ["NOM_LECONS", "NOM_SOI", "REGISTRE_LECONS", "REGISTRE_SOI", "construire"]
