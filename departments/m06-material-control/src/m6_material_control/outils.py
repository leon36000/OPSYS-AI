"""Capacités d'agent du département M6 Material Control.

Chaque outil enveloppe l'orchestrateur unique `materiel.py` (seul point d'écriture par
type de mouvement — RECEPTION/CONSOMMATION/VARIANCE_INVENTAIRE, DA-M6-11 ; RETOUR/PERTE/
BRIS depuis PLAN T1.1-d2, garde_ecriture_stock de conformite.py). `m6_receptionner_commande`
compose de bout en bout : réception -> écriture du stock -> résolution de prix -> variance
de réception -> signal à M5 -> suggestion de réapprovisionnement, en un seul appel.
`m6_declarer_materiaux_utilises` (PLAN T1.1-d2) fait de même pour la fin de chantier :
formulaire enrichi -> mouvements typés (CONSOMMATION/RETOUR/PERTE/BRIS) -> stock théorique
cohérent, idempotent par wct_id.

Le registre (append-only hash-chaîné) est durable en production (ADR-0009) : à l'intérieur de la
transaction que `Capacites.appeler`/`executer_atomique` ouvre pour chaque appel d'outil (point de
passage unique), chaque fonction ci-dessous lit et écrit le registre durable du département via
`opsys.stockage.maillons` — plus besoin que l'appelant transporte un historique. Hors transaction
(appel direct de ce module, tests unitaires du département, qui ne montent aucune base) :
comportement historique inchangé — l'appelant transmet l'historique renvoyé par le précédent appel
dans `registre_historique` ; ce module le rejoue pour retrouver un registre en mémoire valide et
chaîné avant d'y écrire la suite. `registre.py` reste pur (aucun import `opsys`/SQLAlchemy) : c'est
ici, et seulement ici, que le paquet touche `opsys.stockage`.

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

from opsys import stockage
from opsys.outils import Autonomie, Outil

from . import catalogue as catalogue_module
from . import digest, materiel, variance_chantier
from . import registre as registre_module

_DEPARTEMENT = "m06-material-control"
_NOM_REGISTRE = "principal"

_MAILLON = {"type": "object", "description": "Maillon tel que renvoyé par un appel précédent."}
_REGISTRE_HISTORIQUE = {
    "type": "array",
    "items": _MAILLON,
    "description": (
        "À omettre : le registre M6 est durable et relu par l'outil. Ne sert qu'aux appels directs "
        "hors transaction, qui retransmettent l'historique renvoyé par l'appel précédent."
    ),
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
_BESOIN_ESTIME_CHANTIER = {
    "type": "object",
    "description": "BesoinEstimeChantier : ce que M3 a estimé pour ce matériau sur ce chantier.",
    "properties": {
        "materiau_id": {"type": "string"},
        "quantite_estimee": {"type": "number"},
        "unite": {"type": "string"},
    },
    "required": ["materiau_id", "quantite_estimee", "unite"],
}
_BESOINS_ESTIMES_CHANTIER = {"type": "array", "items": _BESOIN_ESTIME_CHANTIER}
_LIGNE_DECLAREE_CHANTIER = {
    "type": "object",
    "description": (
        "Ligne du formulaire de fin de chantier enrichi (materiel.soumettre_materiaux_utilises) : "
        "type_ligne parmi prevu/non_prevu/retour/perte/bris/achat_terrain, materiau_id, quantite, "
        "unite ; quantite_estimee en plus si prevu ; photo_fournie et recu_fourni en plus si "
        "achat_terrain (au moins l'un des deux requis)."
    ),
    "properties": {
        "type_ligne": {
            "type": "string",
            "enum": ["prevu", "non_prevu", "retour", "perte", "bris", "achat_terrain"],
        },
        "materiau_id": {"type": "string"},
        "quantite": {"type": "number"},
        "unite": {"type": "string"},
        "quantite_estimee": {"type": "number"},
        "photo_fournie": {"type": "boolean"},
        "recu_fourni": {"type": "boolean"},
    },
    "required": ["type_ligne", "materiau_id", "quantite", "unite"],
}
_LIGNES_DECLAREES_CHANTIER = {"type": "array", "items": _LIGNE_DECLAREE_CHANTIER}
_FORMULAIRE_MATERIAUX_UTILISES = {
    "type": "object",
    "description": "Formulaire de fin de chantier enrichi (M6.10/M6.11), 6 types de ligne.",
    "properties": {
        "wct_id": {"type": "string"},
        "intervention_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_materiaux": {"type": "array", "items": _LIGNE_DECLAREE_CHANTIER},
    },
    "required": ["wct_id", "intervention_id", "chantier_id", "lignes_materiaux"],
}


def _rejouer_registre(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Reconstruit le registre M6 en rejouant l'historique fourni par l'appelant
    (mêmes maillons, même ordre -> mêmes hachages : reconstruction fidèle, pas une
    vérification contre une vérité externe que ce paquet ne détient pas).

    PLAN T1.1-d2 : wct_id, quand un maillon en porte un, est repris tel quel — sinon la
    rejoue perdrait l'idempotence (materiel.soumettre_materiaux_utilises) et le ciblage
    par wct_id (variance_chantier.comparer_depuis_registre) dès le deuxième appel hors
    transaction. Absent (tous les maillons antérieurs à PLAN T1.1-d2), rien ne change :
    même reconstruction qu'avant.
    """
    registre_cible = registre_module.Registre()
    historique = historique or []
    if not historique:
        return registre_cible
    mouvements = []
    for maillon in historique:
        mouvement = {
            "type_mouvement": maillon["type_mouvement"],
            "chantier_id": maillon["chantier_id"],
            "materiau_id": maillon["materiau_id"],
            "quantite": maillon["quantite"],
            "cout_unitaire": maillon["cout_unitaire"],
        }
        if "wct_id" in maillon:
            mouvement["wct_id"] = maillon["wct_id"]
        mouvements.append(mouvement)
    _, erreur = registre_cible.ajouter_lot(mouvements)
    if erreur is not None:
        raise ValueError(f"registre_historique incohérent : {erreur}")
    return registre_cible


