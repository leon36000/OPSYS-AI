"""Prévisions consolidées M9.9 : lire ce que les propriétaires ont PRÉVU, jamais le prévoir à leur place.

Module pur. Seule la prévision de trésorerie de M5 (``m5.prevision_tresorerie``) existe aujourd'hui chez un
propriétaire.
M9 la présente avec ce que M5 déclare (horizon, réserves, ce qui est non calculable, encaissements non comptés), ses
VERSIONS successives (empreinte ``prevision_id``) et leur âge au jour de référence ; chaque valeur est un fait citable
``<lecture>#<rang>:p<page>.<chemin>`` en texte exact. M9 ne calcule aucun solde, aucune différence d'argent et aucune
probabilité : M5 ne publie pas d'incertitude chiffrée, et ce manque est dit tel quel.

Les domaines sans prévision publiée par leur propriétaire (leads, capacité d'équipe, matériaux) restent
``AUCUNE_PREVISION_PRODUITE`` avec le propriétaire attendu : un chiffre n'est jamais produit à leur place, et une
absence ne devient pas une valeur. Une capture refusée, partielle ou contradictoire ne produit aucune prévision citée.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs

VERSION = "2026-10-28.1"
LECTURE_TRESORERIE = "m5.prevision_tresorerie"
_R = "resultat.resultat"
DOMAINES: dict[str, dict] = {
    "tresorerie": {"proprietaire": "m05-financecore", "lecture": LECTURE_TRESORERIE},
    "leads": {"proprietaire": "m02-revenue-crm", "lecture": None},
    "capacite": {"proprietaire": "m04-field-ops", "lecture": None},
    "materiaux": {"proprietaire": "m06-material-control", "lecture": None},
}
_CHAMPS_CITES = (
    "aujourd_hui",
    "horizon_semaines",
    "fin_horizon",
    "calculable",
    "non_calculable_a_partir_de",
    "alerte.statut",
    "premiere_semaine_en_deficit",
    "prevision_id",
    "solde_initial.montant",
)
_LIMITES = (
    "Prévisions de leurs propriétaires, citées telles quelles : M9 n'en produit aucune et ne calcule aucun montant.",
    "M5 ne publie ni intervalle ni probabilité : l'incertitude n'est pas chiffrée, elle est décrite par ses réserves.",
)


def _jour(valeur: object) -> dt.date | None:
    if type(valeur) is not str or len(valeur) != 10:
        return None
    try:
        return dt.date.fromisoformat(valeur)
    except ValueError:
        return None


def _valeur(capture: Mapping, chemin: str) -> object:
    trouvees = [v for page in capture["pages"] for v in cs.extraire(page, f"{_R}.{chemin}")]
    return trouvees[0] if trouvees else None


def _texte(valeur: object) -> str | None:
    return None if valeur is None else (json.dumps(valeur) if not isinstance(valeur, str) else valeur)


def _adresse(capture: Mapping, chemin: str) -> str | None:
    for numero_page, page in enumerate(capture["pages"]):
        if cs.extraire(page, f"{_R}.{chemin}"):
            return f"{capture['lecture_id']}#{capture['index']}:p{numero_page}.{_R}.{chemin}"
    return None


def _statut_capture(capture: Mapping, en_conflit: set) -> str:
    if capture["verdict"] != "ACCEPTEE":
        return "REFUSEE"
    if (capture["lecture_id"], capture["arguments_sha256"]) in en_conflit:
        return "CONTRADICTOIRE"
    return "COMPLETE" if capture["complete"] else "PARTIELLE"


def _version(capture: Mapping, statut: str, jour_connaissance: dt.date | None) -> dict:
    entree: dict = {
        "capture": capture["index"],
        "hash_capture": capture["hash_maillon"],
        "recu_a": capture["recu_a"],
        "statut": statut,
        "arguments": capture["arguments"],
        "reference_jour": capture.get("reference_jour"),
    }
    if statut not in ("COMPLETE", "PARTIELLE"):
        return entree
    semaines = [s for page in capture["pages"] for s in cs.extraire(page, f"{_R}.semaines[*]")]
    horizon = _valeur(capture, "horizon_semaines")
    entree["faits"] = {chemin: _adresse(capture, chemin) for chemin in _CHAMPS_CITES if _adresse(capture, chemin)}
    entree["valeurs"] = {chemin: _texte(_valeur(capture, chemin)) for chemin in _CHAMPS_CITES}
    entree["solde_initial"] = _texte(_valeur(capture, "solde.montant")) or _texte(
        _valeur(capture, "solde_initial.montant")
    )
    entree["semaines_lues"] = len(semaines)
    entree["semaines_manquantes"] = (
        (horizon - len(semaines)) if type(horizon) is int and horizon >= len(semaines) else None
    )
    entree["reserves"] = list(_valeur(capture, "reserves") or [])
    entree["manque"] = _valeur(capture, "manque") or []
    entree["encaissements_non_comptes"] = _valeur(capture, "encaissements_non_comptes") or []
    jour = _jour(capture.get("reference_jour"))
    entree["age_jours"] = (
        (jour_connaissance - jour).days if jour is not None and jour_connaissance is not None else None
    )
    entree["partielle_raison"] = capture.get("raison_incomplete") if statut == "PARTIELLE" else None
    return entree


def consolider(
    captures: Sequence[Mapping], *, connaissance: str, perime_apres_jours: int | None = None, max_versions: int = 5
) -> dict:
    """Prévisions connues à ``connaissance`` par domaine, avec versions, âge, réserves et domaines sans prévision."""
    if type(max_versions) is not int or not 1 <= max_versions <= 20:
        raise ValueError("REJ-PREVISION-VERSIONS : entier de 1 à 20 requis")
    if perime_apres_jours is not None and (type(perime_apres_jours) is not int or not 0 <= perime_apres_jours <= 3650):
        raise ValueError("REJ-PREVISION-PEREMPTION : entier de 0 à 3650 jours ou absent")
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    jour_connaissance = cs.instant(connaissance).date()  # type: ignore[union-attr]
    domaines: list[dict] = []
    for nom, source in DOMAINES.items():
        entree: dict = {"domaine": nom, "proprietaire": source["proprietaire"], "lecture": source["lecture"]}
        if source["lecture"] is None:
            entree |= {
                "statut": "AUCUNE_PREVISION_PRODUITE",
                "raison": f"{source['proprietaire']} ne publie aucune prévision de {nom} ; M9 n'en estime aucune",
                "versions": [],
            }
            domaines.append(entree)
            continue
        lues = [c for c in connues if c["lecture_id"] == source["lecture"]]
        if not lues:
            entree |= {"statut": "ABSENTE", "raison": "aucune capture connue de cette lecture", "versions": []}
            domaines.append(entree)
            continue
        versions = [_version(c, _statut_capture(c, en_conflit), jour_connaissance) for c in lues]
        precedente: dict | None = None
        for version in versions:
            if "valeurs" in version and precedente is not None and "valeurs" in precedente:
                version["change_depuis_precedente"] = {
                    "prevision_id": version["valeurs"]["prevision_id"] != precedente["valeurs"]["prevision_id"],
                    "solde_initial": version["solde_initial"] != precedente["solde_initial"],
                    "alerte": version["valeurs"]["alerte.statut"] != precedente["valeurs"]["alerte.statut"],
                    "reserves": version["reserves"] != precedente["reserves"],
                }
            if "valeurs" in version:
                precedente = version
        # Version courante : la dernière capture COMPLETE (jamais une partielle, refusée ou contradictoire).
        completes = [v for v in versions if v["statut"] == "COMPLETE"]
        courante = completes[-1] if completes else None
        entree["versions_total"] = len(versions)
        entree["versions"] = versions[-max_versions:]  # les plus récentes ; le total reste dit
        if courante is None:
            entree |= {"statut": "AUCUNE_VERSION_UTILISABLE", "raison": "aucune capture complète et non contradictoire"}
        else:
            entree["statut"] = "DISPONIBLE"
            entree["courante"] = courante["capture"]
            entree["incertitude"] = {
                "chiffree": False,
                "decrite_par": {"reserves": courante["reserves"], "manque": courante["manque"]},
            }
            age = courante["age_jours"]
            if perime_apres_jours is not None and age is not None and age > perime_apres_jours:
                entree["statut"] = "PERIMEE"
        domaines.append(entree)
    return {
        "type": "PREVISIONS_CONSOLIDEES",
        "version": VERSION,
        "connaissance": connaissance,
        "perime_apres_jours": perime_apres_jours,
        "domaines": domaines,
        "limites": list(_LIMITES),
    }
