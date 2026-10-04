from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import select

from opsys import admission_agents, agents, identite, jetons


def _setup(session, departements_demo, *, budget=100, budget_mois=None):
    with session() as cnx:
        identite.creer_personne(cnx, "admission-admin", "Administrateur", "test-password-admission-1234", ["admin"])
        agents.creer(
            cnx,
            departements_demo,
            {
                "id": "m09-admission",
                "departement": "m09-demo",
                "responsabilite": "Préparer les analyses.",
                "palier_modele": "standard",
                "outils": ["m9_additionner"],
                "budget_jour": budget,
                "budget_mois": budget_mois if budget_mois is not None else budget * 10,
                "limite_tours": 4,
                "limite_reessais": 1,
                "limite_concurrence": 2,
                "declencheurs": [{"type": "manuel"}],
            },
            par="admission-admin",
            mutation_id="profile-create-0001",
        )
        agents.definir_actif(
            cnx,
            "m09-admission",
            departements_demo,
            True,
            par="admission-admin",
            mutation_id="profile-activate-0001",
            revision_attendue=1,
        )


def _policy(session, *, day=100, month=1000):
    with session() as cnx:
        admission_agents.configurer_plafonds_entreprise(
            cnx,
            day,
            month,
            par="admission-admin",
            revision_attendue=0,
        )


def _reserve(cnx, departements_demo, execution_id, key, tokens, *, tours=1, reessais=0):
    return admission_agents.reserver(
        cnx,
        "m09-admission",
        departements_demo,
        execution_id,
        key,
        tokens,
        tours=tours,
        reessais=reessais,
    )


@pytest.fixture
def postgres_session(opsys_home, monkeypatch):
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv("OPSYS_BASE_URL", url)
        from opsys import stockage

        stockage.migrer()
        try:
            yield stockage.transaction
        finally:
            stockage.liberer()


def test_refuse_ferme_si_plafond_entreprise_non_configure(session, departements_demo):
    _setup(session, departements_demo)
    with session() as cnx, pytest.raises(admission_agents.AdmissionRefusee, match="plafond entreprise"):
        _reserve(cnx, departements_demo, "execution-0001", "call-key-0001", 20)


def test_aggregat_usage_externe_superieur_i64_refuse_sans_overflow_sqlite(session, departements_demo):
    from datetime import date

    from opsys.stockage.schema import USAGE_TOKENS

    _setup(session, departements_demo)
    _policy(session)
    maximum = (1 << 63) - 1
    with session() as cnx:
        for modele in ("fournisseur-a", "fournisseur-b"):
            cnx.execute(USAGE_TOKENS.insert().values(
                jour=date.today().isoformat(), departement="m09-demo", modele=modele,
                appels=1, tokens_entree=maximum, tokens_sortie=0, tokens_cache_lus=0,
            ))
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget"):
            _reserve(cnx, departements_demo, "usage-overflow-run", "usage-overflow-key", 1)


def test_conciliation_refuse_overflow_ledger_sans_modifier_reservation_ni_historique(session, departements_demo):
    from datetime import date

    from opsys.stockage.schema import USAGE_TOKENS

    _setup(session, departements_demo)
    _policy(session)
    maximum = (1 << 63) - 1
    with session() as cnx:
        reservation = _reserve(cnx, departements_demo, "ledger-overflow-run", "ledger-overflow-key", 1)
        cnx.execute(USAGE_TOKENS.insert().values(
            jour=date.today().isoformat(), departement="m09-demo", modele="agent:m09-admission",
            appels=1, tokens_entree=maximum, tokens_sortie=0, tokens_cache_lus=0,
        ))
        with pytest.raises(admission_agents.AdmissionRefusee, match="compteur d'usage"):
            admission_agents.concilier(cnx, reservation["id"], 1)
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id="m09-admission")
        history = admission_agents.historique(cnx, reservation["id"])
    assert current["statut"] == "reservee" and current["tokens_reels"] is None
    assert len(history) == 1


def test_conciliation_upsert_returning_met_a_jour_une_ligne_sqlite_existante(session, departements_demo):
    from datetime import date

    from opsys.stockage.schema import USAGE_TOKENS

    _setup(session, departements_demo)
    _policy(session)
    with session() as cnx:
        cnx.execute(USAGE_TOKENS.insert().values(
            jour=date.today().isoformat(), departement="m09-demo", modele="agent:m09-admission",
            appels=1, tokens_entree=4, tokens_sortie=0, tokens_cache_lus=0,
        ))
        reservation = _reserve(cnx, departements_demo, "ledger-conflict-run", "ledger-conflict-key", 1)
        final = admission_agents.concilier(cnx, reservation["id"], 3)
        row = cnx.execute(
            select(USAGE_TOKENS.c.appels, USAGE_TOKENS.c.tokens_entree).where(
                USAGE_TOKENS.c.modele == "agent:m09-admission"
            )
        ).one()
    assert final["statut"] == "conciliee"
    assert tuple(row) == (2, 7)


