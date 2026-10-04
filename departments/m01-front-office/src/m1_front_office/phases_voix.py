import hashlib

from . import horodatage as _horodatage
from . import verdicts
from .registre import Registre


class TransitionInterdite(Exception):
    """Levée lorsqu'une tentative de transition n'est pas autorisée."""
    def __init__(self, verdict):
        self.verdict = verdict
        super().__init__(f"Transition interdite: {verdict['code']} - {verdict.get('detail', '')}")

def _generer_conversation_id(signal_id, horodatage):
    """Génère un identifiant déterministe basé sur le signal et l'horodatage."""
    base = f"{signal_id}|{horodatage}"
    return hashlib.sha256(base.encode()).hexdigest()[:12]

def ouvrir_conversation(signal_id, horodatage, registre: Registre):
    """Crée une nouvelle conversation avec la phase 0 ouverte.

    Retourne la conversation ou un verdict d'erreur si l'horodatage est invalide.
    """
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE",
                                           detail="Horodatage invalide pour ouverture")
    conv_id = _generer_conversation_id(signal_id, horodatage)
    phase0 = {
        "numero": 0,
        "horodatage_debut": horodatage,
        "horodatage_fin": None,
        "statut": "ouverte",
    }
    conversation = {
        "conversation_id": conv_id,
        "signal_id": signal_id,
        "statut": "ouverte",
        "phases": [phase0],
        "phase_courante": 0,
        "dernier_ligne_id": None,
    }

    # Écriture de l'ouverture dans le registre (chaînée)
    entree_ouverture = {
        "type_entree": "transition_phase",
        "horodatage": horodatage,
        "precedent_ligne_id": None,
        "payload": {
            "conversation_id": conv_id,
            "signal_id": signal_id,
            "phase_source": None,
            "phase_cible": 0,
            "motif": "ouverture",
        },
    }
    ligne_id = registre.ajouter(entree_ouverture)
    conversation["dernier_ligne_id"] = ligne_id

    return conversation

def transitionner(conversation, phase_cible, horodatage, registre: Registre):
    """Effectue une transition vers la phase cible.

    Retourne un verdict OK ou lève TransitionInterdite, ou retourne un verdict
    d'erreur si l'horodatage est invalide.
    """
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE",
                                           detail="Horodatage invalide pour transition")
    # Conversation déjà close (erreur, abandon ou complétion) : toute transition est bloquée
    if conversation["statut"] in ("close_erreur", "close_abandon", "close_normale"):
        verdict = verdicts.construire_verdict("REJ-PHASE-SAUTE",
                                              detail="Conversation déjà close")
        raise TransitionInterdite(verdict)

    phase_courante = conversation["phase_courante"]

    # Seule transition autorisée : strictement linéaire vers phase_courante+1
    if phase_cible != phase_courante + 1 or phase_cible > 5:
        # Violation → figer la conversation
        conversation["statut"] = "close_erreur"
        phase_courante_obj = conversation["phases"][phase_courante]
        phase_courante_obj["statut"] = "close_erreur"

        # Écriture d'une alerte dans le registre
        entree_alerte = {
            "type_entree": "alerte",
            "horodatage": horodatage,
            "code": "EVT-PHASE-VIOLATION",
            "payload": {
                "conversation_id": conversation["conversation_id"],
                "phase_courante": phase_courante,
                "phase_cible": phase_cible,
            },
        }
        registre.ajouter(entree_alerte)

        verdict = verdicts.construire_verdict("REJ-PHASE-SAUTE",
                                              detail="Transition non autorisée")
        raise TransitionInterdite(verdict)

    # Transition autorisée : clore la phase courante normalement
    phase_courante_obj = conversation["phases"][phase_courante]
    phase_courante_obj["statut"] = "close_normale"
    phase_courante_obj["horodatage_fin"] = horodatage

    # Ouvrir la nouvelle phase (phase 5 = close_normale directement)
    statut_nouvelle = "close_normale" if phase_cible == 5 else "ouverte"
    nouvelle_phase = {
        "numero": phase_cible,
        "horodatage_debut": horodatage,
        "horodatage_fin": None,
        "statut": statut_nouvelle,
    }
    conversation["phases"].append(nouvelle_phase)
    conversation["phase_courante"] = phase_cible

    if phase_cible == 5:
        conversation["statut"] = "close_normale"

    # Écriture de la transition dans le registre (chaînée)
    entree_trans = {
        "type_entree": "transition_phase",
        "horodatage": horodatage,
        "precedent_ligne_id": conversation["dernier_ligne_id"],
        "payload": {
            "conversation_id": conversation["conversation_id"],
            "phase_source": phase_courante,
            "phase_cible": phase_cible,
        },
    }
    nouveau_ligne_id = registre.ajouter(entree_trans)
    conversation["dernier_ligne_id"] = nouveau_ligne_id

    return verdicts.construire_verdict("OK")

def abandonner(conversation, horodatage, registre: Registre):
    """Abandonne la conversation : ferme la phase courante en `close_abandon`
    et crée une phase 5 `close_abandon`.

    Retourne un verdict OK ou une erreur si la conversation est déjà close
    ou si l'horodatage est invalide.
    """
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE",
                                           detail="Horodatage invalide pour abandon")
    if conversation["statut"] in ("close_abandon", "close_erreur", "close_normale"):
        return verdicts.construire_verdict("REJ-CONVERSATION-CLOSE",
                                           detail="Conversation déjà close, abandon impossible")

    phase_courante = conversation["phase_courante"]

    # Fermer la phase courante en abandon
    phase_courante_obj = conversation["phases"][phase_courante]
    phase_courante_obj["statut"] = "close_abandon"
    phase_courante_obj["horodatage_fin"] = horodatage

    # Ajouter la phase 5 de clôture en abandon
    phase_cloture = {
        "numero": 5,
        "horodatage_debut": horodatage,
        "horodatage_fin": horodatage,
        "statut": "close_abandon",
    }
    conversation["phases"].append(phase_cloture)
    conversation["statut"] = "close_abandon"

    # Écriture de l'entrée registre pour l'abandon
    entree_abandon = {
        "type_entree": "transition_phase",
        "horodatage": horodatage,
        "precedent_ligne_id": conversation["dernier_ligne_id"],
        "payload": {
            "conversation_id": conversation["conversation_id"],
            "phase_source": phase_courante,
            "phase_cible": 5,
            "motif": "abandon",
        },
    }
    nouveau_ligne_id = registre.ajouter(entree_abandon)
    conversation["dernier_ligne_id"] = nouveau_ligne_id

    return verdicts.construire_verdict("OK")
