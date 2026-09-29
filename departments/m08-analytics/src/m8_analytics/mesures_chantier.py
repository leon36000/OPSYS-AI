"""Mesures d'un chantier terminé (PLAN T1.5-d ; DEFINITION-PRODUIT.md §6 « travaux terminés » :
« M8 : temps réel vs prévu, marge prévue vs réelle, performance d'équipe » ; flux des matériaux :
« M8 mesure la variance → M9 lit le risque »).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (les instants viennent des faits
reçus). ``outils.py``, seul point de contact avec le socle, lit et écrit les faits et publie les
alertes.

Trois principes, dans l'ordre où le code les applique :

1. GOUVERNÉ. Chaque métrique est définie une seule fois dans ``metrics/m8-metrics.v1.yaml`` (nom,
   formule, source, unité ; garde de devise CAD de ``dictionnaire.py``). ``mesurer_chantier`` ne
   calcule que ce que ce registre définit et porte la version de la définition (empreinte) dans
   chaque mesure. Le code calcule, jamais un modèle.
2. HONNÊTE. Une entrée absente ou illisible donne une mesure ``non_calculable`` qui NOMME ce qui
   manque et sa source (« manque duree_estimee_minutes (M3) »), jamais une valeur inventée ni un
   zéro. M8 ne recalcule ni la finance (marge réelle : reprise de M5), ni le verdict de M6
   (écart de matériaux : repris de ``m6.variance_chantier``).
3. SANS SEUIL INVENTÉ. Une alerte n'existe que si le seuil est configuré (``department.yaml``,
   ``configuration.seuils_alerte``). Sans seuil valide, aucune alerte de franchissement : M8 émet
   un signal « seuil à configurer », qui dit quoi faire. Un franchissement est un CONSTAT chiffré
   (valeur, seuil, sens) et une action proposée : jamais une cause, jamais un responsable.

Faits reçus (un dictionnaire par fait, ajoutés en lecture seule au registre ``faits_chantier`` par
``outils.py``, chacun idempotent) :

- ``wct``      : ``m4.travaux_termines`` (durée réelle, technicien, devis lié) ;
- ``devis``    : ``m3.devis_accepte`` (prix total, coût total et, s'il est fourni, durée estimée) ;
- ``variance`` : ``m6.variance_chantier`` (verdict d'écart de matériaux, ligne par ligne) ;
- ``rentabilite`` : marge réelle rapportée par M5, ``{type_entree, wct_id, marge_reelle_cad}`` en
  texte décimal. M5 ne la publie pas encore : tant qu'aucun fait de ce type n'existe, la marge
  réelle et ses écarts sont « non calculables, manque marge_reelle_cad (M5) ».
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import dictionnaire, encodage

MODULE_DEFINITIONS = "m08-analytics"
METRIQUE_EQUIPE = "m8_ecart_duree_technicien_pct"

TYPE_ALERTE_SEUIL_FRANCHI = "MESURE-SEUIL-FRANCHI"
TYPE_ALERTE_SEUIL_A_CONFIGURER = "MESURE-SEUIL-A-CONFIGURER"

STATUT_CALCULEE = "calculee"
STATUT_NON_CALCULABLE = "non_calculable"

SEUIL_FRANCHI = "franchi"
SEUIL_NON_FRANCHI = "non_franchi"
SEUIL_A_CONFIGURER = "seuil_a_configurer"
SEUIL_INVALIDE = "seuil_invalide"

SENS_AU_DESSUS = "au_dessus"
SENS_AU_DESSOUS = "au_dessous"

_CHEMIN_METRIQUES = Path(__file__).resolve().parents[2] / "metrics" / "m8-metrics.v1.yaml"
_CENTIEME = Decimal("0.01")
_CENT = Decimal("100")
_ZERO = Decimal("0")

# Métriques dont un franchissement de seuil propose une alerte, et département à qui M8 la propose
# (le propriétaire du processus mesuré : M8 NOMME un destinataire, il n'agit sur personne). La
# performance d'équipe n'y figure jamais : aucun employé n'est alerté ni accusé automatiquement.
_DESTINATAIRE_ALERTE = {
    "m8_ecart_duree_pct": "m04-field-ops",
    "m8_ecart_marge_pct": "m05-financecore",
    "m8_ecart_materiaux_max_pct": "m06-material-control",
}
_DESTINATAIRE_CONFIGURATION = "m08-analytics"
_SOURCE_CONFIGURATION = "department.yaml de m08-analytics (configuration.seuils_alerte)"
_UNITES_AFFICHEES = {"pourcentage": "%"}

# champ d'entrée -> (fait qui le porte, clé dans ce fait, source lisible). La source est celle du
# département propriétaire de la donnée : M8 ne la produit pas.
_LOCALISATEURS = {
    "duree_reelle_minutes": ("wct", "duree_reelle_minutes", "M4 (m4.travaux_termines)"),
    "duree_estimee_minutes": ("devis", "duree_estimee_minutes", "M3 (m3.devis_accepte)"),
    "prix_total": ("devis", "prix_total", "M3 (m3.devis_accepte)"),
    "cout_total": ("devis", "cout_total", "M3 (m3.devis_accepte)"),
    "marge_reelle_cad": ("rentabilite", "marge_reelle_cad", "M5 (rentabilité du chantier)"),
}
_SOURCE_VARIANCE = "M6 (m6.variance_chantier)"


# ---------------------------------------------------------------------------
# Registre des définitions gouvernées
# ---------------------------------------------------------------------------
def charger_definitions(chemin: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Définitions de ``metrics/m8-metrics.v1.yaml`` : ``{metric_id: définition}``, dans l'ordre du
    fichier. Fail-closed : un fichier invalide (structure, devise non CAD, doublon) est une erreur,
    jamais un registre partiel qui laisserait passer une métrique non gouvernée."""
    compilees, erreurs = dictionnaire.compiler_fichier(chemin if chemin is not None else _CHEMIN_METRIQUES)
    if erreurs:
        raise ValueError(f"registre des métriques de M8 invalide : {'; '.join(erreurs)}")
    definitions = compilees.get(MODULE_DEFINITIONS)
    if not definitions:
        raise ValueError(f"registre des métriques de M8 vide : aucune métrique du module {MODULE_DEFINITIONS!r}")
    return definitions


