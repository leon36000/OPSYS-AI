"""Indexation : lexicale (SQLite FTS5 ou PostgreSQL tsvector) et vectorielle (un ESPACE par modèle et configuration),
réindexation, intégrité.

**Lexical.** L'index (adaptateur de `lexical.py` selon le moteur : table virtuelle `connaissances_fts` de la migration
0041 sur SQLite, table `connaissances_lexique` de la migration 0053 sur PostgreSQL) reçoit, par fragment, les termes
normalisés (`normalisation.termes`) du titre de la source, de la section et du texte : le « préfixe de contexte »
déterministe de RAG-PREMIUM §3. Tout autre moteur est un refus typé.

**Vectoriel.** Un vecteur appartient à un espace (`ports.ProfilEmbeddings.espace_id`). La base a UN espace actif
(`connaissances_bases.espace_actif`). Écrire un vecteur d'un autre espace que l'actif est refusé ; la recherche ne lit
que
l'espace actif. Changer de fournisseur, de modèle ou de configuration, c'est `reindexer` : tous les fragments non
retirés
reçoivent un vecteur dans le NOUVEL espace, puis la bascule — dans une seule transaction, donc jamais un état mixte.
Les vecteurs de l'ancien espace restent (append-only) mais ne sont plus jamais lus.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from ..stockage.schema import (
    CONNAISSANCES_BASES,
    CONNAISSANCES_ESPACES,
    CONNAISSANCES_ETATS,
    CONNAISSANCES_FRAGMENTS,
    CONNAISSANCES_INDEXATIONS,
    CONNAISSANCES_SOURCES,
    CONNAISSANCES_VECTEURS,
    CONNAISSANCES_VERSIONS,
)
from . import lexical, normalisation, ports, vecteurs
from .codes import ESPACE_INCOMPATIBLE, INTEGRITE, PLAFOND_VOLUME, ErreurConnaissances
from .modele import ETAT_RETIRE, VECTEURS_PLAFOND

LOT_EMBEDDINGS = 32


def texte_indexe(titre: str, section: str | None, texte: str) -> str:
    """Ce que l'index lexical voit d'un fragment : titre, chemin de section et texte, en termes normalisés."""
    return " ".join(normalisation.termes(f"{titre} {section or ''} {texte}"))


def texte_a_plonger(titre: str, section: str | None, texte: str) -> str:
    """Ce que le modèle d'embeddings voit d'un fragment : même contexte que l'index lexical, en clair."""
    entete = " › ".join(x for x in (titre, section) if x)
    return f"{entete}\n{texte}"


def journaliser_indexation(cnx: Connection, *, departement: str, version_id: str | None, genre: str,
                           espace_id: str | None, nb_fragments: int, par: str, quand: str) -> None:
    cnx.execute(insert(CONNAISSANCES_INDEXATIONS).values(
        quand=quand, departement=departement, version_id=version_id, genre=genre, espace_id=espace_id,
        nb_fragments=nb_fragments, par=par))


def indexer_lexical(cnx: Connection, *, departement: str, version_id: str, titre: str,
                    fragments: list[dict[str, Any]], par: str, quand: str) -> None:
    lexical.pour(cnx).indexer(cnx, [(f["chunk_id"], texte_indexe(titre, f["section"], f["texte"])) for f in fragments])
    journaliser_indexation(cnx, departement=departement, version_id=version_id, genre="lexical", espace_id=None,
                           nb_fragments=len(fragments), par=par, quand=quand)


# -- espaces vectoriels ---------------------------------------------------------------------------------------------
def assurer_espace(cnx: Connection, profil: ports.ProfilEmbeddings, quand: str) -> str:
    espace_id = profil.espace_id
    existe = cnx.execute(select(CONNAISSANCES_ESPACES.c.espace_id).where(
        CONNAISSANCES_ESPACES.c.espace_id == espace_id)).scalar_one_or_none()
    if existe is None:
        cnx.execute(insert(CONNAISSANCES_ESPACES).values(
            espace_id=espace_id, fournisseur_id=profil.fournisseur_id, modele=profil.modele,
            dimension=profil.dimension, config_sha256=profil.config_sha256, profil=profil.canonique(), cree_le=quand))
    return espace_id


def espace_actif(cnx: Connection, departement: str) -> str | None:
    return cnx.execute(select(CONNAISSANCES_BASES.c.espace_actif).where(
        CONNAISSANCES_BASES.c.departement == departement)).scalar_one_or_none()


def infos_espace(cnx: Connection, espace_id: str | None) -> dict[str, Any] | None:
    if espace_id is None:
        return None
    ligne = cnx.execute(select(CONNAISSANCES_ESPACES).where(
        CONNAISSANCES_ESPACES.c.espace_id == espace_id)).mappings().first()
    if ligne is None:
        return None
    return {"espace_id": ligne["espace_id"], "fournisseur_id": ligne["fournisseur_id"], "modele": ligne["modele"],
            "dimension": ligne["dimension"], "config_sha256": ligne["config_sha256"]}


