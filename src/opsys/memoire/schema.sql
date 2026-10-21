-- Mémoire d'entreprise OPSYS, couche B du RAG premium : docs/memory/RAG-PREMIUM.md §4.
-- Script idempotent : `python -m opsys.memoire migrer` peut le rejouer sans effet.
-- Il exige un rôle administrateur, car l'extension vector n'est pas « trusted » (unaccent l'est).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE SCHEMA IF NOT EXISTS memoire;

-- Plein texte français insensible aux accents : « reparation » retrouve « réparation ».
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_ts_config c
        JOIN pg_namespace n ON n.oid = c.cfgnamespace
        WHERE n.nspname = 'memoire' AND c.cfgname = 'francais'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION memoire.francais (COPY = pg_catalog.french);
        ALTER TEXT SEARCH CONFIGURATION memoire.francais
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
    END IF;
END
$$;

-- Un document par source stable (URI, id d'échange) : c'est le lien de provenance des fragments.
CREATE TABLE IF NOT EXISTS memoire.documents (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source   text NOT NULL UNIQUE CHECK (btrim(source) <> '' AND length(source) <= 500),
    titre    text CHECK (titre IS NULL OR length(titre) <= 300),
    cree_le  timestamptz NOT NULL DEFAULT now()
);

-- Unité de recherche. Les métadonnées de gouvernance sont des colonnes typées et contraintes. Les
-- attributs libres (client_id, numéro de devis…) vont dans `metadonnees`.
CREATE TABLE IF NOT EXISTS memoire.fragments (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  bigint NOT NULL REFERENCES memoire.documents (id) ON DELETE CASCADE,
    texte        text NOT NULL CHECK (btrim(texte) <> ''),
    empreinte    text NOT NULL,
    embedding    vector(1024),
    embedding_profile_sha256 text,
    embedding_status text NOT NULL DEFAULT 'pending',
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('memoire.francais'::regconfig, texte)) STORED,
    departement  text NOT NULL CHECK (departement ~ '^[a-z0-9][a-z0-9-]{1,63}$'),
    portee       text NOT NULL CHECK (portee ~ '^[a-z][a-z0-9_-]{1,63}$'),
    sensibilite  text NOT NULL
                 CHECK (sensibilite IN ('publique', 'interne', 'confidentielle', 'personnelle')),
    sujets       text[] NOT NULL DEFAULT '{}',
    metadonnees  jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadonnees) = 'object'),
    cree_le      timestamptz NOT NULL DEFAULT now(),
    expire_le    timestamptz,
    CONSTRAINT fragments_unicite UNIQUE (document_id, empreinte, departement, portee),
    CONSTRAINT fragments_echeance CHECK (expire_le IS NULL OR expire_le > cree_le),
    -- Loi 25 : un renseignement personnel a toujours une échéance et un sujet, pour pouvoir l'effacer.
    CONSTRAINT fragments_personnel
        CHECK (sensibilite <> 'personnelle' OR (expire_le IS NOT NULL AND cardinality(sujets) > 0)),
    CONSTRAINT fragments_embedding_profil_etat CHECK (
        (embedding_status = 'pending' AND embedding IS NULL AND embedding_profile_sha256 IS NULL)
        OR (embedding_status = 'legacy_unknown' AND embedding IS NOT NULL AND embedding_profile_sha256 IS NULL)
        OR (embedding_status = 'ready' AND embedding IS NOT NULL AND embedding_profile_sha256 IS NOT NULL
            AND embedding_profile_sha256 ~ '^[0-9a-f]{64}$')
        OR (embedding_status = 'trop_long' AND embedding IS NULL AND embedding_profile_sha256 IS NOT NULL
            AND embedding_profile_sha256 ~ '^[0-9a-f]{64}$')
    )
);

-- Les lignes historiques ne portent aucune identité de modèle fiable. Les vecteurs existants sont
-- explicitement isolés comme legacy_unknown; les fragments sans vecteur restent pending.
ALTER TABLE memoire.fragments ADD COLUMN IF NOT EXISTS embedding_profile_sha256 text;
ALTER TABLE memoire.fragments ADD COLUMN IF NOT EXISTS embedding_status text;
UPDATE memoire.fragments SET embedding_status =
    CASE WHEN embedding IS NULL THEN 'pending' ELSE 'legacy_unknown' END
