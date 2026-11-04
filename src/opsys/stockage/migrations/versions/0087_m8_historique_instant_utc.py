"""Clé UTC normalisée de l'historique M8 (migration 0087) ; succède à 0086.

PROBLÈME : ``m8_ent_mesures_hist.construit_le`` conserve le texte RFC 3339 du producteur, décalage compris. Trier ce
texte avant ``LIMIT`` n'est pas trier des instants : ``2026-11-01T01:30:00-04:00`` (05:30 UTC) précède
``2026-11-01T01:15:00-05:00`` (06:15 UTC) dans l'ordre lexical, donc la ligne la plus récente peut être omise.

CORRECTION : colonne dérivée ``construit_le_utc``, clé UTC à longueur fixe
(``AAAA-MM-JJTHH:MM:SS.NNNNNNNNNZ``), et index ``(metric_id, construit_le_utc, construction_id)``. Le texte d'origine
n'est ni effacé ni réécrit : la migration ne remplit que la nouvelle colonne, après avoir VALIDÉ tous les instants
existants. Une ligne illisible, sans fuseau, à décalage non RFC 3339 ou à fraction de plus de 9 chiffres fait échouer
la migration avant tout DDL : fail-closed, jamais une clé inventée. Le lecteur refuse aussi une clé nulle.

La table est créée par 0046 à partir du schéma courant : sur une base neuve, la colonne et l'index existent déjà et
cette migration ne fait rien (aucune ligne). Sur une base existante, elle ajoute la colonne, remplit les lignes
présentes puis crée l'index. La descente retire la colonne dérivée ; ``construit_le`` reste intact.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None

_TABLE = "m8_ent_mesures_hist"
_COLONNE = "construit_le_utc"
_INDEX = "ix_m8_ent_mesures_hist_metrique_utc"
_FORMAT_INSTANT = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:[.,](\d+))?(?:[Zz]|[+-]\d{2}:\d{2})"
)
_PRECISION_FRACTION_MAX = 9


def _instant_utc(texte):
    """Même règle que ``m8_analytics.entonnoir.instant_utc`` (la migration ne dépend pas du département)."""
    if not isinstance(texte, str) or not texte:
        return None
    format_iso = _FORMAT_INSTANT.fullmatch(texte)
    if format_iso is None:
        return None
    valeur = texte[:-1] + "+00:00" if texte[-1:] in ("Z", "z") else texte
    try:
        lu = datetime.fromisoformat(valeur)
    except ValueError:
        return None
    if lu.tzinfo is None or lu.utcoffset() is None:
        return None
    decalage = lu.utcoffset()
    if decalage is None or decalage.microseconds or decalage.seconds % 60:
        return None
    fraction = format_iso.group(1) or ""
    if len(fraction) > _PRECISION_FRACTION_MAX:
        return None
    nanosecondes = int(fraction.ljust(_PRECISION_FRACTION_MAX, "0")) if fraction else 0
    try:
        utc = lu.astimezone(UTC)
    except OverflowError:
        # Refus contrôlé : la normalisation sortirait de la plage représentable par datetime.
        return None
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
        f".{nanosecondes:09d}Z"
    )


def _exemples(invalides):
    return ", ".join(
        f"{construction_id}/{metric_id}={construit_le!r}" for construction_id, metric_id, construit_le in invalides[:3]
    )


def _lignes(cnx, avec_colonne):
    colonnes = "construction_id, metric_id, construit_le" + (f", {_COLONNE}" if avec_colonne else "")
    return cnx.execute(sa.text(f"SELECT {colonnes} FROM {_TABLE}")).mappings().all()


def _valider_et_calculer(lignes, avec_colonne):
    """Rend ``(a_remplir, invalides, incoherentes)`` sans rien écrire."""
    a_remplir, invalides, incoherentes = [], [], []
    for ligne in lignes:
        attendu = _instant_utc(ligne["construit_le"])
        if attendu is None:
            invalides.append((ligne["construction_id"], ligne["metric_id"], ligne["construit_le"]))
            continue
        if not avec_colonne:
            a_remplir.append({"utc": attendu, "cid": ligne["construction_id"], "mid": ligne["metric_id"]})
            continue
        stocke = ligne[_COLONNE]
        if stocke is None:
            a_remplir.append({"utc": attendu, "cid": ligne["construction_id"], "mid": ligne["metric_id"]})
        elif stocke != attendu:
            incoherentes.append((ligne["construction_id"], ligne["metric_id"], stocke))
    return a_remplir, invalides, incoherentes


def _refuser(invalides, incoherentes):
    if invalides:
        raise RuntimeError(
            f"migration 0087 refusée : {len(invalides)} instant(s) d'historique illisible(s), sans fuseau ou d'une "
            f"précision supérieure à la nanoseconde ; aucun DDL, aucune réécriture. Exemples : {_exemples(invalides)}"
        )
    if incoherentes:
        raise RuntimeError(
            f"migration 0087 refusée : {len(incoherentes)} clé(s) UTC déjà stockée(s) ne correspondent pas au texte "
            f"d'origine ; aucune réécriture silencieuse. Exemples : {_exemples(incoherentes)}"
        )


def _remplir(cnx, a_remplir):
    if a_remplir:
        cnx.execute(
            sa.text(f"UPDATE {_TABLE} SET {_COLONNE} = :utc WHERE construction_id = :cid AND metric_id = :mid"),
            a_remplir,
        )


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend de l'historique M8 non pris en charge")
    inspecteur = sa.inspect(cnx)
    colonnes = {colonne["name"] for colonne in inspecteur.get_columns(_TABLE)}
    index = {entree["name"] for entree in inspecteur.get_indexes(_TABLE)}
    avec_colonne = _COLONNE in colonnes

    # Valider TOUTES les lignes avant le premier DDL : une base avec un instant illisible reste intacte.
    a_remplir, invalides, incoherentes = _valider_et_calculer(_lignes(cnx, avec_colonne), avec_colonne)
    _refuser(invalides, incoherentes)

    if not avec_colonne:
        op.add_column(_TABLE, sa.Column(_COLONNE, sa.Text(), nullable=True))
    _remplir(cnx, a_remplir)
    if _INDEX not in index:
        op.create_index(_INDEX, _TABLE, ["metric_id", _COLONNE, "construction_id"])


def downgrade():
    cnx = op.get_bind()
    inspecteur = sa.inspect(cnx)
    colonnes = {colonne["name"] for colonne in inspecteur.get_columns(_TABLE)}
    index = {entree["name"] for entree in inspecteur.get_indexes(_TABLE)}
    if _INDEX in index:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLONNE in colonnes:
        op.drop_column(_TABLE, _COLONNE)
