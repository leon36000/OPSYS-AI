"""Aides des tests de parité SQLite / PostgreSQL : un VRAI PostgreSQL 17 éphémère (conteneur), migré une fois, puis une
base neuve par test (`CREATE DATABASE … TEMPLATE`). Sans Docker, le test est IGNORÉ avec la raison exacte (jamais un
faux vert).

Usage (dans un module de test) :

    from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)

`url_base` est paramétrée sur `sqlite` et `postgresql` : un test écrit une fois s'exécute sur les deux moteurs.
"""

from __future__ import annotations

import os
import secrets
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from opsys import stockage


@dataclass
class Serveur:
    url_admin: str  # postgresql+psycopg://…/postgres (superutilisateur du conteneur jetable)
    gabarit: str

    def _admin(self, instruction: str) -> None:
        moteur = create_engine(self.url_admin, isolation_level="AUTOCOMMIT")
        try:
            with moteur.connect() as cnx:
                cnx.execute(text(instruction))
        finally:
            moteur.dispose()

    def nouvelle_base(self, *, depuis_gabarit: bool = True) -> tuple[str, str]:
        nom = "t_" + secrets.token_hex(6)
        modele = f' TEMPLATE "{self.gabarit}"' if depuis_gabarit else ""
        self._admin(f'CREATE DATABASE "{nom}"{modele}')
        return nom, make_url(self.url_admin).set(database=nom).render_as_string(hide_password=False)

    def supprimer(self, nom: str) -> None:
        self._admin(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)')

    def url(self, nom: str) -> str:
        return make_url(self.url_admin).set(database=nom).render_as_string(hide_password=False)

    def conteneur(self) -> str:
        """Identifiant du conteneur jetable (retrouvé par son port publié), pour `docker exec pg_dump / pg_restore`."""
        port = make_url(self.url_admin).port
        sortie = subprocess.run(["docker", "ps", "-q", "--filter", f"publish={port}"], capture_output=True, text=True,
                                check=True, timeout=30).stdout.split()
        assert len(sortie) == 1, f"conteneur PostgreSQL introuvable pour le port {port}"
        return sortie[0]

    def docker_exec(self, *commande: str, entree: bytes | None = None, delai: int = 300) -> subprocess.CompletedProcess:
        """Exécute `commande` DANS le conteneur (binaires PostgreSQL de l'image : pg_dump, pg_restore, psql)."""
        return subprocess.run(["docker", "exec", *(["-i"] if entree is not None else []), self.conteneur(), *commande],
                              input=entree, capture_output=True, timeout=delai, check=False)


@pytest.fixture(scope="module")
def serveur_pg(tmp_path_factory) -> Iterator[Serveur]:
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)
    ancien_home = os.environ.get("OPSYS_HOME")
    os.environ["OPSYS_HOME"] = str(tmp_path_factory.mktemp("pg-home"))  # la migration lit l'ancien état dans ce dossier
    try:
        with postgres_ephemere(stockage_en_memoire=True) as url:
            url_admin = url.replace("postgresql://", "postgresql+psycopg://", 1)
            serveur = Serveur(url_admin, "gabarit_migre")
            serveur._admin(f'CREATE DATABASE "{serveur.gabarit}"')
            gabarit = make_url(url_admin).set(database=serveur.gabarit).render_as_string(hide_password=False)
            stockage.migrer(gabarit)
            stockage.liberer(gabarit)  # plus aucune connexion ouverte sur le gabarit : requis par TEMPLATE
            yield serveur
    finally:
        if ancien_home is None:
            os.environ.pop("OPSYS_HOME", None)
        else:
            os.environ["OPSYS_HOME"] = ancien_home


@pytest.fixture
def base_pg(serveur_pg) -> Iterator[str]:
    """URL d'une base PostgreSQL neuve, migrée (jusqu'à la tête), supprimée en fin de test."""
    nom, url = serveur_pg.nouvelle_base()
    try:
        yield url
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


@pytest.fixture(params=["sqlite", "postgresql"])
def url_base(request, tmp_path: Path) -> Iterator[str]:
    """URL d'une base migrée, sur chacun des deux moteurs."""
    if request.param == "sqlite":
        url = "sqlite:///" + str(tmp_path / "parite.db")
        stockage.migrer(url)
        try:
            yield url
        finally:
            stockage.liberer(url)
        return
    yield request.getfixturevalue("base_pg")
