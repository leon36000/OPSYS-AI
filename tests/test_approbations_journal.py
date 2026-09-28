"""Robustesse de la file d'approbation et journal d'audit."""

from __future__ import annotations

import threading
import time

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import text

from opsys import approbations, etat, modeles, stockage
from opsys.outils import Autonomie, Outil

_SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
APPELS: list[int] = []


def _panne(x: int) -> dict:
    APPELS.append(x)
    raise RuntimeError("fournisseur injoignable")


def _ok(x: int) -> dict:
    APPELS.append(x)
    return {"x": x}


def _panne_apres_ecriture(x: int) -> dict:
    """Écrit un maillon métier puis tombe en panne : le maillon doit être annulé (point de sauvegarde)."""
    stockage.maillons("m09-demo", "principal").append({"x": x})
    raise RuntimeError("fournisseur injoignable après écriture")


def _refus_apres_ecriture(x: int) -> dict:
    stockage.maillons("m09-demo", "principal").append({"x": x})
    raise ValueError("refus métier après écriture")


def _lente(x: int) -> dict:
    time.sleep(0.1)  # élargit la fenêtre de course entre deux décisions concurrentes
    APPELS.append(x)
    return {"x": x}


OUTILS = {
    "m9_panne": Outil("m9_panne", "Outil qui tombe en panne.", _SCHEMA, _panne, Autonomie.T3),
    "m9_ok": Outil("m9_ok", "Outil qui réussit.", _SCHEMA, _ok, Autonomie.T3),
    "m9_panne_ecrit": Outil("m9_panne_ecrit", "Écrit puis tombe en panne.", _SCHEMA,
                            _panne_apres_ecriture, Autonomie.T3),
    "m9_refuse_ecrit": Outil("m9_refuse_ecrit", "Écrit puis refuse.", _SCHEMA, _refus_apres_ecriture, Autonomie.T3),
    "m9_lent": Outil("m9_lent", "Outil lent, pour la course entre deux décisions.", _SCHEMA, _lente, Autonomie.T3),
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
        cnx.execute(text("UPDATE approbations SET statut = 'en_cours' WHERE id = :id"), {"id": ident})
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


# -- ADR-0009 : décision et exécution dans une seule transaction --------------------------------


def test_panne_apres_ecriture_annule_le_maillon_mais_garde_le_statut_echec(session):
    """`executer_atomique` ouvre un point de sauvegarde : la panne n'annule que l'écriture métier."""
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_panne_ecrit", {"x": 7})
        decision = approbations.decider(cnx, ident, True, "nathan", OUTILS)
    assert decision["statut"] == "echec" and decision["reponse"]["erreur"] == "panne_execution"
    with session() as cnx:
        [demande] = approbations.lister(cnx)
    assert demande["statut"] == "echec"
    assert len(stockage.maillons("m09-demo", "principal")) == 0


def test_refus_metier_apres_ecriture_annule_le_maillon_mais_garde_le_statut_echec(session):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_refuse_ecrit", {"x": 8})
        decision = approbations.decider(cnx, ident, True, "nathan", OUTILS)
    assert decision["statut"] == "echec" and decision["reponse"]["erreur"] == "refus_metier"
    with session() as cnx:
        [demande] = approbations.lister(cnx)
    assert demande["statut"] == "echec"
    assert len(stockage.maillons("m09-demo", "principal")) == 0


def test_panne_apres_reservation_annule_toute_la_transaction(session, monkeypatch):
    """Une panne juste avant le commit (après réservation ET exécution) n'écrit RIEN : la demande
    reste `en_attente` et le maillon métier disparaît — décision et exécution sont une transaction."""
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 9})

    def _crash(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("panne simulée juste avant le commit")

    monkeypatch.setattr(approbations, "journaliser", _crash)  # dernier appel de `decider`, avant le commit
    with pytest.raises(RuntimeError, match="panne simulée"), session() as cnx:
        approbations.decider(cnx, ident, True, "nathan", OUTILS)
    # Nouvelle transaction : la précédente n'a jamais committé, y compris sa propre réservation.
    with session() as cnx:
        [demande] = approbations.lister(cnx)
    assert demande["statut"] == "en_attente" and demande["decide_par"] is None
    assert len(stockage.maillons("m09-demo", "principal")) == 0


def _decider_concurremment(session, ident: str, resultats: list) -> None:
    try:
        with session() as cnx:
            resultats.append(approbations.decider(cnx, ident, True, "nathan", OUTILS))
    except ValueError as exc:
        resultats.append(exc)


def test_deux_decisions_concurrentes_une_seule_execution(session):
    """Deux humains approuvent la même demande en même temps : l'outil ne s'exécute qu'une fois."""
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_lent", {"x": 10})
    resultats: list[dict | ValueError] = []
    fils = [threading.Thread(target=_decider_concurremment, args=(session, ident, resultats)) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=10)
    executions = [r for r in resultats if isinstance(r, dict)]
    refus = [r for r in resultats if isinstance(r, ValueError)]
    assert len(executions) == 1 and executions[0]["statut"] == "executee"
    assert len(refus) == 1
    assert APPELS == [10]  # l'outil ne tourne qu'une seule fois


@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_atomicite_et_concurrence_sur_postgresql(monkeypatch):
    """Même mécanisme que `test_stockage.py::test_postgresql_se_comporte_comme_sqlite` : la
    réservation par `UPDATE ... WHERE statut='en_attente'` s'appuie sur le verrouillage de ligne de
    PostgreSQL en lecture-validée, comme `BEGIN IMMEDIATE` s'appuie sur le verrou d'écriture SQLite."""
    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            with stockage.transaction() as cnx:
                ident_echec = approbations.creer_demande(cnx, "m09-demo", "m9_panne_ecrit", {"x": 1})
                ident_course = approbations.creer_demande(cnx, "m09-demo", "m9_lent", {"x": 2})

            with stockage.transaction() as cnx:
                decision = approbations.decider(cnx, ident_echec, True, "nathan", OUTILS)
            assert decision["statut"] == "echec"
            with stockage.transaction() as cnx:
                [demande] = [d for d in approbations.lister(cnx) if d["id"] == ident_echec]
            assert demande["statut"] == "echec"
            assert len(stockage.maillons("m09-demo", "principal")) == 0

            APPELS.clear()
            resultats: list[dict | ValueError] = []
            fils = [threading.Thread(target=_decider_concurremment, args=(stockage.transaction, ident_course,
                                                                           resultats)) for _ in range(2)]
            for fil in fils:
                fil.start()
            for fil in fils:
                fil.join(timeout=10)
            executions = [r for r in resultats if isinstance(r, dict)]
            assert len(executions) == 1 and executions[0]["statut"] == "executee"
            assert APPELS == [2]
        finally:
            stockage.liberer()
