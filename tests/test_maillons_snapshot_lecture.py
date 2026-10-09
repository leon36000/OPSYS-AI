"""Métadonnées SQL réelles et copies de registres fictifs, sans écriture du lecteur."""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import event, insert, select, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage import maillons as fabrique_maillons
from opsys.stockage.schema import META, REGISTRES

FICTIF = True
DEPARTEMENT = "m08-analytics"
REGISTRE = "faits_chantier"


def _module():
    import importlib

    return importlib.import_module("opsys.stockage.maillons")


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'maillons-fictifs.db'}")
    stockage.migrer()
    yield
    stockage.liberer()


def _copier(cnx, **kwargs):
    fonction = getattr(_module(), "copier_maillons_avec_metadonnees", None)
    assert callable(fonction), "la copie des maillons avec métadonnées doit être disponible"
    return fonction(cnx, departement=kwargs.get("departement", DEPARTEMENT),
                    registre=kwargs.get("registre", REGISTRE))


def _tables(cnx):
    return {nom: sorted(repr(tuple(ligne)) for ligne in cnx.execute(select(table)))
            for nom, table in META.tables.items()}


def _ajouter(cnx, rang, valeur, **changes):
    cnx.execute(insert(REGISTRES).values(
        departement=changes.get("departement", DEPARTEMENT), registre=changes.get("registre", REGISTRE),
        rang=rang, maillon=codec.encoder(valeur),
        cree_le=dt.datetime(2026, 10, 9, 12, 0, 0, 123456, tzinfo=dt.UTC),
    ))


def test_snapshot_maillons_vide_identifie_son_registre(base):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        snapshot = _copier(cnx)
        assert snapshot.departement == DEPARTEMENT and snapshot.registre == REGISTRE
        assert snapshot.lignes == ()
        assert snapshot.empreinte_snapshot_calculee == sha256(b"[]").hexdigest()
        assert _tables(cnx) == avant


def test_rangs_reels_non_contigus_dates_sql_et_types_codec_preserves(base):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 7, {"fictif": True, "valeur": Decimal("1.20"), "couple": (1, "é")})
        _ajouter(cnx, 2, {"fictif": True})
        _ajouter(cnx, 0, {"autre": True}, registre="principal")
        _ajouter(cnx, 0, {"autre": True}, departement="m05-financecore")
        avant = _tables(cnx)
        snapshot = _copier(cnx)
        assert isinstance(snapshot.lignes, tuple)
        assert [ligne.rang for ligne in snapshot.lignes] == [2, 7]
        assert snapshot.lignes[1].maillon == {"fictif": True, "valeur": Decimal("1.20"), "couple": (1, "é")}
        assert type(snapshot.lignes[1].maillon["valeur"]) is Decimal
        assert snapshot.lignes[1].cree_le == dt.datetime(2026, 10, 9, 12, 0, 0, 123456)
        assert snapshot.lignes[1].cree_le.tzinfo is None, "SQLite ne fournit pas un fuseau à inventer"
        assert _tables(cnx) == avant


def test_copie_maillons_n_ouvre_pas_de_transaction_et_necrit_pas(base, monkeypatch):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, {"fictif": True})
        statements = []
        event.listen(cnx, "before_cursor_execute", lambda _c, _u, sql, _p, _x, _e: statements.append(sql))
        monkeypatch.setattr(_module(), "transaction", lambda: pytest.fail("transaction propre interdite"))
        snapshot = _copier(cnx)
        assert snapshot.lignes[0].rang == 0
        assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
        assert stockage.connexion_courante() is cnx


def test_copies_maillons_independantes_et_snapshot_fige(base):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, {"liste": ["fictif", 1]})
        premier = _copier(cnx)
        premier.lignes[0].maillon["liste"].append(2)
        deuxieme = _copier(cnx)
        assert deuxieme.lignes[0].maillon == {"liste": ["fictif", 1]}
        with pytest.raises(dataclasses.FrozenInstanceError):
            premier.registre = "autre"


def test_empreinte_maillons_conserve_json_stocke_sans_le_reencoder(base):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, {"fictif": "é"})
        premiere = _copier(cnx)
        cnx.execute(update(REGISTRES).values(maillon=' { "fictif" : "é" } '))
        seconde = _copier(cnx)
        assert premiere.lignes[0].maillon == seconde.lignes[0].maillon
        assert premiere.empreinte_snapshot_calculee != seconde.empreinte_snapshot_calculee