def _fragments_a_plonger(cnx: Connection, version_ids: list[str]) -> list[dict[str, Any]]:
    if not version_ids:
        return []
    lignes = cnx.execute(
        select(CONNAISSANCES_FRAGMENTS.c.chunk_id, CONNAISSANCES_FRAGMENTS.c.texte, CONNAISSANCES_FRAGMENTS.c.section,
               CONNAISSANCES_SOURCES.c.titre)
        .join(CONNAISSANCES_VERSIONS, CONNAISSANCES_VERSIONS.c.version_id == CONNAISSANCES_FRAGMENTS.c.version_id)
        .join(CONNAISSANCES_SOURCES, CONNAISSANCES_SOURCES.c.source_id == CONNAISSANCES_VERSIONS.c.source_id)
        .where(CONNAISSANCES_FRAGMENTS.c.version_id.in_(version_ids))
        .order_by(CONNAISSANCES_FRAGMENTS.c.version_id, CONNAISSANCES_FRAGMENTS.c.rang)).mappings()
    return [dict(r) for r in lignes]


def _ecrire_vecteurs(cnx: Connection, port: ports.PortEmbeddings, espace_id: str, fragments: list[dict[str,
    Any]]) -> int:
    profil = port.profil()
    if not fragments:
        return 0
    deja = {r[0] for r in cnx.execute(select(CONNAISSANCES_VECTEURS.c.chunk_id).where(
        CONNAISSANCES_VECTEURS.c.espace_id == espace_id,
        CONNAISSANCES_VECTEURS.c.chunk_id.in_([f["chunk_id"] for f in fragments])))}
    a_faire = [f for f in fragments if f["chunk_id"] not in deja]
    ecrits = 0
    for i in range(0, len(a_faire), LOT_EMBEDDINGS):
        lot = a_faire[i:i + LOT_EMBEDDINGS]
        resultat = ports.plonger_documents(
            port, [profil.prefixe_document + texte_a_plonger(f["titre"], f["section"], f["texte"]) for f in lot])
        for f, v in zip(lot, resultat, strict=True):
            cnx.execute(insert(CONNAISSANCES_VECTEURS).values(
                chunk_id=f["chunk_id"], espace_id=espace_id, dimension=profil.dimension,
                vecteur=vecteurs.empaqueter(v)))
            ecrits += 1
    return ecrits


def indexer_vecteurs(cnx: Connection, *, departement: str, version_id: str, port: ports.PortEmbeddings, par: str,
                     quand: str) -> dict[str, Any]:
    """Vecteurs d'une version dans l'espace du `port`, SI cet espace est l'espace actif de la base (ou si la base n'en a
    pas encore). Un autre espace est un refus rendu, jamais un mélange : la base doit être réindexée."""
    profil = port.profil()
    actif = espace_actif(cnx, departement)
    if actif is not None and actif != profil.espace_id:
        return {"vectorise": False, "code": ESPACE_INCOMPATIBLE,
                "detail": "l'espace vectoriel de la base n'est pas celui du fournisseur courant : réindexation requise"}
    total = cnx.execute(select(func.count()).select_from(CONNAISSANCES_VECTEURS).where(
        CONNAISSANCES_VECTEURS.c.espace_id == profil.espace_id)).scalar_one()
    fragments = _fragments_a_plonger(cnx, [version_id])
    if total + len(fragments) > VECTEURS_PLAFOND:
        raise ErreurConnaissances(
            PLAFOND_VOLUME, f"plus de {VECTEURS_PLAFOND} vecteurs dans un espace : la similarité exacte en Python "
            "s'arrête là (phase 1) ; il faut pgvector")
    espace_id = assurer_espace(cnx, profil, quand)
    n = _ecrire_vecteurs(cnx, port, espace_id, fragments)
    if actif is None:
        cnx.execute(update(CONNAISSANCES_BASES).where(CONNAISSANCES_BASES.c.departement == departement).values(
            espace_actif=espace_id, modifie_le=quand))
    journaliser_indexation(cnx, departement=departement, version_id=version_id, genre="vectoriel",
                           espace_id=espace_id, nb_fragments=n, par=par, quand=quand)
    return {"vectorise": True, "espace_id": espace_id, "fragments": n}


def versions_non_retirees(cnx: Connection, departement: str) -> list[str]:
    dernier = (select(func.max(CONNAISSANCES_ETATS.c.id))
               .where(CONNAISSANCES_ETATS.c.version_id == CONNAISSANCES_VERSIONS.c.version_id)
               .correlate(CONNAISSANCES_VERSIONS).scalar_subquery())
    return [r[0] for r in cnx.execute(
        select(CONNAISSANCES_VERSIONS.c.version_id)
        .join(CONNAISSANCES_SOURCES, CONNAISSANCES_SOURCES.c.source_id == CONNAISSANCES_VERSIONS.c.source_id)
        .join(CONNAISSANCES_ETATS, CONNAISSANCES_ETATS.c.id == dernier)
        .where(CONNAISSANCES_SOURCES.c.departement == departement, CONNAISSANCES_ETATS.c.etat != ETAT_RETIRE)
        .order_by(CONNAISSANCES_VERSIONS.c.cree_le, CONNAISSANCES_VERSIONS.c.version_id))]


