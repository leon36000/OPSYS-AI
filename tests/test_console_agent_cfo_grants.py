"""Parcours réel de gestion des droits CFO avec personnes et profil fictifs."""

import html
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import admission_agents, agents, departements, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration

FICTIF = True
OWNER = "owner.grant.console.fictif"
ADMIN = "admin.grant.console.fictif"
EMPLOYEE = "employee.grant.console.fictif"
PASSWORD = "mot-de-passe-grant-console-fictif-123"
SECRET = "secret-grant-console-fictif-" + "x" * 32
TOOL = "m5_preparer_dossier_decision_cfo"
CAPITAL = "m5_preparer_decision_capital"


@pytest.fixture
def client_grant_cfo(session):
    deps = departements.charger_departements()
    with session() as cnx:
        for person, roles in ((OWNER, ["nathan_owner"]), (ADMIN, ["admin"]), (EMPLOYEE, ["employee"])):
            identite.creer_personne(cnx, person, "Personne fictive", PASSWORD, roles)
        profile = agents.creer(
            cnx,
            deps,
            {
                "id": "m5-cfo-console-fictif",
                "departement": "m05-financecore",
                "responsabilite": "Préparer des rapports CFO fictifs.",
                "palier_modele": "rapide",
                "outils": [TOOL, CAPITAL],
                "budget_jour": 10000,
                "budget_mois": 100000,
                "limite_tours": 8,
                "limite_reessais": 1,
                "limite_concurrence": 1,
                "declencheurs": [{"type": "manuel"}],
            },
            par=OWNER,
            mutation_id="grant-console-create-fictif",
        )
        profile = agents.definir_actif(
            cnx,
            profile["id"],
            deps,
            True,
            par=OWNER,
            mutation_id="grant-console-activate-fictif",
            revision_attendue=profile["revision"],
        )
    app = application.creer_application(Configuration(SECRET), None, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client, profile


def _login(client, person=OWNER):
    response = client.post("/connexion", data={"identifiant": person, "mot_de_passe": PASSWORD}, follow_redirects=False)
    assert response.status_code == 303
    return client.get("/api/session").json()["csrf"]


def _form(profile, csrf):
    return {
        "csrf": csrf,
        "revision_attendue": profile["revision"],
        "version_grant_attendue": 0,
        "date_debut_rapport": "2026-10-01",
        "date_fin_rapport": "2026-10-31",
        "outils": TOOL,
        "rapports_par_jour": 1,
        "expire_le": "",
    }


def _grants(session):
    from opsys.stockage.schema import AGENTS_GRANTS_CFO, AGENTS_GRANTS_CFO_HISTORIQUE

    with session() as cnx:
        return {
            table.name: [dict(row) for row in cnx.execute(select(table)).mappings()]
            for table in (AGENTS_GRANTS_CFO, AGENTS_GRANTS_CFO_HISTORIQUE)
    }


def test_reservation_active_persistante_bloque_un_nouveau_cycle_et_est_visible_apres_reouverture(
    client_grant_cfo, session,
):
    client, profile = client_grant_cfo
    deps = departements.charger_departements()
    with session() as cnx:
        admission_agents.configurer_plafonds_entreprise(
            cnx, 100_000, 1_000_000, par=OWNER, revision_attendue=0
        )
        reservation = admission_agents.admettre_cycle_runtime(
            cnx, profile["id"], deps, "diag-run-0001", "diag-key-0001", 100,
            revision_profil=profile["revision"], attempt_id="diag-run-0001:0",
            cycle_id="diag-run-0001:0:0", candidate_index=0, stream_ordinal=0,
            is_fallback_retry=False,
        )
        with pytest.raises(admission_agents.AdmissionRefusee, match="concurrence"):
            admission_agents.admettre_cycle_runtime(
                cnx, profile["id"], deps, "diag-run-0002", "diag-key-0002", 100,
                revision_profil=profile["revision"], attempt_id="diag-run-0002:0",
                cycle_id="diag-run-0002:0:0", candidate_index=0, stream_ordinal=0,
                is_fallback_retry=False,
            )
        assert reservation["statut"] == "reservee"

    csrf = _login(client, ADMIN)
    page = client.get(f"/agents/{profile['id']}")
    assert page.status_code == 200
    assert "Réservations runtime actives" in page.text
    assert "diag-run-0001" in page.text and "diag-run-0001:0:0" in page.text
    assert "Inconnu — à rapprocher" in page.text and "100" in page.text
    assert "Utilisation fournisseur à vérifier" in page.text
    assert "Inconnu — à rapprocher" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert csrf

    # A new engine over the same OPSYS_HOME demonstrates this is durable storage, not page state.
    stockage.liberer()
    stockage.migrer()
    reouverte = client.get(f"/agents/{profile['id']}")
    assert reouverte.status_code == 200
    assert "diag-run-0001:0:0" in reouverte.text


def test_listing_reservations_est_borne_avec_total_et_ne_rend_pas_raison_libre(client_grant_cfo, session):
    client, profile = client_grant_cfo
    from opsys.stockage.schema import AGENTS_RESERVATIONS, AGENTS_RESERVATIONS_HISTORIQUE

    with session() as cnx:
        for index in range(51):
            reservation_id = f"{index:032x}"
            execution = f"exec-{index:03d}-<script>"
            cycle = f"{execution}:{index}:0"
            cree_le = (
                "horodatage-invalide" if index == 50
                else "9999-01-01T00:00:00+00:00" if index == 49
                else "2026-10-01T00:00:00+00:00"
            )
            cnx.execute(
                AGENTS_RESERVATIONS.insert().values(
                    id=reservation_id, agent_id=profile["id"], departement=profile["departement"],
                    execution_id=execution, cle_idempotence=f"diag-key-{index:03d}", tokens_plafond=77,
                    tokens_reels=None, jour="2026-10-01", mois="2026-10", tours=1, reessais=0,
                    attempt_id=None, cycle_id=cycle, candidate_index=0, stream_ordinal=0,
                    is_fallback_retry=False, statut="reservee", cree_le=cree_le, modifie_le=cree_le,
                )
            )
            cnx.execute(
                AGENTS_RESERVATIONS_HISTORIQUE.insert().values(
                    id=f"{index + 100:032x}", reservation_id=reservation_id, evenement="reservee",
                    tokens_reels=None, raison="NE_PAS_AFFICHER_SECRET_TEST", cree_le=cree_le,
                )
            )
    csrf = _login(client, ADMIN)
    page = client.get(f"/agents/{profile['id']}")
    assert page.status_code == 200
    assert "50 affichée(s) sur 51" in page.text and "1 omise(s)" in page.text
    assert "NE_PAS_AFFICHER_SECRET_TEST" not in page.text
    assert "&lt;script&gt;" in page.text and "<script>" not in page.text
    assert "INCONNU — horodatage invalide ou sans fuseau" in page.text
    assert "INCONNU — date future selon l’horloge serveur" in page.text
    assert csrf


def test_listing_reservations_refuse_limite_hors_borne(session):
    from opsys import admission_agents

    with session() as cnx, pytest.raises(ValueError, match="entre 1 et 50"):
        admission_agents.lister_reservations_actives(cnx, "m5-cfo-console-fictif", limite=51)


def test_date_corrompue_extreme_donne_un_age_inconnu_sans_erreur(client_grant_cfo, session):
    _client, profile = client_grant_cfo
    from opsys.stockage.schema import AGENTS_RESERVATIONS, AGENTS_RESERVATIONS_HISTORIQUE

    extreme = "0001-01-01T00:00:00+14:00"
    with session() as cnx:
        cnx.execute(
            AGENTS_RESERVATIONS.insert().values(
                id="e" * 32, agent_id=profile["id"], departement=profile["departement"],
                execution_id="horloge-extreme-001", cle_idempotence="horloge-extreme-key",
                tokens_plafond=50, tokens_reels=None, jour="0001-01-01", mois="0001-01",
                tours=1, reessais=0, attempt_id=None, cycle_id="horloge-extreme-001:0:0",
                candidate_index=0, stream_ordinal=0, is_fallback_retry=False,
                statut="reservee", cree_le=extreme, modifie_le=extreme,
            )
        )
        cnx.execute(
            AGENTS_RESERVATIONS_HISTORIQUE.insert().values(
                id="f" * 32, reservation_id="e" * 32, evenement="reservee",
                tokens_reels=None, raison="raison interne", cree_le=extreme,
            )
        )
        resultat = admission_agents.lister_reservations_actives(cnx, profile["id"])
    assert resultat["reservations"][0]["age_statut"] == "INCONNU_HORODATAGE_INVALIDE"
    assert resultat["reservations"][0]["age_secondes"] is None


def _reservation_runtime(session, profile, *, execution_id="manual-run-0001", key="manual-key-0001"):
    deps = departements.charger_departements()
    with session() as cnx:
        admission_agents.configurer_plafonds_entreprise(
            cnx, 100_000, 1_000_000, par=OWNER, revision_attendue=0
        )
        return admission_agents.admettre_cycle_runtime(
            cnx,
            profile["id"],
            deps,
            execution_id,
            key,
            10,
            revision_profil=profile["revision"],
            attempt_id=f"{execution_id}:0",
            cycle_id=f"{execution_id}:0:0",
            candidate_index=0,
            stream_ordinal=0,
            is_fallback_retry=False,
        )


def test_rapprochement_manuel_reel_exige_declaration_et_concilie_exactement_une_fois(
    client_grant_cfo, session,
):
    client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    path = f"/agents/{profile['id']}/reservations/{reservation['id']}/concilier"
    csrf = _login(client, ADMIN)

    page = client.get(f"/agents/{profile['id']}")
    assert page.status_code == 200
    assert "le relevé final" in page.text
    assert "cet appel fournisseur est terminé et ne peut plus générer de frais" in page.text
    assert "OPSYS ne vérifie ni le relevé ni cette déclaration humaine" in page.text
    assert "Si la finalité ou le total reste inconnu, ne soumettez pas" in page.text
    assert 'name="tokens_reels" min="0" step="1" required' in page.text
    assert 'name="attestation" value="oui" required' in page.text

    before = admission_agents.lire_reservation
    with session() as cnx:
        current = before(cnx, reservation["id"], agent_id=profile["id"])
    assert current["statut"] == "reservee" and current["tokens_reels"] is None

    data = {
        "csrf": csrf,
        "tokens_reels": "37",
        "reference_releve": "provider-report-20261001-01",
        "attestation": "oui",
    }
    response = client.post(path, data=data, follow_redirects=False)
    assert response.status_code == 303
    assert "rapprochement=declare" in response.headers["location"]
    with session() as cnx:
        final = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
        historique = admission_agents.historique(cnx, reservation["id"])
    assert final["statut"] == "conciliee"
    assert final["tokens_reels"] == 37 and final["depassement_plafond"] is True
    assert len(historique) == 2
    assert historique[-1]["tokens_reels"] == 37
    assert "déclaration humaine non vérifiée par OPSYS" in historique[-1]["raison"]
    assert "relevé déclaré final" in historique[-1]["raison"]
    assert "appel déclaré terminé et ne pouvant plus générer de frais" in historique[-1]["raison"]
    assert f"déclarant={ADMIN}" in historique[-1]["raison"]
    assert "provider-report-20261001-01" in historique[-1]["raison"]
    confirmation = client.get(f"/agents/{profile['id']}?rapprochement=declare")
    assert confirmation.status_code == 200
    assert "Déclaration manuelle enregistrée; son contenu n’est pas vérifié par OPSYS." in confirmation.text

    replay = client.post(path, data=data, follow_redirects=False)
    assert replay.status_code == 400
    with session() as cnx:
        final_replay = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
        historique_rejeu = admission_agents.historique(cnx, reservation["id"])
    assert final_replay["tokens_reels"] == 37 and len(historique_rejeu) == 2

    with session() as cnx:
        admission_agents.configurer_plafonds_entreprise(
            cnx, 40, 1_000, par=OWNER, revision_attendue=1
        )
        with pytest.raises(admission_agents.AdmissionRefusee, match="budget"):
            admission_agents.admettre_cycle_runtime(
                cnx, profile["id"], departements.charger_departements(), "manual-run-0002", "manual-key-0002", 4,
                revision_profil=profile["revision"], attempt_id="manual-run-0002:0",
                cycle_id="manual-run-0002:0:0", candidate_index=0, stream_ordinal=0,
                is_fallback_retry=False,
            )


def test_rapprochement_manuel_sans_finalite_ou_reference_ne_change_pas_reservation(client_grant_cfo, session):
    client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    path = f"/agents/{profile['id']}/reservations/{reservation['id']}/concilier"
    csrf = _login(client, OWNER)

    sans_attestation = client.post(
        path,
        data={"csrf": csrf, "tokens_reels": "0", "reference_releve": "interim-001"},
    )
    assert sans_attestation.status_code == 400
    mauvaise_reference = client.post(
        path,
        data={"csrf": csrf, "tokens_reels": "0", "reference_releve": "Bearer sk-secret", "attestation": "oui"},
    )
    assert mauvaise_reference.status_code == 400
    with session() as cnx:
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
        historique = admission_agents.historique(cnx, reservation["id"])
    assert current["statut"] == "reservee" and current["tokens_reels"] is None
    assert len(historique) == 1
    assert "sk-secret" not in historique[0]["raison"]


@pytest.mark.parametrize("valeur", [str(1 << 63), "9" * 20])
def test_formulaire_rapprochement_refuse_total_hors_borne_sans_500_ni_mutation(
    client_grant_cfo, session, valeur,
):
    client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    path = f"/agents/{profile['id']}/reservations/{reservation['id']}/concilier"
    csrf = _login(client, OWNER)
    response = client.post(
        path,
        data={
            "csrf": csrf,
            "tokens_reels": valeur,
            "reference_releve": "provider-final-oversize",
            "attestation": "oui",
        },
    )
    assert response.status_code == 400
    with session() as cnx:
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
        history = admission_agents.historique(cnx, reservation["id"])
    assert current["statut"] == "reservee" and current["tokens_reels"] is None
    assert len(history) == 1


def test_rapprochement_manuel_zero_explicite_est_un_usage_concilie_une_fois(client_grant_cfo, session):
    client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    csrf = _login(client, OWNER)
    path = f"/agents/{profile['id']}/reservations/{reservation['id']}/concilier"
    response = client.post(
        path,
        data={
            "csrf": csrf,
            "tokens_reels": "0",
            "reference_releve": "provider-final-zero-001",
            "attestation": "oui",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with session() as cnx:
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
        history = admission_agents.historique(cnx, reservation["id"])
    assert current["statut"] == "conciliee" and current["tokens_reels"] == 0
    assert len(history) == 2 and history[-1]["tokens_reels"] == 0


def test_total_reel_superieur_a_la_limite_de_reservation_10b_est_conserve(client_grant_cfo, session):
    client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    csrf = _login(client, OWNER)
    total_reel = 10_000_000_001
    response = client.post(
        f"/agents/{profile['id']}/reservations/{reservation['id']}/concilier",
        data={
            "csrf": csrf,
            "tokens_reels": str(total_reel),
            "reference_releve": "provider-final-overrun-10b",
            "attestation": "oui",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with session() as cnx:
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
    assert current["tokens_reels"] == total_reel and current["depassement_plafond"] is True


def test_rapprochement_manuel_refuse_mauvais_profil_sans_ecriture(client_grant_cfo, session):
    _client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    with session() as cnx:
        with pytest.raises(admission_agents.AdmissionRefusee, match="n'appartient pas à ce profil"):
            admission_agents.concilier_manuellement(
                cnx, reservation["id"], "autre-profil-fictif", 12,
                par=OWNER, reference_releve="provider-final-mismatch",
            )
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
        history = admission_agents.historique(cnx, reservation["id"])
    assert current["statut"] == "reservee" and current["tokens_reels"] is None
    assert len(history) == 1


@pytest.mark.parametrize("valeur", [True, 1.5, -1, 1 << 63])
def test_conciliation_refuse_total_non_entier_negatif_ou_superieur_a_i64_sans_mutation(
    client_grant_cfo, session, valeur,
):
    _client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    with session() as cnx:
        with pytest.raises(ValueError, match=r"2\^63-1"):
            admission_agents.concilier(cnx, reservation["id"], valeur)
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
        history = admission_agents.historique(cnx, reservation["id"])
    assert current["statut"] == "reservee" and current["tokens_reels"] is None
    assert len(history) == 1


def test_rapprochement_manuel_refuse_role_retire_apres_login(client_grant_cfo, session):
    client, profile = client_grant_cfo
    reservation = _reservation_runtime(session, profile)
    path = f"/agents/{profile['id']}/reservations/{reservation['id']}/concilier"
    csrf = _login(client, ADMIN)
    with session() as cnx:
        identite.retirer_role(cnx, ADMIN, "admin")
    response = client.post(
        path,
        data={
            "csrf": csrf,
            "tokens_reels": "0",
            "reference_releve": "provider-final-001",
            "attestation": "oui",
        },
    )
    assert response.status_code == 403
    with session() as cnx:
        current = admission_agents.lire_reservation(cnx, reservation["id"], agent_id=profile["id"])
    assert current["statut"] == "reservee" and current["tokens_reels"] is None


def test_role_admin_retire_apres_login_refuse_la_lecture_des_reservations(client_grant_cfo, session):
    client, profile = client_grant_cfo
    csrf = _login(client, ADMIN)
    with session() as cnx:
        identite.retirer_role(cnx, ADMIN, "admin")
    page = client.get(f"/agents/{profile['id']}")
    assert page.status_code == 403
    assert "Réservations runtime actives" not in page.text
    assert csrf


@pytest.mark.parametrize("person", [OWNER, ADMIN])
def test_console_accorde_un_droit_limite_puis_le_revoque(client_grant_cfo, session, person):
    client, profile = client_grant_cfo
    csrf = _login(client, person)
    path = f"/agents/{profile['id']}"
    page = client.get(path)
    assert page.status_code == 200 and "Lecture CFO préparatoire" in page.text
    form = _form(profile, csrf)
    granted = client.post(f"{path}/droit-cfo", data=form, follow_redirects=False)
    assert granted.status_code == 303, granted.text
    state = _grants(session)
    grant = state["agents_grants_cfo"][0]
    assert grant["active"] is True and grant["version"] == 1
    assert grant["granted_by"] == person and grant["reports_per_day"] == 1
    assert state["agents_grants_cfo_historique"][0]["actor"] == person
    page = client.get(path)
    textarea = re.search(r'<textarea id="cfo-outils" name="outils" required>(.*?)</textarea>', page.text, re.S)
    assert textarea and html.unescape(textarea.group(1)) == TOOL
    assert f'value="{grant["expires_at"]}"' in page.text
    stale = client.post(f"{path}/droit-cfo", data=form, follow_redirects=False)
    assert stale.status_code in (403, 409)
    assert _grants(session) == state
    revoked = client.post(
        f"{path}/droit-cfo/retrait",
        data={"csrf": csrf, "version_grant_attendue": 1},
        follow_redirects=False,
    )
    assert revoked.status_code == 303, revoked.text
    after = _grants(session)
    assert after["agents_grants_cfo"][0]["active"] is False
    assert after["agents_grants_cfo"][0]["version"] == 2
    assert [row["event"] for row in after["agents_grants_cfo_historique"]] == ["grant", "revocation"]


def test_console_refuse_csrf_employe_et_role_retire_avant_mutation(client_grant_cfo, session):
    client, profile = client_grant_cfo
    csrf = _login(client)
    form = _form(profile, csrf)
    path = f"/agents/{profile['id']}/droit-cfo"
    before = _grants(session)
    assert client.post(path, data={**form, "csrf": "csrf-invalide-fictif"}).status_code == 403
    assert _grants(session) == before
    csrf_employee = _login(client, EMPLOYEE)
    assert client.post(path, data={**form, "csrf": csrf_employee}).status_code == 403
    assert _grants(session) == before
    csrf = _login(client)
    with session() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
    assert client.post(path, data={**form, "csrf": csrf}).status_code == 403
    assert _grants(session) == before
