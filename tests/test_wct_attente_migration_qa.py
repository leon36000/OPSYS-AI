import pytest
from alembic import command
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from opsys import stockage
from opsys.stockage.schema import (
    EVENEMENTS_RECUS,
    EVENEMENTS_SORTANTS,
    OPSYS_INSTANCE,
    SERVICE_AUDIT,
    SERVICE_POLITIQUES,
    SERVICE_RECALCUL_INTENTIONS,
    SERVICE_RECALCUL_RESULTATS,
    WCT_ATTENTES,
    WCT_ATTENTES_AUDIT,
)


def test_upgrade_preserve_politique_audit_sans_grant(tmp_path):
    engine = stockage.moteur("sqlite:///" + str(tmp_path / "fake.db"))
    cfg = stockage._config()
    from alembic.script import ScriptDirectory

    assert ScriptDirectory.from_config(cfg).get_heads() == ["0035"]
    with engine.begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0033")
        instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        cnx.execute(
            insert(SERVICE_POLITIQUES).values(
                instance_id=instance,
                consommateur="m05-financecore",
                operation="m4.verifier_v3",
                revision=1,
                active=True,
                expire_le=2000000000,
            )
        )
        cnx.execute(
            insert(SERVICE_AUDIT).values(
                instance_id=instance,
                consommateur="m05-financecore",
                operation="m4.verifier_v3",
                revision=1,
                evenement_id="a" * 64,
                action="usage",
            )
        )
        policies = cnx.execute(select(SERVICE_POLITIQUES)).all()
        audits = cnx.execute(select(SERVICE_AUDIT)).all()
        command.upgrade(cfg, "0034")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0034"
        cnx.execute(
            insert(SERVICE_RECALCUL_INTENTIONS).values(
                intention_id="c" * 64,
                instance_id=instance,
                acteur="admin-fictif",
                wct_id="a" * 64,
                devis_id="devis-fictif",
            )
        )
        cnx.execute(
            insert(SERVICE_RECALCUL_RESULTATS).values(intention_id="c" * 64, statut="deja_tracee", version="v-fictive")
        )
        intentions = cnx.execute(select(SERVICE_RECALCUL_INTENTIONS)).all()
        resultats = cnx.execute(select(SERVICE_RECALCUL_RESULTATS)).all()
        command.upgrade(cfg, "0035")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0035"
        assert cnx.execute(select(SERVICE_POLITIQUES)).all() == policies
        assert cnx.execute(select(SERVICE_AUDIT)).all() == audits
        assert cnx.execute(select(SERVICE_RECALCUL_INTENTIONS)).all() == intentions
        assert cnx.execute(select(SERVICE_RECALCUL_RESULTATS)).all() == resultats
        assert not cnx.execute(select(WCT_ATTENTES)).all()
        assert not cnx.execute(select(WCT_ATTENTES_AUDIT)).all()
        cnx.execute(
            insert(EVENEMENTS_SORTANTS).values(
                evenement_id="a" * 64,
                type_evenement="m4.travaux_termines",
                producteur="m04-field-ops",
                charge="{}",
                cree_le="2026-01-01T00:00:00+00:00",
            )
        )
        # Une paire close ne peut pas acquérir une attente, même par insertion directe.
        cnx.execute(
            insert(EVENEMENTS_RECUS).values(
                evenement_id="a" * 64, consommateur="m05-financecore", statut="traite", tentatives=1
            )
        )
        values = dict(
            evenement_id="a" * 64,
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
        with pytest.raises(IntegrityError), cnx.begin_nested():
            cnx.execute(insert(WCT_ATTENTES).values(**values))
        cnx.execute(
            insert(EVENEMENTS_SORTANTS).values(
                evenement_id="b" * 64,
                type_evenement="m4.travaux_termines",
                producteur="m04-field-ops",
                charge="{}",
                cree_le="2026-01-01T00:00:00+00:00",
            )
        )
        cnx.execute(
            insert(EVENEMENTS_RECUS).values(
                evenement_id="b" * 64, consommateur="m05-financecore", statut="echec", tentatives=0
            )
        )
        cnx.execute(
            insert(WCT_ATTENTES).values(
                evenement_id="b" * 64,
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
        )
        cnx.execute(
            insert(WCT_ATTENTES_AUDIT).values(evenement_id="b" * 64, action="attente", epoch=1, revision_politique=1)
        )
        with pytest.raises(IntegrityError), cnx.begin_nested():
            cnx.execute(WCT_ATTENTES_AUDIT.update().values(action="prete"))
        for mutation in ({"expire_epoch": 604802}, {"lead_id": "autre"}, {"etat": "terminee"}):
            with pytest.raises(IntegrityError), cnx.begin_nested():
                cnx.execute(WCT_ATTENTES.update().values(**mutation))
        with pytest.raises(IntegrityError), cnx.begin_nested():
            cnx.execute(WCT_ATTENTES.delete())
        with pytest.raises(RuntimeError, match="attentes présentes"), cnx.begin_nested():
            command.downgrade(cfg, "0033")
        assert cnx.execute(select(WCT_ATTENTES.c.etat)).scalar_one() == "attente"
