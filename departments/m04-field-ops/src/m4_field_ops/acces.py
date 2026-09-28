"""Contrôle d'accès par intervention et par personne authentifiée (PLAN T1.4-k, ROLES.md).

Module pur (comme ``etats.py`` : aucun import ``opsys``, aucune horloge, aucun aléa). Il décide, il
ne lit jamais l'identité : c'est ``outils.py`` (l'adaptateur, seul) qui la lit dans
``opsys.contexte.identite_appelante()``, la fait confirmer par la base, et la passe ici sous forme
d'``Acteur``. Ce module ne reçoit donc jamais une identité que le modèle ou l'appareil a écrite
dans les arguments d'un outil.

LE LIEN PERSONNE -> TECHNICIEN. Pour un appel d'appareil, l'identifiant de technicien EST
l'identifiant de la personne OPSYS (``opsys.identite.Personne.identifiant``, minuscules et
chiffres, immuable). Pas de table de correspondance : il n'y aurait qu'un second endroit à tenir à
jour, une décision de plus pour l'admin à chaque embauche, et un état intermédiaire « personne sans
technicien » à traiter. Le lien est explicite (une personne ne peut agir que sous son propre
identifiant), durable (l'identifiant ne change jamais), lu et non deviné (``identite_appelante``,
revalidé en base) et fail-closed : une intervention assignée à un identifiant qui ne correspond à
aucune personne (une ancienne valeur de cédule, par exemple) n'est visible ni actionnable par aucun
employé ; seul l'``admin`` y accède.

TROIS CAS, jamais un quatrième :
  - ``acteur is None`` : appel sans jeton d'appareil (agent, console, outil interne). Comportement
    inchangé, aucun contrôle ici — le secret partagé de la passerelle garde l'accès complet
    (docs/architecture/ROLES.md, « Voie des agents »).
  - ``admin`` : accès à toutes les interventions ; il dispatche pour les autres, donc le
    ``technicien_id`` qu'il fournit est honoré tel quel.
  - ``employee`` : seulement les interventions qui lui sont assignées, et seulement sous son propre
    identifiant. Un ``technicien_id`` différent est REFUSÉ, jamais remplacé en silence par celui de
    la personne authentifiée (un appelant qui se trompe doit le savoir).
``acteur_de`` n'accepte que ces deux rôles ; tout autre rôle de jeton est refusé avant d'arriver ici.
"""

from __future__ import annotations

import dataclasses

from . import etats, verdicts

ROLE_EMPLOYE = "employee"
ROLE_ADMIN = "admin"

__all__ = [
    "ROLE_EMPLOYE",
    "ROLE_ADMIN",
    "Acteur",
    "acteur_de",
    "controler_technicien",
    "controler_consultant",
    "controler_intervention",
    "interventions_visibles",
]


@dataclasses.dataclass(frozen=True)
class Acteur:
    """Personne et rôle d'un jeton d'appareil, DÉJÀ confirmés par la base (voir ``outils.py``)."""

    personne: str
    role: str


def acteur_de(personne, role):
    """``(Acteur, None)`` pour un rôle de terrain (``employee``, ``admin``), sinon ``(None, verdict)``.

    Fail-closed : les outils M4 ne sont ouverts qu'à ces deux rôles (``Outil.roles_appareil``) ; un
    autre rôle qui arriverait jusqu'ici n'a aucune portée sur eux, on ne lui en invente pas une."""
    if role not in (ROLE_EMPLOYE, ROLE_ADMIN):
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=f"rôle d'appareil {role!r} sans portée sur les outils de terrain M4",
        )
    return Acteur(personne=personne, role=role), None


def _accede_a_tout(acteur):
    return acteur is None or acteur.role == ROLE_ADMIN


def controler_technicien(acteur, technicien_id):
    """``None`` si ``technicien_id`` est admis pour cet acteur, sinon un verdict.

    ``employee`` : ``technicien_id`` doit être SA personne (le lien personne -> technicien, voir
    l'en-tête) ; toute autre valeur est REFUSÉE, jamais préférée en silence à la personne
    authentifiée. ``admin`` et l'absence d'acteur : rien à contrôler (dispatch pour autrui)."""
    if _accede_a_tout(acteur):
        return None
    if technicien_id != acteur.personne:
        return verdicts.construire_verdict(
            "REJ-IDENTITE-FOURNIE-DIFFERENTE",
            detail=(
                "technicien_id ne correspond pas à la personne authentifiée : un employé n'agit "
                "que sous son propre identifiant"
            ),
        )
    return None


def controler_consultant(acteur, accede_par):
    """``None`` si ``accede_par`` (POLITIQUE-geolocalisation §6, journal de chaque accès aux
    positions) est admis pour cet acteur, sinon un verdict.

    Pour tout appel d'appareil, le journal d'accès doit nommer la personne AUTHENTIFIÉE : un
    ``accede_par`` différent est refusé, jamais remplacé en silence (un journal qui nommerait un
    autre que celui qui a lu ne prouverait plus rien). Aucune exception pour ``admin`` : c'est
    justement l'admin qui lit les positions des autres. Sans acteur (agent, console) : l'argument
    reste celui de l'appelant, comme avant T1.4-k."""
    if acteur is None:
        return None
    if accede_par != acteur.personne:
        return verdicts.construire_verdict(
            "REJ-IDENTITE-FOURNIE-DIFFERENTE",
            detail=(
                "accede_par ne correspond pas à la personne authentifiée : le journal d'accès "
                "GPS nomme celui qui consulte, pas un autre"
            ),
        )
    return None


def controler_intervention(registre_cible, intervention_id, acteur):
    """``None`` si l'acteur peut agir sur cette intervention, sinon un verdict.

    ``employee`` : l'intervention doit lui être ASSIGNÉE (``etats.technicien_assigne``, lu au
    registre). Inconnue, assignée à un autre ou à personne : le MÊME refus
    (``REJ-INTERVENTION-NON-ASSIGNEE``, sans détail sur l'existence) — un employé ne peut pas
    sonder quelles interventions existent."""
    if _accede_a_tout(acteur):
        return None
    if etats.technicien_assigne(registre_cible, intervention_id) != acteur.personne:
        return verdicts.construire_verdict(
            "REJ-INTERVENTION-NON-ASSIGNEE",
            detail="cette intervention n'est pas assignée à la personne authentifiée",
        )
    return None


def interventions_visibles(interventions, acteur):
    """Filtre la liste de ``etats.lister_interventions`` : l'employé ne voit que les siennes.

    ``acteur is None`` ou ``admin`` : la liste entière, inchangée."""
    if _accede_a_tout(acteur):
        return list(interventions)
    return [i for i in interventions if i.get("technicien_assigne") == acteur.personne]
