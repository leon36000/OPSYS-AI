"""Recherche hybride : lexicale (BM25 de FTS5) + vectorielle (similarité exacte) fusionnées par RRF, reranker optionnel.

Doctrine :

- **Publié seulement, à une date.** Par défaut, seules les versions `publie` sont candidates, et pour chaque source la
  plus récente. `a_la_date` relit la base telle qu'elle était publiée ce jour-là (les états sont des événements datés).
- **Un seul espace vectoriel.** La voie vectorielle ne lit que l'espace actif de la base ET seulement si le fournisseur
  d'embeddings courant produit cet espace ; sinon cette base est cherchée en lexical SEUL et la réponse le dit
  (`avertissements`). Jamais de mélange silencieux d'espaces.
- **Fusion RRF** (Cormack et al., SIGIR 2009) : `score = Σ 1 / (k + rang)` sur les listes lexicale et vectorielle, k =
60.
  Le rang de chaque voie est rendu avec le résultat.
- **Reranker** (port, facultatif) : réordonne la tête de liste fusionnée ; sa panne est un avertissement explicite, la
  liste fusionnée est alors rendue telle quelle.
- **Fraîcheur.** Une source expirée ou dont la révision est due est MARQUÉE (`perime`, motif) et RÉTROGRADÉE : elle
passe
  après toute source à jour, et n'apparaît que s'il reste de la place.
- **Aucune source.** Sans candidat au-dessus des seuils (couverture lexicale, similarité), la réponse est
  `statut: aucune_source` et un message qui dit de ne pas répondre de mémoire : jamais un remplissage par le « moins
  mauvais » fragment.
- **Contenu non fiable.** Tout texte rendu est neutralisé et accompagné de sa provenance complète (`isolation`).

Les seuils (`seuil_couverture`, `seuil_vectoriel`) sont des réglages de phase 1, calibrés sur le double d'embeddings des
tests, PAS sur un vrai modèle : ils seront recalibrés avec le modèle retenu (CONNAISSANCES.md, « Limites »).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Connection, bindparam, select, text

from ..stockage.schema import CONNAISSANCES_FRAGMENTS, CONNAISSANCES_VECTEURS
from . import etats, index, isolation, normalisation, ports, vecteurs
from .codes import (
    ESPACE_INCOMPATIBLE,
    PLAFOND_VOLUME,
    REQUETE_INVALIDE,
    ErreurConnaissances,
)
from .modele import (
    DEPARTEMENT,
    DOMAINES_REGLEMENTES,
    ETAT_PUBLIE,
    ETATS,
    MENTION_DEMONSTRATION,
    MENTION_PROFESSIONNELLE,
    VECTEURS_PLAFOND,
    date_iso,
    fin_de_journee,
    instant_iso,
)

MODES = ("hybride", "lexical", "vectoriel")
REQUETE_MIN, REQUETE_MAX = 2, 500
K_MAX = 20
LOT_VERSIONS = 400
EXTRAIT_RESTREINT = 300
MESSAGE_AUCUNE_SOURCE = ("Aucune source publiée de la base de connaissances ne répond à cette question. Ne réponds pas "
                         "de mémoire : dis que tu ne le sais pas, ou demande qu'une source officielle soit ajoutée.")
MESSAGE_BASE_VIDE = ("Aucune source n'est publiée dans la base de connaissances consultée. Ne réponds pas de mémoire : "
                     "dis que tu ne le sais pas, ou demande qu'une source officielle soit ajoutée.")


@dataclasses.dataclass(frozen=True)
class Reglages:
    rrf_k: int = 60
    candidats: int = 50
    n_rerank: int = 30
    seuil_couverture: float = 0.25
    seuil_vectoriel: float = 0.30


def peremption(version: Mapping[str, Any], reference: str) -> tuple[bool, str | None]:
    """`(périmée, motif)` à la date `reference` (AAAA-MM-JJ) : expirée, ou révision due."""
    if version["expire_le"] and version["expire_le"] < reference:
        return True, "expiree"
    if version["revision_due_le"] and version["revision_due_le"] < reference:
        return True, "revision_due"
    return False, None


def age_jours(version: Mapping[str, Any], reference: str) -> tuple[int, str]:
    base, genre = (version["date_publication"], "publication") if version["date_publication"] else (
        version["date_consultation"], "consultation")
    return (dt.date.fromisoformat(reference) - dt.date.fromisoformat(base)).days, genre


def rrf(listes: Sequence[Sequence[str]], k: int) -> dict[str, float]:
    """Score RRF de chaque identifiant : somme de 1 / (k + rang) sur chaque liste où il figure (rang depuis 1)."""
    scores: dict[str, float] = {}
    for liste in listes:
        for rang, identifiant in enumerate(liste, start=1):
            scores[identifiant] = scores.get(identifiant, 0.0) + 1.0 / (k + rang)
    return scores


def _valider(requete: object, departements: object, k: object, mode: object, etats_voulus: object,
             a_la_date: object, maintenant: dt.datetime) -> tuple[str, tuple[str, ...], tuple[str, ...], str, str]:
    if not isinstance(requete, str) or not REQUETE_MIN <= len(requete.strip()) <= REQUETE_MAX:
        raise ErreurConnaissances(REQUETE_INVALIDE, f"requête : {REQUETE_MIN} à {REQUETE_MAX} caractères")
    if "\x00" in requete:
        raise ErreurConnaissances(REQUETE_INVALIDE, "requête : caractère nul refusé")
    if (not isinstance(departements, (list, tuple)) or not departements
            or any(not isinstance(d, str) or not DEPARTEMENT.fullmatch(d) for d in departements)):
        raise ErreurConnaissances(REQUETE_INVALIDE, "bases : au moins un code de département valide")
    if type(k) is not int or not 1 <= k <= K_MAX:
        raise ErreurConnaissances(REQUETE_INVALIDE, f"k : entier de 1 à {K_MAX}")
    if mode not in MODES:
        raise ErreurConnaissances(REQUETE_INVALIDE, f"mode parmi {', '.join(MODES)}")
    if (not isinstance(etats_voulus, (list, tuple)) or not etats_voulus
            or any(e not in ETATS for e in etats_voulus)):
        raise ErreurConnaissances(REQUETE_INVALIDE, f"états parmi {', '.join(ETATS)}")
    quand = instant_iso(maintenant)
    if a_la_date is None:
        instant, reference = quand, quand[:10]
    else:
        try:
            jour = date_iso(a_la_date, "a_la_date", requise=True)
        except ErreurConnaissances:
            raise ErreurConnaissances(REQUETE_INVALIDE, "a_la_date : AAAA-MM-JJ attendu") from None
        assert jour is not None
        if jour > quand[:10]:
            raise ErreurConnaissances(REQUETE_INVALIDE, "a_la_date ne peut pas être dans le futur")
        instant, reference = (quand if jour == quand[:10] else fin_de_journee(jour)), jour
    return requete.strip(), tuple(dict.fromkeys(departements)), tuple(dict.fromkeys(etats_voulus)), instant, reference


def _candidats_lexicaux(cnx: Connection, termes_requete: list[str], version_ids: list[str], limite: int
                        ) -> list[tuple[str, float]]:
    """`[(chunk_id, bm25)]` du meilleur au moins bon. bm25() de FTS5 : plus petit = meilleur."""
    index.exiger_sqlite(cnx)
    expression = normalisation.requete_fts(termes_requete)
    if not expression:
        return []
    instruction = text(
        "SELECT f.chunk_id AS chunk_id, bm25(connaissances_fts) AS s FROM connaissances_fts "
        "JOIN connaissances_fragments f ON f.chunk_id = connaissances_fts.chunk_id "
        "WHERE connaissances_fts MATCH :q AND f.version_id IN :vids ORDER BY s, f.version_id, f.rang LIMIT :n"
    ).bindparams(bindparam("vids", expanding=True))
    trouves: list[tuple[str, float]] = []
    for i in range(0, len(version_ids), LOT_VERSIONS):
        lot = version_ids[i:i + LOT_VERSIONS]
        trouves.extend((r[0], float(r[1])) for r in cnx.execute(instruction, {"q": expression, "vids": lot,
            "n": limite}))
    trouves.sort(key=lambda t: t[1])  # tri stable : à égalité, l'ordre déjà départagé par SQL (version, rang)
    return trouves[:limite]


def _ordre_lecture(versions: Mapping[str, Mapping[str, Any]], fragment: Mapping[str, Any]) -> tuple[Any, ...]:
    v = versions[fragment["version_id"]]
    return v["departement"], v["cle"], v["numero"], fragment["rang"]


def _charger_fragments(cnx: Connection, chunk_ids: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    if not chunk_ids:
        return {}
    return {r["chunk_id"]: r for r in cnx.execute(
        select(CONNAISSANCES_FRAGMENTS).where(CONNAISSANCES_FRAGMENTS.c.chunk_id.in_(list(chunk_ids)))).mappings()}


def _candidats_vectoriels(cnx: Connection, espace_id: str, dimension: int, vecteur_requete: list[float],
                          version_ids: list[str], seuil: float, limite: int) -> list[tuple[str, float]]:
    comptes = 0
    similarites: list[tuple[str, float]] = []
    for i in range(0, len(version_ids), LOT_VERSIONS):
        lot = version_ids[i:i + LOT_VERSIONS]
        lignes = cnx.execute(
            select(CONNAISSANCES_VECTEURS.c.chunk_id, CONNAISSANCES_VECTEURS.c.vecteur)
            .join(CONNAISSANCES_FRAGMENTS, CONNAISSANCES_FRAGMENTS.c.chunk_id == CONNAISSANCES_VECTEURS.c.chunk_id)
            .where(CONNAISSANCES_VECTEURS.c.espace_id == espace_id, CONNAISSANCES_FRAGMENTS.c.version_id.in_(lot)))
        for chunk_id, octets in lignes:
            comptes += 1
            if comptes > VECTEURS_PLAFOND:
                raise ErreurConnaissances(
                    PLAFOND_VOLUME, f"plus de {VECTEURS_PLAFOND} vecteurs candidats : la similarité exacte en Python "
                    "s'arrête là (phase 1) ; il faut pgvector")
            s = vecteurs.produit_scalaire(vecteur_requete, vecteurs.depaqueter(octets, dimension))
            if s >= seuil:
                similarites.append((chunk_id, s))
    similarites.sort(key=lambda t: (-t[1], t[0]))
    return similarites[:limite]


def rechercher(
    cnx: Connection, *, requete: str, departements: Sequence[str], maintenant: dt.datetime, k: int = 5,
    mode: str = "hybride", etats_voulus: Sequence[str] = (ETAT_PUBLIE,), a_la_date: str | None = None,
    embeddeur: ports.PortEmbeddings | None = None, raison_sans_embeddeur: ErreurConnaissances | None = None,
    reranker: ports.PortReranker | None = None, raison_sans_reranker: ErreurConnaissances | None = None,
    reglages: Reglages | None = None, filtre: isolation.Filtre | None = None,
) -> dict[str, Any]:
    reglages = reglages or Reglages()
    requete, bases, etats_voulus, instant, reference = _valider(
        requete, departements, k, mode, etats_voulus, a_la_date, maintenant)
    avertissements: list[dict[str, str]] = []
    eligibles = etats.versions_eligibles(cnx, bases, etats_voulus, instant)
    base_reponse: dict[str, Any] = {
        "mode": mode, "requete": requete, "bases": list(bases), "etats": list(etats_voulus),
        "reference": {"instant": instant, "date": reference, "a_la_date": a_la_date},
        "fiabilite": "non_fiable", "avertissement_fiabilite": isolation.AVERTISSEMENT,
    }
    if not eligibles:
        return {**base_reponse, "statut": "aucune_source", "resultats": [], "message": MESSAGE_BASE_VIDE,
                "avertissements": avertissements}
    versions = {v["version_id"]: v for v in eligibles}
    version_ids = list(versions)
    termes_requete = normalisation.termes_uniques(requete)

    # -- voie lexicale
    lexical: list[tuple[str, float]] = []
    if mode in ("hybride", "lexical"):
        if not termes_requete:
            avertissements.append({"code": "REQUETE_SANS_TERME",
                                   "detail": "la question ne contient que des mots vides : aucun terme à chercher"})
        else:
            brut = _candidats_lexicaux(cnx, termes_requete, version_ids, reglages.candidats * 4)
            fragments = _charger_fragments(cnx, [c for c, _ in brut])
            retenus: list[tuple[str, float, int]] = []
            for chunk_id, bm25 in brut:
                f = fragments[chunk_id]
                v = versions[f["version_id"]]
                presents = set(index.texte_indexe(v["titre"], f["section"], f["texte"]).split())
                trouves = sum(1 for t in termes_requete if t in presents)
                if trouves / len(termes_requete) >= reglages.seuil_couverture:
                    retenus.append((chunk_id, bm25, trouves))
            # bm25 d'abord ; à égalité (IDF écrasé à ~0 dans un petit corpus), plus de termes de la question d'abord,
            # puis l'ordre de lecture (base, source, version, fragment) : jamais un ordre qui dépend de la machine.
            retenus.sort(key=lambda t: (round(t[1], 6), -t[2], _ordre_lecture(versions, fragments[t[0]])))
            lexical = [(c, b) for c, b, _ in retenus[:reglages.candidats]]

    # -- voie vectorielle, une base à la fois (un espace par base)
    vectoriel: list[tuple[str, float]] = []
    espace_info: dict[str, Any] | None = None
    if mode in ("hybride", "vectoriel"):
        if embeddeur is None:
            detail = raison_sans_embeddeur.detail if raison_sans_embeddeur else "aucun fournisseur d'embeddings"
            avertissements.append({"code": (raison_sans_embeddeur.code if raison_sans_embeddeur else
                                            "REJ-CONN-EMBEDDINGS-NON-RACCORDE"), "detail": f"recherche vectorielle "
                                   f"indisponible : {detail}"})
        else:
            profil = embeddeur.profil()
            vecteur_requete: list[float] | None = None
            for base in bases:
                ids_base = [vid for vid, v in versions.items() if v["departement"] == base]
                if not ids_base:
                    continue
                actif = index.espace_actif(cnx, base)
                if actif != profil.espace_id:
                    avertissements.append({
                        "code": ESPACE_INCOMPATIBLE,
                        "detail": f"{base} : "
                                  + ("aucun vecteur dans cette base" if actif is None else
                                     "l'espace vectoriel de la base n'est pas celui du fournisseur courant")
                                  + " ; cette base est cherchée en lexical seulement (réindexation requise)"})
                    continue
                if vecteur_requete is None:
                    vecteur_requete = ports.plonger_requete(embeddeur, profil.prefixe_requete + requete)
                total, avec = index.couverture_vectorielle(cnx, base, ids_base)
                if avec < total:
                    avertissements.append({
                        "code": "COUVERTURE_VECTORIELLE_PARTIELLE",
                        "detail": f"{base} : {avec} fragments sur {total} ont un vecteur dans l'espace actif"})
                vectoriel.extend(_candidats_vectoriels(cnx, actif, profil.dimension, vecteur_requete, ids_base,
                                                       reglages.seuil_vectoriel, reglages.candidats))
                espace_info = index.infos_espace(cnx, actif)
            vectoriel.sort(key=lambda t: (-t[1], t[0]))
            vectoriel = vectoriel[:reglages.candidats]

    mode_effectif = "hybride" if lexical and vectoriel else "lexical" if lexical else "vectoriel"
    if not lexical and not vectoriel:
        return {**base_reponse, "statut": "aucune_source", "mode_effectif": mode, "resultats": [],
                "message": MESSAGE_AUCUNE_SOURCE, "avertissements": avertissements,
                "candidats": {"lexical": 0, "vectoriel": 0}, "termes": termes_requete}

    # -- fusion
    rang_lex = {c: i for i, (c, _) in enumerate(lexical, start=1)}
    rang_vec = {c: i for i, (c, _) in enumerate(vectoriel, start=1)}
    bm25 = dict(lexical)
    similarite = dict(vectoriel)
    scores = rrf([[c for c, _ in lexical], [c for c, _ in vectoriel]], reglages.rrf_k)
    fragments = _charger_fragments(cnx, list(scores))
    ordre = sorted(scores, key=lambda c: (-scores[c], min(rang_lex.get(c, 10**9), rang_vec.get(c, 10**9)),
                                          _ordre_lecture(versions, fragments[c])))

    # -- reranker (port) : réordonne la tête, jamais ne retire un candidat
    infos_reranker: dict[str, Any] | None = None
    notes: dict[str, float] = {}
    if reranker is not None and ordre:
        tete = ordre[:reglages.n_rerank]
        try:
            valeurs = ports.noter(reranker, requete, [fragments[c]["texte"] for c in tete])
            notes = dict(zip(tete, valeurs, strict=True))
            tete.sort(key=lambda c: (-notes[c], ordre.index(c)))
            ordre = tete + ordre[reglages.n_rerank:]
            identite = reranker.identite()
            infos_reranker = {"fournisseur_id": identite.fournisseur_id, "modele": identite.modele,
                              "config_sha256": identite.config_sha256, "passages": len(tete)}
        except ErreurConnaissances as exc:
            avertissements.append({"code": exc.code, "detail": f"reranker ignoré : {exc.detail}"})
    elif reranker is None and raison_sans_reranker is not None:
        avertissements.append({"code": raison_sans_reranker.code,
                               "detail": f"pas de reranker : {raison_sans_reranker.detail}"})

    # -- fraîcheur : les sources périmées passent après les autres (ordre relatif conservé)
    def perimee(chunk_id: str) -> bool:
        return peremption(versions[fragments[chunk_id]["version_id"]], reference)[0]

    ordre = [c for c in ordre if not perimee(c)] + [c for c in ordre if perimee(c)]
    gardes = ordre[:k]

    resultats = []
    regle = False
    for rang, chunk_id in enumerate(gardes, start=1):
        f, v = fragments[chunk_id], versions[fragments[chunk_id]["version_id"]]
        resultats.append(_resultat(rang, f, v, reference, filtre, {
            "rrf": round(scores[chunk_id], 6),
            "lexical": {"rang": rang_lex[chunk_id], "bm25": round(bm25[chunk_id], 6)} if chunk_id in rang_lex else None,
            "vectoriel": ({"rang": rang_vec[chunk_id], "similarite": round(similarite[chunk_id], 6)}
                          if chunk_id in rang_vec else None),
            "reranker": round(notes[chunk_id], 6) if chunk_id in notes else None,
        }))
        regle = regle or v["domaine"] in DOMAINES_REGLEMENTES
    reponse: dict[str, Any] = {
        **base_reponse, "statut": "ok", "mode_effectif": mode_effectif, "termes": termes_requete,
        "resultats": resultats, "avertissements": avertissements,
        "candidats": {"lexical": len(lexical), "vectoriel": len(vectoriel)},
        "reranker": infos_reranker, "espace_vectoriel": espace_info,
    }
    if regle:
        reponse["mention_professionnelle"] = MENTION_PROFESSIONNELLE
    if any(r["source"]["type_autorite"] == "fictive" for r in resultats):
        reponse["mention_demonstration"] = MENTION_DEMONSTRATION
    if any(r["source"]["perime"] for r in resultats):
        reponse["avertissements"].append({
            "code": "SOURCE_PERIMEE", "detail": "au moins une source rendue est périmée (expirée ou révision due) : "
            "ne pas la citer sans vérification auprès de la source à jour"})
    return reponse


def _resultat(rang: int, f: Mapping[str, Any], v: Mapping[str, Any], reference: str, filtre: isolation.Filtre | None,
              scores: dict[str, Any]) -> dict[str, Any]:
    isole = isolation.isoler(f["texte"], filtre=filtre)
    texte = isole.texte
    restreint = v["licence_reutilisation"] == "droit_auteur_reserve"
    if restreint and len(texte) > EXTRAIT_RESTREINT:
        texte = texte[:EXTRAIT_RESTREINT - 1] + "…"
    neutralise = isole.neutralise
    signaux = set(isole.signaux)

    def champ(valeur: str | None) -> str | None:
        nonlocal neutralise
        if valeur is None:
            return None
        propre = isolation.isoler(valeur, filtre=filtre)
        neutralise = neutralise or propre.neutralise
        signaux.update(propre.signaux)
        return propre.texte

    perime, motif = peremption(v, reference)
    age, base_age = age_jours(v, reference)
    source = {
        "departement": v["departement"], "source_id": v["source_id"], "cle": v["cle"], "titre": champ(v["titre"]),
        "domaine": v["domaine"], "version_id": v["version_id"], "version": v["numero"], "etat": v["etat"],
        "editeur": champ(v["editeur"]), "type_autorite": v["type_autorite"], "reference": champ(v["reference"]),
        "date_publication": v["date_publication"], "date_consultation": v["date_consultation"],
        "licence_reutilisation": v["licence_reutilisation"], "sha256": v["sha256"],
        "expire_le": v["expire_le"], "revision_due_le": v["revision_due_le"], "perime": perime,
        "motif_peremption": motif, "age_jours": age, "age_calcule_depuis": base_age,
    }
    resultat: dict[str, Any] = {
        "rang": rang, "chunk_id": f["chunk_id"], "texte": texte, "scores": scores, "source": source,
        "emplacement": {"page": f["page"], "section": champ(f["section"]), "debut": f["debut"], "fin": f["fin"],
                        "fragment_sha256": f["sha256"]},
        "fiabilite": "non_fiable", "neutralise": neutralise, "signaux": sorted(signaux),
    }
    if restreint:
        resultat["reutilisation_restreinte"] = True
    if v["domaine"] in DOMAINES_REGLEMENTES:
        resultat["mention_professionnelle"] = MENTION_PROFESSIONNELLE
    if v["type_autorite"] == "fictive":
        resultat["demonstration_fictive"] = True
    if perime:
        resultat["avertissement"] = "Source périmée : à vérifier avant toute citation."
    return resultat


__all__ = ["MESSAGE_AUCUNE_SOURCE", "MODES", "Reglages", "age_jours", "peremption", "rechercher", "rrf"]
