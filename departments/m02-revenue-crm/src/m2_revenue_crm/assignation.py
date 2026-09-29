"""Propriété d'un lead dans le temps : la qualification, puis les réassignations (PLAN T1.4-m).

Module PUR (même patron que ``acces.py`` : aucun import ``opsys``, aucune horloge, aucun aléa). Il décide, il ne
lit jamais l'identité ni les personnes : c'est ``outils.py`` (l'adaptateur, seul) qui établit QUI décide et si la
cible est une personne active de rôle ``seller``, puis passe ici le résultat.

UNE SEULE LECTURE DU PROPRIÉTAIRE. Le propriétaire d'un lead est l'``owner`` de sa qualification
(``nouveau -> qualifie``, ``rang`` 1), puis le ``nouveau_proprietaire`` de chaque réassignation (``rang`` 2, 3, ...),
le dernier maillon gagnant. ``proprietaires`` est la seule fonction qui lit ces maillons ; ``acces.py`` (qui voit
quoi), ``readiness.py`` (l'owner du marqueur) et ``digest.py`` s'y alignent, pour qu'un lead réassigné n'ait jamais
deux propriétaires selon l'endroit où on le lit. Rien n'est déduit d'un autre champ (ni l'``auteur`` d'une note, ni
le statut, ni l'ordre d'ingestion).

LE FAIT ``m2.lead_assigne`` EST VERSIONNÉ, de façon additive (le contrat v1 du catalogue reste intact : toute charge
valide avant reste valide) :
  - rang 1, la qualification : charge de trois clés, sans ``rang``, sous l'identifiant ``m2-lead-assigne-<lead_id>``
    (octet pour octet ce que M2 publie depuis T1.4-k2) ;
  - rang n >= 2, une réassignation : les mêmes trois clés, plus ``rang`` et ``proprietaire_precedent``, sous
    l'identifiant ``m2-lead-reassigne-<n>-<lead_id>``.
Les deux familles d'identifiants ne peuvent pas se confondre, quel que soit le ``lead_id`` (une chaîne libre) :
``m2-lead-assigne-`` et ``m2-lead-reassigne-`` diffèrent avant tout ``lead_id``, et dans la seconde le rang, en
chiffres, précède le premier tiret. Le propriétaire COURANT est celui du plus grand rang publié. Un lecteur du bus
(M3) lit d'abord le rang 1, puis ``rang`` 2, 3... jusqu'au premier absent (voir ROLES.md).

Une réassignation est une décision HUMAINE (``REJ-HUMAIN-REQUIS`` sans personne identifiée, par jeton d'appareil
``admin`` ou par une demande qu'une personne vient d'approuver) qui écrit au registre, append-only, un maillon
``reassignation`` : qui décide, par quelle voie, pourquoi (motif obligatoire), de qui à qui, à quel rang. Le maillon
de qualification n'est jamais modifié : l'historique complet reste lisible.
"""

from __future__ import annotations

from . import encodage, verdicts
from . import horodatage as _horodatage
from .statuts import TYPE_ENTREE as _TYPE_TRANSITION
from .statuts import statut_courant

TYPE_ENTREE = "reassignation"
TYPE_EVENEMENT = "m2.lead_assigne"
RANG_QUALIFICATION = 1

MOTIF_MIN_CARACTERES = 10
MOTIF_MAX_CARACTERES = 500

ROLE_ADMIN = "admin"
ROLE_PROPRIETAIRE = "nathan_owner"
VOIE_APPAREIL = "appareil"
VOIE_APPROBATION = "approbation"
ROLES_HUMAINS = frozenset({ROLE_ADMIN, ROLE_PROPRIETAIRE})
VOIES = frozenset({VOIE_APPAREIL, VOIE_APPROBATION})

_PREFIXE_QUALIFICATION = "m2-lead-assigne-"
_PREFIXE_REASSIGNATION = "m2-lead-reassigne-"

