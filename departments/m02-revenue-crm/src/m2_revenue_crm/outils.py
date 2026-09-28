"""Capacités d'agent du département M2 Revenue CRM.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. `m2_ingerer_lead` compose la chaîne complète (validation structurelle et
frontières → écriture → dédoublonnage → statut → readiness) en un seul appel, ce
qui évite à l'agent plusieurs allers-retours et garantit l'ordre des contrôles —
en particulier qu'un doublon probable est toujours signalé à l'ingestion
(correctif d'audit), jamais fusionné : la fusion n'existe nulle part dans ce
paquet, l'arbitrage humain se limite à confirmer deux dossiers distincts.

État partagé : ce module tient le registre du département, partagé par tous les
outils (ingestion, statuts, doublons, interactions, readiness, digest). En
production, il est adossé au stockage durable de l'instance (ADR-0009) via
`opsys.stockage.maillons(...)`, relu à chaque appel et jamais touché au
chargement du module. `reinitialiser_registre()` (réservé aux tests) le bascule
sur un registre EN MÉMOIRE vide ; `utiliser_stockage_durable()` revient au
stockage durable. Ce module est l'unique endroit du département qui connaît
`opsys` au-delà du contrat `Outil` — `registre.py` reste pur (ni `opsys` ni
SQLAlchemy).
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil

from . import contrats, digest, doublons, ingestion, interactions, readiness, statuts
from .registre import Registre

_DEPARTEMENT = "m02-revenue-crm"
_NOM_REGISTRE = "principal"

_registre_memoire = Registre()
_stockage_durable_actif = True


def reinitialiser_registre() -> None:
    """Réinitialise le registre partagé du département sur un registre EN MÉMOIRE vide
    (réservé aux tests). Annule aussi un éventuel branchement sur le stockage durable :
    après cet appel, `_obtenir_registre()` revient toujours à la mémoire."""
    global _registre_memoire, _stockage_durable_actif
    _registre_memoire = Registre()
    _stockage_durable_actif = False


def utiliser_stockage_durable() -> None:
    """Revient au registre de production, adossé au stockage durable de l'instance (ADR-0009) :
    `opsys.stockage.maillons("m02-revenue-crm", "principal")`, dans la base et la transaction de
    l'appel courant (`opsys.outils.executer_atomique` en ouvre une autour de chaque appel
    d'outil). C'est l'état au chargement du module ; les tests l'utilisent après
    `reinitialiser_registre()`."""
    global _stockage_durable_actif
    _stockage_durable_actif = True


def _obtenir_registre() -> Registre:
    if _stockage_durable_actif:
        # Jamais de cache ici, à dessein (même principe que `opsys.stockage.maillons`) : une
        # instance fraîche à chaque appel relit l'état réel depuis la base, pour ne jamais figer
        # une empreinte devenue périmée entre deux appels d'outil (concurrence, autre processus).
        return Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return _registre_memoire


# ---------------------------------------------------------------------------
# Fonctions enveloppes — chacune appelle le code métier existant tel quel.
# ---------------------------------------------------------------------------


def ingerer_lead(contrat: dict[str, Any], horodatage: str) -> dict[str, Any]:
    """Ingestion de bout en bout : validation + frontières (ingestion.ingerer),
    dédoublonnage (chaque doublon détecté à l'ingestion est signalé, jamais
    fusionné — correctif d'audit PRD §2b), statut courant, readiness pour M3."""
    reg = _obtenir_registre()
    accuse, verdict = ingestion.ingerer(contrat, reg, horodatage)
    if verdict is not None:
        return {"etape": "ingestion", "accepte": False, "verdict": verdict}

    lead_id = contrat["lead_id"]
    doublons_signales = []
    for autre_lead_id in accuse["doublons_detectes"]:
        signalement, verdict_doublon = doublons.signaler(reg, lead_id, autre_lead_id, horodatage)
        if verdict_doublon is None:
            doublons_signales.append(signalement)

    return {
        "etape": "complet",
        "accepte": True,
        "lead_id": lead_id,
        "accuse_ingestion": accuse,
        "doublons_signales": doublons_signales,
        "statut": statuts.statut_courant(reg, lead_id),
        "pret_pour_m3": readiness.evaluer(reg, lead_id),
    }


def transitionner_statut(
    lead_id: str,
    statut_cible: str,
    horodatage: str,
    owner: str | None = None,
    prochaine_action: dict[str, Any] | None = None,
    reference_devis_m3: str | None = None,
    motif: str | None = None,
) -> dict[str, Any]:
    accuse, verdict = statuts.transitionner(
        lead_id, statut_cible, _obtenir_registre(), horodatage,
        owner=owner, prochaine_action=prochaine_action,
        reference_devis_m3=reference_devis_m3, motif=motif,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def detecter_doublons(lead_id: str) -> list[str]:
    return doublons.detecter(_obtenir_registre(), lead_id)


def signaler_doublon(lead_id_a: str, lead_id_b: str, horodatage: str) -> dict[str, Any]:
    signalement, verdict = doublons.signaler(_obtenir_registre(), lead_id_a, lead_id_b, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": signalement}


def arbitrer_doublon(signalement_id: str, decision: str, horodatage: str) -> dict[str, Any]:
    accuse, verdict = doublons.arbitrer(_obtenir_registre(), signalement_id, decision, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def enregistrer_interaction(lead_id: str, auteur: str, resume: str, horodatage: str) -> dict[str, Any]:
    accuse, verdict = interactions.enregistrer(lead_id, auteur, resume, _obtenir_registre(), horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def evaluer_readiness(lead_id: str, horodatage: str) -> dict[str, Any]:
    """Émet le marqueur de readiness (aucune écriture au registre) : soit le lead
    satisfait déjà les quatre conditions et le marqueur est signé, soit un
    verdict détaille précisément ce qui manque."""
    marqueur, verdict = readiness.emettre_marqueur(_obtenir_registre(), lead_id, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": marqueur}


def produire_digest(date_jour: str, horodatage: str) -> str:
    return digest.produire_digest(_obtenir_registre(), date_jour, horodatage)


# ---------------------------------------------------------------------------
# Schémas JSON partagés
# ---------------------------------------------------------------------------

_CONTACT = {
    "type": "object",
    "properties": {cle: {"type": "string"} for cle in contrats.CLES_CONTACT},
    "additionalProperties": False,
}
_CONTRAT = {
    "type": "object",
    "description": "Contrat gelé transmis par le module amont (les sept champs exacts, aucun de plus).",
    "properties": {
        "lead_id": {"type": "string"},
        "conversation_id": {"type": "string"},
        "contact": _CONTACT,
        "type_travaux": {"type": "string", "enum": list(contrats.TYPES_TRAVAUX)},
        "ville": {"type": "string"},
        "urgence_declaree": {"type": "boolean"},
        "canal": {"type": "string", "enum": list(contrats.CANAUX)},
    },
    "required": list(contrats.CHAMPS_CONTRAT_GELE),
    "additionalProperties": False,
}
_HORODATAGE = {"type": "string", "description": "ISO-8601 avec fuseau horaire, fourni par l'appelant"}
_PROCHAINE_ACTION = {
    "type": ["object", "null"],
    "description": "{description (non vide), echeance (ISO-8601 avec fuseau)} — jamais générée par ce module",
}


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m2_ingerer_lead",
            description=(
                "Ingère un lead qualifié de bout en bout : validation structurelle et frontières de "
                "vérité, écriture au registre, détection ET signalement des doublons probables (jamais "
                "de fusion), statut courant, readiness pour M3."
            ),
            parametres={
                "type": "object",
                "properties": {"contrat": _CONTRAT, "horodatage": _HORODATAGE},
                "required": ["contrat", "horodatage"],
                "additionalProperties": False,
            },
            fonction=ingerer_lead,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_transitionner_statut",
            description=(
                "Transitionne le statut d'un lead (nouveau→qualifie, qualifie→converti, "
                "qualifie→perdu, nouveau→perdu). Chaque transition exige les données humaines "
                "correspondantes (owner+prochaine_action, ou reference_devis_m3, ou motif) ; jamais "
                "générées par cet outil."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "statut_cible": {"type": "string", "enum": list(statuts.STATUTS)},
                    "horodatage": _HORODATAGE,
                    "owner": {"type": ["string", "null"]},
                    "prochaine_action": _PROCHAINE_ACTION,
                    "reference_devis_m3": {"type": ["string", "null"]},
                    "motif": {"type": ["string", "null"]},
                },
                "required": ["lead_id", "statut_cible", "horodatage"],
                "additionalProperties": False,
            },
            fonction=transitionner_statut,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_detecter_doublons",
            description="Liste les lead_id déjà ingérés qui sont des doublons probables du lead donné (lecture pure).",
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}},
                "required": ["lead_id"],
                "additionalProperties": False,
            },
            fonction=detecter_doublons,
        ),
        Outil(
            nom="m2_signaler_doublon",
            description="Inscrit un signalement de doublon potentiel entre deux leads, en attente d'arbitrage humain.",
            parametres={
                "type": "object",
                "properties": {
                    "lead_id_a": {"type": "string"},
                    "lead_id_b": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["lead_id_a", "lead_id_b", "horodatage"],
                "additionalProperties": False,
            },
            fonction=signaler_doublon,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_arbitrer_doublon",
            description=(
                "Consigne l'arbitrage humain d'un signalement de doublon. Seule décision possible en "
                "v1 : 'distincts_confirmes' (les deux leads restent des dossiers séparés)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signalement_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["distincts_confirmes"]},
                    "horodatage": _HORODATAGE,
                },
                "required": ["signalement_id", "decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=arbitrer_doublon,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_enregistrer_interaction",
            description="Enregistre une interaction commerciale humaine réelle pour un lead actif (non clos).",
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "auteur": {"type": "string"},
                    "resume": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["lead_id", "auteur", "resume", "horodatage"],
                "additionalProperties": False,
            },
            fonction=enregistrer_interaction,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_evaluer_readiness",
            description=(
                "Évalue si un lead qualifié est prêt pour M3 (owner, type de travaux valide, ville, "
                "interaction post-qualification). Émet un marqueur signé si oui, sinon un verdict "
                "détaillant précisément ce qui manque. Ne modifie jamais le registre."
            ),
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}, "horodatage": _HORODATAGE},
                "required": ["lead_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=evaluer_readiness,
        ),
        Outil(
            nom="m2_produire_digest",
            description="Produit le digest déterministe du pipeline commercial, reconstruit à la date_jour donnée.",
            parametres={
                "type": "object",
                "properties": {"date_jour": {"type": "string"}, "horodatage": _HORODATAGE},
                "required": ["date_jour", "horodatage"],
                "additionalProperties": False,
            },
            fonction=produire_digest,
        ),
    )
