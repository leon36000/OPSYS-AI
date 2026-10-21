"""Plan de contrôle (ADR-0009) : approbations, jetons, artefacts tronqués, journal, modes.

Ces cinq tables vivaient dans `~/.opsys/etat.db` (sqlite3 brut) ; `opsys.stockage.migrer` importe
une seule fois le contenu d'un ancien fichier trouvé (`opsys.etat.importer_etat_si_necessaire`),
juste après cette migration.

Révision : 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approbations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("departement", sa.String(64), nullable=False),
        sa.Column("outil", sa.String(128), nullable=False),
        sa.Column("arguments", sa.Text(), nullable=False),
        sa.Column("motif_demande", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("statut", sa.String(16), nullable=False),
        sa.Column("decide_par", sa.Text()),
        sa.Column("decide_le", sa.Text()),
        sa.Column("motif_decision", sa.Text()),
        sa.Column("resultat", sa.Text()),
        sa.PrimaryKeyConstraint("id", name="pk_approbations"),
        sa.CheckConstraint(
            "statut IN ('en_attente','en_cours','refusee','executee','echec')",
            name="ck_approbations_statut_valide",
        ),
    )
    op.create_index("ix_approbations_statut", "approbations", ["statut", "cree_le"])

    op.create_table(
        "usage_tokens",
        sa.Column("jour", sa.Text(), nullable=False),
        sa.Column("departement", sa.String(64), nullable=False),
        sa.Column("modele", sa.String(128), nullable=False),
        sa.Column("appels", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_entree", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_sortie", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_cache_lus", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("jour", "departement", "modele", name="pk_usage_tokens"),
    )

    op.create_table(
        "artefacts",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("cree_le", sa.Text(), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("taille", sa.Integer(), nullable=False),
        sa.Column("contenu", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_artefacts"),
    )

    op.create_table(
        "journal",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("quand", sa.Text(), nullable=False),
        sa.Column("par", sa.Text(), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("cible", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.PrimaryKeyConstraint("id", name="pk_journal"),
    )

    op.create_table(
        "modes_departements",
        sa.Column("departement", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("modifie_par", sa.Text(), nullable=False),
        sa.Column("modifie_le", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("departement", name="pk_modes_departements"),
        sa.CheckConstraint("mode IN ('ombre','supervise','autonome')", name="ck_modes_departements_mode_valide"),
    )


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : le plan de contrôle est sensible ; restaurer une sauvegarde")
