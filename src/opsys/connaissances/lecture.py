"""Lectures : une version (avec son historique et ses fragments neutralisés), les sources d'une base, l'état des bases.

Rien ici n'écrit. Le texte rendu passe toujours par `isolation` (donnée non fiable). L'état des bases sert la console
et la CLI d'administration : nombre de sources par état, sources périmées, dernier index, fournisseurs actifs.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, func, select

from ..fournisseurs import registre
from ..stockage.schema import (
    CONNAISSANCES_BASES,
    CONNAISSANCES_FRAGMENTS,
    CONNAISSANCES_INDEXATIONS,
    CONNAISSANCES_SOURCES,
    CONNAISSANCES_VERSIONS,
)
from . import cycle, etats, index, isolation, ports
from .codes import LECTURE_INTERDITE, REQUETE_INVALIDE, ErreurConnaissances
from .modele import (
    DOMAINES_REGLEMENTES,
    ETAT_PUBLIE,
    ETAT_RETIRE,
    ETATS,
    MENTION_PROFESSIONNELLE,
    instant_iso,
)
from .recherche import age_jours, peremption

PAGE_MAX = 10
JOURS_AVANT_REVISION = 30


def lire_version(cnx: Connection, version_id: str, *, bases_lisibles: Sequence[str] | None, publie_seulement: bool,
                 maintenant: dt.datetime, decalage: int = 0, limite: int = 5,
                 filtre: isolation.Filtre | None = None) -> dict[str, Any]:
    """Une version : provenance complète, historique des états, intégrité, puis une page de ses fragments.

    `bases_lisibles` : bases que l'appelant a le droit de lire (`None` = toutes, pour l'administration). Une version
    hors
    de ces bases est « inconnue » (même refus qu'une version qui n'existe pas : on ne révèle pas son existence).
    `publie_seulement` : l'état courant doit être `publie` (lecture par un département) ; sinon tous les états."""
    if type(decalage) is not int or decalage < 0 or type(limite) is not int or not 1 <= limite <= PAGE_MAX:
        raise ErreurConnaissances(REQUETE_INVALIDE, f"décalage ≥ 0 et limite de 1 à {PAGE_MAX}")
    quand = instant_iso(maintenant)
    v = cycle.charger_version(cnx, version_id)
    if bases_lisibles is not None and v["departement"] not in bases_lisibles:
        raise ErreurConnaissances(LECTURE_INTERDITE, "version inconnue ou base non lisible par ce département")
    etat = etats.etat_courant(cnx, version_id)
    if publie_seulement and etat != ETAT_PUBLIE:
        raise ErreurConnaissances(LECTURE_INTERDITE, "version inconnue ou non publiée")
    perime, motif = peremption(v, quand[:10])
    age, base_age = age_jours(v, quand[:10])

    def propre(valeur: str) -> str:
        return isolation.isoler(valeur, filtre=filtre).texte

    fragments = cnx.execute(select(CONNAISSANCES_FRAGMENTS).where(CONNAISSANCES_FRAGMENTS.c.version_id == version_id)
                            .order_by(CONNAISSANCES_FRAGMENTS.c.rang).offset(decalage).limit(limite)).mappings().all()
    neutralise = False
    rendus = []
    for f in fragments:
        isole = isolation.isoler(f["texte"], filtre=filtre)
        neutralise = neutralise or isole.neutralise
        rendus.append({"chunk_id": f["chunk_id"], "rang": f["rang"], "page": f["page"], "section": propre(f["section"])
                       if f["section"] else None, "debut": f["debut"], "fin": f["fin"], "fragment_sha256": f["sha256"],
                       "texte": isole.texte, "neutralise": isole.neutralise, "signaux": list(isole.signaux)})
    if v["licence_reutilisation"] == "droit_auteur_reserve":
        for r in rendus:
            r["texte"] = r["texte"][:300]
    reponse: dict[str, Any] = {
        "departement": v["departement"], "source_id": v["source_id"], "cle": v["cle"], "titre": propre(v["titre"]),
        "domaine": v["domaine"], "version_id": v["version_id"], "version": v["numero"], "etat": etat,
        "editeur": propre(v["editeur"]), "type_autorite": v["type_autorite"], "reference": propre(v["reference"]),
        "type_source": v["type_source"], "date_publication": v["date_publication"],
        "date_consultation": v["date_consultation"], "licence_reutilisation": v["licence_reutilisation"],
        "expire_le": v["expire_le"], "revision_due_le": v["revision_due_le"], "perime": perime,
        "motif_peremption": motif, "age_jours": age, "age_calcule_depuis": base_age, "sha256": v["sha256"],
        "sha256_octets": v["sha256_octets"], "suspect": bool(v["suspect"]),
        "nb_pages": v["nb_pages"], "nb_fragments": v["nb_fragments"], "fragments": rendus,
        "decalage": decalage, "suivant": decalage + limite if decalage + limite < v["nb_fragments"] else None,
        "integrite": index.verifier_integrite(cnx, version_id) == [],
        "fiabilite": "non_fiable", "avertissement_fiabilite": isolation.AVERTISSEMENT, "neutralise": neutralise,
        "historique": [{"etat": h["etat"], "par": h["par"], "mode": h["mode"], "role": h["role"],
                        "raison": propre(h["raison"]) if h["raison"] else None, "quand": h["quand"]}
                       for h in etats.historique(cnx, version_id)],
    }
    if v["domaine"] in DOMAINES_REGLEMENTES:
        reponse["mention_professionnelle"] = MENTION_PROFESSIONNELLE
    if v["type_autorite"] == "fictive":
        reponse["demonstration_fictive"] = True
    return reponse


