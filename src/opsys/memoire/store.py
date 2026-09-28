"""Mémoire d'entreprise OPSYS : PostgreSQL + pgvector + plein texte français, fusion RRF.

C'est la couche B du RAG premium (docs/memory/RAG-PREMIUM.md §2 à §6) :
- `ajouter` : un fragment, avec sa provenance, sa portée, sa sensibilité et sa rétention (idempotent) ;
- `rechercher` : plein texte et vecteurs fusionnés par RRF, ou plein texte seul, annoncé comme tel ;
- `oublier` : effacement Loi 25 en cascade, journalisé ;
- `purger_expires` : application de la rétention.

Le cloisonnement commence ici : aucune recherche sans portée. Les clauses SQL viennent d'une liste
blanche, et toutes les valeurs passent en paramètres.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import importlib.resources
import json
import math
import numbers
import re
import unicodedata
import urllib.parse
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg

DIMENSION = 1024  # bge-m3 dense ; égal à vector(1024) dans schema.sql
K_RRF = 60  # constante de la fusion RRF (Cormack, Clarke, Büttcher, SIGIR 2009)
K_MAX = 50
CANDIDATS_MIN = 20
CANDIDATS_MAX = 200
TEXTE_MAX = 20_000  # au-delà, découper en amont (RAG-PREMIUM §3)
SENSIBILITES = ("publique", "interne", "confidentielle", "personnelle")
FILTRES = ("attributs", "departement", "document_id", "portee", "sensibilite", "source", "sujet")

_DEPARTEMENT = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_PORTEE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SUJET = re.compile(r"^[a-z][a-z0-9_]{0,31}:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_META_REQUISES = ("departement", "portee", "source", "sensibilite")
_META_FACULTATIVES = ("attributs", "cree_le", "expire_le", "sujets", "titre")
_DERIVE_HORLOGE = dt.timedelta(minutes=5)


class MemoireIndisponible(ValueError):  # noqa: N818 - nom métier, lu tel quel par l'agent
    """La mémoire ne peut pas servir : configuration, connexion, schéma ou droits.

    Elle hérite de ValueError pour que `opsys.outils.executer` rende un refus explicite à l'agent (quoi
    corriger ou escalader) au lieu d'une panne opaque.
    """


@dataclasses.dataclass(frozen=True)
class Resultat:
    fragment_id: int
    document_id: int
    texte: str
    source: str
    titre: str | None
    departement: str
    portee: str
    sensibilite: str
    sujets: tuple[str, ...]
    attributs: dict[str, Any]
    cree_le: dt.datetime
    expire_le: dt.datetime | None
    score: float  # RRF : somme de 1/(60 + rang) sur les voies qui ont trouvé le fragment
    rang_lexical: int | None
    rang_vectoriel: int | None


@dataclasses.dataclass(frozen=True)
class Recherche:
    mode: str  # « hybride » (plein texte + vecteurs) ou « plein_texte » (aucun embedding de requête)
    resultats: tuple[Resultat, ...]


# -- validation -----------------------------------------------------------------------------------------
def valider_texte(texte: Any) -> str:
    """Texte de fragment normalisé (NFC, sans blancs de bord), ou refus explicite."""
    if not isinstance(texte, str) or not texte.strip():
        raise ValueError("texte vide : rien à mémoriser")
    propre = unicodedata.normalize("NFC", texte.strip())  # « é » composé ou décomposé : même fragment
    if len(propre) > TEXTE_MAX:
        raise ValueError(f"fragment de {len(propre)} caractères (max {TEXTE_MAX}) : le découper en amont")
    return propre


def _horodatage(valeur: Any, cle: str) -> dt.datetime:
    if not isinstance(valeur, dt.datetime):
        raise ValueError(f"{cle} : datetime avec fuseau horaire attendu")
    if valeur.tzinfo is None or valeur.utcoffset() is None:
        raise ValueError(f"{cle} sans fuseau horaire : ambigu, fournir un datetime avec fuseau (ex. UTC)")
    return valeur


def _chaines(cle: str, valeur: Any) -> list[str]:
    valeurs = [valeur] if isinstance(valeur, str) else valeur
    if not isinstance(valeurs, (list, tuple)) or not valeurs:
        raise ValueError(f"filtre {cle} : chaîne ou liste non vide de chaînes attendue")
    if not all(isinstance(v, str) and v.strip() for v in valeurs):
        raise ValueError(f"filtre {cle} : chaque valeur doit être une chaîne non vide")
    return [v.strip() for v in valeurs]


def valider_meta(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Métadonnées de gouvernance normalisées. Refuse sans rien deviner (fail-closed).

    Une clé inconnue est refusée : une faute de frappe (« expire » au lieu de « expire_le ») ferait sinon
    perdre la rétention sans bruit.
    """
    if not isinstance(meta, Mapping):
        raise ValueError("meta doit être un objet")
    inconnues = sorted(set(meta) - set(_META_REQUISES) - set(_META_FACULTATIVES))
    if inconnues:
        raise ValueError(f"clé inconnue dans meta : {inconnues} "
                         f"(acceptées : {sorted(_META_REQUISES + _META_FACULTATIVES)})")
    for cle in _META_REQUISES:
        if not isinstance(meta.get(cle), str) or not meta[cle].strip():
            raise ValueError(f"métadonnée requise manquante ou vide : {cle}")
    departement, portee = meta["departement"].strip(), meta["portee"].strip()
    source, sensibilite = meta["source"].strip(), meta["sensibilite"].strip()
    if not _DEPARTEMENT.match(departement):
        raise ValueError(f"departement invalide {departement!r} : identifiant en minuscules (ex. m03-estimation)")
    if not _PORTEE.match(portee):
        raise ValueError(f"portee invalide {portee!r} : identifiant en minuscules (ex. chantiers)")
    if len(source) > 500:
        raise ValueError("source trop longue (max 500 caractères) : garder un identifiant stable")
    if sensibilite not in SENSIBILITES:
        raise ValueError(f"sensibilite invalide {sensibilite!r} (attendu : {', '.join(SENSIBILITES)})")
    titre = meta.get("titre")
    if titre is not None and (not isinstance(titre, str) or len(titre) > 300):
        raise ValueError("titre : chaîne de 300 caractères au plus")
    sujets_bruts = meta.get("sujets") or []
    if not isinstance(sujets_bruts, (list, tuple)):
        raise ValueError("sujets : liste de chaînes type:identifiant attendue")
    sujets: list[str] = []
    for sujet in sujets_bruts:
        if not isinstance(sujet, str) or not _SUJET.match(sujet):
            raise ValueError(f"sujet invalide {sujet!r} : format type:identifiant interne (ex. client:C-0042)")
        if sujet not in sujets:
            sujets.append(sujet)
    attributs = meta.get("attributs") or {}
    if not isinstance(attributs, Mapping):
        raise ValueError("attributs : objet JSON attendu")
    try:
        attributs_json = json.dumps(dict(attributs), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"attributs non sérialisables en JSON : {exc}") from exc
    maintenant = dt.datetime.now(dt.UTC)
    cree_le = meta.get("cree_le")
    if cree_le is not None and _horodatage(cree_le, "cree_le") > maintenant + _DERIVE_HORLOGE:
        raise ValueError("cree_le dans le futur : horodatage refusé")
    expire_le = meta.get("expire_le")
    if expire_le is not None:
        if _horodatage(expire_le, "expire_le") <= maintenant:
            raise ValueError("expire_le déjà passée : une donnée échue ne doit pas être mémorisée (Loi 25, art. 23)")
        if cree_le is not None and expire_le <= cree_le:
            raise ValueError("expire_le doit être postérieure à cree_le")
    if sensibilite == "personnelle":
        if expire_le is None:
            raise ValueError("expire_le obligatoire pour une donnée personnelle (rétention Loi 25, art. 23)")
        if not sujets:
            raise ValueError("sujets obligatoires pour une donnée personnelle (ex. client:C-0042) : "
                             "sans sujet, l'effacement Loi 25 est impossible")
    return {"departement": departement, "portee": portee, "source": source, "sensibilite": sensibilite,
            "titre": titre, "sujets": sujets, "attributs": attributs_json, "cree_le": cree_le,
            "expire_le": expire_le}


