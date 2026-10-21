"""Import, une seule fois, de l'ancien `etat.db` (sqlite3 brut, pré-ADR-0009) dans la base de
l'instance : voir `opsys.etat.importer_etat_si_necessaire`, appelée par `opsys.stockage.migrer`."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import select

from opsys import contexte, etat, jetons, stockage
from opsys.stockage.schema import APPROBATIONS, ARTEFACTS, JOURNAL, MODES_DEPARTEMENTS, USAGE_TOKENS

_ANCIEN_SCHEMA = """
CREATE TABLE approbations (
    id TEXT PRIMARY KEY, cree_le TEXT NOT NULL, departement TEXT NOT NULL, outil TEXT NOT NULL,
    arguments TEXT NOT NULL, motif_demande TEXT NOT NULL DEFAULT '', statut TEXT NOT NULL,
    decide_par TEXT, decide_le TEXT, motif_decision TEXT, resultat TEXT
);
CREATE TABLE usage_tokens (
    jour TEXT NOT NULL, departement TEXT NOT NULL, modele TEXT NOT NULL,
    appels INTEGER NOT NULL DEFAULT 0, tokens_entree INTEGER NOT NULL DEFAULT 0,
    tokens_sortie INTEGER NOT NULL DEFAULT 0, tokens_cache_lus INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (jour, departement, modele)
);
CREATE TABLE artefacts (
    id TEXT PRIMARY KEY, cree_le TEXT NOT NULL, source TEXT NOT NULL, taille INTEGER NOT NULL,
    contenu TEXT NOT NULL
);
CREATE TABLE journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT, quand TEXT NOT NULL, par TEXT NOT NULL,
    action TEXT NOT NULL, cible TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE modes_departements (
    departement TEXT PRIMARY KEY, mode TEXT NOT NULL, modifie_par TEXT NOT NULL, modifie_le TEXT NOT NULL
);
"""


def _ecrire_ancien_etat(chemin, *, avec_journal_double: bool = True) -> None:
    """Crée un `etat.db` au format pré-ADR-0009, avec une ligne dans chaque table."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    cnx = sqlite3.connect(chemin)
    try:
        cnx.executescript(_ANCIEN_SCHEMA)
        cnx.execute(
            "INSERT INTO approbations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("abc123456789", "2026-09-01T00:00:00+00:00", "m09-demo", "m9_payer", "{}", "motif",
             "executee", "nathan", "2026-09-01T00:05:00+00:00", "ok", '{"ok": true}'),
        )
        cnx.execute("INSERT INTO usage_tokens VALUES (?,?,?,?,?,?,?)",
                    ("2026-09-01", "m09-demo", "modele-x", 3, 100, 50, 0))
        cnx.execute("INSERT INTO artefacts VALUES (?,?,?,?,?)",
                    ("deadbeef00000001", "2026-09-01T00:00:00+00:00", "src", 10, "0123456789"))
        cnx.execute("INSERT INTO journal (quand, par, action, cible, details) VALUES (?,?,?,?,?)",
                    ("2026-09-01T00:00:00+00:00", "nathan", "departement.mode", "m09-demo", "{}"))
        if avec_journal_double:
            cnx.execute("INSERT INTO journal (quand, par, action, cible, details) VALUES (?,?,?,?,?)",
                        ("2026-09-01T00:01:00+00:00", "nathan", "approbation.approuver", "abc123456789", "{}"))
        cnx.execute("INSERT INTO modes_departements VALUES (?,?,?,?)",
                    ("m09-demo", "autonome", "nathan", "2026-09-01T00:00:00+00:00"))
        cnx.commit()
    finally:
        cnx.close()


def _comptes(cnx) -> dict[str, int]:
    from sqlalchemy import func

    tables = {"approbations": APPROBATIONS, "usage_tokens": USAGE_TOKENS, "artefacts": ARTEFACTS,
              "journal": JOURNAL, "modes_departements": MODES_DEPARTEMENTS}
    return {nom: cnx.execute(select(func.count()).select_from(table)).scalar_one() for nom, table in tables.items()}


