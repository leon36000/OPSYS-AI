"""Admissibilité d'une équipe pour un service (M4.3, PLAN T4.12) : calculée par le code, lue dans le profil.

Module pur (stdlib et ``verdicts`` ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un test le
vérifie par analyse du code). Il reçoit le profil des équipes de l'entreprise (``opsys.equipes``, un dict que
l'adaptateur a lu et validé) et répond à une seule question : « quelles équipes peuvent faire ce service ? ».

Une équipe est ADMISSIBLE pour un service si, et seulement si :

    * elle détient TOUTES les compétences que le profil exige de ce service ;
    * au moins un de ses quarts est assez long pour la durée du service (``fin_min - debut_min >= duree_min``).

C'est une condition nécessaire, pas le plan : le solveur de tournées (``tournees.py``) ajoute les trajets, la fenêtre du
client, les créneaux figés et la charge des journées. Une équipe admissible peut donc ne recevoir aucun chantier ; une
équipe écartée ici n'en reçoit jamais (le solveur applique la même règle de compétence, sur les mêmes données).

Fail-closed : la durée et les compétences d'un service qui n'est pas au profil ne se devinent pas. Le résultat est alors
un verdict ``REJ-CHAMP-MANQUANT`` qui dit quoi déclarer, jamais « toutes les équipes sont admissibles ». Chaque équipe
écartée dit pourquoi. Aucune évaluation ni classement d'employé : une équipe est admissible ou non, sans note.
"""

from __future__ import annotations

from . import verdicts

CODE_COMPETENCE_MANQUANTE = "competence_manquante"
CODE_AUCUN_QUART_ASSEZ_LONG = "aucun_quart_assez_long"

__all__ = [
    "CODE_COMPETENCE_MANQUANTE",
    "CODE_AUCUN_QUART_ASSEZ_LONG",
    "exigences_du_service",
    "equipes_admissibles",
]

_DECLARER = "opsys-metier equipes declarer"


def _verdict(detail):
    return verdicts.construire_verdict("REJ-CHAMP-MANQUANT", detail=detail)


def exigences_du_service(profil, service):
    """``({duree_min, competences}, None)`` ou ``(None, verdict)`` : ce que le profil exige du service.

    Rien n'est présumé : un profil sans ``services``, ou sans ce service, est un verdict qui dit quoi déclarer."""
    services = profil.get("services") if isinstance(profil, dict) else None
    if not isinstance(services, dict) or not services:
        return None, _verdict(
            "durée et compétences par service non déclarées : les déclarer dans le profil des équipes "
            f"(clé equipes.services, `{_DECLARER}`)"
        )
    exigences = services.get(service)
    if not isinstance(exigences, dict):
        return None, _verdict(
            f"durée et compétences du service {service!r} non déclarées : les ajouter au profil des équipes "
            f"(clé equipes.services, `{_DECLARER}`)"
        )
    return {"duree_min": exigences["duree_min"], "competences": list(exigences["competences"])}, None


def _ecartee(equipe, code, detail):
    return {"equipe": equipe["id"], "code": code, "detail": detail}


def equipes_admissibles(profil, service):
    """``(résultat, None)`` ou ``(None, verdict)`` : les équipes admissibles pour ``service``, et les autres.

    Le résultat porte ``service``, ``duree_min``, ``competences_requises``, ``admissibles`` (identifiants, triés) et
    ``ecartees`` (une ligne par équipe : ``equipe``, ``code``, ``detail``). Sans équipe déclarée, ou sans exigence pour
    ce service : un verdict, pas un résultat vide."""
    exigences, verdict = exigences_du_service(profil, service)
    if verdict is not None:
        return None, verdict
    equipes = profil.get("liste")
    if not isinstance(equipes, list) or not equipes:
        return None, _verdict(
            f"aucune équipe déclarée : les déclarer dans le profil des équipes (clé equipes.liste, `{_DECLARER}`)"
        )
    duree = exigences["duree_min"]
    requises = set(exigences["competences"])
    admissibles = []
    ecartees = []
    for equipe in sorted(equipes, key=lambda e: e["id"]):
        manquantes = sorted(requises - set(equipe["competences"]))
        if manquantes:
            ecartees.append(_ecartee(
                equipe, CODE_COMPETENCE_MANQUANTE, "compétence manquante : " + ", ".join(manquantes)))
            continue
        plus_long = max(quart["fin_min"] - quart["debut_min"] for quart in equipe["quarts"])
        if plus_long < duree:
            ecartees.append(_ecartee(
                equipe, CODE_AUCUN_QUART_ASSEZ_LONG,
                f"aucun quart d'au moins {duree} minutes (le plus long : {plus_long} minutes)",
            ))
            continue
        admissibles.append(equipe["id"])
    return {
        "service": service,
        "duree_min": duree,
        "competences_requises": sorted(requises),
        "admissibles": admissibles,
        "ecartees": ecartees,
    }, None