def _vecteur(valeurs: Any) -> str:
    """Littéral pgvector d'un embedding validé : 1 024 valeurs finies, non toutes nulles."""
    if isinstance(valeurs, (str, bytes, Mapping)) or not hasattr(valeurs, "__len__"):
        raise ValueError(f"embedding : séquence de {DIMENSION} nombres attendue")
    nombres = list(valeurs)
    if len(nombres) != DIMENSION:
        raise ValueError(f"embedding de dimension {len(nombres)} (attendu {DIMENSION}, bge-m3)")
    if not all(isinstance(v, numbers.Real) and not isinstance(v, bool) and math.isfinite(v) for v in nombres):
        raise ValueError("embedding : valeurs numériques finies attendues")
    if not any(nombres):
        raise ValueError("embedding nul : la similarité cosinus n'est pas définie")
    return "[" + ",".join(repr(float(v)) for v in nombres) + "]"


_GABARITS_FILTRE = {
    "attributs": "f.metadonnees @> %({p})s::jsonb",
    "departement": "f.departement = ANY(%({p})s)",
    "document_id": "f.document_id = %({p})s",
    "portee": "f.portee = ANY(%({p})s)",
    "sensibilite": "f.sensibilite = ANY(%({p})s)",
    "source": "d.source = ANY(%({p})s)",
    "sujet": "f.sujets && %({p})s::text[]",
}