def test_reservation_idempotente_bornes_reconciliation_et_traces(session, departements_demo):
    _setup(session, departements_demo)
    _policy(session)
    with session() as cnx:
        first = _reserve(cnx, departements_demo, "execution-0002", "call-key-0002", 70, tours=3)
        replay = _reserve(cnx, departements_demo, "execution-0002", "call-key-0002", 70, tours=3)
        assert replay == first
        with pytest.raises(ValueError, match="idempotence"):
            _reserve(cnx, departements_demo, "execution-0002", "call-key-0002", 71, tours=3)
        with pytest.raises(admission_agents.AdmissionRefusee, match="tours"):
            _reserve(cnx, departements_demo, "execution-0003", "call-key-0003", 1, tours=5)
        with pytest.raises(admission_agents.AdmissionRefusee, match="reessai"):
            _reserve(cnx, departements_demo, "execution-0004", "call-key-0004", 1, reessais=2)
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget"):
            _reserve(cnx, departements_demo, "execution-0005", "call-key-0005", 31)
        final = admission_agents.concilier(cnx, first["id"], 65)
        assert final["statut"] == "conciliee" and final["tokens_reels"] == 65
        assert admission_agents.concilier(cnx, first["id"], 65) == final
        assert len(admission_agents.historique(cnx, first["id"])) == 2


def test_concurrence_plafond_entreprise_serialize_deux_demandes(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session, day=100, month=1000)
    with session() as cnx:
        agents.creer(
            cnx,
            departements_demo,
            {
                "id": "m09-admission-2",
                "departement": "m09-demo",
                "responsabilite": "Relire les analyses.",
                "palier_modele": "standard",
                "outils": ["m9_additionner"],
                "budget_jour": 100,
                "budget_mois": 1000,
                "limite_tours": 4,
                "limite_reessais": 1,
                "limite_concurrence": 2,
                "declencheurs": [{"type": "manuel"}],
            },
            par="admission-admin",
            mutation_id="profile-create-0002",
        )
        agents.definir_actif(
            cnx,
            "m09-admission-2",
            departements_demo,
            True,
            par="admission-admin",
            mutation_id="profile-activate-0002",
            revision_attendue=1,
        )

    def tenter(agent_id: str, key: str):
        with session() as cnx:
            return admission_agents.reserver(cnx, agent_id, departements_demo, key, key, 60, tours=1, reessais=0)

    def resultat(agent_id: str, key: str):
        try:
            return tenter(agent_id, key)
        except admission_agents.AdmissionRefusee as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        futurs = [
            pool.submit(resultat, "m09-admission", "parallel-call-01"),
            pool.submit(resultat, "m09-admission-2", "parallel-call-02"),
        ]
        reponses = [futur.result() for futur in futurs]
    admises = [r for r in reponses if isinstance(r, dict)]
    refusees = [r for r in reponses if isinstance(r, admission_agents.AdmissionRefusee)]
    assert len(admises) == len(refusees) == 1
    assert "budget" in str(refusees[0])


def test_liberer_permet_une_nouvelle_reservation_et_limite_concurrence(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session)
    with session() as cnx:
        first = _reserve(cnx, departements_demo, "execution-0006", "call-key-0006", 10)
        second = _reserve(cnx, departements_demo, "execution-0007", "call-key-0007", 10)
        with pytest.raises(admission_agents.AdmissionRefusee, match="concurrence"):
            _reserve(cnx, departements_demo, "execution-0008", "call-key-0008", 10)
        liberee = admission_agents.liberer(cnx, first["id"], raison="échec avant appel fournisseur")
        assert liberee["statut"] == "liberee"
        third = _reserve(cnx, departements_demo, "execution-0008", "call-key-0008", 10)
        assert third["id"] != second["id"]


def test_limites_jour_departement_et_mois_agent_apres_conciliation(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session, day=1000, month=20000)
    with session() as cnx:
        first = _reserve(cnx, departements_demo, "execution-0009", "call-key-0009", 80)
        admission_agents.concilier(cnx, first["id"], 80)
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget"):
            _reserve(cnx, departements_demo, "execution-0010", "call-key-0010", 21)


def test_retry_et_tours_sont_cumules_par_execution(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session)
    with session() as cnx:
        _reserve(cnx, departements_demo, "execution-retry-1", "retry-attempt-000", 5, tours=3)
        with pytest.raises(admission_agents.AdmissionRefusee, match="tours cumulée"):
            _reserve(cnx, departements_demo, "execution-retry-1", "retry-attempt-001", 5, tours=2, reessais=1)
        second = _reserve(cnx, departements_demo, "execution-retry-1", "retry-attempt-001", 5, tours=1, reessais=1)
        assert second["reessais"] == 1
        with pytest.raises(admission_agents.AdmissionRefusee, match="reessais"):
            _reserve(cnx, departements_demo, "execution-retry-1", "retry-attempt-002", 5, tours=1, reessais=2)


