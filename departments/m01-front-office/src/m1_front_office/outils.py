"""Capacités d'agent du département M1 Front Office.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. `m1_traiter_demande_entrante` compose la chaîne complète (provenance →
registre anti-perte → consentement → qualification) en un seul appel, ce qui évite
à l'agent plusieurs allers-retours et garantit l'ordre des contrôles — en
particulier que TOUT signal entrant laisse une ligne au registre, qualifié ou non
(M1-R-10), et qu'aucun contenu externe n'est traité avant d'être passé par le
filtre de provenance (M1-R-08).

État partagé : ce module tient un registre en mémoire, partagé par tous les
outils qui écrivent ou lisent l'historique du département (signal unique par
demande, phases voix, digest). `reinitialiser_registre()` n'est pas un outil
d'agent : c'est un point d'entrée réservé aux tests, pour repartir d'un état
propre entre deux scénarios.
"""

from __future__ import annotations

from typing import Any

from opsys.outils import Autonomie, Outil

from . import adaptateurs, consentement, contrats, digest, garde_fou, phases_voix, provenance, qualification
from .phases_voix import TransitionInterdite
from .registre import Registre

_CANAUX = ("telephone", "courriel", "formulaire", "texte")

_registre = Registre()


def reinitialiser_registre() -> None:
    """Réinitialise le registre partagé du département (réservé aux tests)."""
    global _registre
    _registre = Registre()


def _obtenir_registre() -> Registre:
    return _registre


# ---------------------------------------------------------------------------
# Fonctions enveloppes — chacune appelle le code métier existant tel quel.
# ---------------------------------------------------------------------------


def filtrer_provenance(contenu_brut: str) -> dict[str, Any]:
    contenu_filtre, sain = provenance.filtrer(contenu_brut)
    return {"contenu_filtre": contenu_filtre, "sain": sain}


def qualifier_signal(
    contenu_filtre: str, canal: str, conversation_id: str, zone_desservie: list[str]
) -> dict[str, Any]:
    return qualification.qualifier(contenu_filtre, canal, conversation_id, zone_desservie)


def verifier_garde_fou(texte: str) -> dict[str, Any]:
    return garde_fou.verifier_sortie(texte)


def verifier_consentement_signal(consentement_enregistrement: str | None = None) -> dict[str, Any]:
    return consentement.verifier_consentement({"consentement_enregistrement": consentement_enregistrement})


def ouvrir_conversation(signal_id: str, horodatage: str) -> dict[str, Any]:
    resultat = phases_voix.ouvrir_conversation(signal_id, horodatage, _obtenir_registre())
    if "conversation_id" not in resultat:
        # phases_voix renvoie un verdict nu (pas un couple) sur horodatage invalide.
        return {"accepte": False, "verdict": resultat}
    return {"accepte": True, "resultat": resultat}


def transitionner_phase(conversation: dict[str, Any], phase_cible: int, horodatage: str) -> dict[str, Any]:
    """Fait progresser une conversation d'une phase. `conversation` est l'objet
    renvoyé par `m1_ouvrir_conversation` (ou une transition précédente), à
    reporter tel quel — jamais reconstruit de mémoire par l'agent."""
    try:
        verdict = phases_voix.transitionner(conversation, phase_cible, horodatage, _obtenir_registre())
    except TransitionInterdite as exc:
        # phases_voix lève sur violation plutôt que de renvoyer un couple : on
        # traduit ici vers le même patron (accepte, verdict) que le reste des
        # outils, pour que l'agent n'ait qu'une seule forme de réponse à lire.
        return {"accepte": False, "verdict": exc.verdict, "conversation": conversation}
    if verdict.get("code") != "OK":
        return {"accepte": False, "verdict": verdict, "conversation": conversation}
    return {"accepte": True, "verdict": verdict, "conversation": conversation}


def abandonner_conversation(conversation: dict[str, Any], horodatage: str) -> dict[str, Any]:
    verdict = phases_voix.abandonner(conversation, horodatage, _obtenir_registre())
    if verdict.get("code") != "OK":
        return {"accepte": False, "verdict": verdict, "conversation": conversation}
    return {"accepte": True, "verdict": verdict, "conversation": conversation}


