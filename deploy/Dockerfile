# syntax=docker/dockerfile:1.7
#
# deploy/Dockerfile — OPSYS runtime image.
#
# Construit UNIQUEMENT l'image "opsys" : serveur MCP HTTP, console et synchronisation de la
# configuration d'OpenClaw. Le Core OPSYS est construit séparément depuis core/Dockerfile.
#
# Base épinglée par digest — vérifiée sur le registre (lecture seule, pas d'exécution) le
# 2026-09-28 via `docker buildx imagetools inspect python:3.12-slim` :
#   Digest:  sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
#   Version: 3.12.14-slim-trixie (index multi-arch amd64/arm64/arm)
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

# PDF natif facultatif : choisir explicitement l'overlay ingestion-pdf. Le paquet bwrap
# ne prouve pas que le noyau/seccomp du conteneur autorise ses namespaces ; readiness_pdf
# réutilise le worker isolé et refuse sans fallback (docs/ops/INGESTION-PDF-DOCKER.md).
ARG OPSYS_INGESTION_PDF=0
# libpq5 : psycopg[binary] embarque déjà libpq dans son wheel manylinux, mais on garde la lib
# système en secours pour les plateformes où le wheel binaire ne serait pas sélectionné.
RUN case "$OPSYS_INGESTION_PDF" in \
      0) set -- libpq5 ;; \
      1) set -- libpq5 bubblewrap ;; \
      *) echo "OPSYS_INGESTION_PDF doit valoir 0 ou 1." >&2; exit 2 ;; \
    esac && \
    apt-get update && \
    apt-get install -y --no-install-recommends "$@" && \
    rm -rf /var/lib/apt/lists/*

# Utilisateur dédié non-root pour le process applicatif (distinct de l'utilisateur dédié système
# que deploy/install.sh crée sur l'hôte pour Docker lui-même).
# Compose choisit 1000 pour le volume partagé avec Core/node ; l'image indépendante garde 10100.
ARG OPSYS_RUNTIME_UID=10100
RUN case "$OPSYS_RUNTIME_UID" in 1000|10100) ;; *) exit 2 ;; esac && \
    useradd --create-home --home-dir /home/opsys --uid "$OPSYS_RUNTIME_UID" --user-group opsys

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
# image officielle scellée) : mcp>=2.0.0,<3 déclaré dans pyproject.toml. Extra "console" obligatoire ici (fastapi/uvicorn) : sans elle,
# `opsys-console` refuse de démarrer (exit 2, "dépendance absente" — src/opsys/console/__init__.py).
# Extra "tournees" (PyVRP 0.14.0, MIT, PLAN T4.1-d) : le solveur de tournées de M4 (m4_proposer_cedule).
# Sans lui, M4 se replie sur son solveur exact jusqu'à 12 chantiers et refuse au-delà (« installer l'extra
# tournees ») : la cédule d'une vraie semaine n'a donc pas de sens dans une image qui ne l'a pas.
# Extra "soumission" (ReportLab 4.5.1, BSD-3-Clause, PLAN T2.3-f) : le PDF de la soumission brouillon de M3.
# Python pur, aucune bibliothèque système ; sans lui, l'outil refuse le format pdf avec un verdict.
RUN --mount=type=secret,id=proxy_ca,target=/run/secrets/proxy_ca,required=false \
    case "$OPSYS_INGESTION_PDF" in \
      0) opsys_lock=/opt/opsys/requirements-runtime.lock.txt ;; \
      1) opsys_lock=/opt/opsys/requirements-ingestion-pdf.lock.txt ;; \
      *) echo "OPSYS_INGESTION_PDF doit valoir 0 ou 1." >&2; exit 2 ;; \
    esac && \
    python3 -m venv /opt/opsys-venv && \
    if [ -f /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca /opt/opsys-venv/bin/python -m pip install \
        --no-input --no-cache-dir --require-hashes -r "$opsys_lock"; \
    else \
      /opt/opsys-venv/bin/python -m pip install --no-input --no-cache-dir --require-hashes \
        -r "$opsys_lock"; \
    fi && \
    /opt/opsys-venv/bin/python -m pip install --no-input --no-cache-dir --no-deps \
      --no-build-isolation -e /opt/opsys

# Le gateway OpenClaw OPSYS est construit depuis core/Dockerfile par
# deploy/docker-compose.yml. Cette image Python fournit aussi tar pour les sauvegardes natives.

RUN mkdir -p /opt/data /openclaw-config /shared/litellm-config && \
    chown -R opsys:opsys /opt/data /opt/opsys /openclaw-config /shared/litellm-config

COPY --chmod=0755 deploy/entrypoint.sh /opt/opsys/deploy/entrypoint.sh

# `opsys` n'est plus la CLI du moteur (PLAN T0.7 lot 2) : elle s'appelle `opsys-metier`, point d'entrée du paquet. Une
# ancienne invocation (`docker compose exec opsys opsys personnes creer`, un script) reçoit un message qui dit la
# nouvelle, au lieu de « executable file not found ». Le venv (PATH, plus haut) n'a plus de `opsys` : c'est ce fichier
# qui répond, et il sort en erreur (2) pour qu'un script ne continue pas sur une commande retirée.
COPY --chmod=0755 deploy/opsys-ancienne-commande.sh /usr/local/bin/opsys

USER opsys
WORKDIR /opt/opsys
EXPOSE 8765 8700
ENTRYPOINT ["/opt/opsys/deploy/entrypoint.sh"]