def test_depassement_reel_est_trace_et_bloque_les_admissions_suivantes(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session, day=100, month=1000)
    with session() as cnx:
        reservation = _reserve(cnx, departements_demo, "execution-overrun", "overrun-key-0001", 60)
        soldee = admission_agents.concilier(cnx, reservation["id"], 75)
        assert soldee["depassement_plafond"] is True and soldee["tokens_reels"] == 75
        evenement = admission_agents.historique(cnx, reservation["id"])[-1]
        assert "dépassement" in evenement["raison"]
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget"):
            _reserve(cnx, departements_demo, "execution-after-overrun", "overrun-key-0002", 26)


def test_usage_departement_existant_deducted_before_agent_reservation(session, departements_demo):
    _setup(session, departements_demo, budget=500)
    _policy(session, day=1000, month=20000)
    with session() as cnx:
        jetons.enregistrer_usage(cnx, "m09-demo", "modele-existant", {"input_tokens": 950})
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget departement insuffisant"):
            _reserve(cnx, departements_demo, "execution-department", "department-key-0001", 51)


def test_plafond_entreprise_requires_admin_and_revision_compare_swap(session, departements_demo):
    with session() as cnx:
        identite.creer_personne(cnx, "admission-staff", "Employé", "test-password-staff-2345", ["employee"])
        with pytest.raises(PermissionError, match="administrateur actif"):
            admission_agents.configurer_plafonds_entreprise(cnx, 100, 1000, par="admission-staff", revision_attendue=0)
        identite.creer_personne(cnx, "admission-admin", "Administrateur", "test-password-admin-2345", ["admin"])
        assert (
            admission_agents.configurer_plafonds_entreprise(cnx, 100, 1000, par="admission-admin", revision_attendue=0)[
                "revision"
            ]
            == 1
        )
        with pytest.raises(ValueError, match="conflit de révision"):
            admission_agents.configurer_plafonds_entreprise(cnx, 200, 2000, par="admission-admin", revision_attendue=0)


def test_admission_revalide_actif_durable_du_profil(session, departements_demo):
    _setup(session, departements_demo)
    _policy(session)
    with session() as cnx:
        agents.definir_actif(
            cnx,
            "m09-admission",
            departements_demo,
            False,
            par="admission-admin",
            mutation_id="profile-deactivate-1",
            revision_attendue=2,
        )
        with pytest.raises(admission_agents.AdmissionRefusee, match="inactif"):
            _reserve(cnx, departements_demo, "execution-inactive", "inactive-key-0001", 10)


def test_postgresql_concurrent_agents_ne_depassent_pas_le_plafond_global(postgres_session, departements_demo):
    _setup(postgres_session, departements_demo, budget=100)
    _policy(postgres_session, day=100, month=1000)
    with postgres_session() as cnx:
        agents.creer(
            cnx,
            departements_demo,
            {
                "id": "m09-pg-second",
                "departement": "m09-demo",
                "responsabilite": "Relire.",
                "palier_modele": "standard",
                "outils": ["m9_additionner"],
                "budget_jour": 100,
                "budget_mois": 1000,
                "limite_tours": 4,
                "limite_reessais": 1,
                "limite_concurrence": 2,
                "declencheurs": [{"type": "manuel"}],
            },
            par="admission-admin",
            mutation_id="pg-create-profile-1",
        )
        agents.definir_actif(
            cnx,
            "m09-pg-second",
            departements_demo,
            True,
            par="admission-admin",
            mutation_id="pg-activate-profile-1",
            revision_attendue=1,
        )

    def result(agent_id: str, key: str):
        try:
            with postgres_session() as cnx:
                return admission_agents.reserver(cnx, agent_id, departements_demo, key, key, 60, tours=1, reessais=0)
        except admission_agents.AdmissionRefusee as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(result, "m09-admission", "pg-parallel-call-01"),
            pool.submit(result, "m09-pg-second", "pg-parallel-call-02"),
        ]
        results = [future.result() for future in futures]
    assert sum(isinstance(value, dict) for value in results) == 1
    assert sum(isinstance(value, admission_agents.AdmissionRefusee) for value in results) == 1


