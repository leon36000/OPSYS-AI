"""Réception du contrat ``BesoinsMateriauxM3`` (M3 -> M6) — PLAN T2.3-e, DEFINITION-PRODUIT.md §6
(flux des matériaux) et §7 M6.4 (« Besoins matériaux depuis M3 : items, quantités estimées, unité,
facteur de perte, confiance »).

Validation du RÉCEPTEUR, indépendante de celle de l'émetteur (``m3_estimation.besoins_materiaux``) :
M6 ne lui fait pas confiance parce qu'elle vient de M3, comme M2 et M3 le font pour ``LeadQualifie``
(``docs/bmad/03-ARCHITECTURE.md`` de M3 §2.9). Aucune constante n'est importée du voisin (#109) : les
clés ci-dessous sont une COPIE ÉPINGLÉE, confrontée à l'architecture et à la source de l'émetteur par
le gate de cohérence de M3 (DA-M3-10). Le contrat, l'événement du catalogue
(``m3.besoins_materiaux``) et ce validateur se resserrent l'un l'autre : le schéma du catalogue est
la première barrière (structure), ce module la seconde (sens : décimaux stricts, doublons, cohérence
du signal de perte, frontières).

Module pur (aucun import ``opsys``) : l'adaptateur ``outils.py::_recevoir_besoins_materiaux`` fait
les entrées-sorties, ``besoins_prevus.py`` range le prévu.

Ce que M6 fait d'un contrat valide : le range comme prévu PROVISOIRE du devis (``besoins_prevus.py``,
source ``estimation_m3``), jamais un second registre. Ce que M6 n'en fait JAMAIS : un bon de commande.
Un PO reste un brouillon calculé à la demande, soumis à approbation (``bons_commande.py``, T2.4/T2.5).

``facteur_perte`` est conservé tel que reçu (texte, dans ``detail_lignes`` du prévu), sans être
appliqué : ``quantite_estimee`` reste la quantité NETTE de M3. Majorer la quantité à commander par le
facteur de perte est une décision d'achat, pas de réception.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from . import contrats

__all__ = [
    "CHAMPS_BESOINS_MATERIAUX_RECUS",
    "CHAMPS_LIGNE_BESOINS_OPTIONNELS",
    "CHAMPS_LIGNE_BESOINS_REQUIS",
    "CLES_PRIX_ET_COUT_INTERDITES",
    "TYPE_EVENEMENT_BESOINS_MATERIAUX",
    "identite_materiau",
    "lignes_detaillees",
    "lignes_prevues",
    "valider",
]

TYPE_EVENEMENT_BESOINS_MATERIAUX = "m3.besoins_materiaux"

# Copie épinglée du contrat émis par M3 (clés du bloc BesoinsMateriauxM3 de l'architecture). Un
# frozenset, comme les autres CHAMPS_* de M6 (contrats.py) : des noms de propriétés, pas un énuméré
# de domaine qui appellerait une échappatoire INDETERMINE.
CHAMPS_BESOINS_MATERIAUX_RECUS = frozenset(
    {
        "devis_id",
        "lead_id",
        "estimation_id",
        "rang_registre",
        "bareme_version",
        "niveau_confiance",
        "lignes",
        "facteurs_perte_absents",
    }
)
CHAMPS_LIGNE_BESOINS_REQUIS = frozenset({"materiau", "quantite_estimee", "unite"})
CHAMPS_LIGNE_BESOINS_OPTIONNELS = frozenset({"sku", "facteur_perte"})

# M6 ne reçoit AUCUN prix ni coût de M3 : il a son propre livre de prix (T2.4). En plus des mots de
# frontière de domaine de M6 (contrats.MOTS_INTERDITS_DOMAINE), ces clés sont refusées à toute
# profondeur — y compris l'intervalle de coût d'EstimationV1, dont les bornes sont des coûts. Copie
# épinglée de CLES_PRIX_ET_COUT_INTERDITES de l'émetteur : le gate de M3 exige les deux ensembles égaux.
CLES_PRIX_ET_COUT_INTERDITES = frozenset(
    {
        "prix",
        "prix_unitaire",
        "prix_ligne",
        "prix_total",
        "prix_recommande",
        "cout",
        "cout_unitaire",
        "cout_ligne",
        "cout_total",
        "cout_unitaire_min",
        "cout_unitaire_max",
        "montant",
        "marge",
        "taux_marge",
        "intervalle_confiance",
        "borne_basse",
        "borne_haute",
        "plancher_rentable",
        "date_execution",
        "creneau",
        "duree",
    }
)

_MOTIF_DECIMAL = re.compile(r"[0-9]+(\.[0-9]+)?")
_MOTIF_EMPREINTE = re.compile(r"[0-9a-f]{64}")
_LONGUEUR_MAX_DECIMAL = 40


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _decimal_strict(valeur: Any) -> Decimal | None:
    """Décimal ASCII non signé, sinon ``None`` (ni exposant, ni espace, ni signe, ni chiffres non
    ASCII, ni ``NaN`` : ce que ``Decimal(str)`` accepterait de trop)."""
    if not isinstance(valeur, str) or len(valeur) > _LONGUEUR_MAX_DECIMAL:
        return None
    if _MOTIF_DECIMAL.fullmatch(valeur) is None:
        return None
    return Decimal(valeur)


def _cle_interdite(objet: Any) -> bool:
    if isinstance(objet, dict):
        for cle, valeur in objet.items():
            if isinstance(cle, str):
                normalisee = cle.strip().lower()
                if normalisee in CLES_PRIX_ET_COUT_INTERDITES or normalisee in contrats.MOTS_INTERDITS_DOMAINE:
                    return True
            if _cle_interdite(valeur):
                return True
    elif isinstance(objet, (list, tuple)):
        return any(_cle_interdite(element) for element in objet)
    return False


def identite_materiau(ligne: dict[str, Any]) -> str:
    """L'identifiant du matériau pour M6 : le SKU du catalogue quand M3 le connaît, sinon la
    désignation de M3. Jamais deviné : c'est l'une des deux valeurs reçues."""
    return ligne["sku"] if "sku" in ligne else ligne["materiau"]


def valider(charge: Any) -> tuple[bool, str | None]:
    """``(True, None)`` si le contrat est acceptable, sinon ``(False, code)`` — première faute
    gagnante, dans cet ordre : frontières (prix, coût, dates) -> structure -> identifiants ->
    confiance -> lignes -> quantités -> facteurs de perte -> doublons -> signal des pertes absentes.
    Aucune exception ne s'échappe : un contrat malformé est un refus nommé, jamais un plantage."""
    if not isinstance(charge, dict):
        return False, "REJ-BESOINS-MATERIAUX-STRUCTURE-INVALIDE"
    if _cle_interdite(charge):
        return False, "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE"
    if set(charge) != CHAMPS_BESOINS_MATERIAUX_RECUS:
        return False, "REJ-BESOINS-MATERIAUX-STRUCTURE-INVALIDE"

    for champ in ("devis_id", "lead_id", "bareme_version"):
        if not _texte_non_vide(charge[champ]):
            return False, "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE"
    estimation_id = charge["estimation_id"]
    if not isinstance(estimation_id, str) or _MOTIF_EMPREINTE.fullmatch(estimation_id) is None:
        return False, "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE"
    rang = charge["rang_registre"]
    if isinstance(rang, bool) or not isinstance(rang, int) or rang < 0:
        return False, "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE"

    niveau = charge["niveau_confiance"]
    if isinstance(niveau, bool) or not isinstance(niveau, (int, float)) or not 0 < niveau < 1:
        return False, "REJ-BESOINS-MATERIAUX-CONFIANCE-INVALIDE"

    lignes = charge["lignes"]
    if not isinstance(lignes, list) or not lignes:
        return False, "REJ-BESOINS-MATERIAUX-LIGNES-VIDES"

    libelles: set[str] = set()
    identites: set[str] = set()
    sans_facteur: list[str] = []
    for ligne in lignes:
        if (
            not isinstance(ligne, dict)
            or not set(ligne) >= CHAMPS_LIGNE_BESOINS_REQUIS
            or not set(ligne) <= CHAMPS_LIGNE_BESOINS_REQUIS | CHAMPS_LIGNE_BESOINS_OPTIONNELS
        ):
            return False, "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE"
        if not _texte_non_vide(ligne["materiau"]) or not _texte_non_vide(ligne["unite"]):
            return False, "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE"
        if "sku" in ligne and not _texte_non_vide(ligne["sku"]):
            return False, "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE"
        quantite = _decimal_strict(ligne["quantite_estimee"])
        if quantite is None or quantite <= 0:
            return False, "REJ-BESOINS-MATERIAUX-QUANTITE-INVALIDE"
        if "facteur_perte" in ligne:
            facteur = _decimal_strict(ligne["facteur_perte"])
            if facteur is None or facteur >= 1:
                return False, "REJ-BESOINS-MATERIAUX-FACTEUR-PERTE-INVALIDE"
        else:
            sans_facteur.append(ligne["materiau"])
        identite = identite_materiau(ligne)
        if ligne["materiau"] in libelles or identite in identites:
            # Fail-closed : agréger deux lignes du même matériau inventerait une quantité que
            # personne n'a fournie telle quelle (même règle que REJ-BESOIN-CHANTIER-DUPLIQUE).
            return False, "REJ-BESOINS-MATERIAUX-DUPLIQUE"
        libelles.add(ligne["materiau"])
        identites.add(identite)

    signales = charge["facteurs_perte_absents"]
    if not isinstance(signales, list) or signales != sans_facteur:
        return False, "REJ-BESOINS-MATERIAUX-PERTE-NON-SIGNALEE"
    return True, None


