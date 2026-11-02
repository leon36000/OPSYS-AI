"""Outils des scénarios CHIFFRÉS (M9-C2) : M9 appelle les moteurs des propriétaires et compose ; il ne calcule rien.

Adaptateur seul (la logique est dans ``scenarios_chiffres``). M9 appelle un propriétaire UNIQUEMENT par le port privé du
socle ``lecteur_producteurs_m9`` (liste blanche de lectures et de calculs paramétrés T0/N0, admin authentifié relu en
base à
chaque appel, jamais un appareil : M5 refuse l'appareil pour son moteur). Aucune capture n'est lue ni écrite, aucune
action
n'est proposée : un « et si » reste préparatoire. Un moteur absent, refusé ou en erreur est un impact NON CHIFFRÉ.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opsys import contexte
from opsys.outils import Autonomie, Niveau, Outil

from . import scenarios_chiffres
from .outils_tissu import borner, exiger_admin_strict

_JOUR = {
    "type": "string",
    "pattern": r"^\d{4}-\d{2}-\d{2}$",
    "description": "Jour de départ AAAA-MM-JJ (M9 n'a pas d'horloge).",
}
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def construire_outils(*, budget_sortie: int, lecteur: Callable[..., dict[str, Any]] | None) -> tuple[Outil, ...]:
    def chiffrer(
        choc: str, parametres: dict[str, Any], jour: str, horodatage: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        appelante = contexte.identite_appelante()
        if appelante is None or appelante.source != "console":
            # M5 refuse l'appareil pour son moteur ; M9 le refuse avant, au lieu de rendre un scénario partout « non
            # chiffré ».
            raise ValueError(
                "REJ-IDENTITE-APPAREIL-INVALIDE : les scénarios chiffrés sont réservés à l'admin de la console"
            )
        scenario = scenarios_chiffres.chiffrer(
            choc, parametres, options, jour=jour, horodatage=horodatage, lecteur=lecteur
        )
        return borner({"accepte": True, **scenario}, budget_sortie)

    def lister() -> dict[str, Any]:
        exiger_admin_strict()
        return borner(
            {
                "accepte": True,
                "type": "CHOCS_CHIFFRES",
                "version": scenarios_chiffres.VERSION,
                "chocs": scenarios_chiffres.catalogue(),
                "limites": list(scenarios_chiffres._LIMITES),
            },
            budget_sortie,
        )

    return (
        Outil(
            nom="m9_chiffrer_scenario",
            description=(
                "Chiffre un « et si » par le MOTEUR DU PROPRIÉTAIRE, avec son reçu rejouable : trésorerie par le "
                "Monte-Carlo de M5 (retard de paiement d'une part du carnet, hausse des coûts, baisse des "
                "encaissements) ou comparaison achat/crédit-bail de M5, capacité par M4 (employés absents, jours "
                "bloqués, hausse de la demande), niveau de leads face à l'intervalle de M2. M9 ne calcule rien : un "
                "moteur absent ou en erreur donne « non chiffré, manque X », jamais zéro. Préparatoire : aucune "
                "décision, aucune action. Admin authentifié seulement."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "choc": {"type": "string", "maxLength": 64},
                    "parametres": {"type": "object"},
                    "jour": _JOUR,
                    "horodatage": _INSTANT,
                    "options": {"type": "object"},
                },
                "required": ["choc", "parametres", "jour", "horodatage"],
                "additionalProperties": False,
            },
            fonction=chiffrer,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m9_lister_scenarios_chiffres",
            description="Liste les chocs chiffrables par un moteur propriétaire (paramètres, options exigées, "
            "propriétaire). Lecture seule.",
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lister,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset(),
        ),
    )
