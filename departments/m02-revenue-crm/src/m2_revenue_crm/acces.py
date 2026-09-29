"""Contrôle d'accès par personne authentifiée et par lead (PLAN T1.4-k2, docs/architecture/ROLES.md).

Module pur (même patron que ``acces.py`` de M4 et de M5 : aucun import ``opsys``, aucune horloge,
aucun aléa). Il décide, il ne lit jamais l'identité : c'est ``outils.py`` (l'adaptateur, seul) qui la
lit dans ``opsys.contexte.identite_appelante()``, la fait confirmer par la base, et la passe ici sous
forme d'``Acteur``. Ce module ne reçoit donc jamais une identité que le modèle ou l'appareil a écrite
dans les arguments d'un outil.

LA PROPRIÉTÉ D'UN LEAD EXISTAIT DÉJÀ. C'est le champ ``owner`` que la transition ``nouveau -> qualifie``
exige (``REJ-OWNER-ABSENT``, ``statuts.py``) et consigne dans son maillon, que la readiness et le digest
lisent déjà. Rien n'est ajouté au registre, et rien n'est déduit d'un autre champ (ni ``auteur`` d'une
interaction, ni statut, ni ordre d'ingestion) : ``proprietaire_du_lead`` relit ce seul maillon.
  - Un lead ``nouveau`` n'a pas de propriétaire : seul l'``admin`` (ou l'agent) le voit et le qualifie.
  - ``owner`` est du texte libre pour un appel sans jeton d'appareil (comportement d'avant, voulu). Il
    ne rend un lead visible à un vendeur que si c'est l'identifiant de sa personne OPSYS
    (``opsys.identite``, immuable), comme ``technicien_id`` pour M4 (ROLES.md, T1.4-k). Un ``owner``
    qui n'est l'identifiant d'aucune personne n'appartient à aucun vendeur : fail-closed.

TROIS CAS, jamais un quatrième :
  - ``acteur is None`` : appel sans jeton d'appareil (agent, console, outil interne). Comportement
    d'avant T1.4-k2, aucun contrôle de personne : ``auteur`` est celui de l'appelant. Le secret partagé
    de la passerelle garde l'accès complet (docs/architecture/ROLES.md, « Voie des agents »).
  - ``admin`` : tous les leads (DEFINITION-PRODUIT §9.5, « M2 : pipeline, leads chauds, doublons »).
  - ``seller`` : seulement les leads dont il est le propriétaire (§9.4, « ses leads », « pipeline
    personnel »). Un lead d'un autre, un lead sans propriétaire et un lead inconnu donnent le MÊME
    refus (``REJ-LEAD-NON-ASSIGNE``) : rien ne dit à un vendeur quels leads existent.

``auteur`` d'une interaction : pour TOUT appel d'appareil, ``admin`` compris (un admin n'écrit pas au
nom d'un vendeur, contrairement à un dispatch M4), il vient de la personne authentifiée. Absent, il vaut
cette personne ; différent, il est REFUSÉ (``REJ-IDENTITE-FOURNIE-DIFFERENTE``), jamais remplacé en
silence : un appelant qui se trompe doit le savoir, et l'historique ne doit jamais nommer un auteur qui
n'a rien écrit. Les interactions système (``system:m3``, ``system:m4``) ne passent pas par ici : un
identifiant de personne ne contient pas de « : » (``opsys.identite``), aucune personne ne peut les imiter.
"""

from __future__ import annotations

import dataclasses

from . import verdicts
from .statuts import TYPE_ENTREE as _TYPE_TRANSITION

ROLE_ADMIN = "admin"
ROLE_VENDEUR = "seller"

# Portée des outils M2 ouverts aux appareils (la source UNIQUE, reprise par `Outil.roles_appareil` dans
# `outils.py` : le core l'applique déjà en amont, la repasser ici est une défense en profondeur, car le
# socle ne l'applique pas hors du core).
ROLES_LEADS = frozenset({ROLE_VENDEUR, ROLE_ADMIN})
ROLES_ADMIN = frozenset({ROLE_ADMIN})
# Qui peut être propriétaire d'un lead (DEFINITION-PRODUIT §9.4 : le vendeur ; §9.5 : le propriétaire de
# l'entreprise qui travaille lui-même un dossier). Jamais un employé, un client ou un agent.
ROLES_PROPRIETAIRES = frozenset({ROLE_VENDEUR, ROLE_ADMIN})

__all__ = [
    "ROLES_ADMIN",
    "ROLES_LEADS",
    "ROLES_PROPRIETAIRES",
    "ROLE_ADMIN",
    "ROLE_VENDEUR",
    "Acteur",
    "acteur_de",
    "auteur_effectif",
    "controler_lead",
    "leads_visibles",
    "proprietaire_du_lead",
    "proprietaires",
    "refus_client_sans_lead_visible",
]


