#!/bin/sh
# deploy/postgres-init/01-init.sh
#
# Exécuté UNE SEULE FOIS par l'image postgres/pgvector officielle, au tout premier démarrage sur
# un volume de données vide (convention /docker-entrypoint-initdb.d/ de l'image postgres upstream,
# héritée telle quelle par pgvector/pgvector:pg17). Jamais rejoué sur un volume déjà initialisé —
# c'est le comportement normal et attendu de Postgres, pas une lacune d'idempotence de ce script.
#
# Rôle :
#   1. active l'extension pgvector dans la base OPSYS (POSTGRES_DB, déjà créée par l'image avec
#      POSTGRES_USER/POSTGRES_PASSWORD au moment où ce script tourne) ;
#   2. crée le rôle et la base séparée pour LiteLLM (son propre plan de contrôle : clés virtuelles,
#      historique de dépense — jamais mélangé aux données métier OPSYS).
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

: "${LITELLM_DB_PASSWORD:?LITELLM_DB_PASSWORD doit être défini (voir deploy/.env.example) pour initialiser la base LiteLLM}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE litellm WITH LOGIN PASSWORD '${LITELLM_DB_PASSWORD}';
    CREATE DATABASE litellm OWNER litellm;
EOSQL
