"""Copies M10 bornées dans la connexion canonique, sans autorité ni writer.

Les fenêtres concernent le préfixe avec sentinel, jamais un compte global prétendu.
CASE ferme tous les payloads si ce cadre est inadmissible. Cela borne le retour et
le décodage, pas le planner ou les allocations internes SQL. Aucune chaîne métier,
permission DEVICE, liaison APP/J, claim ou transaction de repli n'est livré ici.
"""

from __future__ import annotations

import datetime as dt
import json
from hashlib import sha256

from sqlalchemy import Connection, LargeBinary, and_, case, cast, func, literal, or_, select
from sqlalchemy.exc import SQLAlchemyError

from .stockage import codec
from .stockage.maillons import MaillonLu, SnapshotMaillons
from .stockage.moteur import connexion_courante
from .stockage.schema import REGISTRES

_BUDGETS = {
    "evenements": (10000, 65536, 16777216),
    "affaires": (10000, 65536, 16777216),
    "documents_affaire": (512, 16384, 8203264),
    "documents_affaire_traces": (512, 8192, 2120704),
}
_DETAIL = "la copie documentaire ne satisfait pas son contrat"


class RefusCopieM10(ValueError):
    """Erreur technique fermée, sans contenu ni détails SQL/codec."""

    def __init__(self, suffixe: str):
        self.code = "REJ-M10-COPIE-" + suffixe
        self.detail = _DETAIL
        super().__init__(self.code + " : " + self.detail)


def _refuser(suffixe):
    raise RefusCopieM10(suffixe) from None


def _requete(nom, lignes, par_ligne, cumul, dialecte):
    raw = (
        select(REGISTRES.c.rang, REGISTRES.c.cree_le, REGISTRES.c.maillon)
        .where(
            REGISTRES.c.departement == "m10-memoire",
            REGISTRES.c.registre == nom,
        )
        .order_by(REGISTRES.c.rang)
        .limit(lignes + 1)
        .subquery("prefixe_m10")
    )
    if dialecte == "sqlite":
        type_texte = func.typeof(raw.c.maillon)
        type_rang = func.typeof(raw.c.rang)
        octets = func.length(cast(raw.c.maillon, LargeBinary))
    else:
        type_texte, type_rang = literal("text"), literal("integer")
        octets = func.octet_length(raw.c.maillon)
    sizes = select(raw, type_texte.label("type_texte"), type_rang.label("type_rang"), octets.label("octets")).subquery(
        "tailles_m10"
    )
    invalide = or_(
        sizes.c.type_texte != "text",
        sizes.c.type_rang != "integer",
        sizes.c.maillon.is_(None),
        sizes.c.octets.is_(None),
        sizes.c.octets <= 0,
        sizes.c.octets > par_ligne,
        sizes.c.rang < 0,
    )
    window = select(
        sizes,
        func.count().over().label("nombre"),
        func.sum(func.coalesce(sizes.c.octets, 0)).over().label("cumul"),
        func.min(sizes.c.rang).over().label("minimum"),
        func.max(sizes.c.rang).over().label("maximum"),
        func.sum(case((invalide, 1), else_=0)).over().label("invalides"),
    ).subquery("statistiques_m10")
    admissible = and_(
        window.c.nombre <= lignes,
        window.c.cumul <= cumul,
        window.c.invalides == 0,
        window.c.minimum == 0,
        window.c.maximum == window.c.nombre - 1,
    )
    return select(
        window.c.rang,
        window.c.cree_le,
        window.c.type_texte,
        window.c.type_rang,
        window.c.octets,
        window.c.nombre,
        window.c.cumul,
        window.c.minimum,
        window.c.maximum,
        window.c.invalides,
        case((admissible, window.c.maillon), else_=None).label("payload"),
    ).order_by(window.c.rang)


def _encoding(cnx, dialecte):
    if dialecte == "sqlite":
        enc = cnx.exec_driver_sql("PRAGMA encoding").scalar_one()
    else:
        enc = cnx.execute(select(func.current_setting("server_encoding"))).scalar_one()
    if type(enc) is not str or enc.upper().replace("-", "") != "UTF8":
        _refuser("ENCODAGE-INVALIDE")


def copier_registre_m10(cnx: Connection, nom_registre: str) -> SnapshotMaillons:
    """Copie indépendante de rangs/dates et maillons dict, sans classification métier.

    Les allocations du driver/codec et plusieurs snapshots PG ne sont pas certifiés
    par ces plafonds. La future façade doit établir rôle, portée et affaire actuelle.
    """
    if not isinstance(cnx, Connection) or cnx is not connexion_courante() or cnx.closed or not cnx.in_transaction():
        _refuser("CONNEXION-INVALIDE")
    if type(nom_registre) is not str or nom_registre not in _BUDGETS:
        _refuser("REGISTRE-INVALIDE")
    dialecte = cnx.engine.dialect.name
    if dialecte not in ("sqlite", "postgresql"):
        _refuser("CONNEXION-INVALIDE")
    lignes, par_ligne, cumul = _BUDGETS[nom_registre]
    try:
        _encoding(cnx, dialecte)
        rows = list(cnx.execute(_requete(nom_registre, lignes, par_ligne, cumul, dialecte)).mappings())
        if len(rows) > lignes:
            _refuser("BORNE-DEPASSEE")
        if rows and (
            rows[0]["cumul"] > cumul or any(type(row["octets"]) is int and row["octets"] > par_ligne for row in rows)
        ):
            _refuser("BORNE-DEPASSEE")
        # Validate ALL metadata and returned byte lengths before the first decoder.
        total = 0
        for i, row in enumerate(rows):
            if (
                type(row["rang"]) is not int
                or row["rang"] != i
                or not isinstance(row["cree_le"], dt.datetime)
                or row["type_texte"] != "text"
                or row["type_rang"] != "integer"
                or type(row["octets"]) is not int
                or not 0 < row["octets"] <= par_ligne
                or row["nombre"] != len(rows)
                or row["minimum"] != 0
                or row["maximum"] != len(rows) - 1
                or row["invalides"] != 0
                or type(row["payload"]) is not str
            ):
                _refuser("SOURCE-INVALIDE")
            taille = len(row["payload"].encode("utf-8", errors="strict"))
            if taille != row["octets"]:
                _refuser("SOURCE-INVALIDE")
            total += taille
        if total > cumul:
            _refuser("BORNE-DEPASSEE")
        if any(row["cumul"] != total for row in rows):
            _refuser("SOURCE-INVALIDE")
        copies, empreinte = [], []
        for row in rows:
            maillon = codec.decoder(row["payload"])
            if type(maillon) is not dict:
                _refuser("SOURCE-INVALIDE")
            # Technical codec contract only: reject non-finite values/surrogates.
            # Never replace the stored payload or its snapshot digest by this encoding.
            codec.encoder(maillon).encode("utf-8", errors="strict")
            copies.append(MaillonLu(row["rang"], row["cree_le"], maillon))
            empreinte.append({"rang": row["rang"], "cree_le": row["cree_le"].isoformat(), "maillon": row["payload"]})
        texte = json.dumps(empreinte, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return SnapshotMaillons("m10-memoire", nom_registre, tuple(copies), sha256(texte.encode("utf-8")).hexdigest())
    except RefusCopieM10:
        raise
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError, SQLAlchemyError):
        _refuser("SOURCE-INVALIDE")
