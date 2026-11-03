"""Consommation DÉTERMINISTE d'une leçon promue par un département (M10-06).

Le port de lecture `opsys_lecons_actives` rend une leçon promue à son département cible. Ce module va
un cran plus loin : il reçoit cette leçon DÉJÀ filtrée par le port (ou la liste complète des leçons
actives lues par l'adaptateur), vérifie ce qui la rend applicable, puis calcule une valeur corrigée en
`Decimal`. Rien ici n'appelle un modèle, ne lit une horloge ou n'écrit quoi que ce soit.

GARDES, toutes fermées :

- la CIBLE et le GENRE doivent correspondre à ce que le consommateur déclare (`m06-material-control`
  pour l'écart de quantités lu par M3, `m05-financecore` pour l'écart de marge lu par M5) ;
- l'ÉCHANTILLON (`contenu.chantiers`) doit atteindre le MINIMUM DÉCLARÉ par la direction
  (`department.yaml/configuration/lecons_consommees/echantillon_minimum`) ; un minimum absent ou
  invalide n'applique rien et le dit (`minimum_non_declare`, `minimum_invalide`) ;
- la leçon doit être ACTIVE (`complete` ou `canari`), porter un paramètre décimal lisible, au moins une
  source et une date ISO avec fuseau : une valeur sans ces éléments ne peut pas être CITÉE, donc elle
  n'est pas appliquée ;
- deux leçons applicables au même cas ne sont JAMAIS cumulées : `plusieurs_lecons_actives` les refuse
  toutes, ce qui vaut mieux qu'un choix muet de la dernière.

La correction n'est qu'une PROPOSITION (`proposee_non_appliquee`, niveau humain N4) : le calcul de
référence (les besoins matériaux publiés par M3, la marge prévue du devis de M5) reste intact. Le
département affiche la valeur corrigée ET sa leçon ; une personne décide de l'appliquer par la voie de
calibration de son département.

Ce module ne porte aucun prix : il ne fait que multiplier une quantité par un facteur ou ajouter un
décalage en CAD à une marge DÉJÀ calculée par le code du département.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from . import lecons as _lecons

__all__ = [
    "CODE_ECHANTILLON",
    "GENRES",
    "NIVEAU_HUMAIN",
    "appliquer_lignes",
    "lecons_actives",
    "lire_minimum",
]

# Le mode de calcul de chaque genre chiffré, tel que `opsys.mnemo.lecons` l'écrit dans `contenu.mode`.
GENRES = {"ecart_materiau": "facteur", "ecart_marge": "decalage_cad"}
NIVEAU_HUMAIN = "N4"
CODE_ECHANTILLON = "REJ-LECON-MINIMUM-A-CONFIGURER"
_DECIMAL = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?$")
_MINIMUM_MIN, _MINIMUM_MAX = 1, 1000
_ETATS_ACTIFS = frozenset({"complete", "canari"})


class _Lecture:
    """Le sous-ensemble de registre dont `lecons.etat` a besoin : une lecture seule des maillons."""

    def __init__(self, maillons: Any) -> None:
        self._maillons = maillons

    def lire(self) -> list[dict[str, Any]]:
        return list(self._maillons)


def lire_minimum(reglages: Any) -> tuple[int | None, str | None]:
    """Le minimum d'échantillon DÉCLARÉ, ou `(None, raison)`. Aucune valeur par défaut n'est inventée."""
    if not isinstance(reglages, Mapping):
        return None, "minimum_non_declare"
    valeur = reglages.get("echantillon_minimum")
    if valeur is None:
        return None, "minimum_non_declare"
    if type(valeur) is not int or not _MINIMUM_MIN <= valeur <= _MINIMUM_MAX:
        return None, "minimum_invalide"
    return valeur, None


def _dec(valeur: Any) -> Decimal | None:
    if not isinstance(valeur, str) or _DECIMAL.fullmatch(valeur) is None:
        return None
    try:
        resultat = Decimal(valeur)
    except InvalidOperation:
        return None
    return resultat if resultat.is_finite() else None


def _date(valeur: Any) -> bool:
    if not isinstance(valeur, str) or not valeur:
        return False
    try:
        instant = dt.datetime.fromisoformat(valeur)
    except ValueError:
        return False
    return instant.tzinfo is not None


def _texte_decimal(valeur: Decimal) -> str:
    return format(valeur, "f")


def _decision(lecon: Mapping[str, Any]) -> dict[str, Any] | None:
    decisions = lecon.get("decisions")
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
        return None
    valides = [d for d in decisions if isinstance(d, Mapping) and d.get("etape") in _ETATS_ACTIFS]
    if not valides:
        return None
    derniere = valides[-1]
    return {
        cle: derniere.get(cle) for cle in ("etape", "par", "role", "motif", "horodatage")
    }


def _sources(lecon: Mapping[str, Any]) -> list[str] | None:
    sources = lecon.get("sources")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)) or not sources:
        return None
    if not all(isinstance(s, str) and s for s in sources):
        return None
    return list(sources)


def _verifier(
    lecon: Any, *, genre: str, cible: str, cle: str, minimum: int
) -> tuple[dict[str, Any] | None, str | None]:
    """La forme minimale d'une leçon APPLICABLE, ou la raison NOMMÉE de son refus."""
    if not isinstance(lecon, Mapping):
        return None, "lecon_invalide"
    if lecon.get("genre") != genre or lecon.get("cible") != cible or lecon.get("cle") != cle:
        return None, "cible_invalide"
    if lecon.get("etat") not in _ETATS_ACTIFS:
        return None, "etat_non_actif"
    ident = lecon.get("lecon_id")
    if not isinstance(ident, str) or not ident:
        return None, "identifiant_invalide"
    contenu = lecon.get("contenu")
    if not isinstance(contenu, Mapping) or contenu.get("mode") != GENRES[genre]:
        return None, "mode_invalide"
    parametre = _dec(contenu.get("parametre"))
    if parametre is None:
        return None, "parametre_invalide"
    if genre == "ecart_materiau" and parametre <= 0:
        return None, "parametre_invalide"
    chantiers = contenu.get("chantiers")
    if type(chantiers) is not int:
        return None, "echantillon_invalide"
    if chantiers < minimum:
        return None, "echantillon_insuffisant"
    sources = _sources(lecon)
    if sources is None:
        return None, "sources_absentes"
    if not _date(lecon.get("propose_le")):
        return None, "date_invalide"
    return {
        "lecon_id": ident,
        "genre": genre,
        "cible": cible,
        "cle": cle,
        "sources": sources,
        "date": lecon["propose_le"],
        "echantillon": chantiers,
        "parametre": _texte_decimal(parametre),
        "mode": GENRES[genre],
        "etat": lecon["etat"],
        "decision": _decision(lecon),
    }, None