def produire_digest(date_reference: str) -> str:
    return digest.produire_digest(_obtenir_registre().lire(), date_reference)


def emettre_notification(canal: str, message: str) -> dict[str, Any]:
    """Émet un message vers un canal externe (bus de notification en mode ombre).
    Action T2 : réversible, mais externe — jamais présentée comme faite avant
    l'approbation humaine effective en mode ombre/supervisé."""
    bus = adaptateurs.creer_bus(mode_ombre=True)
    resultat = bus.emettre(canal, message)
    if isinstance(resultat, dict):
        return {"accepte": False, "verdict": resultat}
    return {"accepte": True, "resultat": {"message_id": resultat}}


def traiter_demande_entrante(
    contenu_brut: str,
    canal: str,
    conversation_id: str,
    signal_id: str,
    horodatage: str,
    zone_desservie: list[str],
    consentement_enregistrement: str | None = None,
) -> dict[str, Any]:
    """Chaîne complète d'une demande entrante : provenance → registre anti-perte
    → consentement (si vocal) → qualification → décision de routage.

    Chaque signal produit exactement une ligne au registre anti-perte (M1-R-10),
    qu'il soit qualifié ou non : un client qui ne fournit pas assez d'informations
    n'est jamais perdu, seulement redirigé vers une demande de précisions.
    """
    reg = _obtenir_registre()

    # 1. Provenance : neutralise toute tentative d'injection AVANT tout traitement
    #    (M1-R-08 — un contenu externe n'est jamais fiable tel quel).
    contenu_filtre, sain = provenance.filtrer(contenu_brut)

    # 2. Registre anti-perte : une ligne immuable, qualifié ou non.
    ligne_id_signal = reg.ajouter({
        "type_entree": "signal",
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "contenu_filtre": contenu_filtre,
        "provenance_saine": sain,
    })

    # 3. Consentement : uniquement pertinent pour un canal vocal (M1-R-07).
    verdict_consentement = None
    if canal == "telephone":
        verdict_consentement = consentement.verifier_consentement(
            {"consentement_enregistrement": consentement_enregistrement},
            registre=reg,
            horodatage=horodatage,
        )

    # 4. Qualification par règles déterministes, zéro LLM, zéro ville inventée.
    resultat_qualif = qualification.qualifier(contenu_filtre, canal, conversation_id, zone_desservie)
    if "verdict" in resultat_qualif:
        return {
            "etape": "qualification",
            "accepte": True,
            "signal_ligne_id": ligne_id_signal,
            "provenance_saine": sain,
            "consentement": verdict_consentement,
            "qualifie": False,
            "verdict_qualification": resultat_qualif["verdict"],
            "decision": "DEMANDER_PRECISIONS",
        }

    # 5. Décision : lead conforme au contrat gelé M1->M2 (vérification défensive :
    #    qualifier() garantit déjà la conformité, valider_lead le confirme et
    #    lèverait sinon — fail-closed, jamais silencieux).
    contrats.valider_lead(resultat_qualif)

    ligne_id_lead = reg.ajouter({
        "type_entree": "lead_emis",
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "lead": resultat_qualif,
    })

    return {
        "etape": "decision",
        "accepte": True,
        "signal_ligne_id": ligne_id_signal,
        "provenance_saine": sain,
        "consentement": verdict_consentement,
        "qualifie": True,
        "lead": resultat_qualif,
        "lead_ligne_id": ligne_id_lead,
        "decision": "TRANSMETTRE_M2",
    }


# ---------------------------------------------------------------------------
# Schémas JSON partagés
# ---------------------------------------------------------------------------

