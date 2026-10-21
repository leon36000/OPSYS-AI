"""Robustesse de la file d'approbation et journal d'audit."""

from __future__ import annotations

import threading
import time

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import event, select, text

from opsys import approbations, etat, identite, modeles, stockage
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import APPROBATIONS, JOURNAL

_SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
# Les outils de ce module sont T2 (engagement) -> niveau par défaut N4 (ADR-0009 §4) : seul
# `nathan_owner` les décide sous la politique par défaut (fail-closed, ADR-0009 §5). N4, pas N5 :
# ce module teste la mécanique générale de la file (atomicité, concurrence, journal), pas
# l'attestation professionnelle propre à N5 (voir `tests/test_identite_approbations.py`).
DEPARTEMENTS: dict = {}  # aucun manifeste chargé : `decider` retombe sur la politique par défaut
NIVEAU_TEST = Niveau.N4
APPELS: list[int] = []


def _panne(x: int) -> dict:
    APPELS.append(x)
    raise RuntimeError("fournisseur injoignable")


def _ok(x: int) -> dict:
    APPELS.append(x)
    return {"x": x}


def _refus_verdict(x: int) -> dict:
    APPELS.append(x)
    return {"accepte": False, "verdict": {"code": "REJ-PIECE-MANQUANTE", "detail": "Pièce source manquante"}}


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
    "m9_panne": Outil("m9_panne", "Outil qui tombe en panne.", _SCHEMA, _panne, Autonomie.T2),
    "m9_ok": Outil("m9_ok", "Outil qui réussit.", _SCHEMA, _ok, Autonomie.T2),
    "m9_refus_verdict": Outil("m9_refus_verdict", "Verdict métier refusé.", _SCHEMA, _refus_verdict, Autonomie.T2),
    "m9_panne_ecrit": Outil("m9_panne_ecrit", "Écrit puis tombe en panne.", _SCHEMA,
                            _panne_apres_ecriture, Autonomie.T2),
    "m9_refuse_ecrit": Outil("m9_refuse_ecrit", "Écrit puis refuse.", _SCHEMA, _refus_apres_ecriture, Autonomie.T2),
    "m9_lent": Outil("m9_lent", "Outil lent, pour la course entre deux décisions.", _SCHEMA, _lente, Autonomie.T2),
}


def test_approbation_ne_marque_pas_un_verdict_metier_refuse_comme_execute(session, nathan):
    with session() as cnx:
        ident = _creer(cnx, "m9_refus_verdict", {"x": 1})
        decision = approbations.decider(cnx, ident, True, nathan, OUTILS, DEPARTEMENTS)
        assert decision["reponse"]["ok"] is True  # Le transport a bien transmis le verdict.
        assert decision["reponse"]["resultat"]["accepte"] is False
        assert decision["statut"] == "echec"
        trace = approbations.lire(cnx, ident)
        assert trace["statut"] == "echec"
        assert trace["resultat"]["resultat"]["verdict"]["code"] == "REJ-PIECE-MANQUANTE"
    assert APPELS == [1]


def test_validation_au_depart_ne_marque_pas_un_verdict_metier_refuse_comme_execute(session, nathan):
    from opsys.contexte import IdentiteAppelante

    with session() as cnx:
        ident = approbations.tracer_validation_au_depart(
            cnx, "m09-demo", "m9_refus_verdict", {"x": 1}, niveau=Niveau.N3,
            signataire=IdentiteAppelante(nathan, "nathan_owner"),
            reponse={"ok": True, "resultat": {"accepte": False}},
        )
        trace = approbations.lire(cnx, ident)
        assert trace["statut"] == "echec"
        assert trace["resultat"] == {"ok": True, "accepte": False}


@pytest.fixture(autouse=True)
def _vider():
    APPELS.clear()


def _creer(cnx, outil: str, arguments: dict) -> str:
    return approbations.creer_demande(cnx, "m09-demo", outil, arguments, niveau=NIVEAU_TEST)


def test_panne_pendant_execution_termine_en_echec_sans_rejeu(session, nathan):
    with session() as cnx:
        ident = _creer(cnx, "m9_panne", {"x": 1})
        decision = approbations.decider(cnx, ident, True, nathan, OUTILS, DEPARTEMENTS)
        assert decision["statut"] == "echec"
        assert decision["reponse"]["erreur"] == "panne_execution"
        with pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(cnx, ident, True, nathan, OUTILS, DEPARTEMENTS)
    assert APPELS == [1]  # exécuté une seule fois


def test_reservation_concurrente_refusee(session):
    with session() as cnx:
        ident = _creer(cnx, "m9_ok", {"x": 2})
        cnx.execute(text("UPDATE approbations SET statut = 'en_cours' WHERE id = :id"), {"id": ident})
        # La demande est déjà prise en charge : le refus intervient avant même la vérification de
        # rôle, donc "autre" n'a pas besoin d'être une personne enregistrée pour ce test.
        with pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(cnx, ident, True, "autre", OUTILS, DEPARTEMENTS)
    assert APPELS == []