def test_migrer_importe_l_ancien_etat_et_conserve_la_source(opsys_home):
    ancien = opsys_home / "etat.db"
    _ecrire_ancien_etat(ancien)
    try:
        stockage.migrer()
        with stockage.transaction() as cnx:
            assert _comptes(cnx) == {"approbations": 1, "usage_tokens": 1, "artefacts": 1, "journal": 2,
                                     "modes_departements": 1}
            [demande] = cnx.execute(select(APPROBATIONS)).mappings().all()
            assert (demande["id"], demande["statut"], demande["resultat"]) == ("abc123456789", "executee",
                                                                                '{"ok": true}')
            [artefact] = cnx.execute(select(ARTEFACTS)).mappings().all()
            assert artefact["departement"] is None and artefact["origine"] is None
            with contexte.appeler_en_tant_que("m09-demo"), pytest.raises(KeyError, match="artefact inconnu"):
                jetons.lire_artefact(cnx, "deadbeef00000001")
            journal = [dict(ligne) for ligne in cnx.execute(select(JOURNAL).order_by(JOURNAL.c.id)).mappings()]
        # L'ordre chronologique de l'ancien journal est préservé par les nouveaux identifiants.
        assert [j["action"] for j in journal] == ["departement.mode", "approbation.approuver"]
        assert ancien.is_file()  # la source reste disponible pour reprendre après un crash
        # Le contenu de l'ancien fichier reste lisible (T3 : la suppression est une frontière humaine).
        with sqlite3.connect(ancien) as verif:
            assert verif.execute("SELECT COUNT(*) FROM approbations").fetchone()[0] == 1
    finally:
        stockage.liberer()


def test_migrer_sans_ancien_fichier_ne_fait_rien(opsys_home):
    assert not (opsys_home / "etat.db").exists()
    try:
        stockage.migrer()
        with stockage.transaction() as cnx:
            assert _comptes(cnx) == {"approbations": 0, "usage_tokens": 0, "artefacts": 0, "journal": 0,
                                     "modes_departements": 0}
    finally:
        stockage.liberer()


def test_migrer_est_idempotent_le_fichier_n_est_importe_qu_une_fois(opsys_home):
    _ecrire_ancien_etat(opsys_home / "etat.db")
    try:
        stockage.migrer()
        with stockage.transaction() as cnx:
            premier_compte = _comptes(cnx)
        # Rappeler la migration (comme au redémarrage) : le fichier a déjà été renommé, rien à importer.
        stockage.migrer()
        stockage.migrer()
        with stockage.transaction() as cnx:
            assert _comptes(cnx) == premier_compte
    finally:
        stockage.liberer()


def test_importer_etat_si_necessaire_ne_rejoue_pas_si_les_tables_sont_deja_peuplees(opsys_home):
    """Même si un fichier `etat.db` réapparaît, un import n'écrase ni ne double rien si les tables
    cibles contiennent déjà des lignes (fail-closed : on ne devine jamais quoi fusionner)."""
    ancien = opsys_home / "etat.db"
    _ecrire_ancien_etat(ancien)
    try:
        stockage.migrer()
        with stockage.transaction() as cnx:
            premier_compte = _comptes(cnx)
        # Un nouveau fichier « etat.db » réapparaît (ex. sauvegarde restaurée par erreur) ; les
        # tables de la base de l'instance, elles, contiennent déjà les lignes importées plus haut.
        ancien.unlink()
        _ecrire_ancien_etat(ancien, avec_journal_double=False)
        with stockage.transaction() as cnx:
            importe = etat.importer_etat_si_necessaire(cnx)
            assert importe is False
            assert _comptes(cnx) == premier_compte
        assert ancien.is_file()  # rien n'a été renommé cette fois : rien n'a été importé
    finally:
        stockage.liberer()


@pytest.mark.parametrize("table_a_vider", ["approbations", "usage_tokens", "artefacts", "journal",
                                           "modes_departements"])
def test_import_bloque_des_qu_une_seule_table_cible_contient_deja_des_lignes(opsys_home, table_a_vider):
    """La garde « tables vides » porte sur les cinq tables ensemble, pas une par une."""
    ancien = opsys_home / "etat.db"
    stockage.migrer()  # crée le schéma ; l'ancien fichier n'existe pas encore, rien à importer ici
    try:
        table = {"approbations": APPROBATIONS, "usage_tokens": USAGE_TOKENS, "artefacts": ARTEFACTS,
                 "journal": JOURNAL, "modes_departements": MODES_DEPARTEMENTS}[table_a_vider]
        # L'ancien fichier n'apparaît qu'une fois la table cible déjà peuplée par l'usage normal.
        with stockage.transaction() as cnx:
            if table_a_vider == "usage_tokens":
                cnx.execute(table.insert().values(jour="2026-01-01", departement="x", modele="m"))
            elif table_a_vider == "modes_departements":
                cnx.execute(table.insert().values(departement="x", mode="ombre", modifie_par="t",
                                                  modifie_le="2026-01-01T00:00:00+00:00"))
            elif table_a_vider == "artefacts":
                cnx.execute(table.insert().values(id="x", cree_le="2026-01-01T00:00:00+00:00", source="t",
                                                  taille=1, contenu="a"))
            elif table_a_vider == "journal":
                cnx.execute(table.insert().values(quand="2026-01-01T00:00:00+00:00", par="t", action="a",
                                                  cible="c"))
            else:
                cnx.execute(table.insert().values(id="x", cree_le="2026-01-01T00:00:00+00:00", departement="d",
                                                  outil="o", arguments="{}", statut="en_attente"))
        _ecrire_ancien_etat(ancien)
        with stockage.transaction() as cnx:
            importe = etat.importer_etat_si_necessaire(cnx)
        assert importe is False
        assert ancien.is_file()
    finally:
        stockage.liberer()


