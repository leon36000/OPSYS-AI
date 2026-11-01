"""Serveur PostgreSQL éphémère de la revue adverse rvi (tests seulement).

Conteneur nommé `opsys-pg-test-rvi-<aléa>`, image locale `pgvector/pgvector:pg17` (`--pull=never`), stockage en mémoire
plafonné, port publié sur 127.0.0.1 seulement, supprimé en fin de module. Sans Docker (ou sans l'image), le test est
IGNORÉ avec la raison exacte. Données fictives.
"""

from __future__ import annotations

import os
import secrets
import subprocess
from collections.abc import Iterator

import pytest
from memoire.doubles import IMAGE_PGVECTOR, _attendre, _port_publie, raison_sans_docker
from pg_parite import Serveur

from opsys import stockage


@pytest.fixture(scope="module")
def serveur_rvi(tmp_path_factory) -> Iterator[Serveur]:
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)
    nom = f"opsys-pg-test-rvi-{secrets.token_hex(6)}"
    mot_de_passe = secrets.token_hex(12)
    lancement = subprocess.run(
        ["docker", "run", "-d", "--name", nom, "--pull=never", "--memory=512m",
         "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=256m",
         "-e", f"POSTGRES_PASSWORD={mot_de_passe}", "-p", "127.0.0.1::5432", IMAGE_PGVECTOR],
        capture_output=True, text=True, timeout=300, check=False)
    if lancement.returncode != 0:
        pytest.skip(f"image {IMAGE_PGVECTOR} absente ou docker run refusé : {lancement.stderr.strip()[-200:]}")
    ancien_home = os.environ.get("OPSYS_HOME")
    os.environ["OPSYS_HOME"] = str(tmp_path_factory.mktemp("rvi-home"))
    try:
        port = _port_publie(nom)
        _attendre(f"postgresql://postgres:{mot_de_passe}@127.0.0.1:{port}/postgres", nom, 120.0, mot_de_passe)
        serveur = Serveur(f"postgresql+psycopg://postgres:{mot_de_passe}@127.0.0.1:{port}/postgres", "gabarit_migre")
        serveur._admin(f'CREATE DATABASE "{serveur.gabarit}"')
        gabarit = serveur.url(serveur.gabarit)
        stockage.migrer(gabarit)
        stockage.liberer(gabarit)
        yield serveur
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", nom], capture_output=True, timeout=120, check=False)
        if ancien_home is None:
            os.environ.pop("OPSYS_HOME", None)
        else:
            os.environ["OPSYS_HOME"] = ancien_home


@pytest.fixture
def base_rvi(serveur_rvi) -> Iterator[str]:
    """URL d'une base neuve, migrée jusqu'à la tête, supprimée en fin de test."""
    nom, url = serveur_rvi.nouvelle_base()
    try:
        yield url
    finally:
        stockage.liberer(url)
        serveur_rvi.supprimer(nom)
