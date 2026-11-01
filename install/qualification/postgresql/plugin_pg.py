"""Plugiciel pytest du banc PostgreSQL : rejoue la suite ordinaire contre un vrai PostgreSQL, sans modifier les tests.

Activation : `pytest -p plugin_pg` avec `OPSYS_QUALIF_PG_ADMIN_URL` (URL SQLAlchemy `postgresql+psycopg://…/postgres`
d'un serveur éphémère, compte superutilisateur). Sans cette variable, le plugin ne fait RIEN (suite ordinaire
inchangée).

Mécanique (jamais de substitution silencieuse) :
- une base « gabarit » est créée et migrée UNE fois par processus pytest (toutes les migrations, 0001 -> tête) ;
- chaque test reçoit sa propre base `CREATE DATABASE … TEMPLATE gabarit` (isolée, ~100 ms) et `OPSYS_BASE_URL` pointe
  vers elle ; la valeur par défaut de `url_base()` (quand un test supprime la variable) pointe aussi vers elle ;
- la base est supprimée en fin de test (`DROP DATABASE … WITH (FORCE)`) ;
- un compteur compte les ordres SQL réellement émis contre un dialecte PostgreSQL pendant le test : un test qui n'a
  émis AUCUN ordre PostgreSQL (il fabrique sa propre base SQLite) est rapporté « n'a pas touché PG » et ne compte PAS
  comme une preuve PostgreSQL ;
- la réflexion de tables ignore l'index lexical dérivé de PostgreSQL (`connaissances_lexique`), comme les recensements
  des tests ignorent `connaissances_fts*` sous SQLite ;
- chaque test écrit une ligne JSON dans `OPSYS_QUALIF_PG_SORTIE` (nodeid, issue, ordres PG, durée).

Mode `OPSYS_QUALIF_PG_REDIRIGER=1` : les tests qui bâtissent EUX-MÊMES leur base (`stockage.migrer("sqlite:///…")`,
`stockage.moteur(url)`, `stockage.transaction(url)` avec une URL SQLite explicite : plus de 300 fichiers, surtout les
tests « durables » des départements) tournent aussi sur PostgreSQL. `stockage.moteur()` crée alors, pour CHAQUE URL
SQLite distincte du test, une base PostgreSQL VIDE (pas le gabarit : le test migre lui-même, comme sur un fichier
neuf) et la réutilise tant que le test redemande la même URL (la « réouverture » d'un fichier). Limites : un test qui
lit le fichier SQLite par `sqlite3` / `Path`, qui passe l'URL à un sous-processus ou qui compte sur un écouteur SQLite
échoue pour une raison propre à SQLite (classe « test lié à SQLite » du rapport), pas pour un défaut de PostgreSQL.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import time
from pathlib import Path

import pytest

ENV_ADMIN = "OPSYS_QUALIF_PG_ADMIN_URL"
ENV_SORTIE = "OPSYS_QUALIF_PG_SORTIE"
INDEX_DERIVES_PG = frozenset({"connaissances_lexique"})
ENV_REDIRIGER = "OPSYS_QUALIF_PG_REDIRIGER"
_ACTIF = bool(os.environ.get(ENV_ADMIN, "").strip())
_COMPTEUR = itertools.count(1)
_ETAT: dict = {"ordres_pg": 0, "gabarit": None}


def _admin_url() -> str:
    return os.environ[ENV_ADMIN].strip()


def _avec_base(url: str, base: str) -> str:
    from sqlalchemy.engine import make_url

    return make_url(url).set(database=base).render_as_string(hide_password=False)


def _executer_admin(sql: str) -> None:
    from sqlalchemy import create_engine, text

    moteur = create_engine(_admin_url(), isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with moteur.connect() as cnx:
            cnx.execute(text(sql))
    finally:
        moteur.dispose()


if _ACTIF:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "before_cursor_execute")
    def _compter(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if conn.dialect.name == "postgresql":
            _ETAT["ordres_pg"] += 1


@pytest.fixture(scope="session")
def _gabarit_pg():
    if not _ACTIF:
        yield None
        return
    from opsys import stockage

    base = f"opsys_gab_{os.getpid()}_{int(time.time())}"
    _executer_admin(f'CREATE DATABASE "{base}"')
    url = _avec_base(_admin_url(), base)
    ancien_home = os.environ.get("OPSYS_HOME")
    os.environ["OPSYS_HOME"] = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"gabarit-{os.getpid()}")
    try:
        stockage.migrer(url)
    finally:
        stockage.liberer(url)
        if ancien_home is None:
            os.environ.pop("OPSYS_HOME", None)
        else:
            os.environ["OPSYS_HOME"] = ancien_home
    _ETAT["gabarit"] = base
    yield base
    _executer_admin(f'DROP DATABASE IF EXISTS "{base}" WITH (FORCE)')


@pytest.fixture(autouse=True)
def _base_postgresql(_instance_isolee, monkeypatch, _gabarit_pg):
    """Donne à CHAQUE test une base PostgreSQL neuve, migrée, et y fait pointer `OPSYS_BASE_URL`."""
    if not _ACTIF:
        yield
        return
    from opsys import stockage
    from opsys.stockage import moteur as _  # noqa: F401  (importe le sous-module)

    mod = sys.modules["opsys.stockage.moteur"]
    nom = f"opsys_t_{os.getpid()}_{next(_COMPTEUR)}"
    _executer_admin(f'CREATE DATABASE "{nom}" TEMPLATE "{_gabarit_pg}"')
    url = _avec_base(_admin_url(), nom)
    monkeypatch.setenv(stockage.ENV_URL, url)

    def _url_base_pg() -> str:
        return os.environ.get(stockage.ENV_URL, "").strip() or url

    monkeypatch.setattr(mod, "url_base", _url_base_pg)
    monkeypatch.setattr(stockage, "url_base", _url_base_pg)
    # Les recensements de tables des tests (`inspect(cnx).get_table_names()` comparé à `META.tables` + les tables
    # virtuelles de SQLite) ignorent l'index lexical DÉRIVÉ propre à PostgreSQL, comme ils ignorent `connaissances_fts*`
    # sous SQLite. Seul ce nom est écarté, et seulement de la réflexion : la table existe, et les tests de la
    # qualification PostgreSQL la lisent directement.
    from sqlalchemy.engine.reflection import Inspector

    original = Inspector.get_table_names

    def _sans_index_derive(self, schema=None, **kw):
        return [t for t in original(self, schema, **kw) if t not in INDEX_DERIVES_PG]

    monkeypatch.setattr(Inspector, "get_table_names", _sans_index_derive)
    cree = [nom]
    if os.environ.get(ENV_REDIRIGER) == "1":
        par_url: dict[str, str] = {}
        original_create = mod.create_engine

        def _create_engine_redirige(cible, *args, **kw):
            texte = cible if isinstance(cible, str) else cible.render_as_string(hide_password=False)
            if str(texte).startswith("sqlite"):
                if texte not in par_url:
                    base = f"{nom}_r{len(par_url)}"
                    # VIDE : le test migre lui-même, comme sur un fichier neuf
                    _executer_admin(f'CREATE DATABASE "{base}"')
                    par_url[texte] = base
                    cree.append(base)
                cible = _avec_base(url, par_url[texte])
            return original_create(cible, *args, **kw)

        monkeypatch.setattr(mod, "create_engine", _create_engine_redirige)
    _ETAT["ordres_pg"] = 0
    yield
    stockage.liberer()
    for base in cree:
        _executer_admin(f'DROP DATABASE IF EXISTS "{base}" WITH (FORCE)')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    sortie = yield
    rapport = sortie.get_result()
    chemin = os.environ.get(ENV_SORTIE)
    if not _ACTIF or not chemin:
        return
    if rapport.when == "call" or (rapport.when in ("setup", "teardown") and rapport.outcome != "passed"):
        ligne = {
            "nodeid": item.nodeid, "phase": rapport.when, "issue": rapport.outcome,
            "ordres_pg": _ETAT["ordres_pg"], "duree_s": round(rapport.duration, 3),
        }
        if rapport.outcome == "skipped" and rapport.longrepr:
            ligne["raison"] = str(rapport.longrepr[-1])[:200]
        with open(Path(chemin), "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