def _scenario_admission_64_bits(session, departements_demo):
    from opsys.stockage.schema import USAGE_TOKENS

    budget_jour = 4_000_000_000
    budget_mois = 8_000_000_000
    departement = departements_demo["m09-demo"]
    departements_64 = {
        **departements_demo,
        "m09-demo": replace(
            departement,
            budget=replace(departement.budget, tokens_jour=budget_jour, tokens_mois=budget_mois),
        ),
    }
    _setup(session, departements_64, budget=budget_jour, budget_mois=budget_mois)
    _policy(session, day=budget_jour, month=budget_mois)
    with session() as cnx:
        reservation = _reserve(
            cnx, departements_64, "int64-run", "int64-key", 3_000_000_000
        )
        final = admission_agents.concilier(cnx, reservation["id"], 3_500_000_000)
        ledger = cnx.execute(
            select(USAGE_TOKENS.c.tokens_entree).where(USAGE_TOKENS.c.modele == "agent:m09-admission")
        ).scalar_one()
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget"):
            _reserve(cnx, departements_64, "int64-run-next", "int64-key-next", 1_000_000_000)
    return final, ledger


def test_sqlite_admission_conciliation_et_ledger_depassent_32_bits(session, departements_demo):
    final, ledger = _scenario_admission_64_bits(session, departements_demo)
    assert final["statut"] == "conciliee"
    assert final["tokens_reels"] == 3_500_000_000
    assert ledger == 3_500_000_000


def test_postgresql_admission_conciliation_et_ledger_depassent_32_bits(postgres_session, departements_demo):
    final, ledger = _scenario_admission_64_bits(postgres_session, departements_demo)
    assert final["statut"] == "conciliee"
    assert final["tokens_reels"] == 3_500_000_000
    assert ledger == 3_500_000_000


def test_postgresql_conciliation_overrun_serialisee_avant_nouvelle_reservation(
    postgres_session,
    departements_demo,
    monkeypatch,
):
    """Un réel supérieur à la réserve doit être visible avant le prochain calcul de budget."""
    _setup(postgres_session, departements_demo, budget=100)
    _policy(postgres_session, day=100, month=1000)
    with postgres_session() as cnx:
        first = _reserve(cnx, departements_demo, "execution-race-01", "race-key-0001", 60)
        agents.creer(
            cnx,
            departements_demo,
            {
                "id": "m09-admission-race",
                "departement": "m09-demo",
                "responsabilite": "Contrôler le budget global.",
                "palier_modele": "standard",
                "outils": ["m9_additionner"],
                "budget_jour": 100,
                "budget_mois": 1000,
                "limite_tours": 4,
                "limite_reessais": 1,
                "limite_concurrence": 2,
                "declencheurs": [{"type": "manuel"}],
            },
            par="admission-admin",
            mutation_id="race-create-profile-1",
        )
        agents.definir_actif(
            cnx,
            "m09-admission-race",
            departements_demo,
            True,
            par="admission-admin",
            mutation_id="race-activate-profile-1",
            revision_attendue=1,
        )

    conciliation_en_transaction = Event()
    laisser_concilier = Event()
    budget_calcule = Event()
    laisser_reserver = Event()
    historiser_original = admission_agents._historiser
    borne_originale = admission_agents._borne

    def historiser_pause(cnx, reservation_id, evenement, tokens, raison):
        historiser_original(cnx, reservation_id, evenement, tokens, raison)
        if evenement == "conciliee":
            conciliation_en_transaction.set()
            assert laisser_concilier.wait(timeout=10)

    def borne_pause(cnx, *, budget, dimension, cle, debut, fin, mois):
        disponible = borne_originale(
            cnx,
            budget=budget,
            dimension=dimension,
            cle=cle,
            debut=debut,
            fin=fin,
            mois=mois,
        )
        if dimension == "entreprise" and debut == fin:
            budget_calcule.set()
            assert laisser_reserver.wait(timeout=10)
        return disponible

    monkeypatch.setattr(admission_agents, "_historiser", historiser_pause)
    monkeypatch.setattr(admission_agents, "_borne", borne_pause)

    def concilier():
        with postgres_session() as cnx:
            return admission_agents.concilier(cnx, first["id"], 80)

    def tenter_reserver():
        try:
            with postgres_session() as cnx:
                return admission_agents.reserver(
                    cnx,
                    "m09-admission-race",
                    departements_demo,
                    "execution-race-02",
                    "race-key-0002",
                    21,
                    tours=1,
                    reessais=0,
                )
        except admission_agents.AdmissionRefusee as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_conciliation = pool.submit(concilier)
        assert conciliation_en_transaction.wait(timeout=10)
        future_reservation = pool.submit(tenter_reserver)
        # Sans verrou de ledger dans concilier(), l'agrégat voit encore 60 réservés et calcule
        # 40 disponibles pendant que la conciliation à 80 est non commitée. Avec le verrou, la
        # réservation attend la conciliation et ne calcule qu'ensuite (20 disponibles).
        budget_calcule.wait(timeout=1)
        laisser_concilier.set()
        resultat_conciliation = future_conciliation.result(timeout=10)
        laisser_reserver.set()
        resultat_reservation = future_reservation.result(timeout=10)

    assert resultat_conciliation["tokens_reels"] == 80
    assert isinstance(resultat_reservation, admission_agents.AdmissionRefusee)
    assert "budget entreprise insuffisant" in str(resultat_reservation)