@dataclasses.dataclass(frozen=True)
class Acteur:
    """Personne et rôle d'un jeton d'appareil, DÉJÀ confirmés par la base (voir ``outils.py``)."""

    personne: str
    role: str


def acteur_de(personne, role, roles_permis):
    """``(Acteur, None)`` si ``role`` est dans ``roles_permis``, sinon ``(None, verdict)``.

    ``roles_permis`` est la portée déclarée de l'outil (``ROLES_LEADS`` ou ``ROLES_ADMIN``). Fail-closed :
    un rôle hors portée qui arriverait jusqu'ici n'a aucune portée sur l'outil, on ne lui en invente pas
    une, et le refus ne décrit pas ce que l'outil aurait rendu."""
    if role not in roles_permis:
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=f"rôle d'appareil {role!r} sans portée sur cet outil de M2",
        )
    return Acteur(personne=personne, role=role), None


def proprietaires(registre_cible):
    """``{lead_id: propriétaire}`` : l'``owner`` du DERNIER maillon ``nouveau -> qualifie`` de chaque lead
    qui en a un. Un lead sans owner non vide n'est pas dans le dictionnaire (fail-closed : il n'a pas de
    propriétaire). Une seule lecture du registre, pour tous les leads."""
    resultat = {}
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != _TYPE_TRANSITION or maillon.get("statut") != "qualifie":
            continue
        owner = maillon.get("owner")
        if isinstance(owner, str) and owner.strip():
            resultat[maillon.get("lead_id")] = owner.strip()
    return resultat


def proprietaire_du_lead(registre_cible, lead_id):
    """Le propriétaire du lead, ou ``None`` (lead inconnu, ``nouveau``, ou jamais qualifié avec un owner)."""
    return proprietaires(registre_cible).get(lead_id)


def _voit_tout(acteur):
    return acteur is None or acteur.role == ROLE_ADMIN


def _refus_lead(detail):
    return verdicts.construire_verdict("REJ-LEAD-NON-ASSIGNE", detail=detail)


def controler_lead(registre_cible, lead_id, acteur):
    """``None`` si l'acteur peut voir et agir sur ce lead, sinon un verdict.

    ``seller`` : le lead doit lui appartenir (``proprietaire_du_lead``, lu au registre). Inconnu, à un
    autre ou à personne : le MÊME refus, sans détail sur l'existence. ``admin`` et l'absence d'acteur :
    rien à contrôler."""
    if _voit_tout(acteur):
        return None
    if proprietaire_du_lead(registre_cible, lead_id) != acteur.personne:
        return _refus_lead("ce lead n'est pas assigné à la personne authentifiée (ou est inconnu)")
    return None


def leads_visibles(registre_cible, lead_ids, acteur):
    """``None`` si l'acteur voit tous les leads (``admin``, ou aucun acteur), sinon l'ensemble de ceux de
    ``lead_ids`` qui lui appartiennent (vide si aucun). Sert la vue Client 360 : un vendeur ne voit d'un
    client que SES opportunités."""
    if _voit_tout(acteur):
        return None
    par_lead = proprietaires(registre_cible)
    return {lead_id for lead_id in lead_ids if par_lead.get(lead_id) == acteur.personne}


def refus_client_sans_lead_visible():
    """Le refus d'une vue Client 360 dont aucune opportunité n'appartient au vendeur : le même pour un
    client inconnu, pour que le refus ne dise pas si le client existe."""
    return _refus_lead("aucun lead de ce client n'est assigné à la personne authentifiée (ou client inconnu)")


def auteur_effectif(acteur, auteur):
    """``(auteur, None)`` : l'auteur à consigner, ou ``(None, verdict)`` : un refus.

    Appel d'appareil : ``auteur`` absent (``None``) vaut la personne authentifiée ; fourni, il doit lui
    être égal (aux espaces près, que ``interactions.enregistrer`` retire de toute façon), sinon
    ``REJ-IDENTITE-FOURNIE-DIFFERENTE`` — jamais remplacé en silence, y compris pour ``admin``. Sans
    acteur : l'argument de l'appelant, tel quel (``interactions.enregistrer`` refuse un auteur vide)."""
    if acteur is None:
        return auteur, None
    if auteur is None:
        return acteur.personne, None
    if not isinstance(auteur, str) or auteur.strip() != acteur.personne:
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-FOURNIE-DIFFERENTE",
            detail=(
                "auteur ne correspond pas à la personne authentifiée : une interaction nomme celle qui "
                "l'a écrite, jamais une autre (omettre auteur suffit)"
            ),
        )
    return acteur.personne, None
