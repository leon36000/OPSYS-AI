"""Durable private publication attempts; no configuration payload or native dispatch."""
import sqlalchemy as sa
from alembic import op

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'configuration_publications',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('instance_id', sa.String(36), sa.ForeignKey('opsys_instance.instance_id'), nullable=False),
        *(sa.Column(n, sa.String(64), nullable=False) for n in (
            'cible_hash', 'base_hash', 'candidat_hash', 'source_hash', 'fichiers_hash', 'sql_hash',
            'liaison_hash', 'capacite_hash')),
        sa.Column('operation', sa.String(16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('bail_jusqua', sa.BigInteger(), nullable=False),
        sa.Column('etat', sa.String(24), nullable=False),
        sa.Column('observation_hash', sa.String(64)),
        sa.CheckConstraint("operation = 'publish'", name=op.f('ck_configuration_publications_publication_operation')),
        sa.CheckConstraint('version > 0 AND version <= 2147483647 AND bail_jusqua > 0',
                           name=op.f('ck_configuration_publications_publication_version_bail')),
        sa.CheckConstraint("etat IN ('preparee','dispatch_reserve','incertaine','candidat_observe','annulee')",
                           name=op.f('ck_configuration_publications_publication_etat')),
        sa.CheckConstraint('length(id) = 64 AND length(instance_id) = 36 AND length(cible_hash) = 64 AND '
                           'length(base_hash) = 64 AND length(candidat_hash) = 64 AND length(source_hash) = 64 AND '
                           'length(fichiers_hash) = 64 AND length(sql_hash) = 64 AND length(liaison_hash) = 64 AND '
                           'length(capacite_hash) = 64 AND (observation_hash IS NULL OR length(observation_hash) = 64)',
                           name=op.f('ck_configuration_publications_publication_empreintes')),
    )
    op.create_index('uq_configuration_publication_active', 'configuration_publications',
                    ['instance_id', 'cible_hash'], unique=True,
                    sqlite_where=sa.text("etat IN ('preparee','dispatch_reserve','incertaine')"),
                    postgresql_where=sa.text("etat IN ('preparee','dispatch_reserve','incertaine')"))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM configuration_publications LIMIT 1')).first() is not None:
        raise RuntimeError('rétrogradation refusée : historique de publication présent')
    op.drop_index('uq_configuration_publication_active', table_name='configuration_publications')
    op.drop_table('configuration_publications')
