"""Installation PostgreSQL de la mémoire malgré les registres inactifs 0034/0035."""

import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from opsys import stockage
from opsys.stockage.schema import (
    EVENEMENTS_RECUS,
    EVENEMENTS_SORTANTS,
    OPSYS_INSTANCE,
    SERVICE_AUDIT,
    SERVICE_POLITIQUES,
    SERVICE_RECALCUL_ATTESTATIONS,
    SERVICE_RECALCUL_INTENTIONS,
    SERVICE_RECALCUL_RESULTATS,
    WCT_ATTENTES,
    WCT_ATTENTES_AUDIT,
)

# Même propriétaire de fixture que le reste des tests PostgreSQL M10.
_SPEC = importlib.util.spec_from_file_location(
    "opsys_m10_migrations_pg_fixture", Path(__file__).resolve().parents[3] / "tests/fixtures/memoire/doubles.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_PG_FIXTURE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PG_FIXTURE
_SPEC.loader.exec_module(_PG_FIXTURE)


@pytest.fixture(scope="module")
def pg_url():
    raison = _PG_FIXTURE.raison_sans_docker()
    if raison:
        if os.environ.get("CI") == "true":
            pytest.fail("PostgreSQL CI indisponible : " + raison)
        pytest.skip("PostgreSQL local indisponible : " + raison)
    with _PG_FIXTURE.postgres_ephemere(stockage_en_memoire=True) as url:
        yield url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def pg(pg_url):
    engine = sa.create_engine(pg_url)
    name = "qa_migrations_" + uuid.uuid4().hex
    with engine.begin() as c:
        c.exec_driver_sql(f"CREATE SCHEMA {name}")
    try:
        with engine.connect() as c:
            c.exec_driver_sql(f"SET search_path TO {name}")
            c.commit()
            cfg = stockage._config()
            cfg.attributes["connection"] = c
            yield c, cfg
            c.rollback()
    finally:
        with engine.begin() as c:
            c.exec_driver_sql(f"DROP SCHEMA {name} CASCADE")
        engine.dispose()


def denied(c, stmt):
    with pytest.raises(IntegrityError), c.begin_nested():
        c.execute(stmt)


def test_pg_migrations_historique_wct_et_retour_arriere(pg):
    c, cfg = pg
    command.upgrade(cfg, "0033")
    instance = c.execute(sa.select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    assert c.execute(sa.select(sa.func.count()).select_from(SERVICE_POLITIQUES)).scalar_one() == 0
    assert c.execute(sa.select(sa.func.count()).select_from(SERVICE_AUDIT)).scalar_one() == 0
    command.upgrade(cfg, "head")
    assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0035"
    for table in (
        SERVICE_POLITIQUES,
        SERVICE_AUDIT,
        SERVICE_RECALCUL_INTENTIONS,
        SERVICE_RECALCUL_ATTESTATIONS,
        SERVICE_RECALCUL_RESULTATS,
        WCT_ATTENTES,
        WCT_ATTENTES_AUDIT,
    ):
        assert c.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 0
    intention = {
        "intention_id": "c" * 64,
        "instance_id": instance,
        "acteur": "qa-fictif",
        "wct_id": "a" * 64,
        "devis_id": "devis-fictif",
    }
    c.execute(SERVICE_RECALCUL_INTENTIONS.insert().values(**intention))
    c.execute(SERVICE_RECALCUL_RESULTATS.insert().values(intention_id="c" * 64, statut="deja_tracee"))
    denied(c, SERVICE_RECALCUL_INTENTIONS.update().values(acteur="autre"))
    denied(c, SERVICE_RECALCUL_INTENTIONS.delete())
    denied(c, SERVICE_RECALCUL_RESULTATS.update().values(statut="publiee"))
    denied(c, SERVICE_RECALCUL_RESULTATS.delete())
    event = "b" * 64
    c.execute(
        EVENEMENTS_SORTANTS.insert().values(
            evenement_id=event,
            type_evenement="m4.travaux_termines",
            producteur="m04-field-ops",
            charge="{}",
            cree_le="2026-01-01T00:00:00+00:00",
        )
    )
    c.execute(
        EVENEMENTS_RECUS.insert().values(
            evenement_id=event, consommateur="m05-financecore", statut="echec", tentatives=0
        )
    )
    value = dict(
        evenement_id=event,
        consommateur="m05-financecore",
        instance_id=instance,
        devis_id="devis-fictif",
        lead_id="lead-fictif",
        recu_sha256="0" * 64,
        etat="attente",
        cree_epoch=1,
        expire_epoch=604801,
        revision_politique=1,
    )
    for change in (
        {"etat": "prete"},
        {"recu_sha256": "x" * 64},
        {"expire_epoch": 604802},
        {"source_m3": "0" * 64},
        {"instance_id": "autre"},
    ):
        denied(c, WCT_ATTENTES.insert().values(**(value | change)))
    c.execute(WCT_ATTENTES.insert().values(**value))
    c.execute(WCT_ATTENTES_AUDIT.insert().values(evenement_id=event, action="attente", epoch=1, revision_politique=1))
    for change in (
        {"etat": "terminee"},
        {"lead_id": "autre"},
        {"etat": "prete", "source_m3": "x" * 64, "source_m5": "b" * 64},
    ):
        denied(c, WCT_ATTENTES.update().values(**change))
    denied(c, WCT_ATTENTES.delete())
    denied(c, WCT_ATTENTES_AUDIT.update().values(action="prete"))
    denied(c, WCT_ATTENTES_AUDIT.delete())
    c.execute(WCT_ATTENTES.update().values(etat="prete", source_m3="a" * 64, source_m5="b" * 64))
    denied(c, WCT_ATTENTES.update().values(etat="terminee", source_m3="c" * 64))
    c.execute(WCT_ATTENTES.update().values(etat="terminee"))
    with pytest.raises(RuntimeError, match="attentes présentes"), c.begin_nested():
        command.downgrade(cfg, "0033")
    assert c.execute(sa.select(WCT_ATTENTES.c.etat)).scalar_one() == "terminee"
    c.rollback()


def test_pg_downgrade_vide_et_transaction_annulee(pg):
    c, cfg = pg
    command.upgrade(cfg, "0033")
    c.commit()
    transaction = c.begin()
    command.upgrade(cfg, "head")
    transaction.rollback()
    assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0033"
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0033")
    assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0033"
    command.upgrade(cfg, "head")
    assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0035"


def test_pg_attestation_immuable_downgrade_refuse_et_port_ferme(pg):
    from opsys import service_recalcul_m4
    from opsys.service_capability import RefusAutorite

    c, cfg = pg
    command.upgrade(cfg, "head")
    instance = c.execute(sa.select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    c.execute(
        SERVICE_RECALCUL_INTENTIONS.insert().values(
            intention_id="d" * 64, instance_id=instance, acteur="qa-fictif", wct_id="e" * 64, devis_id="devis-fictif"
        )
    )
    ids = []
    for operation in ("recalcul", "service"):
        ids.append(
            c.execute(
                SERVICE_AUDIT.insert()
                .values(
                    instance_id=instance,
                    consommateur="m05-financecore",
                    operation=operation,
                    revision=1,
                    evenement_id="e" * 64,
                    action="usage",
                )
                .returning(SERVICE_AUDIT.c.id)
            ).scalar_one()
        )
    c.execute(
        SERVICE_RECALCUL_ATTESTATIONS.insert().values(
            intention_id="d" * 64,
            audit_recalcul_id=ids[0],
            audit_service_id=ids[1],
            revision_recalcul=1,
            revision_service=1,
            trace_rang=0,
            trace_empreinte="a" * 64,
            source_m4="b" * 64,
            projection_m4="c" * 64,
            wct_hash="d" * 64,
            version_m4="v-fictive",
        )
    )
    denied(c, SERVICE_RECALCUL_ATTESTATIONS.update().values(trace_rang=1))
    denied(c, SERVICE_RECALCUL_ATTESTATIONS.delete())
    with pytest.raises(RefusAutorite, match="transaction ou contexte invalide"):
        service_recalcul_m4._executer_qa(c, None, wct_id="a" * 64, devis_id="fictif", intention_id="b" * 64)
    assert c.execute(sa.select(sa.func.count()).select_from(SERVICE_POLITIQUES)).scalar_one() == 0
    with pytest.raises(RuntimeError, match="historique recalcul présent"), c.begin_nested():
        command.downgrade(cfg, "0033")
    assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0035"


def test_pg_downgrade_ne_perd_pas_une_insertion_concurrente(pg):
    from sqlalchemy.exc import OperationalError

    c, cfg = pg
    command.upgrade(cfg, "head")
    schema = c.exec_driver_sql("SELECT current_schema()").scalar_one()
    instance = c.execute(sa.select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    c.commit()
    c.execute(
        SERVICE_RECALCUL_INTENTIONS.insert().values(
            intention_id="f" * 64, instance_id=instance, acteur="qa-fictif", wct_id="e" * 64, devis_id="fictif"
        )
    )
    with c.engine.connect() as other:
        other.exec_driver_sql(f"SET search_path TO {schema}")
        other.exec_driver_sql("SET lock_timeout TO '200ms'")
        other.commit()
        other_cfg = stockage._config()
        other_cfg.attributes["connection"] = other
        with pytest.raises(OperationalError):
            command.downgrade(other_cfg, "0033")
        other.rollback()
        c.commit()
        with pytest.raises(RuntimeError, match="historique recalcul présent"):
            command.downgrade(other_cfg, "0033")
        other.rollback()
        assert other.execute(sa.select(sa.func.count()).select_from(SERVICE_RECALCUL_INTENTIONS)).scalar_one() == 1


def test_pg_downgrade_ne_perd_pas_une_attente_concurrente(pg):
    from sqlalchemy.exc import OperationalError

    c, cfg = pg
    command.upgrade(cfg, "head")
    schema = c.exec_driver_sql("SELECT current_schema()").scalar_one()
    instance = c.execute(sa.select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    event = "7" * 64
    c.execute(
        EVENEMENTS_SORTANTS.insert().values(
            evenement_id=event,
            type_evenement="m4.travaux_termines",
            producteur="m04-field-ops",
            charge="{}",
            cree_le="2026-01-01T00:00:00+00:00",
        )
    )
    c.execute(
        EVENEMENTS_RECUS.insert().values(
            evenement_id=event, consommateur="m05-financecore", statut="echec", tentatives=0
        )
    )
    c.commit()
    c.execute(
        WCT_ATTENTES.insert().values(
            evenement_id=event,
            consommateur="m05-financecore",
            instance_id=instance,
            devis_id="fictif",
            lead_id="fictif",
            recu_sha256="0" * 64,
            etat="attente",
            cree_epoch=1,
            expire_epoch=604801,
            revision_politique=1,
        )
    )
    with c.engine.connect() as other:
        other.exec_driver_sql(f"SET search_path TO {schema}")
        other.exec_driver_sql("SET lock_timeout TO '200ms'")
        other.commit()
        other_cfg = stockage._config()
        other_cfg.attributes["connection"] = other
        with pytest.raises(OperationalError):
            command.downgrade(other_cfg, "0034")
        other.rollback()
        c.commit()
        with pytest.raises(RuntimeError, match="attentes présentes"):
            command.downgrade(other_cfg, "0034")
        other.rollback()
        assert other.execute(sa.select(sa.func.count()).select_from(WCT_ATTENTES)).scalar_one() == 1
