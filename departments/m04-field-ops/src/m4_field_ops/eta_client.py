"""Estimation d'arrivée pour le client (M4.14) : une FENÊTRE, jamais une heure unique, jamais une promesse.

D'OÙ VIENT LA FENÊTRE. De trois faits, tous fournis par l'adaptateur depuis ce que M4 sait :

* le CRÉNEAU de la cédule appliquée et datée (``calendrier_civil``) : on n'arrive pas avant son début (le client l'a
  attendu à cette heure) ;
* le TRAJET depuis le point de départ de l'équipe (fin du chantier précédent ou dépôt), en secondes, rendu par le port
  de routage (``distances.obtenir_matrice`` : palier 0 approximatif « mode bridé », ou un routeur auto-hébergé
  OSRM/Valhalla si l'on en branche un ; AUCUN routeur n'est installé ici) ;
* les RETARDS DÉCLARÉS (minutes, par l'équipe ou l'administrateur) et l'incertitude de trajet que l'entreprise a
  DÉCLARÉE.

    bas  = max(début du créneau, départ + trajet)
    haut = max(début du créneau, départ + trajet x (100 + incertitude) / 100) + retards déclarés
    haut = max(haut, bas + largeur minimale)          # jamais une heure unique
    bas arrondi vers le bas, haut vers le haut, à la granularité déclarée

Sans départ connu, la fenêtre part du début du créneau seul (``sources`` le dit). Une fenêtre déjà dépassée à
``horodatage_reference`` n'est PAS rendue (``REJ-ETA-FENETRE-DEPASSEE``) : on ne promet pas une arrivée passée.

CE QUE LA SORTIE NE CONTIENT JAMAIS : la position de l'équipe ou d'une personne, le point de départ, un nom, une
adresse, un lien de suivi. Un client ne reçoit qu'une fenêtre de temps.

Calcul en secondes entières (``datetime`` pour lire et écrire des instants ISO 8601 seulement : aucune horloge).
Module pur : stdlib seulement, aucun import ``opsys``, aucun aléa, aucun réseau.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from . import encodage, verdicts

__all__ = ["SCHEMA", "composer_message", "estimer", "lire_parametres"]

SCHEMA = "m4.eta_client/1"
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,79}$")
_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_GRANULARITES = frozenset({5, 10, 15, 30, 60})
_EPOQUE = datetime(1970, 1, 1, tzinfo=UTC)


def _refus(code: str, detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail=detail)


def _instant(texte: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(texte) if isinstance(texte, str) else None
    except ValueError:
        return None
    return d if d is not None and d.tzinfo is not None else None


def lire_parametres(brut: Any) -> tuple[dict[str, int] | None, dict[str, Any] | None]:
    """Les réglages que l'entreprise DÉCLARE (``configuration.eta_client``). Aucun défaut : absents, le verdict dit
    quoi déclarer."""
    detail = (
        "déclarer configuration.eta_client : incertitude_trajet_pct (0 à 200), largeur_minimale_minutes (5 à "
        "240), "
        "granularite_minutes (5, 10, 15, 30 ou 60), validite_consentement_jours (1 à 30), conservation_heures "
        "(1 à 720) et messages_max_par_intervention (1 à 10)"
    )
    bornes = {
        "incertitude_trajet_pct": (0, 200),
        "largeur_minimale_minutes": (5, 240),
        "granularite_minutes": (5, 60),
        "validite_consentement_jours": (1, 30),
        "conservation_heures": (1, 720),
        "messages_max_par_intervention": (1, 10),
    }
    if not isinstance(brut, Mapping) or set(brut) - set(bornes):
        return None, _refus("REJ-ETA-PARAMETRES-ABSENTS", f"réglages absents ou non admis : {detail}")
    for cle, (minimum, maximum) in bornes.items():
        v = brut.get(cle)
        if type(v) is not int or not minimum <= v <= maximum:
            return None, _refus("REJ-ETA-PARAMETRES-ABSENTS", f"{cle} absent ou hors bornes : {detail}")
    if brut["granularite_minutes"] not in _GRANULARITES:
        return None, _refus("REJ-ETA-PARAMETRES-ABSENTS", f"granularite_minutes invalide : {detail}")
    if brut["largeur_minimale_minutes"] < brut["granularite_minutes"]:
        return None, _refus(
            "REJ-ETA-PARAMETRES-ABSENTS",
            "largeur_minimale_minutes < granularite_minutes : la fenêtre pourrait se réduire à un instant",
        )
    return {cle: brut[cle] for cle in bornes}, None


def estimer(entrees: Any, parametres: Mapping[str, int]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(eta, None)`` ou ``(None, verdict)``. ``entrees`` : ``intervention_id``, ``creneau`` (``debut``, ``fin``),
    ``depart`` (``instant``, ``trajet_secondes``, ``origine``, ``approximatif``) ou ``None``,
    ``retards_declares_minutes`` et
    ``horodatage_reference``."""
    cles = {"intervention_id", "creneau", "depart", "retards_declares_minutes", "horodatage_reference"}
    if not isinstance(entrees, Mapping) or set(entrees) != cles:
        return None, _refus("REJ-ETA-ENTREE-INVALIDE", f"entrées : {', '.join(sorted(cles))} (rien d'autre)")
    iid = entrees["intervention_id"]
    creneau = entrees["creneau"]
    debut = _instant(creneau.get("debut")) if isinstance(creneau, Mapping) else None
    fin = _instant(creneau.get("fin")) if isinstance(creneau, Mapping) else None
    reference = _instant(entrees["horodatage_reference"])
    retards = entrees["retards_declares_minutes"]
    if (
        not isinstance(iid, str)
        or not _IDENTIFIANT.fullmatch(iid)
        or debut is None
        or fin is None
        or reference is None
        or fin <= debut
        or not isinstance(retards, list)
        or len(retards) > 20
        or not all(type(r) is int and 0 <= r <= 480 for r in retards)
        or sum(retards) > 480
    ):
        return None, _refus(
            "REJ-ETA-ENTREE-INVALIDE",
            "intervention_id, créneau (debut < fin, avec fuseau), horodatage_reference et retards "
            "(0 à 480 minutes, 480 au total) valides requis",
        )
    depart = entrees["depart"]
    approximatif, sources = False, ["creneau_cedule"]
    physique_bas = physique_haut = None
    if depart is not None:
        origine = depart.get("origine") if isinstance(depart, Mapping) else None
        depart_t = _instant(depart.get("instant")) if isinstance(depart, Mapping) else None
        trajet = depart.get("trajet_secondes") if isinstance(depart, Mapping) else None
        if (
            not isinstance(depart, Mapping)
            or set(depart) != {"instant", "trajet_secondes", "origine", "approximatif"}
            or origine not in ("fin_intervention_precedente", "depot")
            or depart_t is None
            or type(trajet) is not int
            or not 0 <= trajet <= 86400
            or type(depart["approximatif"]) is not bool
        ):
            return None, _refus(
                "REJ-ETA-ENTREE-INVALIDE",
                "depart : instant, trajet_secondes (0 à 86 400), origine et approximatif requis, ou null",
            )
        approximatif = depart["approximatif"]
        base = int(depart_t.timestamp())
        physique_bas = base + trajet
        physique_haut = base + -(-trajet * (100 + parametres["incertitude_trajet_pct"]) // 100)  # plafond entier
        sources.append("trajet_" + ("approximatif" if approximatif else "routier") + "_depuis_" + origine)
    d = int(debut.timestamp())
    bas = d if physique_bas is None else max(d, physique_bas)
    haut = d if physique_haut is None else max(d, physique_haut)
    haut += sum(retards) * 60
    if retards:
        sources.append("retards_declares")
    haut = max(haut, bas + parametres["largeur_minimale_minutes"] * 60)
    pas = parametres["granularite_minutes"] * 60
    bas = (bas // pas) * pas
    haut = -(-haut // pas) * pas
    if int(reference.timestamp()) >= haut:
        return None, _refus(
            "REJ-ETA-FENETRE-DEPASSEE",
            "la fenêtre d'arrivée estimée est déjà passée : aucune arrivée passée n'est annoncée",
        )
    fuseau = debut.tzinfo
    fenetre_debut = (_EPOQUE + timedelta(seconds=bas)).astimezone(fuseau)
    fenetre_fin = (_EPOQUE + timedelta(seconds=haut)).astimezone(fuseau)
    avertissements = ["estimation, pas une promesse : la fenêtre peut changer"]
    if approximatif:
        avertissements.append("trajet approximatif (mode bridé, aucun routeur) : plus grossier qu'un trajet routier")
    if bas > int(fin.timestamp()):
        avertissements.append("l'arrivée estimée dépasse la fin du créneau planifié")
    eta = {
        "schema": SCHEMA,
        "intervention_id": iid,
        "fenetre": {
            "debut": fenetre_debut.isoformat(),
            "fin": fenetre_fin.isoformat(),
            "largeur_minutes": (haut - bas) // 60,
        },
        "promesse": False,
        "approximatif": approximatif,
        "sources": sources,
        "avertissements": avertissements,
        "retards_declares_minutes": sum(retards),
        "parametres": {
            k: parametres[k] for k in ("incertitude_trajet_pct", "largeur_minimale_minutes", "granularite_minutes")
        },
    }
    eta["empreinte"] = encodage.empreinte(SCHEMA, eta)
    return eta, None


def _heure(d: datetime) -> str:
    return f"{d.hour} h" if d.minute == 0 else f"{d.hour} h {d.minute:02d}"


def composer_message(fenetre: Mapping[str, str]) -> str:
    """Le texte FIXE du brouillon destiné au client : une fenêtre, un avertissement, le moyen de se retirer. Aucun
    nom, aucune
    adresse, aucune position, aucun lien, aucun prix."""
    debut, fin = datetime.fromisoformat(fenetre["debut"]), datetime.fromisoformat(fenetre["fin"])
    jour = "1er" if debut.day == 1 else str(debut.day)
    texte = (
        f"Bonjour. L'équipe prévoit arriver chez vous le {_JOURS[debut.weekday()]} {jour} {_MOIS[debut.month - 1]} "
        f"entre {_heure(debut)} et {_heure(fin)}."
    )
    if fin.date() != debut.date():
        texte = (
            "Bonjour. L'équipe prévoit arriver chez vous entre le "
            f"{_JOURS[debut.weekday()]} {jour} {_MOIS[debut.month - 1]} "
            f"à {_heure(debut)} et le {_JOURS[fin.weekday()]} {fin.day} {_MOIS[fin.month - 1]} à {_heure(fin)}."
        )
    return (
        texte + " Cette fenêtre est une estimation, pas une promesse : nous vous aviserons de tout changement. "
        "Pour ne plus recevoir ces avis, répondez STOP."
    )
