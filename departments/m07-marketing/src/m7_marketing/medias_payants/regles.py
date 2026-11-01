"""Règles de plafond et d'arrêt automatique PRÉPARÉES — jamais exécutées.

Une règle dit : « si ceci arrive sur les chiffres lus chez la plateforme, une PAUSE est à proposer à la direction ».
Elle est
écrite avec le plan de campagne, avant tout lancement, et elle est ÉVALUÉE sur des faits constatés
(`signaux_marketing`). Elle
ne fait jamais autre chose que rendre un constat :

- l'unique action d'une règle est `proposer_pause` ; il n'existe aucune autre valeur, aucune fonction de ce paquet
n'écrit
  chez une plateforme, aucun connecteur de lecture n'expose un point d'accès d'écriture (`signaux/base.py`, liste
  blanche) ;
- tout constat porte `executee: false` : la pause (ou la baisse de budget) est un geste de la direction, dans la
plateforme,
  ou une décision N4 si un jour un exécuteur existe — il n'existe pas ;
- les plafonds du plan (quotidien et total) sont TOUJOURS présents : ils sont déduits du budget par le code, le client
ne peut pas
  les retirer, et le budget lui-même est borné par les plafonds durs du sas social
  (`sas_social.politique.PolitiqueSas`) ;
- une règle qui n'a pas de quoi être jugée (jours manquants, conversions inconnues, échantillon trop mince) rend
`declenchee:
  null` et dit POURQUOI : une absence n'est jamais un zéro, un doute n'est jamais un « tout va bien ».

Montants en CENTS entiers (CAD). Les conversions peuvent être fractionnaires (modélisées par la plateforme) : elles
restent des
`Decimal` exacts. Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import statistics
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

ACTION = "proposer_pause"
STATUT_PREPAREE = "PREPAREE_NON_EXECUTEE"
TYPES = ("plafond_quotidien", "plafond_total", "cpa_max", "depense_sans_conversion", "saut_depense")
# Type de règle -> code de l'anomalie qu'il produit (catalogue `m7.anomalie_depense_detectee`).
CODE_DEP = {
    "plafond_quotidien": "DEP-01",
    "depense_sans_conversion": "DEP-02",
    "saut_depense": "DEP-03",
    "cpa_max": "DEP-06",
    "plafond_total": "DEP-07",
}
TOLERANCE_PLAFOND_QUOTIDIEN_PCT = 20
JOURS_MEDIANE = 7
REJ_REGLE = "REJ-PLAN-MEDIA-REGLE"

_CHAMPS_REGLE = {
    "plafond_quotidien": {"type", "tolerance_pct"},
    "plafond_total": {"type"},
    "cpa_max": {"type", "seuil_cents", "conversions_min"},
    "depense_sans_conversion": {"type", "seuil_cents", "fenetre_jours"},
    "saut_depense": {"type", "ratio_pct", "minimum_cents"},
}


@dataclasses.dataclass(frozen=True)
class Jour:
    """Un jour de dépense lu chez la plateforme. `conversions` None : la plateforme ne l'a pas dit (inconnu, pas
    zéro)."""

    jour: date
    cout_cents: int
    conversions: Decimal | None = None


def _refus(chemin: str, detail: str) -> dict[str, str]:
    return {"code": REJ_REGLE, "chemin": chemin, "detail": detail}


def _entier(valeur: Any, minimum: int, maximum: int) -> bool:
    return type(valeur) is int and minimum <= valeur <= maximum


def regles_obligatoires(budget: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Les plafonds déduits du budget par le code : ils ne se retirent pas."""
    return [
        {
            "regle_id": "plafond-quotidien",
            "type": "plafond_quotidien",
            "seuil_cents": budget["plafond_quotidien_cents"],
            "tolerance_pct": TOLERANCE_PLAFOND_QUOTIDIEN_PCT,
            "action": ACTION,
            "statut": STATUT_PREPAREE,
            "executee_par_opsys": False,
            "obligatoire": True,
        },
        {
            "regle_id": "plafond-total",
            "type": "plafond_total",
            "seuil_cents": budget["montant_total_cents"],
            "action": ACTION,
            "statut": STATUT_PREPAREE,
            "executee_par_opsys": False,
            "obligatoire": True,
        },
    ]


