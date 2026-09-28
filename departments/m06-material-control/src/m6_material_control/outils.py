"""Capacités d'agent du département M6 Material Control.

Chaque outil enveloppe l'orchestrateur unique `materiel.py` (seul point d'écriture
par type de mouvement — RECEPTION/CONSOMMATION/VARIANCE_INVENTAIRE, DA-M6-11).
`m6_receptionner_commande` compose de bout en bout : réception -> écriture du
stock -> résolution de prix -> variance de réception -> signal à M5 -> suggestion
de réapprovisionnement, en un seul appel.

Le registre (append-only hash-chaîné) est en mémoire pour la durée d'un appel : ce
paquet ne possède aucune persistance (hors périmètre, couche MCP/dashboard).
L'appelant transmet l'historique renvoyé par le précédent appel dans
`registre_historique` ; ce module le rejoue pour retrouver un registre valide et
chaîné avant d'y écrire la suite.

Frontière M6 -> M5 (financier) : `signal_po_a_payer.montant_total_estime` reste un
float (contrat gelé M6, PRD §2.8/§5.8) — quiconque le transmet à M5 (qui exige un
Decimal, CA-M5-01) doit le convertir via
`contrats_sortie.montant_decimal_a_la_frontiere` (jamais `Decimal(x)` direct sur un
float).

Autonomie (RÈGLE FINANCE) : M6 ne porte aucune écriture financière — elle SIGNALE
un montant à payer, sans jamais l'exécuter. Ses écritures (stock, inventaire) sont
un registre interne : T1. Lecture et calcul purs : T0.
"""

from __future__ import annotations

from typing import Any

from opsys.outils import Autonomie, Outil

from . import catalogue as catalogue_module
from . import digest, materiel
from . import registre as registre_module

_MAILLON = {"type": "object", "description": "Maillon tel que renvoyé par un appel précédent."}
_REGISTRE_HISTORIQUE = {
    "type": "array",
    "items": _MAILLON,
    "description": "Historique du registre M6 renvoyé par le dernier appel connu ; [] ou omis si aucun.",
}
_LIGNE_DEMANDEE = {
    "type": "object",
    "properties": {"materiau_id": {"type": "string"}, "quantite_demandee": {"type": "number"}},
    "required": ["materiau_id", "quantite_demandee"],
}
_LIGNE_RECUE = {
    "type": "object",
    "properties": {"materiau_id": {"type": "string"}, "quantite_recue": {"type": "number"}},
    "required": ["materiau_id", "quantite_recue"],
}
_BON_DEMANDE = {
    "type": "object",
    "properties": {
        "po_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_demandees": {"type": "array", "items": _LIGNE_DEMANDEE},
        "horodatage": {"type": "string"},
    },
    "required": ["po_id", "chantier_id", "lignes_demandees", "horodatage"],
}
_RECEPTION_PO = {
    "type": "object",
    "properties": {
        "po_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_recues": {"type": "array", "items": _LIGNE_RECUE},
        "horodatage": {"type": "string"},
    },
    "required": ["po_id", "chantier_id", "lignes_recues", "horodatage"],
}
_CATALOGUE = {
    "type": ["object", "null"],
    "description": "CatalogueMateriaux {version, unite_monetaire, postes} ; null si aucun catalogue.",
}
_SEUILS_REORDER = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "chantier_id": {"type": "string"},
            "materiau_id": {"type": "string"},
            "seuil_quantite": {"type": "number"},
        },
        "required": ["chantier_id", "materiau_id", "seuil_quantite"],
    },
}
_WCT = {"type": "object", "description": "WctRecu — 12 clés exactes émises par M4, reproduites telles quelles."}
_FORMULAIRE_CONSOMMATION = {
    "type": "object",
    "properties": {
        "wct_id": {"type": "string"},
        "intervention_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_consommees": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"materiau_id": {"type": "string"}, "quantite": {"type": "number"}},
                "required": ["materiau_id", "quantite"],
            },
        },
    },
    "required": ["wct_id", "intervention_id", "chantier_id", "lignes_consommees"],
}
_COMPTAGE = {
    "type": "object",
    "properties": {
        "chantier_id": {"type": "string"},
        "materiau_id": {"type": "string"},
        "quantite_comptee": {"type": "number"},
        "horodatage": {"type": "string"},
    },
    "required": ["chantier_id", "materiau_id", "quantite_comptee", "horodatage"],
}


