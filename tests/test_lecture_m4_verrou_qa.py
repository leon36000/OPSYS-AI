"""Preuve locale SQLite WAL : la transaction du serveur exclut un écrivain concurrent."""

import sqlite3
import threading

from sqlalchemy import event

from opsys import service_capability as sc
from opsys.stockage.moteur import _debuter_sqlite


def test_lecture_canonique_retient_le_verrou_sans_modifier_la_base(session):
    with session() as cnx:
        assert event.contains(cnx.engine, "begin", _debuter_sqlite)
        assert cnx.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        fichier = sc._base(cnx)[0]
        changements_avant = cnx.connection.driver_connection.total_changes
        resultat = []

        def autre_ecrivain():
            c = sqlite3.connect(fichier, timeout=0.1)
            try:
                c.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                resultat.append(str(exc))
            else:
                c.rollback()
                resultat.append("NON_BLOQUE")
            finally:
                c.close()

        t = threading.Thread(target=autre_ecrivain)
        t.start()
        t.join(timeout=3)
        assert not t.is_alive() and resultat == ["database is locked"]
        assert cnx.connection.driver_connection.total_changes == changements_avant
    autre = sqlite3.connect(fichier, timeout=0.1)
    try:
        autre.execute("BEGIN IMMEDIATE")
        autre.rollback()
    finally:
        autre.close()
