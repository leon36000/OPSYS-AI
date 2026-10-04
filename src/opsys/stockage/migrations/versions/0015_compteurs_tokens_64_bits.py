"""Stocke budgets et compteurs de tokens sur 64 bits.

Révision : 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_COLONNES = (
    ("usage_tokens", "appels"),
    ("usage_tokens", "tokens_entree"),
    ("usage_tokens", "tokens_sortie"),
    ("usage_tokens", "tokens_cache_lus"),
    ("agents_configurables", "budget_jour"),
    ("agents_configurables", "budget_mois"),
    ("agents_politique_entreprise", "budget_jour"),
    ("agents_politique_entreprise", "budget_mois"),
    ("agents_reservations", "tokens_plafond"),
    ("agents_reservations", "tokens_reels"),
    ("agents_reservations_historique", "tokens_reels"),
)


def upgrade() -> None:
    # SQLite INTEGER a déjà le stockage signé 64 bits. Ne pas reconstruire ces tables : cela
    # préservera leurs lignes, contraintes et clés existantes.
    if op.get_bind().dialect.name == "sqlite":
        return
    for table, column in _COLONNES:
        op.alter_column(table, column, existing_type=sa.Integer(), type_=sa.BigInteger())


def downgrade() -> None:
    raise RuntimeError("rétrogradation refusée : elle pourrait tronquer les budgets et usages conservés")
