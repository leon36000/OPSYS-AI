"""Faits analytiques consolidés par M8 (M8.18) : M10 les mémorise tels quels, avec leur provenance, sans jamais les
recalculer.

M8 publie ``m8.fait_consolide`` : les mesures d'ENTREPRISE de son catalogue fermé (valeur exacte en texte ou ``null``,
unité,
propriétaire, version de la définition gouvernée, instant du dernier fait, statut de fraîcheur), les changements de
définition
et les anomalies depuis la consolidation précédente. M10 range chaque événement dans son registre ``faits_analytiques``
(append-only, chaîné), distinct des registres Événements et Affaires : ce n'est pas un fait d'affaire (aucun
``lead_id``) et il ne
sort dans aucun paquet de contexte.

Règles :

* LISTE BLANCHE, FORMES FERMÉES. Chaque champ gardé a une forme (identifiant de mesure, empreinte, texte décimal,
énuméré,
  instant) ; un champ de plus ou hors forme est un refus nommé qui dit le CHAMP, jamais la valeur. Rien de personnel
  ne peut
  entrer : aucun champ de texte libre n'est conservé, hors le nom gouverné d'une mesure et la mention.
* CONFIDENTIALITÉ. L'entrée est ``FINANCIAL`` (elle porte le cash libre et le carnet) : elle ne sort dans aucun paquet
de
  contexte, pour aucun agent (``confidentialite.py``, règle 2) ; elle se lit dans M10, avec son outil et son rôle.
* IDEMPOTENCE. Un fait par ``evenement_id`` : une relivraison ou un rejeu n'ajoute rien. L'instant d'une entrée est
celui de
  l'ÉVÉNEMENT (``consolide_le``), jamais une horloge de M10.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import confidentialite, validation

TYPE_EVENEMENT = "m8.fait_consolide"
TYPE_ENTREE = "fait_analytique"
PRODUCTEUR = "m08-analytics"
MESURES_MAX = 40

REJ_ANALYTIQUE_CHAMP_MANQUANT = "REJ-ANALYTIQUE-CHAMP-MANQUANT"
REJ_ANALYTIQUE_CHAMP_INVALIDE = "REJ-ANALYTIQUE-CHAMP-INVALIDE"

_IDENTIFIANT_EVENEMENT = re.compile(r"^m8-faits-[0-9a-f]{64}$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")
_MESURE_ID = re.compile(r"^m8_[a-z0-9_]{1,76}$")
_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
_PROPRIETAIRE = re.compile(r"^m[0-9]{2}-[a-z0-9-]{1,40}$")
_INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+\-Zz]{6,32}$")
_DOMAINES = frozenset({"ventes", "marketing", "operations", "qualite", "finance", "clientele"})
_STATUTS = frozenset({"calculee", "non_calculable"})
_FRAICHEURS = frozenset({"a_jour", "perime", "inconnu", "manquant", "non_applicable"})
_ANOMALIES = frozenset({"devenue_non_calculable", "perimee"})
_CLES_MESURE = frozenset(
    {
        "metric_id",
        "nom",
        "domaine",
        "unite",
        "proprietaire",
        "statut",
        "valeur",
        "version_definition",
        "dernier_fait_le",
        "fraicheur",
    }
)


class ChampRefuse(ValueError):
    """Un champ manque ou sort de sa forme fermée. ``code`` est le verdict, ``detail`` le CHAMP (jamais sa valeur)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def verdict(self) -> dict[str, Any]:
        return validation.construire_verdict(self.code, self.detail)


def _texte(valeur: Any, champ: str, motif: re.Pattern[str] | None = None, maximum: int = 400) -> str:
    if (
        not isinstance(valeur, str)
        or not valeur
        or len(valeur) > maximum
        or (motif is not None and not motif.fullmatch(valeur))
    ):
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, champ)
    return valeur


def _mesure(brut: Any, rang: int) -> dict[str, Any]:
    if not isinstance(brut, Mapping) or set(brut) != _CLES_MESURE:
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, f"mesures[{rang}]")
    valeur = brut["valeur"]
    if valeur is not None:
        _texte(valeur, f"mesures[{rang}].valeur", _DECIMAL, 24)
    if (brut["statut"] == "calculee") != (valeur is not None) or brut["statut"] not in _STATUTS:
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, f"mesures[{rang}].statut")
    if brut["domaine"] not in _DOMAINES or brut["fraicheur"] not in _FRAICHEURS:
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, f"mesures[{rang}].domaine")
    dernier = brut["dernier_fait_le"]
    if dernier is not None:
        _texte(dernier, f"mesures[{rang}].dernier_fait_le", _INSTANT, 40)
    return {
        "metric_id": _texte(brut["metric_id"], f"mesures[{rang}].metric_id", _MESURE_ID),
        "nom": _texte(brut["nom"], f"mesures[{rang}].nom", None, 120),
        "domaine": brut["domaine"],
        "unite": _texte(brut["unite"], f"mesures[{rang}].unite", None, 32),
        "proprietaire": _texte(brut["proprietaire"], f"mesures[{rang}].proprietaire", _PROPRIETAIRE),
        "statut": brut["statut"],
        "valeur": valeur,
        "version_definition": _texte(brut["version_definition"], f"mesures[{rang}].version_definition", _EMPREINTE),
        "dernier_fait_le": dernier,
        "fraicheur": brut["fraicheur"],
    }