def normaliser_regles(
    brutes: Any, budget: Mapping[str, Any]
) -> tuple[list[dict[str, Any]] | None, list[dict[str, str]]]:
    """Les règles du plan : les deux plafonds obligatoires, plus au plus 6 règles supplémentaires déclarées par le
    client.
    Une règle inconnue, un champ inconnu, un seuil hors bornes ou une action autre que `proposer_pause` est refusé."""
    if brutes is None:
        brutes = []
    if not isinstance(brutes, Sequence) or isinstance(brutes, (str, bytes)) or len(brutes) > 6:
        return None, [_refus("$.regles", "liste de 6 règles supplémentaires au plus attendue")]
    refus: list[dict[str, str]] = []
    regles = regles_obligatoires(budget)
    vus = {r["type"] for r in regles}
    for i, r in enumerate(brutes):
        chemin = f"$.regles[{i}]"
        if not isinstance(r, Mapping) or r.get("type") not in TYPES:
            refus.append(_refus(chemin, f"règle attendue : objet avec type parmi {list(TYPES)}"))
            continue
        type_ = r["type"]
        if type_ in ("plafond_quotidien", "plafond_total"):
            refus.append(_refus(chemin, f"{type_} est déduit du budget par le code : il ne se déclare pas"))
            continue
        if type_ in vus:
            refus.append(_refus(chemin, f"une seule règle {type_} par plan"))
            continue
        permis = _CHAMPS_REGLE[type_] | {"action"}
        if set(r) - permis or (_CHAMPS_REGLE[type_] - {"type"}) - set(r):
            refus.append(
                _refus(chemin, f"champs de {type_} : {sorted(_CHAMPS_REGLE[type_] - {'type'})}, action facultative")
            )
            continue
        if r.get("action", ACTION) != ACTION:
            refus.append(
                _refus(
                    chemin + ".action",
                    f"la seule action possible est « {ACTION} » (une proposition, jamais une exécution)",
                )
            )
            continue
        bornes = {
            "seuil_cents": (1, 100_000_000),
            "conversions_min": (1, 1000),
            "fenetre_jours": (2, 30),
            "ratio_pct": (150, 2000),
            "minimum_cents": (0, 100_000_000),
        }
        invalides = [c for c, (a, b) in bornes.items() if c in r and not _entier(r[c], a, b)]
        if invalides:
            refus.append(_refus(chemin, f"entiers dans les bornes attendus : {invalides}"))
            continue
        vus.add(type_)
        regles.append(
            {
                "regle_id": type_.replace("_", "-"),
                **{k: r[k] for k in sorted(_CHAMPS_REGLE[type_]) if k != "type"},
                "type": type_,
                "action": ACTION,
                "statut": STATUT_PREPAREE,
                "executee_par_opsys": False,
                "obligatoire": False,
            }
        )
    return (None, refus) if refus else (regles, [])


def trous(serie: Sequence[Jour], debut: date, fin: date) -> list[date]:
    """Les jours de [debut, fin] SANS fait : leur dépense est inconnue (pas nulle)."""
    presents = {j.jour for j in serie}
    manquants, courant = [], debut
    while courant <= fin:
        if courant not in presents:
            manquants.append(courant)
        courant += timedelta(days=1)
    return manquants


def _constat(
    regle: Mapping[str, Any],
    declenchee: bool | None,
    valeur: Decimal | int | None,
    seuil: Any,
    jours: Sequence[date],
    raison: str,
    unite: str,
) -> dict[str, Any]:
    return {
        "regle_id": regle["regle_id"],
        "type": regle["type"],
        "code_dep": CODE_DEP[regle["type"]],
        "declenchee": declenchee,
        "valeur": None if valeur is None else format(Decimal(valeur), "f"),
        "seuil": None if seuil is None else format(Decimal(seuil), "f"),
        "unite": unite,
        "jours": [j.isoformat() for j in jours],
        "raison": raison,
        "action_preparee": ACTION if declenchee else None,
        "executee": False,
    }


def evaluer(
    regles: Sequence[Mapping[str, Any]], serie: Sequence[Jour], *, debut: date, fin: date
) -> list[dict[str, Any]]:
    """Évalue chaque règle sur la série des jours [debut, fin]. Aucun effet. Les jours manquants sont des TROUS."""
    ordonnee = sorted(serie, key=lambda j: j.jour)
    dans = [j for j in ordonnee if debut <= j.jour <= fin]
    manquants = trous(dans, debut, fin)
    constats = []
    for regle in regles:
        constats.append(_EVALUATEURS[regle["type"]](regle, dans, manquants, fin))
    return constats


def _plafond_quotidien(regle, serie, manquants, fin):
    seuil = regle["seuil_cents"] * (100 + regle["tolerance_pct"]) // 100
    if not serie:
        return _constat(regle, None, None, seuil, [], "aucun jour lu : rien à évaluer", "CAD")
    depasses = [j for j in serie if j.cout_cents > seuil]
    pire = max(j.cout_cents for j in serie)
    if depasses:
        return _constat(
            regle,
            True,
            Decimal(pire) / 100,
            Decimal(seuil) / 100,
            [j.jour for j in depasses],
            f"dépense quotidienne au-delà du plafond ({regle['seuil_cents']} cents) plus {regle['tolerance_pct']} %",
            "CAD",
        )
    note = "" if not manquants else f" ; {len(manquants)} jour(s) sans donnée (dépense inconnue, non évaluée)"
    return _constat(
        regle, False, Decimal(pire) / 100, Decimal(seuil) / 100, [], "aucun jour lu ne dépasse le plafond" + note, "CAD"
    )


