"""Consentement GPS par employé (M4-T4.2, POLITIQUE-geolocalisation.md §4).

Module pur (aucun import ``opsys``, aucune horloge, aucun aléa) : comme ``etats.py``, il rejoue le
registre qu'on lui passe pour dériver un état (ici, le consentement courant d'un technicien),
plutôt que de le tenir en mémoire à part — un seul registre hash-chaîné, immuable, fait foi.

Ce que la politique exige et que ce module rend possible :
    - §4 « Comment il est documenté » : chaque maillon porte le signataire (``technicien_id``),
      l'horodatage UTC, la version de la politique présentée, et une preuve (référence au
      formulaire signé — jamais le document lui-même, cf. ``photos``/``description_factuelle``
      ailleurs dans M4 : aucun binaire dans le registre).
    - §4 « Comment il est retiré » : le retrait est un maillon ``action="retire"`` comme un autre ;
      ``consentement_actif`` le voit au prochain appel (« immédiat » — aucune file d'attente,
      aucune tâche différée entre le retrait et sa prise en compte par ``m4_pointer``).
    - §7 « Droit de retrait à tout moment » : rien n'empêche un employé de redonner son
      consentement plus tard (``historique_consentement`` conserve les DEUX événements, jamais un
      écrasement).

``version_politique`` et ``preuve`` sont TOUJOURS fournis par l'appelant, jamais déduits : ce
module n'a aucun moyen de savoir quelle version du document a réellement été présentée à
l'employé, ni où vit la preuve documentée (formulaire papier scanné, case cochée horodatée côté
app) — l'inventer serait exactement la donnée par défaut que AGENTS.md interdit.
"""

from __future__ import annotations

from . import horodatage as horodatage_mod
from . import verdicts as verdicts_mod

TYPE_CONSENTEMENT = "consentement_gps"
ACTIONS_CONSENTEMENT = ("donne", "retire")

__all__ = [
    "TYPE_CONSENTEMENT",
    "ACTIONS_CONSENTEMENT",
    "enregistrer_consentement",
    "consentement_actif",
    "historique_consentement",
]


def _rejet(detail):
    return None, verdicts_mod.construire_verdict("REJ-CONSENTEMENT-INVALIDE", detail=detail)


def enregistrer_consentement(
    technicien_id, action, horodatage_arg, version_politique, preuve, registre_cible,
):
    """Enregistre un consentement donné ou retiré. Retourne (accusé, None) ou (None, verdict).

    Args:
        technicien_id: identifiant de l'employé signataire (§4, jamais un tiers).
        action: "donne" ou "retire" (``ACTIONS_CONSENTEMENT``).
        horodatage_arg: horodatage RFC 3339 avec fuseau (§4 : « date/heure UTC » — un fuseau non
            UTC reste accepté ici comme partout ailleurs dans M4, ``horodatage.valider_horodatage``
            n'impose que la présence d'un fuseau, jamais UTC précisément ; la politique demande une
            HEURE FIABLE, pas un fuseau particulier).
        version_politique: identifiant de la version du document présenté (ex. commit ou date de
            POLITIQUE-geolocalisation.md) — fourni par l'appelant, jamais deviné.
        preuve: {"fictif": True, "reference": str} — même patron que ``pointage.ATTESTATION`` :
            en mode ombre, seule une preuve fictive est supportée ; ``reference`` pointe vers le
            document signé (formulaire, export), jamais le document lui-même (pas de binaire).
        registre_cible: instance de Registre (M4).

    Returns:
        (accusé, None) en cas de succès, (None, verdict) sinon. Rien n'est écrit en cas de rejet.
    """
    if not isinstance(technicien_id, str) or technicien_id == "":
        return _rejet("technicien_id manquant ou vide")
    if action not in ACTIONS_CONSENTEMENT:
        return _rejet(f"action invalide : {action!r} (attendu {ACTIONS_CONSENTEMENT})")
    try:
        horodatage_mod.valider_horodatage(horodatage_arg)
    except ValueError:
        return _rejet(f"horodatage invalide : {horodatage_arg!r}")
    if not isinstance(version_politique, str) or version_politique == "":
        return _rejet("version_politique manquante ou vide (§4 : traçable jusqu'au document présenté)")
    if not isinstance(preuve, dict) or set(preuve.keys()) != {"fictif", "reference"}:
        return _rejet("preuve mal formée (attendu {fictif, reference})")
    if preuve.get("fictif") is not True:
        return _rejet("preuve réelle non supportée en mode ombre (même garde que pointage.ATTESTATION)")
    reference = preuve.get("reference")
    if not isinstance(reference, str) or reference == "":
        return _rejet("preuve.reference manquante ou vide")

    maillon = {
        "type_entree": TYPE_CONSENTEMENT,
        "technicien_id": technicien_id,
        "action": action,
        "horodatage": horodatage_arg,
        "version_politique": version_politique,
        "preuve": {"fictif": True, "reference": reference},
    }
    ligne_id = registre_cible.ajouter(maillon)
    accuse = {
        "technicien_id": technicien_id,
        "action": action,
        "horodatage": horodatage_arg,
        "ligne_id": ligne_id,
        "actif": action == "donne",
        "tete_chaine": registre_cible.tete(),
    }
    return accuse, None


def consentement_actif(registre_cible, technicien_id):
    """Vrai si le DERNIER maillon de consentement de ``technicien_id`` est ``action="donne"``.

    Fail-closed (§2 « consentement documenté avant activation ») : aucun maillon pour cet employé
    -> False, jamais un défaut « actif » inventé. Même patron de relecture que
    ``etats.statut_courant`` : le registre est rejoué en entier, le dernier maillon écrit gagne —
    aucun état tenu en mémoire à part qui pourrait diverger du registre.
    """
    dernier_actif = False
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != TYPE_CONSENTEMENT:
            continue
        if maillon.get("technicien_id") != technicien_id:
            continue
        dernier_actif = maillon.get("action") == "donne"
    return dernier_actif


def historique_consentement(registre_cible, technicien_id):
    """Tous les maillons de consentement de ``technicien_id``, dans l'ordre d'écriture (§7 : droit
    d'accès — l'employé peut demander l'historique complet, donné ET retiré, jamais seulement le
    dernier état)."""
    return [
        maillon for maillon in registre_cible.lire()
        if maillon.get("type_entree") == TYPE_CONSENTEMENT
        and maillon.get("technicien_id") == technicien_id
    ]
