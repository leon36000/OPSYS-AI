"""Contrat de sortie ``BesoinsMateriauxM3`` v1 (PLAN T2.3-e) : les besoins matériaux que M3 envoie
à M6 (DEFINITION-PRODUIT.md §6, flux des matériaux ; §7 M3 « Renvoie ... à M6 (besoins matériaux :
items, quantités estimées, facteur de perte, confiance) » ; §7 M6.4).

Avant ce module, M3 n'émettait rien de tel : ``m3.devis_accepte`` porte matériau, quantité et unité,
mais ni facteur de perte ni confiance, et seulement à l'acceptation. M6 ne pouvait donc pas préparer
un achat à partir d'une estimation. Le contrat est publié sur le bus (``m3.besoins_materiaux``,
catalogue du socle) dès qu'une estimation NON bloquée produit des quantités, sans attendre le devis.

Module pur (ADR-0009, même règle que ``devis_durable.py``/``estimation.py``) : aucun import
``opsys``, aucune horloge, aucun réseau. C'est ``outils.py``, seul, qui publie sur le bus.

D'où viennent les quantités. Le code calcule, jamais un modèle : chaque poste du barème
(``BaremeCouts``, fourni par l'appelant, jamais codé en dur) PEUT porter une liste OPTIONNELLE
``materiaux`` (même logique que ``duree_minutes_par_unite``, ``estimation.py``) :

    postes: {<type_travaux>: {..., materiaux: [
        {materiau: str, sku: str (optionnel), quantite_par_unite: texte décimal > 0,
         unite: str, facteur_perte: texte décimal, 0 <= f < 1 (optionnel)}]}}

    quantite_estimee = quantite (l'ouvrage estimé) x quantite_par_unite   # Decimal, texte

``quantite_estimee`` est NETTE (avant perte). Le contrat ne porte JAMAIS la quantité brute : c'est
le récepteur qui applique ``facteur_perte`` s'il le décide (une quantité dérivée portée à côté de ses
deux facteurs pourrait diverger d'eux). ``facteur_perte`` est une fraction de la quantité nette
(``0.10`` = 10 %, brut = net x (1 + f)) ; une valeur >= 1 est refusée, parce qu'elle trahit presque
toujours un pourcentage écrit en entier (``10`` au lieu de ``0.10``) et ferait commander onze fois la
quantité nette.

Absent du poste du barème, ``facteur_perte`` reste ABSENT de la ligne du contrat, jamais inventé ni
mis à zéro, et le fait est SIGNALÉ : ``facteurs_perte_absents`` liste les ``materiau`` concernés (le
validateur exige que cette liste soit exactement celle des lignes sans ``facteur_perte``). Un poste
sans ``materiaux`` ne produit AUCUN besoin (``calculer_lignes`` rend ``(None, None)``) : M3 n'invente
pas de nomenclature. Un bloc ``materiaux`` PRÉSENT mais malformé est un rejet NOMMÉ
(``REJ-BESOINS-MATERIAUX-INVALIDE``), jamais ignoré en silence.

Aucun prix ni coût : M6 a son propre livre de prix (PLAN T2.4). Le validateur refuse, récursivement,
toute clé de prix, de coût, de marge ou d'intervalle de coût (``CLES_PRIX_ET_COUT_INTERDITES``) : le
contrat ne peut pas devenir un second canal par lequel la marge sort de M3 (séparation coût/prix,
``docs/departements/M3-audit.md`` §2.1).

``niveau_confiance`` reprend la forme du CODE : le nombre (niveau statistique du Monte Carlo) que
``EstimationV1.niveau_confiance`` porte déjà, jamais la chaîne du PRD. La divergence code/PRD n'est
PAS tranchée ici (``estimation.py``, docstring du module) ; la question reste ouverte.

Version d'estimation et idempotence. ``estimation_id`` est le ``hash_maillon`` du maillon du
registre M3 qui porte ces besoins (le même que ``EstimationV1.hash_maillon``) : chaque estimation
inscrite est une version, et ce hash couvre les quantités elles-mêmes. ``rang_registre`` est le rang
de ce maillon : un ordre total et monotone des versions, que le récepteur utilise pour ignorer une
version périmée arrivée en retard. ``identifiant_evenement`` rend l'``evenement_id`` déterministe
``m3-besoins-materiaux-<devis_id>-<estimation_id[:16]>`` : republier la MÊME version d'un devis est un
no-op du bus, une NOUVELLE estimation du même devis est une nouvelle version.
"""

from __future__ import annotations

import re
from decimal import Context, Decimal, DecimalException, Inexact, InvalidOperation, Overflow
from typing import Any

from . import verdicts

