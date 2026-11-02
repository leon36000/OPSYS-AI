"""Les routines que le planificateur durable déclenche pour M10 (docs/architecture/PLANIFICATION.md §10) : la logique
pure.

Trois travaux qui étaient des tours d'agent « à construire » ou des KPI déclarés mais jamais calculés :

1. **Énumérer les affaires touchées un jour** (`enumerer`) : lit le registre Événements, désigne chaque affaire
   (`lead_id` ou opportunité, forme fermée `affaire.py`) qui a reçu au moins un événement CE JOUR-LÀ, et dit
   lesquelles ont encore quelque chose à consolider (aucun fait durable, ou un fait qui ne cite pas toutes les
   sources du jour). Le critère est EXACTEMENT celui de `consolidation.consolider_affaire` (union des sources de
   tous les faits de la clé) : une affaire désignée « à consolider » donne un nouveau maillon, une autre n'en donne
   pas. Une affaire dont l'identifiant sort de la forme fermée (affaire forgée dans un événement) n'est jamais
   désignée : elle est comptée à part.
2. **L'audit hebdomadaire « non-oubli »** (`rapport_audit`) : des QUESTIONS-TESTS à réponse déterministe, chacune
   avec son numérateur et son dénominateur ou son compte, jamais un score opaque. L'attendu vient du bus (ce que le
   bus dit avoir livré à M10 : reçu « traité »), pas du manifeste (voir `audit.py`) ; un événement encore en attente
   de livraison, en échec ou en quarantaine est compté à part : ce n'est pas un oubli, c'est une livraison qui n'a
   pas fini.
3. **Les KPI du manifeste** (`kpis`) : ceux que les registres permettent de calculer le sont ; les autres sont dits
   « non calculables » avec ce qui manque (jamais zéro, jamais cent).

Module pur (DA-M10-08) : aucun import d'``opsys`` ; l'instant et les données du bus sont fournis par l'appelant.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from . import affaire, audit, classification, consolidation, etapes

TYPE_RAPPORT = "rapport_routine"
GENRE_AUDIT = "audit_non_oubli"
GENRE_KPIS = "kpis"
OUBLIS_MAX = 20  # le rapport garde la liste compacte des premiers oublis ; le reste est compté
LIMITE_MAX = 200
JOURS_AUDIT_DEFAUT, JOURS_AUDIT_MAX = 7, 90


def genres() -> tuple[str, ...]:
    """Les genres de rapport (une fonction, pas une constante publique : les gardes de conformité traitent une tuple en
    MAJUSCULES comme un énuméré métier)."""
    return (GENRE_AUDIT, GENRE_KPIS)


def kpi_ids() -> tuple[str, ...]:
    """Les cinq KPI du manifeste de M10, dans l'ordre où il les déclare."""
    return (
        "taux_revisions_arbitrees",
        "taux_preflight_insuffisant",
        "nb_references_forgees_detectees",
        "nb_affaires_consolidees_jour",
        "nb_oublis_detectes_audit",
    )


def instant(valeur: Any) -> datetime:
    if not isinstance(valeur, str):
        raise ValueError("REJ-HORODATAGE-INVALIDE: chaîne ISO-8601 requise")
    try:
        quand = datetime.fromisoformat(valeur)
    except (ValueError, OverflowError):
        raise ValueError("REJ-HORODATAGE-INVALIDE: format ISO-8601 invalide") from None
    if quand.tzinfo is None:
        raise ValueError("REJ-HORODATAGE-INVALIDE: fuseau horaire manquant")
    return quand


def empreinte(contenu: Any) -> str:
    return hashlib.sha256(
        json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# 1. Les affaires touchées un jour
# ---------------------------------------------------------------------------------------------------------------
def _evenements_par_affaire(
    jour: str, maillons: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, list[Mapping[str, Any]]], int]:
    """`({affaire: événements du jour}, refusées)` : une affaire par `lead_id` résolu, jamais devinée ; un identifiant
    qui sort de la forme fermée est compté dans `refusées` et ne désigne rien."""
    index_wct = classification.index_lead_id_par_wct_id(maillons)
    par_affaire: dict[str, list[Mapping[str, Any]]] = {}
    refusees = 0
    for maillon in maillons:
        if classification.type_evenement(maillon) is None:
            continue
        if consolidation.jour_de(maillon["horodatage"]) != jour:
            continue
        lead = classification.lead_id(maillon, index_wct)
        if lead is None:
            continue
        if not affaire.valide(lead):
            refusees += 1
            continue
        par_affaire.setdefault(lead, []).append(maillon)
    return par_affaire, refusees