WHERE embedding_status IS NULL;
ALTER TABLE memoire.fragments ALTER COLUMN embedding_status SET DEFAULT 'pending';
ALTER TABLE memoire.fragments ALTER COLUMN embedding_status SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'memoire.fragments'::regclass AND conname = 'fragments_embedding_profil_etat'
    ) THEN
        ALTER TABLE memoire.fragments ADD CONSTRAINT fragments_embedding_profil_etat CHECK (
            (embedding_status = 'pending' AND embedding IS NULL AND embedding_profile_sha256 IS NULL)
            OR (embedding_status = 'legacy_unknown' AND embedding IS NOT NULL AND embedding_profile_sha256 IS NULL)
            OR (embedding_status = 'ready' AND embedding IS NOT NULL AND embedding_profile_sha256 IS NOT NULL
                AND embedding_profile_sha256 ~ '^[0-9a-f]{64}$')
            OR (embedding_status = 'trop_long' AND embedding IS NULL AND embedding_profile_sha256 IS NOT NULL
                AND embedding_profile_sha256 ~ '^[0-9a-f]{64}$')
        );
    END IF;
END
$$;

-- La même source/empreinte peut être canonique dans plusieurs profils et portées. On garde
-- cependant une seule copie par profil+portée ; une différence de sensibilité, sujets ou
-- rétention dans ce domaine doit être refusée par l'upsert, jamais écrasée.
ALTER TABLE memoire.fragments DROP CONSTRAINT IF EXISTS fragments_unicite;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'memoire.fragments'::regclass AND conname = 'fragments_unicite'
    ) THEN
        ALTER TABLE memoire.fragments
            ADD CONSTRAINT fragments_unicite UNIQUE (document_id, empreinte, departement, portee);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS fragments_embedding_hnsw
    ON memoire.fragments USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS fragments_embedding_profil
    ON memoire.fragments (embedding_profile_sha256) WHERE embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS fragments_tsv_gin ON memoire.fragments USING gin (tsv);
CREATE INDEX IF NOT EXISTS fragments_sujets_gin ON memoire.fragments USING gin (sujets);
CREATE INDEX IF NOT EXISTS fragments_metadonnees_gin ON memoire.fragments USING gin (metadonnees jsonb_path_ops);
CREATE INDEX IF NOT EXISTS fragments_portee ON memoire.fragments (portee, departement);
CREATE INDEX IF NOT EXISTS fragments_expire ON memoire.fragments (expire_le) WHERE expire_le IS NOT NULL;

-- Journal des effacements (Loi 25) : qui, quand, pourquoi, quels filtres, combien. Jamais le texte effacé.
CREATE TABLE IF NOT EXISTS memoire.journal_effacements (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    effectue_le  timestamptz NOT NULL DEFAULT now(),
    demandeur    text NOT NULL CHECK (btrim(demandeur) <> ''),
    motif        text NOT NULL CHECK (btrim(motif) <> ''),
    filtres      jsonb NOT NULL,
    fragments    integer NOT NULL CHECK (fragments >= 0),
    documents    integer NOT NULL CHECK (documents >= 0)
);