def reindexer(cnx: Connection, *, departement: str, port: ports.PortEmbeddings, par: str, quand: str) -> dict[str, Any]:
    """Bascule la base vers l'espace du `port` : vecteurs pour TOUS les fragments non retirés, puis espace actif.

    Atomique (la transaction de l'appelant) : si un embedding échoue, l'espace actif ne change pas. Les fragments de
    versions retirées n'ont pas besoin de vecteur : elles ne sont plus jamais recherchées."""
    profil = port.profil()
    fragments = _fragments_a_plonger(cnx, versions_non_retirees(cnx, departement))
    if len(fragments) > VECTEURS_PLAFOND:
        raise ErreurConnaissances(
            PLAFOND_VOLUME,
                f"{len(fragments)} fragments à vectoriser : plus que le plafond de {VECTEURS_PLAFOND} de la "
            "similarité exacte en Python (phase 1)")
    espace_id = assurer_espace(cnx, profil, quand)
    ecrits = _ecrire_vecteurs(cnx, port, espace_id, fragments)
    precedent = espace_actif(cnx, departement)
    cnx.execute(update(CONNAISSANCES_BASES).where(CONNAISSANCES_BASES.c.departement == departement).values(
        espace_actif=espace_id, modifie_le=quand))
    journaliser_indexation(cnx, departement=departement, version_id=None, genre="bascule", espace_id=espace_id,
                           nb_fragments=ecrits, par=par, quand=quand)
    return {"espace_id": espace_id, "precedent": precedent, "fragments_total": len(fragments),
            "vecteurs_ecrits": ecrits}


def couverture_vectorielle(cnx: Connection, departement: str, version_ids: list[str]) -> tuple[int, int]:
    """`(fragments considérés, dont un vecteur dans l'espace actif de la base)`."""
    actif = espace_actif(cnx, departement)
    if not version_ids:
        return 0, 0
    total = cnx.execute(select(func.count()).select_from(CONNAISSANCES_FRAGMENTS).where(
        CONNAISSANCES_FRAGMENTS.c.version_id.in_(version_ids))).scalar_one()
    if actif is None:
        return total, 0
    avec = cnx.execute(
        select(func.count()).select_from(CONNAISSANCES_FRAGMENTS)
        .join(CONNAISSANCES_VECTEURS, CONNAISSANCES_VECTEURS.c.chunk_id == CONNAISSANCES_FRAGMENTS.c.chunk_id)
        .where(CONNAISSANCES_FRAGMENTS.c.version_id.in_(version_ids), CONNAISSANCES_VECTEURS.c.espace_id == actif)
    ).scalar_one()
    return total, avec


# -- intégrité ---------------------------------------------------------------------------------------------------------
def verifier_integrite(cnx: Connection, version_id: str) -> list[str]:
    """Défauts d'une version (liste vide = intègre) : empreinte du texte, fragments recoupés dans les pages, rangs."""
    version = cnx.execute(select(CONNAISSANCES_VERSIONS).where(
        CONNAISSANCES_VERSIONS.c.version_id == version_id)).mappings().first()
    if version is None:
        return ["version inconnue"]
    defauts: list[str] = []
    texte = version["texte"]
    if hashlib.sha256(texte.encode("utf-8")).hexdigest() != version["sha256"]:
        defauts.append("empreinte sha256 du texte différente de celle enregistrée")
    pages = texte.split("\f")
    if len(pages) != version["nb_pages"]:
        defauts.append("nombre de pages incohérent")
    fragments = cnx.execute(select(CONNAISSANCES_FRAGMENTS).where(
        CONNAISSANCES_FRAGMENTS.c.version_id == version_id).order_by(CONNAISSANCES_FRAGMENTS.c.rang)).mappings().all()
    if len(fragments) != version["nb_fragments"]:
        defauts.append("nombre de fragments incohérent")
    for attendu, f in enumerate(fragments):
        if f["rang"] != attendu:
            defauts.append(f"rang {f['rang']} au lieu de {attendu}")
            break
        page = pages[f["page"] - 1] if 1 <= f["page"] <= len(pages) else ""
        if page[f["debut"]:f["fin"]] != f["texte"]:
            defauts.append(f"fragment {attendu} : le texte ne correspond pas à son emplacement dans la page")
        if hashlib.sha256(f["texte"].encode("utf-8")).hexdigest() != f["sha256"]:
            defauts.append(f"fragment {attendu} : empreinte différente")
    return defauts


def exiger_integrite(cnx: Connection, version_id: str) -> None:
    defauts = verifier_integrite(cnx, version_id)
    if defauts:
        raise ErreurConnaissances(INTEGRITE, "; ".join(defauts[:5]))
