"""`m4.projection_capacite` : la capacité d'une semaine SOUS HYPOTHÈSES déclarées (« et si… »), calculée par M4.

Module pur : aucune entrée-sortie, aucune horloge, aucun aléa. Il prolonge `capacite_equipe` (le contrat v1, inchangé)
sans
jamais le contredire : la BASE est la charge `m4.capacite_equipe` calculable de la semaine (heures de quart DÉCLARÉES,
heures de la cédule appliquée), et les hypothèses sont celles qu'une PERSONNE déclare — M4 n'en choisit aucune :

* `absences` : pour une équipe, `personnes` absentes pendant `jours` jours. Elles se convertissent en perte d'heures
  d'équipe SEULEMENT par la conversion que le propriétaire a déclarée (`duree_jour_personne_minutes` du profil et
  `effectif_planifie` de l'équipe) : perte = personnes × jours × durée / effectif. Sans l'un des deux, la projection est
  NON CALCULABLE et nomme ce qui manque (jamais une durée, un effectif de 1 ou une perte supposés) ;
* `jours_bloques` : des jours civils de la semaine (mauvaise météo, par exemple) où toutes les équipes ne travaillent
pas.
  M4 les traite comme un congé d'équipe et recalcule la semaine type (`semaine_type` seulement : une semaine datée par
  journées de plan ne se relie pas à un jour civil de façon sûre) ;
* `hausse_demande_pct` : les heures planifiées de la cédule augmentent de ce pourcentage (hypothèse de proportionnalité
  déclarée, pas une prévision de demande).

Tout ou rien (comme `capacite_equipe`) : un seul manque rend la projection non calculable pour toutes les équipes. Un
résultat nul ou négatif n'est jamais ramené à zéro en silence : la capacité épuisée est dite (`capacite_epuisee`).

REÇU REJOUABLE : le reçu porte la méthode, les entrées (base, hypothèses, sources du profil et du registre), le résultat
et leur empreinte SHA-256. `verifier_recu` refait le calcul à partir des SEULES entrées du reçu et compare ; aucun
registre
n'est relu. Les nombres sont des textes décimaux ; les minutes d'une perte non entière gardent deux décimales.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CONTRAT = "m4.projection_capacite"
VERSION = 1
METHODE = "m4.projection_capacite.v1"
UNITE = "heures_declarees"
MAX_ABSENCES = 20
PERSONNES_MAX = 50
JOURS_ABSENCE_MAX = 7
HAUSSE_MAX = Decimal("1000")
MANQUE_EFFECTIF = "effectif_planifie_non_declare"
MANQUE_DUREE = "duree_jour_personne_minutes_non_declaree"
MANQUE_BASE = "base_non_calculable"
_DEUX = Decimal("0.01")
_UN_DIXIEME = Decimal("0.1")
_CLES_HYPOTHESES = frozenset({"absences", "jours_bloques", "hausse_demande_pct"})
_CLES_ABSENCE = frozenset({"equipe_id", "personnes", "jours"})
_CLES_BASE = frozenset({"unite", "semaine_debut", "portee", "duree_jour_personne_minutes", "equipes"})
_CLES_EQUIPE_BASE = frozenset(
    {"equipe_id", "minutes_disponibles", "minutes_planifiees", "effectif_planifie", "perte_jours_bloques_minutes"}
)


def _refus(detail: str) -> ValueError:
    return ValueError(f"REJ-PROJECTION-INVALIDE : {detail}")


def _entier(valeur: Any, minimum: int, maximum: int, nom: str) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int) or not minimum <= valeur <= maximum:
        raise _refus(f"{nom} : entier de {minimum} à {maximum}")
    return valeur


def _texte_decimal(valeur: Decimal) -> str:
    return format(valeur, "f")


def heures(minutes: Decimal) -> str:
    """Heures d'horloge en texte, au centième (demi vers le haut)."""
    return _texte_decimal((minutes / Decimal(60)).quantize(_DEUX, rounding=ROUND_HALF_UP))