__all__ = [
    "MOTIF_MAX_CARACTERES",
    "MOTIF_MIN_CARACTERES",
    "RANG_QUALIFICATION",
    "ROLES_HUMAINS",
    "TYPE_ENTREE",
    "TYPE_EVENEMENT",
    "VOIES",
    "VOIE_APPAREIL",
    "VOIE_APPROBATION",
    "assignations",
    "fait_assigne",
    "identifiant_evenement",
    "proprietaire_du_lead",
    "proprietaires",
    "reassigner",
]


def identifiant_evenement(lead_id, rang=RANG_QUALIFICATION):
    """Identifiant déterministe de l'événement ``m2.lead_assigne`` de ce lead à ce rang (voir l'en-tête)."""
    if rang == RANG_QUALIFICATION:
        return f"{_PREFIXE_QUALIFICATION}{lead_id}"
    return f"{_PREFIXE_REASSIGNATION}{rang}-{lead_id}"


def fait_assigne(lead_id, proprietaire, horodatage, rang=RANG_QUALIFICATION, precedent=None):
    """``(evenement_id, charge)`` de ``m2.lead_assigne`` : LA seule construction de la charge, pour la publication
    d'origine comme pour la republication (la même charge, jamais une variante).

    Rang 1 : ``{lead_id, proprietaire, horodatage_assignation}``, sans autre clé. Rang >= 2 : plus ``rang`` et
    ``proprietaire_precedent``."""
    charge = {"lead_id": lead_id, "proprietaire": proprietaire, "horodatage_assignation": horodatage}
    if rang != RANG_QUALIFICATION:
        charge["rang"] = rang
        charge["proprietaire_precedent"] = precedent
    return identifiant_evenement(lead_id, rang), charge


def _proprietaire_non_vide(valeur):
    return valeur.strip() if isinstance(valeur, str) and valeur.strip() else None


def assignations(registre_cible):
    """Les assignations de tous les leads, dans l'ordre de la chaîne : une liste de dicts
    ``{lead_id, rang, proprietaire, precedent, horodatage}``.

    Le rang 1 est la qualification qui porte un owner non vide (un lead sans owner n'a pas d'assignation) ; les
    rangs suivants sont les maillons ``reassignation``. ``precedent`` est ``None`` au rang 1. La source des
    faits que ``republier`` remet au bus."""
    resultat = []
    for maillon in registre_cible.lire():
        type_entree = maillon.get("type_entree")
        if type_entree == _TYPE_TRANSITION and maillon.get("statut") == "qualifie":
            proprietaire = _proprietaire_non_vide(maillon.get("owner"))
            if proprietaire is not None:
                resultat.append({
                    "lead_id": maillon.get("lead_id"), "rang": RANG_QUALIFICATION, "proprietaire": proprietaire,
                    "precedent": None, "horodatage": maillon.get("horodatage"),
                })
        elif type_entree == TYPE_ENTREE:
            proprietaire = _proprietaire_non_vide(maillon.get("nouveau_proprietaire"))
            if proprietaire is not None:
                resultat.append({
                    "lead_id": maillon.get("lead_id"), "rang": maillon.get("rang"), "proprietaire": proprietaire,
                    "precedent": maillon.get("proprietaire_precedent"), "horodatage": maillon.get("horodatage"),
                })
    return resultat


def proprietaires(registre_cible):
    """``{lead_id: propriétaire courant}`` : la dernière assignation de chaque lead qui en a une. Un lead sans
    owner non vide n'est pas dans le dictionnaire (fail-closed : il n'a pas de propriétaire). Une seule lecture
    du registre, pour tous les leads."""
    resultat = {}
    for assignation in assignations(registre_cible):
        resultat[assignation["lead_id"]] = assignation["proprietaire"]
    return resultat


def proprietaire_du_lead(registre_cible, lead_id):
    """Le propriétaire courant du lead, ou ``None`` (lead inconnu, ``nouveau``, ou jamais qualifié avec un owner)."""
    return proprietaires(registre_cible).get(lead_id)


def _refus(code, detail, statut=""):
    return None, verdicts.construire_verdict(code, statut=statut, detail=detail)


def _decideur_humain(par, role, voie):
    return (
        isinstance(par, str) and bool(par.strip()) and role in ROLES_HUMAINS and voie in VOIES
    )


