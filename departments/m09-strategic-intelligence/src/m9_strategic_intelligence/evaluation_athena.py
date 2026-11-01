"""Évaluation d'Athéna (M9, couche déterministe des nouvelles lectures) : un jeu de cas versionné, des attentes écrites
avant l'exécution, des échecs conservés. Nouveau fichier : ``evals/corpus-athena-v1.json``.

Les trois corpus existants de M9 (``corpus-v1``, ``corpus-metier-v1``, ``corpus-metier-v2``) ne sont ni réécrits ni
déplacés : leurs empreintes ne changent pas. Celui-ci mesure ce qu'Athéna a ajouté :

* ``contrat_charge`` — le contrat des charges des producteurs raccordés (M8 synthèse de direction, M2 pipeline et
  prévision, M5, M10) : une charge qui viole son contrat est REFUSÉE et le refus nomme le champ ;
* ``certitude_fait`` — le statut de certitude d'un fait lu (établi, essai, indéterminé, périmé, prévision) d'après ce
que
  le producteur déclare ;
* ``tableau`` — le tableau de direction sur des captures : « indéterminé » plutôt qu'estimé, jamais un essai ou une
  prévision rendus comme certains, jamais une prévision sans intervalle ;
* ``recommandation`` — le contrôle d'une recommandation : chiffre sourcé, statut non gonflé, aucune décision prétendue,
  abstention sur donnée bloquante, mention professionnelle, injection dans un fait lu sans effet ;
* ``boucle`` — décision → résultat mesuré → leçon : concordance, non mesurable et sa raison, jamais une cause ;
* ``priorite`` — la hiérarchisation de ce qui exige la direction.

Module pur. La mesure porte sur la COUCHE DÉTERMINISTE (``modele_reel`` : faux) : aucune sortie de modèle réel n'est
évaluée, la qualification d'Athéna par un modèle réel reste OUVERTE. Même rapport que ``evaluation`` : par catégorie,
effectif, réussites, taux, intervalle de Wilson à 95 %, échecs listés avec l'attendu et l'observé.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping

from . import (
    boucle_decisions,
    charges_producteurs,
    dossier_strategique,
    priorites_direction,
    recommandation_gouvernee,
    tableau_direction,
)
from . import capture_strategique as cs
from . import catalogue_producteurs as cat
from . import certitude as ct
from .evaluation import wilson

VERSION = "2026-11-01.1"
CATEGORIES = ("contrat_charge", "certitude_fait", "tableau", "recommandation", "boucle", "priorite")
BIAIS_CONNUS = (
    "corpus fictif, rédigé en français par un seul auteur : aucune diversité d'auteurs ni de formulations",
    "petit effectif par catégorie : les intervalles sont larges, un taux élevé ne vaut pas confiance générale",
    "couche déterministe seulement : aucune sortie de modèle réel, ni fidélité ni hallucination de modèle mesurées",
    "les pages sont celles que les vrais producteurs rendent sur des données fictives ; un producteur qui change de "
    "forme "
    "est refusé (clé inconnue), pas deviné",
    "les attentes suivent les règles écrites du SOUL et des contrats ; une règle absente n'est pas testée",
)


def _capturer(specs: list[Mapping]) -> list[dict]:
    """Chaîne de captures construite par le VRAI constructeur (contrat rejoué, empreintes, chaînage)."""
    chaine: list[dict] = []
    for spec in specs:
        lecture = cat.PAR_ID[spec["lecture_id"]]
        arguments = dict(spec["arguments"])
        reference = arguments.get(lecture.reference) if lecture.reference else None
        chaine.append(
            cs.construire(
                lecture, arguments, [spec["page"]], recu_a=spec["recu_a"], reference=reference, index=len(chaine),
                hash_precedent=chaine[-1]["hash_maillon"] if chaine else cs.HASH_INITIAL,
                dernier_recu_a=chaine[-1]["recu_a"] if chaine else None,
            )
        )  # fmt: skip
    return chaine


def _contrat_charge(entree: Mapping) -> dict:
    erreurs = charges_producteurs.valider(entree["lecture_id"], entree["page"], entree["arguments"])
    if not erreurs:
        return {"verdict": "CONFORME"}
    return {"verdict": "REFUSEE", "nomme": erreurs[0].split(" :", 1)[0]}


def _certitude_fait(entree: Mapping) -> dict:
    (capture,) = _capturer([{**entree, "recu_a": entree.get("recu_a", "2026-10-28T12:00:01Z")}])
    if capture["verdict"] != "ACCEPTEE":
        return {"verdict": "REFUSEE"}
    return {"verdict": ct.statut_du_fait(ct.classer_faits(capture), entree["chemin"])}


def _tableau(entree: Mapping) -> dict:
    chaine = _capturer(entree["captures"])
    tableau = tableau_direction.composer(chaine, maintenant=entree["maintenant"], alertes_m8=entree.get("alertes"))
    section = tableau["sections"][entree["section"]]
    return {
        "verdict": section["certitude"],
        "certain": section["certain"],
        "valeurs": [ligne["valeur"] for ligne in section["lignes"]],
        "certains": [ligne["libelle"] for ligne in section["lignes"] if ligne["certain"]],
    }


def _verifier_recu_corpus(recu: Mapping) -> tuple[bool, str]:
    """Vérificateur du corpus : l'empreinte est celle du contenu (le pont du socle fait la même chose avec M5)."""
    sans = {k: v for k, v in recu.items() if k != "empreinte"}
    ok = recu.get("empreinte") == hashlib.sha256(json.dumps(sans, sort_keys=True).encode()).hexdigest()
    return ok, "" if ok else "empreinte incohérente"


