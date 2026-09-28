"""Capacités d'agent du département M10 Mémoire.

Chaque outil enveloppe une fonction métier déterministe existante. `m10_journaliser_decision`
compose validation → écriture au registre Business → référence vérifiable en un seul appel ;
`m10_contexte_preflight` est le PREFLIGHT (D-014, docs/research/R4-memory-rag.md §10) qui
vérifie si un dossier de contexte est suffisant et, sinon, trace le refus au registre — sans
jamais interrompre l'appelant.

Deux registres DISTINCTS (CA-M10-06), chacun un singleton en mémoire du processus MCP de ce
département (même convention que m8_analytics/outils.py) : `_REGISTRE_FORGE` pour les
événements opérationnels (Work Completion Trigger de M4), `_REGISTRE_BUSINESS` pour les
décisions, révisions et traces de préflight. Aucune fonction ci-dessous n'accepte les deux
registres en argument.
"""

from __future__ import annotations

from typing import Any

from opsys.outils import Autonomie, Outil, depuis_couple

from . import contexte, contrats, decisions, registre, revision, wct

_REGISTRE_FORGE = registre.Registre()
_REGISTRE_BUSINESS = registre.Registre()
_REGISTRES_NOMMES = {"forge": _REGISTRE_FORGE, "business": _REGISTRE_BUSINESS}

_DECISION = {
    "type": "object",
    "properties": {
        "decision_id": {"type": "string"},
        "raison": {"type": "string", "description": "Obligatoire, non vide — règle 4 de la fiche source."},
        "statut": {"type": "string", "enum": list(contrats.STATUT_DECISION)},
        "options_ecartees": {"type": "string"},
    },
    "required": sorted(contrats.CHAMPS_DECISION),
    "additionalProperties": False,
}
_WCT = {
    "type": "object",
    "description": (
        "WorkCompletionTriggerV1 gelé par M4 (m4_field_ops/outbox.py), reçu TEL QUEL (12 "
        "champs exacts) — hash_maillon est la preuve de M4, JAMAIS recalculée par M10."
    ),
}
_DOSSIER_CONTEXTE = {
    "type": "object",
    "properties": {
        "evenement": {"type": "string"},
        "resume": {"type": "string"},
        "preuves": {"type": "string"},
        "impact": {"type": "string"},
        "prochaine_action": {"type": "string"},
        "references_decisions": {"type": "array", "items": {"type": "string"}},
    },
    "required": sorted(contrats.CHAMPS_EVENEMENT_MEMOIRE) + ["references_decisions"],
    "additionalProperties": False,
}
_REFERENCE_MEMOIRE = {
    "type": "object",
    "properties": {
        "ligne_id": {"type": "string"},
        "registre": {"type": "string", "enum": sorted(_REGISTRES_NOMMES)},
        "hash_tete": {"type": ["string", "null"]},
    },
    "required": sorted(contrats.CHAMPS_REFERENCE_MEMOIRE),
    "additionalProperties": False,
}


def journaliser_decision(decision: dict[str, Any], horodatage: str) -> dict[str, Any]:
    """Chaîne complète : validation (raison, statut) → écriture (registre Business) → référence.

    N'écrit rien si la décision est refusée (raison absente, statut hors énuméré).
    """
    maillon, code = decisions.enregistrer_decision(decision, _REGISTRE_BUSINESS, horodatage)
    if maillon is None:
        return {"etape": "validation", "accepte": False, "verdict": code}
    reference = contexte.construire_reference(maillon, "business", _REGISTRE_BUSINESS)
    return {"etape": "complet", "accepte": True, "decision": maillon, "reference": reference}


def contexte_preflight(dossier: dict[str, Any], horodatage: str) -> dict[str, Any]:
    """PREFLIGHT (D-014) : vérifie qu'un dossier de contexte est suffisant.

    Si insuffisant, trace le refus au registre Business et rend la main — n'interrompt jamais
    l'appelant, ne bloque aucune action à sa place (le hook applicatif est un GATED futur).
    """
    trace, code = contexte.tracer_refus_contexte(dossier, _REGISTRE_BUSINESS, horodatage)
    if trace is None and code is None:
        return {"suffisant": True, "verdict": None, "trace": None}
    return {"suffisant": False, "verdict": code, "trace": trace}