# ---------------------------------------------------------------------------
# Faits
# ---------------------------------------------------------------------------
def fait_wct(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m4.travaux_termines`` (clés requises du catalogue) : jamais un coût, jamais
    une marge."""
    return {
        "type_entree": "wct",
        "wct_id": charge["wct_id"],
        "intervention_id": charge["intervention_id"],
        "devis_id": charge.get("devis_id"),
        "technicien_id": charge["technicien_id"],
        "horodatage_completion": charge["horodatage_completion"],
        "duree_reelle_minutes": charge["duree_reelle_minutes"],
        "statut": charge["statut"],
    }


def fait_devis(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m3.devis_accepte`` : prix et coût TELS QUE M3 les a arrêtés (M8 n'en recalcule
    aucun) et la durée estimée SEULEMENT si M3 l'a fournie (clé optionnelle du catalogue)."""
    fait = {
        "type_entree": "devis",
        "devis_id": charge["devis_id"],
        "prix_total": charge["prix_total"],
        "cout_total": charge["cout_total"],
        "horodatage_acceptation": charge["horodatage_acceptation"],
    }
    if "duree_estimee_minutes" in charge:
        fait["duree_estimee_minutes"] = charge["duree_estimee_minutes"]
    return fait


def fait_variance(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m6.variance_chantier`` : le verdict de M6, ligne par ligne, tel quel."""
    return {
        "type_entree": "variance",
        "wct_id": charge["wct_id"],
        "statut_variance": charge["statut_variance"],
        "signal_critique": charge["signal_critique"],
        "seuil_pourcentage": charge["seuil_pourcentage"],
        "lignes": charge["lignes"],
    }


def wcts_du_devis(entrees: list[dict[str, Any]], devis_id: str) -> list[str]:
    """Identifiants des chantiers déjà terminés qui pointent vers ce devis (ordre de réception)."""
    vus: list[str] = []
    for entree in entrees:
        est_du_devis = entree.get("type_entree") == "wct" and entree.get("devis_id") == devis_id
        if est_du_devis and entree["wct_id"] not in vus:
            vus.append(entree["wct_id"])
    return vus


def assembler_faits(wct_id: str, entrees: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Faits d'un chantier, joints par ``wct_id`` (et ``devis_id`` du chantier pour le devis) ;
    ``None`` si le chantier est inconnu (aucun ``m4.travaux_termines`` reçu). Les autres faits
    valent ``None`` tant qu'ils ne sont pas arrivés : l'ordre de livraison du bus n'est pas garanti.
    Une variance ``evaluee`` est terminale (M6) et l'emporte sur les statuts précédents."""
    wct: dict[str, Any] | None = None
    devis_par_id: dict[str, dict[str, Any]] = {}
    variances: list[dict[str, Any]] = []
    rentabilite: dict[str, Any] | None = None
    for entree in entrees:
        type_entree = entree.get("type_entree")
        if type_entree == "wct" and entree.get("wct_id") == wct_id:
            wct = entree
        elif type_entree == "devis":
            devis_par_id[entree["devis_id"]] = entree
        elif type_entree == "variance" and entree.get("wct_id") == wct_id:
            variances.append(entree)
        elif type_entree == "rentabilite" and entree.get("wct_id") == wct_id:
            rentabilite = entree
    if wct is None:
        return None
    variance = next((v for v in variances if v["statut_variance"] == "evaluee"), None)
    if variance is None and variances:
        variance = variances[-1]
    return {
        "wct": wct,
        "devis": devis_par_id.get(wct.get("devis_id")),
        "variance": variance,
        "rentabilite": rentabilite,
    }


# ---------------------------------------------------------------------------
# Arithmétique : Decimal partout, texte à la sortie
# ---------------------------------------------------------------------------
def _decimal(valeur: Any) -> Decimal | None:
    """Décimal fini lu d'un nombre ou d'un texte décimal ; ``None`` sinon (un booléen n'est pas un
    nombre). Jamais une valeur par défaut."""
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        lu = Decimal(str(valeur).strip())
    except InvalidOperation:
        return None
    return lu if lu.is_finite() else None


def _texte(valeur: Decimal) -> str:
    """Texte décimal à deux décimales (ROUND_HALF_UP), sans « -0.00 »."""
    arrondi = valeur.quantize(_CENTIEME, rounding=ROUND_HALF_UP)
    if arrondi == 0:
        arrondi = arrondi.copy_abs()
    return format(arrondi, "f")


def _afficher(valeur: str, unite: str) -> str:
    return f"{valeur} {_UNITES_AFFICHEES.get(unite, unite)}"


# ---------------------------------------------------------------------------
# Entrées d'un calcul : présentes et lisibles, ou manques nommés
# ---------------------------------------------------------------------------
def _raison_fait_absent(faits: dict[str, Any], nom_fait: str) -> str:
    if nom_fait == "devis":
        devis_id = faits["wct"].get("devis_id")
        if devis_id is None:
            return "le chantier n'est lié à aucun devis (devis_id absent du m4.travaux_termines)"
        return f"aucun devis accepté reçu pour {devis_id}"
    return "aucun fait reçu de cette source pour ce chantier"


def _lire_entrees(
    faits: dict[str, Any], champs: tuple[str, ...]
) -> tuple[dict[str, Decimal], list[dict[str, str]]]:
    valeurs: dict[str, Decimal] = {}
    manque: list[dict[str, str]] = []
    for champ in champs:
        nom_fait, cle, source = _LOCALISATEURS[champ]
        fait = faits.get(nom_fait)
        if fait is None:
            manque.append({"champ": champ, "source": source, "raison": _raison_fait_absent(faits, nom_fait)})
            continue
        brute = fait.get(cle)
        if brute is None:
            manque.append({"champ": champ, "source": source, "raison": "absent du fait reçu"})
            continue
        lue = _decimal(brute)
        if lue is None:
            manque.append({"champ": champ, "source": source, "raison": f"valeur illisible : {brute!r}"})
            continue
        valeurs[champ] = lue
    return valeurs, manque


def _manque_specifique(champ: str, raison: str) -> dict[str, str]:
    return {"champ": champ, "source": _LOCALISATEURS[champ][2], "raison": raison}


# ---------------------------------------------------------------------------
# Calculs : (valeur | None, entrées lues, manques)
# ---------------------------------------------------------------------------
Resultat = tuple[Decimal | None, dict[str, Any], list[dict[str, str]]]


def _ecart_duree_minutes(faits: dict[str, Any]) -> Resultat:
    v, manque = _lire_entrees(faits, ("duree_reelle_minutes", "duree_estimee_minutes"))
    if manque:
        return None, v, manque
    return v["duree_reelle_minutes"] - v["duree_estimee_minutes"], v, []


def _ecart_duree_pct(faits: dict[str, Any]) -> Resultat:
    v, manque = _lire_entrees(faits, ("duree_reelle_minutes", "duree_estimee_minutes"))
    if manque:
        return None, v, manque
    estimee = v["duree_estimee_minutes"]
    if estimee <= 0:
        return None, v, [_manque_specifique("duree_estimee_minutes", "doit être strictement positive")]
    return (v["duree_reelle_minutes"] - estimee) / estimee * _CENT, v, []


def _marge_prevue_cad(faits: dict[str, Any]) -> Resultat:
    v, manque = _lire_entrees(faits, ("prix_total", "cout_total"))
    if manque:
        return None, v, manque
    return v["prix_total"] - v["cout_total"], v, []


def _marge_reelle_cad(faits: dict[str, Any]) -> Resultat:
    v, manque = _lire_entrees(faits, ("marge_reelle_cad",))
    if manque:
        return None, v, manque
    return v["marge_reelle_cad"], v, []


def _ecart_marge_cad(faits: dict[str, Any]) -> Resultat:
    v, manque = _lire_entrees(faits, ("prix_total", "cout_total", "marge_reelle_cad"))
    if manque:
        return None, v, manque
    return v["marge_reelle_cad"] - (v["prix_total"] - v["cout_total"]), v, []


def _ecart_marge_pct(faits: dict[str, Any]) -> Resultat:
    v, manque = _lire_entrees(faits, ("prix_total", "cout_total", "marge_reelle_cad"))
    if manque:
        return None, v, manque
    prevue = v["prix_total"] - v["cout_total"]
    if prevue == 0:
        return None, v, [_manque_specifique("prix_total", "marge prévue nulle : écart relatif indéfini")]
    return (v["marge_reelle_cad"] - prevue) / prevue * _CENT, v, []


def _ecart_materiaux_max_pct(faits: dict[str, Any]) -> Resultat:
    variance = faits.get("variance")
    if variance is None:
        return None, {}, [{
            "champ": "variance_chantier", "source": _SOURCE_VARIANCE,
            "raison": "M6 n'a publié aucune variance pour ce chantier",
        }]
    if variance["statut_variance"] != "evaluee":
        return None, {}, [{
            "champ": "variance_chantier", "source": _SOURCE_VARIANCE,
            "raison": f"statut de la variance : {variance['statut_variance']} (evaluee attendu)",
        }]
    definis = []
    for ligne in variance["lignes"] or []:
        ecart = _decimal(ligne.get("ecart_pourcentage"))
        if ecart is not None:
            definis.append((ecart, ligne))
    if not definis:
        return None, {}, [{
            "champ": "variance_chantier", "source": _SOURCE_VARIANCE,
            "raison": "aucun matériau avec un écart défini",
        }]
    ecart_max, ligne = max(definis, key=lambda paire: paire[0])
    entrees = {
        "materiau": ligne["materiau"],
        "quantite_prevue": ligne["quantite_prevue"],
        "quantite_reelle": ligne["quantite_reelle"],
        "signal_critique_m6": variance["signal_critique"],
    }
    return ecart_max * _CENT, entrees, []


_CALCULS = {
    "m8_ecart_duree_minutes": _ecart_duree_minutes,
    "m8_ecart_duree_pct": _ecart_duree_pct,
    "m8_marge_prevue_cad": _marge_prevue_cad,
    "m8_marge_reelle_cad": _marge_reelle_cad,
    "m8_ecart_marge_cad": _ecart_marge_cad,
    "m8_ecart_marge_pct": _ecart_marge_pct,
    "m8_ecart_materiaux_max_pct": _ecart_materiaux_max_pct,
}


def _detail_manque(manque: list[dict[str, str]]) -> str:
    morceaux = "; ".join(f"{m['champ']} — {m['source']} : {m['raison']}" for m in manque)
    return f"non calculable, manque {morceaux}"


def _entrees_en_texte(entrees: dict[str, Any]) -> dict[str, Any]:
    return {cle: (_texte(v) if isinstance(v, Decimal) else v) for cle, v in entrees.items()}


def mesurer_chantier(faits: dict[str, Any], definitions: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Les mesures d'un chantier, une par métrique enregistrée (hors performance d'équipe, qui
    porte sur plusieurs chantiers), dans l'ordre du registre. Chaque mesure : ``statut`` (calculée ou
    non calculable), ``valeur`` en texte (``None`` si non calculable), ``manque`` et ``detail`` (ce
    qu'il faut fournir, et de qui), ``entrees`` lues et ``version_definition`` (empreinte de la
    définition gouvernée). Une métrique du registre sans calcul est non calculable, nommément."""
    mesures = []
    for metric_id, definition in definitions.items():
        if metric_id == METRIQUE_EQUIPE:
            continue
        calcul = _CALCULS.get(metric_id)
        if calcul is None:
            valeur: Decimal | None = None
            entrees: dict[str, Any] = {}
            manque = [{"champ": "calcul", "source": "M8", "raison": "aucun calcul enregistré pour cette métrique"}]
        else:
            valeur, entrees, manque = calcul(faits)
        calculee = valeur is not None
        mesures.append({
            "metric_id": metric_id,
            "nom": definition["nom"],
            "unite": definition["unite"],
            "statut": STATUT_CALCULEE if calculee else STATUT_NON_CALCULABLE,
            "valeur": _texte(valeur) if valeur is not None else None,
            "manque": [] if calculee else manque,
            "detail": None if calculee else _detail_manque(manque),
            "entrees": _entrees_en_texte(entrees),
            "version_definition": encodage.empreinte(definition),
        })
    return mesures


def compacter(mesures: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Forme COMPACTE des mesures pour un outil de lecture, dont la réponse ne doit jamais dépasser la
    limite de sortie du socle (`Capacites` tronque au-delà de 6 000 caractères).

    Une mesure non calculable ne porte que les NOMS de ce qui manque ; le détail (champ, source,
    raison) est rendu UNE fois dans la liste ``manques``, dédupliquée : « pas de devis reçu » vaut
    pour cinq métriques et ne se répète pas cinq fois. Rien n'est perdu : chaque nom de ``manque``
    retrouve son détail dans ``manques``. Une mesure calculée garde ses entrées (la provenance du
    chiffre) ; les entrées partielles d'une mesure non calculable, jamais un chiffre, sont omises."""
    compactes: list[dict[str, Any]] = []
    manques: list[dict[str, str]] = []
    vus: set[tuple[str, str, str]] = set()
    for mesure in mesures:
        compacte: dict[str, Any] = {cle: mesure[cle] for cle in ("metric_id", "nom", "unite", "statut", "valeur")}
        if mesure["statut"] == STATUT_NON_CALCULABLE:
            compacte["manque"] = [m["champ"] for m in mesure["manque"]]
            for m in mesure["manque"]:
                cle = (m["champ"], m["source"], m["raison"])
                if cle not in vus:
                    vus.add(cle)
                    manques.append(dict(m))
        elif mesure["entrees"]:
            compacte["entrees"] = mesure["entrees"]
        compacte["version_definition"] = mesure["version_definition"]
        compactes.append(compacte)
    return compactes, manques


# ---------------------------------------------------------------------------
# Seuils : configurés ou pas d'alerte, et un signal qui dit quoi configurer
# ---------------------------------------------------------------------------
def _seuil_valide(brut: Any) -> dict[str, Any] | None:
    if not isinstance(brut, dict) or set(brut) != {"sens", "valeur"}:
        return None
    if brut["sens"] not in (SENS_AU_DESSUS, SENS_AU_DESSOUS):
        return None
    valeur = brut["valeur"]
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    lue = _decimal(valeur)
    return None if lue is None else {"sens": brut["sens"], "valeur": lue}


def evaluer_seuils(mesures: list[dict[str, Any]], seuils: Any) -> list[dict[str, Any]]:
    """Situation de chaque mesure CALCULÉE et surveillée face à son seuil configuré. Une mesure non
    calculable n'est pas évaluée (elle dit déjà ce qui manque). Sans seuil, ou avec un seuil
    invalide, le statut est ``seuil_a_configurer`` ou ``seuil_invalide`` : jamais une valeur par
    défaut, jamais une alerte. « Franchi » = la valeur atteint ou dépasse le seuil (``au_dessus``),
    ou l'atteint ou passe dessous (``au_dessous``), comme le seuil de variance de M6."""
    configures = seuils if isinstance(seuils, dict) else {}
    evaluations = []
    for mesure in mesures:
        metric_id = mesure["metric_id"]
        if metric_id not in _DESTINATAIRE_ALERTE or mesure["statut"] != STATUT_CALCULEE:
            continue
        evaluation: dict[str, Any] = {
            "metric_id": metric_id, "valeur": mesure["valeur"], "unite": mesure["unite"],
            "statut": SEUIL_A_CONFIGURER, "sens": None, "seuil": None,
        }
        brut = configures.get(metric_id)
        if brut is not None:
            seuil = _seuil_valide(brut)
            if seuil is None:
                evaluation["statut"] = SEUIL_INVALIDE
            else:
                valeur = Decimal(mesure["valeur"])
                atteint = valeur >= seuil["valeur"] if seuil["sens"] == SENS_AU_DESSUS else valeur <= seuil["valeur"]
                evaluation.update({
                    "statut": SEUIL_FRANCHI if atteint else SEUIL_NON_FRANCHI,
                    "sens": seuil["sens"], "seuil": _texte(seuil["valeur"]),
                })
        evaluations.append(evaluation)
    return evaluations


def _jour_de(horodatage: str) -> str:
    valeur = horodatage[:-1] + "+00:00" if horodatage.endswith("Z") else horodatage
    return datetime.fromisoformat(valeur).date().isoformat()


def _charge_franchi(
    wct_id: str, evaluation: dict[str, Any], mesure: dict[str, Any], definition: dict[str, str],
    horodatage_reference: str,
) -> dict[str, Any]:
    metric_id = evaluation["metric_id"]
    unite = evaluation["unite"]
    a_qui = _DESTINATAIRE_ALERTE[metric_id]
    valeur = _afficher(evaluation["valeur"], unite)
    seuil = _afficher(evaluation["seuil"], unite)
    comparaison = "atteint ou dépasse" if evaluation["sens"] == SENS_AU_DESSUS else "atteint ou passe sous"
    ident = f"m8-alerte-{metric_id}-{TYPE_ALERTE_SEUIL_FRANCHI}-{encodage.empreinte(wct_id)[:16]}"
    return {
        "evenement_id": ident,
        "metric_id": metric_id,
        "type_alerte": TYPE_ALERTE_SEUIL_FRANCHI,
        "quoi": f"{mesure['nom']} : {valeur} sur le chantier {wct_id}.",
        "a_qui": a_qui,
        "pourquoi": f"valeur {valeur} {comparaison} le seuil configuré {seuil}.",
        "preuve": {
            "metric_id": metric_id, "wct_id": wct_id, "valeur": evaluation["valeur"], "unite": unite,
            "sens": evaluation["sens"], "seuil": evaluation["seuil"],
            "version_definition": mesure["version_definition"],
        },
        "action_proposee": f"Revoir le chantier {wct_id} avec {a_qui} ({mesure['nom']} : {valeur}, seuil {seuil}).",
        "source": definition["source_donnees"],
        "horodatage_reference": horodatage_reference,
    }


def _charge_a_configurer(evaluation: dict[str, Any], horodatage_reference: str) -> dict[str, Any]:
    metric_id = evaluation["metric_id"]
    manque = "seuil" if evaluation["statut"] == SEUIL_A_CONFIGURER else "seuil_invalide"
    chemin = f"configuration.seuils_alerte.{metric_id}"
    etat = "absent" if manque == "seuil" else "invalide (sens au_dessus ou au_dessous et valeur numérique attendus)"
    ident = f"m8-alerte-{metric_id}-{TYPE_ALERTE_SEUIL_A_CONFIGURER}-{_jour_de(horodatage_reference)}"
    return {
        "evenement_id": ident,
        "metric_id": metric_id,
        "type_alerte": TYPE_ALERTE_SEUIL_A_CONFIGURER,
        "quoi": f"Aucun seuil valide pour {metric_id} : aucune alerte n'est possible.",
        "a_qui": _DESTINATAIRE_CONFIGURATION,
        "pourquoi": f"{chemin} est {etat} dans department.yaml.",
        "preuve": {"metric_id": metric_id, "manque": manque},
        "action_proposee": f"Définir le sens et la valeur du seuil ({chemin}) dans department.yaml de m08-analytics.",
        "source": _SOURCE_CONFIGURATION,
        "horodatage_reference": horodatage_reference,
    }


def charges_alertes(
    wct_id: str,
    mesures: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    definitions: dict[str, dict[str, str]],
    horodatage_reference: str,
) -> list[dict[str, Any]]:
    """Charges ``m8.alerte_proposee`` d'un chantier, prêtes à publier : une par seuil franchi
    (identifiant propre au chantier : le rejeu est un no-op du bus) et un signal « seuil à
    configurer » par métrique sans seuil valide (identifiant par métrique et par jour : une pile de
    chantiers le même jour n'émet qu'un seul rappel). ``horodatage_reference`` est l'instant du
    chantier (M8 n'a pas d'horloge)."""
    par_metrique = {mesure["metric_id"]: mesure for mesure in mesures}
    charges = []
    for evaluation in evaluations:
        if evaluation["statut"] == SEUIL_FRANCHI:
            metric_id = evaluation["metric_id"]
            charges.append(_charge_franchi(
                wct_id, evaluation, par_metrique[metric_id], definitions[metric_id], horodatage_reference,
            ))
        elif evaluation["statut"] in (SEUIL_A_CONFIGURER, SEUIL_INVALIDE):
            charges.append(_charge_a_configurer(evaluation, horodatage_reference))
    return charges


# ---------------------------------------------------------------------------
# Performance d'équipe : la plus petite métrique honnête
# ---------------------------------------------------------------------------
def _ligne_equipe(n: int, sans_prevu: int, reel: Decimal, estime: Decimal, minimum: int | None) -> dict[str, Any]:
    return {
        "n_chantiers_mesures": n,
        "n_chantiers_sans_temps_prevu": sans_prevu,
        "duree_reelle_totale_minutes": _texte(reel),
        "duree_estimee_totale_minutes": _texte(estime),
        "ecart_pct": _texte((reel - estime) / estime * _CENT) if n > 0 and estime > 0 else None,
        "suffisant": None if minimum is None else n >= minimum,
    }


def _minimum_valide(minimum: Any) -> int | None:
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        return None
    return minimum


def performance_equipe(entrees: list[dict[str, Any]], chantiers_minimum: Any) -> dict[str, Any]:
    """Écart de temps par technicien sur ses chantiers mesurés, et pour l'équipe entière.

    Un chantier n'est mesuré que s'il porte la durée réelle (M4) ET une durée estimée strictement
    positive (M3) ; les autres sont COMPTÉS (``n_chantiers_sans_temps_prevu``), jamais ignorés en
    silence. Le technicien est celui du dernier pointage de départ du chantier (M4) : un chantier à
    plusieurs personnes est attribué à la dernière — dit dans ``limites`` par l'outil.
    ``chantiers_minimum`` (configuration, jamais un défaut) dit si l'échantillon suffit :
    ``suffisant`` vaut ``None`` tant que le minimum n'est pas configuré, jamais un ``True`` supposé.

    Les techniciens sont rendus par identifiant, JAMAIS par écart : ce n'est pas un classement. Le
    détail nominatif n'est remis qu'au rôle admin (``outils.py``) ; ``equipe`` est anonyme."""
    minimum = _minimum_valide(chantiers_minimum)
    wct_par_id: dict[str, dict[str, Any]] = {}
    devis_par_id: dict[str, dict[str, Any]] = {}
    for entree in entrees:
        if entree.get("type_entree") == "wct":
            wct_par_id[entree["wct_id"]] = entree
        elif entree.get("type_entree") == "devis":
            devis_par_id[entree["devis_id"]] = entree

    cumuls: dict[str, dict[str, Any]] = {}
    for wct in wct_par_id.values():
        cumul = cumuls.setdefault(
            wct["technicien_id"], {"n": 0, "sans_prevu": 0, "reel": _ZERO, "estime": _ZERO}
        )
        devis = devis_par_id.get(wct.get("devis_id"))
        reel = _decimal(wct.get("duree_reelle_minutes"))
        estime = _decimal(devis.get("duree_estimee_minutes")) if devis is not None else None
        if reel is None or estime is None or estime <= 0:
            cumul["sans_prevu"] += 1
            continue
        cumul["n"] += 1
        cumul["reel"] += reel
        cumul["estime"] += estime

    techniciens = [
        {"technicien_id": technicien, **_ligne_equipe(c["n"], c["sans_prevu"], c["reel"], c["estime"], minimum)}
        for technicien, c in sorted(cumuls.items())
    ]
    total = {
        "n": sum(c["n"] for c in cumuls.values()),
        "sans_prevu": sum(c["sans_prevu"] for c in cumuls.values()),
        "reel": sum((c["reel"] for c in cumuls.values()), _ZERO),
        "estime": sum((c["estime"] for c in cumuls.values()), _ZERO),
    }
    return {
        "metric_id": METRIQUE_EQUIPE,
        "equipe": {
            "n_techniciens": len(cumuls),
            **_ligne_equipe(total["n"], total["sans_prevu"], total["reel"], total["estime"], minimum),
        },
        "techniciens": techniciens,
        "chantiers_minimum_a_configurer": minimum is None,
    }


def page_bornee(
    elements: list[dict[str, Any]], depart: int, budget_caracteres: int | None,
    construire: Callable[[list[dict[str, Any]], int | None], dict[str, Any]],
) -> dict[str, Any]:
    """Réponse d'un outil de lecture qui liste ``elements`` à partir de ``depart``, avec autant
    d'éléments que la borne en laisse tenir : ``construire(page, prochain_depart)`` assemble la réponse
    (``prochain_depart`` vaut ``None`` à la fin). La taille se mesure comme ``Capacites`` la mesure
    (``json.dumps`` sans échappement ASCII) : la réponse n'est jamais tronquée, et ce qui n'y tient pas
    est repris à ``prochain_depart``, jamais perdu. ``budget_caracteres`` ``None`` : tout d'un coup.
    Fail-closed : ``depart`` invalide ou au-delà de la fin, ou un seul élément plus gros que la borne (une
    page vide ne ferait pas progresser la lecture)."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"depart : entier positif ou nul attendu, reçu {depart!r}")
    if depart > len(elements):
        raise ValueError(f"depart {depart} au-delà de la fin de la liste ({len(elements)} éléments)")

    def reponse(nombre: int) -> dict[str, Any]:
        fin = depart + nombre
        return construire(elements[depart:fin], fin if fin < len(elements) else None)

    nombre = len(elements) - depart
    if budget_caracteres is not None:
        nombre = 0
        while depart + nombre < len(elements) and len(
            json.dumps(reponse(nombre + 1), ensure_ascii=False)
        ) <= budget_caracteres:
            nombre += 1
        if nombre == 0 and depart < len(elements):
            raise ValueError(f"un seul élément dépasse la borne de {budget_caracteres} caractères")
        if len(json.dumps(reponse(nombre), ensure_ascii=False)) > budget_caracteres:
            raise ValueError(
                f"le squelette de la réponse dépasse à lui seul la borne de {budget_caracteres} caractères"
            )
    return reponse(nombre)


__all__ = [
    "METRIQUE_EQUIPE",
    "MODULE_DEFINITIONS",
    "SEUIL_A_CONFIGURER",
    "SEUIL_FRANCHI",
    "SEUIL_INVALIDE",
    "SEUIL_NON_FRANCHI",
    "STATUT_CALCULEE",
    "STATUT_NON_CALCULABLE",
    "TYPE_ALERTE_SEUIL_A_CONFIGURER",
    "TYPE_ALERTE_SEUIL_FRANCHI",
    "assembler_faits",
    "charger_definitions",
    "charges_alertes",
    "compacter",
    "evaluer_seuils",
    "fait_devis",
    "fait_variance",
    "fait_wct",
    "mesurer_chantier",
    "page_bornee",
    "performance_equipe",
    "wcts_du_devis",
]
