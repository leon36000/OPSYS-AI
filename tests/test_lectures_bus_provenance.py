"""Copies du bus réel, fictives et en lecture seule, pour le diagnostic de provenance."""
from __future__ import annotations

import dataclasses
import json
from hashlib import sha256

import pytest
from sqlalchemy import event, insert, select, update

from opsys import stockage
from opsys.evenements import bus
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, META

FICTIF = True
TYPE = "opsys.demo_complete"
CONSOMMATEUR = "m08-analytics"


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'bus-fictif.db'}")
    stockage.migrer()
    yield
    stockage.liberer()


def _copier(cnx, **kwargs):
    fonction = getattr(bus, "copier_publications_et_recus", None)
    assert callable(fonction), "la copie de provenance du bus doit être disponible"
    return fonction(cnx, type_evenement=kwargs.get("type_evenement", TYPE),
                    consommateur=kwargs.get("consommateur", CONSOMMATEUR))


def _tables(cnx):
    return {nom: sorted(repr(tuple(ligne)) for ligne in cnx.execute(select(table)))
            for nom, table in META.tables.items()}


def _publier(ident, message="FICTIF Québec"):
    return bus.publier(TYPE, "m05-financecore", {"message": message}, evenement_id=ident)


def _recu(cnx, ident, consommateur=CONSOMMATEUR, **changes):
    cnx.execute(insert(EVENEMENTS_RECUS).values(
        evenement_id=ident, consommateur=consommateur, statut=changes.get("statut", "traite"),
        tentatives=2, prochaine_tentative=None,
        resultat=codec.encoder({"enregistre": True, "evenement_id": ident}),
        derniere_erreur=changes.get("erreur", "MARQUEUR-PRIVE-FICTIF"),
    ))


def test_snapshot_bus_vide_a_empreintes_de_la_copie_vide(base):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        snapshot = _copier(cnx)
        assert snapshot.publications == () and snapshot.recus == ()
        assert snapshot.empreinte_publications_calculee == sha256(b"[]").hexdigest()
        assert snapshot.empreinte_recus_calculee == sha256(b"[]").hexdigest()
        assert _tables(cnx) == avant


def test_snapshot_bus_copie_ids_sources_et_seulement_recu_du_consommateur(base):
    with stockage.transaction() as cnx:
        _publier("z-fictif")
        _publier("a-fictif")
        _recu(cnx, "z-fictif")
        _recu(cnx, "a-fictif", "m10-memoire")
        avant = _tables(cnx)
        snapshot = _copier(cnx)
        assert isinstance(snapshot.publications, tuple) and isinstance(snapshot.recus, tuple)
        assert [p.evenement_id for p in snapshot.publications] == ["a-fictif", "z-fictif"]
        assert [(r.evenement_id, r.consommateur) for r in snapshot.recus] == [("z-fictif", CONSOMMATEUR)]
        assert snapshot.publications[0].producteur == "m05-financecore"
        assert snapshot.publications[0].charge == {"message": "FICTIF Québec"}
        assert snapshot.publications[0].cree_le == cnx.execute(select(EVENEMENTS_SORTANTS.c.cree_le).where(
            EVENEMENTS_SORTANTS.c.evenement_id == "a-fictif")).scalar_one()
        assert snapshot.recus[0].resultat == {"enregistre": True, "evenement_id": "z-fictif"}
        assert _tables(cnx) == avant


def test_copie_bus_filtre_type_sans_renvoyer_les_autres_evenements(base):
    with stockage.transaction() as cnx:
        _publier("demo-fictif")
        snapshot = _copier(cnx, type_evenement="m5.cash_libre_constate")
        assert snapshot.publications == () and snapshot.recus == ()


def test_copie_bus_ne_selecte_pas_erreur_privee_et_ne_cree_pas_transaction(base, monkeypatch):
    with stockage.transaction() as cnx:
        _publier("unique-fictif")
        _recu(cnx, "unique-fictif")
        statements = []
        event.listen(cnx, "before_cursor_execute", lambda _c, _u, sql, _p, _x, _e: statements.append(sql))
        monkeypatch.setattr(bus, "transaction", lambda: pytest.fail("transaction propre interdite"))
        snapshot = _copier(cnx)
        assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
        assert all("derniere_erreur" not in sql for sql in statements)
        assert "derniere_erreur" not in {f.name for f in dataclasses.fields(snapshot.recus[0])}
        assert stockage.connexion_courante() is cnx


def test_copies_bus_independantes_et_classes_exterieures_figees(base):
    with stockage.transaction() as cnx:
        _publier("copies-fictives")
        _recu(cnx, "copies-fictives")
        premier = _copier(cnx)
        premier.publications[0].charge["message"] = "modification locale"
        premier.recus[0].resultat["enregistre"] = False
        deuxieme = _copier(cnx)
        assert deuxieme.publications[0].charge["message"] == "FICTIF Québec"
        assert deuxieme.recus[0].resultat["enregistre"] is True
        with pytest.raises(dataclasses.FrozenInstanceError):
            premier.publications = ()


