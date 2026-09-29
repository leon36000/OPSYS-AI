"""Entonnoir commercial, du lead au devis accepté (PLAN T4.19 ; DEFINITION-PRODUIT.md §6 « flux principal » : M2 suit
la soumission jusqu'à l'acceptation ; §7 M8.6 « tableau de bord exécutif » et M8.10 « écarts » du pipeline).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (les instants viennent des faits reçus).
``outils.py``, seul point de contact avec le socle, reçoit les événements, range les faits et lit le registre.

Trois principes, comme ``mesures_chantier.py`` :

1. GOUVERNÉ. Chaque métrique est définie une seule fois dans ``metrics/m8-entonnoir.v1.yaml`` (nom, formule, source,
   unité, propriétaire ; garde de devise CAD de ``dictionnaire.py``). ``mesurer`` ne calcule que ce que ce registre
   définit et porte la version de la définition (empreinte, propriétaire compris) dans chaque mesure. Le code
   calcule, jamais un modèle.
2. HONNÊTE. Une entrée absente ou illisible donne une mesure ``non_calculable`` qui NOMME ce qui manque et sa source,
   jamais une valeur inventée. Un comptage est un comptage (zéro permis) tant qu'au moins un fait de l'entonnoir a été
   reçu ; sans aucun fait, M8 ne peut pas dire si l'entreprise n'a rien fait ou si le bus n'a rien livré : tout est
   non calculable. Un rapport, une médiane ou une somme exigent leurs entrées : jamais un zéro à leur place.
   M8 reprend ce que M2 et M3 ont publié ; il ne refait ni leur décision (qualifier, envoyer, constater un silence) ni
   leur date.
3. SANS SEUIL INVENTÉ. Un seuil n'existe que s'il est configuré (``department.yaml``,
   ``configuration.seuils_entonnoir``, GATE NATHAN). Sans seuil valide, la situation dit « seuil à configurer » :
   jamais une valeur par défaut. Un franchissement est un CONSTAT chiffré (valeur, seuil, sens), jamais une cause.

Faits reçus (un dictionnaire par fait, ajoutés au registre ``faits_entonnoir`` par ``outils.py``, chacun idempotent
par sa clé) : ``lead_recu`` (``m2.client_associe``), ``lead_qualifie`` (``m2.lead_assigne``), ``devis_envoye``
(``m3.devis_envoye``), ``devis_accepte`` (``m3.devis_accepte``) et ``devis_sans_reponse`` (``m3.devis_sans_reponse``).
Loi 25 : seuls des identifiants d'affaire, des instants et, pour un devis accepté, son prix arrêté par M3 sont
gardés ; jamais un contact, le propriétaire du lead, un client, ni un coût.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from . import dictionnaire, encodage, mesures_chantier, nombres, registre_metriques

MODULE_DEFINITIONS = "m08-analytics"

TYPE_LEAD_RECU = "lead_recu"
TYPE_LEAD_QUALIFIE = "lead_qualifie"
TYPE_DEVIS_ENVOYE = "devis_envoye"
TYPE_DEVIS_ACCEPTE = "devis_accepte"
TYPE_DEVIS_SANS_REPONSE = "devis_sans_reponse"

STATUT_CALCULEE = mesures_chantier.STATUT_CALCULEE
STATUT_NON_CALCULABLE = mesures_chantier.STATUT_NON_CALCULABLE
SEUIL_FRANCHI = mesures_chantier.SEUIL_FRANCHI
SEUIL_NON_FRANCHI = mesures_chantier.SEUIL_NON_FRANCHI
SEUIL_A_CONFIGURER = mesures_chantier.SEUIL_A_CONFIGURER
SEUIL_INVALIDE = mesures_chantier.SEUIL_INVALIDE

STATUT_DEVIS_ENVOYE = "envoye"
STATUT_DEVIS_BROUILLON = "brouillon"

_CHEMIN_METRIQUES = Path(__file__).resolve().parents[2] / "metrics" / "m8-entonnoir.v1.yaml"
_CENT = Decimal("100")
_ZERO = Decimal("0")
_SECONDES_PAR_JOUR = Decimal("86400")
_MICROSECONDES_PAR_SECONDE = Decimal("1000000")
_NOMBRE_D_IDENTIFIANTS_CITES = 3

_ORDRE_TYPES = (
    TYPE_LEAD_RECU, TYPE_LEAD_QUALIFIE, TYPE_DEVIS_ENVOYE, TYPE_DEVIS_ACCEPTE, TYPE_DEVIS_SANS_REPONSE,
)
# type de fait -> événement du catalogue qui le porte ; la source est celle du département qui le publie : M8 ne la
# produit pas.
_EVENEMENT_DE_TYPE = {
    TYPE_LEAD_RECU: "m2.client_associe",
    TYPE_LEAD_QUALIFIE: "m2.lead_assigne",
    TYPE_DEVIS_ENVOYE: "m3.devis_envoye",
    TYPE_DEVIS_ACCEPTE: "m3.devis_accepte",
    TYPE_DEVIS_SANS_REPONSE: "m3.devis_sans_reponse",
}
_SOURCE_DE_TYPE = {
    TYPE_LEAD_RECU: "M2 (m2.client_associe)",
    TYPE_LEAD_QUALIFIE: "M2 (m2.lead_assigne)",
    TYPE_DEVIS_ENVOYE: "M3 (m3.devis_envoye)",
    TYPE_DEVIS_ACCEPTE: "M3 (m3.devis_accepte)",
    TYPE_DEVIS_SANS_REPONSE: "M3 (m3.devis_sans_reponse)",
}
# Faits dont une métrique a besoin : ce que le message d'un entonnoir vide (aucun fait reçu) nomme.
_SOURCES_REQUISES = {
    "m8_leads_recus": (TYPE_LEAD_RECU,),
    "m8_leads_qualifies": (TYPE_LEAD_QUALIFIE,),
    "m8_devis_envoyes": (TYPE_DEVIS_ENVOYE,),
    "m8_devis_acceptes": (TYPE_DEVIS_ACCEPTE,),
    "m8_devis_sans_reponse": (TYPE_DEVIS_SANS_REPONSE,),
    "m8_taux_acceptation_pct": (TYPE_DEVIS_ENVOYE, TYPE_DEVIS_ACCEPTE),
    "m8_delai_lead_acceptation_jours": (TYPE_LEAD_RECU, TYPE_DEVIS_ACCEPTE),
    "m8_carnet_signe_cad": (TYPE_DEVIS_ACCEPTE,),
}
# Métriques dont un seuil a un sens (un rapport, une médiane, un stock à un instant) : ni les comptages cumulés (qui ne
# font que croître), ni rien qui ne serait pas une métrique du registre.
_METRIQUES_SURVEILLEES = frozenset({
    "m8_devis_sans_reponse", "m8_taux_acceptation_pct", "m8_delai_lead_acceptation_jours", "m8_carnet_signe_cad",
})


# ---------------------------------------------------------------------------
# Registre des définitions gouvernées
# ---------------------------------------------------------------------------
def _lire_proprietaires(chemin: Path) -> dict[str, str]:
    try:
        contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as erreur:
        raise ValueError(f"registre de l'entonnoir illisible : {chemin} ({erreur})") from erreur
    proprietaires = contenu.get("proprietaires") if isinstance(contenu, dict) else None
    if not isinstance(proprietaires, dict):
        raise ValueError(f"registre de l'entonnoir : `proprietaires` absent ou illisible dans {chemin}")
    return proprietaires


def charger_definitions(chemin: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Définitions de ``metrics/m8-entonnoir.v1.yaml`` : ``{metric_id: définition}``, dans l'ordre du fichier, chacune
    avec son ``proprietaire`` (département qui tient la donnée source). Fail-closed : un fichier invalide (structure,
    devise non CAD, doublon), une métrique sans propriétaire, un propriétaire qui n'est pas un département connu ou un
    propriétaire sans métrique est une erreur, jamais un registre partiel qui laisserait passer une métrique que
    personne ne garantit."""
    fichier = Path(chemin) if chemin is not None else _CHEMIN_METRIQUES
    compilees, erreurs = dictionnaire.compiler_fichier(fichier)
    if erreurs:
        raise ValueError(f"registre de l'entonnoir invalide : {'; '.join(erreurs)}")
    definitions = compilees.get(MODULE_DEFINITIONS)
    if not definitions:
        raise ValueError(f"registre de l'entonnoir vide : aucune métrique du module {MODULE_DEFINITIONS!r}")
    proprietaires = _lire_proprietaires(fichier)
    sans_proprietaire = [metric_id for metric_id in definitions if metric_id not in proprietaires]
    if sans_proprietaire:
        raise ValueError(f"registre de l'entonnoir : métrique(s) sans propriétaire : {', '.join(sans_proprietaire)}")
    inconnus = sorted(
        f"{metric_id} : {proprietaire!r}" for metric_id, proprietaire in proprietaires.items()
        if metric_id not in definitions or not registre_metriques.departement_connu(proprietaire)
    )
    if inconnus:
        raise ValueError(
            f"registre de l'entonnoir : propriétaire inconnu ou sans métrique : {'; '.join(inconnus)}"
        )
    return {
        metric_id: {**definition, "proprietaire": proprietaires[metric_id]}
        for metric_id, definition in definitions.items()
    }


