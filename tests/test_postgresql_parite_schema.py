"""Parité de SCHÉMA et de moteur entre SQLite et PostgreSQL : déclencheurs d'immuabilité, fuseau de session.

Défauts réels trouvés par comparaison d'une base migrée sous SQLite et d'une base migrée sous PostgreSQL :

1. Les migrations 0026 (`fusion_ap_ocr_sources`) et 0033 (`service_attestations_m4`) ne posaient leurs déclencheurs
d'immuabilité que sur SQLite (`if dialect == "sqlite"`) : sur PostgreSQL ces deux tables, déclarées append-only,
acceptaient `UPDATE` et `DELETE`. Corrigé par la migration 0053. 2. `registres_maillons.cree_le` est un `timestamptz`
: PostgreSQL le rend dans le fuseau de la SESSION. Avec un fuseau de base ou de rôle autre que UTC, l'`isoformat()`
que des empreintes hachent changeait (`-05:00`). Le moteur épingle maintenant le fuseau de session à UTC.

3. `evenement_id` était `VARCHAR(128)` : SQLite ne fait pas respecter la longueur, PostgreSQL oui. L'identifiant que M2
   construit pour une opportunité répétée (`<lead>~opp~<wct>`, jusqu'à ~160 caractères) ne pouvait pas être publié sur
   PostgreSQL ; le consommateur partait en quarantaine après cinq essais. Corrigé par la migration 0053 (512).

Le comparateur de déclencheurs garde le futur : toute table qui reçoit un déclencheur d'immuabilité sur SQLite sans
équivalent PostgreSQL fait échouer ce test. Un vrai PostgreSQL 17 éphémère ; données fictives.
"""

from __future__ import annotations

import collections
import datetime as dt
import re
import tempfile
from pathlib import Path

import pytest
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from opsys import stockage

FICTIF = True


def _evenements_sqlite(url: str) -> dict[str, set[str]]:
    resultat: dict[str, set[str]] = collections.defaultdict(set)
    with stockage.moteur(url).connect() as cnx:
        declencheurs = cnx.exec_driver_sql("SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'")
        for _nom, table, sql in declencheurs:
            entete = sql.split("BEGIN")[0]
            resultat[table].update(e.upper() for e in re.findall(r"\b(INSERT|UPDATE|DELETE)\b", entete, re.I))
    return resultat


def _evenements_pg(url: str) -> dict[str, set[str]]:
    resultat: dict[str, set[str]] = collections.defaultdict(set)
    with stockage.moteur(url).connect() as cnx:
        for table, tgtype in cnx.execute(text(
                "SELECT c.relname, t.tgtype FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal")):
            for bit, nom in ((4, "INSERT"), (8, "DELETE"), (16, "UPDATE")):
                if tgtype & bit:
                    resultat[table].add(nom)
    return resultat


@pytest.fixture
def deux_bases(serveur_pg):  # noqa: F811
    with tempfile.TemporaryDirectory() as dossier:
        url_sqlite = "sqlite:///" + str(Path(dossier) / "parite.db")
        stockage.migrer(url_sqlite)
        nom, url_pg = serveur_pg.nouvelle_base()
        try:
            yield url_sqlite, url_pg
        finally:
            stockage.liberer(url_sqlite)
            stockage.liberer(url_pg)
            serveur_pg.supprimer(nom)


def test_toute_table_a_declencheurs_sur_sqlite_a_leur_equivalent_sur_postgresql(deux_bases):
    url_sqlite, url_pg = deux_bases
    sqlite, pg = _evenements_sqlite(url_sqlite), _evenements_pg(url_pg)
    assert len(sqlite) >= 25 and len(pg) >= 25  # les deux inventaires lisent bien quelque chose
    manque = {t: sorted(e - pg.get(t, set())) for t, e in sqlite.items() if e - pg.get(t, set())}
    assert manque == {}, f"immuabilité (ou règle) posée sur SQLite seulement : {manque}"


