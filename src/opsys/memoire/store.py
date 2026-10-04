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

    from .ingestion_procedures import CitationVerifiee

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


class _VersionProcedureInactive(ValueError):
    """La version source n'est plus la version explicitement activée."""


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
    citations_verifiees: tuple[CitationVerifiee, ...] = ()


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
    filtres = dict(filtres)
    speciaux = {cle: filtres.pop(cle) for cle in ("sujets_autorises", "portees_globales") if cle in filtres}
    inconnus = sorted(set(filtres) - set(_GABARITS_FILTRE))
    if inconnus:
        raise ValueError(f"filtre inconnu : {inconnus} (acceptés : {list(FILTRES)})")
    morceaux, parametres = [], {}
    if speciaux:
        if "sujets_autorises" not in speciaux:
            raise ValueError("autorité mémoire : sujets serveur requis")
        sujets = speciaux["sujets_autorises"]
        parametres["autorite_sujets"] = [] if sujets == [] else _chaines("sujets_autorises", sujets)
        globales = speciaux.get("portees_globales", [])
        if globales not in ([], ["procedures"]):
            raise ValueError("autorité mémoire : portée globale non prise en charge")
        parametres["autorite_globales"] = globales
        morceaux.append(
            "((cardinality(f.sujets)>0 AND f.sujets && %(autorite_sujets)s::text[] "
            "AND f.sujets <@ %(autorite_sujets)s::text[]) OR "
            "(f.portee=ANY(%(autorite_globales)s::text[]) AND f.sensibilite IN ('publique','interne') "
            "AND NOT EXISTS (SELECT 1 FROM unnest(f.sujets) s WHERE s LIKE 'client:%%' "
            "OR s LIKE 'chantier:%%')))"
        )
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
_EN_VIGUEUR = "(f.expire_le IS NULL OR f.expire_le > now()) AND ("
_EN_VIGUEUR += "NOT EXISTS (SELECT 1 FROM memoire.documents sd WHERE sd.id=f.document_id "
_EN_VIGUEUR += "AND sd.source LIKE 'opsys-document://%%') OR EXISTS ("
_EN_VIGUEUR += "SELECT 1 FROM memoire.procedure_versions pv JOIN memoire.procedure_series ps "
_EN_VIGUEUR += "USING(document_uuid) WHERE pv.document_id=f.document_id AND pv.etat='INDEXE' "
_EN_VIGUEUR += "AND ps.sha256_courante=pv.sha256))"

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
        WHERE f.embedding IS NOT NULL
          AND ((%(embedding_profile_sha256)s::text IS NULL AND f.embedding_profile_sha256 IS NULL
                AND f.embedding_status='legacy_unknown')
               OR (f.embedding_status='ready'
                   AND f.embedding_profile_sha256 = %(embedding_profile_sha256)s::text))
          AND {en_vigueur} AND {filtres}
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
INSERT INTO memoire.fragments (document_id, texte, empreinte, embedding, embedding_profile_sha256,
                               embedding_status, departement, portee, sensibilite, sujets, metadonnees,
                               cree_le, expire_le)
VALUES (%(document_id)s, %(texte)s, %(empreinte)s, %(embedding)s::vector, NULL,
        %(embedding_status)s, %(departement)s, %(portee)s, %(sensibilite)s,
        %(sujets)s::text[], %(attributs)s::jsonb, COALESCE(%(cree_le)s, now()), %(expire_le)s)
ON CONFLICT (document_id, empreinte, departement, portee) DO UPDATE SET
    embedding = CASE WHEN memoire.fragments.embedding IS NULL THEN EXCLUDED.embedding
                     ELSE memoire.fragments.embedding END,
    embedding_profile_sha256 = CASE WHEN memoire.fragments.embedding IS NULL
                                    THEN EXCLUDED.embedding_profile_sha256
                                    ELSE memoire.fragments.embedding_profile_sha256 END,
    embedding_status = CASE WHEN memoire.fragments.embedding IS NULL THEN EXCLUDED.embedding_status
                            ELSE memoire.fragments.embedding_status END