def memoriser_wct(wct_recu: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(wct.memoriser_wct(wct_recu, _REGISTRE_FORGE))


def signaler_revision(ligne_id_a: str, ligne_id_b: str, horodatage: str) -> dict[str, Any]:
    return depuis_couple(
        revision.signaler_revision(_REGISTRE_BUSINESS, ligne_id_a, ligne_id_b, horodatage)
    )


def arbitrer_revision(revision_ligne_id: str, statut: str, horodatage: str) -> dict[str, Any]:
    return depuis_couple(
        revision.arbitrer_revision(_REGISTRE_BUSINESS, revision_ligne_id, statut, horodatage)
    )


def statut_decision(decision_id: str) -> dict[str, Any]:
    """Statut courant, TOUJOURS calculé par relecture de la chaîne (jamais un champ positionnable)."""
    return {"statut": decisions.statut_courant(_REGISTRE_BUSINESS, decision_id)}


def statut_revision(revision_ligne_id: str) -> dict[str, Any]:
    return {"statut": revision.statut_revision(_REGISTRE_BUSINESS, revision_ligne_id)}


def verifier_reference(reference: dict[str, Any]) -> dict[str, Any]:
    """Vérifie une ReferenceMemoireM10 contre le registre qu'elle nomme (forge ou business)."""
    nom_registre = reference.get("registre") if isinstance(reference, dict) else None
    registre_cible = _REGISTRES_NOMMES.get(nom_registre)
    if registre_cible is None:
        return {"accepte": False, "verdict": "REJ-REFERENCE-REGISTRE-INCONNU-DE-L-OUTIL"}
    return depuis_couple(contexte.verifier_reference(reference, registre_cible))


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m10_journaliser_decision",
            description=(
                "Enregistre une décision motivée de bout en bout : validation (raison "
                "obligatoire, statut dans l'énuméré fermé) → écriture au registre Business → "
                "référence vérifiable. Refuse une décision sans raison non vide."
            ),
            parametres={
                "type": "object",
                "properties": {"decision": _DECISION, "horodatage": {"type": "string"}},
                "required": ["decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=journaliser_decision,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_contexte_preflight",
            description=(
                "PREFLIGHT : vérifie qu'un dossier de contexte (5 champs EvenementMemoire + au "
                "moins une référence de décision) est suffisant ; sinon trace le refus au "
                "registre et rend la main, sans jamais interrompre l'appelant."
            ),
            parametres={
                "type": "object",
                "properties": {"dossier": _DOSSIER_CONTEXTE, "horodatage": {"type": "string"}},
                "required": ["dossier", "horodatage"],
                "additionalProperties": False,
            },
            fonction=contexte_preflight,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_memoriser_wct",
            description=(
                "Consomme un Work Completion Trigger de M4 (12 champs exacts, 'M10' requis "
                "dans consommateurs_cibles) et le mémorise comme événement au registre Forge — "
                "le hash_maillon de M4 n'est jamais recalculé."
            ),
            parametres={
                "type": "object",
                "properties": {"wct_recu": _WCT},
                "required": ["wct_recu"],
                "additionalProperties": False,
            },
            fonction=memoriser_wct,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_signaler_revision",
            description=(
                "Signale une révision entre deux maillons EXISTANTS du registre Business (deux "
                "souvenirs qui se ressemblent, ou un fait devenu obsolète) — jamais une fusion."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "ligne_id_a": {"type": "string"},
                    "ligne_id_b": {"type": "string"},
                    "horodatage": {"type": "string"},
                },
                "required": ["ligne_id_a", "ligne_id_b", "horodatage"],
                "additionalProperties": False,
            },
            fonction=signaler_revision,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_arbitrer_revision",
            description=(
                "Consigne l'arbitrage humain d'une révision SIGNALÉE (jamais une fusion ni une "
                "mutation) ; refuse un statut hors énuméré ou une révision qui n'a jamais été "
                "signalée."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "revision_ligne_id": {"type": "string"},
                    "statut": {"type": "string", "enum": list(contrats.STATUT_REVISION)},
                    "horodatage": {"type": "string"},
                },
                "required": ["revision_ligne_id", "statut", "horodatage"],
                "additionalProperties": False,
            },
            fonction=arbitrer_revision,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_statut_decision",
            description="Statut courant d'une décision, calculé par relecture du registre Business (jamais un champ positionnable).",
            parametres={
                "type": "object",
                "properties": {"decision_id": {"type": "string"}},
                "required": ["decision_id"],
                "additionalProperties": False,
            },
            fonction=statut_decision,
        ),
        Outil(
            nom="m10_statut_revision",
            description="Statut d'une révision (dernier arbitrage connu, ou 'en_attente' si seulement signalée).",
            parametres={
                "type": "object",
                "properties": {"revision_ligne_id": {"type": "string"}},
                "required": ["revision_ligne_id"],
                "additionalProperties": False,
            },
            fonction=statut_revision,
        ),
        Outil(
            nom="m10_verifier_reference",
            description=(
                "Vérifie qu'une ReferenceMemoireM10 désigne un maillon réellement écrit sur une "
                "chaîne intacte (registre, ligne_id et hash_tete cohérents) — détecte une "
                "référence forgée."
            ),
            parametres={
                "type": "object",
                "properties": {"reference": _REFERENCE_MEMOIRE},
                "required": ["reference"],
                "additionalProperties": False,
            },
            fonction=verifier_reference,
        ),
    )
