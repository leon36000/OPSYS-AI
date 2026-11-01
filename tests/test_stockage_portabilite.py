"""Expressions SQL portables (`opsys.stockage.portabilite`) : le MÊME code SQLAlchemy rend les MÊMES valeurs sur SQLite
et sur un vrai PostgreSQL 17 (défauts latents L2 à L5 du rapport de qualification : `CAST(texte AS BLOB)`, `typeof()`,
booléen converti en `bytea`, qui étaient des erreurs SQL sur PostgreSQL). Aucune donnée réelle."""

from __future__ import annotations

import re

import pytest
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    func,
    insert,
    literal,
    select,
)
from sqlalchemy.dialects import postgresql, sqlite

from opsys import stockage
from opsys.stockage.portabilite import (
    DIALECTES_QUALIFIES,
    est_entier,
    est_texte,
    moteur_qualifie,
    nb_octets,
    type_stockage,
)

META = MetaData()
T = Table(
    "portabilite_essai", META,
    Column("id", Integer, primary_key=True),
    Column("texte", Text), Column("court", String(40)), Column("actif", Boolean), Column("n", Integer),
    Column("brut", LargeBinary),
)

FICTIF = True


def _installer(cnx):
    if cnx.dialect.name == "postgresql":
        cnx.exec_driver_sql("CREATE TEMP TABLE portabilite_essai (id integer primary key, texte text, "
                            "court varchar(40), actif boolean, n integer, brut bytea)")
    else:
        cnx.exec_driver_sql("CREATE TEMP TABLE portabilite_essai (id integer primary key, texte text, "
                            "court varchar(40), actif boolean, n integer, brut blob)")
    cnx.execute(insert(T), [
        {"id": 1, "texte": "bonjour", "court": "abc", "actif": True, "n": 12345, "brut": b"\x00\x01\x02"},
        {"id": 2, "texte": "É été — çà", "court": "é", "actif": False, "n": -7, "brut": b""},
        {"id": 3, "texte": None, "court": None, "actif": None, "n": None, "brut": None},
    ])


def test_le_rendu_sqlite_est_celui_d_avant_et_le_rendu_postgresql_n_a_ni_blob_ni_typeof():
    requete = select(nb_octets(T.c.texte), est_texte(T.c.texte), est_entier(T.c.n), type_stockage(T.c.n))
    sql_sqlite = str(requete.compile(dialect=sqlite.dialect()))
    sql_pg = str(requete.compile(dialect=postgresql.dialect()))
    assert "length(CAST(portabilite_essai.texte AS BLOB))" in sql_sqlite
    assert "typeof(portabilite_essai.texte) = 'text'" in sql_sqlite
    assert "BLOB" not in sql_pg and re.search(r"(?<!pg_)typeof\(", sql_pg) is None
    assert "octet_length(portabilite_essai.texte)" in sql_pg and "pg_typeof" in sql_pg


def test_les_octets_comptent_l_utf8_pas_les_caracteres_sur_les_deux_moteurs(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        _installer(cnx)
        lignes = cnx.execute(select(
            T.c.id, nb_octets(T.c.texte), nb_octets(T.c.court), nb_octets(T.c.actif), nb_octets(T.c.n),
        ).order_by(T.c.id)).all()
        assert lignes[0] == (1, 7, 3, 1, 5)
        # « É été — çà » : É(2) espace(1) é(2) t(1) é(2) espace(1) —(3) espace(1) ç(2) à(2) = 17 octets, 10 caractères
        assert lignes[1] == (2, 17, 2, 1, 2)
        assert lignes[2] == (3, None, None, None, None)  # NULL reste NULL


def test_les_octets_d_un_booleen_valent_un_sur_les_deux_moteurs(url_base):  # noqa: F811
    """L5 : `cast(booléen, LargeBinary)` était `cannot cast type boolean to bytea` ; SQLite stocke 0/1 (un octet)."""
    with stockage.transaction(url_base) as cnx:
        _installer(cnx)
        assert cnx.execute(select(func.sum(nb_octets(T.c.actif)))).scalar_one() == 2


def test_somme_et_maximum_des_octets_comme_les_captures_de_console(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        _installer(cnx)
        n, total, maxi = cnx.execute(select(func.count(), func.sum(nb_octets(T.c.texte)),
                                            func.max(nb_octets(T.c.texte))).select_from(T)).one()
        assert (n, total, maxi) == (3, 24, 17)


def test_les_octets_d_un_binaire(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        _installer(cnx)
        assert [r[0] for r in cnx.execute(select(nb_octets(T.c.brut)).order_by(T.c.id)).all()] == [3, 0, None]


def test_le_type_de_stockage_est_reconnu_sur_les_deux_moteurs(url_base):  # noqa: F811
    """L3 : `typeof()` n'existe pas sur PostgreSQL ; `pg_typeof` donne le vrai type, ramené à `text` / `integer`."""
    with stockage.transaction(url_base) as cnx:
        _installer(cnx)
        ligne = cnx.execute(select(est_texte(T.c.texte), est_texte(T.c.n), est_entier(T.c.n), est_entier(T.c.texte),
                                   type_stockage(T.c.texte), type_stockage(T.c.court), type_stockage(T.c.n),
                                   ).where(T.c.id == 1)).one()
        assert tuple(bool(x) if i < 4 else x for i, x in enumerate(ligne)) == (
            True, False, True, False, "text", "text", "integer")


def test_le_type_de_stockage_filtre_dans_un_where(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        _installer(cnx)
        ids = cnx.execute(select(T.c.id).where(est_texte(T.c.texte) & (nb_octets(T.c.texte) <= 10))
                          .order_by(T.c.id)).scalars().all()
        assert ids == [1]


def test_un_litteral_et_une_expression_passent_par_le_texte(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        assert cnx.execute(select(nb_octets(literal("é€")))).scalar_one() == 5


@pytest.mark.parametrize("nom,attendu", [("sqlite", True), ("postgresql", True), ("mysql", False), ("oracle", False)])
def test_seuls_sqlite_et_postgresql_sont_qualifies(nom, attendu):
    class Faux:
        class dialect:  # noqa: N801
            name = nom
    assert moteur_qualifie(Faux) is attendu
    assert (nom in DIALECTES_QUALIFIES) is attendu
