"""Réaudit d'une session de conseil M9.4/M9.23 : ses citations tiennent-elles face aux captures plus récentes ?

Module pur et déterministe. Au dépôt, une citation de modèle est admise si l'adresse et la valeur sont EXACTES dans la
capture citée (immuable). Plus tard, une capture plus récente de la même lecture peut dire autre chose : la
recommandation repose alors sur une source dépassée. Ce module le dit, sans rien corriger ni recommander :

* ``A_JOUR`` — la valeur citée est celle de la capture la plus récente, complète et non contradictoire, de la
  même lecture (mêmes arguments) connue à ``connaissance`` ;
* ``SOURCE_PLUS_RECENTE_DIFFERENTE`` — une capture plus récente porte une autre valeur à la même place ;
* ``PLUS_RECENTE_SANS_LE_FAIT`` — la capture plus récente n'a plus ce fait ;
* ``CAPTURE_INTROUVABLE`` / ``VALEUR_DIFFERENTE_DANS_LA_CAPTURE`` — la capture citée n'existe pas ou ne porte pas
  la valeur citée (registre altéré ou citation falsifiée : ne doit jamais arriver après un dépôt admis).

Les inférences qui s'appuient sur une citation dépassée (directement ou par leurs prémisses) et la recommandation
qui les cite sont marquées ``A_REVOIR``. Le réaudit ne dit jamais que le conseil avait tort : il dit que sa source
a changé.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import criteres, plans, sessions_conseil

VERSION = "2026-10-29.1"
STATUTS_A_REVOIR = frozenset(
    {
        "SOURCE_PLUS_RECENTE_DIFFERENTE",
        "PLUS_RECENTE_SANS_LE_FAIT",
        "CAPTURE_INTROUVABLE",
        "VALEUR_DIFFERENTE_DANS_LA_CAPTURE",
    }
)
MAX_LIGNES = 30
_LIMITES = (
    "Le réaudit compare des valeurs citées à des captures plus récentes : il ne juge ni la vérité ni le raisonnement.",
    "Une source qui a changé n'invalide pas le conseil : elle le rend à revoir par la personne.",
)


def _valeur(capture: Mapping, page: int, chemin: str) -> str | None:
    if page >= len(capture["pages"]):
        return None
    brute = plans.valeur_a(capture["pages"][page], chemin)
    return None if brute is None else criteres.texte(brute)


def _citation(
    captures: Sequence[Mapping], connues: Sequence[Mapping], en_conflit: set, reference: str, valeur: str
) -> dict:
    parties = plans.ADRESSE.fullmatch(reference)
    ligne: dict = {"reference": reference, "valeur_citee": valeur}
    if parties is None:
        return ligne | {"statut": "CAPTURE_INTROUVABLE", "detail": "adresse illisible"}
    rang, page, chemin, lecture = int(parties["rang"]), int(parties["page"]), parties["chemin"], parties["lecture"]
    citee = next((c for c in captures if c["index"] == rang and c["lecture_id"] == lecture), None)
    if citee is None:
        return ligne | {"statut": "CAPTURE_INTROUVABLE", "detail": "aucune capture à ce rang pour cette lecture"}
    if _valeur(citee, page, chemin) != valeur:
        return ligne | {"statut": "VALEUR_DIFFERENTE_DANS_LA_CAPTURE", "valeur_capture": _valeur(citee, page, chemin)}
    plus_recentes = [
        c
        for c in connues
        if c["lecture_id"] == lecture
        and c["arguments_sha256"] == citee["arguments_sha256"]
        and c["index"] > rang
        and c["verdict"] == "ACCEPTEE"
        and c["complete"]
        and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
    ]
    if not plus_recentes:
        return ligne | {"statut": "A_JOUR", "capture_la_plus_recente": rang}
    derniere = plus_recentes[-1]
    actuelle = _valeur(derniere, page, chemin)
    adresse = f"{lecture}#{derniere['index']}:p{page}.{chemin}"
    if actuelle is None:
        return ligne | {"statut": "PLUS_RECENTE_SANS_LE_FAIT", "capture_la_plus_recente": derniere["index"]}
    if actuelle != valeur:
        return ligne | {
            "statut": "SOURCE_PLUS_RECENTE_DIFFERENTE",
            "capture_la_plus_recente": derniere["index"],
            "adresse_plus_recente": adresse,
            "valeur_plus_recente": actuelle,
        }
    return ligne | {"statut": "A_JOUR", "capture_la_plus_recente": derniere["index"]}


def reauditer(
    evenements: Sequence[Mapping], captures: Sequence[Mapping], *, session_id: str, connaissance: str
) -> dict:
    """Réaudit des citations admises d'une session, à ``connaissance`` (les captures connues alors)."""
    if cs.instant(connaissance) is None:
        raise ValueError("REJ-REAUDIT-TEMPS : instant avec fuseau explicite requis")
    projection = sessions_conseil.etat(evenements, session_id)
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    citations: list[dict] = []
    inferences: list[dict] = []
    recommandation: Mapping | None = None
    for tour in projection["tours"]:
        proposition = tour.get("proposition")
        if not isinstance(proposition, Mapping):
            continue
        statuts: dict[str, str] = {}
        for a in proposition["affirmations"]:
            if a["nature"] == "observation_source":
                ligne = {"role": tour["role"], "id": a["id"]} | _citation(
                    captures, connues, en_conflit, a["reference"], a["valeur"]
                )
                citations.append(ligne)
                statuts[a["id"]] = ligne["statut"]
        # une inférence est à revoir si une de ses prémisses l'est, directement ou par une autre inférence
        revues = {i for i, s in statuts.items() if s in STATUTS_A_REVOIR}
        for a in proposition["affirmations"]:
            if a["nature"] == "inference" and any(p in revues for p in a["premisses"]):
                revues.add(a["id"])
                inferences.append(
                    {"role": tour["role"], "id": a["id"], "statut": "A_REVOIR", "premisses": a["premisses"]}
                )
        if tour["role"] == "conseiller_pdg" and isinstance(proposition.get("recommandation"), Mapping):
            cites = proposition["recommandation"].get("refs", [])
            recommandation = {
                "role": tour["role"],
                "refs": cites,
                "statut": "A_REVOIR" if any(r in revues for r in cites) else "ANCREE_SUR_DES_SOURCES_A_JOUR",
            }
    par_statut: dict[str, int] = {}
    for ligne in citations:
        par_statut[ligne["statut"]] = par_statut.get(ligne["statut"], 0) + 1
    a_revoir = [ligne for ligne in citations if ligne["statut"] in STATUTS_A_REVOIR]
    resultat = {
        "type": "REAUDIT_CONSEIL",
        "version": VERSION,
        "session_id": session_id,
        "connaissance": connaissance,
        "citations_total": len(citations),
        "par_statut": par_statut,
        "citations_a_revoir": a_revoir[:MAX_LIGNES],
        "citations_a_revoir_total": len(a_revoir),
        "inferences_a_revoir": inferences[:MAX_LIGNES],
        "recommandation": recommandation,
        "verdict": "A_REVOIR" if a_revoir else "SOURCES_A_JOUR" if citations else "AUCUNE_CITATION",
        "limites": list(_LIMITES),
    }
    resultat["reaudit_id"] = hashlib.sha256(
        json.dumps(resultat, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return resultat
