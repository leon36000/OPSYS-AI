"""Parcours fictifs du préparateur CSV borné R23."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from starlette.requests import Request
from tests.test_console_fusion_operationnelle import (
    KEY,
    OWNER,
    _corps,
    _csrf,
    _csv,
    _factures,
)

from opsys import fusion_csv, identite, stockage
from opsys.stockage.schema import FUSION_LIGNES, FUSION_LOTS, FUSION_QUOTA

pytest_plugins = ["tests.test_console_fusion_operationnelle"]


def _creer_lot(client, csrf, *, mutation_id: str, contenu: bytes):
    response = client.post(
        "/api/fusion-operationnelle/lots",
        json=_corps(mutation_id, contenu),
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 201, response.text
    return response.json()["lot"]


def test_route_preparateur_api_avance_un_lot(client_fusion):
    _factures(101)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-api-fictif", contenu=_csv(101))

    response = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": lot["revision"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lot"]["curseur"] == 101
    assert body["preparation"]["tranches_executees"] == 2
    assert body["preparation"]["limite_tranches"] == 20
    assert "montant" not in response.text and "DETAIL-CLIENT-SECRET" not in response.text


def test_formulaire_html_prepare_et_liste_presente_action_principale(client_fusion):
    _factures(2)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-html-fictif", contenu=_csv(2))
    liste = client_fusion.get("/fusion-operationnelle")
    assert "Préparer le lot" in liste.text
    assert "potentielles" in liste.text
    response = client_fusion.post(
        f"/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
        data={"csrf": csrf, "revision_attendue": "1"},
    )
    assert response.status_code == 200, response.text
    assert "Progression des lignes" in response.text
    assert "DETAIL-CLIENT-SECRET" not in response.text and "100.00" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("revision", [True, 1.0, "1", 0, -1])
def test_revision_non_stricte_refuse_avant_travail(client_fusion, revision):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id=f"revision-invalide-{type(revision).__name__}-fictif",
                     contenu=_csv())
    response = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": revision},
    )
    assert response.status_code == 400
    assert client_fusion.get(f"/api/fusion-operationnelle/lots/{lot['lot_id']}").json()["lot"]["curseur"] == 0


def test_json_preparation_ferme_doublons_et_query_sans_mutation(client_fusion):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-ferme-fictif", contenu=_csv())
    path = f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer"
    duplicate = client_fusion.post(path, headers={"x-csrf-token": csrf, "content-type": "application/json"},
                                  content='{"revision_attendue":1,"revision_attendue":1}')
    extra = client_fusion.post(path, headers={"x-csrf-token": csrf},
                               json={"revision_attendue": 1, "tranches": 999})
    query = client_fusion.post(path + "?limite=20", headers={"x-csrf-token": csrf},
                               json={"revision_attendue": 1})
    assert [duplicate.status_code, extra.status_code, query.status_code] == [400, 400, 400]
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_LOTS.c.curseur).where(FUSION_LOTS.c.lot_id == lot["lot_id"])).scalar_one() == 0
        assert cnx.execute(select(FUSION_LIGNES).where(FUSION_LIGNES.c.lot_id == lot["lot_id"])).first() is None


def test_terminal_est_noop_cas_strict_et_resume_sans_donnees_comptables(client_fusion):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-terminal-fictif", contenu=_csv())
    terminal = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    revision = terminal.json()["lot"]["revision"]
    prepared = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": revision})
    assert prepared.status_code == 200
    assert prepared.json()["preparation"]["tranches_executees"] == 0
    assert prepared.json()["preparation"]["arret"] == "TERMINAL"
    assert "compte_interne_id" not in prepared.text and "source_sha256" not in prepared.text
    stale = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                               headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert stale.status_code == 409


def test_plafond_service_exactement_vingt_tranches(monkeypatch):
    calls = []
    cursor = {"revision": 1, "curseur": 0, "statut": "EN_COURS", "lot_id": "lot-fictif",
              "total_lignes": 2000, "nombre_propositions": 0}

    def summary(factory, actor, lot_id, revision):
        assert revision == cursor["revision"]
        return dict(cursor)

    def process(factory, actor, lot_id, revision):
        calls.append(revision)
        cursor.update(revision=revision + 1, curseur=cursor["curseur"] + 100)
        return dict(cursor)

    ticks = iter([0.0] + [n * 0.01 for n in range(1, 1000)])
    monkeypatch.setattr(fusion_csv, "_resume_preparation", summary)
    monkeypatch.setattr(fusion_csv, "traiter", process)
    monkeypatch.setattr(fusion_csv, "_monotonic", lambda: next(ticks))
    resultat = fusion_csv.preparer(None, "admin-fictif", "lot-fictif", 1, threading.Event())
    assert len(calls) == 20
    assert resultat["preparation"]["limite_tranches"] == 20
    assert resultat["lot"]["curseur"] == 2000


@pytest.mark.parametrize("budget,vals,expected", [
    ("tranche", [0.0, 0.0, 0.0, 2.1, 2.1], "BUDGET_TRANCHE"),
    ("total", [0.0, 0.0, 0.0, 1.0, 1.0, 8.1, 8.1], "BUDGET_TOTAL"),
])
def test_budgets_cooperatifs_sarreter_apres_un_commit(monkeypatch, budget, vals, expected):
    state = {"lot_id": "lot-fictif", "statut": "EN_COURS", "revision": 1,
             "curseur": 0, "total_lignes": 200, "nombre_propositions": 0}
    def summary(factory, actor, lot_id, revision):
        return dict(state)
    def process(factory, actor, lot_id, revision):
        state.update(revision=revision + 1, curseur=100)
        return dict(state)
    ticks = iter(vals)
    monkeypatch.setattr(fusion_csv, "_resume_preparation", summary)
    monkeypatch.setattr(fusion_csv, "traiter", process)
    monkeypatch.setattr(fusion_csv, "_monotonic", lambda: next(ticks))
    result = fusion_csv.preparer(None, "admin-fictif", "lot-fictif", 1, threading.Event())
    assert result["lot"]["curseur"] == 100
    assert result["preparation"]["tranches_executees"] == 1
    assert result["preparation"]["arret"] == expected


def test_concurrence_meme_revision_un_seul_gagnant_sans_lignes_dupliquees(client_fusion):
    _factures(101)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-concurrent-fictif", contenu=_csv(101))
    barrier = threading.Barrier(2)

    def prepare():
        barrier.wait(timeout=3)
        try:
            return fusion_csv.preparer(stockage.transaction, OWNER, lot["lot_id"], 1, threading.Event())
        except fusion_csv.FusionErreur as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: prepare(), range(2)))
    successes = [item for item in results if isinstance(item, dict)]
    failures = [item for item in results if isinstance(item, fusion_csv.FusionErreur)]
    assert len(successes) == 1 and len(failures) == 1
    assert failures[0].code in {"CONFLIT_REVISION", "STOCKAGE_OCCUPE"}
    with stockage.transaction() as cnx:
        numbers = cnx.execute(select(FUSION_LIGNES.c.numero).where(
            FUSION_LIGNES.c.lot_id == lot["lot_id"]
        )).scalars().all()
        assert len(numbers) == len(set(numbers)) == 101


def test_route_api_prepare_deux_mille_lignes_reelles_en_vingt_tranches(client_fusion, monkeypatch):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-2000-fictif", contenu=_csv(2000))
    monkeypatch.setattr(fusion_csv, "_monotonic", lambda: 0.0)
    response = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert response.status_code == 200, response.text
    assert response.json()["lot"]["curseur"] == 2000
    assert response.json()["preparation"]["tranches_executees"] == 20


def test_snapshot_m5_mutate_entre_transactions_arrete_et_provenance_etat_obsolete(client_fusion, monkeypatch):
    from m5_financecore import registre as registre_m5

    _factures(101)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-mutation-snapshot-fictif", contenu=_csv(101))
    traiter = fusion_csv.traiter
    mutations = []

    def muter_apres_commit(*args, **kwargs):
        resultat = traiter(*args, **kwargs)
        if not mutations:
            mutations.append(1)
            with stockage.transaction():
                registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
                registre.ajouter({
                    "type_entree": "facture_creee", "facture_id": "FAC-SNAPSHOT-MODIFIEE-FICTIVE",
                    "statut": "BROUILLON", "montant_apres_taxes": Decimal("3.00"),
                    "horodatage": "2026-09-30T12:00:00+00:00",
                })
        return resultat

    monkeypatch.setattr(fusion_csv, "traiter", muter_apres_commit)
    response = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert response.status_code == 200
    saved = response.json()["lot"]
    assert saved["statut"] == "SNAPSHOT_OBSOLETE" and saved["curseur"] == 100
    assert saved["nombre_propositions"] == 0


@pytest.mark.parametrize("probleme,code_http,code", [
    ("cle", 503, "CLE_INDISPONIBLE"), ("quota", 409, "QUOTA_ATTEINT"),
])
def test_erreur_cle_ou_quota_apres_tranche_ne_retourne_pas_resume_et_provenance(
    client_fusion, monkeypatch, probleme, code_http, code,
):
    _factures(101)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id=f"preparateur-{probleme}-apres-commit-fictif", contenu=_csv(101))
    traiter = fusion_csv.traiter
    calls = []

    def changer_apres_commit(*args, **kwargs):
        resultat = traiter(*args, **kwargs)
        if not calls:
            calls.append(1)
            if probleme == "cle":
                monkeypatch.delenv("OPSYS_INGESTION_CLE")
            else:
                with stockage.transaction() as cnx:
                    cnx.execute(update(FUSION_QUOTA).values(octets_cipher=fusion_csv.QUOTA_CIPHER_MAX))
        return resultat

    monkeypatch.setattr(fusion_csv, "traiter", changer_apres_commit)
    response = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert response.status_code == code_http and code in response.text
    assert "curseur" not in response.text and "nombre_propositions" not in response.text
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot["lot_id"])).one()
        assert saved.curseur == 100
        numbers = cnx.execute(select(FUSION_LIGNES.c.numero).where(
            FUSION_LIGNES.c.lot_id == lot["lot_id"]
        )).scalars().all()
        assert len(numbers) == len(set(numbers)) == 100
        from m10_memoire import provenance_documentaire
        assert provenance_documentaire.lire(stockage.maillons("m10-memoire", "documents"), lot["lot_id"]) is None


def test_snapshot_obsolete_resume_masque_propositions(client_fusion, monkeypatch):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-snapshot-fictif", contenu=_csv())
    monkeypatch.setattr(fusion_csv, "_verifier_snapshot", lambda _: False)
    response = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert response.status_code == 200
    assert response.json()["lot"]["statut"] == "SNAPSHOT_OBSOLETE"
    assert response.json()["lot"]["nombre_propositions"] == 0
    assert response.json()["preparation"]["tranches_executees"] == 0


def test_route_prepare_revalide_snapshot_apres_retour_worker(client_fusion, monkeypatch):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-snapshot-final-fictif", contenu=_csv())

    def faux_preparateur(factory, actor, lot_id, revision, stop_event):
        return {"lot": {"lot_id": lot_id, "statut": "EN_COURS", "revision": revision,
                         "curseur": 0, "total_lignes": 1, "nombre_propositions": 1},
                "preparation": {"tranches_executees": 0, "limite_tranches": 20,
                                "duree_ms": 0, "arret": "BUDGET_TOTAL"}}

    monkeypatch.setattr(fusion_csv, "preparer", faux_preparateur)
    monkeypatch.setattr(fusion_csv, "_verifier_snapshot", lambda _: False)
    response = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert response.status_code == 200
    assert response.json()["lot"]["statut"] == "SNAPSHOT_OBSOLETE"
    assert response.json()["lot"]["nombre_propositions"] == 0


def test_route_revalide_role_apres_retour_worker(client_fusion, monkeypatch):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-role-final-fictif", contenu=_csv())

    async def retire_pendant_retour(request, factory, actor, lot_id, revision):
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, OWNER, "admin")
            identite.retirer_role(cnx, OWNER, "nathan_owner")
            identite.ajouter_role(cnx, OWNER, "employee")
        return {"lot": {"lot_id": lot_id, "statut": "PROPOSITIONS", "revision": revision,
                         "curseur": 1, "total_lignes": 1, "nombre_propositions": 1},
                "preparation": {"tranches_executees": 1, "limite_tranches": 20,
                                "duree_ms": 1, "arret": "TERMINAL"}}

    from opsys.console import fusion_ui
    monkeypatch.setattr(fusion_ui, "_executer_preparation", retire_pendant_retour)
    response = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert response.status_code == 403
    assert "curseur" not in response.text and "nombre_propositions" not in response.text


def test_formulaire_sans_csrf_ou_champ_duplique_refuse(client_fusion):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-csrf-fictif", contenu=_csv())
    path = f"/fusion-operationnelle/lots/{lot['lot_id']}/preparer"
    no_csrf = client_fusion.post(path, data={"revision_attendue": "1"})
    duplicate = client_fusion.post(path, content=f"csrf={csrf}&csrf={csrf}&revision_attendue=1",
                                  headers={"content-type": "application/x-www-form-urlencoded"})
    assert no_csrf.status_code == 400
    assert duplicate.status_code == 400
    current = client_fusion.get(f"/api/fusion-operationnelle/lots/{lot['lot_id']}").json()["lot"]
    assert current["curseur"] == 0


@pytest.mark.parametrize("path,body", [
    ("/api/fusion-operationnelle/lots/{id}/preparer", "json"),
    ("/fusion-operationnelle/lots/{id}/preparer", "form"),
])
def test_route_deconnexion_pose_evenement_et_nattache_pas_le_worker(client_fusion, monkeypatch, path, body):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id=f"deconnexion-{body}-fictif", contenu=_csv())
    observed = threading.Event()
    finished = threading.Event()

    def fake_preparer(factory, actor, lot_id, revision, stop_event):
        assert stop_event.wait(2)
        observed.set()
        finished.set()
        return {"lot": {"lot_id": lot_id, "statut": "EN_COURS", "revision": revision,
                         "curseur": 0, "total_lignes": 1, "nombre_propositions": 0},
                "preparation": {"tranches_executees": 0, "limite_tranches": 20,
                                "duree_ms": 0, "arret": "ARRET_DEMANDE"}}

    async def disconnected(self):
        return True

    monkeypatch.setattr(fusion_csv, "preparer", fake_preparer)
    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    endpoint = path.format(id=lot["lot_id"])
    if body == "json":
        response = client_fusion.post(endpoint, json={"revision_attendue": 1}, headers={"x-csrf-token": csrf})
    else:
        response = client_fusion.post(endpoint, data={"csrf": csrf, "revision_attendue": "1"})
    assert response.status_code == 200, response.text
    assert observed.is_set() and finished.is_set()


def test_annulation_route_draine_le_worker_et_signal_arret(monkeypatch):
    started = threading.Event()
    finished = threading.Event()
    observed = threading.Event()

    def fake_preparer(factory, actor, lot_id, revision, stop_event):
        started.set()
        while not stop_event.wait(0.01):
            pass
        observed.set()
        finished.set()
        return {}

    async def connected(self):
        return False

    async def scenario():
        request = SimpleNamespace(is_disconnected=lambda: connected(None))
        monkeypatch.setattr(fusion_csv, "preparer", fake_preparer)
        task = asyncio.create_task(fusion_csv_ui._executer_preparation(request, None, "admin", "lot", 1))
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    from opsys.console import fusion_ui as fusion_csv_ui
    asyncio.run(scenario())
    assert observed.is_set() and finished.is_set()


def test_tranche_sans_progression_refuse_sans_boucler(monkeypatch):
    state = {"lot_id": "lot-fictif", "statut": "EN_COURS", "revision": 1,
             "curseur": 0, "total_lignes": 10, "nombre_propositions": 0}
    calls = []
    monkeypatch.setattr(fusion_csv, "_resume_preparation", lambda *args: dict(state))

    def no_progress(*args):
        calls.append(1)
        return dict(state)

    monkeypatch.setattr(fusion_csv, "traiter", no_progress)
    with pytest.raises(fusion_csv.FusionErreur) as caught:
        fusion_csv.preparer(None, "admin", "lot-fictif", 1, threading.Event())
    assert caught.value.code == "PREPARATION_SANS_PROGRESSION"
    assert len(calls) == 1


def test_stockage_sqlite_occupe_est_classe_sans_sql_supplementaire():
    calls = []

    def busy_factory():
        calls.append(1)
        raise OperationalError("statement", {}, sqlite3.OperationalError("database is locked"))

    with pytest.raises(fusion_csv.FusionErreur) as caught:
        fusion_csv.preparer(busy_factory, "admin", "lot-fictif", 1, threading.Event())
    assert caught.value.code == "STOCKAGE_OCCUPE"
    assert caught.value.statut_http == 503
    assert len(calls) == 1


def test_cle_absente_et_quota_sature_ne_retournent_aucun_resume(client_fusion, monkeypatch):
    _factures(1)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-erreurs-fictif", contenu=_csv())
    path = f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer"
    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    missing_key = client_fusion.post(path, headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert missing_key.status_code == 503 and "CLE_INDISPONIBLE" in missing_key.text
    monkeypatch.setenv("OPSYS_INGESTION_CLE", KEY)
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_QUOTA).values(octets_cipher=fusion_csv.QUOTA_CIPHER_MAX))
    full_quota = client_fusion.post(path, headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert full_quota.status_code == 409 and "QUOTA_ATTEINT" in full_quota.text
    assert "lot" not in full_quota.text and "curseur" not in full_quota.text
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot["lot_id"])).one()
        assert saved.curseur == 0
        assert cnx.execute(select(FUSION_LIGNES).where(FUSION_LIGNES.c.lot_id == lot["lot_id"])).first() is None


def test_reprise_apres_erreur_apres_commit_conserve_la_tranche_et_reutilise_parse(client_fusion, monkeypatch):
    from m5_financecore import reconciliation_bancaire_csv

    _factures(101)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-reprise-fictif", contenu=_csv(101))
    parseur = reconciliation_bancaire_csv.previsualiser_releve_csv
    appels_parseur = []

    def parser(*args, **kwargs):
        appels_parseur.append(1)
        return parseur(*args, **kwargs)

    traiter = fusion_csv.traiter
    panne_injectee = []

    def apres_commit(*args, **kwargs):
        resultat = traiter(*args, **kwargs)
        if not panne_injectee and resultat["curseur"] == 100:
            panne_injectee.append(1)
            raise fusion_csv.FusionErreur("PANNE_REPRISE_FICTIVE", "tranche persistée; reprendre", 503)
        return resultat

    monkeypatch.setattr(reconciliation_bancaire_csv, "previsualiser_releve_csv", parser)
    monkeypatch.setattr(fusion_csv, "traiter", apres_commit)
    path = f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer"
    failed = client_fusion.post(path, headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert failed.status_code == 503 and "curseur" not in failed.text
    current = client_fusion.get(f"/api/fusion-operationnelle/lots/{lot['lot_id']}").json()["lot"]
    assert current["curseur"] == 100
    resumed = client_fusion.post(path, headers={"x-csrf-token": csrf},
                                 json={"revision_attendue": current["revision"]})
    assert resumed.status_code == 200 and resumed.json()["lot"]["curseur"] == 101
    assert len(appels_parseur) == 1


def test_retrait_role_apres_commit_refuse_reponse_et_garde_progression(client_fusion, monkeypatch):
    _factures(101)
    csrf = _csrf(client_fusion)
    lot = _creer_lot(client_fusion, csrf, mutation_id="preparateur-retrait-fictif", contenu=_csv(101))
    traiter = fusion_csv.traiter
    calls = []

    def retirer_apres_premiere_tranche(*args, **kwargs):
        resultat = traiter(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1 and resultat["curseur"] == 100:
            with stockage.transaction() as cnx:
                identite.retirer_role(cnx, OWNER, "admin")
                identite.retirer_role(cnx, OWNER, "nathan_owner")
                identite.ajouter_role(cnx, OWNER, "employee")
        return resultat

    monkeypatch.setattr(fusion_csv, "traiter", retirer_apres_premiere_tranche)
    response = client_fusion.post(f"/api/fusion-operationnelle/lots/{lot['lot_id']}/preparer",
                                  headers={"x-csrf-token": csrf}, json={"revision_attendue": 1})
    assert response.status_code == 403
    assert response.json() == {"detail": "accès Fusion opérationnelle refusé"}
    with stockage.transaction() as cnx:
        saved_cursor = cnx.execute(select(FUSION_LOTS.c.curseur).where(
            FUSION_LOTS.c.lot_id == lot["lot_id"]
        )).scalar_one()
        assert saved_cursor == 100
        assert cnx.execute(select(FUSION_LIGNES.c.numero).where(FUSION_LIGNES.c.lot_id == lot["lot_id"])).all()