def test_decision_refusee_sans_personne_active(session):
    """Fail-closed (ADR-0009 §5) : un identifiant inconnu, ou une personne inactive, ne décide rien —
    la demande reste `en_attente`, rien n'est exécuté."""
    with session() as cnx:
        ident = _creer(cnx, "m9_ok", {"x": 99})
        with pytest.raises(ValueError, match="personne inconnue ou inactive"):
            approbations.decider(cnx, ident, True, "fantome", OUTILS, DEPARTEMENTS)
        with pytest.raises(ValueError, match="doit être signée par une personne"):
            approbations.decider(cnx, ident, True, "  ", OUTILS, DEPARTEMENTS)
        [demande] = approbations.lister(cnx, "en_attente")
    assert demande["id"] == ident and demande["decide_par"] is None
    assert APPELS == []


def test_journal_trace_decisions_modes_et_paliers(session, opsys_home, nathan):
    with session() as cnx:
        ident = _creer(cnx, "m9_ok", {"x": 3})
        approbations.decider(cnx, ident, True, nathan, OUTILS, DEPARTEMENTS, "ok pour moi")
        approbations.fixer_mode(cnx, "m09-demo", "supervise", "nathan")
    modeles.enregistrer_paliers({"rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}},
                                par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    actions = [(e["action"], e["par"]) for e in journal]
    assert actions == [("modeles.paliers", "nathan"), ("departement.mode", "nathan"),
                       ("approbation.approuver", "nathan")]
    assert journal[2]["details"] == {"outil": "m9_ok", "statut": "executee", "role": "nathan_owner"}


# -- ADR-0009 : décision et exécution dans une seule transaction --------------------------------


def test_panne_apres_ecriture_annule_le_maillon_mais_garde_le_statut_echec(session, nathan):
    """`executer_atomique` ouvre un point de sauvegarde : la panne n'annule que l'écriture métier."""
    with session() as cnx:
        ident = _creer(cnx, "m9_panne_ecrit", {"x": 7})
        decision = approbations.decider(cnx, ident, True, nathan, OUTILS, DEPARTEMENTS)
    assert decision["statut"] == "echec" and decision["reponse"]["erreur"] == "panne_execution"
    with session() as cnx:
        [demande] = approbations.lister(cnx)
    assert demande["statut"] == "echec"
    assert len(stockage.maillons("m09-demo", "principal")) == 0


def test_refus_metier_apres_ecriture_annule_le_maillon_mais_garde_le_statut_echec(session, nathan):
    with session() as cnx:
        ident = _creer(cnx, "m9_refuse_ecrit", {"x": 8})
        decision = approbations.decider(cnx, ident, True, nathan, OUTILS, DEPARTEMENTS)
    assert decision["statut"] == "echec" and decision["reponse"]["erreur"] == "refus_metier"
    with session() as cnx:
        [demande] = approbations.lister(cnx)
    assert demande["statut"] == "echec"
    assert len(stockage.maillons("m09-demo", "principal")) == 0


def test_panne_apres_reservation_annule_toute_la_transaction(session, monkeypatch, nathan):
    """Une panne juste avant le commit (après réservation ET exécution) n'écrit RIEN : la demande
    reste `en_attente` et le maillon métier disparaît — décision et exécution sont une transaction."""
    with session() as cnx:
        ident = _creer(cnx, "m9_ok", {"x": 9})

    def _crash(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("panne simulée juste avant le commit")

    monkeypatch.setattr(approbations, "journaliser", _crash)  # dernier appel de `decider`, avant le commit
    with pytest.raises(RuntimeError, match="panne simulée"), session() as cnx:
        approbations.decider(cnx, ident, True, nathan, OUTILS, DEPARTEMENTS)
    # Nouvelle transaction : la précédente n'a jamais committé, y compris sa propre réservation.
    with session() as cnx:
        [demande] = approbations.lister(cnx)
    assert demande["statut"] == "en_attente" and demande["decide_par"] is None
    assert len(stockage.maillons("m09-demo", "principal")) == 0


def _decider_concurremment(session, ident: str, resultats: list) -> None:
    try:
        with session() as cnx:
            resultats.append(approbations.decider(cnx, ident, True, "nathan", OUTILS, DEPARTEMENTS))
    except ValueError as exc:
        resultats.append(exc)


def test_deux_decisions_concurrentes_une_seule_execution(session, nathan):
    """Deux humains approuvent la même demande en même temps : l'outil ne s'exécute qu'une fois."""
    with session() as cnx:
        ident = _creer(cnx, "m9_lent", {"x": 10})
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
                identite.creer_personne(cnx, "nathan", "Nathan St-Louis", "mot-de-passe-de-test-pg-1234",
                                        ["nathan_owner"])
                ident_echec = approbations.creer_demande(cnx, "m09-demo", "m9_panne_ecrit", {"x": 1},
                                                         niveau=NIVEAU_TEST)
                ident_course = approbations.creer_demande(cnx, "m09-demo", "m9_lent", {"x": 2}, niveau=NIVEAU_TEST)

            with stockage.transaction() as cnx:
                decision = approbations.decider(cnx, ident_echec, True, "nathan", OUTILS, DEPARTEMENTS)
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


@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
@pytest.mark.parametrize(
    "perdant_approuve,gagnant_approuve", [(False, True), (True, True), (True, False), (False, False)]
)
def test_decision_postgresql_perdante_ne_confirme_ni_ne_journalise(monkeypatch, tmp_path, record_property,
                                                               perdant_approuve, gagnant_approuve):
    """Fictif : suspendre l'UPDATE après le SELECT réel, puis committer l'autre décision."""
    with postgres_ephemere(stockage_en_memoire=True) as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home-fictif"))
        stockage.migrer()

        def sentinelle(x):
            stockage.maillons("m09-demo", "sentinelles-fictives").append({"fictif": True, "x": x})
            return _ok(x)

        outils = {"m9_sentinelle": Outil("m9_sentinelle", "Sentinelle fictive.", _SCHEMA,
                                       sentinelle, Autonomie.T2)}
        with stockage.transaction() as cnx:
            identite.creer_personne(cnx, "nathan", "Propriétaire fictif", "mot-de-passe-fictif-1234",
                                    ["nathan_owner"])
            ident = _creer(cnx, "m9_sentinelle", {"x": 7})
        pret = threading.Event()
        reprendre = threading.Event()
        observations = {"rowcounts": []}
        moteur = stockage.moteur()

        def metadata(cnx):
            assert cnx.get_isolation_level() == "READ COMMITTED"
            cnx.exec_driver_sql("SET LOCAL statement_timeout = '5s'")
            cnx.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            return cnx.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()

        def decider_perdant():
            try:
                with stockage.transaction() as cnx:
                    observations["pid_perdant"] = metadata(cnx)
                    reponse = approbations.decider(cnx, ident, perdant_approuve, "nathan", outils, DEPARTEMENTS)
                observations["reponse_perdant"] = reponse
            except Exception as exc:
                observations["erreur_perdant"] = exc

        perdant = threading.Thread(target=decider_perdant, name="decision-perdante-fictive", daemon=True)

        def est_update(context):
            requete = getattr(getattr(context, "compiled", None), "statement", None)
            return (getattr(requete, "is_update", False)
                    and getattr(getattr(requete, "table", None), "name", None) == APPROBATIONS.name)

        def avant(_cnx, _curseur, _sql, _params, context, _multiple):
            if threading.current_thread() is perdant and est_update(context):
                pret.set()
                assert reprendre.wait(10), "décision gagnante non committée"
                assert observations["gagnant_committe"] is True

        def apres(_cnx, curseur, _sql, _params, context, _multiple):
            if threading.current_thread() is perdant and est_update(context):
                observations["rowcounts"].append(curseur.rowcount)

        event.listen(moteur, "before_cursor_execute", avant)
        event.listen(moteur, "after_cursor_execute", apres)
        try:
            perdant.start()
            assert pret.wait(10), observations
            with stockage.transaction() as cnx:
                pid_gagnant = metadata(cnx)
                reponse = approbations.decider(cnx, ident, gagnant_approuve, "nathan", outils, DEPARTEMENTS)
            observations["gagnant_committe"] = True
            reprendre.set()
            perdant.join(10)
            assert not perdant.is_alive()
            assert observations["pid_perdant"] != pid_gagnant
            assert observations["rowcounts"] == [0]
            statut = "executee" if gagnant_approuve else "refusee"
            assert reponse["statut"] == statut
            with stockage.transaction() as cnx:
                assert approbations.lire(cnx, ident)["statut"] == statut
                actions = cnx.execute(select(JOURNAL.c.action).where(JOURNAL.c.cible == ident)).scalars().all()
            appels_attendus = [7] if gagnant_approuve else []
            assert list(APPELS) == appels_attendus
            sentinelles_attendues = [{"fictif": True, "x": 7}] if gagnant_approuve else []
            assert list(stockage.maillons("m09-demo", "sentinelles-fictives")) == sentinelles_attendues
            record_property("concurrence_fictive", repr({**observations, "pid_gagnant": pid_gagnant,
                                                        "isolation": "READ COMMITTED", "statut_final": statut,
                                                        "journal": actions, "sentinelles": sentinelles_attendues}))
            assert "reponse_perdant" not in observations, observations
            assert isinstance(observations.get("erreur_perdant"), ValueError), observations
            assert "autre décision" in str(observations["erreur_perdant"])
            assert actions == ["approbation.approuver" if gagnant_approuve else "approbation.refuser"]
        finally:
            reprendre.set()
            if perdant.ident is not None:
                perdant.join(10)
            event.remove(moteur, "before_cursor_execute", avant)
            event.remove(moteur, "after_cursor_execute", apres)
            stockage.liberer()
            assert not perdant.is_alive(), "décision fictive non arrêtée"
