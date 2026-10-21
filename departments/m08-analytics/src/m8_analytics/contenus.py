"""Mesure par contenu : quels contenus de M7 amènent des leads, puis des devis (PLAN T4.17-e ; DEFINITION-PRODUIT.md
§6 « M7 attire → M1 capte », §7 M7.3 « mesure », M7.8 « marketing → leads → ventes » et M8.3 « registre de
métriques »).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (les instants viennent des faits reçus).
``outils.py``, seul point de contact avec le socle, reçoit les événements, range les faits et lit les registres.

Même patron que ``entonnoir.py`` (T4.19), trois principes :

1. GOUVERNÉ. Chaque métrique est définie une seule fois dans ``metrics/m8-contenus.v1.yaml`` (nom, formule, source,
   unité, propriétaire) et porte la version de sa définition. Le code calcule, jamais un modèle.
2. HONNÊTE. Une entrée absente donne une mesure ``non_calculable`` qui NOMME ce qui manque et sa source, jamais une
   valeur inventée : sans aucun contenu exporté, sans aucun lead reçu de M1 (ou, pour les devis, sans aucun fait de
   l'entonnoir), M8 ne peut pas dire si l'entreprise n'a rien fait ou si le bus n'a rien livré. Les impressions et les
   clics n'ont AUCUNE source aujourd'hui : ils sont « non calculable, manque la source des impressions et des clics »,
   jamais un zéro.
3. ATTRIBUTION STRICTE. Un lead est attribué à un contenu par l'égalité stricte de sa clé ``utm_content`` (M1,
   ``m1.lead_qualifie``) avec celle d'un contenu que M7 a exporté AVEC un lien de suivi (``m7.contenu_exporte``). Un
   lead sans clé n'est attribué à aucun contenu ; une clé que nul contenu ne porte, ou que deux contenus se disputent,
   n'est attribuée à aucun non plus : chaque cas est compté à part, jamais ignoré en silence. Un devis suit le lead
   qu'il porte (``lead_id``, M3) : un devis dont le lead n'est pas connu de M1 (l'opportunité que M2 rouvre pour un
   client connu, par exemple) n'est attribué à aucun contenu.

Faits reçus (registre ``faits_contenus``, chacun idempotent par sa clé, ajoutés par ``outils.py``) :
``contenu_exporte`` (``m7.contenu_exporte``) et ``lead_m1`` (``m1.lead_qualifie``). Les devis viennent des faits de
l'entonnoir (``faits_entonnoir``, T4.19), que ce module lit sans les réécrire. Loi 25 : seuls des identifiants, des
instants et la clé ``utm_content`` sont gardés ; jamais le contact, la ville ni le texte d'un lead, ni le texte d'un
contenu.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from . import entonnoir

MODULE_DEFINITIONS = entonnoir.MODULE_DEFINITIONS

TYPE_CONTENU_EXPORTE = "contenu_exporte"
TYPE_LEAD_M1 = "lead_m1"
EVENEMENT_CONTENU = "m7.contenu_exporte"
EVENEMENT_LEAD = "m1.lead_qualifie"

STATUT_CALCULEE = entonnoir.STATUT_CALCULEE
STATUT_NON_CALCULABLE = entonnoir.STATUT_NON_CALCULABLE

SUIVI_LIEN = "lien"  # le paquet portait un lien qui contient la clé : des leads peuvent l'apporter
SUIVI_SANS_LIEN = "sans_lien"  # aucun lien ne porte la clé : aucun lead ne peut l'apporter, « non mesurable »
SUIVI_AMBIGU = "ambigu"  # deux contenus se disputent la clé : aucun n'est mesuré

_CHEMIN_METRIQUES = Path(__file__).resolve().parents[2] / "metrics" / "m8-contenus.v1.yaml"
_REGISTRE = "des contenus"

# Ce qu'un lead devient face aux contenus connus.
_ATTRIBUE = "attribue"
_SANS_CLE = "sans_utm_content"
_INCONNU = "utm_content_inconnu"
_AMBIGU = "utm_content_ambigu"


def _manque(champ: str, source: str, raison: str) -> dict[str, str]:
    return {"champ": champ, "source": source, "raison": raison}


_MANQUE_CONTENUS = _manque(
    EVENEMENT_CONTENU, "M7 (m7.contenu_exporte)",
    "aucun contenu exporté reçu : rien exporté par M7, ou rien livré par le bus",
)
_MANQUE_LEADS = _manque(
    EVENEMENT_LEAD, "M1 (m1.lead_qualifie)", "aucun lead reçu de M1 : rien qualifié, ou rien livré par le bus",
)
_MANQUES_DEVIS = {
    "envoyes": _manque(
        "m3.devis_envoye", "M3 (m3.devis_envoye)",
        "aucun fait de l'entonnoir reçu : rien publié par le département, ou rien livré par le bus",
    ),
    "acceptes": _manque(
        "m3.devis_accepte", "M3 (m3.devis_accepte)",
        "aucun fait de l'entonnoir reçu : rien publié par le département, ou rien livré par le bus",
    ),
}
_MANQUE_IMPRESSIONS_CLICS = _manque(
    "source des impressions et des clics", "aucune (connecteur à décider : statistiques des plateformes, Matomo)",
    "ni le bus ni un connecteur ne fournit les impressions ni les clics d'un contenu",
)


# ---------------------------------------------------------------------------
# Registre des définitions gouvernées
# ---------------------------------------------------------------------------
def charger_definitions(chemin: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Définitions de ``metrics/m8-contenus.v1.yaml`` : ``{metric_id: définition}``, dans l'ordre du fichier, chacune
    avec son ``proprietaire``. Mêmes contrôles et mêmes refus que l'entonnoir (``entonnoir.charger_definitions``) :
    fail-closed, jamais un registre partiel."""
    return entonnoir.charger_definitions(chemin if chemin is not None else _CHEMIN_METRIQUES, registre=_REGISTRE)


