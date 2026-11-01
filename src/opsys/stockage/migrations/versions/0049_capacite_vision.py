"""Capacité « vision » du registre de fournisseurs (M3.3 et M3.5 : Grounding DINO, SAM 2 ou équivalents).

NUMÉROTATION : 0049 est le numéro réservé à la ligne M3/M4 (vague 3). Dans cette branche, `down_revision` est « 0044
», la tête réelle de la ligne de base ; les numéros réservés 0045 à 0048 (autres branches de la vague 3) n'y existent
pas encore. L'architecte réaligne `down_revision` sur « 0048 » à l'intégration (une seule ligne à changer, aucune
autre dépendance).

Aucune table : la contrainte CHECK `fournisseurs_configurations.capacite` s'élargit à « vision », remplacée en place
sur SQLite sans reconstruire la table (même technique que les migrations 0040 et 0044). La rétrogradation est refusée
dès qu'un fournisseur « vision » est configuré : la retirer détruirait sa configuration et son historique d'activation
(suppression définitive = frontière humaine).
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0046"
branch_labels = None
depends_on = None

_CONFIG = "fournisseurs_configurations"
_CHECK = "ck_fournisseurs_configurations_capacite_valide"
_ANCIENNES = "'llm','embeddings','reranker','ocr','stt','tts','avatar','image','video','recherche_web','courriel'"
_NOUVELLES = _ANCIENNES + ",'vision'"
_NAMING = {"ck": "%(constraint_name)s"}
_MOTIF = re.compile(r"capacite IN \([^)]*\)")


def _remplacer_sqlite(liste: str) -> None:
    """Remplace la CHECK de capacité en place (modification directe du schéma documentée par SQLite) : la
    reconstruction de
    table échouerait dès que des tables enfants contiennent des lignes."""
    cnx = op.get_bind()
    ddl = cnx.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"), {"n": _CONFIG}
    ).scalar_one()
    neuf, nombre = _MOTIF.subn(f"capacite IN ({liste})", ddl)
    if nombre != 1:
        raise RuntimeError("la contrainte de capacité attendue est introuvable dans fournisseurs_configurations")
    version = cnx.execute(sa.text("PRAGMA schema_version")).scalar_one()
    op.execute("PRAGMA writable_schema = ON")
    try:
        cnx.execute(
            sa.text("UPDATE sqlite_master SET sql = :sql WHERE type='table' AND name = :n"), {"sql": neuf, "n": _CONFIG}
        )
        op.execute(f"PRAGMA schema_version = {int(version) + 1}")
    finally:
        op.execute("PRAGMA writable_schema = OFF")
    if cnx.execute(sa.text("PRAGMA integrity_check")).scalar_one() != "ok":
        raise RuntimeError("le schéma modifié ne passe pas integrity_check")


def _remplacer(liste: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        _remplacer_sqlite(liste)
        return
    with op.batch_alter_table(_CONFIG, recreate="auto", naming_convention=_NAMING) as batch:
        batch.drop_constraint(op.f(_CHECK), type_="check")
        batch.create_check_constraint(op.f(_CHECK), f"capacite IN ({liste})")


def upgrade():
    if op.get_bind().dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend du registre de fournisseurs non pris en charge")
    _remplacer(_NOUVELLES)


def downgrade():
    cnx = op.get_bind()
    if cnx.execute(sa.text(f"SELECT 1 FROM {_CONFIG} WHERE capacite = 'vision' LIMIT 1")).first() is not None:
        raise RuntimeError("rétrogradation refusée : un fournisseur « vision » est configuré (aucune suppression)")
    _remplacer(_ANCIENNES)