def _reserve_runtime_cycle(
    cnx,
    departements_demo,
    *,
    execution_id,
    cle,
    candidate_index,
    stream_ordinal,
    tokens=5,
    is_fallback_retry=None,
    attempt_id=None,
    cycle_id=None,
    reessais=None,
    revision_profil=2,
):
    is_fallback_retry = candidate_index > 0 if is_fallback_retry is None else is_fallback_retry
    attempt_id = f"{execution_id}:{candidate_index}" if attempt_id is None else attempt_id
    cycle_id = f"{attempt_id}:{stream_ordinal}" if cycle_id is None else cycle_id
    arguments = {
        "attempt_id": attempt_id,
        "cycle_id": cycle_id,
        "candidate_index": candidate_index,
        "stream_ordinal": stream_ordinal,
        "is_fallback_retry": is_fallback_retry,
        "revision_profil": revision_profil,
    }
    if reessais is not None:
        arguments["reessais"] = reessais
    return admission_agents.admettre_cycle_runtime(
        cnx,
        "m09-admission",
        departements_demo,
        execution_id,
        cle,
        tokens,
        **arguments,
    )


def test_protocol_runtime_streams_du_meme_candidat_ne_comptent_pas_comme_reessais(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session)
    with session() as cnx:
        first = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-stream-001",
            cle="stream-cycle-0-0001",
            candidate_index=0,
            stream_ordinal=0,
        )
        with pytest.raises(admission_agents.AdmissionRefusee, match="cycle déjà admis"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-stream-001",
                cle="stream-cycle-0-0001",
                candidate_index=0,
                stream_ordinal=0,
            )
        replay = admission_agents.reserver(
            cnx,
            "m09-admission",
            departements_demo,
            "run-stream-001",
            "stream-cycle-0-0001",
            5,
            tours=1,
            attempt_id="run-stream-001:0",
            cycle_id="run-stream-001:0:0",
            candidate_index=0,
            stream_ordinal=0,
            is_fallback_retry=False,
            revision_profil=2,
        )
        next_stream = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-stream-001",
            cle="stream-cycle-0-0002",
            candidate_index=0,
            stream_ordinal=1,
        )
        admission_agents.concilier(cnx, first["id"], 5)
        admission_agents.concilier(cnx, next_stream["id"], 5)
        fallback = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-stream-001",
            cle="stream-cycle-1-0000",
            candidate_index=1,
            stream_ordinal=0,
        )
        admission_agents.concilier(cnx, fallback["id"], 5)
        fallback_continuation = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-stream-001",
            cle="stream-cycle-1-0001",
            candidate_index=1,
            stream_ordinal=1,
        )
        assert replay == {key: value for key, value in first.items() if key != "accord_neuf"}
        assert first["accord_neuf"] is True and next_stream["accord_neuf"] is True
        assert first["reessais"] == next_stream["reessais"] == 0
        assert fallback["reessais"] == fallback_continuation["reessais"] == 1
        assert first["attempt_id"] == next_stream["attempt_id"] == "run-stream-001:0"
        assert first["cycle_id"] == "run-stream-001:0:0"
        assert next_stream["cycle_id"] == "run-stream-001:0:1"
        assert fallback["attempt_id"] == "run-stream-001:1"
        assert fallback["is_fallback_retry"] is True and fallback_continuation["is_fallback_retry"] is True
        assert next_stream["stream_ordinal"] == 1 and fallback_continuation["stream_ordinal"] == 1