def test_empreinte_maillons_a_vecteur_litteral_rang_et_date_sql(base):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 3, {"fictif": True})
        snapshot = _copier(cnx)
        attendu = ('[{"cree_le":"2026-10-09T12:00:00.123456",'
                   '"maillon":"{\\"fictif\\":true}","rang":3}]')
        assert snapshot.empreinte_snapshot_calculee == sha256(attendu.encode()).hexdigest()


@pytest.mark.parametrize("mode", ["aucune", "etrangere", "autre_courante"])
def test_copie_maillons_refuse_connexion_non_canonique_avant_select(base, mode):
    fonction = getattr(_module(), "copier_maillons_avec_metadonnees", None)
    assert callable(fonction), "la copie des maillons avec métadonnées doit être disponible"
    if mode == "aucune":
        with pytest.raises(ValueError, match="canonique"):
            fonction(None, departement=DEPARTEMENT, registre=REGISTRE)
        return
    with stockage.moteur().connect() as etrangere:
        statements = []
        event.listen(etrangere, "before_cursor_execute", lambda _c, _u, sql, _p, _x, _e: statements.append(sql))
        if mode == "autre_courante":
            with stockage.transaction(), pytest.raises(ValueError, match="canonique"):
                fonction(etrangere, departement=DEPARTEMENT, registre=REGISTRE)
        else:
            with pytest.raises(ValueError, match="canonique"):
                fonction(etrangere, departement=DEPARTEMENT, registre=REGISTRE)
        assert statements == []


def test_maillon_corrompu_refuse_sans_fuite_de_sa_valeur(base):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, {"fictif": True})
        cnx.execute(update(REGISTRES).values(maillon='{"__opsys__":"CANARY-FICTIF","v":0}'))
        avant = _tables(cnx)
        with pytest.raises(ValueError) as exc:
            _copier(cnx)
        assert "CANARY-FICTIF" not in str(exc.value)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("texte", [
    '{"__opsys__":"decimal","v":"CANARY-FICTIF"}',
    '{"__opsys__":"bytes","v":["CANARY-FICTIF"]}',
])
def test_codec_maillon_mal_type_refuse_constamment(base, texte):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, {"fictif": True})
        cnx.execute(update(REGISTRES).values(maillon=texte))
        avant = _tables(cnx)
        with pytest.raises(ValueError) as exc:
            _copier(cnx)
        assert str(exc.value) == "copie des maillons avec métadonnées invalide"
        assert _tables(cnx) == avant


def test_reader_reflete_une_nouvelle_ecriture_sans_cache(base):
    with stockage.transaction() as cnx:
        fabrique_maillons(DEPARTEMENT, REGISTRE).append({"fictif": True})
        premier = _copier(cnx)
        fabrique_maillons(DEPARTEMENT, REGISTRE).append({"fictif": True, "revision": 2})
        deuxieme = _copier(cnx)
        assert len(premier.lignes) == 1 and len(deuxieme.lignes) == 2
        assert premier.empreinte_snapshot_calculee != deuxieme.empreinte_snapshot_calculee


def test_maillon_json_sql_profond_reel_devient_erreur_copie_constante(base):
    """Le vrai codec décode une chaîne JSON valide profonde persistée dans SQLite."""
    from sqlalchemy import inspect, text

    def tables_reelles(cnx):
        noms = inspect(cnx).get_table_names()
        assert len(noms) == 49
        return {nom: sorted(repr(tuple(ligne)) for ligne in cnx.execute(text(
            'SELECT * FROM "' + nom.replace('"', '""') + '"',
        ))) for nom in noms}

    profond = '{"FICTIF":' + '[' * 2000 + '0' + ']' * 2000 + '}'
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, {"FICTIF": True})
        cnx.execute(update(REGISTRES).values(maillon=profond))
        avant = tables_reelles(cnx)
        try:
            with pytest.raises(ValueError) as exc:
                _copier(cnx)
            assert type(exc.value) is ValueError
            assert str(exc.value) == "copie des maillons avec métadonnées invalide"
        finally:
            assert tables_reelles(cnx) == avant
