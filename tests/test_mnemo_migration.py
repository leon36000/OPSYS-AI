"""Migration 0052 du graphe de connaissances : montée, descente, refus avec données, immuabilité, contraintes.

SQLite ; PostgreSQL éphémère si Docker est disponible (le graphe y est aussi exercé : requêtes et déclencheurs).
Le modèle de soi et les leçons n'ont pas de table : ce sont des registres chaînés (`test_mnemo_soi`,
`test_mnemo_lecons`).
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from opsys import stockage
from opsys.mnemo import codes
from opsys.mnemo.codes import ErreurMnemo
from opsys.mnemo.graphe import DemandeArete, GrapheSql, NoeudRef
from opsys.stockage.schema import META, TABLES_VIRTUELLES_SQLITE

FICTIF = True
TABLES = ("graphe_noeuds", "graphe_aretes", "graphe_aretes_etats")
T = "2026-11-01T12:00:00+00:00"
CLIENT = hashlib.sha256(b"client").hexdigest()[:32]
PROPRIETE = hashlib.sha256(b"propriete").hexdigest()[:32]


def _chaine(cnx):
    """Deux nœuds, une arête, un état (valeurs fictives, insertion brute)."""
    for ident, type_noeud, cle in (("n1", "client", CLIENT), ("n2", "propriete", PROPRIETE)):
        cnx.execute(
            text("INSERT INTO graphe_noeuds VALUES (:i, :t, :c, :l, 'test:source', :q, 'p')"),
            {"i": ident, "t": type_noeud, "c": cle, "l": f"{type_noeud}·x", "q": T},
        )
    cnx.execute(
        text(
            "INSERT INTO graphe_aretes VALUES ('a1', 'possede', 'n1', 'n2', '2026-01-01', 1, 'agent', "
            "'test_fictif', 'test:source', 'moyenne', :q, 'p')"
        ),
        {"q": T},
    )
    cnx.execute(
        text(
            "INSERT INTO graphe_aretes_etats (arete_id, etat, quand, par, mode) "
            "VALUES ('a1', 'brouillon', :q, 'p', 'agent')"
        ),
        {"q": T},
    )


def test_0052_succede_a_0049_et_la_chaine_n_a_qu_une_tete():
    scripts = ScriptDirectory.from_config(stockage._config())
    assert len(scripts.get_heads()) == 1
    assert scripts.get_revision("0052").down_revision == "0049"


def test_montee_descente_et_remontee_sur_sqlite(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "m.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0049")
        avant = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master")}
        assert not set(TABLES) & avant
        command.upgrade(cfg, "0052")
        noms = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master")}
        assert set(TABLES) <= noms
        assert {f"{t}_no_{a}" for t in TABLES for a in ("update", "delete")} <= noms
        command.downgrade(cfg, "0049")
        apres = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master")}
        assert apres == avant  # tables et déclencheurs partis, rien d'autre touché
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0049"
        command.upgrade(cfg, "0052")  # remontable


def test_le_schema_declare_et_le_schema_migre_ont_les_memes_tables(tmp_path):
    url = "sqlite:///" + str(tmp_path / "s.db")
    stockage.migrer(url)
    attendues = {t for t in META.tables if t.startswith("graphe_")}
    assert attendues == set(TABLES)
    reelles = {
        r[0]
        for r in sqlite3.connect(str(tmp_path / "s.db")).execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'graphe_%'"
        )
    }
    assert reelles == attendues
    toutes = {
        r[0]
        for r in sqlite3.connect(str(tmp_path / "s.db")).execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert toutes - TABLES_VIRTUELLES_SQLITE <= set(META.tables) | {"alembic_version"}


@pytest.mark.parametrize("table", TABLES)
def test_descente_refusee_des_qu_une_table_contient_une_ligne(tmp_path, table):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / f"{table}.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0052")
        _chaine(cnx)
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0049")
    with stockage.moteur(url).begin() as cnx:
        assert cnx.execute(text("SELECT count(*) FROM graphe_aretes")).scalar_one() == 1  # rien n'a été détruit
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0052"


@pytest.mark.parametrize(
    "instruction",
    [
        "UPDATE graphe_noeuds SET libelle = 'autre'",
        "DELETE FROM graphe_noeuds",
        "UPDATE graphe_aretes SET confiance = 'haute'",
        "DELETE FROM graphe_aretes",
        "UPDATE graphe_aretes_etats SET etat = 'confirmee'",
        "DELETE FROM graphe_aretes_etats",
    ],
)
def test_les_tables_sont_append_only(tmp_path, instruction):
    url = "sqlite:///" + str(tmp_path / "ao.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        _chaine(cnx)
    with pytest.raises(DBAPIError, match="immuable"), stockage.moteur(url).begin() as cnx:
        cnx.execute(text(instruction))


ARETE = (
    "INSERT INTO graphe_aretes VALUES ('a2', 'possede', '{de}', '{vers}', '2026-01-01', 1, '{origine}', "
    "'tst', 's', 'm', 't', 'p')"
)
ETAT = (
    "INSERT INTO graphe_aretes_etats (arete_id, etat, quand, par, mode) "
    "VALUES ('{arete}', '{etat}', 't', 'p', '{mode}')"
)


@pytest.mark.parametrize(
    "instruction",
    [
        "INSERT INTO graphe_noeuds VALUES ('n3', 'employe', 'x', 'l', 's', 't', 'p')",  # type hors schéma
        ARETE.format(de="n1", vers="n1", origine="agent"),  # boucle
        ARETE.format(de="n1", vers="n2", origine="robot"),  # origine hors énuméré
        ARETE.format(de="n1", vers="inconnu", origine="agent"),  # extrémité inconnue
        ARETE.format(de="n1", vers="n2", origine="agent"),  # unicité (type, extrémités, début)
        ETAT.format(arete="a1", etat="archivee", mode="agent"),
        ETAT.format(arete="a1", etat="confirmee", mode="robot"),
        ETAT.format(arete="absente", etat="confirmee", mode="agent"),
    ],
)
def test_les_contraintes_refusent_les_formes_invalides(tmp_path, instruction):
    url = "sqlite:///" + str(tmp_path / "ck.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        cnx.exec_driver_sql("PRAGMA foreign_keys = ON")
        _chaine(cnx)
    with pytest.raises(IntegrityError), stockage.moteur(url).begin() as cnx:
        cnx.exec_driver_sql("PRAGMA foreign_keys = ON")
        cnx.execute(text(instruction))


def test_le_plafond_de_noeuds_est_un_refus_nomme_pas_une_lenteur(session, monkeypatch):
    from opsys.mnemo.graphe import sql

    monkeypatch.setattr(sql, "_PLAFOND_NOEUDS", 2)
    with session() as cnx:
        g = GrapheSql(cnx)
        g.poser_noeud("fournisseur", "f-1", None, source_ref="test:s", par="a", quand=T)
        g.poser_noeud("fournisseur", "f-2", None, source_ref="test:s", par="a", quand=T)
        with pytest.raises(ErreurMnemo, match=codes.PLAFOND):
            g.poser_noeud("fournisseur", "f-3", None, source_ref="test:s", par="a", quand=T)
        assert (
            g.poser_noeud("fournisseur", "f-2", None, source_ref="test:s", par="a", quand=T).cle == "f-2"
        )  # rejeu permis


def test_le_plafond_d_aretes_est_un_refus_nomme(session, monkeypatch):
    from opsys.mnemo.graphe import sql

    monkeypatch.setattr(sql, "_PLAFOND_ARETES", 1)
    with session() as cnx:
        g = GrapheSql(cnx)
        demande = DemandeArete(
            type="utilise",
            de=NoeudRef("intervention", "i-1"),
            vers=NoeudRef("materiau", "m-1"),
            valide_de="2026-01-01",
            origine="agent",
            source_type="test_fictif",
            source_ref="test:s",
        )
        g.proposer_arete(demande, par="a", quand=T)
        with pytest.raises(ErreurMnemo, match=codes.PLAFOND):
            g.proposer_arete(
                DemandeArete(**{**demande.__dict__, "vers": NoeudRef("materiau", "m-2")}), par="a", quand=T
            )


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_le_graphe_sur_postgresql(monkeypatch):
    from memoire.doubles import postgres_ephemere

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            tete = ScriptDirectory.from_config(stockage._config()).get_current_head()
            assert stockage.moteur(url).dialect.name == "postgresql" and stockage.revision_courante(url) == tete
            with stockage.transaction() as cnx:
                g = GrapheSql(cnx)
                for i in (1, 2):
                    g.proposer_arete(
                        DemandeArete(
                            type="utilise",
                            de=NoeudRef("intervention", f"i-{i}"),
                            vers=NoeudRef("materiau", "m-a"),
                            valide_de="2026-01-01",
                            origine="bus",
                            source_type="bus:test",
                            source_ref="test:s",
                        ),
                        par="a",
                        quand=T,
                    )
                a = g.proposer_arete(
                    DemandeArete(
                        type="possede",
                        de=NoeudRef("client", CLIENT),
                        vers=NoeudRef("propriete", PROPRIETE),
                        valide_de="2026-01-01",
                        origine="bus",
                        source_type="bus:test",
                        source_ref="test:s",
                    ),
                    par="a",
                    quand=T,
                ).arete
                for ident in [x.arete_id for x in g.en_attente(10) if not x.sensible]:
                    g.confirmer_arete(ident, par="systeme", mode="systeme", role=None, raison=None, quand=T)
                with pytest.raises(ErreurMnemo, match=codes.HUMAIN_REQUIS):
                    g.confirmer_arete(a.arete_id, par="systeme", mode="systeme", role=None, raison=None, quand=T)
                g.confirmer_arete(
                    a.arete_id, par="direction.fictive", mode="humain", role="admin", raison="vérifié", quand=T
                )
                v = g.voisinage(NoeudRef("materiau", "m-a"), 2, a_la_date="2026-06-01")
                assert {n.cle for n, _ in v.noeuds} == {"m-a", "i-1", "i-2"}
                assert (
                    g.chemin(
                        NoeudRef("intervention", "i-1"), NoeudRef("intervention", "i-2"), a_la_date="2026-06-01"
                    ).longueur
                    == 2
                )
                assert g.etat()["aretes_par_etat"]["confirmee"] == 3
            for instruction in ("UPDATE graphe_aretes SET confiance = 'haute'", "DELETE FROM graphe_aretes_etats"):
                with pytest.raises(DBAPIError, match="immuable"), stockage.transaction() as cnx:
                    cnx.execute(text(instruction))
        finally:
            stockage.liberer()