def _rejouer_registre(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Reconstruit le registre M6 en rejouant l'historique fourni par l'appelant
    (mêmes maillons, même ordre -> mêmes hachages : reconstruction fidèle, pas une
    vérification contre une vérité externe que ce paquet ne détient pas)."""
    registre_cible = registre_module.Registre()
    historique = historique or []
    if not historique:
        return registre_cible
    mouvements = [
        {
            "type_mouvement": maillon["type_mouvement"],
            "chantier_id": maillon["chantier_id"],
            "materiau_id": maillon["materiau_id"],
            "quantite": maillon["quantite"],
            "cout_unitaire": maillon["cout_unitaire"],
        }
        for maillon in historique
    ]
    _, erreur = registre_cible.ajouter_lot(mouvements)
    if erreur is not None:
        raise ValueError(f"registre_historique incohérent : {erreur}")
    return registre_cible


def receptionner_commande(
    bon_demande: dict[str, Any],
    reception_po: dict[str, Any],
    catalogue_materiaux: dict[str, Any] | None = None,
    seuils_reorder: list[dict[str, Any]] | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(registre_historique)
    resultat, code = materiel.enregistrer_reception(
        bon_demande, reception_po, catalogue_materiaux, registre_cible, seuils=seuils_reorder
    )
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, "registre_historique": registre_cible.lire()}


def consommer_materiaux(
    wct: dict[str, Any],
    formulaire: dict[str, Any],
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(registre_historique)
    resultat, code = materiel.consommer_materiaux(wct, formulaire, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, "registre_historique": registre_cible.lire()}


def soumettre_comptage(
    comptage: dict[str, Any], registre_historique: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(registre_historique)
    resultat, code = materiel.soumettre_comptage(comptage, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, "registre_historique": registre_cible.lire()}


def produire_digest(
    registre_historique: list[dict[str, Any]] | None = None,
    seuils_reorder: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(registre_historique)
    return digest.produire_digest_quotidien(registre_cible, seuils_reorder or [])


def resoudre_prix_materiau(
    materiau_id: str,
    catalogue_materiaux: dict[str, Any] | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(registre_historique)
    return catalogue_module.resoudre_prix(materiau_id, catalogue_materiaux, registre_cible)


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m6_receptionner_commande",
            description=(
                "Réceptionne une commande de bout en bout : résout le prix par ligne (catalogue -> "
                "historique -> indéterminé), écrit le stock reçu, calcule le verdict de réception "
                "(conforme/inférieure/supérieure/mixte), émet un signal à M5 si un montant est dû "
                "(jamais si indéterminé) et des suggestions de réapprovisionnement si un seuil est fourni."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "bon_demande": _BON_DEMANDE,
                    "reception_po": _RECEPTION_PO,
                    "catalogue_materiaux": _CATALOGUE,
                    "seuils_reorder": _SEUILS_REORDER,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["bon_demande", "reception_po"],
                "additionalProperties": False,
            },
            fonction=receptionner_commande,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_consommer_materiaux",
            description=(
                "Confirme une consommation de matériaux sur une intervention terrain (WCT de M4), "
                "décrémente le stock localisé du chantier. Refuse fail-closed si le stock disponible "
                "est insuffisant. La confirmation ne porte jamais de coût."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct": _WCT,
                    "formulaire": _FORMULAIRE_CONSOMMATION,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["wct", "formulaire"],
                "additionalProperties": False,
            },
            fonction=consommer_materiaux,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_soumettre_comptage",
            description=(
                "Compare un comptage physique au stock théorique dérivé du registre et enregistre le "
                "constat (AUCUN_ECART/STOCK_INFERIEUR/STOCK_SUPERIEUR/INDETERMINE). Jamais de cause "
                "ni de responsable attribué automatiquement (R-020)."
            ),
            parametres={
                "type": "object",
                "properties": {"comptage": _COMPTAGE, "registre_historique": _REGISTRE_HISTORIQUE},
                "required": ["comptage"],
                "additionalProperties": False,
            },
            fonction=soumettre_comptage,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_produire_digest",
            description=(
                "Digest quotidien déterministe : variances d'inventaire du registre et suggestions "
                "de réapprovisionnement recalculées contre les seuils fournis. Lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "registre_historique": _REGISTRE_HISTORIQUE,
                    "seuils_reorder": _SEUILS_REORDER,
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=produire_digest,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m6_resoudre_prix_materiau",
            description=(
                "Résout le coût unitaire d'un matériau : catalogue fourni -> dernier prix du "
                "registre -> indéterminé. Calcul pur, aucune écriture."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "materiau_id": {"type": "string"},
                    "catalogue_materiaux": _CATALOGUE,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["materiau_id"],
                "additionalProperties": False,
            },
            fonction=resoudre_prix_materiau,
            autonomie=Autonomie.T0,
        ),
    )
