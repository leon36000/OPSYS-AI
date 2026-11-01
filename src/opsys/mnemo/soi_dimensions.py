"""Les dimensions du modèle de soi : ce qu'on peut dire de l'entreprise, sous quelle forme fermée, et qui peut le lire.

Une dimension fixe : sa clé (ce que l'énoncé décrit), la forme de sa valeur (validée, bornée, sans donnée personnelle),
la phrase française que le CODE en tire (aucun modèle ne rédige un énoncé), si elle est STRUCTURANTE (elle oriente des
décisions : sa dérive est une alerte), son niveau de confidentialité et les départements qui la lisent.

Quatre dimensions s'alimentent seules d'un port de lecture existant (`soi_sources`) : services, zones, équipes et
capacité (profil d'entreprise de l'onboarding), vocabulaire (pack sectoriel), marges observées (faits analytiques de
M8 mémorisés par M10), saisonnalité (travaux terminés mémorisés par M10). Les autres (clients types, préférences et
règles de la direction, ton de marque) n'ont PAS de source automatique : elles viennent d'une déclaration de la
direction ou d'une proposition sourcée ; sans cela elles restent « inconnues », jamais inventées.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from . import codes, vie_privee
from .codes import ErreurMnemo

DEPARTEMENTS_FINANCIERS = frozenset(
    {"m03-estimation", "m05-financecore", "m08-analytics", "m09-strategic-intelligence", "m10-memoire"}
)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_METRIC = re.compile(r"^m8_[a-z0-9_]{1,76}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^-?[0-9]{1,14}(\.[0-9]{1,8})?$")
_ID_EQUIPE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MOIS = tuple(f"{m:02d}" for m in range(1, 13))
TOLERANCE_RELATIVE_MARGE = Decimal("0.10")


def _entier(valeur: object, champ: str, minimum: int, maximum: int) -> int:
    if type(valeur) is not int or not minimum <= valeur <= maximum:
        raise ErreurMnemo(codes.VALEUR_INVALIDE, f"{champ} : entier de {minimum} à {maximum}")
    return valeur


def _decimal(valeur: object, champ: str) -> str:
    if not isinstance(valeur, str) or not _DECIMAL.fullmatch(valeur):
        raise ErreurMnemo(
            codes.VALEUR_INVALIDE, f"{champ} : nombre décimal en texte (ex. « 12.50 »), jamais un flottant"
        )
    return valeur


def _objet(valeur: object, champ: str, cles: set[str]) -> Mapping[str, Any]:
    if not isinstance(valeur, Mapping) or set(valeur) != cles:
        raise ErreurMnemo(codes.VALEUR_INVALIDE, f"{champ} : objet aux clés exactes {sorted(cles)}")
    return valeur


def _slug(cle: object, champ: str = "cle") -> str:
    if not isinstance(cle, str) or not _SLUG.fullmatch(cle):
        raise ErreurMnemo(codes.VALEUR_INVALIDE, f"{champ} : identifiant en minuscules (lettres, chiffres, . _ -)")
    return cle


# -- validateurs : (cle, valeur) -> (cle, valeur normalisée)
# ------------------------------------------------------------
def _services(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    v = _objet(valeur, "valeur", {"libelle"})
    return _slug(cle), {"libelle": vie_privee.texte_libre(v["libelle"], "libelle", maximum=120)}


def _zones(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    if cle != "zone_desservie":
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "zones : la clé est « zone_desservie »")
    v = _objet(valeur, "valeur", {"villes"})
    villes = v["villes"]
    if not isinstance(villes, list) or not 1 <= len(villes) <= 300:
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "villes : 1 à 300 villes")
    propres = sorted({vie_privee.texte_libre(x, "ville", maximum=80) for x in villes})
    return "zone_desservie", {"villes": propres}


def _equipes(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    if not isinstance(cle, str) or not _ID_EQUIPE.fullmatch(cle):
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "equipes : la clé est l'identifiant de l'équipe")
    v = _objet(valeur, "valeur", {"competences", "effectif_planifie"})
    comp = v["competences"]
    if not isinstance(comp, list) or len(comp) > 30:
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "competences : liste de 30 codes au plus")
    effectif = v["effectif_planifie"]
    return cle, {
        "competences": sorted({_slug(c, "competence") for c in comp}),
        "effectif_planifie": None if effectif is None else _entier(effectif, "effectif_planifie", 1, 50),
    }


def _capacite(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    if not isinstance(cle, str) or not (cle == "entreprise" or _ID_EQUIPE.fullmatch(cle)):
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "capacite : la clé est « entreprise » ou l'identifiant d'une équipe")
    v = _objet(valeur, "valeur", {"minutes_semaine_type", "heures_par_semaine", "effectif_planifie"})
    minutes, heures, effectif = v["minutes_semaine_type"], v["heures_par_semaine"], v["effectif_planifie"]
    if minutes is None:
        if heures is not None:
            raise ErreurMnemo(
                codes.VALEUR_INVALIDE, "heures_par_semaine sans minutes : une capacité inconnue reste inconnue"
            )
    else:
        minutes = _entier(minutes, "minutes_semaine_type", 0, 7 * 24 * 60)
        attendu = str((Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01")))
        if heures != attendu:
            raise ErreurMnemo(
                codes.VALEUR_INVALIDE, f"heures_par_semaine doit être calculée des minutes par le code ({attendu})"
            )
    return cle, {
        "minutes_semaine_type": minutes,
        "heures_par_semaine": heures,
        "effectif_planifie": None if effectif is None else _entier(effectif, "effectif_planifie", 1, 50),
    }


def _clients_types(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    v = _objet(valeur, "valeur", {"description", "part_pct"})
    part = v["part_pct"]
    if part is not None:
        part = _decimal(part, "part_pct")
        if not Decimal("0") <= Decimal(part) <= Decimal("100"):
            raise ErreurMnemo(codes.VALEUR_INVALIDE, "part_pct : entre 0 et 100")
    return _slug(cle), {
        "description": vie_privee.texte_propre(v["description"], "description", maximum=200),
        "part_pct": part,
    }


def _marges(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    if not isinstance(cle, str) or not _METRIC.fullmatch(cle):
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "marges_observees : la clé est l'identifiant d'une mesure M8 (m8_…)")
    v = _objet(valeur, "valeur", {"valeur", "unite", "version_definition"})
    if not isinstance(v["version_definition"], str) or not _SHA.fullmatch(v["version_definition"]):
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "version_definition : empreinte sha256")
    return cle, {
        "valeur": _decimal(v["valeur"], "valeur"),
        "unite": vie_privee.texte_libre(v["unite"], "unite", maximum=32),
        "version_definition": v["version_definition"],
    }


def _saisonnalite(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    if cle != "charge_mensuelle":
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "saisonnalite : la clé est « charge_mensuelle »")
    v = _objet(valeur, "valeur", {"par_mois", "observations"})
    par_mois = v["par_mois"]
    if not isinstance(par_mois, Mapping) or set(par_mois) != set(_MOIS):
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "par_mois : les douze mois « 01 » à « 12 »")
    comptes = {m: _entier(par_mois[m], f"par_mois.{m}", 0, 10_000_000) for m in _MOIS}
    total = _entier(v["observations"], "observations", 1, 10_000_000)
    if sum(comptes.values()) != total:
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "observations doit égaler la somme des douze mois")
    return cle, {"par_mois": comptes, "observations": total}


def _texte_direction(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    v = _objet(valeur, "valeur", {"texte"})
    return _slug(cle), {"texte": vie_privee.texte_propre(v["texte"], "texte", maximum=300, minimum=10)}


def _vocabulaire(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    v = _objet(valeur, "valeur", {"terme"})
    return _slug(cle), {"terme": vie_privee.texte_propre(v["terme"], "terme", maximum=60)}


def _ton(cle: object, valeur: object) -> tuple[str, dict[str, Any]]:
    if cle != "ton":
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "ton_marque : la clé est « ton »")
    v = _objet(valeur, "valeur", {"descripteurs"})
    d = v["descripteurs"]
    if not isinstance(d, list) or not 1 <= len(d) <= 8:
        raise ErreurMnemo(codes.VALEUR_INVALIDE, "descripteurs : 1 à 8 mots")
    return "ton", {"descripteurs": [vie_privee.texte_propre(x, "descripteur", maximum=30) for x in d]}


# -- libellés : la phrase est écrite par le code
# --------------------------------------------------------------------------
def _l_services(c: str, v: Mapping[str, Any]) -> str:
    return f"L'entreprise offre le service « {v['libelle']} » ({c})."


def _l_zones(c: str, v: Mapping[str, Any]) -> str:
    return f"L'entreprise dessert {len(v['villes'])} ville(s) : {', '.join(v['villes'][:5])}" + (
        "…" if len(v["villes"]) > 5 else "."
    )


def _l_equipes(c: str, v: Mapping[str, Any]) -> str:
    comp = ", ".join(v["competences"]) or "aucune compétence déclarée"
    eff = (
        "effectif prévu non déclaré"
        if v["effectif_planifie"] is None
        else f"{v['effectif_planifie']} personne(s) prévue(s)"
    )
    return f"L'équipe {c} : {comp} ; {eff}."


def _l_capacite(c: str, v: Mapping[str, Any]) -> str:
    cible = "L'entreprise" if c == "entreprise" else f"L'équipe {c}"
    if v["heures_par_semaine"] is None:
        return f"{cible} : capacité hebdomadaire non déclarée (inconnue)."
    return f"{cible} déclare {v['heures_par_semaine']} h d'équipe par semaine type."


def _l_clients(c: str, v: Mapping[str, Any]) -> str:
    part = "" if v["part_pct"] is None else f" (part déclarée : {v['part_pct']} %)"
    return f"Type de client « {c} » : {v['description']}{part}."


def _l_marges(c: str, v: Mapping[str, Any]) -> str:
    return f"Mesure {c} observée : {v['valeur']} {v['unite']} (définition {v['version_definition'][:8]})."


def _l_saison(c: str, v: Mapping[str, Any]) -> str:
    haut = max(v["par_mois"], key=lambda m: (v["par_mois"][m], m))
    return f"{v['observations']} travaux terminés observés ; le mois le plus chargé est le mois {haut}."


def _l_texte(c: str, v: Mapping[str, Any]) -> str:
    return f"{c} : {v['texte']}"


def _l_vocab(c: str, v: Mapping[str, Any]) -> str:
    return f"Dans l'entreprise, « {c} » se dit « {v['terme']} »."


def _l_ton(c: str, v: Mapping[str, Any]) -> str:
    return f"Ton de la marque : {', '.join(v['descripteurs'])}."


@dataclasses.dataclass(frozen=True)
class Dimension:
    nom: str
    structurante: bool
    confidentialite: str
    valider: Callable[[object, object], tuple[str, dict[str, Any]]]
    libelle: Callable[[str, Mapping[str, Any]], str]
    alimentation: str  # d'où vient l'énoncé quand personne ne le déclare
    tolerance_relative: Decimal | None = None  # dérive numérique : en deçà, ce n'est pas une contradiction
    lecteurs: frozenset[str] | None = None  # None : tous les départements


DIMENSIONS: dict[str, Dimension] = {
    d.nom: d
    for d in (
        Dimension("services", True, "INTERNAL", _services, _l_services, "profil d'entreprise (onboarding)"),
        Dimension("zones", True, "INTERNAL", _zones, _l_zones, "profil d'entreprise (onboarding)"),
        Dimension("equipes", True, "INTERNAL", _equipes, _l_equipes, "profil des équipes (onboarding)"),
        Dimension("capacite", True, "INTERNAL", _capacite, _l_capacite, "profil des équipes (semaine type déclarée)"),
        Dimension("clients_types", False, "INTERNAL", _clients_types, _l_clients, "déclaration ou proposition sourcée"),
        Dimension(
            "marges_observees",
            True,
            "FINANCIAL",
            _marges,
            _l_marges,
            "faits analytiques de M8 mémorisés par M10",
            tolerance_relative=TOLERANCE_RELATIVE_MARGE,
            lecteurs=DEPARTEMENTS_FINANCIERS,
        ),
        Dimension("saisonnalite", False, "INTERNAL", _saisonnalite, _l_saison, "travaux terminés mémorisés par M10"),
        Dimension("preferences_direction", True, "INTERNAL", _texte_direction, _l_texte, "déclaration de la direction"),
        Dimension("regles_direction", True, "INTERNAL", _texte_direction, _l_texte, "déclaration de la direction"),
        Dimension("vocabulaire", False, "INTERNAL", _vocabulaire, _l_vocab, "pack sectoriel actif"),
        Dimension("ton_marque", False, "INTERNAL", _ton, _l_ton, "déclaration de la direction"),
    )
}


def dimension(nom: object) -> Dimension:
    if not isinstance(nom, str) or nom not in DIMENSIONS:
        raise ErreurMnemo(codes.DIMENSION_INCONNUE, f"dimension {vie_privee.court(nom)} inconnue : {list(DIMENSIONS)}")
    return DIMENSIONS[nom]


def dans_la_tolerance(d: Dimension, ancienne: Mapping[str, Any], nouvelle: Mapping[str, Any]) -> bool:
    """Vrai si deux valeurs d'une dimension numérique diffèrent de moins que sa tolérance relative (même unité et même
    définition exigées : un changement de définition est toujours une contradiction à examiner)."""
    if d.tolerance_relative is None:
        return False
    if (ancienne["unite"], ancienne["version_definition"]) != (nouvelle["unite"], nouvelle["version_definition"]):
        return False
    try:
        a, n = Decimal(ancienne["valeur"]), Decimal(nouvelle["valeur"])
    except InvalidOperation:
        return False
    if a == 0:
        return n == 0
    return abs(n - a) / abs(a) < d.tolerance_relative