__all__ = [
    "CHAMPS_BESOINS_MATERIAUX_V1",
    "CHAMPS_LIGNE_BESOINS_OPTIONNELS",
    "CHAMPS_LIGNE_BESOINS_REQUIS",
    "CHAMPS_MATERIAU_BAREME_OPTIONNELS",
    "CHAMPS_MATERIAU_BAREME_REQUIS",
    "CLES_PRIX_ET_COUT_INTERDITES",
    "TYPE_EVENEMENT_BESOINS_MATERIAUX",
    "assembler_besoins_materiaux",
    "calculer_lignes",
    "identifiant_evenement",
    "valider_besoins_materiaux",
]

TYPE_EVENEMENT_BESOINS_MATERIAUX = "m3.besoins_materiaux"

# Clés du contrat, dans l'ordre de l'architecture (docs/bmad/03-ARCHITECTURE.md §2.9). Le gate de
# cohérence confronte ce tuple au bloc yaml de l'architecture ET à la copie indépendante du
# récepteur (M6, ``besoins_materiaux_recus.py``) : une copie qu'on ne confronte pas dérive.
CHAMPS_BESOINS_MATERIAUX_V1 = (
    "devis_id",
    "lead_id",
    "estimation_id",
    "rang_registre",
    "bareme_version",
    "niveau_confiance",
    "lignes",
    "facteurs_perte_absents",
)
CHAMPS_LIGNE_BESOINS_REQUIS = ("materiau", "quantite_estimee", "unite")
CHAMPS_LIGNE_BESOINS_OPTIONNELS = ("sku", "facteur_perte")

# Entrée d'une liste ``materiaux`` du barème (poste par type de travaux).
CHAMPS_MATERIAU_BAREME_REQUIS = ("materiau", "quantite_par_unite", "unite")
CHAMPS_MATERIAU_BAREME_OPTIONNELS = ("sku", "facteur_perte")

# Clés qui ne doivent JAMAIS apparaître dans ce contrat, à aucune profondeur : prix, coût, marge et
# l'intervalle de coût d'EstimationV1 (ses bornes sont des coûts), plus les clés de dates de M4.
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
_LONGUEUR_ID_EVENEMENT = 16

# Contexte de calcul sans arrondi silencieux : un produit qui ne tiendrait pas exactement est un
# rejet, jamais un chiffre tronqué en douce (contexte par défaut de decimal : 28 chiffres).
_CONTEXTE_EXACT = Context(prec=60, traps=[Inexact, InvalidOperation, Overflow])


