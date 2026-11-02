"""Rejeu, sur un VRAI PostgreSQL 17, de fichiers de test existants écrits pour SQLite : « le même test, deux moteurs ».

Un test de console ou de service écrit pour SQLite bâtit son monde par `stockage.migrer()` / `stockage.transaction()`
sur la base par défaut (`OPSYS_BASE_URL`, sinon un fichier SQLite sous `OPSYS_HOME`). Ce module-ci charge le fichier de
test d'origine, en injecte les tests ET les fixtures dans le module appelant, et ajoute une fixture automatique qui fait
pointer `OPSYS_BASE_URL` vers une base PostgreSQL neuve, migrée (gabarit de `pg_parite`). Le test d'origine reste
exécuté tel quel sur SQLite par son propre fichier ; ici il l'est sur PostgreSQL, sans la moindre modification : aucune
duplication de scénario, aucune dérive possible entre les deux moteurs.

Usage, dans `tests/test_postgresql_rejeu_xxx.py` :

    from pg_rejeu import installer
    INJECTES = installer(globals(), "test_console_catalogue_m6.py", "test_console_prix_m6.py")

Sans Docker, chaque test est IGNORÉ avec la raison exacte (jamais un faux vert).
Limites : un test qui lit le fichier SQLite par `sqlite3`/`Path`, qui compte sur un écouteur SQLite ou qui attend le
refus d'un moteur autre que SQLite échoue pour une raison propre à SQLite : il n'a pas sa place dans un rejeu.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest
from _pytest.fixtures import FixtureFunctionDefinition
from pg_parite import base_pg, serveur_pg  # noqa: F401  (fixtures pytest)

from opsys import stockage

RACINE_TESTS = Path(__file__).resolve().parents[1]
INDEX_DERIVES_PG = frozenset({"connaissances_lexique"})


@pytest.fixture(autouse=True)
def _sur_postgresql(_instance_isolee, base_pg, monkeypatch):  # noqa: F811
    """Chaque test du rejeu s'exécute sur sa propre base PostgreSQL neuve, migrée jusqu'à la tête.

    `OPSYS_BASE_URL` pointe vers elle ; et, comme le fait le plugiciel du banc, la valeur par défaut de
    `stockage.url_base()` aussi : un test qui retire la variable (fixture automatique de certains fichiers) reste sur
    PostgreSQL au lieu de retomber sur le fichier SQLite de `OPSYS_HOME`."""
    monkeypatch.setenv(stockage.ENV_URL, base_pg)

    def url_base_pg() -> str:
        return os.environ.get(stockage.ENV_URL, "").strip() or base_pg

    mod = sys.modules["opsys.stockage.moteur"]
    monkeypatch.setattr(mod, "url_base", url_base_pg)
    monkeypatch.setattr(stockage, "url_base", url_base_pg)
    # Comme le plugiciel du banc : les recensements de tables des tests ignorent l'index lexical DÉRIVÉ propre à
    # PostgreSQL (`connaissances_lexique`, migration 0053), comme ils ignorent `connaissances_fts*` sous SQLite.
    from sqlalchemy.engine.reflection import Inspector

    original = Inspector.get_table_names

    def sans_index_derive(self, schema=None, **kw):
        return [t for t in original(self, schema, **kw) if t not in INDEX_DERIVES_PG]

    monkeypatch.setattr(Inspector, "get_table_names", sans_index_derive)
    yield base_pg
    stockage.liberer()


def _charger(fichier: str):
    chemin = Path(fichier)
    if not chemin.is_absolute():
        chemin = RACINE_TESTS / fichier
    nom = "rejeu_" + chemin.stem
    spec = importlib.util.spec_from_file_location(nom, chemin)
    assert spec is not None and spec.loader is not None, f"test introuvable : {chemin}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


_PARTAGEES = {"_sur_postgresql", "base_pg", "serveur_pg"}


def _meme_code(a, b) -> bool:
    """Deux fixtures chargées depuis le même source (ex. importée par deux fichiers) ont le même code."""
    try:
        return a._get_wrapped_function().__code__ == b._get_wrapped_function().__code__
    except AttributeError:
        return False


def module(fichier: str):
    """Le module de test déjà chargé par `installer` (pour réutiliser ses fonctions d'aide dans un test du rejeu)."""
    return sys.modules["rejeu_" + Path(fichier).stem]


@pytest.fixture(autouse=True)
def _sqlite_explicite_vers_postgresql(serveur_pg):
    """Variante du rejeu pour les tests qui bâtissent EUX-MÊMES une base SQLite fichier (`OPSYS_BASE_URL=sqlite:///…`).

    Même mécanisme que le mode `--redirige` du banc : toute URL SQLite passée au moteur de l'instance devient une base
    PostgreSQL VIDE (le test la migre lui-même, comme sur un fichier neuf), supprimée en fin de test. Le test d'origine
    n'est pas modifié ; un test qui ouvre le fichier SQLite directement (sqlite3, `Path`) n'a pas sa place ici."""
    mod = sys.modules["opsys.stockage.moteur"]
    original = mod.create_engine
    creees: dict[str, tuple[str, str]] = {}

    def redirige(cible, *args, **kw):
        texte = str(cible if isinstance(cible, str) else cible.render_as_string(hide_password=False))
        if texte.startswith("sqlite"):
            if texte not in creees:
                creees[texte] = serveur_pg.nouvelle_base(depuis_gabarit=False)
            cible = creees[texte][1]
        return original(cible, *args, **kw)

    mod.create_engine = redirige
    try:
        yield
    finally:
        mod.create_engine = original
        stockage.liberer()
        for nom, _ in creees.values():
            serveur_pg.supprimer(nom)


def installer(
    globales: dict, *fichiers: str, exclure: Iterable[str] = (), rediriger_sqlite: bool = False,
) -> list[str]:
    """Injecte tests et fixtures des `fichiers` dans `globales` ; rend les noms des tests injectés (pour les relire).

    `rediriger_sqlite` : les URL SQLite explicites que bâtit le test deviennent des bases PostgreSQL vides."""
    exclus = set(exclure)
    injectes: list[str] = []
    for nom, objet in (("_sur_postgresql", _sur_postgresql), ("base_pg", base_pg), ("serveur_pg", serveur_pg)):
        globales[nom] = objet
    if rediriger_sqlite:
        globales["_sqlite_explicite_vers_postgresql"] = _sqlite_explicite_vers_postgresql
    for fichier in fichiers:
        module = _charger(fichier)
        prefixe = Path(fichier).stem.removeprefix("test_")
        for nom, objet in list(vars(module).items()):
            if nom.startswith("_") and not isinstance(objet, FixtureFunctionDefinition):
                continue
            if isinstance(objet, FixtureFunctionDefinition):
                existant = globales.get(nom)
                if existant is not None and existant is not objet and nom not in _PARTAGEES and not _meme_code(
                        existant, objet):
                    # deux fichiers aux fixtures homonymes mais DIFFÉRENTES : un fichier de rejeu par fichier de test
                    raise AssertionError(f"fixture en double dans le rejeu : {nom} ({fichier})")
                globales[nom] = objet  # même nom que dans le fichier d'origine : les tests le retrouvent
            elif nom.startswith("test_") and callable(objet) and nom not in exclus:
                cible = nom if nom not in globales else f"{nom}__{prefixe}"  # deux fichiers, même nom de test
                globales[cible] = objet
                injectes.append(f"{prefixe}::{nom}")
    return injectes


def verrou_tenu(cnx, nom: str) -> bool:
    """Le verrou consultatif de transaction `nom` est-il TENU par la session de `cnx` ? (lu dans `pg_locks`)"""
    from sqlalchemy import text

    from opsys.stockage.concurrence import cle_verrou

    cle = cle_verrou(nom)
    haut, bas = (cle >> 32) & 0xFFFFFFFF, cle & 0xFFFFFFFF
    return bool(cnx.execute(text(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted AND objsubid = 1 "
        "AND pid = pg_backend_pid() AND classid::bigint = :haut AND objid::bigint = :bas)"),
        {"haut": haut, "bas": bas}).scalar_one())


def espionner_verrou(monkeypatch, objet, attribut: str, nom_verrou: str = "console-ecriture") -> dict:
    """Enveloppe `objet.attribut` : à chaque appel, note si le verrou `nom_verrou` est tenu par la session courante.

    Rend le compteur `{"appels": n, "sans_verrou": m}` : un port d'écriture humaine qui perd son verrou d'écriture de
    console est vu ici, même si la course qu'il évitait est trop étroite pour se produire dans un test."""
    original = getattr(objet, attribut)
    journal = {"appels": 0, "sans_verrou": 0}

    def espion(*args, **kwargs):
        cnx = stockage.connexion_courante()
        journal["appels"] += 1
        if cnx is None or not verrou_tenu(cnx, nom_verrou):
            journal["sans_verrou"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(objet, attribut, espion)
    return journal
