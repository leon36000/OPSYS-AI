"""Rapport de performance publicitaire HONNÊTE : ce que les chiffres lus chez la plateforme permettent de dire, et
rien de plus.

Pour chaque campagne (et pour l'ensemble) sur la période demandée :
- la COUVERTURE : combien de jours ont été lus, lesquels manquent (un jour sans donnée n'est pas un jour à zéro) ;
- les totaux de ce qui a été lu (dépense, impressions, clics, conversions), jamais extrapolés ;
- le taux de clic (clics sur impressions) et le taux de conversion (conversions sur clics) avec leur intervalle de
Wilson et
  l'effectif sur lequel ils reposent ; le coût par clic ; le coût par conversion avec un intervalle déduit de celui du
  taux
  de conversion (borne haute « non bornée » quand la borne basse du taux est zéro) ;
- un verdict de SUFFISANCE : sous 100 clics ou 5 conversions, le rapport le dit et ne conclut rien (seuils de prudence
internes,
  pas des faits sur les plateformes) ;
- une comparaison entre campagnes SANS classement : des campagnes dont les intervalles de coût par conversion se
chevauchent
  sont dans le même niveau (« indistinguables »).

Ce rapport DÉCRIT. Il n'établit aucune cause : sans test marche-arrêt ou géographique préenregistré
(`mesure/experiences.py`),
rien de ce qu'il montre n'est un effet de la publicité (`causalite: non_etablie`). Les conversions de plateforme
peuvent être
modélisées (fractionnaires) : alors l'intervalle de conversion n'est pas calculé et le dit.

Montants en cents entiers, conversions exactes en `Decimal`, sorties en texte décimal. Module pur.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..mesure import statistiques as st
from .regles import trous

MIN_CLICS = 100
MIN_CONVERSIONS = 5
CAUSALITE = (
    "Rapport descriptif : il compte ce que la plateforme déclare, il n'explique pas pourquoi. Sans test marche-arrêt "
    "ou géographique préenregistré, aucun effet causal de la publicité n'est affirmé."
)


@dataclasses.dataclass(frozen=True)
class JourPerf:
    jour: date
    cout_cents: int
    impressions: int | None = None
    clics: int | None = None
    conversions: Decimal | None = None


def _total_ou_none(valeurs):
    """Le total, ou None si une valeur est inconnue OU si aucun jour n'a été lu (un total de zéro jour n'est pas
    zéro)."""
    return None if not valeurs or any(v is None for v in valeurs) else sum(valeurs)


def _argent(valeur: Decimal) -> str:
    """Un montant en dollars canadiens, deux décimales toujours (« 30.00 », jamais « 30 »)."""
    return format(valeur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _ratio(num: Decimal | int, den: Decimal | int, quantum: str = "0.000001") -> str | None:
    if not den:
        return None
    return st.texte(Decimal(num) / Decimal(den), Decimal(quantum))


def _intervalle(k: int, n: int, niveau: Decimal) -> dict[str, str] | None:
    if n < 1 or not 0 <= k <= n:
        return None
    bas, haut = st.wilson(k, n, niveau)
    return {"bas": st.texte(bas), "haut": st.texte(haut)}


def _campagne(ref: str, jours: Sequence[JourPerf], debut: date, fin: date, niveau: Decimal) -> dict[str, Any]:
    dans = sorted((j for j in jours if debut <= j.jour <= fin), key=lambda j: j.jour)
    manquants = trous(dans, debut, fin)  # type: ignore[arg-type]
    cout = sum(j.cout_cents for j in dans)
    impressions = _total_ou_none([j.impressions for j in dans])
    clics = _total_ou_none([j.clics for j in dans])
    conversions = _total_ou_none([j.conversions for j in dans])
    notes: list[str] = []
    if manquants:
        notes.append(f"{len(manquants)} jour(s) sans donnée : les totaux sont ceux des jours lus seulement")
    for nom, valeur in (("impressions", impressions), ("clics", clics), ("conversions", conversions)):
        if valeur is None and dans:
            notes.append(f"{nom} non déclarées par la plateforme pour au moins un jour : total inconnu")
    ctr = {"valeur": None, "intervalle": None, "n": None}
    if impressions and clics is not None and clics <= impressions:
        ctr = {
            "valeur": _ratio(clics, impressions),
            "intervalle": _intervalle(clics, impressions, niveau),
            "n": impressions,
        }
    taux = {"valeur": None, "intervalle": None, "n": None}
    cpa = {"valeur": None, "intervalle": None, "n": None}
    if clics and conversions is not None and clics > 0:
        entier = conversions == conversions.to_integral_value()
        taux = {"valeur": _ratio(conversions, clics), "intervalle": None, "n": clics}
        if entier and conversions <= clics:
            taux["intervalle"] = _intervalle(int(conversions), clics, niveau)
        else:
            notes.append("conversions fractionnaires (modélisées) : intervalle du taux de conversion non calculé")
        if conversions > 0:
            valeur = _argent(Decimal(cout) / 100 / conversions)
            cpa = {"valeur": valeur, "intervalle": None, "n": int(conversions) if entier else None}
            if taux["intervalle"] is not None and cout > 0:
                p_bas, p_haut = Decimal(taux["intervalle"]["bas"]), Decimal(taux["intervalle"]["haut"])
                bas = Decimal(cout) / 100 / (Decimal(clics) * p_haut) if p_haut > 0 else None
                haut = Decimal(cout) / 100 / (Decimal(clics) * p_bas) if p_bas > 0 else None
                cpa["intervalle"] = {
                    "bas": None if bas is None else _argent(bas),
                    "haut": None if haut is None else _argent(haut),
                }
    suffisant = bool(
        clics is not None and conversions is not None and clics >= MIN_CLICS and conversions >= MIN_CONVERSIONS
    )
    if not suffisant:
        notes.append(
            f"échantillon insuffisant (moins de {MIN_CLICS} clics ou de {MIN_CONVERSIONS} conversions) : ne pas "
            "conclure, ni comparer, ni changer de budget sur ces chiffres"
        )
    return {
        "campagne_ref": ref,
        "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
        "couverture": {
            "jours_attendus": (fin - debut).days + 1,
            "jours_lus": len(dans),
            "jours_manquants": [m.isoformat() for m in manquants],
        },
        "totaux": {
            "cout_cad": _argent(Decimal(cout) / 100) if dans else None,
            "impressions": impressions,
            "clics": clics,
            "conversions": None if conversions is None else st.texte(conversions),
        },
        "taux_de_clic": ctr,
        "cout_par_clic_cad": _argent(Decimal(cout) / 100 / clics) if clics else None,
        "taux_de_conversion": taux,
        "cout_par_conversion_cad": cpa,
        "suffisant": suffisant,
        "notes": notes,
    }


def _niveaux(campagnes: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """Regroupe les campagnes SUFFISANTES dont les intervalles de coût par conversion se chevauchent. Pas de
    classement."""
    intervalles = []
    for c in campagnes:
        i = c["cout_par_conversion_cad"]["intervalle"]
        if c["suffisant"] and i is not None and i["bas"] is not None:
            haut = Decimal(i["haut"]) if i["haut"] is not None else Decimal("Infinity")
            intervalles.append((c["campagne_ref"], Decimal(i["bas"]), haut))
    groupes: list[list[tuple[str, Decimal, Decimal]]] = []
    for item in sorted(intervalles, key=lambda t: (t[1], t[0])):
        if groupes and item[1] <= max(g[2] for g in groupes[-1]):
            groupes[-1].append(item)
        else:
            groupes.append([item])
    return [sorted(x[0] for x in g) for g in groupes]


def construire(
    *,
    canal: str,
    campagnes: Mapping[str, Sequence[JourPerf]],
    debut: date,
    fin: date,
    niveau: Decimal = Decimal("0.95"),
    fictifs_presents: bool = False,
) -> dict[str, Any]:
    if debut > fin or (fin - debut).days > 366:
        raise ValueError("période inversée ou de plus de 367 jours")
    detail = [_campagne(ref, jours, debut, fin, niveau) for ref, jours in sorted(campagnes.items())]
    toutes = [j for jours in campagnes.values() for j in jours if debut <= j.jour <= fin]
    # L'ensemble n'additionne que ce qui est chiffré pour chaque campagne : il réutilise le même calcul sur les jours-
    # campagnes.
    par_jour: dict[date, list[JourPerf]] = {}
    for j in toutes:
        par_jour.setdefault(j.jour, []).append(j)
    agreges = []
    for jour, lignes in sorted(par_jour.items()):
        agreges.append(
            JourPerf(
                jour,
                sum(x.cout_cents for x in lignes),
                _total_ou_none([x.impressions for x in lignes]),
                _total_ou_none([x.clics for x in lignes]),
                _total_ou_none([x.conversions for x in lignes]),
            )
        )
    ensemble = _campagne("ensemble", agreges, debut, fin, niveau)
    niveaux = _niveaux(detail)
    return {
        "type": "RAPPORT_PERFORMANCE_PUBLICITAIRE",
        "canal": canal,
        "niveau_confiance": st.texte(niveau, Decimal("0.01")),
        "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
        "campagnes": detail,
        "ensemble": ensemble,
        "comparaison": {
            "niveaux_indistinguables": niveaux,
            "classement": None,
            "lecture": "Aucun classement : des campagnes dans le même niveau ne se distinguent pas avec ces "
            "données ; une campagne seule dans son niveau se distingue seulement au sens statistique "
            "descriptif, pas causal.",
        },
        "causalite": "non_etablie",
        "avertissement": CAUSALITE,
        "fictifs_presents": fictifs_presents,
        "seuils": {
            "clics_min": MIN_CLICS,
            "conversions_min": MIN_CONVERSIONS,
            "nature": "prudence interne, pas un fait sur les plateformes",
        },
    }


__all__ = ["CAUSALITE", "JourPerf", "MIN_CLICS", "MIN_CONVERSIONS", "construire"]
