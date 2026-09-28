"""Capacités d'agent du département M3 Estimation.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est réécrite.
`m3_estimer_projet` compose la chaîne complète en un seul appel, ce qui évite à l'agent
cinq allers-retours (économie de tokens) et garantit l'ordre des contrôles. Le prix n'est
jamais calculé quand il doit être bloqué.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from opsys import evenements, stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import (
    blocage_prix,
    contrats,
    devis_durable,
    estime_vs_reel,
    hierarchie_echelle,
    monte_carlo,
    plancher,
    qualite_photos,
    registre,
)

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
_LIGNE_DEVIS = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quantite": {"type": "string", "description": "texte décimal, ex. \"12.5\" (jamais un nombre JSON)"},
        "unite": {"type": "string"},
        "cout_unitaire": {
            "type": "string",
            "description": "texte décimal CAD, coût unitaire — jamais un prix, le prix est calculé",
        },
        "reference_besoin_materiau": {
            "type": ["string", "null"],
            "description": "référence du besoin matériau (M6), ou null si cette ligne n'en a pas",
        },
    },
    "required": ["description", "quantite", "unite", "cout_unitaire", "reference_besoin_materiau"],
    "additionalProperties": False,
}


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


def registre_devis_production() -> stockage.MaillonsDurables:
    """Registre M3 des DEVIS (PLAN T2.3-a), adossé au stockage durable de l'instance (ADR-0009) :
    `opsys.stockage.maillons("m03-estimation", "devis")`, dans la base et la transaction de
    l'appel courant, relu à chaque appel, jamais mis en cache — même discipline que
    `registre_production` ci-dessus, mais DÉLIBÉRÉMENT une collection distincte ("devis", jamais
    "principal") : le registre "principal" porte les charges d'ESTIMATION Monte Carlo (S008, six
    clés fixes dont `niveau_confiance`/`bareme_version`/`graine_monte_carlo`, hash-chaînées par
    `registre.Registre`), pas les lignes commerciales d'un devis (voir la docstring de
    `devis_durable.py`). `devis_durable.py` reste pur : il ignore que ses maillons viennent d'une
    liste Python (tests unitaires, construite EN MÉMOIRE, explicitement, sans passer par cette
    fonction) ou de `opsys.stockage.MaillonsDurables` (production, ce point d'entrée) — c'est ce
    point d'entrée, jamais `devis_durable.py`, qui choisit le support durable."""
    return stockage.maillons("m03-estimation", "devis")


def creer_devis(
    devis_id: str,
    lead_id: str,
    chantier_id: str | None,
    lignes: list[dict[str, Any]],
    taux_marge: str,
    horodatage: str,
    prix_total: str | None = None,
) -> dict[str, Any]:
    return depuis_couple(
        devis_durable.creer_devis(
            devis_id,
            lead_id,
            chantier_id,
            lignes,
            taux_marge,
            horodatage,
            registre_devis_production(),
            prix_total_fourni=prix_total,
        )
    )


def lire_devis(devis_id: str, role: str = "interne") -> dict[str, Any]:
    devis, verdict = devis_durable.lire_devis(registre_devis_production(), devis_id)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return depuis_couple(devis_durable.projeter_devis(devis, role))


def marquer_devis_accepte(devis_id: str, approbateur: str, horodatage: str) -> dict[str, Any]:
    """Marque un devis ACCEPTE et publie `m3.devis_accepte` dans la MÊME transaction (ADR-0009
    §3) — seulement quand la transition réussit réellement (`verdict is None`) : un rejet
    (devis introuvable, transition illégale, approbateur absent) n'écrit et ne publie jamais rien.

    `evenement_id` déterministe (`f"m3-devis-accepte-{devis_id}"`, PLAN T2.3-b, même patron que
    M6 pour `m6.variance_chantier` : `f"m6-variance-{wct_id}"`) : défense en profondeur — un
    rejeu de cet appel (ex. panne réseau entre l'écriture et la réponse au producteur) republie
    donc un no-op (`evenements.publier` sur un `evenement_id` déjà connu), jamais un second
    événement pour la même acceptation.
    """
    devis, verdict = devis_durable.marquer_devis_accepte(
        devis_id, approbateur, horodatage, registre_devis_production()
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    evenements.publier(
        "m3.devis_accepte",
        "m03-estimation",
        devis_durable.charge_evenement_devis_accepte(devis),
        evenement_id=f"m3-devis-accepte-{devis_id}",
    )
    return {"accepte": True, "resultat": devis}


def registre_estime_vs_reel_production() -> stockage.MaillonsDurables:
    """Registre M3 dédié à l'estimé-vs-réel (PLAN T1.2-d, en second ordre) : `stockage.maillons(
    "m03-estimation", "estime_vs_reel")`, relu à chaque appel, jamais mis en cache — même
    discipline que `registre_devis_production`/`registre_production` ci-dessus. Distinct de
    `registre_production()` ("principal") : celui-ci reste le registre D'ORIGINE des estimations
    (S008, jamais écrit ici — lu seulement, voir `estime_vs_reel.py`) ; "estime_vs_reel" est la
    collection propre aux RÉSULTATS de comparaison (durée réelle vs estimée, variance matériaux),
    jamais mélangée aux deux autres."""
    return stockage.maillons("m03-estimation", "estime_vs_reel")


# ---------------------------------------------------------------------------------------------
# Consommateurs d'événements (ADR-0009 §3, PLAN T1.2-d) : seul cet adaptateur connaît `opsys` ;
# `estime_vs_reel.py` (module pur) fait le rapprochement et l'enregistrement déterministes. Le
# répartiteur (`opsys.evenements.repartir`) n'appelle ces fonctions que dans une transaction déjà
# ouverte : le registre durable fait donc TOUJOURS autorité ici (comme les outils T1/T3
# ci-dessus), sans le mode « en mémoire » des tests unitaires du module pur.
# ---------------------------------------------------------------------------------------------
def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m4.travaux_termines` : relie le WCT à son devis puis, si le lien existe déjà, à
    l'estimation d'origine (`estime_vs_reel.enregistrer_travaux_termines`, DÉTERMINISTE). Toujours
    `traite: true` — une comparaison main-d'œuvre incomplète est une lacune nommée dans le
    résultat, jamais un échec de consommation."""
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        charge, registre_devis_production(), registre_production().lire(), registre_estime_vs_reel_production()
    )
    return {"traite": True, "wct_id": resultat["wct_id"]}


def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m6.variance_chantier` : n'alimente la partie matériaux que si `statut_variance
    == "evaluee"` (`estime_vs_reel.enregistrer_variance_chantier`) ; les autres statuts sont
    reconnus sans écriture. Laisse volontairement remonter `LookupError` si le wct_id est inconnu
    (ordre d'arrivée inversé, jamais un cas normal) : le répartiteur réessaie puis met en
    quarantaine, comme toute panne de consommateur."""
    resultat = estime_vs_reel.enregistrer_variance_chantier(charge, registre_estime_vs_reel_production())
    if resultat is None:
        return {"traite": True, "ignore_statut": charge["statut_variance"]}
    return {"traite": True, "wct_id": resultat["wct_id"]}


def lire_ecarts_estime_reel(
    devis_id: str | None = None, depuis: str | None = None, jusqua: str | None = None
) -> dict[str, Any]:
    return depuis_couple(
        estime_vs_reel.lire_ecarts(registre_estime_vs_reel_production(), devis_id, depuis, jusqua)
    )


def consommateurs() -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    return {
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m6.variance_chantier": _recevoir_variance_chantier,
    }


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
        Outil(
            nom="m3_creer_devis",
            description=(
                "Crée un devis BROUILLON (PLAN T2.3-a) sur le registre dédié des devis, distinct du "
                "registre d'estimations. Le prix de chaque ligne est TOUJOURS calculé par le code, "
                "jamais fourni : prix_unitaire = cout_unitaire x (1 + taux_marge) arrondi au cent, "
                "puis prix_ligne = prix_unitaire x quantite, arrondi une seconde fois — même ordre "
                "que la facture M5 recalculera. Les totaux sont recalculés depuis les lignes ; un "
                "prix_total fourni qui diffère est rejeté. "
                "Idempotente par devis_id : un second appel identique est un no-op, un contenu "
                "différent est rejeté. Écriture interne non finale (T1) : n'envoie rien au client."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"},
                    "lead_id": {"type": "string", "description": "lien avec le lead M2"},
                    "chantier_id": {"type": ["string", "null"], "description": "chantier M4, si déjà connu"},
                    "lignes": {"type": "array", "items": _LIGNE_DEVIS, "minItems": 1},
                    "taux_marge": {
                        "type": "string",
                        "description": "texte décimal, ex. \"0.35\" pour 35 % — jamais codé en dur",
                    },
                    "horodatage": {"type": "string"},
                    "prix_total": {
                        "type": ["string", "null"],
                        "description": (
                            "Optionnel : contrôle défensif, doit correspondre exactement au total "
                            "recalculé depuis les lignes, sinon rejet."
                        ),
                    },
                },
                "required": ["devis_id", "lead_id", "chantier_id", "lignes", "taux_marge", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_devis,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m3_lire_devis",
            description=(
                "Lit l'état courant d'un devis par devis_id (registre durable, relu à chaque appel, "
                "jamais mis en cache). role=\"employe\" retire coût, marge ET prix (séparation "
                "coût/prix, audit M3) ; role=\"interne\" (défaut) rend la vue complète."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"},
                    "role": {"type": "string", "enum": ["interne", "employe"]},
                },
                "required": ["devis_id"],
                "additionalProperties": False,
            },
            fonction=lire_devis,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_marquer_devis_accepte",
            description=(
                "Marque un devis (brouillon ou envoyé) ACCEPTE et publie m3.devis_accepte dans la "
                "même transaction. T3 (frontière humaine, AGENTS.md) : l'acceptation du client est "
                "un engagement externe — approbateur doit être un humain qui CONSTATE l'acceptation "
                "réelle (signature, courriel, appel), jamais déduite. L'ENVOI du devis au client "
                "n'est pas un outil exposé (action externe, ira derrière les approbations du socle "
                "en T1.3) : marquer_devis_accepte accepte donc aussi depuis brouillon."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"},
                    "approbateur": {"type": "string", "description": "humain qui constate l'acceptation"},
                    "horodatage": {"type": "string"},
                },
                "required": ["devis_id", "approbateur", "horodatage"],
                "additionalProperties": False,
            },
            fonction=marquer_devis_accepte,
            autonomie=Autonomie.T3,
        ),
        Outil(
            nom="m3_lire_ecarts_estime_reel",
            description=(
                "Rend les écarts estimé-vs-réel (PLAN T1.2-d) pour un devis_id ou sur une période "
                "[depuis, jusqua[ (horodatage_completion, ISO-8601 avec fuseau) — au moins un des "
                "deux requis. Par WCT : main_doeuvre (durée réelle vs estimée, écart relatif, ou un "
                "verdict nommé si la durée estimée est introuvable) et materiaux (lignes de "
                "variance M6 telles quelles, absentes tant qu'aucune variance evaluee n'est reçue). "
                "Lecture pure (T0), aucun barème ajusté."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": ["string", "null"]},
                    "depuis": {"type": ["string", "null"], "description": "borne incluse, ISO-8601 avec fuseau"},
                    "jusqua": {"type": ["string", "null"], "description": "borne exclue, ISO-8601 avec fuseau"},
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=lire_ecarts_estime_reel,
            autonomie=Autonomie.T0,
        ),
    )