def extraire(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Les champs à garder d'une charge ``m8.fait_consolide`` : liste blanche, formes fermées."""
    if not isinstance(charge, Mapping):
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, "charge")
    for cle in (
        "evenement_id",
        "consolide_le",
        "empreinte_registres",
        "version_catalogue",
        "premiere_consolidation",
        "mesures",
        "changements_definition",
        "anomalies",
        "mention",
    ):
        if cle not in charge:
            raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_MANQUANT, cle)
    mesures = charge["mesures"]
    if not isinstance(mesures, list) or not 1 <= len(mesures) <= MESURES_MAX:
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, "mesures")
    changements, anomalies = charge["changements_definition"], charge["anomalies"]
    if not isinstance(changements, list) or len(changements) > MESURES_MAX:
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, "changements_definition")
    if not isinstance(anomalies, list) or len(anomalies) > 2 * MESURES_MAX:
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, "anomalies")
    if not isinstance(charge["premiere_consolidation"], bool):
        raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, "premiere_consolidation")
    gardees_changements = []
    for rang, c in enumerate(changements):
        if not isinstance(c, Mapping) or set(c) != {"metric_id", "ancienne", "nouvelle"}:
            raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, f"changements_definition[{rang}]")
        gardees_changements.append(
            {
                "metric_id": _texte(c["metric_id"], f"changements_definition[{rang}].metric_id", _MESURE_ID),
                "ancienne": _texte(c["ancienne"], f"changements_definition[{rang}].ancienne", _EMPREINTE),
                "nouvelle": _texte(c["nouvelle"], f"changements_definition[{rang}].nouvelle", _EMPREINTE),
            }
        )
    gardees_anomalies = []
    for rang, a in enumerate(anomalies):
        if not isinstance(a, Mapping) or set(a) != {"metric_id", "type"} or a["type"] not in _ANOMALIES:
            raise ChampRefuse(REJ_ANALYTIQUE_CHAMP_INVALIDE, f"anomalies[{rang}]")
        gardees_anomalies.append(
            {"metric_id": _texte(a["metric_id"], f"anomalies[{rang}].metric_id", _MESURE_ID), "type": a["type"]}
        )
    return {
        "evenement_id": _texte(charge["evenement_id"], "evenement_id", _IDENTIFIANT_EVENEMENT),
        "horodatage": _texte(charge["consolide_le"], "consolide_le", _INSTANT, 40),
        "empreinte_registres": _texte(charge["empreinte_registres"], "empreinte_registres", _EMPREINTE),
        "version_catalogue": _texte(charge["version_catalogue"], "version_catalogue", _EMPREINTE),
        "premiere_consolidation": charge["premiere_consolidation"],
        "mesures": [_mesure(m, rang) for rang, m in enumerate(mesures)],
        "changements_definition": gardees_changements,
        "anomalies": gardees_anomalies,
        "mention": _texte(charge["mention"], "mention"),
    }


def entree(champs: Mapping[str, Any]) -> dict[str, Any]:
    """Le maillon à écrire : les champs extraits, puis ce que M10 pose. Une charge ne peut ni choisir le type, ni le
    producteur, ni le niveau de confidentialité : ces clés sont écrites APRÈS elle."""
    return {
        **champs,
        "type_entree": TYPE_ENTREE,
        "producteur": PRODUCTEUR,
        "confidentialite": confidentialite.NIVEAU_FINANCIER,
    }


def memoriser(charge: Mapping[str, Any], registre_cible: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Mémorise une consolidation de M8 ; rend ``(resultat, None)`` ou ``(None, verdict)``, sans rien écrire au refus.
    ``resultat`` : ``{maillon, deja_memorise}``. Un seul maillon par ``evenement_id``."""
    try:
        champs = extraire(charge)
    except ChampRefuse as refus:
        return None, refus.verdict()
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == TYPE_ENTREE and maillon.get("evenement_id") == champs["evenement_id"]:
            return {"maillon": maillon, "deja_memorise": True}, None
    ligne_id = registre_cible.ajouter(entree(champs))
    maillon = next(m for m in registre_cible.lire() if m["ligne_id"] == ligne_id)
    return {"maillon": maillon, "deja_memorise": False}, None


def lister(registre_cible: Any, limite: int, decalage: int) -> dict[str, Any]:
    """Les consolidations mémorisées, de la plus récente à la plus ancienne, une page à la fois, en RÉSUMÉ (identifiant,
    instant, comptes, changements, anomalies) — jamais l'ensemble des valeurs : la dernière valeur de chaque mesure se
    lit
    avec ``derniere_valeur``."""
    maillons = [m for m in registre_cible.lire() if m.get("type_entree") == TYPE_ENTREE]
    recents = list(reversed(maillons))
    page = recents[decalage : decalage + limite]
    return {
        "total": len(maillons),
        "decalage": decalage,
        "limite": limite,
        "consolidations": [
            {
                "evenement_id": m["evenement_id"],
                "consolide_le": m["horodatage"],
                "ligne_id": m["ligne_id"],
                "n_mesures": len(m["mesures"]),
                "changements_definition": m["changements_definition"],
                "anomalies": m["anomalies"],
                "premiere_consolidation": m["premiere_consolidation"],
            }
            for m in page
        ],
        "suivant": decalage + limite if decalage + limite < len(recents) else None,
        "confidentialite": confidentialite.NIVEAU_FINANCIER,
    }


def derniere_valeur(registre_cible: Any, metric_id: str) -> dict[str, Any]:
    """La dernière valeur mémorisée d'une mesure, avec la consolidation qui la porte ; ``{"trouvee": false}`` sinon."""
    for maillon in reversed([m for m in registre_cible.lire() if m.get("type_entree") == TYPE_ENTREE]):
        for mesure in maillon["mesures"]:
            if mesure["metric_id"] == metric_id:
                return {
                    "trouvee": True,
                    "metric_id": metric_id,
                    "mesure": mesure,
                    "evenement_id": maillon["evenement_id"],
                    "consolide_le": maillon["horodatage"],
                    "ligne_id": maillon["ligne_id"],
                }
    return {"trouvee": False, "metric_id": metric_id}