def _registre_de_l_appel(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Registre à utiliser pour CET appel.

    À l'intérieur de la transaction que `Capacites.appeler`/`executer_atomique` ouvre pour chaque
    appel d'outil (ADR-0009, point de passage unique) : le registre durable du département fait
    autorité — `stockage.maillons(...)`, rien à rejouer, c'est le registre de PRODUCTION, et
    `ajouter`/`ajouter_lot` s'y exécutent dans cette même transaction (tout ou rien). Hors
    transaction (appel direct des fonctions de ce module, tests unitaires du département qui ne
    montent aucune base) : comportement historique inchangé, `_rejouer_registre` reconstruit un
    registre en mémoire depuis `registre_historique`.
    """
    if stockage.connexion_courante() is not None:
        return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return _rejouer_registre(historique)


def _etat_registre(registre_cible: registre_module.Registre) -> dict[str, Any]:
    """Ce que la réponse dit du registre après l'appel.

    Registre durable (production) : la tête de chaîne et la taille, jamais l'historique complet,
    qui grossit sans limite et coûterait des tokens à chaque appel. Hors transaction : l'historique
    complet, que l'appelant doit retransmettre au prochain appel (contrat historique).
    """
    if stockage.connexion_courante() is not None:
        return {"registre": {"taille": registre_cible.taille(), "hash_tete": registre_cible.hash_tete()}}
    return {"registre_historique": registre_cible.lire()}


def receptionner_commande(
    bon_demande: dict[str, Any],
    reception_po: dict[str, Any],
    catalogue_materiaux: dict[str, Any] | None = None,
    seuils_reorder: list[dict[str, Any]] | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.enregistrer_reception(
        bon_demande, reception_po, catalogue_materiaux, registre_cible, seuils=seuils_reorder
    )
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def consommer_materiaux(
    wct: dict[str, Any],
    formulaire: dict[str, Any],
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.consommer_materiaux(wct, formulaire, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def declarer_materiaux_utilises(
    wct: dict[str, Any],
    formulaire: dict[str, Any],
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """PLAN T1.1-d2 point 2. En transaction (production) : registre durable, réponse
    tête + taille seulement (_etat_registre), comme les autres outils d'écriture."""
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.soumettre_materiaux_utilises(wct, formulaire, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def soumettre_comptage(
    comptage: dict[str, Any], registre_historique: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.soumettre_comptage(comptage, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def produire_digest(
    registre_historique: list[dict[str, Any]] | None = None,
    seuils_reorder: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    return digest.produire_digest_quotidien(registre_cible, seuils_reorder or [])


def resoudre_prix_materiau(
    materiau_id: str,
    catalogue_materiaux: dict[str, Any] | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    return catalogue_module.resoudre_prix(materiau_id, catalogue_materiaux, registre_cible)


def evaluer_variance_chantier(
    chantier_id: str,
    besoins_estimes: list[dict[str, Any]],
    seuil_pourcentage: float,
    lignes_declarees: list[dict[str, Any]] | None = None,
    wct_id: str | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """PLAN T1.1-d/d2 points 2 et 3. variance_chantier.evaluer n'écrit jamais le registre
    (T0, lecture/calcul pur) mais peut désormais le LIRE (PLAN T1.1-d2 point 3) : le
    registre est donc toujours résolu (comme m6_produire_digest/m6_resoudre_prix_materiau,
    d'autres outils T0 qui lisent sans écrire), et utilisé seulement si `lignes_declarees`
    est omis. `lignes_declarees` explicite reste utilisable tel quel (entrée directe
    gardée, comme demandé)."""
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = variance_chantier.evaluer(
        chantier_id,
        besoins_estimes,
        lignes_declarees,
        seuil_pourcentage,
        registre=registre_cible,
        wct_id=wct_id,
    )
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat}


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
            nom="m6_declarer_materiaux_utilises",
            description=(
                "Déclare le formulaire de fin de chantier enrichi (M6.10/M6.11 ; lignes typées "
                "prévu/non prévu/retour/perte/bris/achat terrain — achat terrain refusé fail-closed "
                "sans photo ni reçu) et l'écrit au registre : CONSOMMATION pour prévu/non prévu/achat "
                "terrain, RETOUR pour un retour (réintègre le stock), PERTE/BRIS pour une perte ou un "
                "bris (sortent du stock sans être une consommation de chantier). Même règle de coût "
                "unitaire fail-closed que m6_consommer_materiaux, aucun coût inventé. Idempotente par "
                "wct_id : une seconde déclaration pour le même WCT est refusée nommément, jamais "
                "réécrite. Distincte de m6_consommer_materiaux, qui garde son contrat "
                "{materiau_id, quantite} exact et n'est pas remplacé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct": _WCT,
                    "formulaire": _FORMULAIRE_MATERIAUX_UTILISES,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["wct", "formulaire"],
                "additionalProperties": False,
            },
            fonction=declarer_materiaux_utilises,
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
        Outil(
            nom="m6_evaluer_variance_chantier",
            description=(
                "Compare les besoins matériaux estimés (M3, toujours fournis en entrée) au réel "
                "déclaré au formulaire de fin de chantier enrichi (lignes typées prévu/non prévu/"
                "retour/perte/bris/achat terrain) et calcule un verdict neutre par matériau. Le réel "
                "vient soit de lignes_declarees fourni explicitement, soit — si omis — relu "
                "directement au registre pour wct_id (une déclaration précise) ou chantier_id seul "
                "(tout le réel déclaré du chantier), déjà écrit par m6_declarer_materiaux_utilises. Ne "
                "classe jamais la cause : cause_possible reste toujours null (classification humaine "
                "uniquement parmi les 6 causes nommées de la définition produit, jamais « vol ») et "
                "classification_requise indique si un écart attend cette classification. Émet "
                "SignalVarianceChantierCritique quand l'écart d'au moins un matériau atteint ou "
                "dépasse seuil_pourcentage, toujours fourni par l'appelant, jamais codé en dur. M6 "
                "signale seulement : ce signal ne modifie jamais le statut du chantier côté M4. "
                "Lecture et calcul purs, aucune écriture au registre."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "chantier_id": {"type": "string"},
                    "besoins_estimes": _BESOINS_ESTIMES_CHANTIER,
                    "lignes_declarees": {
                        **_LIGNES_DECLAREES_CHANTIER,
                        "description": (
                            "Réel déclaré explicite. À omettre pour lire le réel directement au "
                            "registre (wct_id ou chantier_id seul) plutôt que de le retransporter."
                        ),
                    },
                    "wct_id": {
                        "type": "string",
                        "description": (
                            "Utilisé seulement quand lignes_declarees est omis : cible une seule "
                            "déclaration au registre. Omis avec lignes_declarees : agrège tout le réel "
                            "déclaré du chantier."
                        ),
                    },
                    "seuil_pourcentage": {
                        "type": "number",
                        "description": (
                            "Fraction (0.40 = 40 %). Toujours fourni par l'appelant : aucune valeur "
                            "par défaut n'existe dans le code."
                        ),
                    },
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["chantier_id", "besoins_estimes", "seuil_pourcentage"],
                "additionalProperties": False,
            },
            fonction=evaluer_variance_chantier,
            autonomie=Autonomie.T0,
        ),
    )