def _a_consolider(
    affaire_id: str,
    jour: str,
    evenements_du_jour: Sequence[Mapping[str, Any]],
    faits: Mapping[str, list[Mapping[str, Any]]],
) -> bool:
    """Vrai si `consolider_affaire(affaire, jour)` écrirait un maillon : même règle que `consolidation.py`."""
    deja = faits.get(f"{affaire_id}:{jour}", [])
    if not deja:
        return True
    connues = {s.get("ligne_id") for fait in deja for s in fait.get("sources", [])}
    return bool({e["ligne_id"] for e in evenements_du_jour} - connues)


def _faits_par_cle(maillons_affaires: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    faits: dict[str, list[Mapping[str, Any]]] = {}
    for maillon in maillons_affaires:
        if maillon.get("type_entree") == consolidation.TYPE_ENTREE_FAIT:
            faits.setdefault(maillon.get("cle_consolidation"), []).append(maillon)
    return faits


def enumerer(
    jour: str,
    limite: int,
    maillons_evenements: Sequence[Mapping[str, Any]],
    maillons_affaires: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Les affaires touchées le `jour` (date telle qu'écrite au registre, comme la consolidation) et celles à
    consolider,
    triées (ordre stable : deux lectures du même état donnent la même liste). `a_consolider` est borné à `limite` ;
    `reste`
    dit ce qui attend le passage suivant."""
    par_affaire, refusees = _evenements_par_affaire(jour, maillons_evenements)
    faits = _faits_par_cle(maillons_affaires)
    touchees = sorted(par_affaire)
    pendantes = [a for a in touchees if _a_consolider(a, jour, par_affaire[a], faits)]
    return {
        "jour": jour,
        "touchees": len(touchees),
        "a_consolider": pendantes[:limite],
        "reste": max(0, len(pendantes) - limite),
        "deja_consolidees": len(touchees) - len(pendantes),
        "affaires_refusees": refusees,
    }


# ---------------------------------------------------------------------------------------------------------------
# 2. L'audit hebdomadaire « non-oubli »
# ---------------------------------------------------------------------------------------------------------------
def identifiant_attendu(type_evenement: str, charge: Mapping[str, Any]) -> str | None:
    """La clé publique par laquelle M10 garde un fait (voir `classification.identifiant`), lue de la charge du bus.
    `None` si la charge n'a pas la forme que M10 accepte : le consommateur l'aurait refusée, ce n'est pas un oubli."""
    if type_evenement == classification.TYPE_WCT:
        cle = charge.get("wct_id")
    elif type_evenement in (classification.TYPE_VARIANCE, classification.TYPE_RENTABILITE):
        cle = charge.get("evenement_id")
    else:
        etape = etapes.etape(type_evenement)
        if etape is None:
            return None
        try:
            cle = etape.extraire(charge).get(etape.cle)
        except etapes.ChampRefuse:
            return None
    return cle if isinstance(cle, str) and cle else None


def attendus_du_bus(publications: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """`publications` : `{type_evenement, charge, recu}` où `recu` est le statut du reçu de M10 (`traite`, `echec`,
    `quarantaine`) ou `None` (pas encore livré). Seul un événement `traite` est ATTENDU au registre."""
    attendus: list[dict[str, str]] = []
    compte = {"en_attente": 0, "en_echec": 0, "quarantaine": 0, "refuses_par_forme": 0, "hors_perimetre": 0}
    audites = set(audit.types_audites())
    for publication in publications:
        type_evenement = publication["type_evenement"]
        if type_evenement not in audites:
            compte["hors_perimetre"] += 1
            continue
        recu = publication.get("recu")
        if recu == "echec":
            compte["en_echec"] += 1
        elif recu == "quarantaine":
            compte["quarantaine"] += 1
        elif recu != "traite":
            compte["en_attente"] += 1
        else:
            identifiant = identifiant_attendu(type_evenement, publication["charge"])
            if identifiant is None:
                compte["refuses_par_forme"] += 1
            else:
                attendus.append({"type_evenement": type_evenement, "identifiant": identifiant})
    return {"attendus": attendus, "livraison": compte}


def _revisions_en_attente(maillons_affaires: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """`(signalées, arbitrées)` : un signalement est une ligne `revision_signalee` qui désigne deux lignes ; il est
    arbitré dès qu'une ligne d'arbitrage le désigne. Les traces de préflight (qui n'ont pas de paire de lignes) n'en
    sont
    pas."""
    signalees = {
        m["ligne_id"]
        for m in maillons_affaires
        if m.get("type_entree") == "revision_signalee" and m.get("ligne_id_a") is not None
    }
    arbitrees = {
        m.get("revision_ligne_id")
        for m in maillons_affaires
        if m.get("type_entree") == "revision_signalee"
        and m.get("ligne_id_a") is None
        and m.get("revision_ligne_id") in signalees
    }
    return len(signalees), len(arbitrees)


def rapport_audit(
    fin: str,
    jours: int,
    bus: Mapping[str, Any],
    maillons_evenements: Sequence[Mapping[str, Any]],
    maillons_affaires: Sequence[Mapping[str, Any]],
    registres: Mapping[str, Any],
) -> dict[str, Any]:
    """Le rapport d'audit : des questions-tests déterministes. `registres` porte les deux objets `Registre` (pour la
    validation des chaînes, `audit.auditer_non_oubli`) ; `bus` est le résultat de `attendus_du_bus`."""
    resultat = audit.auditer_non_oubli(bus["attendus"], registres["evenements"], registres["affaires"])
    fin_dt = instant(fin)
    debut = (fin_dt - timedelta(days=jours)).date().isoformat()
    jour_fin = fin_dt.date().isoformat()
    # -- les jours à consolider : chaque (affaire, jour) d'événements de la fenêtre, avant le jour de l'audit
    faits = _faits_par_cle(maillons_affaires)
    paires = 0
    non_consolidees: list[str] = []
    jours_vus = sorted(
        {
            consolidation.jour_de(m["horodatage"])
            for m in maillons_evenements
            if classification.type_evenement(m) is not None
        }
    )
    for jour in (j for j in jours_vus if debut <= j < jour_fin):
        par_affaire, _ = _evenements_par_affaire(jour, maillons_evenements)
        for lead, evenements in par_affaire.items():
            paires += 1
            if _a_consolider(lead, jour, evenements, faits):
                non_consolidees.append(jour)
    signalees, arbitrees = _revisions_en_attente(maillons_affaires)
    instants = [instant(m["horodatage"]) for m in maillons_evenements if classification.type_evenement(m)]
    dernier = max(0, int((fin_dt - max(instants)).total_seconds() // 3600)) if instants else None
    traces = resultat["total_attendus"] - resultat["nb_oublis"]
    questions = [
        {
            "id": "trace_des_evenements_livres",
            "question": "Chaque événement que le bus a livré à M10 (reçu traité) a-t-il sa trace au registre "
            "Événements ?",
            "numerateur": traces,
            "denominateur": resultat["total_attendus"],
            "reponse": None if resultat["total_attendus"] == 0 else resultat["nb_oublis"] == 0,
            "note": "aucun événement attendu : rien n'a été vérifié" if resultat["total_attendus"] == 0 else "",
        },
        {
            "id": "chaines_intactes",
            "question": "Les chaînes de hachage des registres Événements et Affaires sont-elles intactes ?",
            "reponse": bool(resultat["chaine_evenements_intacte"] and resultat["chaine_affaires_intacte"]),
        },
        {
            "id": "jours_consolides",
            "question": "Chaque couple (affaire, jour) d'événements de la fenêtre, avant le jour de l'audit, a-t-il "
            "un fait durable qui cite toutes ses sources ?",
            "numerateur": paires - len(non_consolidees),
            "denominateur": paires,
            "reponse": None if paires == 0 else not non_consolidees,
            "plus_ancien_non_consolide": min(non_consolidees) if non_consolidees else None,
        },
        {
            "id": "revisions_en_attente",
            "question": "Combien de révisions signalées attendent un arbitrage humain ?",
            "valeur": signalees - arbitrees,
        },
        {
            "id": "fraicheur_memoire",
            "question": "Quel est l'âge, en heures, du dernier événement mémorisé (selon l'instant de l'événement) ?",
            "heures": dernier,
        },
    ]
    return {
        "fin": fin,
        "jours": jours,
        "fenetre": {"debut": debut, "fin": jour_fin},
        "total_attendus": resultat["total_attendus"],
        "nb_oublis": resultat["nb_oublis"],
        "oublis": resultat["oublis"][:OUBLIS_MAX],
        "oublis_omis": max(0, resultat["nb_oublis"] - OUBLIS_MAX),
        "livraison": bus["livraison"],
        "questions": questions,
    }


# ---------------------------------------------------------------------------------------------------------------
# 3. Les KPI du manifeste
# ---------------------------------------------------------------------------------------------------------------
def dernier_rapport(maillons: Iterable[Mapping[str, Any]], genre: str) -> Mapping[str, Any] | None:
    trouves = [m for m in maillons if m.get("type_entree") == TYPE_RAPPORT and m.get("genre") == genre]
    return trouves[-1] if trouves else None


def kpis(
    jour: str,
    debut_cycle: str,
    fin_cycle: str,
    maillons_affaires: Sequence[Mapping[str, Any]],
    rapports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Les cinq KPI du manifeste. `[debut_cycle, fin_cycle[` est la journée locale du cycle de consolidation (fournie
    par l'appelant, qui connaît le fuseau) ; `rapports` : le registre des rapports (dernier audit)."""
    debut_dt, fin_dt = instant(debut_cycle), instant(fin_cycle)
    signalees, arbitrees = _revisions_en_attente(maillons_affaires)
    affaires_du_cycle = {
        m["affaire_id"]
        for m in maillons_affaires
        if m.get("type_entree") == consolidation.TYPE_ENTREE_FAIT and debut_dt <= instant(m["horodatage"]) < fin_dt
    }
    refus_preflight = sum(
        1
        for m in maillons_affaires
        if m.get("type_entree") == "revision_signalee" and m.get("code_verdict") is not None
    )
    audit_recent = dernier_rapport(rapports, GENRE_AUDIT)
    resultat: dict[str, Any] = {
        "taux_revisions_arbitrees": (
            {
                "calculable": True,
                "valeur_pct": round(100 * arbitrees / signalees, 1),
                "numerateur": arbitrees,
                "denominateur": signalees,
            }
            if signalees
            else {"calculable": False, "manque": "aucune révision signalée : un taux sur zéro n'existe pas"}
        ),
        "taux_preflight_insuffisant": {
            "calculable": False,
            "refus_traces": refus_preflight,
            "manque": "seuls les refus du préflight sont tracés au registre ; les dossiers jugés suffisants ne le "
            "sont pas, donc le nombre de dossiers soumis (dénominateur) est inconnu",
        },
        "nb_references_forgees_detectees": {
            "calculable": False,
            "manque": "une référence rejetée par m10_verifier_reference n'est pas consignée : aucun compte n'existe",
        },
        "nb_affaires_consolidees_jour": {"calculable": True, "valeur": len(affaires_du_cycle), "jour": jour},
        "nb_oublis_detectes_audit": (
            {"calculable": True, "valeur": audit_recent["contenu"]["nb_oublis"], "audit_du": audit_recent["fin"]}
            if audit_recent
            else {"calculable": False, "manque": "aucun audit « non-oubli » n'a encore été consigné"}
        ),
    }
    return {"jour": jour, "cycle": {"debut": debut_cycle, "fin": fin_cycle}, "kpis": resultat}
