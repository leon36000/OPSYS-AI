"""Une montée de schéma garde intact un accusé M6 créé avant la liaison à son auteur."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from alembic import command
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import inspect, text

from opsys import stockage


@contextmanager
def _base_fictive(tmp_path, backend):
    if backend == "sqlite":
        yield f"sqlite:///{tmp_path / 'm6-migration-fictive.db'}"
    else:
        with postgres_ephemere() as url:
            yield url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_migration_preserve_un_accuse_historique_sans_inventer_auteur(tmp_path, monkeypatch, backend):
    if backend == "postgresql" and raison_sans_docker() is not None:
        pytest.skip(f"PostgreSQL indisponible : {raison_sans_docker()}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home-fictif"))
    accuse_historique = '{"ok":true,"resultat":{"accepte":true,"registre":{"hash_tete":"' + "a" * 64 + '"}}}'
    with _base_fictive(tmp_path, backend) as url:
        try:
            config = stockage._config()
            with stockage.moteur(url).begin() as cnx:
                config.attributes["connection"] = cnx
                command.upgrade(config, "0088")
                assert "personne_origine" not in {c["name"] for c in inspect(cnx).get_columns("mutations_appliquees")}
                cnx.execute(text("""
                    INSERT INTO mutations_appliquees
                    (appareil, cle_idempotence, outil, empreinte_arguments, reponse,
                     horodatage_appareil, recu_le, statut)
                    VALUES (:appareil, :cle, :outil, :empreinte, :reponse, :horodatage, :recu, :statut)
                """), {
                    "appareil": "appareil-legacy-fictif", "cle": "cle-legacy-fictive",
                    "outil": "m6_declarer_materiaux_utilises", "empreinte": "b" * 64,
                    "reponse": accuse_historique, "horodatage": "2026-01-01T10:00:00+00:00",
                    "recu": "2026-01-01T10:00:01+00:00", "statut": "ok",
                })

            premiere_revision = stockage.migrer(url)
            assert stockage.migrer(url) == premiere_revision
            with stockage.moteur(url).connect() as cnx:
                ligne = cnx.execute(text("""
                    SELECT reponse, personne_origine FROM mutations_appliquees
                    WHERE appareil = :appareil AND cle_idempotence = :cle
                """), {"appareil": "appareil-legacy-fictif", "cle": "cle-legacy-fictive"}).mappings().one()
            assert ligne["reponse"] == accuse_historique
            assert ligne["personne_origine"] is None
        finally:
            stockage.liberer(url)