def _verifier_motif(motif):
    """``None`` si le motif est recevable, sinon le refus ``(None, verdict)``."""
    if not isinstance(motif, str) or not motif.strip():
        return _refus("REJ-MOTIF-ABSENT", "le motif d'une réassignation est obligatoire : dis pourquoi")
    if not MOTIF_MIN_CARACTERES <= len(motif.strip()) <= MOTIF_MAX_CARACTERES:
        return _refus(
            "REJ-MOTIF-INVALIDE",
            f"le motif fait {len(motif.strip())} caractères : {MOTIF_MIN_CARACTERES} à {MOTIF_MAX_CARACTERES} "
            "sont attendus, pour dire pourquoi",
        )
    return None


def reassigner(registre_cible, lead_id, nouveau_proprietaire, motif, horodatage, par, role, voie):
    """Réassigne un lead à un autre propriétaire : ``(accusé, None)`` ou ``(None, verdict)``.

    ``nouveau_proprietaire`` est DÉJÀ confirmé par l'adaptateur (personne active de rôle ``seller``) ; ``par``,
    ``role`` et ``voie`` sont DÉJÀ établis (jeton d'appareil ``admin`` confirmé en base, ou demande approuvée par
    une personne). Défense en profondeur : sans un décideur de cette forme, ``REJ-HUMAIN-REQUIS``.

    Ordre des contrôles, tous AVANT l'unique écriture : décideur, horodatage, motif, lead connu, lead avec un
    propriétaire, nouveau propriétaire différent de l'actuel. Aucun maillon n'est écrit pour un refus."""
    if not _decideur_humain(par, role, voie):
        return _refus(
            "REJ-HUMAIN-REQUIS",
            "une réassignation est une décision de personne (rôle admin ou nathan_owner, par jeton d'appareil "
            "ou par demande approuvée)",
        )
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return _refus("REJ-HORODATAGE-INVALIDE", "Horodatage de la réassignation invalide.")
    refus_motif = _verifier_motif(motif)
    if refus_motif is not None:
        return refus_motif
    courant = statut_courant(registre_cible, lead_id)
    if courant is None:
        return _refus("REJ-LEAD-INCONNU", f"aucun lead {lead_id!r} au registre")
    du_lead = [a for a in assignations(registre_cible) if a["lead_id"] == lead_id]
    if not du_lead:
        return _refus(
            "REJ-OWNER-ABSENT",
            "ce lead n'a pas de propriétaire à qui le reprendre : un lead nouveau s'assigne en le qualifiant "
            "(m2_transitionner_statut, avec owner)",
            statut=courant,
        )
    precedent = du_lead[-1]["proprietaire"]
    if precedent == nouveau_proprietaire:
        return _refus(
            "REJ-PROPRIETAIRE-INCHANGE",
            f"le lead appartient déjà à {nouveau_proprietaire!r} : rien à réassigner",
            statut=courant,
        )
    rang = max(a["rang"] for a in du_lead) + 1
    maillon = {
        "type_entree": TYPE_ENTREE,
        "horodatage": horodatage_valide,
        "lead_id": lead_id,
        "rang": rang,
        "proprietaire_precedent": precedent,
        "nouveau_proprietaire": nouveau_proprietaire,
        "motif": motif.strip(),
        "decide_par": par.strip(),
        "decide_role": role,
        "voie": voie,
    }
    ligne_id = registre_cible.ajouter(maillon)
    maillon_relu = next((m for m in registre_cible.lire() if m.get("ligne_id") == ligne_id), None)
    if maillon_relu is None:
        raise RuntimeError("Maillon ajouté introuvable.")
    return {
        "lead_id": lead_id,
        "ligne_id": ligne_id,
        "rang": rang,
        "proprietaire_precedent": precedent,
        "nouveau_proprietaire": nouveau_proprietaire,
        "decide_par": maillon["decide_par"],
        "decide_role": role,
        "voie": voie,
        "horodatage": horodatage_valide,
        "empreinte_maillon": encodage.empreinte(maillon_relu),
        "tete_chaine": registre_cible.tete(),
    }, None