def test_empreinte_bus_conserve_le_texte_codec_brut(base):
    with stockage.transaction() as cnx:
        _publier("texte-fictif", "é")
        premiere = _copier(cnx)
        cnx.execute(update(EVENEMENTS_SORTANTS).values(charge=' { "message" : "é" } '))
        seconde = _copier(cnx)
        assert premiere.publications[0].charge == seconde.publications[0].charge
        assert premiere.empreinte_publications_calculee != seconde.empreinte_publications_calculee


def test_empreinte_recu_exclut_le_champ_erreur_non_copie(base):
    with stockage.transaction() as cnx:
        _publier("erreur-fictive")
        _recu(cnx, "erreur-fictive")
        premiere = _copier(cnx)
        cnx.execute(update(EVENEMENTS_RECUS).values(derniere_erreur="autre marqueur privé fictif"))
        seconde = _copier(cnx)
        assert premiere.empreinte_recus_calculee == seconde.empreinte_recus_calculee


def test_empreinte_bus_a_un_vecteur_litteral_ordonnee(base):
    with stockage.transaction() as cnx:
        cnx.execute(insert(EVENEMENTS_SORTANTS).values(
            evenement_id="vector-fictif", type_evenement=TYPE, producteur="m05-financecore",
            charge='{"message":"é"}', cree_le="2026-10-09T12:00:00Z",
        ))
        snapshot = _copier(cnx)
        attendu = ('[{"charge":"{\\"message\\":\\"é\\"}","cree_le":"2026-10-09T12:00:00Z",'
                   '"evenement_id":"vector-fictif","producteur":"m05-financecore",'
                   '"type_evenement":"opsys.demo_complete"}]')
        assert json.loads(attendu)[0]["charge"] == '{"message":"é"}'
        assert snapshot.empreinte_publications_calculee == sha256(attendu.encode()).hexdigest()


@pytest.mark.parametrize("mode", ["aucune", "etrangere", "autre_courante"])
def test_copie_bus_refuse_connexion_non_canonique_avant_select(base, mode):
    fonction = getattr(bus, "copier_publications_et_recus", None)
    assert callable(fonction), "la copie de provenance du bus doit être disponible"
    if mode == "aucune":
        with pytest.raises(ValueError, match="canonique"):
            fonction(None, type_evenement=TYPE, consommateur=CONSOMMATEUR)
        return
    with stockage.moteur().connect() as etrangere:
        statements = []
        event.listen(etrangere, "before_cursor_execute", lambda _c, _u, sql, _p, _x, _e: statements.append(sql))
        if mode == "autre_courante":
            with stockage.transaction(), pytest.raises(ValueError, match="canonique"):
                fonction(etrangere, type_evenement=TYPE, consommateur=CONSOMMATEUR)
        else:
            with pytest.raises(ValueError, match="canonique"):
                fonction(etrangere, type_evenement=TYPE, consommateur=CONSOMMATEUR)
        assert statements == []


def test_codec_bus_corrompu_refuse_sans_message_source(base):
    with stockage.transaction() as cnx:
        _publier("corruption-fictive")
        cnx.execute(update(EVENEMENTS_SORTANTS).values(charge='{"__opsys__":"CANARY-FICTIF","v":0}'))
        avant = _tables(cnx)
        with pytest.raises(ValueError) as exc:
            _copier(cnx)
        assert "CANARY-FICTIF" not in str(exc.value)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("champ", ["charge", "resultat"])
@pytest.mark.parametrize("texte", [
    '{"__opsys__":"decimal","v":"CANARY-FICTIF"}',
    '{"__opsys__":"bytes","v":["CANARY-FICTIF"]}',
])
def test_codec_bus_mal_type_refuse_constamment_publication_ou_recu(base, champ, texte):
    with stockage.transaction() as cnx:
        _publier("type-corrompu-fictif")
        _recu(cnx, "type-corrompu-fictif")
        table = EVENEMENTS_SORTANTS if champ == "charge" else EVENEMENTS_RECUS
        cnx.execute(update(table).values(**{champ: texte}))
        avant = _tables(cnx)
        with pytest.raises(ValueError) as exc:
            _copier(cnx)
        assert str(exc.value) == "copie de provenance du bus invalide"
        assert _tables(cnx) == avant


@pytest.mark.parametrize("cible", ["charge", "resultat"])
def test_json_sql_profond_reel_devient_erreur_copie_constante(base, cible):
    """JSON valide stocké directement : le vrai decoder est exercé, sans faultmock."""
    from sqlalchemy import inspect, text

    def tables_reelles(cnx):
        noms = inspect(cnx).get_table_names()
        assert len(noms) == 49
        return {nom: sorted(repr(tuple(ligne)) for ligne in cnx.execute(text(
            'SELECT * FROM "' + nom.replace('"', '""') + '"',
        ))) for nom in noms}

    profond = '{"FICTIF":' + '[' * 2000 + '0' + ']' * 2000 + '}'
    with stockage.transaction() as cnx:
        _publier("json-profond-fictif")
        _recu(cnx, "json-profond-fictif")
        table = EVENEMENTS_SORTANTS if cible == "charge" else EVENEMENTS_RECUS
        cnx.execute(update(table).values({cible: profond}))
        avant = tables_reelles(cnx)
        try:
            with pytest.raises(ValueError) as exc:
                _copier(cnx)
            assert type(exc.value) is ValueError
            assert str(exc.value) == "copie de provenance du bus invalide"
        finally:
            assert tables_reelles(cnx) == avant
