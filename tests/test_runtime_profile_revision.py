from __future__ import annotations

import pytest
from sqlalchemy import func, select

from opsys import admission_agents, agents, identite
from opsys.stockage.schema import AGENTS_RESERVATIONS


def _profile(session, departements_demo):
    with session() as cnx:
        identite.creer_personne(cnx, "revision-admin", "Admin factice", "synthetic-only-password-01", ["admin"])
        agents.creer(
            cnx,
            departements_demo,
            {
                "id": "m09-revision",
                "departement": "m09-demo",
                "responsabilite": "Profil fictif du test de révision.",
                "palier_modele": "standard",
                "outils": ["m9_additionner", "m9_refuser_si_negatif"],
                "budget_jour": 100,
                "budget_mois": 1_000,
                "limite_tours": 2,
                "limite_reessais": 1,
                "limite_concurrence": 1,
                "declencheurs": [{"type": "manuel"}],
            },
            par="revision-admin",
            mutation_id="revision-profile-create-01",
        )
        agents.definir_actif(
            cnx,
            "m09-revision",
            departements_demo,
            True,
            par="revision-admin",
            mutation_id="revision-profile-activate-01",
            revision_attendue=1,
        )


def test_live_tool_check_uses_exact_current_profile_revision_and_allowlist(session, departements_demo):
    _profile(session, departements_demo)
    with session() as cnx:
        assert admission_agents.verifier_outil_runtime(
            cnx, "m09-revision", departements_demo, "opsys_m9__m9_refuser_si_negatif", 2
        ) == {"autorise": True, "revision_profil": 2}

        current = agents.obtenir(cnx, "m09-revision")
        assert current is not None
        specification = {
            key: current[key]
            for key in (
                "id",
                "departement",
                "responsabilite",
                "palier_modele",
                "outils",
                "budget_jour",
                "budget_mois",
                "limite_tours",
                "limite_reessais",
                "limite_concurrence",
                "declencheurs",
            )
        }
        specification["outils"] = ["m9_additionner"]
        agents.modifier(
            cnx,
            "m09-revision",
            departements_demo,
            specification,
            par="revision-admin",
            mutation_id="revision-profile-revoke-01",
            revision_attendue=2,
        )

        with pytest.raises(admission_agents.AdmissionRefusee, match="périmée"):
            admission_agents.verifier_outil_runtime(
                cnx, "m09-revision", departements_demo, "opsys_m9__m9_additionner", 2
            )
        with pytest.raises(admission_agents.AdmissionRefusee, match="absente"):
            admission_agents.verifier_outil_runtime(
                cnx, "m09-revision", departements_demo, "opsys_m9__m9_refuser_si_negatif", 3
            )
        assert admission_agents.verifier_outil_runtime(
            cnx, "m09-revision", departements_demo, "opsys_m9__m9_additionner", 3
        ) == {"autorise": True, "revision_profil": 3}


def test_stale_admission_is_refused_before_a_reservation_row_is_created(session, departements_demo):
    _profile(session, departements_demo)
    with session() as cnx:
        admission_agents.configurer_plafonds_entreprise(
            cnx, 1_000, 10_000, par="revision-admin", revision_attendue=0
        )
        current = agents.obtenir(cnx, "m09-revision")
        assert current is not None
        specification = {
            key: current[key]
            for key in (
                "id",
                "departement",
                "responsabilite",
                "palier_modele",
                "outils",
                "budget_jour",
                "budget_mois",
                "limite_tours",
                "limite_reessais",
                "limite_concurrence",
                "declencheurs",
            )
        }
        agents.modifier(
            cnx,
            "m09-revision",
            departements_demo,
            specification,
            par="revision-admin",
            mutation_id="revision-profile-update-01",
            revision_attendue=2,
        )
        with pytest.raises(admission_agents.AdmissionRefusee, match="périmée"):
            admission_agents.admettre_cycle_runtime(
                cnx,
                "m09-revision",
                departements_demo,
                "revision-run-0001",
                "revision-cycle-key-0001",
                20,
                revision_profil=2,
                attempt_id="revision-run-0001:0",
                cycle_id="revision-run-0001:0:0",
                candidate_index=0,
                stream_ordinal=0,
                is_fallback_retry=False,
            )
        remaining = cnx.execute(select(func.count()).select_from(AGENTS_RESERVATIONS)).scalar_one()
        assert remaining == 0
        current = admission_agents.admettre_cycle_runtime(
            cnx,
            "m09-revision",
            departements_demo,
            "revision-run-0002",
            "revision-cycle-key-0002",
            20,
            revision_profil=3,
            attempt_id="revision-run-0002:0",
            cycle_id="revision-run-0002:0:0",
            candidate_index=0,
            stream_ordinal=0,
            is_fallback_retry=False,
        )
        assert current["statut"] == "reservee"
