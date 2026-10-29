"""Évaluation et confiance M9.23 : un jeu de cas versionné, des attentes écrites avant l'exécution, des échecs
conservés.

Module pur. Le corpus (``evals/corpus-v1.json``) est rédigé à la main : chaque cas porte une ENTRÉE, une ATTENTE dérivée
d'une
règle du contrat (pas de la sortie du code) et sa justification. ``evaluer`` fait tourner chaque cas dans la vraie
couche
déterministe de M9 (admission des propositions du conseil, gouvernance, sémantique des métriques, abstention sur donnée
manquante) et compare : verdict, code de refus, et les champs ``extra`` attendus.

Ce que la mesure dit — et ne dit pas :

* elle porte sur la COUCHE DÉTERMINISTE (``modele_reel`` : faux) : aucune sortie de modèle réel n'est évaluée ici, la
  qualification du conseil avec un modèle reste une dépendance ouverte, séparée de ce double de protocole ;
* elle rend, par catégorie, l'effectif, les réussites, le taux et un intervalle de Wilson à 95 % ; les ÉCHECS sont
listés avec
  l'attendu et l'observé, jamais effacés ni moyennés ;
* un taux de 100 % sur un petit effectif n'établit ni « zéro hallucination » ni une confiance générale : l'intervalle le
montre,
  et ``biais_connus`` nomme ce que le corpus ne couvre pas ;
* aucun auto-jugement unique : les attentes sont indépendantes du code mesuré, et un second oracle naïf recoupe les cas
de
  citation (voir les tests).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence

from . import conseil, occasions, playbooks, previsions, priorisation, semantique_metriques

VERSION = "2026-10-28.1"
CATEGORIES = (
    "fidelite_citation",
    "inference",
    "demandes_et_injection",
    "gouvernance",
    "semantique",
    "abstention_donnees_manquantes",
)
BIAIS_CONNUS = (
    "corpus fictif, rédigé en français par un seul auteur : aucune diversité d'auteurs ni de formulations",
    "petit effectif par catégorie : les intervalles sont larges, un taux élevé ne vaut pas confiance générale",
    "couche déterministe seulement : aucune sortie de modèle réel, ni fidélité ni hallucination de modèle mesurées",
    "les attentes suivent les règles écrites du contrat ; une règle absente du contrat n'est pas testée",
)


def _admission(entree: Mapping) -> dict:
    admise = conseil.admettre_proposition(entree["sortie"], sources=entree["sources"])
    return {
        "verdict": "ADMIS",
        "demandes_ecartees": admise["demandes_ecartees"],
        "validation_semantique": admise["validation_semantique"],
    }


def _gouvernance(entree: Mapping) -> dict:
    verdict = conseil.gouverner({"decision": entree["decision"], "actions": entree["actions"]})
    premiere = verdict["actions"][0]
    return {
        "verdict": premiere["verdict"],
        "mandataire": premiere["mandataire"],
        "effet_autorise": premiere["effet_autorise"],
    }


def _semantique(entree: Mapping) -> dict:
    catalogue = semantique_metriques.cataloguer(entree["definitions"])
    return {"verdict": semantique_metriques.classer(entree["observation"], catalogue)["statut"]}


def _abstention(entree: Mapping) -> dict:
    genre = entree["kind"]
    if genre == "priorisation":
        resultat = priorisation.allouer(entree["candidats"], capacite=entree["capacite"])
        if resultat["allocation"]["statut"] == "CAPACITE_INCONNUE":
            return {"verdict": "CAPACITE_INCONNUE"}
        non = resultat["non_retenus"]
        return {"verdict": "NON_RETENU", "raison": non[0]["raison"]} if non else {"verdict": "RETENU"}
    if genre == "occasion":
        res = occasions.evaluer([entree["occasion"]], {}, [], connaissance="2026-10-28T13:00:00Z")
        return {"verdict": res["occasions"][0]["statut"]}
    if genre == "prevision":
        res = previsions.consolider([], connaissance="2026-10-28T13:00:00Z")
        return {"verdict": next(d for d in res["domaines"] if d["domaine"] == entree["domaine"])["statut"]}
    if genre == "playbook":
        plan = playbooks.instancier(entree["playbook"], None, connaissance="2026-10-28T13:00:00Z")
        return {"verdict": plan["declenchement"]["statut"]}
    raise ValueError(f"REJ-EVAL-CAS : genre d'abstention inconnu {genre!r}")


RUNNERS: dict[str, Callable[[Mapping], dict]] = {
    "fidelite_citation": _admission,
    "inference": _admission,
    "demandes_et_injection": _admission,
    "gouvernance": _gouvernance,
    "semantique": _semantique,
    "abstention_donnees_manquantes": _abstention,
}


def _executer(cas: Mapping) -> dict:
    """Résultat observé : verdict (ADMIS/REFUSE ou statut métier), code de refus, champs additionnels."""
    try:
        return RUNNERS[cas["categorie"]](cas["entree"])
    except ValueError as exc:
        message = str(exc)
        code = message.split(" :", 1)[0] if message.startswith("REJ-") else "ERREUR-NON-NOMMEE"
        return {"verdict": "REFUSE", "code": code}


def _ecarts(attente: Mapping, observe: Mapping) -> list[str]:
    ecarts = []
    if observe.get("verdict") != attente["verdict"]:
        ecarts.append(f"verdict : attendu {attente['verdict']!r}, observé {observe.get('verdict')!r}")
    if "code" in attente and observe.get("code") != attente["code"]:
        ecarts.append(f"code : attendu {attente['code']!r}, observé {observe.get('code')!r}")
    for cle, valeur in attente.get("extra", {}).items():
        reel = observe.get(cle)
        if reel != valeur:
            ecarts.append(f"{cle} : attendu {valeur!r}, observé {reel!r}")
    return ecarts


def wilson(reussites: int, effectif: int) -> tuple[str, str]:
    """Intervalle de Wilson à 95 % (4 décimales) ; effectif nul : intervalle non défini (« 0.0000 », « 1.0000 »)."""
    if effectif == 0:
        return "0.0000", "1.0000"
    z = 1.959963984540054
    p = reussites / effectif
    centre = (p + z * z / (2 * effectif)) / (1 + z * z / effectif)
    marge = z * math.sqrt(p * (1 - p) / effectif + z * z / (4 * effectif * effectif)) / (1 + z * z / effectif)
    return f"{max(0.0, centre - marge):.4f}", f"{min(1.0, centre + marge):.4f}"


def valider_corpus(corpus: object) -> list[dict]:
    if not isinstance(corpus, Mapping) or not isinstance(corpus.get("cas"), list) or not corpus["cas"]:
        raise ValueError("REJ-EVAL-CORPUS : corpus {version, cas[]} requis")
    ids: set[str] = set()
    for cas in corpus["cas"]:
        if (
            not isinstance(cas, Mapping)
            or not {"id", "categorie", "entree", "attente", "justification", "regle"} <= set(cas)
            or cas["categorie"] not in CATEGORIES
            or cas["id"] in ids
            or not isinstance(cas["attente"], Mapping)
            or "verdict" not in cas["attente"]
            or not str(cas["justification"]).strip()
            or not str(cas["regle"]).strip()
        ):
            raise ValueError(f"REJ-EVAL-CORPUS : cas invalide {cas.get('id') if isinstance(cas, Mapping) else cas!r}")
        ids.add(cas["id"])
    return list(corpus["cas"])


def evaluer(corpus: Mapping) -> dict:
    cas_liste = valider_corpus(corpus)
    par_categorie: dict[str, dict] = {c: {"effectif": 0, "reussites": 0, "echecs": []} for c in CATEGORIES}
    for cas in cas_liste:
        observe = _executer(cas)
        ecarts = _ecarts(cas["attente"], observe)
        bloc = par_categorie[cas["categorie"]]
        bloc["effectif"] += 1
        if ecarts:
            bloc["echecs"].append({"id": cas["id"], "ecarts": ecarts, "regle": cas["regle"]})
        else:
            bloc["reussites"] += 1
    resume = {}
    total_n = total_ok = 0
    for categorie, bloc in par_categorie.items():
        n, ok = bloc["effectif"], bloc["reussites"]
        bas, haut = wilson(ok, n)
        resume[categorie] = {
            "effectif": n,
            "reussites": ok,
            "taux": f"{(ok / n) if n else 0:.4f}",
            "wilson95": [bas, haut],
            "echecs": bloc["echecs"],
        }
        total_n += n
        total_ok += ok
    bas, haut = wilson(total_ok, total_n)
    rapport = {
        "type": "EVALUATION_M9",
        "version": VERSION,
        "corpus": corpus.get("version"),
        "corpus_sha256": hashlib.sha256(
            json.dumps(corpus, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest(),
        "portee": "couche déterministe de M9 (admission, gouvernance, sémantique, abstention)",
        "modele_reel": False,
        "par_categorie": resume,
        "global": {
            "effectif": total_n,
            "reussites": total_ok,
            "taux": f"{(total_ok / total_n):.4f}",
            "wilson95": [bas, haut],
            "echecs_total": total_n - total_ok,
        },
        "cout_modele": {"tokens": 0, "raison": "aucun appel de modèle : couche déterministe seulement"},
        "biais_connus": list(BIAIS_CONNUS),
        "limites": [
            "Un taux élevé sur un petit effectif ne prouve ni l'absence d'hallucination ni une confiance générale.",
            "La qualification du conseil avec un modèle réel reste ouverte et séparée de cette mesure.",
        ],
    }
    return rapport


def categories_couvertes(cas_liste: Sequence[Mapping]) -> dict[str, int]:
    effectifs: dict[str, int] = {}
    for cas in cas_liste:
        effectifs[cas["categorie"]] = effectifs.get(cas["categorie"], 0) + 1
    return effectifs