def _rejet(detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict("REJ-BESOINS-MATERIAUX-INVALIDE", detail=detail)


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _decimal_strict(valeur: Any) -> Decimal | None:
    """Décimal ASCII non signé (``12``, ``0.125``), sinon ``None`` : ni exposant, ni espace, ni
    signe, ni chiffres non ASCII, ni ``NaN`` — ce que ``Decimal(str)`` accepterait de trop."""
    if not isinstance(valeur, str) or len(valeur) > _LONGUEUR_MAX_DECIMAL:
        return None
    if _MOTIF_DECIMAL.fullmatch(valeur) is None:
        return None
    return Decimal(valeur)


def _texte_decimal(valeur: Decimal) -> str:
    """Texte décimal canonique : notation positionnelle, sans zéros de fin (``60``, ``0.5``)."""
    texte = format(valeur, "f")
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return texte


def _cle_interdite(objet: Any) -> str | None:
    """Première clé de prix/coût/date trouvée, à toute profondeur, ou ``None``."""
    if isinstance(objet, dict):
        for cle, valeur in objet.items():
            if isinstance(cle, str) and cle.strip().lower() in CLES_PRIX_ET_COUT_INTERDITES:
                return cle
            trouvee = _cle_interdite(valeur)
            if trouvee is not None:
                return trouvee
    elif isinstance(objet, (list, tuple)):
        for element in objet:
            trouvee = _cle_interdite(element)
            if trouvee is not None:
                return trouvee
    return None


def _valider_entree_bareme(index: int, entree: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Valide UNE entrée de ``materiaux`` du barème ; rend ses champs décodés ou un rejet."""
    prefixe = f"barème, materiaux[{index}]"
    if not isinstance(entree, dict):
        return None, _rejet(f"{prefixe} : un objet est attendu")
    requis = set(CHAMPS_MATERIAU_BAREME_REQUIS)
    connus = requis | set(CHAMPS_MATERIAU_BAREME_OPTIONNELS)
    manquantes = sorted(requis - set(entree))
    inconnues = sorted(set(entree) - connus)
    if manquantes or inconnues:
        return None, _rejet(f"{prefixe} : clés manquantes {manquantes}, clés inconnues {inconnues}")
    for champ in ("materiau", "unite"):
        if not _texte_non_vide(entree[champ]):
            return None, _rejet(f"{prefixe} : {champ} doit être un texte non vide")
    if "sku" in entree and not _texte_non_vide(entree["sku"]):
        return None, _rejet(f"{prefixe} : sku doit être un texte non vide s'il est fourni")
    par_unite = _decimal_strict(entree["quantite_par_unite"])
    if par_unite is None or par_unite <= 0:
        return None, _rejet(
            f"{prefixe} : quantite_par_unite doit être un texte décimal strictement positif "
            "(jamais un nombre JSON)"
        )
    facteur = None
    if "facteur_perte" in entree:
        facteur = _decimal_strict(entree["facteur_perte"])
        if facteur is None or facteur >= 1:
            return None, _rejet(
                f"{prefixe} : facteur_perte doit être un texte décimal, 0 <= f < 1 "
                "(0.10 = 10 %, jamais 10)"
            )
    return {"entree": entree, "par_unite": par_unite, "facteur_perte": facteur}, None


def calculer_lignes(
    bareme: Any, type_travaux: str, quantite: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Lignes de besoins d'un ouvrage de ``quantite`` unités, depuis ``materiaux`` du poste du barème.

    ``(None, None)`` : le poste ne porte pas de ``materiaux`` — aucun besoin, rien d'inventé.
    ``({"lignes": [...], "facteurs_perte_absents": [...]}, None)`` : besoins calculés (Decimal,
    textes décimaux canoniques). ``(None, verdict)`` : bloc ``materiaux`` malformé, ou quantité
    inexploitable — un rejet nommé, jamais une exception.
    """
    postes = bareme.get("postes") if isinstance(bareme, dict) else None
    poste = postes.get(type_travaux) if isinstance(postes, dict) else None
    if not isinstance(poste, dict) or "materiaux" not in poste:
        return None, None

    materiaux = poste["materiaux"]
    if not isinstance(materiaux, list) or not materiaux:
        return None, _rejet("barème : materiaux doit être une liste non vide (ou absent)")

    if isinstance(quantite, bool) or not isinstance(quantite, (int, float, Decimal)):
        return None, _rejet("quantité de l'ouvrage non numérique")
    try:
        quantite_decimale = quantite if isinstance(quantite, Decimal) else Decimal(str(quantite))
    except InvalidOperation:
        return None, _rejet("quantité de l'ouvrage non convertible en Decimal")
    if not quantite_decimale.is_finite() or quantite_decimale <= 0:
        return None, _rejet("quantité de l'ouvrage : un nombre fini strictement positif est exigé")

    lignes: list[dict[str, Any]] = []
    absents: list[str] = []
    libelles: set[str] = set()
    identites: set[str] = set()
    for index, entree in enumerate(materiaux):
        decodee, verdict = _valider_entree_bareme(index, entree)
        if verdict is not None:
            return None, verdict
        brute = decodee["entree"]
        identite = brute.get("sku", brute["materiau"])
        if brute["materiau"] in libelles or identite in identites:
            return None, _rejet(
                f"barème, materiaux[{index}] : matériau {identite!r} en double "
                "(agréger en silence inventerait une quantité)"
            )
        libelles.add(brute["materiau"])
        identites.add(identite)
        try:
            produit = _CONTEXTE_EXACT.multiply(quantite_decimale, decodee["par_unite"])
        except DecimalException:
            return None, _rejet(f"barème, materiaux[{index}] : produit quantité x quantite_par_unite inexact")
        ligne: dict[str, Any] = {"materiau": brute["materiau"]}
        if "sku" in brute:
            ligne["sku"] = brute["sku"]
        ligne["quantite_estimee"] = _texte_decimal(produit)
        ligne["unite"] = brute["unite"]
        if decodee["facteur_perte"] is not None:
            ligne["facteur_perte"] = brute["facteur_perte"]
        else:
            absents.append(brute["materiau"])
        lignes.append(ligne)
    return {"lignes": lignes, "facteurs_perte_absents": absents}, None


def valider_besoins_materiaux(charge: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validation STRICTE côté émetteur : ``(charge, None)`` ou ``(None, verdict)``, première faute
    gagnante. Le récepteur (M6) refait la sienne, indépendamment — une seule des deux validations
    ne suffirait pas à garder le contrat."""
    if not isinstance(charge, dict):
        return None, _rejet("le contrat doit être un objet")
    interdite = _cle_interdite(charge)
    if interdite is not None:
        return None, _rejet(f"clé interdite {interdite!r} : ce contrat ne porte ni prix, ni coût, ni date")
    manquantes = sorted(set(CHAMPS_BESOINS_MATERIAUX_V1) - set(charge))
    inconnues = sorted(set(charge) - set(CHAMPS_BESOINS_MATERIAUX_V1))
    if manquantes or inconnues:
        return None, _rejet(f"clés manquantes {manquantes}, clés inconnues {inconnues}")

    for champ in ("devis_id", "lead_id", "bareme_version"):
        if not _texte_non_vide(charge[champ]):
            return None, _rejet(f"{champ} doit être un texte non vide")
    estimation_id = charge["estimation_id"]
    if not isinstance(estimation_id, str) or _MOTIF_EMPREINTE.fullmatch(estimation_id) is None:
        return None, _rejet("estimation_id doit être une empreinte sha256 en hexadécimal minuscule (64 signes)")
    rang = charge["rang_registre"]
    if isinstance(rang, bool) or not isinstance(rang, int) or rang < 0:
        return None, _rejet("rang_registre doit être un entier >= 0")
    niveau = charge["niveau_confiance"]
    if isinstance(niveau, bool) or not isinstance(niveau, (int, float)) or not 0 < niveau < 1:
        return None, _rejet("niveau_confiance doit être un nombre strictement entre 0 et 1")

    lignes = charge["lignes"]
    if not isinstance(lignes, list) or not lignes:
        return None, _rejet("lignes doit être une liste non vide")
    requis = set(CHAMPS_LIGNE_BESOINS_REQUIS)
    connus = requis | set(CHAMPS_LIGNE_BESOINS_OPTIONNELS)
    libelles: set[str] = set()
    identites: set[str] = set()
    sans_facteur: list[str] = []
    for index, ligne in enumerate(lignes):
        if not isinstance(ligne, dict) or not requis <= set(ligne) or not set(ligne) <= connus:
            return None, _rejet(f"lignes[{index}] : clés attendues {sorted(requis)} (+ {sorted(connus - requis)})")
        for champ in ("materiau", "unite"):
            if not _texte_non_vide(ligne[champ]):
                return None, _rejet(f"lignes[{index}] : {champ} doit être un texte non vide")
        if "sku" in ligne and not _texte_non_vide(ligne["sku"]):
            return None, _rejet(f"lignes[{index}] : sku doit être un texte non vide s'il est fourni")
        quantite = _decimal_strict(ligne["quantite_estimee"])
        if quantite is None or quantite <= 0:
            return None, _rejet(f"lignes[{index}] : quantite_estimee doit être un texte décimal strictement positif")
        if "facteur_perte" in ligne:
            facteur = _decimal_strict(ligne["facteur_perte"])
            if facteur is None or facteur >= 1:
                return None, _rejet(f"lignes[{index}] : facteur_perte doit être un texte décimal, 0 <= f < 1")
        else:
            sans_facteur.append(ligne["materiau"])
        identite = ligne.get("sku", ligne["materiau"])
        if ligne["materiau"] in libelles or identite in identites:
            return None, _rejet(f"lignes[{index}] : matériau {identite!r} en double")
        libelles.add(ligne["materiau"])
        identites.add(identite)

    signales = charge["facteurs_perte_absents"]
    if not isinstance(signales, list) or not all(isinstance(element, str) for element in signales):
        return None, _rejet("facteurs_perte_absents doit être une liste de textes")
    if signales != sans_facteur:
        return None, _rejet(
            f"facteurs_perte_absents {signales} diffère des lignes sans facteur_perte {sans_facteur} : "
            "une absence doit être signalée, jamais tue ni inventée"
        )
    return charge, None


def assembler_besoins_materiaux(
    devis_id: Any,
    lead_id: Any,
    estimation_id: Any,
    rang_registre: Any,
    bareme_version: Any,
    niveau_confiance: Any,
    lignes: Any,
    facteurs_perte_absents: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Assemble puis valide le contrat ``BesoinsMateriauxM3`` : ``(contrat, None)`` ou
    ``(None, verdict)``. Les listes sont copiées : le contrat rendu ne partage rien de mutable avec
    l'appelant."""
    charge = {
        "devis_id": devis_id,
        "lead_id": lead_id,
        "estimation_id": estimation_id,
        "rang_registre": rang_registre,
        "bareme_version": bareme_version,
        "niveau_confiance": niveau_confiance,
        "lignes": [dict(ligne) if isinstance(ligne, dict) else ligne for ligne in lignes]
        if isinstance(lignes, list)
        else lignes,
        "facteurs_perte_absents": list(facteurs_perte_absents)
        if isinstance(facteurs_perte_absents, list)
        else facteurs_perte_absents,
    }
    return valider_besoins_materiaux(charge)


def identifiant_evenement(contrat: dict[str, Any]) -> str:
    """``evenement_id`` déterministe d'une version d'estimation d'un devis (idempotence du producteur,
    ``opsys.evenements.publier``) : la même version republiée est un no-op, une nouvelle version
    (autre ``estimation_id``) est un événement distinct. Suppose le contrat déjà validé."""
    return f"m3-besoins-materiaux-{contrat['devis_id']}-{contrat['estimation_id'][:_LONGUEUR_ID_EVENEMENT]}"