def _clause(filtres: Mapping[str, Any]) -> tuple[str, dict[str, Any], bool]:
    """Clause WHERE (alias f = fragments, d = documents), ses paramètres, et le besoin de joindre `d`.

    Tout vient d'une liste blanche. On ne joint `documents` que pour le filtre `source` : la jointure double
    le coût de la voie vectorielle (mesuré à 50 k fragments).
    """
    if not isinstance(filtres, Mapping):
        raise ValueError("filtres : objet attendu")
    inconnus = sorted(set(filtres) - set(_GABARITS_FILTRE))
    if inconnus:
        raise ValueError(f"filtre inconnu : {inconnus} (acceptés : {list(FILTRES)})")
    morceaux, parametres = [], {}
    for cle in sorted(filtres):
        nom, valeur = f"filtre_{cle}", filtres[cle]
        if cle == "attributs":
            if not isinstance(valeur, Mapping) or not valeur:
                raise ValueError("filtre attributs : objet non vide attendu")
            parametres[nom] = json.dumps(dict(valeur), ensure_ascii=False)
        elif cle == "document_id":
            if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < 1:
                raise ValueError("filtre document_id : entier positif attendu")
            parametres[nom] = valeur
        else:
            parametres[nom] = _chaines(cle, valeur)
        morceaux.append(_GABARITS_FILTRE[cle].format(p=nom))
    return " AND ".join(morceaux), parametres, "source" in filtres


# -- SQL -------------------------------------------------------------------------------------------------
_EN_VIGUEUR = "(f.expire_le IS NULL OR f.expire_le > now())"

