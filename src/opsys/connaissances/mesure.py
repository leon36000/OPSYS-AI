"""Harnais de mesure de la recherche : recall@k et MRR, lexical seul / vectoriel seul / hybride.

Il ingère, révise et publie un corpus de mesure dans une base JETABLE (la connexion qu'on lui donne, jamais l'instance
du client), puis rejoue chaque question dans les trois modes avec le MÊME index et le MÊME port d'embeddings, et compare
le classement obtenu aux jugements de pertinence du corpus.

**Honnêteté de la mesure.**
- Avec le double déterministe (`doubles.EmbeddingsDeterministe`), les chiffres valident le harnais, la fusion RRF et la
  plomberie. Ils ne disent RIEN de la qualité d'un vrai modèle d'embeddings sur du français québécois : le double ne
  comprend aucun sens (« voiture » et « automobile » lui sont étrangers).
- Le corpus est petit (quelques dizaines de fragments, une trentaine de questions), fictif, écrit par la même équipe
que le
  moteur : c'est un banc de non-régression et de démonstration, pas une preuve de qualité en production. Les intervalles
  de confiance sont larges ; un écart d'une question vaut plusieurs points.
- Les jugements sont des paires « clé de source # titre de section » écrites à la main avant la mesure.

Le harnais publie avec un acteur HUMAIN fictif (`banc-de-mesure`) parce que les sources du corpus couvrent des domaines
réglementés : c'est licite UNIQUEMENT dans la base jetable du banc. Aucun outil ni aucune commande ne l'expose à une
base
réelle.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from typing import Any

import yaml
from sqlalchemy import Connection

from . import cycle, ingestion, ports, recherche
from .codes import ENTREE_INVALIDE, ErreurConnaissances
from .modele import date_iso

SCHEMA_CORPUS = "opsys.connaissances.corpus/v1"
SCHEMA_RAPPORT = "opsys.connaissances.mesure/v1"
MODES = ("lexical", "vectoriel", "hybride")
K_RECALL = (1, 3, 5)
K_MRR = 10
ACTEUR_BANC = cycle.Acteur("banc-de-mesure", "humain", "admin")
_CLE_JUGEMENT = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}#.+$")


def recall_at_k(classement: Sequence[str], pertinents: set[str] | frozenset[str], k: int) -> float:
    """Part des éléments pertinents retrouvés dans les `k` premiers du classement (sans doublon)."""
    if not pertinents:
        raise ValueError("recall@k est indéfini sans élément pertinent")
    return len(set(classement[:k]) & set(pertinents)) / len(pertinents)


def reciprocal_rank(classement: Sequence[str], pertinents: set[str] | frozenset[str], k: int = K_MRR) -> float:
    """1 / rang du premier élément pertinent parmi les `k` premiers ; 0 s'il n'y en a pas."""
    for rang, element in enumerate(classement[:k], start=1):
        if element in pertinents:
            return 1.0 / rang
    return 0.0


def charger_corpus(source: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    donnees = yaml.safe_load(source) if isinstance(source, (str, bytes)) else dict(source)
    if (not isinstance(donnees, dict) or donnees.get("schema") != SCHEMA_CORPUS or donnees.get("fictif") is not True
            or not isinstance(donnees.get("sources"), list) or not isinstance(donnees.get("requetes"), list)):
        raise ErreurConnaissances(ENTREE_INVALIDE,
            f"corpus : schéma {SCHEMA_CORPUS}, « fictif: true », sources et requêtes")
    date_iso(donnees.get("date_reference"), "date_reference", requise=True)
    cles = set()
    for s in donnees["sources"]:
        cles.add(f"{s['departement']}/{s['cle']}")
    ids: set[str] = set()
    for q in donnees["requetes"]:
        if q["id"] in ids:
            raise ErreurConnaissances(ENTREE_INVALIDE, f"requête en double : {q['id']}")
        ids.add(q["id"])
        for jugement in q["pertinents"]:
            if not _CLE_JUGEMENT.match(jugement):
                raise ErreurConnaissances(ENTREE_INVALIDE, f"jugement mal formé : {jugement}")
    return donnees


def _publier_corpus(cnx: Connection, corpus: Mapping[str, Any], embeddeur: ports.PortEmbeddings | None,
                    maintenant: dt.datetime) -> None:
    for s in corpus["sources"]:
        provenance = ingestion.Provenance(
            editeur="Éditeur fictif (corpus de mesure)", type_autorite="fictive",
            reference=f"fictif://corpus/{s['cle']}", licence_reutilisation="interne",
            date_consultation=maintenant.date().isoformat(), date_publication=s.get("date_publication"),
            expire_le=s.get("expire_le"), revision_due_le=s.get("revision_due_le"))
        resultat = ingestion.ingerer(
            cnx, departement=s["departement"], cle=s["cle"], titre=s["titre"], domaine=s["domaine"],
            type_source="markdown", contenu=s["contenu"], provenance=provenance, par="banc-de-mesure-ingestion",
            maintenant=maintenant, embeddeur=embeddeur)
        cycle.reviser(cnx, resultat["version_id"], acteur=cycle.Acteur("banc-de-mesure-agent", "agent"),
                      maintenant=maintenant)
        cycle.publier(cnx, resultat["version_id"], acteur=ACTEUR_BANC, maintenant=maintenant,
                      raison="corpus de mesure fictif publié dans une base jetable")


def _identifiant(resultat: Mapping[str, Any]) -> str:
    section = resultat["emplacement"].get("section") or ""
    return f"{resultat['source']['cle']}#{section.split(' › ')[-1]}"


def _classement(reponse: Mapping[str, Any]) -> list[str]:
    vus: dict[str, None] = {}
    for r in reponse["resultats"]:
        vus.setdefault(_identifiant(r), None)
    return list(vus)


def executer(cnx: Connection, corpus: Mapping[str, Any], *, embeddeur: ports.PortEmbeddings,
             reranker: ports.PortReranker | None = None, modes: Sequence[str] = MODES,
             reglages: recherche.Reglages | None = None) -> dict[str, Any]:
    """Rapport `opsys.connaissances.mesure/v1` : par mode, global et par type de question."""
    corpus = charger_corpus(corpus)
    jour = dt.date.fromisoformat(corpus["date_reference"])
    maintenant = dt.datetime.combine(jour, dt.time(12), tzinfo=dt.UTC)
    _publier_corpus(cnx, corpus, embeddeur, maintenant)
    bases = sorted({s["departement"] for s in corpus["sources"]})
    rapport: dict[str, Any] = {
        "schema": SCHEMA_RAPPORT, "corpus": {"version": corpus.get("version"), "sources": len(corpus["sources"]),
                                             "requetes": len(corpus["requetes"]), "fictif": True},
        "embeddings": {"fournisseur_id": embeddeur.profil().fournisseur_id, "modele": embeddeur.profil().modele,
                       "dimension": embeddeur.profil().dimension},
        "reranker": reranker.identite().modele if reranker else None,
        "avertissement": ("Mesure sur un petit corpus fictif avec un double d'embeddings déterministe : elle valide le "
                          "harnais et la fusion, pas la qualité d'un vrai modèle ni la recherche en production."),
        "modes": {},
    }
    for mode in modes:
        details = []
        for q in corpus["requetes"]:
            reponse = recherche.rechercher(
                cnx, requete=q["texte"], departements=bases, maintenant=maintenant, k=K_MRR, mode=mode,
                embeddeur=embeddeur, reranker=reranker if mode != "lexical" else None, reglages=reglages)
            classement = _classement(reponse)
            pertinents = set(q["pertinents"])
            ligne: dict[str, Any] = {"id": q["id"], "type": q["type"], "statut": reponse["statut"],
                                     "classement": classement[:K_MRR]}
            if pertinents:
                ligne.update({f"recall@{k}": recall_at_k(classement, pertinents, k) for k in K_RECALL})
                ligne["mrr"] = reciprocal_rank(classement, pertinents)
            else:
                ligne["abstention_correcte"] = reponse["statut"] == "aucune_source"
            details.append(ligne)
        rapport["modes"][mode] = {"global": _agreger(details), "par_type": {
            t: _agreger([d for d in details if d["type"] == t]) for t in sorted({d["type"] for d in details})},
            "details": details}
    return rapport


def _moyenne(valeurs: list[float]) -> float | None:
    return round(sum(valeurs) / len(valeurs), 4) if valeurs else None


def _agreger(details: list[dict[str, Any]]) -> dict[str, Any]:
    avec = [d for d in details if "mrr" in d]
    sans = [d for d in details if "abstention_correcte" in d]
    sortie: dict[str, Any] = {"questions": len(avec)}
    for k in K_RECALL:
        sortie[f"recall@{k}"] = _moyenne([d[f"recall@{k}"] for d in avec])
    sortie["mrr@10"] = _moyenne([d["mrr"] for d in avec])
    sortie["faux_aucune_source"] = sum(1 for d in avec if d["statut"] == "aucune_source")
    sortie["questions_sans_reponse"] = len(sans)
    sortie["abstentions_correctes"] = sum(1 for d in sans if d["abstention_correcte"])
    return sortie
