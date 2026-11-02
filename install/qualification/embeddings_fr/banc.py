#!/usr/bin/env python3
"""Banc de mesure des embeddings sur un corpus FICTIF en français québécois (données : docs/qualification/).

Ce que le banc fait : embed le corpus et les requêtes par la passerelle LiteLLM de test (`/v1/embeddings`), met les
vecteurs en cache disque HORS dépôt, classe par similarité cosinus, par BM25 local (SQLite FTS5 du dépôt) et par fusion
RRF des deux, puis calcule rappel@1/5/10, MRR@10, nDCG@10 (jugements gradués), intervalles de confiance à 95 % par
rééchantillonnage des questions, écarts appariés, robustesse aux fautes (mêmes requêtes perturbées), séparation des
questions sans réponse, latence p50/p95, jetons, coût estimé, taille des vecteurs. Option : reclassement des 10 premiers
par un petit modèle de discussion utilisé comme juge de pertinence.

Ce que le banc ne fait pas : prouver la qualité en production. Corpus fictif écrit par une seule main, petit, jugements
binaires/gradués faits à la main : voir docs/qualification/MESURE-EMBEDDINGS-FR-2026-11.md pour les limites.

Usage (depuis la racine du dépôt, venv du dépôt) :
  python install/qualification/embeddings_fr/banc.py verifier
  OPSYS_LITELLM_TEST_URL=http://127.0.0.1:14400 OPSYS_LITELLM_TEST_KEY_FILE=/chemin/cle \\
      python install/qualification/embeddings_fr/banc.py mesurer --cache ~/.cache/opsys-bench-embeddings-fr \\
      --sortie docs/qualification/preuves-embeddings-fr [--juge opsys-haiku-5-5]
  python install/qualification/embeddings_fr/banc.py mesurer --sans-appel ...     (rejoue depuis le cache, aucun appel)
  python install/qualification/embeddings_fr/banc.py rapport --resultats mesure-....json
La clé se lit d'un FICHIER, jamais d'un argument ; elle n'est ni affichée ni écrite.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import operator
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # exécution directe : `python install/qualification/embeddings_fr/banc.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "embeddings_fr"

from . import corpus as mod_corpus
from . import juge as mod_juge
from . import metriques
from .cache import Cache, cle_vecteur
from .lexical_local import Lexique, identifiants
from .passerelle import ENV_CLE_FICHIER, ENV_URL, ClientPasserelle, ErreurPasserelle, lire_cle

ICI = Path(__file__).resolve().parent
DOSSIER_CORPUS = ICI.parents[2] / "docs" / "qualification" / "corpus-embeddings-fr"  # données, hors du cœur
SCHEMA_RESULTATS = "opsys.qualification.mesure-embeddings-fr/v1"
GRAINE_IC = 20261102
REPETITIONS_IC = 2000
RRF_K = 60  # valeur du produit (`recherche.Reglages.rrf_k`)
PROFONDEUR = 50  # candidats par voie avant fusion (`recherche.Reglages.candidats`)
SEUIL_VECTORIEL_PRODUIT = 0.30  # `recherche.Reglages.seuil_vectoriel`, réglé pour bge-m3
TAILLE_LOT = 64
SONDE_LATENCE = 40  # requêtes envoyées une à une pour mesurer la latence d'une requête isolée
K_RAPPEL = (1, 5, 10)
POIDS_BM25_EXPLORATOIRE = 0.5


class ErreurBanc(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class Config:
    identifiant: str
    modele: str
    description: str
    prefixe_requete: str = ""
    prefixe_document: str = ""
    input_type: bool = False  # envoie input_type=query|document (honoré par voyage et gemini via la passerelle)


CONFIGURATIONS: tuple[Config, ...] = (
    Config("e5-large", "opsys-embed-e5-multilingue", "multilingual-e5-large, texte brut (appel OpenAI standard)"),
    Config("e5-large-prefixes", "opsys-embed-e5-multilingue",
           "multilingual-e5-large avec les préfixes « query: » / « passage: » de sa fiche", "query: ", "passage: "),
    Config("gemini-2", "opsys-embed-gemini-2", "Gemini Embedding 2, appel OpenAI standard"),
    Config("gemini-2-type", "opsys-embed-gemini-2", "Gemini Embedding 2 avec input_type query/document",
           input_type=True),
    Config("voyage-4", "opsys-embed-voyage-4", "Voyage 4, appel OpenAI standard"),
    Config("voyage-4-type", "opsys-embed-voyage-4", "Voyage 4 avec input_type query/document", input_type=True),
    Config("voyage-4-lite", "opsys-embed-voyage-4-lite", "Voyage 4 lite, appel OpenAI standard"),
    Config("voyage-4-lite-type", "opsys-embed-voyage-4-lite", "Voyage 4 lite avec input_type query/document",
           input_type=True),
)


# --------------------------------------------------------------------------------------------------- vecteurs
def _produit(a: Sequence[float], b: Sequence[float]) -> float:
    sumprod = getattr(math, "sumprod", None)
    return sumprod(a, b) if sumprod else sum(map(operator.mul, a, b))


def normaliser(v: Sequence[float]) -> list[float]:
    norme = math.sqrt(_produit(v, v))
    if not norme or not math.isfinite(norme):
        raise ErreurBanc("vecteur de norme nulle ou infinie")
    return [x / norme for x in v]


def plonger(client: ClientPasserelle | None, cache: Cache, config: Config, textes: Iterable[str], role: str, *,
            taille_lot: int = TAILLE_LOT, sonde: int = 0) -> dict[str, list[float]]:
    """Vecteurs des textes (cache d'abord). Les manquants partent en lots ; les `sonde` premiers partent un par un, ce
    qui donne une latence de requête isolée. role : « document » ou « requete »."""
    if role not in ("document", "requete"):
        raise ErreurBanc("rôle : document ou requete")
    prefixe = config.prefixe_requete if role == "requete" else config.prefixe_document
    genre = ("query" if role == "requete" else "document") if config.input_type else None
    uniques = list(dict.fromkeys(textes))
    cles = {t: cle_vecteur(config.modele, prefixe, genre, t) for t in uniques}
    manquants = [t for t in uniques if cache.lire(cles[t]) is None]
    if manquants and client is None:
        raise ErreurBanc(f"{len(manquants)} vecteur(s) absent(s) du cache pour {config.identifiant} (--sans-appel)")

    def appeler(lot: list[str], role_journal: str) -> None:
        assert client is not None
        reponse = client.embeddings(config.modele, [prefixe + t for t in lot], input_type=genre)
        for t, v in zip(lot, reponse.vecteurs, strict=True):
            cache.ecrire(cles[t], config.modele, v)
        cache.journaliser_appel(config.modele, config.identifiant, role_journal, len(lot), reponse.secondes,
                                reponse.jetons)

    unitaires, reste = manquants[:sonde], manquants[sonde:]
    for t in unitaires:
        appeler([t], f"{role}-unitaire")
    for i in range(0, len(reste), taille_lot):
        appeler(reste[i:i + taille_lot], f"{role}-lot")
    resultat: dict[str, list[float]] = {}
    for t in uniques:
        v = cache.lire(cles[t])
        assert v is not None
        resultat[t] = v
    return resultat


# --------------------------------------------------------------------------------------------------- classements
def classement_vectoriel(vecteur_requete: Sequence[float], docs: Mapping[str, Sequence[float]], limite: int = PROFONDEUR
                         ) -> list[tuple[str, float]]:
    """[(identifiant, cosinus)] décroissant ; vecteurs déjà normalisés (produit scalaire = cosinus)."""
    scores = {i: _produit(vecteur_requete, d) for i, d in docs.items()}
    tri = sorted(scores.items(), key=lambda t: (-t[1], t[0]))
    return tri[:limite]


def mesurer_requete(q: mod_corpus.Requete, classement: Sequence[str]) -> dict[str, Any]:
    """Métriques d'une question AVEC réponse pour un classement donné."""
    sortie: dict[str, Any] = {"rr": metriques.rang_reciproque(classement, q.pertinents, 10),
                              "ndcg": metriques.ndcg_a_k(classement, q.gains(), 10), "top10": list(classement[:10])}
    for k in K_RAPPEL:
        sortie[f"r{k}"] = metriques.rappel_a_k(classement, q.pertinents, k)
    return sortie


def _trace(enregistrements: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Rang réciproque et cinq premiers identifiants par question : de quoi relire un classement hors ligne."""
    return {qid: {"rr": round(e["rr"], 4), "top5": e["top10"][:5]} for qid, e in sorted(enregistrements.items())}


def resume(enregistrements: Sequence[Mapping[str, Any]], graine: int = GRAINE_IC) -> dict[str, Any]:
    """Moyennes et intervalles de confiance à 95 % (percentile, rééchantillonnage des questions)."""
    if not enregistrements:
        raise ErreurBanc("résumé d'une liste vide")
    sortie: dict[str, Any] = {"n": len(enregistrements)}
    for cle, nom in (("rr", "mrr@10"), ("r1", "rappel@1"), ("r5", "rappel@5"), ("r10", "rappel@10"),
                     ("ndcg", "ndcg@10")):
        valeurs = [e[cle] for e in enregistrements]
        bas, haut = metriques.intervalle_bootstrap(valeurs, graine=graine, repetitions=REPETITIONS_IC)
        sortie[nom] = {"moyenne": round(metriques.moyenne(valeurs), 4), "ic95": [round(bas, 4), round(haut, 4)]}
    return sortie


def comparer(a: Mapping[str, Mapping[str, Any]], b: Mapping[str, Mapping[str, Any]], cle: str = "rr",
             graine: int = GRAINE_IC) -> dict[str, Any]:
    """Écart apparié a - b sur les questions communes ; `distinguable` si l'IC95 exclut 0."""
    ids = sorted(set(a) & set(b))
    ecart, bas, haut = metriques.difference_appariee([a[i][cle] for i in ids], [b[i][cle] for i in ids], graine=graine,
                                                     repetitions=REPETITIONS_IC)
    return {"ecart": round(ecart, 4), "ic95": [round(bas, 4), round(haut, 4)], "n": len(ids),
            "distinguable": not (bas <= 0.0 <= haut)}


def par_type(corpus: mod_corpus.Corpus, enregistrements: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    types: dict[str, list[Mapping[str, Any]]] = {}
    for q in corpus.requetes:
        if not q.negative and q.identifiant in enregistrements:
            types.setdefault(q.type, []).append(enregistrements[q.identifiant])
    return {t: {"n": len(v), "mrr@10": round(metriques.moyenne([e["rr"] for e in v]), 3),
                "rappel@5": round(metriques.moyenne([e["r5"] for e in v]), 3)} for t, v in sorted(types.items())}


# --------------------------------------------------------------------------------------------------- évaluation
def evaluer_systemes(corpus: mod_corpus.Corpus, lexique: Lexique, docs: Mapping[str, Sequence[float]] | None,
                     requetes_vec: Mapping[str, Sequence[float]] | None,
                     requetes_vec_pert: Mapping[str, Sequence[float]] | None,
                     textes_perturbes: Mapping[str, str]) -> dict[str, Any]:
    """Systèmes évalués : `lex` (BM25 seul), et si des vecteurs existent `vec` (cosinus seul) et `hyb` (RRF des deux),
    chacun sur requêtes propres et perturbées. `docs` : vecteurs de passages normalisés ; `requetes_vec` :
    identifiant de requête -> vecteur normalisé. Rend, par système, les enregistrements par question, plus les scores de
    tête des questions avec / sans réponse (abstention)."""
    sorties: dict[str, dict[str, Any]] = {}
    negatifs: dict[str, dict[str, list[str]]] = {}

    def enregistrer(systeme: str, q: mod_corpus.Requete, classement: Sequence[str]) -> None:
        if q.negative:
            negatifs.setdefault(systeme, {})[q.identifiant] = list(classement[:10])
        else:
            sorties.setdefault(systeme, {})[q.identifiant] = mesurer_requete(q, classement)

    tetes: dict[str, dict[str, list[float]]] = {}

    def tete(systeme: str, q: mod_corpus.Requete, score: float) -> None:
        tetes.setdefault(systeme, {"avec": [], "sans": []})["sans" if q.negative else "avec"].append(score)

    for q in corpus.requetes:
        for variante, texte in (("", q.texte), ("_pert", textes_perturbes[q.identifiant])):
            lex = lexique.classer(texte, limite=PROFONDEUR)
            ids_lex = identifiants(lex)
            enregistrer("lex" + variante, q, ids_lex)
            if not variante:
                tete("lex", q, -lex[0][1] if lex else 0.0)  # bm25 rendu : plus petit = meilleur ; on range l'opposé
            vecteurs_req = requetes_vec if not variante else requetes_vec_pert
            if docs is None or vecteurs_req is None:
                continue
            vec = classement_vectoriel(vecteurs_req[q.identifiant], docs)
            ids_vec = [i for i, _ in vec]
            enregistrer("vec" + variante, q, ids_vec)
            enregistrer("hyb" + variante, q, metriques.fusionner([ids_lex, ids_vec], RRF_K))
            if not variante:  # EXPLORATOIRE (post hoc) : même fusion, BM25 à demi-poids ; le produit ne le fait pas
                enregistrer("hyb_demi", q,
                            metriques.fusionner([ids_lex, ids_vec], RRF_K, [POIDS_BM25_EXPLORATOIRE, 1.0]))
            if not variante:
                tete("vec", q, vec[0][1])
    return {"enregistrements": sorties, "tetes": tetes, "negatifs": negatifs}


def abstention(tetes: Mapping[str, list[float]]) -> dict[str, Any]:
    """Séparation des questions avec / sans réponse par le score de tête (AUC) et faux acceptés à 90 % de rappel."""
    avec, sans = tetes["avec"], tetes["sans"]
    seuil, faux = metriques.faux_acceptes_au_rappel(avec, sans, 0.9)
    return {"auc": round(metriques.auc(avec, sans), 4), "seuil_a_90pc_rappel": round(seuil, 4),
            "faux_acceptes_a_90pc_rappel": round(faux, 4), "n_avec": len(avec), "n_sans": len(sans),
            "tete_mediane_avec": round(metriques.quantile(avec, 0.5), 4),
            "tete_mediane_sans": round(metriques.quantile(sans, 0.5), 4)}


def analyse_seuil_produit(corpus: mod_corpus.Corpus, docs: Mapping[str, Sequence[float]],
                          requetes_vec: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    """Effet du seuil cosinus de 0,30 du produit (réglé pour bge-m3) sur CE modèle : part des passages pertinents sous
    le seuil (perdus par la voie vectorielle) et part des questions sans réponse qui le passent quand même."""
    sous, total, sans_passent, sans_n = 0, 0, 0, 0
    for q in corpus.requetes:
        v = requetes_vec[q.identifiant]
        if q.negative:
            sans_n += 1
            sans_passent += 1 if max(_produit(v, d) for d in docs.values()) >= SEUIL_VECTORIEL_PRODUIT else 0
        else:
            for p in q.pertinents:
                total += 1
                sous += 1 if _produit(v, docs[p]) < SEUIL_VECTORIEL_PRODUIT else 0
    return {"seuil": SEUIL_VECTORIEL_PRODUIT, "pertinents_sous_le_seuil": round(sous / total, 4),
            "sans_reponse_au_dessus_du_seuil": round(sans_passent / sans_n, 4)}


# --------------------------------------------------------------------------------------------------- latence et coût
def latence(appels: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    unitaires = [a["secondes"] for a in appels if a["role"] == "requete-unitaire"]
    lots_doc = [a for a in appels if a["role"] == "document-lot"]
    sortie: dict[str, Any] = {}
    if unitaires:
        sortie["requete_isolee"] = {"n": len(unitaires), "p50_s": round(metriques.quantile(unitaires, 0.5), 3),
                                    "p95_s": round(metriques.quantile(unitaires, 0.95), 3),
                                    "max_s": round(max(unitaires), 3)}
    if lots_doc:
        textes = sum(a["textes"] for a in lots_doc)
        sortie["documents_par_lot"] = {"appels": len(lots_doc), "textes": textes,
                                       "secondes_par_texte": round(sum(a["secondes"] for a in lots_doc) / textes, 4)}
    return sortie


def cout(appels: Sequence[Mapping[str, Any]], tarif: Mapping[str, str] | None, n_passages: int) -> dict[str, Any]:
    jetons_doc = sum(a["jetons"] or 0 for a in appels if a["role"].startswith("document"))
    jetons_req = sum(a["jetons"] or 0 for a in appels if a["role"].startswith("requete"))
    manquant = any(a["jetons"] is None for a in appels)
    sortie: dict[str, Any] = {"jetons_documents": jetons_doc, "jetons_requetes": jetons_req,
                              "jetons_inconnus": manquant}
    if tarif is not None and not manquant:
        prix = Decimal(tarif["entree"])
        sortie["usd_mesure"] = float((prix * (jetons_doc + jetons_req)).quantize(Decimal("0.000001")))
        moyen = jetons_doc / n_passages if n_passages else 0
        sortie["jetons_par_passage"] = round(moyen, 1)
        sortie["usd_par_million_de_jetons"] = float(prix * 1_000_000)
        sortie["usd_pour_100000_passages_de_meme_taille"] = float((prix * Decimal(str(moyen)) * 100_000).quantize(
            Decimal("0.01")))
    return sortie


def _taille_vecteur(dimension: int) -> dict[str, Any]:
    return {"dimension": dimension, "octets_float32": 4 * dimension,
            "mo_pour_100000_passages": round(4 * dimension * 100_000 / 1_048_576, 1)}


# --------------------------------------------------------------------------------------------------- exécution
def executer(corpus: mod_corpus.Corpus, cache: Cache, client: ClientPasserelle | None, *,
             configs: Sequence[Config] = CONFIGURATIONS, tarifs: Mapping[str, Any] | None = None,
             modele_juge: str | None = None, sonde: int = SONDE_LATENCE, etiquette: str = "") -> dict[str, Any]:
    textes_perturbes = {q.identifiant: mod_corpus.perturber_requete(q.texte) for q in corpus.requetes}
    lexique = Lexique(corpus.passages)
    depense_avant = client.depense() if client else None
    resultats: dict[str, Any] = {
        "schema": SCHEMA_RESULTATS, "etiquette": etiquette,
        "execute_le": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "corpus": {"fictif": True, "empreinte_sha256": corpus.empreinte, "passages": len(corpus.passages),
                   "requetes": len(corpus.requetes),
                   "requetes_avec_reponse": sum(1 for q in corpus.requetes if not q.negative),
                   "requetes_sans_reponse": sum(1 for q in corpus.requetes if q.negative),
                   "types": {t: sum(1 for q in corpus.requetes if q.type == t) for t in mod_corpus.TYPES_REQUETE}},
        "parametres": {"rrf_k": RRF_K, "profondeur": PROFONDEUR, "graine_ic": GRAINE_IC,
                       "repetitions_ic": REPETITIONS_IC, "couverture_lexicale": 0.25, "taille_lot": TAILLE_LOT,
                       "sonde_latence": sonde},
        "configurations": {}, "systemes_locaux": {}, "comparaisons": {}, "par_requete": {},
    }
    prix = (tarifs or {}).get("usd_par_jeton", {})
    tout: dict[str, dict[str, dict[str, Any]]] = {}
    tout_neg: dict[str, dict[str, list[str]]] = {}

    # BM25 seul (aucun appel)
    base = evaluer_systemes(corpus, lexique, None, None, None, textes_perturbes)
    tout["lex"] = base["enregistrements"]["lex"]
    tout_neg["lex"] = base["negatifs"]["lex"]
    tout["lex_pert"] = base["enregistrements"]["lex_pert"]
    resultats["par_requete"]["lex"] = _trace(tout["lex"])
    resultats["systemes_locaux"]["bm25_fts5"] = {
        "description": "BM25 de SQLite FTS5 du dépôt (opsys.connaissances.lexical), couverture >= 0,25",
        "propre": resume(list(tout["lex"].values())), "perturbe": resume(list(tout["lex_pert"].values())),
        "par_type": par_type(corpus, tout["lex"]), "abstention": abstention(base["tetes"]["lex"]),
        "robustesse_mrr": comparer(tout["lex"], tout["lex_pert"])}

    # plancher : double déterministe du dépôt (hachage de termes), PAS un modèle
    try:
        from opsys.connaissances.doubles import EmbeddingsDeterministe
    except ImportError:
        EmbeddingsDeterministe = None  # noqa: N806
    if EmbeddingsDeterministe is not None:
        double = EmbeddingsDeterministe()
        ids_p = sorted(corpus.passages)
        docs = dict(zip(ids_p, (normaliser(v) for v in double.plonger_documents([corpus.passages[i] for i in ids_p])),
                        strict=True))
        rq = {q.identifiant: normaliser(double.plonger_requete(q.texte)) for q in corpus.requetes}
        rp = {q.identifiant: normaliser(double.plonger_requete(textes_perturbes[q.identifiant]))
              for q in corpus.requetes}
        ev = evaluer_systemes(corpus, lexique, docs, rq, rp, textes_perturbes)
        resultats["systemes_locaux"]["double_hachage"] = {
            "description": "Double déterministe du dépôt (hachage de termes et de trigrammes, 256 dim.) : un PLANCHER, "
                           "pas un modèle d'embeddings",
            "vecteurs": {"propre": resume(list(ev["enregistrements"]["vec"].values())),
                         "perturbe": resume(list(ev["enregistrements"]["vec_pert"].values())),
                         "par_type": par_type(corpus, ev["enregistrements"]["vec"])},
            "hybride": {"propre": resume(list(ev["enregistrements"]["hyb"].values())),
                        "perturbe": resume(list(ev["enregistrements"]["hyb_pert"].values()))},
            "abstention": abstention(ev["tetes"]["vec"])}

    # modèles de la passerelle
    ordre_passages = sorted(corpus.passages)
    for config in configs:
        bloc: dict[str, Any] = {"modele_passerelle": config.modele, "description": config.description,
                                "prefixe_requete": config.prefixe_requete, "prefixe_document": config.prefixe_document,
                                "input_type": config.input_type}
        try:
            vd = plonger(client, cache, config, [corpus.passages[i] for i in ordre_passages], "document")
            textes_req = [q.texte for q in corpus.requetes]
            vq = plonger(client, cache, config, textes_req, "requete", sonde=sonde)
            vqp = plonger(client, cache, config, [textes_perturbes[q.identifiant] for q in corpus.requetes], "requete")
        except (ErreurPasserelle, ErreurBanc) as exc:
            bloc["erreur"] = str(exc)
            resultats["configurations"][config.identifiant] = bloc
            continue
        docs = {i: normaliser(vd[corpus.passages[i]]) for i in ordre_passages}
        rq = {q.identifiant: normaliser(vq[q.texte]) for q in corpus.requetes}
        rp = {q.identifiant: normaliser(vqp[textes_perturbes[q.identifiant]]) for q in corpus.requetes}
        ev = evaluer_systemes(corpus, lexique, docs, rq, rp, textes_perturbes)
        en = ev["enregistrements"]
        for systeme in ("vec", "hyb", "vec_pert", "hyb_pert"):
            tout[f"{config.identifiant}:{systeme}"] = en[systeme]
        tout_neg[f"{config.identifiant}:hyb"] = ev["negatifs"]["hyb"]
        tout_neg[f"{config.identifiant}:vec"] = ev["negatifs"]["vec"]
        for systeme in ("vec", "hyb"):  # traces pour l'audit des jugements (jamais de vecteur ni de clé)
            resultats["par_requete"][f"{config.identifiant}:{systeme}"] = _trace(en[systeme])
        appels = cache.appels(config.identifiant)
        dimension = len(next(iter(docs.values())))
        bloc.update({
            "vecteur": _taille_vecteur(dimension),
            "vecteurs": {"propre": resume(list(en["vec"].values())),
                         "perturbe": resume(list(en["vec_pert"].values())),
                         "par_type": par_type(corpus, en["vec"]),
                         "robustesse_mrr": comparer(en["vec"], en["vec_pert"])},
            "hybride": {"propre": resume(list(en["hyb"].values())),
                        "perturbe": resume(list(en["hyb_pert"].values())),
                        "par_type": par_type(corpus, en["hyb"]),
                        "robustesse_mrr": comparer(en["hyb"], en["hyb_pert"])},
            "hybride_bm25_demi_poids_exploratoire": {
                "avertissement": "choisi APRÈS avoir vu les résultats à poids égaux : à confirmer sur d'autres données",
                "propre": resume(list(en["hyb_demi"].values())),
                "contre_vecteurs_mrr": comparer(en["hyb_demi"], en["vec"]),
                "contre_hybride_mrr": comparer(en["hyb_demi"], en["hyb"])},
            "abstention": abstention(ev["tetes"]["vec"]),
            "seuil_produit": analyse_seuil_produit(corpus, docs, rq),
            "latence": latence(appels), "cout": cout(appels, prix.get(config.modele), len(corpus.passages)),
            "contexte_maximal_jetons": (tarifs or {}).get("contexte_maximal_amont", {}).get(config.modele)})
        resultats["comparaisons"][config.identifiant] = {
            "vecteurs_contre_bm25_mrr": comparer(en["vec"], tout["lex"]),
            "hybride_contre_bm25_mrr": comparer(en["hyb"], tout["lex"]),
            "hybride_contre_vecteurs_mrr": comparer(en["hyb"], en["vec"]),
            "hybride_contre_bm25_ndcg": comparer(en["hyb"], tout["lex"], "ndcg")}
        resultats["configurations"][config.identifiant] = bloc

    # écarts appariés entre modèles (vecteurs seuls, MRR) : ligne - colonne
    avec_vecteurs = [c.identifiant for c in configs if "vecteurs" in resultats["configurations"].get(c.identifiant, {})]
    resultats["entre_modeles_mrr"] = {
        a: {b: comparer(tout[f"{a}:vec"], tout[f"{b}:vec"]) for b in avec_vecteurs if b != a} for a in avec_vecteurs}

    # reclassement par un juge de discussion
    if modele_juge:
        resultats["juge"] = evaluer_juge(corpus, cache, client, modele_juge, tout, tout_neg, resultats,
                                           prix.get(modele_juge))
    resultats["depense_passerelle_observee_usd"] = (
        None if depense_avant is None or client is None or client.depense() is None
        else round(client.depense() - depense_avant, 6))
    lexique.fermer()
    return resultats


def evaluer_juge(corpus: mod_corpus.Corpus, cache: Cache, client: ClientPasserelle | None, modele: str,
                 tout: Mapping[str, Mapping[str, Mapping[str, Any]]], tout_neg: Mapping[str, Mapping[str, list[str]]],
                 resultats: Mapping[str, Any], tarif: Mapping[str, str] | None) -> dict[str, Any]:
    """Reclasse les 10 premiers de BM25 seul, du meilleur système vectoriel et du meilleur hybride (par MRR propre) avec
    le juge, et mesure s'il sait dire « aucune réponse » (aucune note >= 2) sur les questions sans réponse."""
    def meilleure(systeme: str, cle: str) -> str:
        ok = [(c, b[systeme]["propre"]["mrr@10"]["moyenne"]) for c, b in resultats["configurations"].items()
              if systeme in b]
        return max(ok, key=lambda t: (t[1], t[0]))[0]

    sources = ["lex", f"{meilleure('vecteurs', 'vec')}:vec", f"{meilleure('hybride', 'hyb')}:hyb"]
    sources = list(dict.fromkeys(sources))
    bloc: dict[str, Any] = {"modele": modele, "k": 10, "sources": {}}
    requetes = {q.identifiant: q for q in corpus.requetes}
    for source in sources:
        propres = tout[source]
        apres: dict[str, dict[str, Any]] = {}
        illisibles = 0
        fausses_abstentions = 0
        for qid, enr in propres.items():
            q = requetes[qid]
            candidats = enr["top10"]
            notes = (mod_juge.juger(client, cache, modele, qid, q.texte, candidats, corpus.passages)
                     if candidats else None)
            if notes is None:
                illisibles += 1 if candidats else 0
                classement = candidats
            else:
                classement = mod_juge.reclasser(candidats, notes)
                fausses_abstentions += 1 if max(notes.values()) < mod_juge.SEUIL_REPONSE else 0
            apres[qid] = mesurer_requete(q, classement)
        negatives_acceptees = 0
        negatives_illisibles = 0
        for qid, candidats in tout_neg[source].items():
            notes = mod_juge.juger(client, cache, modele, qid, requetes[qid].texte, candidats,
                                   corpus.passages) if candidats else None
            if candidats and notes is None:
                negatives_illisibles += 1
            elif notes is not None and max(notes.values()) >= mod_juge.SEUIL_REPONSE:
                negatives_acceptees += 1
        bloc["sources"][source] = {
            "avant": resume(list(propres.values())), "apres": resume(list(apres.values())),
            "mrr_apres_moins_avant": comparer(apres, propres),
            "ndcg_apres_moins_avant": comparer(apres, propres, "ndcg"),
            "reponses_illisibles": illisibles + negatives_illisibles, "questions_avec_reponse": len(propres),
            "questions_sans_reponse": len(tout_neg[source]),
            "fausses_abstentions_du_juge": fausses_abstentions,
            "sans_reponse_acceptees_a_tort_par_le_juge": negatives_acceptees}
    appels = [a for a in cache.appels("juge") if a["modele"] == modele]
    bloc["appels_cumules"] = len(appels)
    rapportes = [a["cout_usd"] for a in appels if a["cout_usd"] is not None]
    if rapportes:
        bloc["usd_rapporte_par_la_passerelle"] = round(sum(rapportes), 6)
        bloc["appels_avec_cout_rapporte"] = len(rapportes)
    if appels and tarif is not None and all(a["jetons"] is not None for a in appels):
        usd = sum(Decimal(tarif["entree"]) * a["jetons"] + Decimal(tarif["sortie"]) * (a["jetons_sortie"] or 0)
                  for a in appels)
        bloc["usd_estime_par_tarif"] = float(usd.quantize(Decimal("0.000001")))
        bloc["secondes_p50"] = round(metriques.quantile([a["secondes"] for a in appels], 0.5), 3)
        bloc["secondes_p95"] = round(metriques.quantile([a["secondes"] for a in appels], 0.95), 3)
    return bloc


# --------------------------------------------------------------------------------------------------- rapport
def _ic(mesure: Mapping[str, Any]) -> str:
    return f"{mesure['moyenne']:.3f} [{mesure['ic95'][0]:.3f} ; {mesure['ic95'][1]:.3f}]"


def _ecart(c: Mapping[str, Any]) -> str:
    """Écart apparié signé avec son intervalle : « +0,024 [-0,003 ; +0,055] »."""
    return f"{c['ecart']:+.3f} [{c['ic95'][0]:+.3f} ; {c['ic95'][1]:+.3f}]"


def _oui(valeur: bool) -> str:
    return "oui" if valeur else "non"


def _ligne_metriques(nom: str, bloc: Mapping[str, Any]) -> str:
    return (f"| {nom} | {bloc['n']} | {_ic(bloc['mrr@10'])} | {bloc['rappel@1']['moyenne']:.3f} | "
            f"{bloc['rappel@5']['moyenne']:.3f} | {bloc['rappel@10']['moyenne']:.3f} | {_ic(bloc['ndcg@10'])} |")


def _systemes(r: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """[(nom lisible, bloc {propre, perturbe, par_type, robustesse_mrr})] : BM25, puis vecteurs et hybride."""
    sortie: list[tuple[str, Mapping[str, Any]]] = [("BM25 FTS5 (local)", r["systemes_locaux"]["bm25_fts5"])]
    for ident, b in r["configurations"].items():
        if "erreur" not in b:
            sortie.append((f"{ident} (vecteurs)", b["vecteurs"]))
            sortie.append((f"{ident} + BM25 (RRF)", b["hybride"]))
    return sortie


def _tableau(entetes: Sequence[str], lignes: Iterable[Sequence[Any]]) -> str:
    sortie = ["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes)]
    sortie += ["| " + " | ".join(str(c) for c in ligne) + " |" for ligne in lignes]
    return "\n".join(sortie)


def tableau_markdown(r: Mapping[str, Any]) -> str:
    entetes = ["Système", "Questions", "MRR@10 [IC95]", "Rappel@1", "Rappel@5", "Rappel@10", "nDCG@10 [IC95]"]
    lignes = [_ligne_metriques("BM25 FTS5 (local)", r["systemes_locaux"]["bm25_fts5"]["propre"])]
    if "double_hachage" in r["systemes_locaux"]:
        plancher = r["systemes_locaux"]["double_hachage"]["vecteurs"]["propre"]
        lignes.append(_ligne_metriques("double de hachage (plancher)", plancher))
    for ident, b in r["configurations"].items():
        if "erreur" in b:
            lignes.append(f"| {ident} | erreur | {b['erreur']} | | | | |")
            continue
        lignes.append(_ligne_metriques(f"{ident} (vecteurs)", b["vecteurs"]["propre"]))
        lignes.append(_ligne_metriques(f"{ident} + BM25 (RRF)", b["hybride"]["propre"]))
    return "\n".join(["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes), *lignes])


def tableau_par_type(r: Mapping[str, Any]) -> str:
    types = [t for t in mod_corpus.TYPES_REQUETE if t != "negative"]
    entetes = ["Système (MRR@10)", *(f"{t} ({r['corpus']['types'][t]})" for t in types)]
    return _tableau(entetes, ([nom, *(f"{bloc['par_type'][t]['mrr@10']:.2f}" for t in types)]
                              for nom, bloc in _systemes(r)))


def tableau_robustesse(r: Mapping[str, Any]) -> str:
    entetes = ["Système", "MRR@10 requêtes propres", "MRR@10 mêmes requêtes mal tapées", "Perte [IC95]",
               "Perte distinguable de 0"]
    return _tableau(entetes, (
        [nom, f"{b['propre']['mrr@10']['moyenne']:.3f}", f"{b['perturbe']['mrr@10']['moyenne']:.3f}",
         _ecart(b["robustesse_mrr"]), _oui(b["robustesse_mrr"]["distinguable"])] for nom, b in _systemes(r)))


def tableau_abstention(r: Mapping[str, Any]) -> str:
    entetes = ["Système (tête de liste)", "AUC avec / sans réponse", "Seuil à 90 % de rappel",
               "Sans réponse acceptées à ce seuil", "Médiane avec / sans", "Pertinents sous 0,30",
               "Sans réponse au-dessus de 0,30"]
    bm = r["systemes_locaux"]["bm25_fts5"]["abstention"]
    lignes: list[list[Any]] = [["BM25 (score -bm25)", f"{bm['auc']:.3f}", f"{bm['seuil_a_90pc_rappel']:.2f}",
                                f"{bm['faux_acceptes_a_90pc_rappel']:.0%}",
                                f"{bm['tete_mediane_avec']:.2f} / {bm['tete_mediane_sans']:.2f}", "n/a", "n/a"]]
    for ident, b in r["configurations"].items():
        if "erreur" not in b:
            a, s = b["abstention"], b["seuil_produit"]
            lignes.append([ident, f"{a['auc']:.3f}", f"{a['seuil_a_90pc_rappel']:.2f}",
                           f"{a['faux_acceptes_a_90pc_rappel']:.0%}",
                           f"{a['tete_mediane_avec']:.2f} / {a['tete_mediane_sans']:.2f}",
                           f"{s['pertinents_sous_le_seuil']:.1%}", f"{s['sans_reponse_au_dessus_du_seuil']:.0%}"])
    return _tableau(entetes, lignes)


def tableau_exploitation(r: Mapping[str, Any]) -> str:
    entetes = ["Configuration", "Dimension", "Mo / 100 000 passages", "Jetons / passage", "USD / million de jetons",
               "USD mesuré (corpus + requêtes)", "USD / 100 000 passages", "Requête isolée p50 / p95 (s)",
               "Documents (s / texte)"]
    lignes = []
    for ident, b in r["configurations"].items():
        if "erreur" in b:
            continue
        c, lat, v = b["cout"], b["latence"], b["vecteur"]
        iso, doc = lat.get("requete_isolee"), lat.get("documents_par_lot")
        lignes.append([ident, v["dimension"], v["mo_pour_100000_passages"], c.get("jetons_par_passage", "n/d"),
                       c.get("usd_par_million_de_jetons", "n/d"), c.get("usd_mesure", "n/d"),
                       c.get("usd_pour_100000_passages_de_meme_taille", "n/d"),
                       f"{iso['p50_s']} / {iso['p95_s']}" if iso else "n/d",
                       doc["secondes_par_texte"] if doc else "n/d"])
    return _tableau(entetes, lignes)


def tableau_hybride(r: Mapping[str, Any]) -> str:
    entetes = ["Configuration", "MRR@10 vecteurs", "MRR@10 + BM25 (RRF, poids égaux)", "Écart [IC95]", "Distinguable",
               "MRR@10 BM25 à demi-poids (exploratoire)", "Écart contre vecteurs [IC95]"]
    lignes = []
    for ident, b in r["configurations"].items():
        if "erreur" in b:
            continue
        c = r["comparaisons"][ident]["hybride_contre_vecteurs_mrr"]
        d = b.get("hybride_bm25_demi_poids_exploratoire")
        lignes.append([ident, f"{b['vecteurs']['propre']['mrr@10']['moyenne']:.3f}",
                       f"{b['hybride']['propre']['mrr@10']['moyenne']:.3f}", _ecart(c), _oui(c["distinguable"]),
                       f"{d['propre']['mrr@10']['moyenne']:.3f}" if d else "n/d",
                       _ecart(d["contre_vecteurs_mrr"]) if d else "n/d"])
    return _tableau(entetes, lignes)


def tableau_juge(r: Mapping[str, Any]) -> str:
    j = r.get("juge")
    if not j:
        return "(aucun reclassement exécuté)"
    cout_usd = j.get("usd_rapporte_par_la_passerelle", j.get("usd_estime_par_tarif", "n/d"))
    intro = (f"Juge : {j['modele']}, 10 candidats par question, {j.get('appels_cumules', 'n/d')} appels, "
             f"{cout_usd} USD, p50 {j.get('secondes_p50', 'n/d')} s / p95 {j.get('secondes_p95', 'n/d')} s par appel.")
    entetes = ["Source des 10 candidats", "MRR@10 avant [IC95]", "MRR@10 après [IC95]", "Écart MRR [IC95]",
               "Écart nDCG [IC95]", "Sans réponse jugées « répondues »", "Répondables jugées « sans réponse »",
               "Réponses illisibles"]
    lignes = [[nom, _ic(s["avant"]["mrr@10"]), _ic(s["apres"]["mrr@10"]), _ecart(s["mrr_apres_moins_avant"]),
               _ecart(s["ndcg_apres_moins_avant"]),
               f"{s['sans_reponse_acceptees_a_tort_par_le_juge']} / {s['questions_sans_reponse']}",
               f"{s['fausses_abstentions_du_juge']} / {s['questions_avec_reponse']}", s["reponses_illisibles"]]
              for nom, s in j["sources"].items()]
    return intro + "\n\n" + _tableau(entetes, lignes)


def tableau_entre_modeles(r: Mapping[str, Any]) -> str:
    """Matrice des écarts de MRR@10 (vecteurs seuls), ligne moins colonne ; « * » = IC95 qui exclut 0."""
    noms = list(r.get("entre_modeles_mrr", {}))
    lignes = []
    for a in noms:
        cellules = []
        for b in noms:
            c = r["entre_modeles_mrr"][a].get(b)
            cellules.append("·" if c is None else f"{c['ecart']:+.3f}{'*' if c['distinguable'] else ''}")
        lignes.append([a, *cellules])
    return _tableau(["ligne − colonne", *noms], lignes)


def tableaux_complets(r: Mapping[str, Any]) -> str:
    return "\n\n".join(f"### {titre}\n\n{corps}" for titre, corps in (
        ("Qualité de classement", tableau_markdown(r)), ("MRR@10 par type de question", tableau_par_type(r)),
        ("Écarts appariés entre modèles (MRR@10, vecteurs seuls)", tableau_entre_modeles(r)),
        ("Hybride contre vecteurs seuls", tableau_hybride(r)), ("Robustesse aux fautes", tableau_robustesse(r)),
        ("Questions sans réponse et seuil cosinus", tableau_abstention(r)),
        ("Exploitation : taille, coût, latence", tableau_exploitation(r)), ("Reclassement par juge", tableau_juge(r))))


# --------------------------------------------------------------------------------------------------- CLI
def _cmd_verifier(args: argparse.Namespace) -> int:
    corpus = mod_corpus.charger_corpus(args.corpus)
    print(json.dumps({"corpus": "valide", "passages": len(corpus.passages), "requetes": len(corpus.requetes),
                      "sans_reponse": sum(1 for q in corpus.requetes if q.negative),
                      "empreinte_sha256": corpus.empreinte}, ensure_ascii=False, indent=2))
    return 0


def _cmd_mesurer(args: argparse.Namespace) -> int:
    corpus = mod_corpus.charger_corpus(args.corpus)
    cache = Cache(args.cache)
    client = None
    if not args.sans_appel:
        url = args.url or os.environ.get(ENV_URL)
        fichier = args.cle_fichier or os.environ.get(ENV_CLE_FICHIER)
        if not url or not fichier:
            print(f"URL ({ENV_URL}) et fichier de clé ({ENV_CLE_FICHIER}) requis (ou --sans-appel).", file=sys.stderr)
            return 2
        client = ClientPasserelle(url, lire_cle(fichier))
    tarifs = json.loads((ICI / "tarifs.json").read_text(encoding="utf-8"))
    choisies = CONFIGURATIONS if not args.configs else tuple(c for c in CONFIGURATIONS if c.identifiant in args.configs)
    resultats = executer(corpus, cache, client, configs=choisies, tarifs=tarifs, modele_juge=args.juge,
                         sonde=args.sonde, etiquette=args.etiquette)
    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    horodatage = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    chemin = sortie / f"mesure-{horodatage}-{corpus.empreinte[:8]}.json"
    if chemin.exists():
        raise ErreurBanc(f"{chemin} existe déjà : les preuves ne s'écrasent jamais")
    chemin.write_text(json.dumps(resultats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(tableaux_complets(resultats))
    print(f"\nrésultats : {chemin}")
    return 0


def _cmd_rapport(args: argparse.Namespace) -> int:
    print(tableaux_complets(json.loads(Path(args.resultats).read_text(encoding="utf-8"))))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="commande", required=True)
    v = sous.add_parser("verifier", help="valide le corpus (aucun réseau)")
    v.add_argument("--corpus", default=str(DOSSIER_CORPUS))
    v.set_defaults(fonction=_cmd_verifier)
    m = sous.add_parser("mesurer", help="mesure (appelle la passerelle sauf --sans-appel)")
    m.add_argument("--corpus", default=str(DOSSIER_CORPUS))
    m.add_argument("--url")
    m.add_argument("--cle-fichier")
    m.add_argument("--cache", required=True, help="dossier HORS dépôt (vecteurs et journal des appels)")
    m.add_argument("--sortie", required=True, help="dossier des résultats JSON (jamais écrasés)")
    m.add_argument("--configs", nargs="*", help="sous-ensemble de configurations")
    m.add_argument("--juge", help="modèle de discussion servant de juge de reclassement, ex. opsys-haiku-5-5")
    m.add_argument("--sonde", type=int, default=SONDE_LATENCE)
    m.add_argument("--etiquette", default="")
    m.add_argument("--sans-appel", action="store_true", help="n'utilise que le cache disque")
    m.set_defaults(fonction=_cmd_mesurer)
    r = sous.add_parser("rapport", help="tableau Markdown d'un fichier de résultats")
    r.add_argument("--resultats", required=True)
    r.set_defaults(fonction=_cmd_rapport)
    args = p.parse_args(argv)
    try:
        return args.fonction(args)
    except (ErreurBanc, ErreurPasserelle, mod_corpus.ErreurCorpus) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
