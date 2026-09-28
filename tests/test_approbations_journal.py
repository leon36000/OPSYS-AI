"""Robustesse de la file d'approbation et journal d'audit."""

from __future__ import annotations

import pytest

from opsys import approbations, etat, modeles
from opsys.outils import Autonomie, Outil

_SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
APPELS: list[int] = []


def _panne(x: int) -> dict:
    APPELS.append(x)
    raise RuntimeError("fournisseur injoignable")


def _ok(x: int) -> dict:
    APPELS.append(x)
    return {"x": x}


OUTILS = {
    "m9_panne": Outil("m9_panne", "Outil qui tombe en panne.", _SCHEMA, _panne, Autonomie.T3),
    "m9_ok": Outil("m9_ok", "Outil qui réussit.", _SCHEMA, _ok, Autonomie.T3),
}


@pytest.fixture(autouse=True)
def _vider():
    APPELS.clear()


def test_panne_pendant_execution_termine_en_echec_sans_rejeu(session):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_panne", {"x": 1})
        decision = approbations.decider(cnx, ident, True, "nathan", OUTILS)
        assert decision["statut"] == "echec"
        assert decision["reponse"]["erreur"] == "panne_execution"
        with pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(cnx, ident, True, "nathan", OUTILS)
    assert APPELS == [1]  # exécuté une seule fois


def test_reservation_concurrente_refusee(session):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 2})
        cnx.execute("UPDATE approbations SET statut='en_cours' WHERE id=?", (ident,))
        with pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(cnx, ident, True, "autre", OUTILS)
    assert APPELS == []


def test_journal_trace_decisions_modes_et_paliers(session, opsys_home):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 3})
        approbations.decider(cnx, ident, True, "nathan", OUTILS, "ok pour moi")
        approbations.fixer_mode(cnx, "m09-demo", "supervise", "nathan")
    modeles.enregistrer_paliers({"rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}},
                                par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    actions = [(e["action"], e["par"]) for e in journal]
    assert actions == [("modeles.paliers", "nathan"), ("departement.mode", "nathan"),
                       ("approbation.approuver", "nathan")]
    assert journal[2]["details"] == {"outil": "m9_ok", "statut": "executee"}
