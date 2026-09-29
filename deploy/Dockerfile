# syntax=docker/dockerfile:1.7
#
# deploy/Dockerfile — image OPSYS.
#
# Construit UNIQUEMENT l'image "opsys" : serveur MCP HTTP, console et synchronisation de la
# configuration d'OpenClaw. Le Core (OpenClaw) n'est jamais reconstruit ni exécuté ici :
# deploy/docker-compose.yml consomme son image officielle épinglée par digest.
#
# Base épinglée par digest — vérifiée sur le registre (lecture seule, pas d'exécution) le
# 2026-09-28 via `docker buildx imagetools inspect python:3.12-slim` :
#   Digest:  sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
#   Version: 3.12.14-slim-trixie (index multi-arch amd64/arm64/arm)
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

# libpq5 : psycopg[binary] embarque déjà libpq dans son wheel manylinux, mais on garde la lib
# système en secours pour les plateformes où le wheel binaire ne serait pas sélectionné.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Utilisateur dédié non-root pour le process applicatif (distinct de l'utilisateur dédié système
# que deploy/install.sh crée sur l'hôte pour Docker lui-même).
RUN useradd --create-home --home-dir /home/opsys --uid 10100 --user-group opsys

ENV OPSYS_HOME=/opt/data \
    OPSYS_MCP_PORT=8765 \
    OPSYS_CONSOLE_PORT=8700 \
    OPENCLAW_CONFIG_DIR=/openclaw-config \
    LITELLM_CONFIG_DIR=/shared/litellm-config \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/opsys-venv/bin:$PATH

# Dépôt OPSYS-AI copié dans /opt/opsys (source unique : départements, src/opsys, patchs, deploy/).
# Les exclusions (git, caches, secrets locaux) sont dans /.dockerignore. Pas de --chmod sur
# l'arborescence : 0644 appliqué aux dossiers les rendrait non traversables.
COPY . /opt/opsys

# Environnement virtuel dédié à opsys (processus séparé du Core OpenClaw, qui vit dans sa propre
# image officielle scellée) : mcp>=2.0.0,<3 déclaré dans pyproject.toml, compatibilité amont documentée
# dans core/UPSTREAM.md. Extra "console" obligatoire ici (fastapi/uvicorn) : sans elle,
# `opsys-console` refuse de démarrer (exit 2, "dépendance absente" — src/opsys/console/__init__.py).
# Extra "tournees" (PyVRP 0.14.0, MIT, PLAN T4.1-d) : le solveur de tournées de M4 (m4_proposer_cedule).
# Sans lui, M4 se replie sur son solveur exact jusqu'à 12 chantiers et refuse au-delà (« installer l'extra
# tournees ») : la cédule d'une vraie semaine n'a donc pas de sens dans une image qui ne l'a pas.
# Extra "soumission" (ReportLab 4.5.1, BSD-3-Clause, PLAN T2.3-f) : le PDF de la soumission brouillon de M3.
# Python pur, aucune bibliothèque système ; sans lui, l'outil refuse le format pdf avec un verdict.
RUN python3 -m venv /opt/opsys-venv && \
    /opt/opsys-venv/bin/python -m pip install --no-input --no-cache-dir --upgrade pip && \
    /opt/opsys-venv/bin/python -m pip install --no-input --no-cache-dir -e "/opt/opsys[postgres,console,tournees,soumission]"

# Le Core n'est jamais construit ici. Un premier patch amont (core/patches/) imposera une image
# dérivée distincte, deploy/Dockerfile.core : voir core/UPSTREAM.md.

RUN mkdir -p /opt/data /openclaw-config /shared/litellm-config && \
    chown -R opsys:opsys /opt/data /opt/opsys /openclaw-config /shared/litellm-config

COPY --chmod=0755 deploy/entrypoint.sh /opt/opsys/deploy/entrypoint.sh

USER opsys
WORKDIR /opt/opsys
EXPOSE 8765 8700
ENTRYPOINT ["/opt/opsys/deploy/entrypoint.sh"]