def _recommandation(entree: Mapping) -> dict:
    chaine = _capturer(entree["captures"])
    dossier = dossier_strategique.construire(
        chaine, question="évaluation", domaines=["strategie"], reference=entree["connaissance"],
        connaissance=entree["connaissance"], max_faits=10**6,
    )  # fmt: skip
    utilises = {(u["index"], u["hash_maillon"]) for u in dossier["captures_utilisees"]}
    utiles = [c for c in cs.connues_a(chaine, entree["connaissance"]) if (c["index"], c["hash_maillon"]) in utilises]
    recus = {r["empreinte"]: r for r in entree.get("recus", [])}
    try:
        resultat = recommandation_gouvernee.controler(
            entree["recommandation"], faits=dossier["faits"], certitudes=ct.certitude_des_faits(utiles), recus=recus,
            verifier_recu=_verifier_recu_corpus,
        )  # fmt: skip
    except ValueError as exc:
        return {"verdict": "REFUSE", "code": str(exc).split(" :", 1)[0]}
    return {"verdict": "ADMIS", "abstention": resultat["abstention"],
        "professionnels": resultat["domaines_professionnels"]}


def _boucle(entree: Mapping) -> dict:
    chaine = _capturer(entree["captures"])
    decision = entree["decision"]
    maillon = boucle_decisions.declarer(
        [], decision_id="dec-eval", enonce=decision["enonce"], attendus=decision["attendus"], captures=chaine,
        decide_par="proprio.fictif", decide_role="nathan_owner", decide_le=decision["decide_le"],
    )  # fmt: skip
    ajouts = boucle_decisions.mesurer([maillon], "dec-eval", captures=chaine, maintenant=entree["mesure_le"])
    resultat = ajouts[0]
    return {
        "verdict": resultat["concordance"],
        "raisons": [o["raison"] for o in resultat["observations"]],
        "lecon_proposee": any(a["type"] == "LECON" for a in ajouts),
        "lecon_sans_cause": all("Aucune cause" in a["texte"] for a in ajouts if a["type"] == "LECON"),
    }


def _priorite(entree: Mapping) -> dict:
    classement = priorites_direction.hierarchiser(entree["decisions"], maintenant=entree["maintenant"])
    return {"verdict": "ORDRE", "ids": [e["id"] for e in classement["elements"]]}


RUNNERS: dict[str, Callable[[Mapping], dict]] = {
    "contrat_charge": _contrat_charge,
    "certitude_fait": _certitude_fait,
    "tableau": _tableau,
    "recommandation": _recommandation,
    "boucle": _boucle,
    "priorite": _priorite,
}


def _executer(cas: Mapping) -> dict:
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
        ecarts = _ecarts(cas["attente"], _executer(cas))
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
            "effectif": n, "reussites": ok, "taux": f"{(ok / n) if n else 0:.4f}", "wilson95": [bas, haut],
            "echecs": bloc["echecs"],
        }  # fmt: skip
        total_n += n
        total_ok += ok
    bas, haut = wilson(total_ok, total_n)
    return {
        "type": "EVALUATION_ATHENA",
        "version": VERSION,
        "corpus": corpus.get("version"),
        "corpus_sha256": hashlib.sha256(
            json.dumps(corpus, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest(),
        "portee": "couche déterministe d'Athéna (contrat des charges, certitude, tableau, recommandation, boucle, "
                  "priorité)",
        "modele_reel": False,
        "par_categorie": resume,
        "global": {
            "effectif": total_n, "reussites": total_ok, "taux": f"{(total_ok / total_n):.4f}", "wilson95": [bas, haut],
            "echecs_total": total_n - total_ok,
        },  # fmt: skip
        "cout_modele": {"tokens": 0, "raison": "aucun appel de modèle : couche déterministe seulement"},
        "biais_connus": list(BIAIS_CONNUS),
        "limites": [
            "Un taux élevé sur un petit effectif ne prouve ni l'absence d'hallucination ni une confiance générale.",
            "La qualification d'Athéna avec un modèle réel reste ouverte et séparée de cette mesure.",
        ],
    }