def valider_hypotheses(brut: Any, *, portee: str, semaine_debut: str, equipes: set[str]) -> dict[str, Any]:
    """Les hypothèses NORMALISÉES, ou un refus nommé : une au moins, aucune clé en trop, chaque valeur bornée."""
    if not isinstance(brut, Mapping) or not brut or set(brut) - _CLES_HYPOTHESES:
        raise _refus(f"hypotheses : objet non vide parmi {sorted(_CLES_HYPOTHESES)}")
    propres: dict[str, Any] = {}
    if "absences" in brut:
        absences = brut["absences"]
        if not isinstance(absences, list) or not 1 <= len(absences) <= MAX_ABSENCES:
            raise _refus(f"absences : liste de 1 à {MAX_ABSENCES} entrées")
        lignes = []
        for rang, absence in enumerate(absences):
            if not isinstance(absence, Mapping) or set(absence) != _CLES_ABSENCE:
                raise _refus(f"absences[{rang}] : exactement {sorted(_CLES_ABSENCE)}")
            if absence["equipe_id"] not in equipes:
                raise _refus(f"absences[{rang}].equipe_id : équipe inconnue de la charge")
            lignes.append(
                {
                    "equipe_id": absence["equipe_id"],
                    "personnes": _entier(absence["personnes"], 1, PERSONNES_MAX, f"absences[{rang}].personnes"),
                    "jours": _entier(absence["jours"], 1, JOURS_ABSENCE_MAX, f"absences[{rang}].jours"),
                }
            )
        propres["absences"] = sorted(lignes, key=lambda a: (a["equipe_id"], a["personnes"], a["jours"]))
    if "jours_bloques" in brut:
        if portee != "semaine_type":
            raise _refus("jours_bloques : exige la portée semaine_type (jour civil relié à la semaine type déclarée)")
        jours = brut["jours_bloques"]
        lundi = date.fromisoformat(semaine_debut)
        semaine = {(lundi + timedelta(days=k)).isoformat() for k in range(7)}
        if (
            not isinstance(jours, list)
            or not 1 <= len(jours) <= 7
            or len(set(map(str, jours))) != len(jours)
            or not all(isinstance(j, str) and j in semaine for j in jours)
        ):
            raise _refus("jours_bloques : 1 à 7 jours distincts AAAA-MM-JJ de la semaine demandée")
        propres["jours_bloques"] = sorted(jours)
    if "hausse_demande_pct" in brut:
        texte = brut["hausse_demande_pct"]
        try:
            hausse = Decimal(texte) if isinstance(texte, str) else None
        except InvalidOperation:
            hausse = None
        if hausse is None or not hausse.is_finite() or not 0 <= hausse <= HAUSSE_MAX or hausse.as_tuple().exponent < -2:
            raise _refus("hausse_demande_pct : texte décimal de 0 à 1000, deux décimales au plus")
        propres["hausse_demande_pct"] = _texte_decimal(hausse)
    return propres


def base_depuis_charge(charge: Mapping[str, Any], pertes_jours_bloques: Mapping[str, int] | None) -> dict[str, Any]:
    """La base d'une projection : les chiffres de la charge calculable (rien d'autre n'est lu)."""
    pertes = pertes_jours_bloques or {}
    equipes = []
    for ligne in charge["equipes"]:
        equipes.append(
            {
                "equipe_id": ligne["equipe_id"],
                "minutes_disponibles": ligne["minutes_disponibles"],
                "minutes_planifiees": ligne["minutes_planifiees"],
                "effectif_planifie": ligne.get("effectif_planifie"),
                "perte_jours_bloques_minutes": pertes.get(ligne["equipe_id"], 0),
            }
        )
    return {
        "unite": UNITE,
        "semaine_debut": charge["semaine_debut"],
        "portee": charge["portee"],
        "duree_jour_personne_minutes": charge.get("duree_jour_personne_minutes"),
        "equipes": equipes,
    }