def lister_sources(cnx: Connection, *, departement: str, etat: str | None, maintenant: dt.datetime,
                   decalage: int = 0, limite: int = 20) -> dict[str, Any]:
    """Sources d'une base avec leur DERNIÈRE version (numéro, état), filtrables par état de cette dernière version."""
    if etat is not None and etat not in ETATS:
        raise ErreurConnaissances(REQUETE_INVALIDE, f"état parmi {', '.join(ETATS)}")
    if type(decalage) is not int or decalage < 0 or type(limite) is not int or not 1 <= limite <= 50:
        raise ErreurConnaissances(REQUETE_INVALIDE, "décalage ≥ 0 et limite de 1 à 50")
    reference = instant_iso(maintenant)[:10]
    lignes = []
    for s in cnx.execute(select(CONNAISSANCES_SOURCES).where(CONNAISSANCES_SOURCES.c.departement == departement)
                         .order_by(CONNAISSANCES_SOURCES.c.cle)).mappings():
        derniere = cnx.execute(select(CONNAISSANCES_VERSIONS)
                               .where(CONNAISSANCES_VERSIONS.c.source_id == s["source_id"])
                               .order_by(CONNAISSANCES_VERSIONS.c.numero.desc()).limit(1)).mappings().first()
        if derniere is None:
            continue
        etat_derniere = etats.etat_courant(cnx, derniere["version_id"])
        if etat is not None and etat_derniere != etat:
            continue
        perime, motif = peremption(derniere, reference)
        lignes.append({
            "source_id": s["source_id"], "cle": s["cle"], "titre": isolation.isoler(s["titre"]).texte,
            "domaine": s["domaine"], "version_id": derniere["version_id"], "version": derniere["numero"],
            "etat": etat_derniere, "type_autorite": derniere["type_autorite"], "suspect": bool(derniere["suspect"]),
            "perime": perime and etat_derniere == ETAT_PUBLIE, "motif_peremption": motif,
            "expire_le": derniere["expire_le"], "revision_due_le": derniere["revision_due_le"]})
    return {"departement": departement, "total": len(lignes), "sources": lignes[decalage:decalage + limite],
            "suivant": decalage + limite if decalage + limite < len(lignes) else None}


# -- état des bases (console, CLI) ------------------------------------------------------------------------------------
def _fournisseur(cnx: Connection, capacite: str, departement: str, adaptateurs: dict[str, Any]) -> dict[str, Any]:
    try:
        r = registre.resoudre(cnx, capacite, departement)
    except registre.RegistreErreur as exc:
        return {"statut": "non_utilisable", "code": exc.code, "refus": list(exc.codes)}
    f = r.fournisseur
    return {"statut": "selectionne", "identifiant": f.identifiant, "modele": f.modele, "portee": r.portee,
            "mode": f.mode, "qualification": f.qualification, "raccorde": f.identifiant in adaptateurs,
            "config_sha256": ports.empreinte_configuration(f)}


