"""Capacités d'agent du département M3 Estimation.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est réécrite.
`m3_estimer_projet` compose la chaîne complète en un seul appel, ce qui évite à l'agent
cinq allers-retours (économie de tokens) et garantit l'ordre des contrôles. Le prix n'est
jamais calculé quand il doit être bloqué.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import blocage_prix, contrats, hierarchie_echelle, monte_carlo, plancher, qualite_photos, registre

_PHOTO = {
    "type": "object",
    "properties": {
        "photo_id": {"type": "string"},
        "resolution_largeur": {"type": "integer"},
        "resolution_hauteur": {"type": "integer"},
        "eclairage": {"type": "number", "description": "0 à 10"},
        "angle": {"type": "string"},
        "reference_echelle": {
            "type": ["object", "null"],
            "description": "{type, dimensions_connues} ou null si aucun objet de référence",
        },
    },
    "required": list(contrats.CHAMPS_PHOTO),
}
_SEUILS = {
    "type": "object",
    "properties": {"resolution_minimale": {"type": "integer"}, "eclairage_minimal": {"type": "number"}},
    "required": list(contrats.CHAMPS_SEUILS_QUALITE),
}
_BAREME = {
    "type": "object",
    "description": "{version, unite, postes: {type_travaux: {cout_unitaire_min, cout_unitaire_max}}}",
}
_TYPE_TRAVAUX = {"type": "string", "enum": list(contrats.TYPES_TRAVAUX)}


def qualifier_photos(photos: list[dict[str, Any]], seuils: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(qualite_photos.qualifier_photos(photos, seuils))


def classifier_confiance(photos: list[dict[str, Any]], seuils: dict[str, Any]) -> dict[str, Any]:
    # Convention propre à cette fonction : (niveau, motifs) si valide, (None, verdict) sinon.
    niveau, info = hierarchie_echelle.classifier_niveau_confiance(photos, seuils)
    if niveau is None:
        return {"accepte": False, "verdict": info}
    return {"accepte": True, "resultat": {"niveau_confiance": niveau, "motifs": info}}


def simuler_intervalle(
    bareme: dict[str, Any], type_travaux: str, quantite: float, graine: int, niveau: float = 0.9
) -> dict[str, Any]:
    intervalle, rejet = monte_carlo.simuler_intervalle(bareme, type_travaux, quantite, graine, niveau)
    if rejet is not None:
        return depuis_couple((intervalle, rejet))
    intervalle = {
        "borne_basse": arrondir_au_cent(intervalle["borne_basse"]),
        "borne_haute": arrondir_au_cent(intervalle["borne_haute"]),
        "niveau": intervalle["niveau"],
    }
    return depuis_couple((intervalle, None))


def confronter_plancher(intervalle: dict[str, Any], plancher_rentable: float) -> dict[str, Any]:
    return depuis_couple(plancher.confronter_au_plancher(intervalle, plancher_rentable))


def graine_stable(bareme: dict[str, Any], type_travaux: str, quantite: float) -> int:
    """Graine reproductible dérivée des entrées : même demande, même intervalle."""
    empreinte = json.dumps([bareme.get("version"), type_travaux, quantite], sort_keys=True)
    return int(hashlib.sha256(empreinte.encode("utf-8")).hexdigest()[:8], 16)


_CENT = Decimal("0.01")


def arrondir_au_cent(valeur: float) -> float:
    """Arrondit un montant CAD au cent le plus proche via Decimal.

    ``Decimal(str(valeur))`` (jamais ``Decimal(valeur)``) : convertir depuis
    la représentation DÉCIMALE du float évite de figer les artefacts de son
    codage binaire (ex. 9979.771554055122 plutôt que la valeur "ronde"
    voulue). Le résultat reste un float — le contrat gelé EstimationV1
    (PRD §5) type ``borne_basse``/``borne_haute`` en ``float`` — mais chaque
    cent est déterminé par un calcul décimal exact, jamais par l'arrondi
    binaire implicite du float.
    """
    return float(Decimal(str(valeur)).quantize(_CENT, rounding=ROUND_HALF_UP))


# Niveau statistique (couverture du Monte Carlo — PRD §5 : "niveau : float,
# ex. 0.90 pour 90 %, configurable par l'appelant") retenu par rang de
# FIABILITÉ DE MESURE dans la hiérarchie ratifiée (hierarchie_echelle.
# NIVEAUX_CONFIANCE, ordre épinglé). Politique ÉNONCÉE, pas une mesure —
# REFERENCE_ECHELLE (rang 0, objet de dimensions CERTIFIÉES visible dans le
# cadre — "condition nécessaire et suffisante pour une estimation précise",
# PRD §4.1) reprend SANS changement le niveau nominal déclaré par
# l'architecture (blocage_prix.NIVEAU_CONFIANCE_NOMINAL = 0.90). Chaque cran
# de MOINS de fiabilité de mesure élève la couverture statistique demandée :
# MULTI_VUES ("précision moindre", PRD §4.1) puis MONO_VUE_BORNES_LARGES
# (BORNES LARGES dès son nom, MAE ~0,45 m au mieux sans référence, brief
# analyste §3). Une couverture statistique plus large élargit MÉCANIQUEMENT
# l'intervalle rendu par monte_carlo.simuler_intervalle SANS jamais dépasser
# le support du barème : la borne "NON NÉGOCIABLE" déjà imposée par
# monte_carlo.py (chaque tirage est borné à [cout_min, cout_max] * quantite)
# s'applique intacte, sans clamp supplémentaire à ajouter ici. INDETERMINE
# n'atteint jamais cette table : le prix y est bloqué en amont par
# blocage_prix.decider_blocage, avant tout calcul d'intervalle.
NIVEAUX_STATISTIQUES_PAR_CONFIANCE = {
    hierarchie_echelle.NIVEAUX_CONFIANCE[0]: blocage_prix.NIVEAU_CONFIANCE_NOMINAL,  # REFERENCE_ECHELLE : 0.90
    hierarchie_echelle.NIVEAUX_CONFIANCE[1]: 0.95,  # MULTI_VUES
    hierarchie_echelle.NIVEAUX_CONFIANCE[2]: 0.99,  # MONO_VUE_BORNES_LARGES
}


def estimer_projet(
    photos: list[dict[str, Any]],
    seuils: dict[str, Any],
    bareme: dict[str, Any],
    type_travaux: str,
    quantite: float,
    plancher_rentable: float,
    graine: int | None = None,
) -> dict[str, Any]:
    """Chaîne complète : qualité photos → confiance → blocage → intervalle → plancher."""
    qualification, verdict = qualite_photos.qualifier_photos(photos, seuils)
    if verdict is not None:
        return {"etape": "qualite_photos", "accepte": False, "verdict": verdict}
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(photos, seuils)
    if niveau is None:
        return {"etape": "niveau_confiance", "accepte": False, "verdict": motifs}
    decision, rejet = blocage_prix.decider_blocage(niveau, qualification)
    if rejet is not None:
        return {"etape": "blocage", "accepte": False, "verdict": rejet}
    if decision["prix_bloque"]:
        return {
            "etape": "blocage",
            "accepte": True,
            "prix_bloque": True,
            "niveau_confiance": niveau,
            "motifs_confiance": motifs,
            "verdict_estimation": decision["verdict_estimation"],
            "raison_blocage": decision["raison_blocage"],
            "elements_manquants": qualification["elements_manquants"],
        }
    graine_effective = graine if graine is not None else graine_stable(bareme, type_travaux, quantite)
    niveau_statistique = NIVEAUX_STATISTIQUES_PAR_CONFIANCE[niveau]
    intervalle, rejet = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite, graine_effective, niveau_statistique
    )
    if rejet is not None:
        return {"etape": "intervalle", "accepte": False, "verdict": rejet}
    intervalle = {
        "borne_basse": arrondir_au_cent(intervalle["borne_basse"]),
        "borne_haute": arrondir_au_cent(intervalle["borne_haute"]),
        "niveau": intervalle["niveau"],
    }
    constat, rejet = plancher.confronter_au_plancher(intervalle, plancher_rentable)
    if rejet is not None:
        return {"etape": "plancher", "accepte": False, "verdict": rejet}
    return {
        "etape": "complet",
        "accepte": True,
        "prix_bloque": False,
        "niveau_confiance": niveau,
        "motifs_confiance": motifs,
        "intervalle": intervalle,
        "alerte_plancher": constat["alerte_plancher"],
        "verdict_estimation": constat["verdict_estimation"],
        "graine_monte_carlo": graine_effective,
        "bareme_version": bareme.get("version"),
    }


def registre_production() -> registre.Registre:
    """Registre M3 adossé au stockage durable de l'instance (ADR-0009).

    `registre.py` reste pur : il ignore que ses maillons viennent d'une liste Python ou de
    `opsys.stockage.MaillonsDurables`. C'est ce point d'entrée — jamais `registre.py` — qui
    choisit le support durable pour un registre de production, dans la transaction courante
    (`opsys.stockage.transaction()`, ouverte par l'appelant ou par `Capacites.appeler`). Les
    tests unitaires du département construisent `registre.Registre()` EN MÉMOIRE, explicitement,
    sans passer par cette fonction.
    """
    return registre.Registre(stockage.maillons("m03-estimation", "principal"))


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m3_estimer_projet",
            description=(
                "Estime un projet de bout en bout à partir des photos, seuils, barème, type de travaux, "
                "quantité et plancher de rentabilité. Bloque le prix si les photos ou la référence "
                "d'échelle sont insuffisantes et liste alors les éléments manquants à demander."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "photos": {"type": "array", "items": _PHOTO},
                    "seuils": _SEUILS,
                    "bareme": _BAREME,
                    "type_travaux": _TYPE_TRAVAUX,
                    "quantite": {"type": "number"},
                    "plancher_rentable": {"type": "number"},
                    "graine": {"type": "integer"},
                },
                "required": ["photos", "seuils", "bareme", "type_travaux", "quantite", "plancher_rentable"],
                "additionalProperties": False,
            },
            fonction=estimer_projet,
        ),
        Outil(
            nom="m3_qualifier_photos",
            description="Vérifie la qualité des photos (résolution, éclairage) et liste ce qui manque.",
            parametres={
                "type": "object",
                "properties": {"photos": {"type": "array", "items": _PHOTO}, "seuils": _SEUILS},
                "required": ["photos", "seuils"],
                "additionalProperties": False,
            },
            fonction=qualifier_photos,
        ),
        Outil(
            nom="m3_classifier_confiance",
            description="Classe le niveau de confiance des mesures (référence d'échelle, multi-vues, mono-vue).",
            parametres={
                "type": "object",
                "properties": {"photos": {"type": "array", "items": _PHOTO}, "seuils": _SEUILS},
                "required": ["photos", "seuils"],
                "additionalProperties": False,
            },
            fonction=classifier_confiance,
        ),
        Outil(
            nom="m3_simuler_intervalle",
            description="Intervalle de coût Monte Carlo reproductible pour un type de travaux et une quantité.",
            parametres={
                "type": "object",
                "properties": {
                    "bareme": _BAREME,
                    "type_travaux": _TYPE_TRAVAUX,
                    "quantite": {"type": "number"},
                    "graine": {"type": "integer"},
                    "niveau": {"type": "number", "description": "entre 0 et 1 exclus, défaut 0,9"},
                },
                "required": ["bareme", "type_travaux", "quantite", "graine"],
                "additionalProperties": False,
            },
            fonction=simuler_intervalle,
        ),
        Outil(
            nom="m3_confronter_plancher",
            description="Compare la borne basse d'un intervalle au plancher de rentabilité fourni.",
            parametres={
                "type": "object",
                "properties": {
                    "intervalle": {"type": "object"},
                    "plancher_rentable": {"type": "number"},
                },
                "required": ["intervalle", "plancher_rentable"],
                "additionalProperties": False,
            },
            fonction=confronter_plancher,
            autonomie=Autonomie.T0,
        ),
    )