WHERE memoire.fragments.departement = EXCLUDED.departement
  AND memoire.fragments.portee = EXCLUDED.portee
  AND memoire.fragments.sensibilite = EXCLUDED.sensibilite
  AND memoire.fragments.sujets = EXCLUDED.sujets
  AND memoire.fragments.metadonnees = EXCLUDED.metadonnees
  AND memoire.fragments.expire_le IS NOT DISTINCT FROM EXCLUDED.expire_le
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

    @contextlib.contextmanager
    def _connexion_documentaire(self) -> Iterator[psycopg.Connection[Any]]:
        """Opérations d'ingestion seules : attente et calcul bornés, sans changer les appels historiques."""
        psycopg = _psycopg()
        try:
            with self._connexion() as cnx:
                cnx.execute("SET LOCAL lock_timeout = '2s'")
                cnx.execute("SET LOCAL statement_timeout = '5s'")
                yield cnx
        except psycopg.errors.LockNotAvailable as exc:
            raise MemoireIndisponible("STOCKAGE_OCCUPE : admission documentaire annulée sans mutation") from exc
        except psycopg.errors.QueryCanceled as exc:
            raise MemoireIndisponible("OPERATION_DOCUMENTAIRE_DEPASSEE : transaction annulée sans mutation") from exc
        except MemoireIndisponible as exc:
            raison = str(exc).lower()
            if "lock timeout" in raison:
                raise MemoireIndisponible("STOCKAGE_OCCUPE : admission documentaire annulée sans mutation") from exc
            if "statement timeout" in raison:
                raise MemoireIndisponible(
                    "OPERATION_DOCUMENTAIRE_DEPASSEE : transaction annulée sans mutation"
                ) from exc
            raise

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
        if valeurs["source"].startswith("opsys-document://"):
            raise ValueError("source réservée à l'admission vérifiée de procédures")
        valeurs.update(texte=propre, empreinte=hashlib.sha256(propre.encode("utf-8")).hexdigest(),
                       embedding=None if embedding is None else _vecteur(embedding),
                       embedding_status="pending" if embedding is None else "legacy_unknown")
        with self._connexion() as cnx:
            (valeurs["document_id"],) = cnx.execute(
                "INSERT INTO memoire.documents (source, titre) VALUES (%(source)s, %(titre)s)"
                " ON CONFLICT (source) DO UPDATE SET titre = COALESCE(memoire.documents.titre, EXCLUDED.titre)"
                " RETURNING id",
                valeurs,
            ).fetchone()
            retour = cnx.execute(_SQL_AJOUT, valeurs).fetchone()
            if retour is None:
                raise ValueError(
                    "fragment déjà mémorisé avec une gouvernance différente; une reclassification explicite est requise"
                )
            (ident,) = retour
        return int(ident)

    def rechercher(
        self, requete: str, embedding_requete: Sequence[float] | None, k: int, filtres: Mapping[str, Any],
        *, embedding_profile_sha256: str | None = None,
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
            if embedding_profile_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", embedding_profile_sha256):
                raise ValueError("embedding_profile_sha256 doit être un SHA-256 hexadécimal minuscule")
            parametres["embedding_profile_sha256"] = embedding_profile_sha256
        elif embedding_profile_sha256 is not None:
            raise ValueError("un profil d'embedding exige un vecteur de requête")
        gabarit = _SQL_HYBRIDE if hybride else _SQL_PLEIN_TEXTE
        sql = gabarit.format(colonnes=_COLONNES, en_vigueur=_EN_VIGUEUR, filtres=clause,
                             jointure=_JOINTURE_DOCUMENTS if jointure else "")
        psycopg = _psycopg()
        with self._connexion() as cnx:
            profil_disponible = None
            if hybride:
                # Filtres sélectifs : un parcours HNSW itératif évite de rendre moins de candidats que demandé.
                cnx.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true),"
                            " set_config('hnsw.ef_search', %s, true)", (str(max(40, candidats)),))
            with cnx.cursor(row_factory=psycopg.rows.dict_row) as curseur:
                lignes = curseur.execute(sql, parametres).fetchall()
            if embedding_profile_sha256 is not None:
                sql_disponible = (
                    "SELECT EXISTS (SELECT 1 FROM memoire.fragments f JOIN memoire.documents d ON d.id=f.document_id"
                    f" WHERE f.embedding IS NOT NULL AND f.embedding_status='ready'"
                    " AND f.embedding_profile_sha256=%(embedding_profile_sha256)s::text"
                    f" AND {_EN_VIGUEUR} AND {clause})"
                )
                (profil_disponible,) = cnx.execute(sql_disponible, parametres).fetchone()
            citations = self._citations_verifiees(cnx, lignes)
            for ligne in lignes:
                if ligne["source"].startswith("opsys-document://") and ligne["fragment_id"] not in citations:
                    raise ValueError("provenance de citation documentaire absente")
        resultats = []
        for ligne in lignes:
            resultat = _resultat(ligne)
            resultats.append(dataclasses.replace(resultat,
                                citations_verifiees=tuple(citations.get(resultat.fragment_id, ()))))
        mode = "hybride" if hybride and profil_disponible is not False else "plein_texte"
        return Recherche(mode=mode,
                         resultats=tuple(resultats))

    @staticmethod
    def _citations_verifiees(cnx: Any, lignes: Sequence[Mapping[str, Any]]) -> dict[int, list[Any]]:
        import hashlib

        from .ingestion_procedures import CitationVerifiee, Position, extraire
        identifiants = [int(ligne["fragment_id"]) for ligne in lignes]
        if not identifiants:
            return {}
        versions = cnx.execute("SELECT DISTINCT version_id FROM memoire.procedure_occurrences"
                               " WHERE fragment_id=ANY(%s) ORDER BY version_id", (identifiants,)).fetchall()
        version_ids = [row[0] for row in versions]
        if not version_ids:
            return {}
        sources = cnx.execute(
            "SELECT v.id,v.document_uuid::text,v.document_id,v.sha256,v.extracteur,v.auteur,v.corps"
            " FROM memoire.procedure_versions v JOIN memoire.procedure_series s USING(document_uuid)"
            " WHERE v.id=ANY(%s) AND v.etat='INDEXE' AND s.sha256_courante=v.sha256", (version_ids,)).fetchall()
        source_par_version: dict[int, tuple[str, int, str, str, str, bytes, tuple[Any, ...]]] = {}
        for version_id, document_uuid, document_id, digest, extracteur, auteur, corps_brut in sources:
            corps = bytes(corps_brut)
            if hashlib.sha256(corps).hexdigest() != digest:
                raise ValueError(f"intégrité de la source documentaire invalide (version {version_id})")
            if extracteur != "procedures-1":
                raise ValueError(f"version d'extracteur documentaire non prise en charge : {extracteur}")
            source_par_version[version_id] = (document_uuid, document_id, digest, extracteur, auteur,
                                              corps, extraire(corps))
        occurrences = cnx.execute(
            "SELECT o.version_id,o.fragment_id,f.document_id,f.departement,f.portee,f.sensibilite,f.texte,"
            "o.debut_octets,o.fin_octets,o.ligne_debut,o.ligne_fin,o.section "
            "FROM memoire.procedure_occurrences o JOIN memoire.fragments f ON f.id=o.fragment_id "
            "WHERE o.version_id=ANY(%s) ORDER BY o.version_id,o.debut_octets", (version_ids,)).fetchall()
        par_version: dict[int, list[Any]] = {ident: [] for ident in version_ids}
        for occurrence in occurrences:
            par_version[occurrence[0]].append(occurrence)
        groupe: dict[int, list[Position]] = {}
        meta: dict[int, tuple[str, str, str, str, int]] = {}
        for version_id, (document_uuid, document_id, digest, extracteur, auteur, corps, chunks) in (
                source_par_version.items()):
            lignes_version = par_version.get(version_id, [])
            if len(lignes_version) != len(chunks):
                raise ValueError("compte d'occurrences documentaires différent de la source extraite")
            comptes: dict[int, int] = {}
            positions_par_fragment: dict[int, list[Position]] = {}
            for index, occurrence in enumerate(lignes_version):
                (_, fragment_id, fragment_document_id, departement, portee, sensibilite, fragment,
                 debut, fin, ligne_debut, ligne_fin, section) = occurrence
                chunk = chunks[index]
                if (fragment_document_id != document_id or departement != "m03-estimation"
                        or portee != "procedures" or sensibilite != "interne"):
                    raise ValueError("lien de provenance documentaire hors document ou portée canonique")
                if debut < 0 or fin <= debut or fin > len(corps):
                    raise ValueError("offset documentaire hors des octets source")
                try:
                    extrait = corps[debut:fin].decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise ValueError("offset UTF-8 de citation invalide") from exc
                texte_attendu = valider_texte(chunk.texte)
                if (debut, fin, ligne_debut, ligne_fin, tuple(section)) != (
                        chunk.debut_octets, chunk.fin_octets, chunk.ligne_debut, chunk.ligne_fin, chunk.section
                ) or unicodedata.normalize("NFC", extrait.strip()) != texte_attendu or fragment != texte_attendu:
                    raise ValueError("offset, lignes ou section de citation différents de la source")
                comptes[fragment_id] = comptes.get(fragment_id, 0) + 1
                positions_par_fragment.setdefault(fragment_id, []).append(
                    Position(debut, fin, ligne_debut, ligne_fin, tuple(section)))
            for fragment_id, total in comptes.items():
                if fragment_id in identifiants:
                    groupe[fragment_id] = positions_par_fragment[fragment_id][:3]
                    meta[fragment_id] = (document_uuid, digest, extracteur, auteur, total)
        return {fragment_id: [CitationVerifiee(*meta[fragment_id], tuple(positions))]
                for fragment_id, positions in groupe.items()}

    def procedures(self):
        """Service d'admission M03; les paramètres de gouvernance sont fixés côté serveur."""
        from .ingestion_procedures import IngestionProcedures
        return IngestionProcedures(self)

    def vectoriser_procedures(
        self, document_id: str, sha256: str, embedder: Any, *, limite: int = 8
    ) -> dict[str, int]:
        """Vectorise explicitement des fragments d'une version M03 active, sans transaction HTTP ouverte.

        `embedder` doit fournir le client local fingerprinté. Les lectures et écritures sont des transactions
        séparées; l'écriture est un CAS contre l'activation exacte. Une coupure laisse des fragments reprenables.
        """
        import uuid

        from .ingestion_procedures import extraire

        try:
            ident = str(uuid.UUID(document_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("document_id doit être un UUID logique") from exc
        if ident != document_id or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("UUID canonique et SHA-256 minuscule de la version attendus")
        if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= 8:
            raise ValueError("limite doit être un entier de 1 à 8 fragments")
        if not getattr(embedder, "local", False):
            raise ValueError("vectorisation M03 réservée au provider explicitement local")
        profil = embedder.verifier_profil_local()
        if not isinstance(profil, str) or not re.fullmatch(r"[0-9a-f]{64}", profil):
            raise ValueError("handshake local sans empreinte de profil valide")

        with self._connexion_documentaire() as cnx:
            version = self._version_procedure_active(cnx, ident, sha256)
            version_id, document_db_id, corps = version
            chunks = extraire(corps)
            chunks_par_offsets = {(c.debut_octets, c.fin_octets): c for c in chunks}
            lignes = cnx.execute(
                "SELECT f.id,f.texte,f.embedding_status,f.embedding_profile_sha256,f.embedding,"
                "o.debut_octets,o.fin_octets,o.ligne_debut,o.ligne_fin,o.section "
                "FROM memoire.procedure_occurrences o JOIN memoire.fragments f ON f.id=o.fragment_id "
                "JOIN memoire.documents d ON d.id=f.document_id "
                "WHERE o.version_id=%s AND d.id=%s AND d.source=%s ORDER BY f.id,o.debut_octets",
                (version_id, document_db_id, f"opsys-document://{ident}/{sha256}"),
            ).fetchall()
            if len(lignes) != len(chunks):
                raise ValueError("occurrences de procédure différentes de la source extraite")
            fragments: dict[int, tuple[str, str, str | None, bool, int, int]] = {}
            for (fragment_id, texte, etat, profil_ligne, embedding, debut, fin, ld, lf, section) in lignes:
                chunk = chunks_par_offsets.get((debut, fin))
                if (chunk is None or texte != valider_texte(chunk.texte)
                        or (ld, lf, tuple(section)) != (chunk.ligne_debut, chunk.ligne_fin, chunk.section)):
                    raise ValueError("provenance de fragment différente des octets source")
                fragments.setdefault(
                    fragment_id, (texte, etat, profil_ligne, embedding is not None, debut, fin)
                )
            candidats = [
                (fragment_id, texte, etat, profil_ligne, debut, fin)
                for fragment_id, (texte, etat, profil_ligne, a_embedding, debut, fin) in fragments.items()
                if ((etat == "pending" and not a_embedding)
                    or (etat == "trop_long" and not a_embedding and profil_ligne != profil)
                    or (etat == "ready" and a_embedding and profil_ligne != profil))
            ][:limite]

        vect = trop_longs = ignores = 0
        for fragment_id, texte, etat_precedent, profil_precedent, debut_octets, fin_octets in candidats:
            try:
                resultat = embedder.plonger_avec_profil([texte])
            except Exception as exc:
                if not (getattr(exc, "http_status", None) == 413
                        and getattr(exc, "code", None) == "input_token_limit_exceeded"):
                    raise
                etat_cible = "trop_long"
                vecteur = None
            else:
                if resultat.profile_sha256 != profil or len(resultat.vecteurs) != 1:
                    raise ValueError("profil ou nombre de vecteurs différent du handshake local")
                vecteur = _vecteur(resultat.vecteurs[0])
                etat_cible = "ready"

            with self._connexion_documentaire() as cnx:
                try:
                    courant = self._version_procedure_active(cnx, ident, sha256)
                except _VersionProcedureInactive:
                    ignores += 1
                    continue
                if courant[0] != version_id or courant[1] != document_db_id:
                    ignores += 1
                    continue
                retour = cnx.execute(
                    "UPDATE memoire.fragments f SET embedding=%s::vector,embedding_profile_sha256=%s,"
                    "embedding_status=%s WHERE f.id=%s AND f.texte=%s "
                    "AND f.embedding_status=%s AND f.embedding_profile_sha256 IS NOT DISTINCT FROM %s "
                    "AND ((f.embedding_status='pending' AND f.embedding IS NULL) OR "
                    "(f.embedding_status='trop_long' AND f.embedding IS NULL) OR "
                    "(f.embedding_status='ready' AND f.embedding IS NOT NULL)) "
                    "AND EXISTS (SELECT 1 FROM memoire.procedure_occurrences o "
                    "JOIN memoire.procedure_versions v ON v.id=o.version_id "
                    "JOIN memoire.procedure_series s USING(document_uuid) "
                    "JOIN memoire.documents d ON d.id=v.document_id "
                    "WHERE o.fragment_id=f.id AND v.id=%s AND v.sha256=%s AND v.etat='INDEXE' "
                    "AND s.sha256_courante=v.sha256 AND d.source=%s AND v.corps=%s "
                    "AND o.debut_octets=%s AND o.fin_octets=%s)",
                    (vecteur, profil, etat_cible, fragment_id, texte, etat_precedent, profil_precedent,
                     version_id, sha256,
                     f"opsys-document://{ident}/{sha256}", courant[2], debut_octets, fin_octets),
                ).rowcount
            if retour:
                if vecteur is None:
                    trop_longs += 1
                else:
                    vect += 1
            else:
                ignores += 1
        return {"vectorises": vect, "trop_longs": trop_longs, "ignores_cas": ignores,
                "candidats_limite": len(candidats)}

    @staticmethod
    def _version_procedure_active(cnx: Any, ident: str, sha256: str) -> tuple[int, int, bytes]:
        import hashlib

        ligne = cnx.execute(
            "SELECT v.id,v.document_id,v.corps,v.etat,s.sha256_courante,v.sha256 "
            "FROM memoire.procedure_versions v JOIN memoire.procedure_series s USING(document_uuid) "
            "WHERE v.document_uuid=%s::uuid AND v.sha256=%s",
            (ident, sha256),
        ).fetchone()
        if ligne is None or ligne[3] != "INDEXE" or ligne[4] != sha256 or ligne[5] != sha256:
            raise _VersionProcedureInactive("version absente, non INDEXE ou inactive; activation explicite requise")
        corps = bytes(ligne[2])
        if hashlib.sha256(corps).hexdigest() != sha256:
            raise ValueError("empreinte de la source admise invalide")
        return int(ligne[0]), int(ligne[1]), corps

    @staticmethod
    def _empreinte_cle_lot(cle_lot: str) -> str:
        if (not isinstance(cle_lot, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", cle_lot)):
            raise ValueError("clé de lot opaque de 16 à 128 caractères attendue")
        return hashlib.sha256(b"opsys-m10-import-lot-v1\0" + cle_lot.encode("ascii")).hexdigest()

    @staticmethod
    def _cle_admission_lot(cle_lot_sha256: str, position: int) -> str:
        brut = f"opsys-m10-import-slot-v1:{cle_lot_sha256}:{position}".encode("ascii")
        return hashlib.sha256(brut).hexdigest()

    @staticmethod
    def _valider_source_procedure(contenu: bytes) -> str:
        from .ingestion_procedures import OCTETS_MAX, extraire

        if not isinstance(contenu, bytes) or not contenu or len(contenu) > OCTETS_MAX:
            raise ValueError("source UTF-8 de 1 à 1 MiB attendue")
        try:
            texte_source = contenu.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("UTF-8 strict attendu") from exc
        if not texte_source.strip() or "\x00" in texte_source:
            raise ValueError("source vide ou contenant NUL refusée")
        extraire(contenu)
        return hashlib.sha256(contenu).hexdigest()

    @staticmethod
    def _verrouiller_quota_procedure(cnx: Any) -> None:
        cnx.execute("SELECT pg_advisory_xact_lock(hashtext('opsys.memoire.procedure.quota'))")

    @staticmethod
    def _verrouiller_lot_procedure(cnx: Any, cle_lot_sha256: str) -> None:
        cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("opsys.memoire.procedure.lot." + cle_lot_sha256,))

    def _admettre_procedure(self, contenu: bytes, titre: str, *, auteur: str, cle_admission: str,
                            document_id: str | None):
        import uuid


        digest = self._valider_source_procedure(contenu)
        if not isinstance(titre, str) or not titre.strip() or len(titre) > 300:
            raise ValueError("titre obligatoire (300 caractères au plus)")
        if not isinstance(auteur, str) or not auteur.strip() or len(auteur) > 200:
            raise ValueError("auteur administrateur obligatoire")
        if (not isinstance(cle_admission, str) or not 16 <= len(cle_admission) <= 128
                or not re.fullmatch(r"[A-Za-z0-9_-]+", cle_admission)):
            raise ValueError("clé d'admission opaque de 16 à 128 caractères attendue")
        ident_fourni = None
        if document_id is not None:
            try:
                ident_fourni = str(uuid.UUID(document_id))
            except (ValueError, AttributeError) as exc:
                raise ValueError("UUID logique invalide") from exc
        with self._connexion_documentaire() as cnx:
            return self._admettre_procedure_dans_cnx(
                cnx, contenu, digest, titre.strip(), auteur.strip(), cle_admission, ident_fourni
            )

    def _admettre_procedure_dans_cnx(
        self, cnx: Any, contenu: bytes, digest: str, titre: str, auteur: str, cle_admission: str,
        ident_fourni: str | None, *, quota_verrouille: bool = False,
    ):
        """Insère ou rejoue une source dans la transaction détenue par l'appelant."""
        import uuid

        from .ingestion_procedures import Admission

        if not quota_verrouille:
            self._verrouiller_quota_procedure(cnx)
        if cnx.execute("SELECT 1 FROM memoire.procedure_admission_oubliees WHERE cle_admission=%s",
                       (cle_admission,)).fetchone():
            raise ValueError("clé d'admission oubliée : une nouvelle admission exige une nouvelle clé")
        commande = cnx.execute(
            "SELECT v.id,v.etat,v.sha256,v.auteur,d.titre,s.document_uuid::text"
            " FROM memoire.procedure_versions v JOIN memoire.documents d ON d.id=v.document_id"
            " JOIN memoire.procedure_series s USING(document_uuid) WHERE v.cle_admission=%s",
            (cle_admission,),
        ).fetchone()
        if commande:
            if (commande[2] != digest or commande[3] != auteur or commande[4] != titre
                    or (ident_fourni is not None and commande[5] != ident_fourni)):
                raise ValueError("conflit : clé d'admission déjà liée à une autre commande")
            return Admission(commande[5], digest, int(commande[0]), commande[1])
        ident = ident_fourni or str(uuid.uuid4())
        uri = f"opsys-document://{ident}/{digest}"
        cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("opsys.memoire.procedure." + ident,))
        existante = cnx.execute(
            "SELECT v.id, v.etat FROM memoire.procedure_versions v"
            " WHERE v.document_uuid = %s::uuid AND v.sha256 = %s", (ident, digest)
        ).fetchone()
        if existante:
            raise ValueError("version déjà admise : réutiliser sa clé d'admission idempotente")
        serie = cnx.execute("SELECT 1 FROM memoire.procedure_series WHERE document_uuid=%s::uuid FOR UPDATE",
                            (ident,)).fetchone()
        if serie is None:
            if ident_fourni is not None:
                raise ValueError("UUID initial fourni interdit; l'identité logique est générée par le serveur")
            (n_series,) = cnx.execute("SELECT count(*) FROM memoire.procedure_series").fetchone()
            if n_series >= 64:
                raise ValueError("quota atteint : 64 séries de procédures")
            cnx.execute("INSERT INTO memoire.procedure_series(document_uuid,titre) VALUES (%s::uuid,%s)",
                        (ident, titre))
            version_no = 1
        else:
            (version_no,) = cnx.execute(
                "SELECT COALESCE(max(version_no),0)+1 FROM memoire.procedure_versions"
                " WHERE document_uuid=%s::uuid", (ident,)
            ).fetchone()
            if version_no > 8:
                raise ValueError("quota atteint : 8 versions par série")
        (octets_existants,) = cnx.execute(
            "SELECT COALESCE(sum(octet_length(corps)),0) FROM memoire.procedure_versions"
        ).fetchone()
        if octets_existants + len(contenu) > 64 * 1024 * 1024:
            raise ValueError("quota global de 64 MiB atteint")
        (db_document_id,) = cnx.execute(
            "INSERT INTO memoire.documents(source,titre) VALUES (%s,%s) RETURNING id", (uri, titre)
        ).fetchone()
        (version_pk,) = cnx.execute(
            "INSERT INTO memoire.procedure_versions(document_uuid,version_no,sha256,cle_admission,"
            "document_id,corps,auteur,etat,extracteur)"
            " VALUES (%s::uuid,%s,%s,%s,%s,%s,%s,'RECU','procedures-1') RETURNING id",
            (ident, version_no, digest, cle_admission, db_document_id, contenu, auteur),
        ).fetchone()
        return Admission(ident, digest, int(version_pk), "RECU")

    def _sources_lot_procedure(self, sources: Sequence[Any]):
        import uuid

        from .ingestion_procedures import SourceLot

        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)) or not 1 <= len(sources) <= 5:
            raise ValueError("un lot doit décrire de 1 à 5 emplacements")
        resultat = []
        positions = set()
        for source in sources:
            if not isinstance(source, SourceLot):
                raise ValueError("chaque source doit être un SourceLot")
            if (isinstance(source.position, bool) or not isinstance(source.position, int)
                    or not 1 <= source.position <= 5):
                raise ValueError("position de lot entre 1 et 5 attendue")
            if source.position in positions:
                raise ValueError("positions de lot dupliquées")
            positions.add(source.position)
            if (not isinstance(source.titre, str) or not source.titre.strip() or len(source.titre) > 300
                    or not isinstance(source.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", source.sha256) is None):
                raise ValueError("titre et SHA-256 documentaire valides attendus")
            cible = None
            if source.serie_cible_id is not None:
                try:
                    cible = str(uuid.UUID(source.serie_cible_id))
                except (ValueError, AttributeError, TypeError) as exc:
                    raise ValueError("UUID de série cible invalide") from exc
            resultat.append(SourceLot(source.position, source.titre.strip(), source.sha256, cible))
        return tuple(sorted(resultat, key=lambda source: source.position))

    def _creer_lot_procedure(self, cle_lot: str, sources: Sequence[Any], *, auteur: str):
        cle_sha = self._empreinte_cle_lot(cle_lot)
        propres = self._sources_lot_procedure(sources)
        if not isinstance(auteur, str) or not auteur.strip() or len(auteur) > 200:
            raise ValueError("auteur administrateur obligatoire")
        auteur = auteur.strip()
        cibles = sorted({source.serie_cible_id for source in propres if source.serie_cible_id is not None})
        with self._connexion_documentaire() as cnx:
            self._verrouiller_quota_procedure(cnx)
            self._verrouiller_lot_procedure(cnx, cle_sha)
            if cnx.execute("SELECT 1 FROM memoire.procedure_lots_oublies WHERE cle_lot_sha256=%s",
                           (cle_sha,)).fetchone():
                raise ValueError("clé de lot oubliée : une nouvelle admission exige une nouvelle clé")
            ligne = cnx.execute(
                "SELECT auteur,nombre_emplacements FROM memoire.procedure_lots"
                " WHERE cle_lot_sha256=%s FOR UPDATE", (cle_sha,)
            ).fetchone()
            if ligne:
                existantes = cnx.execute(
                    "SELECT position,titre,sha256,serie_cible_id::text FROM memoire.procedure_lot_emplacements"
                    " WHERE cle_lot_sha256=%s ORDER BY position", (cle_sha,)
                ).fetchall()
                attendues = [(s.position, s.titre, s.sha256, s.serie_cible_id) for s in propres]
                if (ligne[0] != auteur or ligne[1] != len(propres)
                        or [tuple(row) for row in existantes] != attendues):
                    raise ValueError("conflit : clé de lot déjà liée à un autre manifeste ou auteur")
                return self._lire_lot_dans_cnx(cnx, cle_lot, cle_sha, auteur)
            (nombre_lots,) = cnx.execute("SELECT count(*) FROM memoire.procedure_lots").fetchone()
            if nombre_lots >= 64:
                raise ValueError("quota atteint : 64 lots vivants")
            if cibles:
                for ident in cibles:
                    # Même ordre que indexation/activation : advisory série avant le row lock.
                    cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                                ("opsys.memoire.procedure." + ident,))
                    if cnx.execute("SELECT 1 FROM memoire.procedure_series"
                                   " WHERE document_uuid=%s::uuid FOR UPDATE", (ident,)).fetchone() is None:
                        raise ValueError("série cible absente")
            cnx.execute("INSERT INTO memoire.procedure_lots(cle_lot_sha256,auteur,nombre_emplacements)"
                        " VALUES (%s,%s,%s)", (cle_sha, auteur, len(propres)))
            for source in propres:
                cnx.execute(
                    "INSERT INTO memoire.procedure_lot_emplacements(cle_lot_sha256,position,titre,sha256,"
                    "serie_cible_id) VALUES (%s,%s,%s,%s,%s::uuid)",
                    (cle_sha, source.position, source.titre, source.sha256, source.serie_cible_id),
                )
            return self._lire_lot_dans_cnx(cnx, cle_lot, cle_sha, auteur)

    def _lire_lot_dans_cnx(self, cnx: Any, cle_lot: str, cle_sha: str, auteur: str):
        from .ingestion_procedures import EmplacementLot, LotProcedure

        manifeste = cnx.execute("SELECT auteur,nombre_emplacements FROM memoire.procedure_lots"
                                " WHERE cle_lot_sha256=%s", (cle_sha,)).fetchone()
        if manifeste is None:
            if cnx.execute("SELECT 1 FROM memoire.procedure_lots_oublies WHERE cle_lot_sha256=%s",
                           (cle_sha,)).fetchone():
                raise ValueError("lot oublié")
            raise ValueError("lot absent")
        if manifeste[0] != auteur:
            raise ValueError("auteur différent du propriétaire du lot")
        rows = cnx.execute(
            "SELECT e.position,e.titre,e.sha256,e.serie_cible_id::text,v.document_uuid::text,v.etat,"
            "(v.sha256=s.sha256_courante) FROM memoire.procedure_lot_emplacements e"
            " LEFT JOIN memoire.procedure_versions v ON v.id=e.version_id"
            " LEFT JOIN memoire.procedure_series s ON s.document_uuid=v.document_uuid"
            " WHERE e.cle_lot_sha256=%s ORDER BY e.position", (cle_sha,)
        ).fetchall()
        if len(rows) != manifeste[1]:
            raise ValueError("manifeste du lot incomplet")
        emplacements = tuple(
            EmplacementLot(int(row[0]), row[1], row[2], row[3], row[4], row[5] or "ATTENTE",
                           bool(row[6]) if row[5] else False)
            for row in rows
        )
        return LotProcedure(cle_lot, auteur, emplacements)

    def _lire_lot_procedure(self, cle_lot: str, *, auteur: str):
        cle_sha = self._empreinte_cle_lot(cle_lot)
        if not isinstance(auteur, str) or not auteur.strip():
            raise ValueError("auteur administrateur obligatoire")
        with self._connexion_documentaire() as cnx:
            self._verrouiller_quota_procedure(cnx)
            self._verrouiller_lot_procedure(cnx, cle_sha)
            return self._lire_lot_dans_cnx(cnx, cle_lot, cle_sha, auteur.strip())

    def _admettre_emplacement_lot(self, cle_lot: str, position: int, contenu: bytes, *, auteur: str):
        cle_sha = self._empreinte_cle_lot(cle_lot)
        if isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= 5:
            raise ValueError("position de lot entre 1 et 5 attendue")
        if not isinstance(auteur, str) or not auteur.strip() or len(auteur) > 200:
            raise ValueError("auteur administrateur obligatoire")
        digest = self._valider_source_procedure(contenu)
        auteur = auteur.strip()
        with self._connexion_documentaire() as cnx:
            self._verrouiller_quota_procedure(cnx)
            self._verrouiller_lot_procedure(cnx, cle_sha)
            manifeste = cnx.execute("SELECT auteur FROM memoire.procedure_lots WHERE cle_lot_sha256=%s FOR UPDATE",
                                    (cle_sha,)).fetchone()
            if manifeste is None:
                if cnx.execute("SELECT 1 FROM memoire.procedure_lots_oublies WHERE cle_lot_sha256=%s",
                               (cle_sha,)).fetchone():
                    raise ValueError("lot oublié")
                raise ValueError("lot absent")
            if manifeste[0] != auteur:
                raise ValueError("auteur différent du propriétaire du lot")
            emplacement = cnx.execute(
                "SELECT titre,sha256,serie_cible_id::text,version_id FROM memoire.procedure_lot_emplacements"
                " WHERE cle_lot_sha256=%s AND position=%s FOR UPDATE", (cle_sha, position)
            ).fetchone()
            if emplacement is None:
                raise ValueError("emplacement absent du manifeste")
            titre, attendu, cible, version_id = emplacement
            if digest != attendu:
                raise ValueError("empreinte de source différente du manifeste du lot")
            if version_id is not None:
                version = cnx.execute("SELECT document_uuid::text FROM memoire.procedure_versions WHERE id=%s",
                                      (version_id,)).fetchone()
                if version is None:
                    raise ValueError("version liée au lot absente")
                return self._lire_lot_dans_cnx(cnx, cle_lot, cle_sha, auteur)
            admission = self._admettre_procedure_dans_cnx(
                cnx, contenu, digest, titre, auteur, self._cle_admission_lot(cle_sha, position), cible,
                quota_verrouille=True,
            )
            maj = cnx.execute(
                "UPDATE memoire.procedure_lot_emplacements SET version_id=%s"
                " WHERE cle_lot_sha256=%s AND position=%s AND version_id IS NULL",
                (admission.version_id, cle_sha, position),
            )
            if maj.rowcount != 1:
                raise ValueError("conflit de rattachement d'emplacement")
            return self._lire_lot_dans_cnx(cnx, cle_lot, cle_sha, auteur)

    def _etat_procedure(self, document_id: str, *, absent_ok: bool = False):
        import uuid

        from .ingestion_procedures import EtatDocument
        try:
            ident = str(uuid.UUID(document_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError("UUID logique invalide") from exc
        with self._connexion_documentaire() as cnx:
            row = cnx.execute(
                "SELECT s.sha256_courante, v.sha256, v.etat FROM memoire.procedure_series s"
                " LEFT JOIN LATERAL (SELECT sha256,etat FROM memoire.procedure_versions"
                " WHERE document_uuid=s.document_uuid ORDER BY version_no DESC LIMIT 1) v ON true"
                " WHERE s.document_uuid=%s::uuid", (ident,)).fetchone()
        if row is None:
            if absent_ok:
                return None
            raise ValueError("document absent")
        return EtatDocument(ident, row[2] or "RECU", row[0])

    def _lister_series_procedure(self, *, limite: int = 50, offset: int = 0):
        from .ingestion_procedures import PageSeries
        if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= 50:
            raise ValueError("limite doit être un entier de 1 à 50")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 64:
            raise ValueError("offset doit être un entier de 0 à 64")
        with self._connexion_documentaire() as cnx:
            (total,) = cnx.execute("SELECT count(*) FROM memoire.procedure_series").fetchone()
            lignes = cnx.execute(
                "SELECT s.document_uuid::text,s.titre,s.sha256_courante,latest.sha256,latest.etat,"
                "(SELECT count(*) FROM memoire.procedure_versions x WHERE x.document_uuid=s.document_uuid)"
                " FROM memoire.procedure_series s LEFT JOIN LATERAL (SELECT sha256,etat"
                " FROM memoire.procedure_versions WHERE document_uuid=s.document_uuid ORDER BY version_no DESC LIMIT 1)"
                " latest ON true ORDER BY s.cree_le DESC,s.document_uuid LIMIT %s OFFSET %s",
                (limite, offset)).fetchall()
        return PageSeries(int(total), tuple({"document_id": row[0], "titre": row[1],
                                             "version_courante": row[2], "derniere_version": row[3],
                                             "etat_derniere_version": row[4], "nombre_versions": row[5]}
                                            for row in lignes))

    def _lister_versions_procedure(self, document_id: str):
        import uuid

        from .ingestion_procedures import VersionResume
        try:
            ident = str(uuid.UUID(document_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError("UUID logique invalide") from exc
        with self._connexion_documentaire() as cnx:
            rows = cnx.execute(
                "SELECT v.sha256,v.version_no,v.etat,v.auteur,v.admis_le,s.sha256_courante,"
                "octet_length(v.corps) FROM memoire.procedure_versions v"
                " JOIN memoire.procedure_series s USING(document_uuid)"
                " WHERE v.document_uuid=%s::uuid ORDER BY v.version_no", (ident,)).fetchall()
        return tuple(VersionResume(row[0], row[1], row[2], row[3], row[4].isoformat(),
                                   row[0] == row[5], row[6]) for row in rows)

    def _lister_versions_procedure_recues(self, *, limite: int) -> tuple[tuple[str, str], ...]:
        from .ingestion_procedures import INDEXATION_LOT_MAX

        if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= INDEXATION_LOT_MAX:
            raise ValueError(f"limite doit être entre 1 et {INDEXATION_LOT_MAX}")
        with self._connexion_documentaire() as cnx:
            rows = cnx.execute(
                "SELECT document_uuid::text,sha256 FROM memoire.procedure_versions "
                "WHERE etat='RECU' ORDER BY admis_le,id LIMIT %s", (limite,)
            ).fetchall()
        return tuple((str(document_id), str(sha256)) for document_id, sha256 in rows)

    def _indexer_procedure(self, document_id: str, sha256: str):
        import hashlib
        import uuid

        from .ingestion_procedures import EtatDocument, extraire
        ident = str(uuid.UUID(document_id))
        with self._connexion_documentaire() as cnx:
            cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("opsys.memoire.procedure." + ident,))
            ligne = cnx.execute(
                "SELECT v.id,v.document_id,v.corps,v.etat,s.sha256_courante,v.sha256"
                " FROM memoire.procedure_versions v JOIN memoire.procedure_series s USING(document_uuid)"
                " WHERE v.document_uuid=%s::uuid AND v.sha256=%s FOR UPDATE OF s,v", (ident, sha256)).fetchone()
            if ligne is None:
                raise ValueError("admission absente")
            version_id, db_document_id, raw, etat, courante, digest = ligne
            if hashlib.sha256(bytes(raw)).hexdigest() != digest:
                raise ValueError("intégrité de la source admise invalide")
            if etat == "INDEXE":
                return EtatDocument(ident, etat, courante)
            chunks = extraire(bytes(raw))
            for chunk in chunks:
                texte = valider_texte(chunk.texte)
                meta = {"departement": "m03-estimation", "portee": "procedures", "source":
                        f"opsys-document://{ident}/{digest}", "sensibilite": "interne"}
                valeurs = valider_meta(meta)
                valeurs.update(texte=texte, empreinte=hashlib.sha256(texte.encode("utf-8")).hexdigest(),
                               embedding=None, embedding_status="pending")
                valeurs["document_id"] = db_document_id
                (fragment_id,) = cnx.execute(_SQL_AJOUT, valeurs).fetchone()
                cnx.execute(
                    "INSERT INTO memoire.procedure_occurrences(version_id,fragment_id,debut_octets,fin_octets,"
                    "ligne_debut,ligne_fin,section) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (version_id, fragment_id, chunk.debut_octets, chunk.fin_octets,
                     chunk.ligne_debut, chunk.ligne_fin, list(chunk.section)))
            cnx.execute("UPDATE memoire.procedure_versions SET etat='INDEXE' WHERE id=%s", (version_id,))
            return EtatDocument(ident, "INDEXE", courante)

    def _activer_procedure(self, document_id: str, sha256: str, *, attendu_sha256: str | None, auteur: str) -> None:
        import uuid
        ident = str(uuid.UUID(document_id))
        if not isinstance(auteur, str) or not auteur.strip():
            raise ValueError("auteur administrateur obligatoire")
        with self._connexion_documentaire() as cnx:
            cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("opsys.memoire.procedure." + ident,))
            row = cnx.execute("SELECT sha256_courante FROM memoire.procedure_series"
                              " WHERE document_uuid=%s::uuid FOR UPDATE", (ident,)).fetchone()
            if row is None or row[0] != attendu_sha256:
                raise ValueError("conflit CAS : version courante modifiée")
            (count,) = cnx.execute("SELECT count(*) FROM memoire.procedure_versions"
                                    " WHERE document_uuid=%s::uuid AND sha256=%s AND etat='INDEXE'",
                                    (ident, sha256)).fetchone()
            if count != 1:
                raise ValueError("seule une version INDEXE peut être activée")
            cnx.execute("UPDATE memoire.procedure_series SET sha256_courante=%s WHERE document_uuid=%s::uuid",
                        (sha256, ident))
            cnx.execute("INSERT INTO memoire.procedure_activations(document_uuid,version_precedente,version_cible,"
                        "auteur) VALUES (%s::uuid,%s,%s,%s)", (ident, row[0], sha256, auteur.strip()))

    def _oublier_procedure(self, document_id: str, *, demandeur: str, motif: str) -> int:
        import uuid
        ident = str(uuid.UUID(document_id))
        if not isinstance(demandeur, str) or not demandeur.strip() or not isinstance(motif, str) or not motif.strip():
            raise ValueError("demandeur et motif obligatoires pour journaliser l'effacement")
        with self._connexion_documentaire() as cnx:
            self._verrouiller_quota_procedure(cnx)
            lots = cnx.execute(
                "SELECT DISTINCT e.cle_lot_sha256 FROM memoire.procedure_lot_emplacements e"
                " LEFT JOIN memoire.procedure_versions v ON v.id=e.version_id"
                " WHERE v.document_uuid=%s::uuid OR e.serie_cible_id=%s::uuid"
                " ORDER BY e.cle_lot_sha256", (ident, ident)
            ).fetchall()
            self._invalider_lots_procedure_cnx(cnx, [row[0] for row in lots])
            cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("opsys.memoire.procedure." + ident,))
            cnx.execute("INSERT INTO memoire.procedure_admission_oubliees(cle_admission)"
                        " SELECT cle_admission FROM memoire.procedure_versions WHERE document_uuid=%s::uuid"
                        " ON CONFLICT DO NOTHING", (ident,))
            rows = cnx.execute("SELECT v.document_id FROM memoire.procedure_versions v"
                               " WHERE v.document_uuid=%s::uuid FOR UPDATE", (ident,)).fetchall()
            docs = [r[0] for r in rows]
            (fragments,) = cnx.execute("SELECT count(*) FROM memoire.fragments WHERE document_id=ANY(%s)",
                                       (docs,)).fetchone() if docs else (0,)
            cnx.execute("DELETE FROM memoire.procedure_series WHERE document_uuid=%s::uuid", (ident,))
            documents = cnx.execute("DELETE FROM memoire.documents WHERE id=ANY(%s)", (docs,)).rowcount if docs else 0
            cnx.execute(_SQL_JOURNAL, (demandeur.strip(), motif.strip(),
                                       json.dumps({"document_uuid": ident}), fragments, documents))
        return int(fragments)

    def _invalider_lots_procedure_cnx(self, cnx: Any, cles_sha256: Sequence[str]) -> None:
        for cle_sha in sorted(set(cles_sha256)):
            self._verrouiller_lot_procedure(cnx, cle_sha)
            cnx.execute("INSERT INTO memoire.procedure_lots_oublies(cle_lot_sha256) VALUES (%s)"
                        " ON CONFLICT DO NOTHING", (cle_sha,))
            cnx.execute("DELETE FROM memoire.procedure_lots WHERE cle_lot_sha256=%s", (cle_sha,))

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
        cles_admission = {"source", "document_id", "departement", "portee", "sensibilite"}
        admission_ciblable = (bool(set(filtres) & {"source", "document_id"})
                              and set(filtres) <= cles_admission)
        with (self._connexion_documentaire() if admission_ciblable
              else self._connexion()) as cnx:
            # Toutes les suppressions de source partagent le verrou quota avec les admissions et les lots.
            self._verrouiller_quota_procedure(cnx)
            fragments_cascade = 0
            documents_cascade = 0
            # Les admissions RECU peuvent n'avoir aucun fragment : les sélecteurs historiques par source
            # ou id de document doivent quand même retirer la source et toutes ses versions.
            if admission_ciblable:
                sources = _chaines("source", filtres["source"]) if "source" in filtres else None
                doc_id = filtres.get("document_id")
                conditions = ["(%s::text[] IS NULL OR d.source=ANY(%s::text[]))",
                              "(%s::bigint IS NULL OR d.id=%s::bigint)"]
                params = [sources, sources, doc_id, doc_id]
                gouvernance = {"departement": "m03-estimation", "portee": "procedures",
                               "sensibilite": "interne"}
                for cle, canonique in gouvernance.items():
                    if cle in filtres:
                        conditions.append("%s=ANY(%s::text[])")
                        params.extend((canonique, _chaines(cle, filtres[cle])))
                predicats = " AND ".join(conditions)
                series = cnx.execute(
                    "SELECT DISTINCT v.document_uuid::text FROM memoire.procedure_versions v"
                    " JOIN memoire.documents d ON d.id=v.document_id"
                    f" WHERE {predicats} ORDER BY 1",
                    params,
                ).fetchall()
                document_ids = cnx.execute(
                    "SELECT DISTINCT v.document_id FROM memoire.procedure_versions v"
                    " JOIN memoire.documents d ON d.id=v.document_id"
                    f" WHERE {predicats} ORDER BY v.document_id", params,
                ).fetchall()
                ids_cibles = [row[0] for row in document_ids]
                if ids_cibles:
                    lots = cnx.execute(
                        "SELECT DISTINCT e.cle_lot_sha256 FROM memoire.procedure_lot_emplacements e"
                        " JOIN memoire.procedure_versions v ON v.id=e.version_id"
                        " WHERE v.document_id=ANY(%s) ORDER BY e.cle_lot_sha256", (ids_cibles,)
                    ).fetchall()
                    cles_lots = {row[0] for row in lots}
                    ids_cibles_set = set(ids_cibles)
                    for (serie_cible,) in series:
                        docs_serie = cnx.execute(
                            "SELECT document_id FROM memoire.procedure_versions"
                            " WHERE document_uuid=%s::uuid", (serie_cible,)
                        ).fetchall()
                        if {row[0] for row in docs_serie} <= ids_cibles_set:
                            lots_cibles = cnx.execute(
                                "SELECT DISTINCT cle_lot_sha256 FROM memoire.procedure_lot_emplacements"
                                " WHERE serie_cible_id=%s::uuid ORDER BY cle_lot_sha256", (serie_cible,)
                            ).fetchall()
                            cles_lots.update(row[0] for row in lots_cibles)
                    self._invalider_lots_procedure_cnx(cnx, tuple(cles_lots))
                for (serie_id,) in series:
                    cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                                ("opsys.memoire.procedure." + serie_id,))
                    ids_docs = cnx.execute(
                        "SELECT v.document_id FROM memoire.procedure_versions v"
                        " JOIN memoire.documents d ON d.id=v.document_id"
                        f" WHERE v.document_uuid=%s::uuid AND {predicats} FOR UPDATE OF v",
                        [serie_id, *params],
                    ).fetchall()
                    ids_docs = [row[0] for row in ids_docs]
                    (fragments_serie,) = cnx.execute(
                        "SELECT count(*) FROM memoire.fragments f JOIN memoire.procedure_versions v"
                        " ON v.document_id=f.document_id WHERE v.document_id=ANY(%s)", (ids_docs,)
                    ).fetchone()
                    fragments_cascade += fragments_serie
                    if ids_docs:
                        cnx.execute("INSERT INTO memoire.procedure_admission_oubliees(cle_admission)"
                                    " SELECT cle_admission FROM memoire.procedure_versions"
                                    " WHERE document_id=ANY(%s) ON CONFLICT DO NOTHING", (ids_docs,))
                        cnx.execute("UPDATE memoire.procedure_series s SET sha256_courante=NULL"
                                    " WHERE s.document_uuid=%s::uuid AND EXISTS ("
                                    "SELECT 1 FROM memoire.procedure_versions v WHERE v.document_uuid=s.document_uuid"
                                    " AND v.document_id=ANY(%s) AND v.sha256=s.sha256_courante)",
                                    (serie_id, ids_docs))
                        documents_cascade += cnx.execute("DELETE FROM memoire.documents WHERE id=ANY(%s)",
                                                         (ids_docs,)).rowcount
                        cnx.execute("DELETE FROM memoire.procedure_series s WHERE s.document_uuid=%s::uuid"
                                    " AND NOT EXISTS (SELECT 1 FROM memoire.procedure_versions v"
                                    " WHERE v.document_uuid=s.document_uuid)", (serie_id,))
            supprimes = cnx.execute(
                f"DELETE FROM memoire.fragments f{using} WHERE {condition}"  # noqa: S608 - clause en liste blanche
                " RETURNING f.document_id",
                parametres,
            ).fetchall()
            documents = documents_cascade + self._supprimer_orphelins(cnx, {ligne[0] for ligne in supprimes})
            total_supprimes = len(supprimes) + fragments_cascade
            cnx.execute(_SQL_JOURNAL, (demandeur.strip(), motif.strip(),
                                       json.dumps(dict(filtres), ensure_ascii=False, default=str),
                                       total_supprimes, documents))
        return total_supprimes

    def purger_expires(self) -> int:
        """Supprime les fragments dont l'échéance est passée (rétention Loi 25, art. 23)."""
        with self._connexion() as cnx:
            self._verrouiller_quota_procedure(cnx)
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
                    " AND NOT EXISTS (SELECT 1 FROM memoire.documents sd WHERE sd.id=f.document_id "
                    "AND sd.source LIKE 'opsys-document://%%')" +
                    " AND (%s OR f.sensibilite <> 'personnelle') ORDER BY f.id LIMIT %s FOR UPDATE SKIP LOCKED",
                    (inclure_personnelles, lot),
                ).fetchall()
                if not lignes:
                    return total
                vecteurs = list(plongeur([texte for _, texte in lignes]))
                if len(vecteurs) != len(lignes):
                    raise ValueError(f"le plongeur a rendu {len(vecteurs)} vecteurs pour {len(lignes)} textes")
                cnx.cursor().executemany(
                    "UPDATE memoire.fragments SET embedding = %s::vector, embedding_profile_sha256=NULL,"
                    " embedding_status='legacy_unknown' WHERE id = %s",
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

    def _supprimer_orphelins(self, cnx: psycopg.Connection[Any], documents: set[int]) -> int:
        if not documents:
            return 0
        candidats = sorted(row[0] for row in cnx.execute(
            "SELECT d.id FROM memoire.documents d WHERE d.id=ANY(%s)"
            " AND NOT EXISTS (SELECT 1 FROM memoire.fragments f WHERE f.document_id=d.id) ORDER BY d.id",
            (sorted(documents),),
        ).fetchall())
        if not candidats:
            return 0

        # Stabiliser indexation pendant la décision d'orphelin : elle prend le verrou advisory de série
        # avant de créer des fragments. Le quota est déjà détenu par oublier()/purger_expires().
        versions_avant = cnx.execute(
            "SELECT id,document_uuid::text,cle_admission FROM memoire.procedure_versions"
            " WHERE document_id=ANY(%s) ORDER BY document_uuid,id", (candidats,)
        ).fetchall()
        if versions_avant:
            ids_version = [row[0] for row in versions_avant]
            series = sorted({row[1] for row in versions_avant})
            lots = cnx.execute(
                "SELECT DISTINCT cle_lot_sha256 FROM memoire.procedure_lot_emplacements"
                " WHERE version_id=ANY(%s) OR serie_cible_id=ANY(%s::uuid[]) ORDER BY cle_lot_sha256",
                (ids_version, series),
            ).fetchall()
            cles_lots_verrouillees = [row[0] for row in lots]
            for cle_sha in cles_lots_verrouillees:
                self._verrouiller_lot_procedure(cnx, cle_sha)
            for ident in series:
                cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                            ("opsys.memoire.procedure." + ident,))

            # L'indexation déjà engagée a pu finir pendant l'attente du verrou de série.
            candidats = sorted(row[0] for row in cnx.execute(
                "SELECT d.id FROM memoire.documents d WHERE d.id=ANY(%s)"
                " AND NOT EXISTS (SELECT 1 FROM memoire.fragments f WHERE f.document_id=d.id) ORDER BY d.id",
                (candidats,),
            ).fetchall())
            if candidats:
                versions = cnx.execute(
                    "SELECT id,document_uuid::text,cle_admission FROM memoire.procedure_versions"
                    " WHERE document_id=ANY(%s) ORDER BY document_uuid,id", (candidats,)
                ).fetchall()
                ids_version = [row[0] for row in versions]
                series_supprimees = []
                for ident in sorted({row[1] for row in versions}):
                    restant = cnx.execute(
                        "SELECT 1 FROM memoire.procedure_versions v WHERE v.document_uuid=%s::uuid"
                        " AND NOT (v.document_id=ANY(%s)) LIMIT 1", (ident, candidats),
                    ).fetchone()
                    if restant is None:
                        series_supprimees.append(ident)
                cles_lots = set()
                if ids_version:
                    cles_lots.update(row[0] for row in cnx.execute(
                        "SELECT DISTINCT cle_lot_sha256 FROM memoire.procedure_lot_emplacements"
                        " WHERE version_id=ANY(%s) ORDER BY cle_lot_sha256", (ids_version,)
                    ).fetchall())
                if series_supprimees:
                    cles_lots.update(row[0] for row in cnx.execute(
                        "SELECT DISTINCT cle_lot_sha256 FROM memoire.procedure_lot_emplacements"
                        " WHERE serie_cible_id=ANY(%s::uuid[]) ORDER BY cle_lot_sha256",
                        (series_supprimees,),
                    ).fetchall())
                # Ces clés ont été prises avant les advisory de série; tout nouveau lot est bloqué au quota.
                for cle_sha in sorted(cles_lots):
                    self._verrouiller_lot_procedure(cnx, cle_sha)
                cnx.execute(
                    "INSERT INTO memoire.procedure_admission_oubliees(cle_admission)"
                    " SELECT cle_admission FROM memoire.procedure_versions WHERE document_id=ANY(%s)"
                    " ON CONFLICT DO NOTHING", (candidats,),
                )
                self._invalider_lots_procedure_cnx(cnx, tuple(cles_lots))

        cnx.execute("UPDATE memoire.procedure_series s SET sha256_courante=NULL"
                    " WHERE EXISTS (SELECT 1 FROM memoire.procedure_versions v"
                    " WHERE v.document_uuid=s.document_uuid AND v.document_id=ANY(%s)"
                    " AND v.sha256=s.sha256_courante)", (candidats,))
        supprimes = cnx.execute(_SQL_ORPHELINS, (candidats,)).rowcount
        # Les FK document_id en cascade enlèvent les versions; supprimer leurs séries vides évite
        # de réserver un UUID sans source ni historique après un effacement standard.
        cnx.execute("DELETE FROM memoire.procedure_series s WHERE NOT EXISTS "
                    "(SELECT 1 FROM memoire.procedure_versions v WHERE v.document_uuid=s.document_uuid)")
        return supprimes