def _processus_interrompu(home, phase: str) -> subprocess.CompletedProcess:
    script = textwrap.dedent(
        """
        import os
        from opsys import etat, stockage

        phase = os.environ["OPSYS_TEST_PHASE"]
        importer = etat.importer_etat_si_necessaire

        def interrompre(cnx):
            resultat = importer(cnx)
            if phase == "avant_commit":
                os._exit(73)
            return resultat

        etat.importer_etat_si_necessaire = interrompre
        stockage.migrer()
        if phase == "apres_commit":
            os._exit(74)
        """
    )
    environnement = {**os.environ, "OPSYS_HOME": str(home), "OPSYS_TEST_PHASE": phase}
    return subprocess.run([sys.executable, "-c", script], env=environnement, check=False, capture_output=True)


@pytest.mark.parametrize("phase,code", [("avant_commit", 73), ("apres_commit", 74)])
def test_import_historique_reprend_apres_crash_sans_perte_ni_doublon(opsys_home, phase, code):
    _ecrire_ancien_etat(opsys_home / "etat.db")

    processus = _processus_interrompu(opsys_home, phase)

    assert processus.returncode == code, processus.stderr.decode(errors="replace")
    try:
        stockage.migrer()
        with stockage.transaction() as cnx:
            assert _comptes(cnx) == {"approbations": 1, "usage_tokens": 1, "artefacts": 1, "journal": 2,
                                     "modes_departements": 1}
            assert cnx.execute(select(JOURNAL.c.action)).scalars().all() == ["departement.mode",
                                                                             "approbation.approuver"]
        assert (opsys_home / "etat.db").is_file()
    finally:
        stockage.liberer()


def test_import_reprend_apres_ancien_rename_avant_commit(opsys_home):
    archive = opsys_home / "etat.db.migre-20260930"
    _ecrire_ancien_etat(archive)

    processus = _processus_interrompu(opsys_home, "avant_commit")

    assert processus.returncode == 73, processus.stderr.decode(errors="replace")
    try:
        stockage.migrer()
        with stockage.transaction() as cnx:
            assert _comptes(cnx) == {"approbations": 1, "usage_tokens": 1, "artefacts": 1, "journal": 2,
                                     "modes_departements": 1}
        assert archive.is_file()
    finally:
        stockage.liberer()


def test_import_lit_aussi_les_lignes_historique_encore_dans_le_wal(opsys_home):
    ancien = opsys_home / "etat.db"
    _ecrire_ancien_etat(ancien)
    lecteur = sqlite3.connect(ancien)
    lecteur.execute("PRAGMA journal_mode=WAL")
    lecteur.execute("BEGIN")
    lecteur.execute("SELECT COUNT(*) FROM journal").fetchone()
    ecrivain = sqlite3.connect(ancien)
    ecrivain.execute("INSERT INTO journal (quand, par, action, cible, details) VALUES (?,?,?,?,?)",
                     ("2026-09-02T00:00:00+00:00", "nathan", "historique.wal", "fictif", "{}"))
    ecrivain.commit()
    ecrivain.close()
    assert Path(f"{ancien}-wal").stat().st_size > 0

    processus = subprocess.run(
        [sys.executable, "-c", "from opsys import stockage; stockage.migrer(); stockage.liberer()"],
        env={**os.environ, "OPSYS_HOME": str(opsys_home)}, check=False, capture_output=True,
    )

    lecteur.close()
    assert processus.returncode == 0, processus.stderr.decode(errors="replace")
    try:
        with stockage.transaction() as cnx:
            actions = cnx.execute(select(JOURNAL.c.action).order_by(JOURNAL.c.id)).scalars().all()
        assert actions == ["departement.mode", "approbation.approuver", "historique.wal"]
    finally:
        stockage.liberer()