def test_protocol_runtime_refuse_sauts_repetitions_et_intention_modifiee(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session)
    with session() as cnx:
        first = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-validation-001",
            cle="validation-cycle-0-0000",
            candidate_index=0,
            stream_ordinal=0,
        )
        with pytest.raises(admission_agents.AdmissionRefusee, match="cycle déjà admis"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-validation-001",
                cle="validation-cycle-other",
                candidate_index=0,
                stream_ordinal=0,
            )
        with pytest.raises(ValueError, match="idempotence"):
            admission_agents.reserver(
                cnx,
                "m09-admission",
                departements_demo,
                "run-validation-001",
                "validation-cycle-0-0000",
                6,
                tours=1,
                reessais=0,
                attempt_id="run-validation-001:0",
                cycle_id="run-validation-001:0:0",
                candidate_index=0,
                stream_ordinal=0,
                is_fallback_retry=False,
                revision_profil=2,
            )
        with pytest.raises(admission_agents.AdmissionRefusee, match="ordinal"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-validation-001",
                cle="validation-cycle-0-0002",
                candidate_index=0,
                stream_ordinal=2,
            )
        with pytest.raises(admission_agents.AdmissionRefusee, match="reessais"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-validation-001",
                cle="validation-cycle-2-0000",
                candidate_index=2,
                stream_ordinal=0,
            )
        with pytest.raises(admission_agents.AdmissionRefusee, match="reessai"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-validation-001",
                cle="validation-cycle-1-0000",
                candidate_index=1,
                stream_ordinal=0,
                reessais=0,
            )
        with pytest.raises(ValueError, match="fallback"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-validation-001",
                cle="validation-cycle-badflag",
                candidate_index=1,
                stream_ordinal=0,
                is_fallback_retry=False,
            )
        with pytest.raises(admission_agents.AdmissionRefusee, match="protocoles runtime/legacy"):
            _reserve(cnx, departements_demo, "run-validation-001", "legacy-in-runtime-run", 5, reessais=1)
        with pytest.raises(admission_agents.AdmissionRefusee, match="profil lié"):
            admission_agents.lire_reservation(cnx, first["id"], agent_id="m09-other")
        legacy = _reserve(cnx, departements_demo, "run-legacy-first-001", "legacy-first-cycle-0001", 5)
        with pytest.raises(admission_agents.AdmissionRefusee, match="protocoles legacy/runtime"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-legacy-first-001",
                cle="runtime-after-legacy-1",
                candidate_index=0,
                stream_ordinal=0,
            )
        with pytest.raises(admission_agents.AdmissionRefusee, match="protocoles runtime/legacy"):
            _reserve(cnx, departements_demo, "run-validation-001", "legacy-in-runtime-run", 5, reessais=1)
        with pytest.raises(admission_agents.AdmissionRefusee, match="profil lié"):
            admission_agents.lire_reservation(cnx, first["id"], agent_id="m09-other")
        legacy = _reserve(cnx, departements_demo, "run-legacy-first-001", "legacy-first-cycle-0001", 5)
        with pytest.raises(admission_agents.AdmissionRefusee, match="protocoles legacy/runtime"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-legacy-first-001",
                cle="runtime-after-legacy-1",
                candidate_index=0,
                stream_ordinal=0,
            )
        assert admission_agents.historique(cnx, first["id"])[0]["evenement"] == "reservee"
        assert legacy["statut"] == "reservee"
        assert legacy["statut"] == "reservee"


def test_protocol_runtime_limite_reessais_stable_sur_les_cycles_fallback(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session)
    with session() as cnx:
        initial = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-retry-limit-01",
            cle="retry-limit-cycle-0-0",
            candidate_index=0,
            stream_ordinal=0,
        )
        admission_agents.concilier(cnx, initial["id"], 5)
        fallback = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-retry-limit-01",
            cle="retry-limit-cycle-1-0",
            candidate_index=1,
            stream_ordinal=0,
        )
        admission_agents.concilier(cnx, fallback["id"], 5)
        continuation = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="run-retry-limit-01",
            cle="retry-limit-cycle-1-1",
            candidate_index=1,
            stream_ordinal=1,
        )
        assert continuation["reessais"] == fallback["reessais"] == 1
        admission_agents.concilier(cnx, continuation["id"], 5)
        with pytest.raises(admission_agents.AdmissionRefusee, match="limite de reessais"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="run-retry-limit-01",
                cle="retry-limit-cycle-2-0",
                candidate_index=2,
                stream_ordinal=0,
            )


def test_postgresql_runtime_cycle_fields_and_unique_cycle(postgres_session, departements_demo):
    _setup(postgres_session, departements_demo, budget=100)
    _policy(postgres_session)
    with postgres_session() as cnx:
        first = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id="pg-runtime-run-001",
            cle="pg-runtime-cycle-0000",
            candidate_index=0,
            stream_ordinal=0,
        )
        replay = admission_agents.reserver(
            cnx,
            "m09-admission",
            departements_demo,
            "pg-runtime-run-001",
            "pg-runtime-cycle-0000",
            5,
            tours=1,
            attempt_id="pg-runtime-run-001:0",
            cycle_id="pg-runtime-run-001:0:0",
            candidate_index=0,
            stream_ordinal=0,
            is_fallback_retry=False,
            revision_profil=2,
        )
        assert replay == {key: value for key, value in first.items() if key != "accord_neuf"}
        with pytest.raises(admission_agents.AdmissionRefusee, match="cycle déjà admis"):
            _reserve_runtime_cycle(
                cnx,
                departements_demo,
                execution_id="pg-runtime-run-001",
                cle="pg-runtime-cycle-other",
                candidate_index=0,
                stream_ordinal=0,
            )
        assert (
            admission_agents.lire_reservation(cnx, first["id"], agent_id="m09-admission")["cycle_id"]
            == "pg-runtime-run-001:0:0"
        )