def lignes_prevues(charge: dict[str, Any]) -> list[dict[str, Any]]:
    """Le prévu au format INTERNE de M6 (``contrats.CHAMPS_BESOIN_ESTIME_CHANTIER`` : ``materiau_id``,
    ``quantite_estimee``, ``unite``), tiré d'un contrat DÉJÀ validé. Le nombre est converti en
    ``float`` ICI, à l'entrée — seul format que ``variance_chantier`` accepte ; la valeur exacte
    (texte décimal) reste dans ``lignes_detaillees``."""
    return [
        {
            "materiau_id": identite_materiau(ligne),
            "quantite_estimee": float(Decimal(ligne["quantite_estimee"])),
            "unite": ligne["unite"],
        }
        for ligne in charge["lignes"]
    ]


def lignes_detaillees(charge: dict[str, Any]) -> list[dict[str, Any]]:
    """Les lignes reçues, telles quelles (textes décimaux exacts, désignation, SKU, facteur de perte
    s'ils sont fournis), avec l'identifiant de M6 en plus. Conservées pour la traçabilité et pour
    l'achat : ni la désignation ni le facteur de perte n'ont de place dans le prévu interne."""
    return [{"materiau_id": identite_materiau(ligne), **ligne} for ligne in charge["lignes"]]
