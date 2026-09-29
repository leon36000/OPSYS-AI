"""Environnement Alembic : migre toujours sur la connexion fournie par `opsys.stockage.migrer`."""

from __future__ import annotations

from alembic import context

from opsys.stockage.schema import META

connexion = context.config.attributes.get("connection")
if connexion is None:
    raise RuntimeError(
        "migrations OPSYS : lancer par `opsys-metier base migrer` (connexion fournie par opsys.stockage)")

context.configure(connection=connexion, target_metadata=META, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
