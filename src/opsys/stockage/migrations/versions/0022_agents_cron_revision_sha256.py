"""Ajoute les révisions natives SHA-256 sans réinterpréter les entiers historiques."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_TABLE = "agents_declencheurs_remises"
_CHECKS_OLD = (
    "ck_agents_declencheurs_remises_agents_cron_remises_revision_attendue",
    "ck_agents_declencheurs_remises_agents_cron_remises_ack",
)
_CHECKS_NEW = (
    *_CHECKS_OLD,
    "ck_agents_declencheurs_remises_agents_cron_remises_revision_attendue_type",
    "ck_agents_declencheurs_remises_agents_cron_remises_revision_attendue_sha256",
    "ck_agents_declencheurs_remises_agents_cron_remises_revision_native_type",
    "ck_agents_declencheurs_remises_agents_cron_remises_revision_native_sha256",
)
_BATCH_NAMING = {"ck": "%(constraint_name)s"}
_BASE64URL_SHA256_LAST = "('A','E','I','M','Q','U','Y','c','g','k','o','s','w','0','4','8')"


def _check_name(logical: str):
    return op.f(f"ck_{_TABLE}_{logical}")


def _definition_sha256(column: str) -> str:
    return (
        f"{column} IS NULL OR (length({column}) = 50 "
        f"AND substr({column}, 1, 7) = 'sha256:' "
        f"AND substr({column}, 50, 1) IN {_BASE64URL_SHA256_LAST})"
    )


def upgrade() -> None:
    with op.batch_alter_table(_TABLE, recreate="auto", naming_convention=_BATCH_NAMING) as batch:
        batch.drop_constraint(op.f(_CHECKS_OLD[0]), type_="check")
        batch.drop_constraint(op.f(_CHECKS_OLD[1]), type_="check")
        batch.add_column(sa.Column("native_expected_fingerprint", sa.String(50), nullable=True))
        batch.add_column(sa.Column("native_config_fingerprint", sa.String(50), nullable=True))
        batch.create_check_constraint(
            _check_name("agents_cron_remises_revision_attendue"),
            "native_expected_revision IS NULL OR native_expected_revision > 0",
        )
        batch.create_check_constraint(
            _check_name("agents_cron_remises_revision_attendue_type"),
            "native_expected_revision IS NULL OR native_expected_fingerprint IS NULL",
        )
        batch.create_check_constraint(
            _check_name("agents_cron_remises_revision_attendue_sha256"),
            _definition_sha256("native_expected_fingerprint"),
        )
        batch.create_check_constraint(
            _check_name("agents_cron_remises_revision_native_type"),
            "native_config_revision IS NULL OR native_config_fingerprint IS NULL",
        )
        batch.create_check_constraint(
            _check_name("agents_cron_remises_revision_native_sha256"),
            _definition_sha256("native_config_fingerprint"),
        )
        batch.create_check_constraint(
            _check_name("agents_cron_remises_ack"),
            "etat != 'remise' OR (native_job_id IS NOT NULL AND "
            "((native_config_revision IS NOT NULL AND native_config_fingerprint IS NULL) OR "
            "(native_config_revision IS NULL AND native_config_fingerprint IS NOT NULL)))",
        )


def downgrade() -> None:
    bind = op.get_bind()
    fingerprints = bind.execute(
        sa.text(
            f"SELECT 1 FROM {_TABLE} WHERE native_expected_fingerprint IS NOT NULL "
            "OR native_config_fingerprint IS NOT NULL LIMIT 1"
        )
    ).first()
    if fingerprints is not None:
        raise RuntimeError(
            "rétrogradation refusée : elle supprimerait des empreintes natives SHA-256 conservées"
        )
    with op.batch_alter_table(_TABLE, recreate="auto", naming_convention=_BATCH_NAMING) as batch:
        for name in _CHECKS_NEW:
            batch.drop_constraint(op.f(name), type_="check")
        batch.drop_column("native_config_fingerprint")
        batch.drop_column("native_expected_fingerprint")
        batch.create_check_constraint(
            _check_name("agents_cron_remises_revision_attendue"),
            "native_expected_revision IS NULL OR native_expected_revision > 0",
        )
        batch.create_check_constraint(
            _check_name("agents_cron_remises_ack"),
            "etat != 'remise' OR (native_job_id IS NOT NULL AND native_config_revision IS NOT NULL)",
        )
