"""Revue adverse (reg) : les déclencheurs d'immuabilité SQLite résistent à `INSERT OR REPLACE`.

SQLite supprime la ligne en conflit d'un `REPLACE` SANS déclencher les `BEFORE DELETE` tant que
`PRAGMA recursive_triggers` est à OFF (son défaut). Un journal « immuable » se réécrivait donc par un simple
`INSERT OR REPLACE ... (id, ...)`. Exploitable seulement avec du SQL arbitraire (aucun code de `src/` n'utilise
REPLACE) : défense en profondeur, mais le contrat « append-only imposé par la base » doit tenir. Données fictives.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from opsys import stockage

FICTIF = True


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _journal_courriel(cnx) -> list[tuple]:
    return cnx.execute(text("SELECT id, code FROM courriel_journal ORDER BY id")).all()


def test_insert_or_replace_ne_reecrit_pas_un_journal_immuable(base):
    with stockage.transaction() as cnx:
        cnx.execute(text("INSERT INTO courriel_journal(quand, compte_id, evenement, code, acteur, details) "
                         "VALUES ('2026-11-01T10:00:00Z', 'c1', 'envoi.envoye', 'ok', 'systeme', '{}')"))
    with pytest.raises(IntegrityError), stockage.transaction() as cnx:
        cnx.execute(text(
            "INSERT OR REPLACE INTO courriel_journal(id, quand, compte_id, evenement, code, acteur, details) "
            "VALUES (1, '2026-11-01T10:00:00Z', 'c1', 'envoi.envoye', 'FALSIFIE', 'systeme', '{}')"))
    with stockage.transaction() as cnx:
        assert _journal_courriel(cnx) == [(1, "ok")]


def test_chaque_connexion_de_l_instance_active_les_declencheurs_recursifs(base):
    """C'est ce réglage (par connexion) qui fait déclencher les `BEFORE DELETE` d'un REPLACE, pour TOUTES les tables."""
    with stockage.transaction() as cnx:
        assert cnx.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1


def test_replace_sur_le_journal_du_planificateur(base):
    with stockage.transaction() as cnx:
        cnx.execute(text("INSERT INTO planificateur_journal(quand, executeur, evenement, acteur, mode, statut, code, "
                         "details) VALUES ('t', 'courriel.synchro', 'passage', 'systeme', 'actif', 'ok', NULL, '{}')"))
    with pytest.raises(IntegrityError), stockage.transaction() as cnx:
        cnx.execute(text("INSERT OR REPLACE INTO planificateur_journal(id, quand, executeur, evenement, acteur, "
                         "mode, statut, code, details) VALUES (1, 'FALSIFIE', 'courriel.synchro', 'passage', "
                         "'systeme', 'actif', 'ok', NULL, '{}')"))
    with stockage.transaction() as cnx:
        assert cnx.execute(text("SELECT quand FROM planificateur_journal")).scalar_one() == "t"


def test_cas_legitimes_restent_acceptes(base):
    """Cas négatif : ajouter, et les `ON CONFLICT DO NOTHING` de l'idempotence, fonctionnent toujours."""
    with stockage.transaction() as cnx:
        cnx.execute(text("INSERT INTO courriel_journal(quand, compte_id, evenement, code, acteur, details) "
                         "VALUES ('t', 'c1', 'e', 'ok', 'a', '{}')"))
        cnx.execute(text("INSERT INTO courriel_journal(quand, compte_id, evenement, code, acteur, details) "
                         "VALUES ('t', 'c1', 'e', 'ok2', 'a', '{}')"))
        cnx.execute(text("INSERT INTO evenements_sortants(evenement_id, type_evenement, producteur, charge, cree_le) "
                         "VALUES ('e1', 't', 'p', '{}', 't') ON CONFLICT(evenement_id) DO NOTHING"))
        cnx.execute(text("INSERT INTO evenements_sortants(evenement_id, type_evenement, producteur, charge, cree_le) "
                         "VALUES ('e1', 't2', 'p2', '{}', 't2') ON CONFLICT(evenement_id) DO NOTHING"))
        assert len(_journal_courriel(cnx)) == 2
        assert cnx.execute(text("SELECT type_evenement FROM evenements_sortants")).scalar_one() == "t"
