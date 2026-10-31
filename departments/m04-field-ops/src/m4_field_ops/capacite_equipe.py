"""Capacité des équipes pour une semaine : ce que le profil DÉCLARE, face à ce que la cédule APPLIQUÉE planifie
(contrat ``m4.capacite_equipe`` v1, lecture pure T0 ; voir ``docs/capacite-equipe.md``).

Module pur (stdlib et modules de M4 ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau) : il ne fait
QUE lire. Le profil des équipes (``opsys.equipes``) est lu par l'adaptateur (``outils.py``) et passé ici.

CE QUE LE CHIFFRE EST. ``heures_disponibles`` = les heures des QUARTS DÉCLARÉS de l'équipe (``fin_min - debut_min`` du
profil), une fois par journée DATÉE de la semaine ; ``heures_planifiees`` = la durée des créneaux de la cédule appliquée
dont la date civile est confirmée (``cedule_datee``). Une équipe est une unité de cédule : ce sont des heures d'horloge
du quart de l'équipe (unité ``heures_declarees``), JAMAIS des heures-personnes. Les membres déclarés ne sont ni lus ni
comptés : la déclaration d'une équipe ne vaut pas la présence d'une personne, et aucune présence individuelle n'est
déduite (ni absence signalée, ni pointage, ni position). Les absences signalées (``absences_journalieres``) ne sont PAS
déduites : elles sont individuelles, le profil ne porte aucun congé.

CE QUE LE PROFIL NE DIT PAS, et que ce module dit au lieu de l'inventer. Le ``jour`` d'un quart est le numéro de journée
d'un plan de cédule, pas un jour de semaine (docs/architecture/TAXONOMIE.md, « reste à faire ») : seule une journée
DATÉE par un administrateur (``m4_confirmer_dates_cedule``) relie ce numéro à une date civile. Une semaine sans journée
datée n'a donc AUCUNE disponibilité connue (non calculable, jamais zéro) ; une semaine partiellement datée ne compte que
ses journées datées (``portee`` = ``journees_datees_seulement``) : une borne basse de la capacité ouverte, pas de la
capacité totale.

Absence ≠ zéro, tout ou rien : dès qu'une équipe, une journée ou la cédule laisse un manque, ``calculable`` est faux, la
liste ``equipes`` est vide, aucun total n'est écrit, et ``manque`` nomme chaque cause par un code fermé. Les seules
chaînes qui sortent sont ces codes, des identifiants déjà validés et des dates ISO : aucun texte libre (nom d'équipe,
détail de verdict) n'est recopié, donc rien d'un nom d'équipe ne peut agir sur un lecteur.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import calendrier_civil, horodatage

CONTRAT = "m4.capacite_equipe"
VERSION = 1
UNITE = "heures_declarees"
PORTEE = "journees_datees_seulement"

MANQUE_PROFIL_NON_DECLARE = "profil_equipes_non_declare"
MANQUE_PROFIL_INVALIDE = "profil_equipes_invalide"
MANQUE_PROFIL_SANS_EQUIPES = "profil_sans_equipes"
MANQUE_CEDULE_NON_APPLIQUEE = "cedule_non_appliquee"
MANQUE_AUCUNE_JOURNEE_DATEE = "aucune_journee_datee_dans_la_semaine"
MANQUE_SANS_DATE = "interventions_planifiees_sans_date"  # suffixe ":N"
MANQUE_A_RECONFIRMER = "creneaux_a_reconfirmer"  # suffixe ":N"
MANQUE_QUART_AMBIGU = "quart_ambigu"  # suffixes ":equipe:date"
MANQUE_EQUIPE_NON_DECLAREE = "equipe_planifiee_non_declaree"  # suffixe ":equipe"

AVERTISSEMENTS = (
    "Heures d'horloge du quart déclaré de chaque équipe (une équipe = une unité de cédule), "
    "jamais des heures-personnes.",
    "Déclaration d'équipe n'est pas présence individuelle : aucun membre n'est compté, aucune absence signalée "
    "ni aucun pointage n'est déduit.",
    "Seules les journées datées par un administrateur comptent : une borne basse de la capacité ouverte, "
    "pas la capacité totale de la semaine.",
)

_CODE_VERDICT_NON_DECLARE = "REJ-EQUIPES-NON-CONFIGUREES"
_IDENTIFIANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_DECIMAL = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,4})?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# Un créneau « à reconfirmer » dont l'intervention est sortie de la cédule (reportée, annulée, à replanifier) ne
# planifie plus rien : il n'est pas un manque. Tout autre est une charge dont la date n'est plus fiable.
_SORTIES_DE_LA_CEDULE = frozenset({"reportee", "annulee", "a_planifier"})
_CLES_RACINE = frozenset({
    "contrat", "version", "semaine_debut", "fuseau", "unite", "portee", "lu_a", "calculable", "manque", "equipes",
    "jours_dates", "sources", "avertissements", "heures_disponibles", "heures_planifiees",
    "minutes_disponibles", "minutes_planifiees",
})
_CLES_EQUIPE = frozenset({
    "equipe_id", "heures_disponibles", "heures_planifiees", "minutes_disponibles", "minutes_planifiees",
})


class ChargeIncoherente(ValueError):
    """La charge produite (ou présentée) ne respecte pas le contrat ``m4.capacite_equipe`` v1."""


def heures(minutes: int) -> str:
    """Texte décimal des heures : ``minutes / 60`` arrondi au dix-millième (demi vers le haut), au moins deux décimales
    (``"9.00"``, ``"0.1667"``). Les minutes entières exactes sont écrites à côté (``minutes_*``) : l'arrondi ne cache
    rien."""
    if type(minutes) is not int or minutes < 0:
        raise ValueError("minutes entières positives ou nulles requises")
    valeur = (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    texte = format(valeur, "f")
    entier, decimales = texte.split(".")
    return f"{entier}.{decimales.rstrip('0').ljust(2, '0')}"


def _identifiant_sur(valeur: Any) -> str | None:
    return valeur if isinstance(valeur, str) and _IDENTIFIANT.fullmatch(valeur) else None


def _suffixe_equipe(prefixe: str, equipe: Any) -> str:
    sur = _identifiant_sur(equipe)
    return f"{prefixe}:{sur}" if sur is not None else prefixe


def _semaine(debut_semaine: Any) -> tuple[date, datetime, datetime]:
    jour = calendrier_civil._date(debut_semaine)
    if jour.weekday() != 0:
        raise ValueError("debut_semaine doit être un lundi")
    debut = calendrier_civil.instant_local(jour.isoformat(), 0)
    fin = calendrier_civil.instant_local((jour + timedelta(days=7)).isoformat(), 0)
    return jour, debut, fin


def _jours_dates(
    dates: dict, applications: dict, propositions: dict, detenteurs: dict, lundi: date,
) -> tuple[dict[date, set[int]], int | None, str | None]:
    """``({date civile de la semaine: {numéros de journée de plan}}, révision max, dernière confirmation)`` d'après la
    dernière confirmation de dates de chaque plan APPLIQUÉ qui détient encore au moins une intervention (un plan
    entièrement remplacé ne dit plus rien du calendrier). Un calendrier illisible lève ``ValueError`` (preuve
    incohérente : jamais ignoré en silence)."""
    dimanche = lundi + timedelta(days=6)
    vivants = set(detenteurs.values())
    par_date: dict[date, set[int]] = {}
    revision: int | None = None
    confirme: tuple[datetime, str] | None = None
    for plan_id, (_, entree) in sorted(dates.items()):
        if plan_id not in applications or plan_id not in propositions or plan_id not in vivants:
            continue
        calendrier = entree.get("calendrier")
        if not isinstance(calendrier, dict):
            raise ValueError("calendrier daté illisible")
        pris = False
        for cle, texte in calendrier.items():
            if not isinstance(cle, str) or not cle.isascii() or not cle.isdigit() or str(int(cle)) != cle:
                raise ValueError("calendrier daté illisible")
            jour_civil = calendrier_civil._date(texte)
            if lundi <= jour_civil <= dimanche:
                par_date.setdefault(jour_civil, set()).add(int(cle))
                pris = True
        if pris:
            numero = entree.get("revision")
            if type(numero) is int:
                revision = numero if revision is None else max(revision, numero)
            instant = entree.get("horodatage")
            if isinstance(instant, str):
                lu = datetime.fromisoformat(instant)
                if lu.tzinfo is not None and (confirme is None or lu.astimezone(UTC) > confirme[0]):
                    confirme = (lu.astimezone(UTC), instant)
    return par_date, revision, confirme[1] if confirme else None


def calculer(
    registre_cible: Any,
    profil: dict[str, Any] | None,
    verdict_profil: dict[str, Any] | None,
    empreinte_profil: str | None,
    debut_semaine: str,
    horodatage_reference: str | None = None,
) -> dict[str, Any]:
    """Charge ``m4.capacite_equipe`` de la semaine qui commence le lundi ``debut_semaine`` (AAAA-MM-JJ, Montréal).

    ``profil`` / ``verdict_profil`` : ce que rend ``opsys.equipes.charger_equipes()`` (le verdict n'est lu que par son
    ``code``). ``horodatage_reference`` : l'instant de lecture que l'appelant donne (ISO 8601 avec fuseau) et que la
    charge recopie en ``lu_a`` ; M4 n'a pas d'horloge. Lecture seule : rien n'est écrit au registre.

    Lève ``ValueError`` (semaine ou instant invalide), ``cedule_tournees.PreuvePlanInvalide`` et
    ``registre.VerificationError`` (preuve du registre incohérente) : l'appelant les traduit en refus, jamais en
    capacité."""
    lundi, debut_w, fin_w = _semaine(debut_semaine)
    reference = None if horodatage_reference is None else horodatage.valider_horodatage(horodatage_reference)

    maillons, propositions, applications, dates, detenteurs, _ = index = calendrier_civil._index(registre_cible)
    par_date, revision_max, confirme_le = _jours_dates(dates, applications, propositions, detenteurs, lundi)
    sources = {
        "profil_empreinte": empreinte_profil,
        "registre_tete": maillons[-1]["ligne_id"] if maillons else None,
        "plans_appliques": len(applications),
        "plans_proposes_non_appliques": len(set(propositions) - set(applications)),
        "cedule_revision_max": revision_max,
        "cedule_confirmee_le": confirme_le,
    }
    manque: list[str] = []

    # -- le profil : déclaré, valide, avec des équipes --------------------------------------------------------------
    equipes_declarees: dict[str, dict[int, int]] = {}
    if verdict_profil is not None or profil is None:
        code = verdict_profil.get("code") if isinstance(verdict_profil, dict) else None
        manque.append(MANQUE_PROFIL_NON_DECLARE if code == _CODE_VERDICT_NON_DECLARE else MANQUE_PROFIL_INVALIDE)
    else:
        for equipe in profil.get("liste", ()):
            equipes_declarees[equipe["id"]] = {
                quart["jour"]: quart["fin_min"] - quart["debut_min"] for quart in equipe["quarts"]
            }
        if not equipes_declarees:
            manque.append(MANQUE_PROFIL_SANS_EQUIPES)

    # -- la cédule appliquée : de quoi savoir ce qui est planifié, et quand ------------------------------------------
    planifiees: dict[str, int] = {}
    if not applications:
        manque.append(MANQUE_CEDULE_NON_APPLIQUEE)
    else:
        lignes, sans_date = calendrier_civil._projection(index)
        a_reconfirmer = 0
        for ligne in lignes:
            debut_l, fin_l = datetime.fromisoformat(ligne["debut"]), datetime.fromisoformat(ligne["fin"])
            if not (debut_l < fin_w and fin_l > debut_w):
                continue
            if ligne["validite"] != "date_confirmee":
                if ligne["statut"] not in _SORTIES_DE_LA_CEDULE:
                    a_reconfirmer += 1
                continue
            recouvrement = min(fin_l, fin_w) - max(debut_l, debut_w)
            minutes = int(recouvrement.total_seconds() // 60)
            planifiees[ligne["equipe_id"]] = planifiees.get(ligne["equipe_id"], 0) + minutes
        sans_date_actives = sum(1 for entree in sans_date if entree["statut"] not in _SORTIES_DE_LA_CEDULE)
        if a_reconfirmer:
            manque.append(f"{MANQUE_A_RECONFIRMER}:{a_reconfirmer}")
        if sans_date_actives:
            manque.append(f"{MANQUE_SANS_DATE}:{sans_date_actives}")
        if not par_date:
            manque.append(MANQUE_AUCUNE_JOURNEE_DATEE)
        if equipes_declarees:  # sans profil exploitable, le manque est déjà dit : pas de second bruit
            for equipe in sorted(set(planifiees) - set(equipes_declarees)):
                manque.append(_suffixe_equipe(MANQUE_EQUIPE_NON_DECLAREE, equipe))

    # -- la disponibilité déclarée, sur les journées datées ----------------------------------------------------------
    disponibles: dict[str, int] = {}
    for equipe, quarts in sorted(equipes_declarees.items()):
        total = 0
        for jour_civil, numeros in sorted(par_date.items()):
            valeurs = {quarts.get(numero, 0) for numero in numeros}
            if len(valeurs) != 1:
                manque.append(f"{_suffixe_equipe(MANQUE_QUART_AMBIGU, equipe)}:{jour_civil.isoformat()}")
                continue
            total += valeurs.pop()
        disponibles[equipe] = total

    charge: dict[str, Any] = {
        "contrat": CONTRAT,
        "version": VERSION,
        "semaine_debut": lundi.isoformat(),
        "fuseau": calendrier_civil.FUSEAU,
        "unite": UNITE,
        "portee": PORTEE,
        "lu_a": reference,
        "jours_dates": [jour_civil.isoformat() for jour_civil in sorted(par_date)],
        "sources": sources,
        "avertissements": list(AVERTISSEMENTS),
    }
    manque = sorted(set(manque))
    if manque:
        charge.update({"calculable": False, "manque": manque, "equipes": []})
    else:
        lignes_equipes = [
            {
                "equipe_id": equipe,
                "heures_disponibles": heures(disponibles[equipe]),
                "heures_planifiees": heures(planifiees.get(equipe, 0)),
                "minutes_disponibles": disponibles[equipe],
                "minutes_planifiees": planifiees.get(equipe, 0),
            }
            for equipe in sorted(equipes_declarees)
        ]
        total_dispo = sum(ligne["minutes_disponibles"] for ligne in lignes_equipes)
        total_plan = sum(ligne["minutes_planifiees"] for ligne in lignes_equipes)
        charge.update({
            "calculable": True, "manque": [], "equipes": lignes_equipes,
            "heures_disponibles": heures(total_dispo), "heures_planifiees": heures(total_plan),
            "minutes_disponibles": total_dispo, "minutes_planifiees": total_plan,
        })
    verifier_charge(charge)
    return charge


# ---------------------------------------------------------------------------
# Contrôle de la charge : celui que le producteur s'impose, et que tout lecteur peut refaire
# ---------------------------------------------------------------------------
def _decimal(valeur: Any) -> bool:
    return isinstance(valeur, str) and _DECIMAL.fullmatch(valeur) is not None


def verifier_charge(charge: Any) -> None:
    """Lève ``ChargeIncoherente`` si ``charge`` n'est pas une charge ``m4.capacite_equipe`` v1 cohérente.

    Refuse : une clé inconnue ou manquante, une unité autre que ``heures_declarees`` (jamais convertie), une date ou une
    équipe mal formée, un nombre qui n'est pas un texte décimal, un ``calculable`` faux avec une valeur ou sans cause
    nommée, un ``calculable`` vrai avec un manque, sans équipe ou avec des totaux qui ne sont pas la somme des équipes.
    Rien n'est corrigé."""
    if not isinstance(charge, dict):
        raise ChargeIncoherente("charge non objet")
    calculable = charge.get("calculable")
    inconnues = sorted(set(charge) - _CLES_RACINE)
    if inconnues:
        raise ChargeIncoherente(f"clés inconnues {inconnues}")
    obligatoires = {"contrat", "version", "semaine_debut", "unite", "calculable", "manque", "equipes"}
    absentes = sorted(obligatoires - set(charge))
    if absentes:
        raise ChargeIncoherente(f"clés manquantes {absentes}")
    if charge["contrat"] != CONTRAT or charge["version"] != VERSION:
        raise ChargeIncoherente("contrat ou version inconnus")
    if charge["unite"] != UNITE:
        raise ChargeIncoherente(f"unité {charge['unite']!r} refusée : seule {UNITE!r} est admise, rien n'est converti")
    semaine = charge["semaine_debut"]
    if not isinstance(semaine, str) or _DATE.fullmatch(semaine) is None:
        raise ChargeIncoherente("semaine_debut : date AAAA-MM-JJ attendue")
    try:
        if date.fromisoformat(semaine).weekday() != 0:
            raise ChargeIncoherente("semaine_debut doit être un lundi")
    except ValueError:
        raise ChargeIncoherente("semaine_debut : date réelle attendue") from None
    if type(calculable) is not bool:
        raise ChargeIncoherente("calculable : booléen attendu")
    manque, equipes = charge["manque"], charge["equipes"]
    if not isinstance(manque, list) or not all(isinstance(m, str) and m.strip() for m in manque):
        raise ChargeIncoherente("manque : liste de codes attendue")
    if not isinstance(equipes, list):
        raise ChargeIncoherente("equipes : liste attendue")
    valeurs = {"heures_disponibles", "heures_planifiees", "minutes_disponibles", "minutes_planifiees"}
    if not calculable:
        if not manque:
            raise ChargeIncoherente("calculable faux sans manque nommé")
        if equipes or valeurs & set(charge):
            raise ChargeIncoherente("calculable faux : aucune valeur n'est écrite (absence n'est pas zéro)")
        return
    if manque:
        raise ChargeIncoherente("calculable vrai avec un manque")
    if not equipes:
        raise ChargeIncoherente("calculable vrai sans aucune équipe")
    if valeurs - set(charge):
        raise ChargeIncoherente("calculable vrai : totaux manquants")
    identifiants: list[str] = []
    somme = {"minutes_disponibles": 0, "minutes_planifiees": 0}
    for position, ligne in enumerate(equipes):
        if not isinstance(ligne, dict) or set(ligne) != _CLES_EQUIPE:
            raise ChargeIncoherente(f"equipes[{position}] : clés {sorted(_CLES_EQUIPE)} attendues")
        if _identifiant_sur(ligne["equipe_id"]) is None:
            raise ChargeIncoherente(f"equipes[{position}].equipe_id : identifiant attendu")
        identifiants.append(ligne["equipe_id"])
        for cle in ("minutes_disponibles", "minutes_planifiees"):
            minutes = ligne[cle]
            if type(minutes) is not int or minutes < 0:
                raise ChargeIncoherente(f"equipes[{position}].{cle} : entier positif ou nul attendu")
            somme[cle] += minutes
            heures_cle = cle.replace("minutes", "heures")
            if not _decimal(ligne[heures_cle]) or ligne[heures_cle] != heures(minutes):
                raise ChargeIncoherente(f"equipes[{position}].{heures_cle} : texte décimal de {cle} attendu")
    if len(set(identifiants)) != len(identifiants):
        raise ChargeIncoherente("equipe_id en double")
    for cle, total in somme.items():
        if charge[cle] != total or charge[cle.replace("minutes", "heures")] != heures(total):
            raise ChargeIncoherente(f"{cle} : le total n'est pas la somme des équipes")