# Requête OU sur les lexèmes de la question : « et » exigerait tous les mots, ce qui tue le rappel sur
# des questions en langage naturel. Les lexèmes sont cités (' et \ doublés) pour être pris tels quels.
_CTE_LEXICALE = """
requete AS (
    SELECT string_agg(
               chr(39) || replace(replace(lexeme, chr(92), chr(92) || chr(92)), chr(39), chr(39) || chr(39))
               || chr(39), ' | ')::tsquery AS q
    FROM unnest(tsvector_to_array(to_tsvector('memoire.francais'::regconfig, %(requete)s))) AS lexeme
),
lexical AS (
    SELECT f.id, row_number() OVER (ORDER BY ts_rank(f.tsv, requete.q, 1) DESC, f.id) AS rang
    FROM memoire.fragments f{jointure}
    CROSS JOIN requete
    WHERE requete.q IS NOT NULL AND f.tsv @@ requete.q AND {en_vigueur} AND {filtres}
    ORDER BY rang
    LIMIT %(candidats)s
)"""

_CTE_VECTORIELLE = """
vectoriel AS (
    SELECT proches.id, row_number() OVER (ORDER BY proches.distance, proches.id) AS rang
    FROM (
        SELECT f.id, f.embedding <=> %(embedding)s::vector AS distance
        FROM memoire.fragments f{jointure}
        WHERE f.embedding IS NOT NULL AND {en_vigueur} AND {filtres}
        ORDER BY distance
        LIMIT %(candidats)s
    ) AS proches
)"""

_COLONNES = """f.id AS fragment_id, f.document_id, f.texte, d.source, d.titre, f.departement, f.portee,
       f.sensibilite, f.sujets, f.metadonnees, f.cree_le, f.expire_le"""

_SQL_HYBRIDE = "WITH" + _CTE_LEXICALE + "," + _CTE_VECTORIELLE + """
SELECT {colonnes}, lexical.rang AS rang_lexical, vectoriel.rang AS rang_vectoriel,
       (COALESCE(1.0 / (%(k_rrf)s + lexical.rang), 0)
        + COALESCE(1.0 / (%(k_rrf)s + vectoriel.rang), 0))::float8 AS score
FROM lexical
FULL OUTER JOIN vectoriel ON vectoriel.id = lexical.id
JOIN memoire.fragments f ON f.id = COALESCE(lexical.id, vectoriel.id)
JOIN memoire.documents d ON d.id = f.document_id
ORDER BY score DESC, f.id
LIMIT %(k)s"""

_SQL_PLEIN_TEXTE = "WITH" + _CTE_LEXICALE + """
SELECT {colonnes}, lexical.rang AS rang_lexical, NULL::bigint AS rang_vectoriel,
       (1.0 / (%(k_rrf)s + lexical.rang))::float8 AS score
FROM lexical
JOIN memoire.fragments f ON f.id = lexical.id
JOIN memoire.documents d ON d.id = f.document_id
ORDER BY score DESC, f.id
LIMIT %(k)s"""

_SQL_AJOUT = """
INSERT INTO memoire.fragments (document_id, texte, empreinte, embedding, departement, portee, sensibilite,
                               sujets, metadonnees, cree_le, expire_le)
VALUES (%(document_id)s, %(texte)s, %(empreinte)s, %(embedding)s::vector, %(departement)s, %(portee)s,
        %(sensibilite)s, %(sujets)s::text[], %(attributs)s::jsonb, COALESCE(%(cree_le)s, now()), %(expire_le)s)
ON CONFLICT (document_id, empreinte) DO UPDATE SET
    embedding = COALESCE(EXCLUDED.embedding, memoire.fragments.embedding),
    departement = EXCLUDED.departement,
    portee = EXCLUDED.portee,
    sensibilite = EXCLUDED.sensibilite,
    sujets = EXCLUDED.sujets,
    metadonnees = EXCLUDED.metadonnees,
    expire_le = EXCLUDED.expire_le
RETURNING id"""

_JOINTURE_DOCUMENTS = "\n    JOIN memoire.documents d ON d.id = f.document_id"

_SQL_ORPHELINS = """
DELETE FROM memoire.documents d
WHERE d.id = ANY(%s) AND NOT EXISTS (SELECT 1 FROM memoire.fragments f WHERE f.document_id = d.id)"""

_SQL_JOURNAL = """
INSERT INTO memoire.journal_effacements (demandeur, motif, filtres, fragments, documents)
VALUES (%s, %s, %s::jsonb, %s, %s)"""


