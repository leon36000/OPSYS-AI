"""Ingestion d'une source : extraction, découpage déterministe, empreintes, index lexical, embeddings (port).

Le résultat est TOUJOURS une version en `brouillon` : jamais recherchable, jamais publiée par l'ingestion. Une version
n'est jamais réécrite : un contenu ou une provenance différents sous la même clé donnent une NOUVELLE version (numéro
suivant) ; le même contenu et la même provenance rendent la version existante (rejeu idempotent, aucune écriture).

L'ingestion ne dépend d'aucun réseau : les embeddings passent par un port (`ports.PortEmbeddings`) ; sans port ou en cas
de refus du port, la version est tout de même indexée en lexical et la réponse dit pourquoi elle n'a pas de vecteurs.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import Connection, func, insert, select

from .. import etat as journal
from ..stockage.schema import (
    CONNAISSANCES_BASES,
    CONNAISSANCES_FRAGMENTS,
    CONNAISSANCES_SOURCES,
    CONNAISSANCES_VERSIONS,
)
from . import decoupage, etats, extraction, index, isolation, ports
from .codes import (
    DOMAINE_IMMUABLE,
    ENTREE_INVALIDE,
    PLAFOND_VOLUME,
    ErreurConnaissances,
)
from .modele import (
    AUTORITES,
    CLE_SOURCE,
    DEPARTEMENT,
    DOMAINES,
    ETAT_BROUILLON,
    FRAGMENTS_PLAFOND_PAR_BASE,
    LICENCES,
    TYPES_SOURCE,
    date_iso,
    instant_iso,
)


@dataclasses.dataclass(frozen=True)
class Provenance:
    """D'où vient la source, sous quelle licence, et jusqu'à quand elle vaut."""

    editeur: str
    type_autorite: str
    reference: str
    licence_reutilisation: str
    date_consultation: str
    date_publication: str | None = None
    expire_le: str | None = None
    revision_due_le: str | None = None


def valider_provenance(p: Provenance, *, aujourd_hui: str) -> Provenance:
    for champ, maximum in (("editeur", 200), ("reference", 500)):
        valeur = getattr(p, champ)
        if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum or not valeur.isprintable():
            raise ErreurConnaissances(ENTREE_INVALIDE, f"{champ} requis (texte imprimable de {maximum} caractères)")
    if p.type_autorite not in AUTORITES:
        raise ErreurConnaissances(ENTREE_INVALIDE, f"type_autorite parmi {', '.join(AUTORITES)}")
    if p.licence_reutilisation not in LICENCES:
        raise ErreurConnaissances(ENTREE_INVALIDE, f"licence_reutilisation parmi {', '.join(LICENCES)}")
    consultation = date_iso(p.date_consultation, "date_consultation", requise=True)
    publication = date_iso(p.date_publication, "date_publication", requise=False)
    expire = date_iso(p.expire_le, "expire_le", requise=False)
    revision = date_iso(p.revision_due_le, "revision_due_le", requise=False)
    assert consultation is not None
    if consultation > aujourd_hui or (publication is not None and publication > aujourd_hui):
        raise ErreurConnaissances(ENTREE_INVALIDE, "une date de consultation ou de publication ne peut pas être future")
    if publication is not None and publication > consultation:
        raise ErreurConnaissances(ENTREE_INVALIDE, "la source ne peut pas être consultée avant d'être publiée")
    for nom, valeur in (("expire_le", expire), ("revision_due_le", revision)):
        if valeur is not None and publication is not None and valeur < publication:
            raise ErreurConnaissances(ENTREE_INVALIDE, f"{nom} précède la date de publication")
    return Provenance(p.editeur.strip(), p.type_autorite, p.reference.strip(), p.licence_reutilisation, consultation,
                      publication, expire, revision)


def _empreinte_meta(titre: str, type_source: str, p: Provenance) -> str:
    donnees = {"titre": titre, "type_source": type_source, **dataclasses.asdict(p)}
    return hashlib.sha256(json.dumps(donnees, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _identifiant(*morceaux: object) -> str:
    """Identifiant DÉTERMINISTE (32 hexadécimaux) : mêmes entrées, même identifiant, sur toute machine. Rend la
    recherche
    reproductible (les égalités de score se départagent toujours de la même façon) et un rejeu inoffensif."""
    return hashlib.sha256("|".join(str(m) for m in morceaux).encode("utf-8")).hexdigest()[:32]


def assurer_base(cnx: Connection, departement: str, par: str, quand: str) -> None:
    if not isinstance(departement, str) or not DEPARTEMENT.fullmatch(departement):
        raise ErreurConnaissances(ENTREE_INVALIDE, "département : code de la forme m05-financecore")
    if cnx.execute(select(CONNAISSANCES_BASES.c.departement).where(
            CONNAISSANCES_BASES.c.departement == departement)).first() is None:
        cnx.execute(insert(CONNAISSANCES_BASES).values(
            departement=departement, cree_le=quand, cree_par=par, espace_actif=None, modifie_le=quand))


def _octets(contenu: str | bytes) -> bytes:
    return contenu if isinstance(contenu, bytes) else contenu.encode("utf-8")


def ingerer(
    cnx: Connection, *, departement: str, cle: str, titre: str, domaine: str, type_source: str,
    contenu: str | bytes, provenance: Provenance, par: str, maintenant: dt.datetime,
    embeddeur: ports.PortEmbeddings | None = None, raison_sans_embeddeur: str | None = None,
    extracteur_pdf: extraction.ExtracteurPDF | None = None, filtre: isolation.Filtre | None = None,
) -> dict[str, Any]:
    """Crée une version `brouillon` (ou rend la version identique déjà là). `par` : l'identité de l'ingestionneur."""
    quand = instant_iso(maintenant)
    aujourd_hui = quand[:10]
    if not isinstance(cle, str) or not CLE_SOURCE.fullmatch(cle):
        raise ErreurConnaissances(ENTREE_INVALIDE, "clé de source : minuscules, chiffres, . _ - (3 à 96 caractères)")
    if not isinstance(titre, str) or not 1 <= len(titre.strip()) <= 300 or not titre.isprintable():
        raise ErreurConnaissances(ENTREE_INVALIDE, "titre : 1 à 300 caractères imprimables")
    titre = titre.strip()
    if domaine not in DOMAINES:
        raise ErreurConnaissances(ENTREE_INVALIDE, f"domaine parmi {', '.join(DOMAINES)}")
    if type_source not in TYPES_SOURCE:
        raise ErreurConnaissances(ENTREE_INVALIDE, f"type_source parmi {', '.join(TYPES_SOURCE)}")
    if not isinstance(par, str) or not par.strip():
        raise ErreurConnaissances(ENTREE_INVALIDE, "ingestionneur requis")
    provenance = valider_provenance(provenance, aujourd_hui=aujourd_hui)

    pages = extraction.extraire_pages(type_source, contenu, extracteur_pdf=extracteur_pdf)
    texte = extraction.SEPARATEUR_PAGES.join(pages)
    sha = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    meta = _empreinte_meta(titre, type_source, provenance)

    assurer_base(cnx, departement, par, quand)
    source = cnx.execute(select(CONNAISSANCES_SOURCES).where(
        CONNAISSANCES_SOURCES.c.departement == departement, CONNAISSANCES_SOURCES.c.cle == cle)).mappings().first()
    if source is not None and source["domaine"] != domaine:
        raise ErreurConnaissances(
            DOMAINE_IMMUABLE, f"la source {cle} est du domaine « {source['domaine']} » : le domaine d'une source ne "
            "change jamais (il décide de la revue humaine et de la mention professionnelle)")
    if source is not None:
        for existante in cnx.execute(select(CONNAISSANCES_VERSIONS.c.version_id, CONNAISSANCES_VERSIONS.c.numero,
                                            CONNAISSANCES_VERSIONS.c.sha256, CONNAISSANCES_VERSIONS.c.empreinte_meta)
                                     .where(CONNAISSANCES_VERSIONS.c.source_id == source["source_id"])
                                     .order_by(CONNAISSANCES_VERSIONS.c.numero.desc())).mappings():
            if existante["sha256"] == sha and existante["empreinte_meta"] == meta:
                etat = etats.etat_courant(cnx, existante["version_id"])
                if etat != "retire":
                    return {"rejeu": True, "source_id": source["source_id"], "version_id": existante["version_id"],
                            "numero": existante["numero"], "etat": etat, "sha256": sha}
                break  # identique mais retirée : une nouvelle version peut la remplacer

    fragments = decoupage.decouper(pages)
    actuels = cnx.execute(select(func.count()).select_from(CONNAISSANCES_FRAGMENTS)
                          .join(CONNAISSANCES_VERSIONS,
                                CONNAISSANCES_VERSIONS.c.version_id == CONNAISSANCES_FRAGMENTS.c.version_id)
                          .join(CONNAISSANCES_SOURCES, CONNAISSANCES_SOURCES.c.source_id ==
                                CONNAISSANCES_VERSIONS.c.source_id)
                          .where(CONNAISSANCES_SOURCES.c.departement == departement)).scalar_one()
    if actuels + len(fragments) > FRAGMENTS_PLAFOND_PAR_BASE:
        raise ErreurConnaissances(PLAFOND_VOLUME, f"la base de {departement} dépasserait {FRAGMENTS_PLAFOND_PAR_BASE} "
                                  "fragments (plafond de la phase 1)")

    # Contenu non fiable : le texte est gardé tel quel (son empreinte reste celle du document), mais une version dont un
    # segment déclenche le filtre anti-injection est marquée `suspect` — seul un humain la publie.
    signaux: set[str] = set()
    suspect = False
    analyses = [texte[i:i + 20_000] for i in range(0, len(texte), 20_000)] + [f.texte for f in fragments]
    for morceau in analyses:
        isole = isolation.isoler(morceau, filtre=filtre)
        suspect = suspect or isole.neutralise
        signaux.update(isole.signaux)

    if source is None:
        source_id = _identifiant("src", departement, cle)
        cnx.execute(insert(CONNAISSANCES_SOURCES).values(
            source_id=source_id, departement=departement, cle=cle, titre=titre, domaine=domaine, cree_le=quand,
            cree_par=par))
        numero = 1
    else:
        source_id = source["source_id"]
        numero = 1 + cnx.execute(select(func.max(CONNAISSANCES_VERSIONS.c.numero)).where(
            CONNAISSANCES_VERSIONS.c.source_id == source_id)).scalar_one()
    version_id = _identifiant("ver", source_id, numero)
    cnx.execute(insert(CONNAISSANCES_VERSIONS).values(
        version_id=version_id, source_id=source_id, numero=numero, type_source=type_source,
        editeur=provenance.editeur, type_autorite=provenance.type_autorite, reference=provenance.reference,
        date_publication=provenance.date_publication, date_consultation=provenance.date_consultation,
        licence_reutilisation=provenance.licence_reutilisation, expire_le=provenance.expire_le,
        revision_due_le=provenance.revision_due_le, sha256=sha,
            sha256_octets=hashlib.sha256(_octets(contenu)).hexdigest(),
        empreinte_meta=meta, texte=texte, nb_pages=len(pages), nb_fragments=len(fragments), suspect=suspect,
        signaux=json.dumps(sorted(signaux)), cree_le=quand, cree_par=par))
    lignes = [{"chunk_id": _identifiant("chk", version_id, f.rang), "version_id": version_id, "rang": f.rang,
        "texte": f.texte,
               "sha256": f.sha256, "page": f.page, "section": f.section, "debut": f.debut, "fin": f.fin}
              for f in fragments]
    if lignes:
        cnx.execute(insert(CONNAISSANCES_FRAGMENTS), lignes)
    etats.ajouter_etat(cnx, version_id, ETAT_BROUILLON, attendu=None, par=par, mode="agent", role=None, raison=None,
                       controles=None, quand=quand)
    index.indexer_lexical(cnx, departement=departement, version_id=version_id, titre=titre, fragments=lignes,
                          par=par, quand=quand)
    vecteurs_info: dict[str, Any]
    if embeddeur is None:
        vecteurs_info = {"vectorise": False, "code": "REJ-CONN-EMBEDDINGS-NON-RACCORDE",
                         "detail": raison_sans_embeddeur or "aucun fournisseur d'embeddings utilisable : recherche "
                                                            "lexicale"}
    else:
        vecteurs_info = index.indexer_vecteurs(cnx, departement=departement, version_id=version_id, port=embeddeur,
                                               par=par, quand=quand)
    journal.journaliser(cnx, par, "connaissances.ingerer", f"{departement}/{cle}#{numero}", {
        "version_id": version_id, "sha256": sha, "fragments": len(fragments), "suspect": suspect,
        "domaine": domaine, "vectorise": vecteurs_info["vectorise"]})
    return {"rejeu": False, "source_id": source_id, "version_id": version_id, "numero": numero, "etat": ETAT_BROUILLON,
            "sha256": sha, "sha256_octets": hashlib.sha256(_octets(contenu)).hexdigest(), "pages": len(pages),
            "fragments": len(fragments), "suspect": suspect, "signaux": sorted(signaux), "vecteurs": vecteurs_info}
