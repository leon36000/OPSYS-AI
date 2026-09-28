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
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('memoire.francais'::regconfig, texte)) STORED,
    departement  text NOT NULL CHECK (departement ~ '^[a-z0-9][a-z0-9-]{1,63}$'),
    portee       text NOT NULL CHECK (portee ~ '^[a-z][a-z0-9_-]{1,63}$'),
    sensibilite  text NOT NULL
                 CHECK (sensibilite IN ('publique', 'interne', 'confidentielle', 'personnelle')),
    sujets       text[] NOT NULL DEFAULT '{}',
    metadonnees  jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadonnees) = 'object'),
    cree_le      timestamptz NOT NULL DEFAULT now(),
    expire_le    timestamptz,
    CONSTRAINT fragments_unicite UNIQUE (document_id, empreinte),
    CONSTRAINT fragments_echeance CHECK (expire_le IS NULL OR expire_le > cree_le),
    -- Loi 25 : un renseignement personnel a toujours une échéance et un sujet, pour pouvoir l'effacer.
    CONSTRAINT fragments_personnel
        CHECK (sensibilite <> 'personnelle' OR (expire_le IS NOT NULL AND cardinality(sujets) > 0))
);

CREATE INDEX IF NOT EXISTS fragments_embedding_hnsw
    ON memoire.fragments USING hnsw (embedding vector_cosine_ops);
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