def test_runtime_cycle_ids_support_existing_maximum_execution_id_length(session, departements_demo):
    _setup(session, departements_demo, budget=100)
    _policy(session)
    execution_id = "r" * 128
    with session() as cnx:
        row = _reserve_runtime_cycle(
            cnx,
            departements_demo,
            execution_id=execution_id,
            cle="long-run-cycle-0001",
            candidate_index=0,
            stream_ordinal=0,
        )
        assert len(row["attempt_id"]) == 130
        assert len(row["cycle_id"]) == 132


def test_postgresql_cycle_concurrent_admission_ne_delivre_quun_accord_neuf(postgres_session, departements_demo):
    _setup(postgres_session, departements_demo, budget=100)
    _policy(postgres_session)

    def admission():
        try:
            with postgres_session() as cnx:
                return _reserve_runtime_cycle(
                    cnx,
                    departements_demo,
                    execution_id="pg-runtime-duplicate-001",
                    cle="pg-runtime-duplicate-cycle",
                    candidate_index=0,
                    stream_ordinal=0,
                )
        except admission_agents.AdmissionRefusee as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = [future.result() for future in [pool.submit(admission), pool.submit(admission)]]
    grants = [result for result in resultats if isinstance(result, dict) and result.get("accord_neuf") is True]
    refus = [result for result in resultats if isinstance(result, admission_agents.AdmissionRefusee)]
    assert len(grants) == 1 and len(refus) == 1
    assert "cycle déjà admis" in str(refus[0])


def _release_runtime(cnx, row, **changes):
    arguments = {key: row[key] for key in (
        "agent_id", "execution_id", "attempt_id", "cycle_id", "candidate_index", "stream_ordinal",
    )}
    arguments["revision_profil"] = 2
    arguments.update(changes)
    return admission_agents.liberer_cycle_runtime_avant_dispatch(cnx, row["id"], **arguments)


def _runtime_before_dispatch(session, departements_demo, *, tokens=5):
    # Fictif : vraie transaction SQLite ; aucun provider n'est lancé par ce helper.
    _setup(session, departements_demo, budget=100)
    _policy(session)
    with session() as cnx:
        return _reserve_runtime_cycle(
            cnx, departements_demo, execution_id="run-pre-dispatch-001", cle="cycle-pre-dispatch-001",
            candidate_index=0, stream_ordinal=0, tokens=tokens,
        )


def test_liberation_runtime_avant_dispatch_restitue_budget_sans_usage_et_sans_readmission(session, departements_demo):
    from opsys.stockage.schema import USAGE_TOKENS

    row = _runtime_before_dispatch(session, departements_demo, tokens=80)
    with session() as cnx:
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget agent"):
            _reserve(cnx, departements_demo, "blocked-budget-run", "blocked-budget-key", 21)
        released = _release_runtime(cnx, row)
        assert released["statut"] == "liberee" and released["tokens_reels"] is None
        assert _release_runtime(cnx, row) == released
        history = admission_agents.historique(cnx, row["id"])
        assert [event["evenement"] for event in history] == ["reservee", "liberee"]
        assert history[0]["raison"] == '{"revision_profil":2,"type":"runtime_admission","version":1}'
        assert "provider non invoqué" in history[1]["raison"]
        assert cnx.execute(select(USAGE_TOKENS)).first() is None
        with pytest.raises(admission_agents.AdmissionRefusee, match="cycle déjà admis"):
            _reserve_runtime_cycle(
                cnx, departements_demo, execution_id=row["execution_id"], cle="another-key-same-cycle",
                candidate_index=0, stream_ordinal=0, tokens=80,
            )
        assert _reserve(cnx, departements_demo, "fresh-budget-run", "fresh-budget-key", 100)["statut"] == "reservee"


@pytest.mark.parametrize("changes", [
    {"agent_id": "another-profile"},
    {"execution_id": "another-run-001", "attempt_id": "another-run-001:0", "cycle_id": "another-run-001:0:0"},
    {"candidate_index": 1, "attempt_id": "run-pre-dispatch-001:1", "cycle_id": "run-pre-dispatch-001:1:0"},
    {"stream_ordinal": 1, "cycle_id": "run-pre-dispatch-001:0:1"},
    {"revision_profil": 3},
    {"candidate_index": False},
    {"stream_ordinal": True},
    {"revision_profil": True},
])
def test_liberation_runtime_refuse_autre_capture_et_bool_sans_mutation(session, departements_demo, changes):
    row = _runtime_before_dispatch(session, departements_demo)
    with session() as cnx:
        before = admission_agents.historique(cnx, row["id"])
        with pytest.raises(ValueError):
            _release_runtime(cnx, row, **changes)
        assert admission_agents.lire_reservation(cnx, row["id"], agent_id=row["agent_id"])["statut"] == "reservee"
        assert admission_agents.historique(cnx, row["id"]) == before