def _ligne_non_corrigee(
    cle: str, base: str, raison: str, *, minimum: int, **details: Any
) -> dict[str, Any]:
    return {
        "cle": cle,
        "base": base,
        "valeur": base,
        "corrigee": False,
        "raison": raison,
        "minimum_echantillon": minimum,
        "attribution": None,
        **details,
    }


def appliquer_lignes(
    *,
    consommateur: str,
    cible: str,
    genre: str,
    entrees: Any,
    lecons_actives: Any,
    minimum_echantillon: Any,
    avertissement: str | None = None,
) -> dict[str, Any]:
    """Applique une leçon par ligne d'entrée, sous le minimum DÉCLARÉ, et ATTRIBUE chaque valeur.

    `entrees` : séquence de `{cle, base}` (base en texte décimal). `lecons_actives` : les leçons que le
    port a rendues actives pour la cible. Aucune entrée, leçon ou valeur invalide n'est interprétée :
    la ligne garde sa base et dit `raison`.
    """
    if genre not in GENRES:
        return {
            "consommateur": consommateur, "cible": cible, "genre": genre, "mode": None,
            "statut": "genre_invalide", "application": "aucune_correction", "niveau_humain": NIVEAU_HUMAIN,
            "minimum_echantillon": None, "lignes": [], "corrections": [], "sans_correction": [],
            "avertissement": "Genre de leçon inconnu : aucun calcul.",
        }
    mode = GENRES[genre]
    sortie: dict[str, Any] = {
        "consommateur": consommateur,
        "cible": cible,
        "genre": genre,
        "mode": mode,
        "minimum_echantillon": minimum_echantillon,
        "application": "aucune_correction",
        "niveau_humain": NIVEAU_HUMAIN,
        "lignes": [],
        "corrections": [],
        "sans_correction": [],
        "avertissement": avertissement or (
            "Une correction proposée n'est jamais appliquée par ce calcul : elle cite sa leçon et attend "
            "une décision humaine de niveau N4."
        ),
    }
    if type(minimum_echantillon) is not int or not _MINIMUM_MIN <= minimum_echantillon <= _MINIMUM_MAX:
        if minimum_echantillon is None:
            sortie["statut"] = "minimum_non_declare"
            sortie["avertissement"] = (
                "Aucune correction : l'échantillon minimum n'est pas déclaré. Déclarer "
                "configuration.lecons_consommees.echantillon_minimum dans department.yaml."
            )
        else:
            sortie["statut"] = "minimum_invalide"
            sortie["avertissement"] = (
                "Aucune correction : l'échantillon minimum doit être un entier de "
                f"{_MINIMUM_MIN} à {_MINIMUM_MAX} chantiers distincts."
            )
        if isinstance(entrees, Sequence) and not isinstance(entrees, (str, bytes)):
            for entree in entrees:
                cle = entree.get("cle") if isinstance(entree, Mapping) else "?"
                base = entree.get("base") if isinstance(entree, Mapping) else "0"
                ligne = _ligne_non_corrigee(
                    str(cle), str(base), sortie["statut"], minimum=minimum_echantillon
                )
                sortie["lignes"].append(ligne)
                sortie["sans_correction"].append({k: ligne[k] for k in ("cle", "raison")})
        return sortie
    if not isinstance(entrees, Sequence) or isinstance(entrees, (str, bytes)):
        sortie["statut"] = "entree_invalide"
        sortie["avertissement"] = "Aucune correction : les entrées doivent être une séquence de {cle, base}."
        return sortie
    if not isinstance(lecons_actives, Sequence) or isinstance(lecons_actives, (str, bytes)):
        lecons_actives = []

    for entree in entrees:
        if not isinstance(entree, Mapping):
            ligne = _ligne_non_corrigee("?", "0", "entree_invalide", minimum=minimum_echantillon)
            sortie["lignes"].append(ligne)
            sortie["sans_correction"].append({k: ligne[k] for k in ("cle", "raison")})
            continue
        cle = entree.get("cle")
        if not isinstance(cle, str) or not cle:
            ligne = _ligne_non_corrigee("?", "0", "cle_invalide", minimum=minimum_echantillon)
            sortie["lignes"].append(ligne)
            sortie["sans_correction"].append({k: ligne[k] for k in ("cle", "raison")})
            continue
        base = _dec(entree.get("base"))
        if base is None or (genre == "ecart_materiau" and base <= 0):
            ligne = _ligne_non_corrigee(cle, str(entree.get("base")), "base_invalide", minimum=minimum_echantillon)
            sortie["lignes"].append(ligne)
            sortie["sans_correction"].append({k: ligne[k] for k in ("cle", "raison")})
            continue
        base_texte = _texte_decimal(base)
        candidates = [
            lecon for lecon in lecons_actives
            if isinstance(lecon, Mapping)
            and lecon.get("genre") == genre
            and lecon.get("cible") == cible
            and lecon.get("cle") == cle
        ]
        if not candidates:
            ligne = _ligne_non_corrigee(cle, base_texte, "aucune_lecon_active", minimum=minimum_echantillon)
            sortie["lignes"].append(ligne)
            sortie["sans_correction"].append({k: ligne[k] for k in ("cle", "raison")})
            continue
        valides: list[dict[str, Any]] = []
        raisons: list[dict[str, Any]] = []
        for candidate in candidates:
            attribution, raison = _verifier(candidate, genre=genre, cible=cible, cle=cle, minimum=minimum_echantillon)
            if attribution is None:
                raisons.append({
                    "lecon_id": candidate.get("lecon_id"),
                    "raison": raison,
                    "echantillon": (candidate.get("contenu") or {}).get("chantiers")
                    if isinstance(candidate.get("contenu"), Mapping) else None,
                    "minimum_echantillon": minimum_echantillon,
                })
            else:
                valides.append(attribution)
        if len(valides) > 1:
            ligne = _ligne_non_corrigee(
                cle, base_texte, "plusieurs_lecons_actives", minimum=minimum_echantillon,
                lecons=[a["lecon_id"] for a in valides],
            )
            sortie["lignes"].append(ligne)
            sortie["sans_correction"].append({k: ligne[k] for k in ("cle", "raison")})
            continue
        if not valides:
            premiere = raisons[0] if raisons else {"raison": "lecon_inapplicable"}
            detail: dict[str, Any] = {"lecons_vues": raisons}
            if premiere["raison"] == "echantillon_insuffisant":
                detail.update(
                    echantillon=premiere.get("echantillon"),
                    minimum_echantillon=minimum_echantillon,
                )
            ligne = _ligne_non_corrigee(
                cle, base_texte, str(premiere["raison"]), minimum=minimum_echantillon, **detail
            )
            sortie["lignes"].append(ligne)
            sortie["sans_correction"].append({k: ligne[k] for k in ("cle", "raison")})
            continue
        attribution = valides[0]
        parametre = Decimal(attribution["parametre"])
        valeur = base * parametre if genre == "ecart_materiau" else base + parametre
        ligne = {
            "cle": cle,
            "base": base_texte,
            "valeur": _texte_decimal(valeur),
            "corrigee": True,
            "raison": None,
            "minimum_echantillon": minimum_echantillon,
            "attribution": attribution,
            "application": "proposee_non_appliquee",
            "niveau_humain": NIVEAU_HUMAIN,
        }
        sortie["lignes"].append(ligne)
        sortie["corrections"].append(
            {"cle": cle, "avant": base_texte, "apres": ligne["valeur"], "attribution": attribution}
        )
    if sortie["corrections"]:
        sortie["statut"] = "correction_proposee"
        sortie["application"] = "proposee_non_appliquee"
    else:
        raisons = sorted({str(ligne["raison"]) for ligne in sortie["lignes"]})
        if len(raisons) == 1 and raisons[0] in {"aucune_lecon_active", "plusieurs_lecons_actives"}:
            sortie["statut"] = raisons[0]
        elif len(raisons) == 1 and raisons[0] in {
            "cible_invalide", "etat_non_actif", "identifiant_invalide", "mode_invalide",
            "parametre_invalide", "echantillon_invalide", "sources_absentes", "date_invalide",
        }:
            sortie["statut"] = "lecon_inapplicable"
        else:
            sortie["statut"] = "aucune_correction"
    return sortie


def lecons_actives(cible: str, cle_application: str) -> dict[str, Any]:
    """Les leçons que le port `opsys_lecons_actives` rend actives pour `cible` et ce cas.

    Lit le même registre append-only que l'outil commun de M10 ; n'écrit rien et ne rend que ce que le
    port a déjà filtré par la cible et le canari.
    """
    if not isinstance(cible, str) or not cible:
        raise ValueError("cible obligatoire")
    if not isinstance(cle_application, str) or not cle_application:
        raise ValueError("cle_application obligatoire")
    from .. import stockage

    return _lecons.appliquer_a(
        _Lecture(stockage.maillons("m10-memoire", "lecons")), cible, cle_application
    )
