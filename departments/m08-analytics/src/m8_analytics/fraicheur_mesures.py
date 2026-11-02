"""Fraîcheur des MESURES du catalogue : la règle unique que partagent wallboards, score de santé, copilote et pont BI.

Module PUR (ADR-0009) : aucune horloge. ``maintenant`` est donné par l'appelant (M8 n'a pas d'horloge, il ne devine
jamais l'heure) ; sans lui lisible, aucun statut de fraîcheur n'est rendu.

La règle reprend la décision d'architecte r1 (« fraîcheur M8 ») et la fenêtre attendue de ``fraicheur_lectures`` :

* le PRODUCTEUR (M8) déclare, au catalogue, la fenêtre attendue de chaque mesure en secondes (vue exécutive : 24 h) ou
la
  dit ``terminale`` (mesure cumulée de chantiers terminés : non applicable une fois le chantier terminé) ; le
  propriétaire
  peut la resserrer ou la fixer par mesure (``department.yaml``, ``configuration.fraicheur_mesures_s``, vide à la
  livraison : aucune valeur n'y est inventée) ; la CADENCE de la source (D7 : ``cadence_s`` du catalogue, ou
  ``configuration.cadences_mesures_s`` du propriétaire, vide à la livraison) relève la fenêtre au-dessus de 24 h : la
  fenêtre du producteur est ``max(fenetre_s, cadence)``, jamais plus courte que le rythme de la source ;
* l'APPELANT peut demander plus strict (``fraicheur_max_s``) ; le département SOURCE peut déclarer sa propre fenêtre
  (M7 dit combien de temps ses relevés publicitaires restent frais : ``fenetre_source_s`` de la mesure) ; la précédence
  est la PLUS STRICTE des trois, jamais la plus indulgente ;
* l'âge d'une mesure est celui de son dernier fait (``dernier_fait_le``) face à ``maintenant``. M8 ne peut pas
distinguer
  « l'entreprise n'a rien fait » de « le bus n'a rien livré » : un fait trop ancien rend donc la mesure ``perime``, et
  c'est
  au propriétaire de choisir une fenêtre qui convient au rythme de son entreprise.

Statuts : ``a_jour``, ``perime``, ``inconnu`` (aucun instant de fait lisible, instant dans le futur, fenêtre ou horloge
indisponible), ``manquant`` (mesure non calculable : aucune valeur à dater) et ``non_applicable`` (mesure terminale).
Seuls ``a_jour`` et ``non_applicable`` autorisent à montrer la valeur SANS mention : ``peut_etre_montree_comme_a_jour``.
Une mesure périmée, inconnue ou manquante n'est JAMAIS montrée comme à jour.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import entonnoir, fraicheur_lectures

STATUT_A_JOUR = "a_jour"
STATUT_PERIME = "perime"
STATUT_INCONNU = "inconnu"
STATUT_MANQUANT = "manquant"
STATUT_NON_APPLICABLE = "non_applicable"

_STATUTS_SANS_MENTION = frozenset({STATUT_A_JOUR, STATUT_NON_APPLICABLE})

CLE_CONFIGURATION = "fraicheur_mesures_s"
CLE_CADENCES = "cadences_mesures_s"

REJ_MAINTENANT_INVALIDE = "REJ-FRAICHEUR-MAINTENANT-INVALIDE"
REJ_FENETRE_APPELANT_INVALIDE = "REJ-FRAICHEUR-FENETRE-APPELANT-INVALIDE"

ORIGINE_APPELANT = "appelant"
ORIGINE_SOURCE = "source"
ORIGINE_CONFIGURATION = "configuration"
ORIGINE_CATALOGUE = "catalogue"
ORIGINE_CADENCE = "cadence"
ORIGINE_TERMINALE = "terminale"


def lire_maintenant(brut: Any) -> datetime:
    """L'instant de l'appelant : RFC 3339 AVEC fuseau. Absent, illisible ou sans fuseau : refus nommé, jamais une heure
    devinée."""
    instant = entonnoir.instant_lu(brut)
    if instant is None:
        raise ValueError(
            f"{REJ_MAINTENANT_INVALIDE} : maintenant doit être un instant RFC 3339 avec fuseau (reçu {brut!r})"
        )
    return instant


def lire_fenetre_appelant(brut: Any) -> int | None:
    """La fenêtre plus stricte que l'appelant demande, ou ``None`` s'il n'en demande pas. Mêmes bornes que les fenêtres
    du propriétaire (entier de secondes, 1 à 3650 jours) : une valeur invalide est refusée, jamais corrigée."""
    if brut is None:
        return None
    raison = fraicheur_lectures.raison_invalide(brut)
    if raison is not None:
        raise ValueError(f"{REJ_FENETRE_APPELANT_INVALIDE} : fraicheur_max_s : {raison}")
    return brut


def lire_configuration(configuration: Any, catalogue: dict[str, Any]) -> dict[str, Any]:
    """Les fenêtres du propriétaire lues de ``configuration.fraicheur_mesures_s`` : ``{fenetres, refusees, ignorees}``.

    Une valeur invalide est REFUSÉE et dite (aucune fenêtre n'est alors exposée pour cette mesure, jamais corrigée) ;
    une
    clé qui n'est pas une mesure du catalogue est dite (faute de frappe : le propriétaire croirait sa fenêtre en
    place)."""
    connues = {entree["metric_id"] for entree in catalogue["mesures"]}
    fenetres: dict[str, int] = {}
    refusees: list[dict[str, str]] = []
    ignorees: list[str] = []
    if configuration is None:
        return {"fenetres": fenetres, "refusees": refusees, "ignorees": ignorees}
    if not isinstance(configuration, dict):
        return {
            "fenetres": fenetres,
            "ignorees": ignorees,
            "refusees": [{"metric_id": "*", "raison": "un dictionnaire {mesure: secondes} est attendu"}],
        }
    for cle, valeur in configuration.items():
        if cle not in connues:
            ignorees.append(str(cle))
            continue
        raison = fraicheur_lectures.raison_invalide(valeur)
        if raison is not None:
            refusees.append({"metric_id": cle, "raison": raison})
        else:
            fenetres[cle] = valeur
    return {"fenetres": fenetres, "refusees": refusees, "ignorees": sorted(ignorees)}


def fenetre_effective(
    entree: dict[str, Any],
    fenetres_proprietaire: dict[str, int],
    fraicheur_max_s: int | None = None,
    fenetre_source_s: int | None = None,
    cadences_proprietaire: dict[str, int] | None = None,
) -> dict[str, Any]:
    """La fenêtre qui s'applique à une mesure : le producteur, le département source qui déclare la sienne
    (``fenetre_source_s``) et l'appelant, la PLUS STRICTE des trois. À égalité, le producteur garde la main, puis la
    source.
    ``secondes`` vaut ``None`` seulement pour une mesure terminale que ni l'appelant ni la source ne resserrent.

    Le producteur (D7) : la fenêtre que le propriétaire fixe pour la mesure (``configuration.fraicheur_mesures_s``) la
    remplace ; sinon c'est ``max(fenetre_s du catalogue, cadence)``, où la cadence est celle que le propriétaire déclare
    (``configuration.cadences_mesures_s``) ou, à défaut, celle que le catalogue déclare (``null`` : aucune, la fenêtre
    du
    catalogue s'applique). Une source qui publie une fois par semaine n'est pas « périmée » au bout de 24 h : sa fenêtre
    ne peut pas être plus courte que son rythme. Aucune cadence n'est inventée."""
    metric_id = entree["metric_id"]
    if metric_id in fenetres_proprietaire:
        producteur: int | None = fenetres_proprietaire[metric_id]
        origine_producteur = ORIGINE_CONFIGURATION
    elif "fenetre_s" in entree["fraicheur"]:
        producteur = entree["fraicheur"]["fenetre_s"]
        origine_producteur = ORIGINE_CATALOGUE
        cadence = (cadences_proprietaire or {}).get(metric_id, entree["fraicheur"].get("cadence_s"))
        if cadence is not None and cadence > producteur:
            producteur, origine_producteur = cadence, ORIGINE_CADENCE
    else:
        producteur, origine_producteur = None, ORIGINE_TERMINALE
    retenue: dict[str, Any] = {"secondes": producteur, "origine": origine_producteur}
    if fenetre_source_s is not None and (retenue["secondes"] is None or fenetre_source_s < retenue["secondes"]):
        retenue = {"secondes": fenetre_source_s, "origine": ORIGINE_SOURCE}
    if fraicheur_max_s is not None and (retenue["secondes"] is None or fraicheur_max_s < retenue["secondes"]):
        retenue = {"secondes": fraicheur_max_s, "origine": ORIGINE_APPELANT}
    return retenue


def formater_duree(secondes: int) -> str:
    """Une durée lisible en français québécois (« 3 j 4 h », « 2 h 05 min », « 45 s »)."""
    jours, reste = divmod(max(0, secondes), 86400)
    heures, reste = divmod(reste, 3600)
    minutes, sec = divmod(reste, 60)
    if jours:
        return f"{jours} j {heures} h"
    if heures:
        return f"{heures} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {sec:02d} s"
    return f"{sec} s"


def evaluer(mesure: dict[str, Any], maintenant: datetime, fenetre: dict[str, Any]) -> dict[str, Any]:
    """Le statut de fraîcheur d'UNE mesure lue (``moteur_mesures.lire``) à l'instant ``maintenant``."""
    base = {"fenetre_s": fenetre["secondes"], "origine_fenetre": fenetre["origine"], "age_s": None}
    if mesure["statut"] != entonnoir.STATUT_CALCULEE:
        bloquee = (mesure.get("qualite") or {}).get("statut") == "echec"
        return {
            **base,
            "statut": STATUT_MANQUANT,
            "peut_etre_montree_comme_a_jour": False,
            "motif": "mesure bloquée par le contrôle de qualité des données : aucune valeur à dater"
            if bloquee
            else "mesure non calculable : aucune valeur à dater",
        }
    instant = entonnoir.instant_lu(mesure.get("dernier_fait_le"))
    if instant is not None:
        age = int((maintenant - instant).total_seconds())
        base["age_s"] = age if age >= 0 else None
    if fenetre["secondes"] is None:
        return {
            **base,
            "statut": STATUT_NON_APPLICABLE,
            "peut_etre_montree_comme_a_jour": True,
            "motif": "mesure cumulée de chantiers terminés : sa fraîcheur ne se juge pas par l'âge du dernier chantier",
        }
    if instant is None:
        return {
            **base,
            "statut": STATUT_INCONNU,
            "peut_etre_montree_comme_a_jour": False,
            "motif": "aucun instant de fait lisible : l'âge de la mesure est inconnu",
        }
    age = int((maintenant - instant).total_seconds())
    if age < 0:
        return {
            **base,
            "statut": STATUT_INCONNU,
            "peut_etre_montree_comme_a_jour": False,
            "motif": "le dernier fait est daté après l'instant de l'appelant : l'âge est inconnu",
        }
    if age <= fenetre["secondes"]:
        return {
            **base,
            "statut": STATUT_A_JOUR,
            "peut_etre_montree_comme_a_jour": True,
            "motif": f"dernier fait il y a {formater_duree(age)} (fenêtre {formater_duree(fenetre['secondes'])})",
        }
    return {
        **base,
        "statut": STATUT_PERIME,
        "peut_etre_montree_comme_a_jour": False,
        "motif": f"dernier fait il y a {formater_duree(age)}, au-delà de la fenêtre de "
        f"{formater_duree(fenetre['secondes'])}",
    }


def peut_etre_montree_comme_a_jour(statut: str) -> bool:
    return statut in _STATUTS_SANS_MENTION


def lire_mesures_avec_fraicheur(
    mesures: list[dict[str, Any]],
    catalogue: dict[str, Any],
    maintenant: datetime,
    fenetres_proprietaire: dict[str, int],
    fraicheur_max_s: int | None = None,
    cadences_proprietaire: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Les mesures lues, chacune enrichie de sa ``fraicheur`` (statut, âge, fenêtre et son origine, motif). Une seule
    boucle pour toutes les surfaces : aucune ne réinvente la règle."""
    entrees = {entree["metric_id"]: entree for entree in catalogue["mesures"]}
    enrichies = []
    for mesure in mesures:
        fenetre = fenetre_effective(
            entrees[mesure["metric_id"]],
            fenetres_proprietaire,
            fraicheur_max_s,
            mesure.get("fenetre_source_s"),
            cadences_proprietaire,
        )
        enrichies.append({**mesure, "fraicheur": evaluer(mesure, maintenant, fenetre)})
    return enrichies


__all__ = [
    "CLE_CADENCES",
    "CLE_CONFIGURATION",
    "ORIGINE_APPELANT",
    "ORIGINE_CADENCE",
    "ORIGINE_CATALOGUE",
    "ORIGINE_CONFIGURATION",
    "ORIGINE_SOURCE",
    "ORIGINE_TERMINALE",
    "REJ_FENETRE_APPELANT_INVALIDE",
    "REJ_MAINTENANT_INVALIDE",
    "STATUT_A_JOUR",
    "STATUT_INCONNU",
    "STATUT_MANQUANT",
    "STATUT_NON_APPLICABLE",
    "STATUT_PERIME",
    "evaluer",
    "fenetre_effective",
    "formater_duree",
    "lire_configuration",
    "lire_fenetre_appelant",
    "lire_maintenant",
    "lire_mesures_avec_fraicheur",
    "peut_etre_montree_comme_a_jour",
]
