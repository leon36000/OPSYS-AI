"""Oracles SQL/contrat du propriétaire CMO, aucune source vraie ni API externe."""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from m7_marketing import cmo_strategie as cmo
from sqlalchemy import insert

from opsys import contexte, identite, stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'cmo-fictif.db'}")
    stockage.liberer()
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "owner-fictif", "Propriétaire FICTIF", "mot-de-passe-fictif-2026", ["nathan_owner"],
        )
    yield
    stockage.liberer()


@contextmanager
def _humain():
    with (
        stockage.transaction() as cnx,
        contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-fictif", "nathan_owner", source="console")),
        contexte.appeler_en_tant_que("m07-marketing", origine="console"),
    ):
        yield cnx


def _brut(cnx, rang, texte):
    cnx.execute(insert(REGISTRES).values(departement="m07-marketing", registre=cmo.REGISTRE, rang=rang, maillon=texte))


@pytest.mark.parametrize("mode", ["maillon", "nombre", "total"])
def test_quotas_sql_avant_tout_decodage(base, monkeypatch, mode):
    with _humain() as cnx:
        if mode == "maillon":
            _brut(cnx, 0, "x" * (cmo.MAX_MAILLON + 1))
        elif mode == "nombre":
            for rang in range(cmo.MAX_EVENEMENTS + 1):
                _brut(cnx, rang, "{}")
        else:
            for rang in range(33):
                _brut(cnx, rang, "x" * cmo.MAX_MAILLON)
        def interdit(*_args):
            pytest.fail("le quota SQL doit refuser avant codec.decoder")
        monkeypatch.setattr(codec, "decoder", interdit)
        with pytest.raises(ValueError, match="CMO-QUOTA-REGISTRE"):
            cmo.lire(cnx)


@pytest.mark.parametrize("rangs", [[-1, 1], [0, 2]])
def test_prefixe_negatif_ou_discontinu_refuse_avant_decodage(base, monkeypatch, rangs):
    with _humain() as cnx:
        for rang in rangs:
            _brut(cnx, rang, "{}")
        def interdit(*_args):
            pytest.fail("les rangs doivent être contrôlés avant décodage")
        monkeypatch.setattr(codec, "decoder", interdit)
        with pytest.raises(ValueError, match="CMO-PREFIXE-NON-CONTIGU"):
            cmo.lire(cnx)


@pytest.mark.parametrize("source,origine", [
    ("agent", "console"), ("console", "m07-marketing"), ("agent", "m07-marketing"),
])
def test_source_console_seule_ne_forge_pas_le_port_humain(base, source, origine):
    with (
        stockage.transaction() as cnx,
        contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-fictif", "nathan_owner", source=source)),
        contexte.appeler_en_tant_que("m07-marketing", origine=origine),
        pytest.raises(PermissionError, match="CMO-PORT-HUMAIN-REQUIS"),
    ):
        cmo.lire(cnx)


@pytest.mark.parametrize("brut", ['{"__opsys__":null,"v":"x"}', '{"__opsys__":"decimal","v":"oops"}',
                                  '[1,2]', '{"schema_version":1,"type":"inconnu"}'])
def test_corruptions_codec_et_formes_historique_refusees(base, brut):
    with _humain() as cnx:
        _brut(cnx, 0, brut)
        with pytest.raises(ValueError, match="CMO-HISTORIQUE-INVALIDE"):
            cmo.lire(cnx)