# ---------------------------------------------------------------------------
# Faits : identifiants, instants et clé de mesure, rien d'autre
# ---------------------------------------------------------------------------
def fait_contenu_exporte(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m7.contenu_exporte`` : ce contenu existe (M7 en a exporté le paquet à cet instant), avec sa clé de
    mesure, son chantier, son canal, et si son paquet portait un lien de suivi. Aucun texte."""
    return {
        "type_entree": TYPE_CONTENU_EXPORTE, "contenu_id": charge["contenu_id"], "wct_id": charge["wct_id"],
        "canal": charge["canal"], "utm_content": charge["utm_content"], "lien_de_suivi": charge["lien_de_suivi"],
        "horodatage": charge["exporte_le"],
    }


def fait_lead_m1(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m1.lead_qualifie`` : M1 a qualifié ce lead à cet instant, avec la clé ``utm_content`` qu'il
    portait (``None`` s'il n'en portait pas). NI le contact, NI la ville, NI le service, NI la conversation : M8
    compte des leads, il ne garde rien qui identifie une personne."""
    lead = charge["lead"]
    utm = lead.get("utm")
    cle = utm.get("utm_content") if isinstance(utm, dict) else None
    return {
        "type_entree": TYPE_LEAD_M1, "lead_id": lead["lead_id"],
        "utm_content": cle if isinstance(cle, str) and cle else None, "horodatage": charge["horodatage"],
    }


def cles_unicite(type_entree: str) -> tuple[str, ...]:
    """Les clés qui font un fait unique : un contenu pour ``contenu_exporte``, un lead pour ``lead_m1``. Une relivraison
    de l'événement, ou un rejeu du répartiteur, n'ajoute jamais un second fait."""
    return ("contenu_id",) if type_entree == TYPE_CONTENU_EXPORTE else ("lead_id",)


# ---------------------------------------------------------------------------
# Attribution : qui a amené quoi
# ---------------------------------------------------------------------------
def _uniques(faits: list[dict[str, Any]], type_entree: str, cle: str) -> list[dict[str, Any]]:
    """Le premier fait de chaque valeur de ``cle`` parmi ceux de ce type, dans l'ordre de réception ; un fait sans
    identifiant lisible n'est pas un fait."""
    vus: set[str] = set()
    uniques: list[dict[str, Any]] = []
    for fait in faits:
        identifiant = fait.get(cle)
        if fait.get("type_entree") == type_entree and isinstance(identifiant, str) and identifiant \
                and identifiant not in vus:
            vus.add(identifiant)
            uniques.append(fait)
    return uniques


def _devis(
    entrees: list[dict[str, Any]], type_entree: str, classement: dict[str, tuple[str, str | None]],
) -> dict[str, Any]:
    """Les devis d'un type de fait de l'entonnoir, rangés selon ce que devient leur lead : attribué à un contenu,
    connu de M1 sans contenu, ou inconnu de M1."""
    faits = _uniques(entrees, type_entree, "devis_id")
    par_cle: Counter[str] = Counter()
    sans_lead_de_m1 = lead_sans_contenu = 0
    for fait in faits:
        lead_id = fait.get("lead_id")
        sort = classement.get(lead_id) if isinstance(lead_id, str) else None
        if sort is None:
            sans_lead_de_m1 += 1
        elif sort[0] == _ATTRIBUE and sort[1] is not None:
            par_cle[sort[1]] += 1
        else:
            lead_sans_contenu += 1
    return {
        "n_recus": len(faits), "n_attribues": sum(par_cle.values()), "n_sans_lead_de_m1": sans_lead_de_m1,
        "n_lead_sans_contenu": lead_sans_contenu, "par_cle": par_cle,
    }


def attribuer(faits: list[dict[str, Any]], entrees_entonnoir: list[dict[str, Any]]) -> dict[str, Any]:
    """Tout ce que les faits reçus permettent d'attribuer, en un seul passage : les contenus connus, les clés
    ambiguës, le sort de chaque lead, les décomptes par clé et les devis rattachés. ``faits`` est le registre
    ``faits_contenus``, ``entrees_entonnoir`` le registre ``faits_entonnoir`` (devis). Lecture pure."""
    contenus = _uniques(faits, TYPE_CONTENU_EXPORTE, "contenu_id")
    leads = _uniques(faits, TYPE_LEAD_M1, "lead_id")

    par_cle: dict[str, list[dict[str, Any]]] = {}
    for contenu in contenus:
        cle = contenu.get("utm_content")
        if isinstance(cle, str) and cle:
            par_cle.setdefault(cle, []).append(contenu)
    cles_ambigues = {cle for cle, liste in par_cle.items() if len(liste) > 1}
    cles_attribuables = {
        cle for cle, liste in par_cle.items() if len(liste) == 1 and liste[0].get("lien_de_suivi") is True
    }

    classement: dict[str, tuple[str, str | None]] = {}
    for lead in leads:
        cle = lead.get("utm_content")
        if not isinstance(cle, str) or not cle:
            classement[lead["lead_id"]] = (_SANS_CLE, None)
        elif cle in cles_ambigues:
            classement[lead["lead_id"]] = (_AMBIGU, None)
        elif cle in cles_attribuables:
            classement[lead["lead_id"]] = (_ATTRIBUE, cle)
        else:
            classement[lead["lead_id"]] = (_INCONNU, None)
    sorts = Counter(sort for sort, _ in classement.values())
    return {
        "contenus": contenus,
        "cles_ambigues": cles_ambigues,
        "cles_attribuables": cles_attribuables,
        "leads": {
            "n_recus": len(leads), "n_attribues": sorts[_ATTRIBUE], "n_sans_utm_content": sorts[_SANS_CLE],
            "n_utm_content_inconnu": sorts[_INCONNU], "n_utm_content_ambigu": sorts[_AMBIGU],
        },
        "leads_par_cle": Counter(cle for sort, cle in classement.values() if sort == _ATTRIBUE and cle is not None),
        "devis_envoyes": _devis(entrees_entonnoir, entonnoir.TYPE_DEVIS_ENVOYE, classement),
        "devis_acceptes": _devis(entrees_entonnoir, entonnoir.TYPE_DEVIS_ACCEPTE, classement),
        "entonnoir_vide": entonnoir.est_vide(entrees_entonnoir),
    }


def suivi_du_contenu(contenu: dict[str, Any], cles_ambigues: set[str]) -> str:
    """Comment un contenu se mesure : par un lien de suivi (``lien``), pas du tout (``sans_lien`` : aucun lien ne
    porte sa clé, donc aucun lead ne peut la rapporter) ou pas de façon sûre (``ambigu`` : sa clé est aussi celle d'un
    autre)."""
    cle = contenu.get("utm_content")
    if isinstance(cle, str) and cle in cles_ambigues:
        return SUIVI_AMBIGU
    return SUIVI_LIEN if contenu.get("lien_de_suivi") is True and isinstance(cle, str) and cle else SUIVI_SANS_LIEN


# ---------------------------------------------------------------------------
# Calculs : (valeur | None, entrées lues, manques)
# ---------------------------------------------------------------------------
Resultat = tuple[str | None, dict[str, Any], list[dict[str, str]]]


def _contenus_exportes(attribution: dict[str, Any]) -> Resultat:
    contenus = attribution["contenus"]
    if not contenus:
        return None, {}, [_MANQUE_CONTENUS]
    suivis = Counter(suivi_du_contenu(contenu, attribution["cles_ambigues"]) for contenu in contenus)
    entrees = {
        "n_mesurables": suivis[SUIVI_LIEN], "n_sans_lien_de_suivi": suivis[SUIVI_SANS_LIEN],
        "n_cle_ambigue": suivis[SUIVI_AMBIGU],
    }
    return str(len(contenus)), entrees, []


def _manques_de_la_chaine(attribution: dict[str, Any], devis: str | None) -> list[dict[str, str]]:
    """Ce que la chaîne contenu -> lead (-> devis) n'a pas reçu : les manques de chaque source absente, une fois."""
    manque = []
    if not attribution["contenus"]:
        manque.append(_MANQUE_CONTENUS)
    if not attribution["leads"]["n_recus"]:
        manque.append(_MANQUE_LEADS)
    if devis is not None and attribution["entonnoir_vide"]:
        manque.append(_MANQUES_DEVIS[devis])
    return manque


def _leads_par_contenu(attribution: dict[str, Any]) -> Resultat:
    manque = _manques_de_la_chaine(attribution, None)
    if manque:
        return None, {}, manque
    leads = attribution["leads"]
    entrees = {
        "n_leads_recus": leads["n_recus"], "n_leads_attribues": leads["n_attribues"],
        "n_leads_sans_utm_content": leads["n_sans_utm_content"],
        "n_leads_utm_content_inconnu": leads["n_utm_content_inconnu"],
        "n_leads_utm_content_ambigu": leads["n_utm_content_ambigu"],
    }
    return str(leads["n_attribues"]), entrees, []


def _devis_par_contenu(genre: str) -> Any:
    def calcul(attribution: dict[str, Any]) -> Resultat:
        manque = _manques_de_la_chaine(attribution, genre)
        if manque:
            return None, {}, manque
        devis = attribution[f"devis_{genre}"]
        entrees = {
            "n_devis_recus": devis["n_recus"], "n_devis_attribues": devis["n_attribues"],
            "n_sans_lead_de_m1": devis["n_sans_lead_de_m1"], "n_lead_sans_contenu": devis["n_lead_sans_contenu"],
        }
        return str(devis["n_attribues"]), entrees, []

    return calcul


def _sans_source(_attribution: dict[str, Any]) -> Resultat:
    """Impressions et clics : aucune source aujourd'hui, donc jamais une valeur (surtout pas zéro)."""
    return None, {}, [_MANQUE_IMPRESSIONS_CLICS]


_CALCULS = {
    "m8_contenus_exportes": _contenus_exportes,
    "m8_leads_par_contenu": _leads_par_contenu,
    "m8_devis_envoyes_par_contenu": _devis_par_contenu("envoyes"),
    "m8_devis_acceptes_par_contenu": _devis_par_contenu("acceptes"),
    "m8_impressions_par_contenu": _sans_source,
    "m8_clics_par_contenu": _sans_source,
}


def mesurer(attribution: dict[str, Any], definitions: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Les mesures par contenu, une par métrique du registre, dans l'ordre du registre (forme de
    ``entonnoir.construire_mesure``). ``valeur`` est le total sur tous les contenus ; le détail par contenu est dans
    ``lignes``. Une métrique du registre sans calcul est non calculable, nommément."""
    mesures = []
    for metric_id, definition in definitions.items():
        calcul = _CALCULS.get(metric_id)
        if calcul is None:
            valeur: str | None = None
            entrees: dict[str, Any] = {}
            manque = [{"champ": "calcul", "source": "M8", "raison": "aucun calcul enregistré pour cette métrique"}]
        else:
            valeur, entrees, manque = calcul(attribution)
        mesures.append(entonnoir.construire_mesure(metric_id, definition, valeur, entrees, manque))
    return mesures


# ---------------------------------------------------------------------------
# Une ligne par contenu, et ce que M8 a reçu
# ---------------------------------------------------------------------------
def _rang(contenu: dict[str, Any], ligne: dict[str, Any]) -> tuple[Any, ...]:
    """Ordre total, indépendant de l'ordre de réception : le plus de leads, puis de devis acceptés, puis de devis
    envoyés, puis le plus récent ; la clé et l'identifiant départagent."""
    instant = entonnoir.instant_lu(contenu.get("horodatage"))
    return (
        -(ligne["leads"] or 0), -(ligne["devis_acceptes"] or 0), -(ligne["devis_envoyes"] or 0),
        0 if instant is not None else 1, -(instant.timestamp() if instant is not None else 0.0),
        str(ligne["utm_content"]), str(contenu.get("contenu_id")),
    )


def lignes(attribution: dict[str, Any]) -> list[dict[str, Any]]:
    """Une ligne par contenu exporté : sa clé, son canal, son chantier, l'instant de l'export, comment il se mesure
    (``suivi``) et ses décomptes. Un décompte est ``None`` quand la mesure correspondante est non calculable (un manque
    dit alors lequel, dans les mesures) ou que le contenu ne se mesure pas (``sans_lien``, ``ambigu``) : jamais un zéro
    à la place de ce qu'on ne sait pas."""
    chaine_lue = bool(attribution["contenus"]) and attribution["leads"]["n_recus"] > 0
    devis_lus = chaine_lue and not attribution["entonnoir_vide"]
    rangees = []
    for contenu in attribution["contenus"]:
        cle = contenu.get("utm_content")
        suivi = suivi_du_contenu(contenu, attribution["cles_ambigues"])
        mesurable = suivi == SUIVI_LIEN
        ligne = {
            "utm_content": cle, "canal": contenu.get("canal"), "wct_id": contenu.get("wct_id"),
            "exporte_le": contenu.get("horodatage"), "suivi": suivi,
            "leads": attribution["leads_par_cle"][cle] if mesurable and chaine_lue else None,
            "devis_envoyes": attribution["devis_envoyes"]["par_cle"][cle] if mesurable and devis_lus else None,
            "devis_acceptes": attribution["devis_acceptes"]["par_cle"][cle] if mesurable and devis_lus else None,
        }
        rangees.append((_rang(contenu, ligne), ligne))
    return [ligne for _, ligne in sorted(rangees, key=lambda paire: paire[0])]


def _plus_recent(faits: list[dict[str, Any]]) -> str | None:
    """L'instant (tel que reçu) du fait le plus récent parmi ceux dont l'instant est lisible, sinon ``None``."""
    lisibles = [(entonnoir.instant_lu(fait.get("horodatage")), fait.get("horodatage")) for fait in faits]
    lisibles = [(instant, texte) for instant, texte in lisibles if instant is not None]
    return max(lisibles, key=lambda paire: paire[0])[1] if lisibles else None


def sources(faits: list[dict[str, Any]], entrees_entonnoir: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ce que M8 a reçu, par événement : combien de faits et l'instant du plus récent (la fraîcheur de la mesure, P2 :
    M8 n'a pas d'horloge, il dit jusqu'où vont ses faits). Zéro fait est dit zéro : le lecteur voit lui-même quelle
    source n'a rien livré. Les deux événements des devis sont ceux de l'entonnoir."""
    lignes_sources = []
    for evenement, type_entree, cle in (
        (EVENEMENT_CONTENU, TYPE_CONTENU_EXPORTE, "contenu_id"), (EVENEMENT_LEAD, TYPE_LEAD_M1, "lead_id"),
    ):
        du_type = [fait for fait in faits if fait.get("type_entree") == type_entree]
        lignes_sources.append({
            "evenement": evenement, "n": len(_uniques(du_type, type_entree, cle)),
            "dernier_fait_le": _plus_recent(du_type),
        })
    devis = {"m3.devis_envoye", "m3.devis_accepte"}
    lignes_sources.extend(ligne for ligne in entonnoir.sources(entrees_entonnoir) if ligne["evenement"] in devis)
    return lignes_sources


def situation(
    faits: list[dict[str, Any]], entrees_entonnoir: list[dict[str, Any]], definitions: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """La mesure par contenu telle que les faits reçus la permettent : mesures gouvernées, une ligne par contenu et ce
    que M8 a reçu. Lecture pure : ne publie rien."""
    attribution = attribuer(faits, entrees_entonnoir)
    return {
        "mesures": mesurer(attribution, definitions),
        "lignes": lignes(attribution),
        "sources": sources(faits, entrees_entonnoir),
    }


__all__ = [
    "EVENEMENT_CONTENU",
    "EVENEMENT_LEAD",
    "MODULE_DEFINITIONS",
    "STATUT_CALCULEE",
    "STATUT_NON_CALCULABLE",
    "SUIVI_AMBIGU",
    "SUIVI_LIEN",
    "SUIVI_SANS_LIEN",
    "TYPE_CONTENU_EXPORTE",
    "TYPE_LEAD_M1",
    "attribuer",
    "charger_definitions",
    "cles_unicite",
    "fait_contenu_exporte",
    "fait_lead_m1",
    "lignes",
    "mesurer",
    "situation",
    "sources",
    "suivi_du_contenu",
]