def appliquer(base: Mapping[str, Any], hypotheses: Mapping[str, Any]) -> dict[str, Any]:
    """Le résultat de la projection : fonction PURE de (base, hypothèses). `calculable` faux : aucun chiffre."""
    duree = base["duree_jour_personne_minutes"]
    absences: dict[str, int] = {}
    for absence in hypotheses.get("absences", ()):
        absences[absence["equipe_id"]] = absences.get(absence["equipe_id"], 0) + absence["personnes"] * absence["jours"]
    manque = []
    for ligne in base["equipes"]:
        if absences.get(ligne["equipe_id"]):
            if duree is None:
                manque.append(MANQUE_DUREE)
            if ligne["effectif_planifie"] is None:
                manque.append(f"{MANQUE_EFFECTIF}:{ligne['equipe_id']}")
    if manque:
        return {"calculable": False, "manque": sorted(set(manque)), "equipes": []}
    bloques = bool(hypotheses.get("jours_bloques"))
    hausse = Decimal(hypotheses.get("hausse_demande_pct", "0"))
    lignes = []
    for ligne in base["equipes"]:
        disponibles = Decimal(ligne["minutes_disponibles"])
        perte_blocage = Decimal(ligne["perte_jours_bloques_minutes"]) if bloques else Decimal(0)
        personnes_jours = absences.get(ligne["equipe_id"], 0)
        perte_absence = (
            (Decimal(personnes_jours) * Decimal(duree) / Decimal(ligne["effectif_planifie"])).quantize(
                _DEUX, rounding=ROUND_HALF_UP
            )
            if personnes_jours
            else Decimal(0)
        )
        brut = disponibles - perte_blocage - perte_absence
        projetees = max(brut, Decimal(0))
        planifiees = (Decimal(ligne["minutes_planifiees"]) * (Decimal(100) + hausse) / Decimal(100)).quantize(
            _DEUX, rounding=ROUND_HALF_UP
        )
        solde = projetees - planifiees
        lignes.append(
            {
                "equipe_id": ligne["equipe_id"],
                "heures_disponibles_base": heures(disponibles),
                "heures_planifiees_base": heures(Decimal(ligne["minutes_planifiees"])),
                "perte_jours_bloques_heures": heures(perte_blocage),
                "perte_absences_heures": heures(perte_absence),
                "heures_disponibles_projetees": heures(projetees),
                "heures_planifiees_projetees": heures(planifiees),
                "solde_heures": heures(solde) if solde >= 0 else "-" + heures(-solde),
                "capacite_epuisee": brut <= 0,
                "statut": "SURCHARGE" if planifiees > projetees else "SUFFISANTE",
                "utilisation_pct": _texte_decimal(
                    (planifiees * 100 / projetees).quantize(_UN_DIXIEME, rounding=ROUND_HALF_UP)
                )
                if projetees > 0
                else None,
            }
        )
    return {
        "calculable": True,
        "manque": [],
        "equipes": lignes,
        "equipes_en_surcharge": [ligne["equipe_id"] for ligne in lignes if ligne["statut"] == "SURCHARGE"],
    }


def _empreinte(methode: str, entrees: Mapping[str, Any], resultat: Mapping[str, Any]) -> str:
    texte = json.dumps(
        {"methode": methode, "entrees": entrees, "resultat": resultat},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def construire_recu(
    base: Mapping[str, Any], hypotheses: Mapping[str, Any], sources: Mapping[str, Any]
) -> dict[str, Any]:
    entrees = {"base": dict(base), "hypotheses": dict(hypotheses), "sources": dict(sources)}
    resultat = appliquer(base, hypotheses)
    return {
        "contrat": CONTRAT,
        "version": VERSION,
        "methode": METHODE,
        "entrees": entrees,
        "resultat": resultat,
        "empreinte": _empreinte(METHODE, entrees, resultat),
    }


def verifier_recu(recu: Any) -> dict[str, Any]:
    """Refait le calcul à partir des seules entrées du reçu. Lève `ValueError` (reçu mal formé) ; sinon dit si
    l'empreinte et le résultat se retrouvent."""
    if (
        not isinstance(recu, Mapping)
        or set(recu) != {"contrat", "version", "methode", "entrees", "resultat", "empreinte"}
        or recu["contrat"] != CONTRAT
        or recu["version"] != VERSION
        or recu["methode"] != METHODE
        or not isinstance(recu["entrees"], Mapping)
        or set(recu["entrees"]) != {"base", "hypotheses", "sources"}
    ):
        raise _refus("reçu : forme inconnue")
    base, hypotheses = recu["entrees"]["base"], recu["entrees"]["hypotheses"]
    if not isinstance(base, Mapping) or set(base) != _CLES_BASE or not isinstance(base["equipes"], list):
        raise _refus("reçu : base mal formée")
    if any(not isinstance(e, Mapping) or set(e) != _CLES_EQUIPE_BASE for e in base["equipes"]):
        raise _refus("reçu : équipe de la base mal formée")
    if not isinstance(hypotheses, Mapping) or set(hypotheses) - _CLES_HYPOTHESES:
        raise _refus("reçu : hypothèses mal formées")
    try:
        refait = appliquer(base, hypotheses)
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise _refus("reçu : entrées incalculables") from exc
    empreinte = _empreinte(recu["methode"], recu["entrees"], recu["resultat"])
    return {
        "empreinte_valide": empreinte == recu["empreinte"],
        "rejoue": True,
        "identique": refait == recu["resultat"] and empreinte == recu["empreinte"],
        "empreinte": recu["empreinte"],
    }
