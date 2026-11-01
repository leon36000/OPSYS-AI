#
# install/qualification/Dockerfile — image de QUALIFICATION hors réseau (substitut honnête de deploy/Dockerfile).
#
# Différences voulues avec deploy/Dockerfile, toutes déclarées dans docs/qualification/QUALIFICATION-CONTENEUR.md :
#  - base : `python:3.12-slim` telle qu'elle existe dans le cache local (pas le digest épinglé de la production) ;
#  - dépendances : copiées d'un environnement déjà installé (`--build-context deps=...`, voir preparer_contexte.py),
#    au lieu de `pip install --require-hashes -r requirements-runtime.lock.txt` (qui exige le réseau) ;
#  - pas d'`apt-get install libpq5` (réseau) : psycopg[binary] embarque sa libpq, l'image ne l'utilise pas.
# Tout le reste (utilisateur non root, variables, entrypoint, droits, EXPOSE) reproduit deploy/Dockerfile.
FROM python:3.12-slim

ARG OPSYS_RUNTIME_UID=1000
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

COPY . /opt/opsys

RUN python3 -m venv /opt/opsys-venv
COPY --from=deps site-packages/ /opt/opsys-venv/lib/python3.12/site-packages/
RUN /opt/opsys-venv/bin/python -m pip install --no-input --no-cache-dir --no-deps --no-build-isolation \
      --disable-pip-version-check -e /opt/opsys

RUN mkdir -p /opt/data /openclaw-config /shared/litellm-config /sauvegardes /cles /ref /copie && \
    chown -R opsys:opsys /opt/data /opt/opsys /openclaw-config /shared/litellm-config /sauvegardes /ref /copie && \
    chown opsys:opsys /cles && chmod 0700 /cles

COPY --chmod=0755 deploy/entrypoint.sh /opt/opsys/deploy/entrypoint.sh
COPY --chmod=0755 deploy/opsys-ancienne-commande.sh /usr/local/bin/opsys

USER opsys
WORKDIR /opt/opsys
EXPOSE 8765 8700
ENTRYPOINT ["/opt/opsys/deploy/entrypoint.sh"]