@pytest.mark.parametrize(("table", "message"), [
    ("fusion_ap_ocr_sources", "source OCR AP immuable"),
    ("service_attestations_m4", "attestation immutable"),
])
def test_les_deux_tables_corrigees_par_0053_refusent_update_et_delete_sur_postgresql(deux_bases, table, message):
    _, url_pg = deux_bases
    with stockage.moteur(url_pg).begin() as cnx:
        colonnes = [(r[0], r[1]) for r in cnx.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = :t "
            "ORDER BY ordinal_position"), {"t": table})]
        # Une ligne de test posée SANS les clés étrangères (rôle de réplication) : seul l'état du déclencheur est en
        # cause.
        cnx.exec_driver_sql("SET LOCAL session_replication_role = replica")
        valeurs = {c: (1 if t == "integer" else "x" * 8 if c != "source_type" else "OCR_CANDIDAT") for c, t in colonnes}
        valeurs.update({c: "a" * 64 for c, _ in colonnes if c.endswith("sha256")})
        valeurs.update({c: "p" * 8 for c, _ in colonnes if c == "ocr_profil_id"})
        cnx.execute(text(f"INSERT INTO {table} ({', '.join(valeurs)}) VALUES ({', '.join(':' + c for c in valeurs)})"),
                    valeurs)
        cnx.exec_driver_sql("SET LOCAL session_replication_role = origin")
    premiere = colonnes[0][0]
    for instruction in (f"UPDATE {table} SET {premiere} = {premiere}", f"DELETE FROM {table}"):
        with pytest.raises(IntegrityError, match=message), stockage.moteur(url_pg).begin() as cnx:
            cnx.execute(text(instruction))


def test_le_fuseau_de_session_est_epingle_a_utc_meme_si_la_base_a_un_autre_fuseau(serveur_pg):  # noqa: F811
    nom, url = serveur_pg.nouvelle_base()
    try:
        serveur_pg._admin(f'ALTER DATABASE "{nom}" SET timezone TO \'America/Toronto\'')
        with stockage.transaction(url) as cnx:
            assert cnx.execute(text("SHOW timezone")).scalar_one() == "UTC"
            stockage.maillons("m09-demo", "fuseau").append({"fictif": True})
            cree_le = cnx.execute(text("SELECT cree_le FROM registres_maillons WHERE registre = 'fuseau'")).scalar_one()
        assert cree_le.utcoffset() == dt.timedelta(0) and cree_le.isoformat().endswith("+00:00")
        # Sans l'épinglette, la même base rendrait -05:00 (ou -04:00 l'été) : on le prouve avec une connexion NON
        # épinglée.
        from sqlalchemy import create_engine

        brut = create_engine(url)
        with brut.connect() as cnx:
            assert cnx.execute(text("SHOW timezone")).scalar_one() == "America/Toronto"
            hors = cnx.execute(text("SELECT cree_le FROM registres_maillons WHERE registre = 'fuseau'")).scalar_one()
        brut.dispose()
        assert hors.utcoffset() != dt.timedelta(0) and hors == cree_le  # le même instant, une autre écriture
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


def test_un_identifiant_d_evenement_de_160_caracteres_est_accepte_sur_les_deux_moteurs(url_base):  # noqa: F811
    """La forme réelle d'une opportunité répétée : `m2-lead-assigne-<lead 64>~opp~<wct 64>` (149 caractères, davantage
    avec un rang), avec son reçu (clé étrangère) : la chaîne de colonnes `evenement_id` suit sans troncature."""
    from sqlalchemy import insert, select

    from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

    ident = "m2-lead-assigne-" + "a" * 64 + "~opp~" + "b" * 64
    assert len(ident) == 149
    long = ident + "-rang-2-" + "c" * 8
    with stockage.transaction(url_base) as cnx:
        cnx.execute(insert(EVENEMENTS_SORTANTS).values(
            evenement_id=long, type_evenement="m2.lead_assigne", producteur="m02-revenue-crm", charge="{}",
            cree_le="2026-11-01T12:00:00+00:00"))
        cnx.execute(insert(EVENEMENTS_RECUS).values(
            evenement_id=long, consommateur="m10-memoire", statut="traite", tentatives=1))
        assert cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id)).scalar_one() == long


def test_la_descente_de_0053_refuse_de_tronquer_un_identifiant_long(serveur_pg):  # noqa: F811
    from alembic import command
    from sqlalchemy import insert

    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    cfg = stockage._config()
    nom, url = serveur_pg.nouvelle_base()
    try:
        with stockage.transaction(url) as cnx:
            cnx.execute(insert(EVENEMENTS_SORTANTS).values(
                evenement_id="e" * 200, type_evenement="t.x", producteur="p", charge="{}", cree_le="2026-11-01"))
        with pytest.raises(RuntimeError, match="plus de 128 caractères"), stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.downgrade(cfg, "0052")
        with stockage.transaction(url) as cnx:
            assert cnx.execute(text("SELECT count(*) FROM evenements_sortants WHERE length(evenement_id) = 200")
                               ).scalar_one() == 1  # rien n'a été tronqué ni perdu
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)
