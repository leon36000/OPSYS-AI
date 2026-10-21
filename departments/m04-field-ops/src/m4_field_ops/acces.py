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

L'ÉQUIPE (PLAN T4.12). La cédule par tournées assigne une intervention à une ÉQUIPE du profil de l'entreprise : le
``technicien_id`` de l'assignation est alors l'identifiant de l'équipe (``opsys.equipes``), pas celui d'une personne.
Un ``employee`` agit aussi sur l'intervention assignée à une équipe DONT IL EST MEMBRE : l'adaptateur lit ses
équipes dans le profil (``Acteur.equipes``) ; un profil absent ou invalide donne aucune équipe (fail-closed : moins
de droits, jamais plus). Quand il part (``planifiee -> en_route``), le technicien de l'intervention devient la
personne qui part (``etats.transitionner``) : les autres membres n'y ont plus accès, comme pour une assignation
directe. Le profil interdit qu'une personne soit membre de deux équipes et qu'une équipe porte l'identifiant d'un
tiers : aucune équipe ne donne accès à quelqu'un qui n'en est pas membre.

TROIS CAS, jamais un quatrième :
  - ``acteur is None`` : appel sans jeton d'appareil (agent, console, outil interne). Comportement
    inchangé, aucun contrôle ici — le secret partagé de la passerelle garde l'accès complet
    (docs/architecture/ROLES.md, « Voie des agents »).
  - ``admin`` : accès à toutes les interventions ; il dispatche pour les autres, donc le
    ``technicien_id`` qu'il fournit est honoré tel quel.
  - ``employee`` : seulement les interventions qui lui sont assignées (à lui, ou à une équipe dont il est
    membre), et seulement sous son propre identifiant. Un ``technicien_id`` différent est REFUSÉ, jamais
    remplacé en silence par celui de la personne authentifiée (un appelant qui se trompe doit le savoir).
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
    "controler_administrateur",
    "controler_confirmant",
    "controler_saisisseur",
    "controler_intervention",
    "interventions_visibles",
]


@dataclasses.dataclass(frozen=True)
class Acteur:
    """Personne et rôle d'un jeton d'appareil, DÉJÀ confirmés par la base (voir ``outils.py``), et les identifiants
    des équipes dont la personne est membre selon le profil de l'entreprise (T4.12 ; vide sans profil valide)."""

    personne: str
    role: str
    equipes: tuple = ()


def acteur_de(personne, role, equipes=()):
    """``(Acteur, None)`` pour un rôle de terrain (``employee``, ``admin``), sinon ``(None, verdict)``.

    Fail-closed : les outils M4 ne sont ouverts qu'à ces deux rôles (``Outil.roles_appareil``) ; un
    autre rôle qui arriverait jusqu'ici n'a aucune portée sur eux, on ne lui en invente pas une.
    ``equipes`` : les équipes de la personne, lues au profil par l'adaptateur, jamais par le modèle."""
    if role not in (ROLE_EMPLOYE, ROLE_ADMIN):
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=f"rôle d'appareil {role!r} sans portée sur les outils de terrain M4",
        )
    return Acteur(personne=personne, role=role, equipes=tuple(equipes)), None


def _lui_est_assignee(acteur, technicien_assigne):
    """Vrai si le technicien assigné est la personne elle-même ou une équipe dont elle est membre. ``None`` (personne
    d'assigné) n'est jamais à quelqu'un."""
    return technicien_assigne is not None and (
        technicien_assigne == acteur.personne or technicien_assigne in acteur.equipes
    )


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


def controler_administrateur(acteur):
    """``None`` si l'acteur peut appeler un outil réservé à l'``admin``, sinon un verdict.

    La portée par outil (``Outil.roles_appareil``, ``docs/architecture/ROLES.md``) est déjà tenue par
    le core ; ce contrôle la double dans l'outil même, pour qu'un jeton qui la franchirait (portée mal
    déclarée, appel direct) n'écrive rien. Sans acteur (agent, console) : rien à contrôler."""
    if acteur is None or acteur.role == ROLE_ADMIN:
        return None
    return verdicts.construire_verdict(
        "REJ-IDENTITE-APPAREIL-INVALIDE",
        detail=f"rôle d'appareil {acteur.role!r} sans portée sur cet outil, réservé à l'admin",
    )


def controler_confirmant(acteur, confirme_par):
    """``None`` si ``confirme_par`` (qui confirme la localisation d'un chantier, PLAN T4.1-a) est admis
    pour cet acteur, sinon un verdict.

    Même règle que ``controler_consultant`` : pour tout appel d'appareil, la confirmation nomme la
    personne AUTHENTIFIÉE ; un autre nom est refusé, jamais remplacé en silence (une confirmation
    signée d'un autre nom ne prouverait plus qu'un humain l'a faite). Sans acteur : l'argument reste
    celui de l'appelant, comme pour les autres outils sans identité."""
    if acteur is None:
        return None
    if confirme_par != acteur.personne:
        return verdicts.construire_verdict(
            "REJ-IDENTITE-FOURNIE-DIFFERENTE",
            detail=(
                "confirme_par ne correspond pas à la personne authentifiée : la confirmation d'une "
                "localisation nomme celui qui la fait, pas un autre"
            ),
        )
    return None


def controler_saisisseur(acteur, saisi_par):
    """``None`` si ``saisi_par`` (qui a saisi une prévision météo à la main, PLAN T4.13) est admis pour cet acteur,
    sinon
    un verdict.

    Même règle que ``controler_confirmant`` : pour tout appel d'appareil, la saisie nomme la personne AUTHENTIFIÉE ; un
    autre nom est refusé, jamais remplacé en silence (une prévision citée sous un autre nom ne prouverait plus qui l'a
    lue).
    Sans acteur (agent, console) : l'argument reste celui de l'appelant."""
    if acteur is None:
        return None
    if saisi_par != acteur.personne:
        return verdicts.construire_verdict(
            "REJ-IDENTITE-FOURNIE-DIFFERENTE",
            detail=(
                "saisi_par ne correspond pas à la personne authentifiée : la prévision saisie à la main nomme celui "
                "qui "
                "l'a saisie, pas un autre"
            ),
        )
    return None


def controler_intervention(registre_cible, intervention_id, acteur):
    """``None`` si l'acteur peut agir sur cette intervention, sinon un verdict.

    ``employee`` : l'intervention doit lui être ASSIGNÉE, à lui ou à une équipe dont il est membre
    (``etats.technicien_assigne``, lu au registre). Inconnue, assignée à un autre ou à personne : le MÊME refus
    (``REJ-INTERVENTION-NON-ASSIGNEE``, sans détail sur l'existence) — un employé ne peut pas
    sonder quelles interventions existent."""
    if _accede_a_tout(acteur):
        return None
    if not _lui_est_assignee(acteur, etats.technicien_assigne(registre_cible, intervention_id)):
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
    return [i for i in interventions if _lui_est_assignee(acteur, i.get("technicien_assigne"))]