-- Admissions M03 : source immuable conservée pour vérifier les citations et permettre le rejeu.
CREATE TABLE IF NOT EXISTS memoire.procedure_series (
    document_uuid uuid PRIMARY KEY,
    titre text NOT NULL CHECK (btrim(titre) <> '' AND length(titre) <= 300),
    sha256_courante text,
    cree_le timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memoire.procedure_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_uuid uuid NOT NULL REFERENCES memoire.procedure_series(document_uuid) ON DELETE CASCADE,
    version_no smallint NOT NULL CHECK (version_no BETWEEN 1 AND 8),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    cle_admission text NOT NULL UNIQUE CHECK (btrim(cle_admission) <> '' AND length(cle_admission) <= 128),
    document_id bigint NOT NULL UNIQUE REFERENCES memoire.documents(id) ON DELETE CASCADE,
    corps bytea NOT NULL CHECK (octet_length(corps) BETWEEN 1 AND 1048576),
    auteur text NOT NULL CHECK (btrim(auteur) <> '' AND length(auteur) <= 200),
    etat text NOT NULL CHECK (etat IN ('RECU', 'INDEXE')),
    extracteur text NOT NULL CHECK (extracteur = 'procedures-1'),
    admis_le timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT procedure_version_hash_unique UNIQUE(document_uuid, sha256),
    CONSTRAINT procedure_version_ordinal_unique UNIQUE(document_uuid, version_no),
    CONSTRAINT procedure_version_id_uuid_unique UNIQUE(id, document_uuid)
);
-- Tombstones opaques empêchent la reprise HTTP d'une clé après oubli. Aucun contenu, titre,
-- hash ni identifiant logique n'est conservé ici.
CREATE TABLE IF NOT EXISTS memoire.procedure_admission_oubliees (
    cle_admission text PRIMARY KEY CHECK (length(cle_admission) BETWEEN 16 AND 128)
);
-- Manifeste léger d'import. Le contenu demeure uniquement dans procedure_versions.corps.
CREATE TABLE IF NOT EXISTS memoire.procedure_lots (
    cle_lot_sha256 text PRIMARY KEY CHECK (cle_lot_sha256 ~ '^[0-9a-f]{64}$'),
    auteur text NOT NULL CHECK (btrim(auteur) <> '' AND length(auteur) <= 200),
    nombre_emplacements smallint NOT NULL CHECK (nombre_emplacements BETWEEN 1 AND 5),
    cree_le timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memoire.procedure_lot_emplacements (
    cle_lot_sha256 text NOT NULL REFERENCES memoire.procedure_lots(cle_lot_sha256) ON DELETE CASCADE,
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 5),
    titre text NOT NULL CHECK (btrim(titre) <> '' AND length(titre) <= 300),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    serie_cible_id uuid,
    version_id bigint UNIQUE REFERENCES memoire.procedure_versions(id) ON DELETE CASCADE,
    PRIMARY KEY (cle_lot_sha256, position)
);
CREATE INDEX IF NOT EXISTS procedure_lot_emplacements_version
    ON memoire.procedure_lot_emplacements(version_id) WHERE version_id IS NOT NULL;
-- Empreinte seule : l'oubli invalide le rejeu sans garder clé, titre, SHA documentaire ni UUID.
CREATE TABLE IF NOT EXISTS memoire.procedure_lots_oublies (
    cle_lot_sha256 text PRIMARY KEY CHECK (cle_lot_sha256 ~ '^[0-9a-f]{64}$')
);
ALTER TABLE memoire.procedure_series DROP CONSTRAINT IF EXISTS procedure_courante_fk;
ALTER TABLE memoire.procedure_series ADD CONSTRAINT procedure_courante_fk
    FOREIGN KEY (document_uuid, sha256_courante)
    REFERENCES memoire.procedure_versions(document_uuid, sha256) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE IF NOT EXISTS memoire.procedure_occurrences (
    version_id bigint NOT NULL REFERENCES memoire.procedure_versions(id) ON DELETE CASCADE,
    fragment_id bigint NOT NULL REFERENCES memoire.fragments(id) ON DELETE CASCADE,
    debut_octets integer NOT NULL CHECK (debut_octets >= 0),
    fin_octets integer NOT NULL CHECK (fin_octets > debut_octets),
    ligne_debut integer NOT NULL CHECK (ligne_debut > 0),
    ligne_fin integer NOT NULL CHECK (ligne_fin >= ligne_debut),
    section text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY(version_id, debut_octets, fin_octets)
);
CREATE INDEX IF NOT EXISTS procedure_occurrences_fragment ON memoire.procedure_occurrences(fragment_id, version_id);
CREATE TABLE IF NOT EXISTS memoire.procedure_activations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_uuid uuid NOT NULL REFERENCES memoire.procedure_series(document_uuid) ON DELETE CASCADE,
    version_precedente text CHECK (version_precedente IS NULL OR version_precedente ~ '^[0-9a-f]{64}$'),
    version_cible text NOT NULL CHECK (version_cible ~ '^[0-9a-f]{64}$'),
    auteur text NOT NULL CHECK (btrim(auteur) <> '' AND length(auteur) <= 200),
    active_le timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS procedure_activations_document
    ON memoire.procedure_activations(document_uuid, id);