def etat_bases(cnx: Connection, *, maintenant: dt.datetime, departements: Sequence[str] | None = None
               ) -> dict[str, Any]:
    quand = instant_iso(maintenant)
    reference = quand[:10]
    limite_revision = (dt.date.fromisoformat(reference) + dt.timedelta(days=JOURS_AVANT_REVISION)).isoformat()
    bases = [r for r in cnx.execute(select(CONNAISSANCES_BASES).order_by(CONNAISSANCES_BASES.c.departement)).mappings()
             if departements is None or r["departement"] in departements]
    sortie = []
    for b in bases:
        dep = b["departement"]
        versions = cnx.execute(
            select(CONNAISSANCES_VERSIONS, CONNAISSANCES_SOURCES.c.cle, CONNAISSANCES_SOURCES.c.titre,
                   CONNAISSANCES_SOURCES.c.domaine)
            .join(CONNAISSANCES_SOURCES, CONNAISSANCES_SOURCES.c.source_id == CONNAISSANCES_VERSIONS.c.source_id)
            .where(CONNAISSANCES_SOURCES.c.departement == dep)).mappings().all()
        par_etat = dict.fromkeys(ETATS, 0)
        sources_par_etat = dict.fromkeys(ETATS, 0)
        publiees_courantes: dict[str, Any] = {}
        derniere_par_source: dict[str, Any] = {}
        perimees, a_reviser, suspectes, fictif = [], [], 0, False
        for v in sorted(versions, key=lambda x: (x["source_id"], x["numero"])):
            etat = etats.etat_courant(cnx, v["version_id"])
            par_etat[etat] += 1
            derniere_par_source[v["source_id"]] = etat
            if etat != ETAT_RETIRE:
                fictif = fictif or v["type_autorite"] == "fictive"
                suspectes += 1 if v["suspect"] else 0
            if etat == ETAT_PUBLIE:
                publiees_courantes[v["source_id"]] = v  # le plus grand numéro écrase (tri croissant)
        for etat in derniere_par_source.values():
            sources_par_etat[etat] += 1
        for v in publiees_courantes.values():
            perime, motif = peremption(v, reference)
            entree = {"cle": v["cle"], "titre": isolation.isoler(v["titre"]).texte, "version": v["numero"],
                      "domaine": v["domaine"], "expire_le": v["expire_le"], "revision_due_le": v["revision_due_le"]}
            if perime:
                perimees.append({**entree, "motif": motif})
            elif v["revision_due_le"] and v["revision_due_le"] <= limite_revision:
                a_reviser.append(entree)
        dernieres = {genre: cnx.execute(select(func.max(CONNAISSANCES_INDEXATIONS.c.quand)).where(
            CONNAISSANCES_INDEXATIONS.c.departement == dep, CONNAISSANCES_INDEXATIONS.c.genre == genre)).scalar_one()
            for genre in ("lexical", "vectoriel", "bascule")}
        ids_publies = [v["version_id"] for v in publiees_courantes.values()]
        total_frag, avec_vecteur = index.couverture_vectorielle(cnx, dep, ids_publies)
        embeddings = _fournisseur(cnx, "embeddings", dep, ports._ADAPTATEURS_EMBEDDINGS)
        espace = index.infos_espace(cnx, b["espace_actif"])
        # Le fournisseur sélectionné n'est plus celui des vecteurs de la base : ils ne seront plus lus (jamais de
        # mélange d'espaces), la recherche passe en lexical seul tant que la base n'est pas réindexée.
        reindexation = bool(espace and embeddings["statut"] == "selectionne"
                            and espace["config_sha256"] != embeddings["config_sha256"])
        sortie.append({
            "departement": dep, "cree_le": b["cree_le"], "sources": len(derniere_par_source),
            "sources_par_etat": sources_par_etat, "versions_par_etat": par_etat,
            "sources_perimees": perimees, "revisions_a_venir": a_reviser, "versions_suspectes": suspectes,
            "contient_demonstration_fictive": fictif, "derniere_indexation": dernieres,
            "espace_actif": espace, "reindexation_requise": reindexation,
            "couverture_vectorielle": {"fragments_publies": total_frag, "avec_vecteur": avec_vecteur},
            "embeddings": embeddings,
            "reranker": _fournisseur(cnx, "reranker", dep, ports._ADAPTATEURS_RERANKER),
            "domaines_reglementes_publies": sorted({v["domaine"] for v in publiees_courantes.values()
                                                    if v["domaine"] in DOMAINES_REGLEMENTES}),
        })
    return {"genere_le": quand, "jours_avant_revision": JOURS_AVANT_REVISION, "bases": sortie,
            "mention_professionnelle": MENTION_PROFESSIONNELLE}