# ---------------------------------------------------------------------------
# Faits : identifiants, instants et prix arrêté, rien d'autre
# ---------------------------------------------------------------------------
def fait_lead_recu(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m2.client_associe`` : le lead existe chez M2 depuis cet instant. Le ``client_id`` (empreinte du
    contact) n'est PAS gardé : M8 n'en a pas besoin."""
    return {
        "type_entree": TYPE_LEAD_RECU, "lead_id": charge["lead_id"], "horodatage": charge["horodatage_association"],
    }


def fait_lead_qualifie(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m2.lead_assigne`` : M2 a qualifié le lead à cet instant. Le propriétaire du lead (une personne)
    n'est PAS gardé : M8 compte des leads, il ne suit pas des vendeurs."""
    return {
        "type_entree": TYPE_LEAD_QUALIFIE, "lead_id": charge["lead_id"], "horodatage": charge["horodatage_assignation"],
    }


def fait_devis_envoye(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m3.devis_envoye`` : l'envoi a été approuvé à cet instant (pas livré : la livraison n'est pas
    encore un fait du bus). Aucun montant, M3 n'en porte pas."""
    return {
        "type_entree": TYPE_DEVIS_ENVOYE, "devis_id": charge["devis_id"], "lead_id": charge["lead_id"],
        "horodatage": charge["horodatage_envoi"],
    }


def fait_devis_accepte(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m3.devis_accepte`` : le devis est accepté à cet instant, pour le prix TOTAL que M3 a arrêté (M8
    n'en recalcule aucun). Ni le coût, ni les lignes, ni le taux de marge : l'entonnoir n'en a pas besoin."""
    return {
        "type_entree": TYPE_DEVIS_ACCEPTE, "devis_id": charge["devis_id"], "lead_id": charge["lead_id"],
        "prix_total": charge["prix_total"], "horodatage": charge["horodatage_acceptation"],
    }


def fait_devis_sans_reponse(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m3.devis_sans_reponse`` : le constat de M3 (statut du devis au constat, délai de relance qu'il a
    appliqué, instant du constat et du dernier état du devis), repris tel quel."""
    return {
        "type_entree": TYPE_DEVIS_SANS_REPONSE, "devis_id": charge["devis_id"], "lead_id": charge["lead_id"],
        "statut": charge["statut"], "horodatage": charge["horodatage_reference"],
        "horodatage_devis": charge["horodatage_devis"], "delai_relance_jours": charge["delai_relance_jours"],
    }


def cles_unicite(type_entree: str) -> tuple[str, ...]:
    """Les clés qui font un fait unique : un lead pour les faits de lead, un devis pour les faits de devis. Une
    relivraison de l'événement, ou un rejeu du répartiteur, n'ajoute jamais un second fait."""
    return ("lead_id",) if type_entree in (TYPE_LEAD_RECU, TYPE_LEAD_QUALIFIE) else ("devis_id",)


# ---------------------------------------------------------------------------
# Lecture des faits
# ---------------------------------------------------------------------------
def _par_type(entrees: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    par_type: dict[str, list[dict[str, Any]]] = {type_entree: [] for type_entree in _ORDRE_TYPES}
    for entree in entrees:
        type_entree = entree.get("type_entree")
        if type_entree in par_type:
            par_type[type_entree].append(entree)
    return par_type


def _premier_par_cle(faits: list[dict[str, Any]], cle: str) -> list[dict[str, Any]]:
    """Le premier fait de chaque valeur de ``cle``, dans l'ordre de réception ; un fait sans identifiant lisible
    n'est pas un fait de l'entonnoir."""
    vus: set[str] = set()
    uniques: list[dict[str, Any]] = []
    for fait in faits:
        identifiant = fait.get(cle)
        if isinstance(identifiant, str) and identifiant and identifiant not in vus:
            vus.add(identifiant)
            uniques.append(fait)
    return uniques


def _identifiants(faits: list[dict[str, Any]], cle: str) -> list[str]:
    return [fait[cle] for fait in _premier_par_cle(faits, cle)]


def instant_lu(texte: Any) -> datetime | None:
    """Instant lu d'un horodatage RFC 3339 AVEC fuseau ; ``None`` s'il est illisible ou sans fuseau : M8 ne devine
    jamais un fuseau."""
    if not isinstance(texte, str) or not texte:
        return None
    valeur = texte[:-1] + "+00:00" if texte.endswith("Z") else texte
    try:
        lu = datetime.fromisoformat(valeur)
    except ValueError:
        return None
    return lu if lu.tzinfo is not None and lu.utcoffset() is not None else None


def _secondes(ecart: Any) -> Decimal:
    """Durée exacte d'un ``timedelta``, en secondes décimales."""
    return (
        Decimal(ecart.days) * _SECONDES_PAR_JOUR + Decimal(ecart.seconds)
        + Decimal(ecart.microseconds) / _MICROSECONDES_PAR_SECONDE
    )


def _mediane(valeurs: list[Decimal]) -> Decimal:
    ordonnees = sorted(valeurs)
    milieu = len(ordonnees) // 2
    if len(ordonnees) % 2 == 1:
        return ordonnees[milieu]
    return (ordonnees[milieu - 1] + ordonnees[milieu]) / 2


def _plus_recent(faits: list[dict[str, Any]]) -> str | None:
    """L'instant (tel que reçu) du fait le plus récent parmi ceux dont l'instant est lisible, sinon ``None``."""
    lus = [(instant_lu(fait.get("horodatage")), fait.get("horodatage")) for fait in faits]
    lisibles = [(instant, texte) for instant, texte in lus if instant is not None]
    return max(lisibles, key=lambda paire: paire[0])[1] if lisibles else None


def _cites(identifiants: list[str]) -> str:
    cites = ", ".join(identifiants[:_NOMBRE_D_IDENTIFIANTS_CITES])
    reste = len(identifiants) - _NOMBRE_D_IDENTIFIANTS_CITES
    return f"{cites} et {reste} autre(s)" if reste > 0 else cites


def _plus_ancien_d_abord(faits: list[dict[str, Any]]) -> list[str]:
    """Identifiants de devis du plus ancien état connu au plus récent ; un instant illisible passe en dernier, à
    égalité l'identifiant départage : l'ordre ne dépend jamais de l'ordre de réception."""
    def cle(fait: dict[str, Any]) -> tuple[int, float, str]:
        instant = instant_lu(fait.get("horodatage_devis"))
        return (0, instant.timestamp(), fait["devis_id"]) if instant is not None else (1, 0.0, fait["devis_id"])

    return [fait["devis_id"] for fait in sorted(_premier_par_cle(faits, "devis_id"), key=cle)]


def _devis_en_attente(par_type: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    acceptes = set(_identifiants(par_type[TYPE_DEVIS_ACCEPTE], "devis_id"))
    envoyes = set(_identifiants(par_type[TYPE_DEVIS_ENVOYE], "devis_id"))
    constats = par_type[TYPE_DEVIS_SANS_REPONSE]
    sans_reponse = _plus_ancien_d_abord([
        fait for fait in constats
        if fait.get("statut") == STATUT_DEVIS_ENVOYE and fait.get("devis_id") not in acceptes
    ])
    en_attente = set(sans_reponse)
    brouillons = _plus_ancien_d_abord([
        fait for fait in constats
        if fait.get("statut") == STATUT_DEVIS_BROUILLON
        and fait.get("devis_id") not in acceptes | envoyes | en_attente
    ])
    return {"sans_reponse": sans_reponse, "brouillons_en_retard": brouillons}


def etat_des_devis(entrees: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Les devis qui attendent, tels que M3 les a constatés : ``sans_reponse`` (envoyés, constatés sans réponse, pas
    acceptés depuis) et ``brouillons_en_retard`` (constatés au statut brouillon, jamais vus envoyés ni acceptés),
    du plus ancien au plus récent. Une seule règle, pour la mesure comme pour la vue exécutive."""
    return _devis_en_attente(_par_type(entrees))


# ---------------------------------------------------------------------------
# Calculs : (valeur | None, entrées lues, manques)
# ---------------------------------------------------------------------------
Resultat = tuple[str | None, dict[str, Any], list[dict[str, str]]]


def _manque_source(type_entree: str, raison: str) -> dict[str, str]:
    return {"champ": _EVENEMENT_DE_TYPE[type_entree], "source": _SOURCE_DE_TYPE[type_entree], "raison": raison}


def _comptage(type_entree: str, cle: str) -> Callable[..., Resultat]:
    def calcul(par_type: dict[str, list[dict[str, Any]]], _wcts: list[dict[str, Any]]) -> Resultat:
        return str(len(_identifiants(par_type[type_entree], cle))), {}, []

    return calcul


def _devis_sans_reponse(par_type: dict[str, list[dict[str, Any]]], _wcts: list[dict[str, Any]]) -> Resultat:
    attente = _devis_en_attente(par_type)
    entrees = {
        "n_constats_recus": len(_identifiants(par_type[TYPE_DEVIS_SANS_REPONSE], "devis_id")),
        "brouillons_en_retard": len(attente["brouillons_en_retard"]),
    }
    return str(len(attente["sans_reponse"])), entrees, []


def _taux_acceptation_pct(par_type: dict[str, list[dict[str, Any]]], _wcts: list[dict[str, Any]]) -> Resultat:
    envoyes = _identifiants(par_type[TYPE_DEVIS_ENVOYE], "devis_id")
    acceptes = set(_identifiants(par_type[TYPE_DEVIS_ACCEPTE], "devis_id"))
    if not envoyes:
        manque = _manque_source(TYPE_DEVIS_ENVOYE, "aucun devis envoyé reçu : le taux n'a pas de dénominateur")
        return None, {}, [manque]
    acceptes_parmi_envoyes = [devis_id for devis_id in envoyes if devis_id in acceptes]
    entrees = {
        "n_envoyes": len(envoyes),
        "n_acceptes_parmi_envoyes": len(acceptes_parmi_envoyes),
        "n_acceptes_sans_envoi_recu": len(acceptes - set(envoyes)),
    }
    taux = Decimal(len(acceptes_parmi_envoyes)) * _CENT / Decimal(len(envoyes))
    return nombres.texte_decimal(taux), entrees, []


def _delai_lead_acceptation_jours(par_type: dict[str, list[dict[str, Any]]], _wcts: list[dict[str, Any]]) -> Resultat:
    acceptes = _premier_par_cle(par_type[TYPE_DEVIS_ACCEPTE], "devis_id")
    if not acceptes:
        return None, {}, [_manque_source(TYPE_DEVIS_ACCEPTE, "aucun devis accepté reçu")]
    leads = _premier_par_cle(par_type[TYPE_LEAD_RECU], "lead_id")
    arrivees = {fait["lead_id"]: fait.get("horodatage") for fait in leads}
    delais: list[Decimal] = []
    sans_arrivee = illisibles = negatifs = 0
    for fait in acceptes:
        if fait.get("lead_id") not in arrivees:
            sans_arrivee += 1
            continue
        debut, fin = instant_lu(arrivees[fait["lead_id"]]), instant_lu(fait.get("horodatage"))
        if debut is None or fin is None:
            illisibles += 1
            continue
        secondes = _secondes(fin - debut)
        if secondes < _ZERO:
            negatifs += 1
            continue
        delais.append(secondes)
    entrees = {
        "n_mesures": len(delais), "n_sans_arrivee_du_lead": sans_arrivee,
        "n_instants_illisibles": illisibles, "n_delais_negatifs": negatifs,
    }
    if delais:
        return nombres.texte_decimal(_mediane(delais) / _SECONDES_PAR_JOUR), entrees, []
    manque = []
    if sans_arrivee:
        manque.append(_manque_source(
            TYPE_LEAD_RECU, f"{sans_arrivee} devis accepté(s) dont le lead n'a aucun fait d'arrivée reçu"
        ))
    if illisibles:
        manque.append({
            "champ": "horodatage", "source": "M2 et M3 (instants des faits)",
            "raison": f"{illisibles} devis accepté(s) dont un instant est illisible (RFC 3339 avec fuseau attendu)",
        })
    if negatifs:
        manque.append({
            "champ": "horodatage", "source": "M2 et M3 (instants des faits)",
            "raison": f"{negatifs} devis accepté(s) acceptés avant l'arrivée de leur lead : instants incohérents",
        })
    return None, entrees, manque


def _carnet_signe_cad(par_type: dict[str, list[dict[str, Any]]], wcts: list[dict[str, Any]]) -> Resultat:
    acceptes = _premier_par_cle(par_type[TYPE_DEVIS_ACCEPTE], "devis_id")
    termines = {wct["devis_id"] for wct in wcts if isinstance(wct.get("devis_id"), str) and wct["devis_id"]}
    au_carnet = [fait for fait in acceptes if fait["devis_id"] not in termines]
    entrees = {
        "n_devis_au_carnet": len(au_carnet), "n_devis_acceptes": len(acceptes),
        "chantiers_termines_sans_devis_relie": sum(1 for wct in wcts if not wct.get("devis_id")),
    }
    somme = _ZERO
    sans_prix: list[str] = []
    for fait in au_carnet:
        prix = nombres.decimal_lu(fait.get("prix_total"))
        if prix is None:
            sans_prix.append(fait["devis_id"])
        else:
            somme += prix
    if sans_prix:
        return None, entrees, [_manque_source(
            TYPE_DEVIS_ACCEPTE, f"{len(sans_prix)} devis du carnet sans prix lisible (prix_total) : {_cites(sans_prix)}"
        )]
    return nombres.texte_decimal(somme), entrees, []


_CALCULS = {
    "m8_leads_recus": _comptage(TYPE_LEAD_RECU, "lead_id"),
    "m8_leads_qualifies": _comptage(TYPE_LEAD_QUALIFIE, "lead_id"),
    "m8_devis_envoyes": _comptage(TYPE_DEVIS_ENVOYE, "devis_id"),
    "m8_devis_acceptes": _comptage(TYPE_DEVIS_ACCEPTE, "devis_id"),
    "m8_devis_sans_reponse": _devis_sans_reponse,
    "m8_taux_acceptation_pct": _taux_acceptation_pct,
    "m8_delai_lead_acceptation_jours": _delai_lead_acceptation_jours,
    "m8_carnet_signe_cad": _carnet_signe_cad,
}


def _detail_manque(manque: list[dict[str, str]]) -> str:
    morceaux = "; ".join(f"{m['champ']} — {m['source']} : {m['raison']}" for m in manque)
    return f"non calculable, manque {morceaux}"


def _manques_entonnoir_vide(metric_id: str) -> list[dict[str, str]]:
    return [
        _manque_source(
            type_entree,
            "aucun fait de l'entonnoir reçu : rien publié par le département, ou rien livré par le bus",
        )
        for type_entree in _SOURCES_REQUISES.get(metric_id, ())
    ]


def mesurer(
    entrees: list[dict[str, Any]], faits_chantier: list[dict[str, Any]], definitions: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """Les mesures de l'entonnoir, une par métrique du registre, dans l'ordre du registre. Chaque mesure : ``statut``
    (calculée ou non calculable), ``valeur`` en texte (``None`` si non calculable), ``manque`` et ``detail`` (ce qu'il
    faut fournir, et de qui), ``entrees`` lues, ``proprietaire``, ``source`` et ``version_definition`` (empreinte de la
    définition gouvernée, propriétaire compris).

    ``faits_chantier`` est le registre des chantiers terminés (``mesures_chantier``) : seuls ses faits ``wct`` servent,
    pour sortir du carnet un devis dont le chantier est terminé. Sans aucun fait de l'entonnoir, toutes les mesures sont
    non calculables ; une métrique du registre sans calcul l'est aussi, nommément."""
    par_type = _par_type(entrees)
    entonnoir_vide = not any(par_type.values())
    wcts = [fait for fait in faits_chantier if fait.get("type_entree") == "wct"]
    mesures = []
    for metric_id, definition in definitions.items():
        calcul = _CALCULS.get(metric_id)
        if entonnoir_vide:
            valeur: str | None = None
            entrees_lues: dict[str, Any] = {}
            manque = _manques_entonnoir_vide(metric_id)
        elif calcul is None:
            valeur, entrees_lues = None, {}
            manque = [{"champ": "calcul", "source": "M8", "raison": "aucun calcul enregistré pour cette métrique"}]
        else:
            valeur, entrees_lues, manque = calcul(par_type, wcts)
        calculee = valeur is not None
        mesures.append({
            "metric_id": metric_id,
            "nom": definition["nom"],
            "unite": definition["unite"],
            "statut": STATUT_CALCULEE if calculee else STATUT_NON_CALCULABLE,
            "valeur": valeur,
            "manque": [] if calculee else manque,
            "detail": None if calculee else _detail_manque(manque),
            "entrees": entrees_lues,
            "proprietaire": definition["proprietaire"],
            "source": definition["source_donnees"],
            "version_definition": encodage.empreinte(definition),
        })
    return mesures


def sources(entrees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ce que M8 a reçu, par événement : combien de faits et l'instant du plus récent (la fraîcheur de l'entonnoir,
    P2 : M8 n'a pas d'horloge, il dit jusqu'où vont ses faits). Zéro fait est dit zéro : le lecteur voit lui-même
    quelle source n'a rien livré."""
    par_type = _par_type(entrees)
    return [
        {
            "evenement": _EVENEMENT_DE_TYPE[type_entree],
            "n": len(_premier_par_cle(par_type[type_entree], cles_unicite(type_entree)[0])),
            "dernier_fait_le": _plus_recent(par_type[type_entree]),
        }
        for type_entree in _ORDRE_TYPES
    ]


# ---------------------------------------------------------------------------
# Seuils : configurés ou pas d'alerte, et un signal qui dit quoi configurer
# ---------------------------------------------------------------------------
def evaluer_seuils(mesures: list[dict[str, Any]], seuils: Any) -> list[dict[str, Any]]:
    """Situation de chaque mesure CALCULÉE et surveillée face à son seuil configuré. Une mesure non calculable n'est
    pas évaluée (elle dit déjà ce qui manque). Sans seuil, ou avec un seuil invalide, le statut est
    ``seuil_a_configurer`` ou ``seuil_invalide`` : jamais une valeur par défaut, jamais un franchissement. « Franchi » =
    la valeur atteint ou dépasse le seuil (``au_dessus``), ou l'atteint ou passe dessous (``au_dessous``), comme
    pour la mesure d'un chantier."""
    configures = seuils if isinstance(seuils, dict) else {}
    evaluations = []
    for mesure in mesures:
        metric_id = mesure["metric_id"]
        if metric_id not in _METRIQUES_SURVEILLEES or mesure["statut"] != STATUT_CALCULEE:
            continue
        evaluation: dict[str, Any] = {
            "metric_id": metric_id, "valeur": mesure["valeur"], "unite": mesure["unite"],
            "statut": SEUIL_A_CONFIGURER, "sens": None, "seuil": None,
        }
        brut = configures.get(metric_id)
        if brut is not None:
            seuil = nombres.seuil_valide(brut)
            if seuil is None:
                evaluation["statut"] = SEUIL_INVALIDE
            else:
                valeur = Decimal(mesure["valeur"])
                if seuil["sens"] == nombres.SENS_AU_DESSUS:
                    atteint = valeur >= seuil["valeur"]
                else:
                    atteint = valeur <= seuil["valeur"]
                evaluation.update({
                    "statut": SEUIL_FRANCHI if atteint else SEUIL_NON_FRANCHI,
                    "sens": seuil["sens"], "seuil": nombres.texte_decimal(seuil["valeur"]),
                })
        evaluations.append(evaluation)
    return evaluations


def seuils_ignores(seuils: Any) -> list[str]:
    """Les clés de la configuration qui ne sont pas une métrique surveillée : une faute de frappe, ou un comptage
    cumulé (qui ne fait que croître) auquel un seuil ne dirait rien. Dites au propriétaire, jamais ignorées en
    silence : il croirait sa surveillance en place."""
    if not isinstance(seuils, dict):
        return []
    return sorted(str(cle) for cle in seuils if cle not in _METRIQUES_SURVEILLEES)


def situation(
    entrees: list[dict[str, Any]], faits_chantier: list[dict[str, Any]], definitions: dict[str, dict[str, str]],
    seuils: Any,
) -> dict[str, Any]:
    """L'entonnoir tel que les faits reçus le permettent : mesures, sources, situation face aux seuils (et les clés
    de configuration qui ne surveillent rien) et devis qui attendent. Lecture pure : ne publie rien."""
    mesures = mesurer(entrees, faits_chantier, definitions)
    return {
        "mesures": mesures,
        "sources": sources(entrees),
        "seuils": evaluer_seuils(mesures, seuils),
        "seuils_ignores": seuils_ignores(seuils),
        "devis": etat_des_devis(entrees),
    }


__all__ = [
    "MODULE_DEFINITIONS",
    "SEUIL_A_CONFIGURER",
    "SEUIL_FRANCHI",
    "SEUIL_INVALIDE",
    "SEUIL_NON_FRANCHI",
    "STATUT_CALCULEE",
    "STATUT_NON_CALCULABLE",
    "TYPE_DEVIS_ACCEPTE",
    "TYPE_DEVIS_ENVOYE",
    "TYPE_DEVIS_SANS_REPONSE",
    "TYPE_LEAD_QUALIFIE",
    "TYPE_LEAD_RECU",
    "charger_definitions",
    "cles_unicite",
    "etat_des_devis",
    "evaluer_seuils",
    "fait_devis_accepte",
    "fait_devis_envoye",
    "fait_devis_sans_reponse",
    "fait_lead_qualifie",
    "fait_lead_recu",
    "instant_lu",
    "mesurer",
    "seuils_ignores",
    "situation",
    "sources",
]