def _psycopg() -> Any:
    try:
        import psycopg
        import psycopg.rows
    except ImportError as exc:
        raise MemoireIndisponible("psycopg absent : installer l'extra PostgreSQL (pip install 'opsys-ai[postgres]')") \
            from exc
    return psycopg


def _resultat(ligne: Mapping[str, Any]) -> Resultat:
    return Resultat(
        fragment_id=ligne["fragment_id"], document_id=ligne["document_id"], texte=ligne["texte"],
        source=ligne["source"], titre=ligne["titre"], departement=ligne["departement"], portee=ligne["portee"],
        sensibilite=ligne["sensibilite"], sujets=tuple(ligne["sujets"]), attributs=dict(ligne["metadonnees"]),
        cree_le=ligne["cree_le"], expire_le=ligne["expire_le"], score=float(ligne["score"]),
        rang_lexical=ligne["rang_lexical"], rang_vectoriel=ligne["rang_vectoriel"],
    )


class MemoireEntreprise:
    """Base de connaissances d'entreprise sur PostgreSQL 17 + pgvector (une connexion par opération)."""

    def __init__(self, url: str) -> None:
        if not isinstance(url, str) or not url.strip():
            raise MemoireIndisponible("URL PostgreSQL vide : définir OPSYS_DATABASE_URL (postgresql://…)")
        self._url = url.strip()

    # -- infrastructure --------------------------------------------------------------------------------
    def _secrets(self) -> list[str]:
        secrets = re.findall(r"password\s*=\s*(\S+)", self._url)
        if "://" in self._url:
            mot_de_passe = urllib.parse.urlsplit(self._url).password
            if mot_de_passe:
                secrets.append(mot_de_passe)
        return [s for s in secrets if s]

    def _masquer(self, texte: str) -> str:
        for secret in self._secrets():
            texte = texte.replace(secret, "***")
        return texte

    def __repr__(self) -> str:
        return f"MemoireEntreprise({self._masquer(self._url)!r})"

    @contextlib.contextmanager
    def _connexion(self) -> Iterator[psycopg.Connection[Any]]:
        psycopg = _psycopg()
        try:
            cnx = psycopg.connect(self._url, connect_timeout=10, application_name="opsys-memoire")
        except psycopg.OperationalError as exc:
            raise MemoireIndisponible(f"PostgreSQL injoignable : {self._masquer(str(exc).strip())}") from exc
        erreurs = psycopg.errors
        try:
            with cnx:
                yield cnx
        except (erreurs.UndefinedTable, erreurs.UndefinedObject, erreurs.InvalidSchemaName,
                erreurs.UndefinedFunction) as exc:
            raise MemoireIndisponible(
                f"schéma mémoire absent ou incomplet ({exc.diag.message_primary}) : exécuter "
                "`python -m opsys.memoire migrer` avec un rôle administrateur"
            ) from exc
        except erreurs.InsufficientPrivilege as exc:
            raise MemoireIndisponible(f"droits PostgreSQL insuffisants ({exc.diag.message_primary})") from exc
        except psycopg.OperationalError as exc:
            raise MemoireIndisponible(f"connexion PostgreSQL perdue : {self._masquer(str(exc).strip())}") from exc

    # -- API -------------------------------------------------------------------------------------------
    def migrer(self) -> None:
        """Applique schema.sql (idempotent), sous verrou consultatif contre les migrations concurrentes."""
        script = importlib.resources.files("opsys.memoire").joinpath("schema.sql").read_text(encoding="utf-8")
        with self._connexion() as cnx:
            cnx.execute("SELECT pg_advisory_xact_lock(hashtext('opsys.memoire.migrer'))")
            cnx.execute(script)

    def ajouter(self, texte: str, meta: Mapping[str, Any], embedding: Sequence[float] | None = None) -> int:
        """Mémorise un fragment et renvoie son id. Même source + même texte = même fragment (upsert).

        `meta` : departement, portee, source, sensibilite (requis) ; titre, sujets, attributs, cree_le,
        expire_le (facultatifs, mais expire_le et sujets sont requis si sensibilite = personnelle).
        """
        propre = valider_texte(texte)
        valeurs = valider_meta(meta)
        valeurs.update(texte=propre, empreinte=hashlib.sha256(propre.encode("utf-8")).hexdigest(),
                       embedding=None if embedding is None else _vecteur(embedding))
        with self._connexion() as cnx:
            (valeurs["document_id"],) = cnx.execute(
                "INSERT INTO memoire.documents (source, titre) VALUES (%(source)s, %(titre)s)"
                " ON CONFLICT (source) DO UPDATE SET titre = COALESCE(EXCLUDED.titre, memoire.documents.titre)"
                " RETURNING id",
                valeurs,
            ).fetchone()
            (ident,) = cnx.execute(_SQL_AJOUT, valeurs).fetchone()
        return int(ident)

    def rechercher(
        self, requete: str, embedding_requete: Sequence[float] | None, k: int, filtres: Mapping[str, Any]
    ) -> Recherche:
        """Top-k par RRF (plein texte français ⊕ cosinus pgvector), ou plein texte seul si pas d'embedding.

        `filtres["portee"]` est obligatoire : une recherche est toujours cloisonnée. Les fragments échus sont
        invisibles, même avant la purge.
        """
        if not isinstance(requete, str) or not requete.strip():
            raise ValueError("requête vide : rien à chercher")
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= K_MAX:
            raise ValueError(f"k doit être un entier de 1 à {K_MAX}")
        if not isinstance(filtres, Mapping) or "portee" not in filtres:
            raise ValueError("filtre portee obligatoire : une recherche est toujours cloisonnée par portée")
        clause, parametres, jointure = _clause(filtres)
        candidats = min(max(4 * k, CANDIDATS_MIN), CANDIDATS_MAX)
        parametres.update(requete=unicodedata.normalize("NFC", requete.strip()), candidats=candidats, k=k,
                          k_rrf=K_RRF)
        hybride = embedding_requete is not None
        if hybride:
            parametres["embedding"] = _vecteur(embedding_requete)
        gabarit = _SQL_HYBRIDE if hybride else _SQL_PLEIN_TEXTE
        sql = gabarit.format(colonnes=_COLONNES, en_vigueur=_EN_VIGUEUR, filtres=clause,
                             jointure=_JOINTURE_DOCUMENTS if jointure else "")
        psycopg = _psycopg()
        with self._connexion() as cnx:
            if hybride:
                # Filtres sélectifs : un parcours HNSW itératif évite de rendre moins de candidats que demandé.
                cnx.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true),"
                            " set_config('hnsw.ef_search', %s, true)", (str(max(40, candidats)),))
            with cnx.cursor(row_factory=psycopg.rows.dict_row) as curseur:
                lignes = curseur.execute(sql, parametres).fetchall()
        return Recherche(mode="hybride" if hybride else "plein_texte",
                         resultats=tuple(_resultat(ligne) for ligne in lignes))

    def oublier(self, filtres: Mapping[str, Any], *, demandeur: str, motif: str) -> int:
        """Effacement Loi 25 en une transaction : fragments, puis documents orphelins, puis journal.

        Renvoie le nombre de fragments supprimés. La demande est journalisée même si rien n'est trouvé.
        """
        if not isinstance(filtres, Mapping) or not filtres:
            raise ValueError("oublier exige au moins un filtre (sujet, source, document_id…) : "
                             "un effacement global n'est jamais implicite")
        for nom, valeur in (("demandeur", demandeur), ("motif", motif)):
            if not isinstance(valeur, str) or not valeur.strip():
                raise ValueError(f"{nom} obligatoire : l'effacement est journalisé (Loi 25)")
        clause, parametres, jointure = _clause(filtres)
        using = " USING memoire.documents d" if jointure else ""
        condition = f"d.id = f.document_id AND {clause}" if jointure else clause
        with self._connexion() as cnx:
            supprimes = cnx.execute(
                f"DELETE FROM memoire.fragments f{using} WHERE {condition}"  # noqa: S608 - clause en liste blanche
                " RETURNING f.document_id",
                parametres,
            ).fetchall()
            documents = self._supprimer_orphelins(cnx, {ligne[0] for ligne in supprimes})
            cnx.execute(_SQL_JOURNAL, (demandeur.strip(), motif.strip(),
                                       json.dumps(dict(filtres), ensure_ascii=False, default=str),
                                       len(supprimes), documents))
        return len(supprimes)

    def purger_expires(self) -> int:
        """Supprime les fragments dont l'échéance est passée (rétention Loi 25, art. 23)."""
        with self._connexion() as cnx:
            supprimes = cnx.execute("DELETE FROM memoire.fragments WHERE expire_le IS NOT NULL"
                                    " AND expire_le <= now() RETURNING document_id").fetchall()
            if supprimes:
                documents = self._supprimer_orphelins(cnx, {ligne[0] for ligne in supprimes})
                cnx.execute(_SQL_JOURNAL, ("opsys:retention", "rétention échue (expire_le dépassée)",
                                           json.dumps({"expire_le": "<= now()"}), len(supprimes), documents))
        return len(supprimes)

    def completer_embeddings(
        self,
        plongeur: Callable[[list[str]], Sequence[Sequence[float]]],
        *,
        inclure_personnelles: bool,
        lot: int = 32,
    ) -> int:
        """Vectorise les fragments en vigueur sans embedding (panne passée du service, plein texte seul).

        `inclure_personnelles` doit être vrai seulement si le plongeur tourne sur le VPS (Loi 25, art. 17).
        """
        if isinstance(lot, bool) or not isinstance(lot, int) or lot < 1:
            raise ValueError("lot doit être un entier positif")
        total = 0
        while True:
            with self._connexion() as cnx:
                lignes = cnx.execute(
                    "SELECT id, texte FROM memoire.fragments f WHERE f.embedding IS NULL AND " + _EN_VIGUEUR +
                    " AND (%s OR f.sensibilite <> 'personnelle') ORDER BY f.id LIMIT %s FOR UPDATE SKIP LOCKED",
                    (inclure_personnelles, lot),
                ).fetchall()
                if not lignes:
                    return total
                vecteurs = list(plongeur([texte for _, texte in lignes]))
                if len(vecteurs) != len(lignes):
                    raise ValueError(f"le plongeur a rendu {len(vecteurs)} vecteurs pour {len(lignes)} textes")
                cnx.cursor().executemany(
                    "UPDATE memoire.fragments SET embedding = %s::vector WHERE id = %s",
                    [(_vecteur(v), ident) for (ident, _), v in zip(lignes, vecteurs, strict=True)],
                )
                total += len(lignes)

    def etat(self) -> dict[str, int]:
        """Compteurs d'exploitation, pour la console et M8."""
        with self._connexion() as cnx:
            ligne = cnx.execute(
                "SELECT (SELECT count(*) FROM memoire.documents), count(*),"
                " count(*) FILTER (WHERE embedding IS NULL),"
                " count(*) FILTER (WHERE expire_le IS NOT NULL AND expire_le <= now()),"
                " count(*) FILTER (WHERE sensibilite = 'personnelle')"
                " FROM memoire.fragments"
            ).fetchone()
        cles = ("documents", "fragments", "sans_embedding", "echus_a_purger", "personnels")
        return {cle: int(valeur) for cle, valeur in zip(cles, ligne, strict=True)}

    @staticmethod
    def _supprimer_orphelins(cnx: psycopg.Connection[Any], documents: set[int]) -> int:
        if not documents:
            return 0
        return cnx.execute(_SQL_ORPHELINS, (sorted(documents),)).rowcount