_CANAL = {"type": "string", "enum": list(_CANAUX)}
_ZONE_DESSERVIE = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Villes desservies par l'entreprise (configuration métier, jamais devinée).",
}
_CONVERSATION = {
    "type": "object",
    "description": "Objet conversation renvoyé par m1_ouvrir_conversation ou une transition précédente.",
}


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m1_traiter_demande_entrante",
            description=(
                "Traite une demande entrante de bout en bout : filtre la provenance, inscrit le "
                "signal au registre anti-perte, vérifie le consentement si canal=telephone, qualifie "
                "par règles déterministes et décide du routage (précisions à demander ou transmission "
                "à M2). Aucune ville hors de zone_desservie n'est reconnue."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contenu_brut": {"type": "string"},
                    "canal": _CANAL,
                    "conversation_id": {"type": "string"},
                    "signal_id": {"type": "string"},
                    "horodatage": {"type": "string", "description": "ISO-8601 avec fuseau horaire"},
                    "zone_desservie": _ZONE_DESSERVIE,
                    "consentement_enregistrement": {
                        "type": ["string", "null"],
                        "description": "'accorde' ou autre ; pertinent seulement si canal=telephone",
                    },
                },
                "required": [
                    "contenu_brut", "canal", "conversation_id", "signal_id", "horodatage", "zone_desservie",
                ],
                "additionalProperties": False,
            },
            fonction=traiter_demande_entrante,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_filtrer_provenance",
            description="Neutralise toute tentative d'injection dans un contenu externe brut.",
            parametres={
                "type": "object",
                "properties": {"contenu_brut": {"type": "string"}},
                "required": ["contenu_brut"],
                "additionalProperties": False,
            },
            fonction=filtrer_provenance,
        ),
        Outil(
            nom="m1_qualifier_signal",
            description=(
                "Extrait type de travaux, ville (dans zone_desservie) et urgence déclarée d'un "
                "contenu déjà filtré. Ne renvoie qu'un lead complet ou un verdict de rejet."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contenu_filtre": {"type": "string"},
                    "canal": _CANAL,
                    "conversation_id": {"type": "string"},
                    "zone_desservie": _ZONE_DESSERVIE,
                },
                "required": ["contenu_filtre", "canal", "conversation_id", "zone_desservie"],
                "additionalProperties": False,
            },
            fonction=qualifier_signal,
        ),
        Outil(
            nom="m1_verifier_garde_fou",
            description="Vérifie qu'un texte destiné au client ne contient ni prix, ni date, ni engagement, ni aveu.",
            parametres={
                "type": "object",
                "properties": {"texte": {"type": "string"}},
                "required": ["texte"],
                "additionalProperties": False,
            },
            fonction=verifier_garde_fou,
        ),
        Outil(
            nom="m1_verifier_consentement",
            description="Vérifie si le consentement explicite à l'enregistrement a été accordé ('accorde' uniquement).",
            parametres={
                "type": "object",
                "properties": {
                    "consentement_enregistrement": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
            fonction=verifier_consentement_signal,
        ),
        Outil(
            nom="m1_ouvrir_conversation",
            description="Ouvre une conversation vocale en phase 0 et inscrit son ouverture au registre.",
            parametres={
                "type": "object",
                "properties": {
                    "signal_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                },
                "required": ["signal_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=ouvrir_conversation,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_transitionner_phase",
            description=(
                "Fait progresser une conversation vocale vers la phase suivante (0→5), strictement "
                "linéaire : toute tentative de saut fige la conversation."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "conversation": _CONVERSATION,
                    "phase_cible": {"type": "integer"},
                    "horodatage": {"type": "string"},
                },
                "required": ["conversation", "phase_cible", "horodatage"],
                "additionalProperties": False,
            },
            fonction=transitionner_phase,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_abandonner_conversation",
            description="Clôt une conversation vocale abandonnée avant la phase 5, proprement tracée au registre.",
            parametres={
                "type": "object",
                "properties": {
                    "conversation": _CONVERSATION,
                    "horodatage": {"type": "string"},
                },
                "required": ["conversation", "horodatage"],
                "additionalProperties": False,
            },
            fonction=abandonner_conversation,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_produire_digest",
            description="Produit le digest déterministe du registre anti-perte pour une date de référence donnée.",
            parametres={
                "type": "object",
                "properties": {"date_reference": {"type": "string"}},
                "required": ["date_reference"],
                "additionalProperties": False,
            },
            fonction=produire_digest,
        ),
        Outil(
            nom="m1_emettre_notification",
            description=(
                "Envoie un message à un client ou un système externe via le bus de notification. "
                "Action externe réversible : en mode ombre, attend une approbation humaine."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "canal": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["canal", "message"],
                "additionalProperties": False,
            },
            fonction=emettre_notification,
            autonomie=Autonomie.T2,
        ),
    )