def test_liberation_runtime_apres_retrait_profil_ne_rearme_pas_agent(session, departements_demo):
    row = _runtime_before_dispatch(session, departements_demo)
    with session() as cnx:
        agents.definir_actif(cnx, row["agent_id"], departements_demo, False, par="admission-admin",
                            mutation_id="withdraw-before-dispatch", revision_attendue=2)
        released = _release_runtime(cnx, row)
        assert released["statut"] == "liberee"
        assert _release_runtime(cnx, row) == released
        assert [event["evenement"] for event in admission_agents.historique(cnx, row["id"])] == ["reservee", "liberee"]
        current = agents.obtenir(cnx, row["agent_id"])
        assert current["actif"] is False and current["revision"] == 3


@pytest.mark.parametrize("capture", ["absente", "ambigue"])
def test_liberation_runtime_ne_retroattribue_pas_revision_et_reprise_operateur_preservee(
    session, departements_demo, capture,
):
    from opsys.stockage.schema import AGENTS_RESERVATIONS_HISTORIQUE

    row = _runtime_before_dispatch(session, departements_demo)
    with session() as cnx:
        if capture == "absente":
            cnx.execute(AGENTS_RESERVATIONS_HISTORIQUE.update().where(
                AGENTS_RESERVATIONS_HISTORIQUE.c.reservation_id == row["id"],
            ).values(raison="enveloppe réservée avant exécution"))
        else:
            # Corruption fictive : deux captures initiales identiques ne sont pas une preuve unique.
            initial = admission_agents.historique(cnx, row["id"])[0]
            cnx.execute(AGENTS_RESERVATIONS_HISTORIQUE.insert().values(**{**initial, "id": "f" * 32}))
        before = admission_agents.historique(cnx, row["id"])
        with pytest.raises(admission_agents.AdmissionRefusee, match="preuve de capture"):
            _release_runtime(cnx, row)
        assert admission_agents.lire_reservation(cnx, row["id"], agent_id=row["agent_id"])["statut"] == "reservee"
        assert admission_agents.historique(cnx, row["id"]) == before
        # Le chemin humain/interne historique conserve son contrat ; aucune capture inventée.
        assert admission_agents.liberer(cnx, row["id"], raison="reprise opérateur fictive")["statut"] == "liberee"


def test_liberation_runtime_refuse_conciliee_et_preserve_tokens_reels(session, departements_demo):
    row = _runtime_before_dispatch(session, departements_demo)
    with session() as cnx:
        reconciled = admission_agents.concilier(cnx, row["id"], 3)
        before = admission_agents.historique(cnx, row["id"])
        with pytest.raises(ValueError, match="conciliée"):
            _release_runtime(cnx, row)
        assert admission_agents.lire_reservation(cnx, row["id"], agent_id=row["agent_id"]) == reconciled
        assert admission_agents.historique(cnx, row["id"]) == before


def test_liberation_runtime_et_historique_rollback_ensemble(session, departements_demo):
    row = _runtime_before_dispatch(session, departements_demo)
    with pytest.raises(RuntimeError, match="rollback fictif"), session() as cnx:
        _release_runtime(cnx, row)
        raise RuntimeError("rollback fictif")
    with session() as cnx:
        assert admission_agents.lire_reservation(cnx, row["id"], agent_id=row["agent_id"])["statut"] == "reservee"
        assert [event["evenement"] for event in admission_agents.historique(cnx, row["id"])] == ["reservee"]


def test_liberation_runtime_refuse_reservation_legacy_et_conciliation_historique_reste_valide(
    session, departements_demo
):
    _setup(session, departements_demo)
    _policy(session)
    with session() as cnx:
        row = _reserve(cnx, departements_demo, "legacy-run-no-dispatch", "legacy-key-no-dispatch", 5)
        before = admission_agents.historique(cnx, row["id"])
        with pytest.raises(admission_agents.AdmissionRefusee, match="capture différente"):
            admission_agents.liberer_cycle_runtime_avant_dispatch(
                cnx, row["id"], agent_id="m09-admission", execution_id=row["execution_id"],
                attempt_id=f'{row["execution_id"]}:0', cycle_id=f'{row["execution_id"]}:0:0',
                candidate_index=0, stream_ordinal=0, revision_profil=2,
            )
        assert admission_agents.historique(cnx, row["id"]) == before
        assert before[0]["raison"] == "enveloppe réservée avant exécution"
        reconciled = admission_agents.concilier(cnx, row["id"], 2)
        assert reconciled["statut"] == "conciliee" and reconciled["tokens_reels"] == 2