def _plafond_total(regle, serie, manquants, fin):
    total = sum(j.cout_cents for j in serie)
    seuil = regle["seuil_cents"]
    if total > seuil:
        return _constat(
            regle,
            True,
            Decimal(total) / 100,
            Decimal(seuil) / 100,
            [j.jour for j in serie if j.cout_cents],
            "la dépense lue dépasse déjà le budget total du plan (même avec des jours manquants)",
            "CAD",
        )
    if manquants:
        return _constat(
            regle,
            None,
            Decimal(total) / 100,
            Decimal(seuil) / 100,
            manquants,
            f"{len(manquants)} jour(s) sans donnée : la dépense lue est un minimum, le dépassement ne peut pas "
            "être exclu",
            "CAD",
        )
    return _constat(
        regle, False, Decimal(total) / 100, Decimal(seuil) / 100, [], "dépense lue sous le budget total", "CAD"
    )


def _cpa_max(regle, serie, manquants, fin):
    seuil = Decimal(regle["seuil_cents"]) / 100
    if not serie or manquants or any(j.conversions is None for j in serie):
        return _constat(
            regle, None, None, seuil, manquants, "conversions inconnues ou jours manquants : CPA non évaluable", "CAD"
        )
    conversions = sum((j.conversions for j in serie), Decimal(0))
    if conversions < regle["conversions_min"]:
        return _constat(
            regle,
            None,
            conversions,
            seuil,
            [],
            f"{conversions} conversion(s) : moins de {regle['conversions_min']}, "
            "échantillon trop mince pour juger un coût par conversion",
            "conversions",
        )
    cpa = (Decimal(sum(j.cout_cents for j in serie)) / 100 / conversions).quantize(Decimal("0.01"))
    if cpa > seuil:
        return _constat(
            regle, True, cpa, seuil, [j.jour for j in serie], "coût par conversion au-dessus du maximum déclaré", "CAD"
        )
    return _constat(regle, False, cpa, seuil, [], "coût par conversion sous le maximum déclaré", "CAD")


def _sans_conversion(regle, serie, manquants, fin):
    fenetre = regle["fenetre_jours"]
    debut_f = fin - timedelta(days=fenetre - 1)
    derniers = [j for j in serie if debut_f <= j.jour <= fin]
    seuil = Decimal(regle["seuil_cents"]) / 100
    if len(derniers) < fenetre or any(j.conversions is None for j in derniers):
        return _constat(
            regle,
            None,
            None,
            seuil,
            [],
            f"les {fenetre} derniers jours ne sont pas tous lus avec leurs conversions : non évaluable",
            "CAD",
        )
    depense = sum(j.cout_cents for j in derniers)
    conversions = sum((j.conversions for j in derniers), Decimal(0))
    if conversions == 0 and depense >= regle["seuil_cents"]:
        return _constat(
            regle,
            True,
            Decimal(depense) / 100,
            seuil,
            [j.jour for j in derniers],
            f"dépense sans aucune conversion sur {fenetre} jours",
            "CAD",
        )
    return _constat(
        regle,
        False,
        Decimal(depense) / 100,
        seuil,
        [],
        "dépense sans conversion sous le seuil, ou conversions présentes",
        "CAD",
    )


def _saut(regle, serie, manquants, fin):
    ratio, minimum = regle["ratio_pct"], regle["minimum_cents"]
    for index, jour in enumerate(serie):
        precedents = [j for j in serie[:index] if jour.jour - timedelta(days=JOURS_MEDIANE) <= j.jour < jour.jour]
        if len(precedents) < JOURS_MEDIANE:
            continue
        mediane = int(statistics.median(j.cout_cents for j in precedents))
        if jour.cout_cents * 100 > mediane * ratio and jour.cout_cents - mediane >= minimum:
            return _constat(
                regle,
                True,
                Decimal(jour.cout_cents) / 100,
                Decimal(mediane * ratio // 100) / 100,
                [jour.jour],
                f"dépense du jour supérieure à {ratio} % de la médiane des {JOURS_MEDIANE} jours précédents "
                f"({mediane} cents)",
                "CAD",
            )
    if len(serie) <= JOURS_MEDIANE:
        return _constat(
            regle,
            None,
            None,
            None,
            [],
            f"moins de {JOURS_MEDIANE + 1} jours lus : la médiane précédente n'existe pas",
            "CAD",
        )
    note = (
        ""
        if not manquants
        else (
            f" ; {len(manquants)} jour(s) sans donnée : les sauts autour de ces jours sont non jugés "
            "(médiane incomplète)"
        )
    )
    return _constat(
        regle, False, None, None, [], "aucun saut de dépense contre la médiane des jours précédents" + note, "CAD"
    )


_EVALUATEURS = {
    "plafond_quotidien": _plafond_quotidien,
    "plafond_total": _plafond_total,
    "cpa_max": _cpa_max,
    "depense_sans_conversion": _sans_conversion,
    "saut_depense": _saut,
}

__all__ = [
    "ACTION",
    "CODE_DEP",
    "Jour",
    "STATUT_PREPAREE",
    "TYPES",
    "evaluer",
    "normaliser_regles",
    "regles_obligatoires",
    "trous",
]
