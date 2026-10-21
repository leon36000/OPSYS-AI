"""Parcours humain du tableau agents vers les intentions cron durables, sans runtime."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import agents, departements, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import AGENTS_DECLENCHEURS_COMMANDES, AGENTS_DECLENCHEURS_INTENTIONS, JOURNAL

FICTIF = True
OWNER = "owner.cron.console.fictif"
EMPLOYEE = "employee.cron.console.fictif"
PASSWORD = "mot-de-passe-cron-console-fictif-123"
SECRET = "secret-cron-console-fictif-" + "x" * 32
PROFILE = "m3-cron-console-fictif"


@pytest.fixture
def console_cron(session, opsys_home, monkeypatch):
    deps = departements.charger_departements()
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))
    with session() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", PASSWORD, ["nathan_owner"])
        identite.creer_personne(cnx, EMPLOYEE, "Employé fictif", PASSWORD, ["employee"])
        profile = agents.creer(cnx, deps, {
            "id": PROFILE,
            "departement": "m03-estimation",
            "responsabilite": "Préparer des dossiers fictifs sans action externe.",
            "palier_modele": "rapide",
            "outils": [],
            "budget_jour": 1000,
            "budget_mois": 10000,
            "limite_tours": 8,
            "limite_reessais": 1,
            "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        }, par=OWNER, mutation_id="create-console-cron-profile-fictif")
        profile = agents.definir_actif(
            cnx, PROFILE, deps, True, par=OWNER, mutation_id="activate-console-cron-profile-fictif",
            revision_attendue=profile["revision"],
        )
    policy = {
        "version": 1,
        "departements": {"m03-estimation": "global"},
        "agents": {"opsys-agent-" + PROFILE: {"departement": "m03-estimation", "mode": "global"}},
        "procedures_globales": ["procedures"],
    }
    directory = opsys_home / "core" / "opsys"
    directory.mkdir(parents=True)
    (directory / "memoire-autorites.json").write_text(json.dumps(policy), encoding="utf-8")
    app = application.creer_application(Configuration(SECRET), None, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client, profile, deps


def _login(client, person=OWNER):
    response = client.post(
        "/connexion", data={"identifiant": person, "mot_de_passe": PASSWORD}, follow_redirects=False,
    )
    assert response.status_code == 303
    return client.get("/api/session").json()["csrf"]


def _form(profile, csrf, *, mutation="demande-cron-console-fictive", fuseau="America/Toronto"):
    return {
        "csrf": csrf,
        "mutation_id": mutation,
        "revision_attendue": str(profile["revision"]),
        "fuseau": fuseau,
        "confirme": "oui",
    }


def _lignes(session):
    with session() as cnx:
        return {
            "intentions": [dict(row) for row in cnx.execute(select(AGENTS_DECLENCHEURS_INTENTIONS)).mappings()],
            "commandes": [dict(row) for row in cnx.execute(select(AGENTS_DECLENCHEURS_COMMANDES)).mappings()],
            "journal": [dict(row) for row in cnx.execute(
                select(JOURNAL).where(JOURNAL.c.action.like("agents.cron.%"))
            ).mappings()],
        }


def test_dashboard_prepare_et_retrait_sont_inertes_audites_et_revisionnes(console_cron, session):
    client, profile, deps = console_cron
    csrf = _login(client)
    page = client.get(f"/agents/{PROFILE}")
    assert page.status_code == 200
    assert "Préparer la demande cron" in page.text
    assert "aucune planification" in page.text.lower()
    before = _lignes(session)
    assert before == {"intentions": [], "commandes": [], "journal": []}

    form = _form(profile, csrf)
    prepared = client.post(f"/agents/{PROFILE}/declencheurs/cron/demander", data=form)
    assert prepared.status_code == 200
    assert "Aucune tâche Core n’a été créée ou exécutée" in prepared.text
    rows = _lignes(session)
    assert len(rows["intentions"]) == 1
    assert rows["intentions"][0]["statut"] == "a_declarer"
    assert rows["intentions"][0]["demande_par"] == OWNER
    assert len(rows["commandes"]) == 1  # Idempotence propriétaire, pas de cron.add.
    assert [row["action"] for row in rows["journal"]] == ["agents.cron.demande"]
    assert rows["journal"][0]["par"] == OWNER

    replay = client.post(f"/agents/{PROFILE}/declencheurs/cron/demander", data=form)
    assert replay.status_code == 200
    assert _lignes(session) == rows

    with session() as cnx:
        inactive = agents.definir_actif(
            cnx, PROFILE, deps, False, par=OWNER, mutation_id="disable-console-cron-profile-fictif",
            revision_attendue=profile["revision"],
        )
    assert inactive["actif"] is False
    retire_form = {
        "csrf": csrf,
        "mutation_id": "retrait-cron-console-fictif",
        "revision_attendue": str(inactive["revision"]),
        "confirme": "oui",
    }
    retrait = client.post(
        f"/agents/{PROFILE}/declencheurs/cron/retirer", data=retire_form,
    )
    assert retrait.status_code == 200
    rows = _lignes(session)
    assert rows["intentions"][0]["statut"] == "a_retirer"
    assert len(rows["commandes"]) == 2  # Une clé d'idempotence par mutation humaine.
    assert [row["action"] for row in rows["journal"]] == [
        "agents.cron.demande", "agents.cron.retrait_demande",
    ]


def test_dashboard_refuse_csrf_role_champs_forges_et_revision_perimee(console_cron, session):
    client, profile, deps = console_cron
    csrf = _login(client)
    path = f"/agents/{PROFILE}/declencheurs/cron/demander"
    form = _form(profile, csrf)
    assert client.post(path, data={**form, "csrf": "csrf-fictif-invalide"}).status_code == 403
    duplicate = client.post(path, content=(
        "csrf=" + csrf + "&mutation_id=duplicate-cron-console-fictif&revision_attendue="
        + str(profile["revision"]) + "&revision_attendue=1&fuseau=America%2FToronto&confirme=oui"
    ), headers={"content-type": "application/x-www-form-urlencoded"})
    assert duplicate.status_code == 400
    invalid_utf8 = client.post(
        path, content="csrf=" + csrf + "&mutation_id=bad-utf8-cron-console-fictif&revision_attendue="
        + str(profile["revision"]) + "&fuseau=%FF&confirme=oui",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert invalid_utf8.status_code == 400
    assert _lignes(session) == {"intentions": [], "commandes": [], "journal": []}

    employee_csrf = _login(client, EMPLOYEE)
    assert client.post(path, data=_form(profile, employee_csrf)).status_code == 403
    assert _lignes(session) == {"intentions": [], "commandes": [], "journal": []}

    csrf = _login(client)
    assert client.post(path, data={**_form(profile, csrf), "par": OWNER, "role": "nathan_owner"}).status_code == 400
    assert _lignes(session) == {"intentions": [], "commandes": [], "journal": []}

    with session() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
    csrf_apres_retrait = csrf
    stale = client.post(
        path, data=_form(profile, csrf_apres_retrait, mutation="role-retire-cron-console-fictif"),
    )
    assert stale.status_code == 403
    assert _lignes(session) == {"intentions": [], "commandes": [], "journal": []}

    # Une personne qui perd son rôle après la connexion est refusée par la session rechargée,
    # avant que l'owner cron puisse écrire quoi que ce soit.
    with session() as cnx:
        identite.ajouter_role(cnx, OWNER, "nathan_owner")
        courant = agents.obtenir(cnx, PROFILE)
        spec = {key: courant[key] for key in (
            "id", "departement", "responsabilite", "palier_modele", "outils", "budget_jour", "budget_mois",
            "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs",
        )}
        spec["responsabilite"] += " Révisé."
        agents.modifier(
            cnx, PROFILE, deps, spec, par=OWNER,
            mutation_id="revision-console-cron-fictive", revision_attendue=profile["revision"],
        )
    stale = client.post(
        path, data=_form(profile, csrf, mutation="revision-expiree-cron-fictive"),
    )
    assert stale.status_code == 400
    assert _lignes(session) == {"intentions": [], "commandes": [], "journal": []}


def test_base_app_divergente_est_refusee_sans_ecriture_dans_les_deux_bases(
    console_cron, session, tmp_path, monkeypatch,
):
    _, _, deps = console_cron
    url_a = stockage.url_base()
    url_b = f"sqlite:///{tmp_path / 'autre-base-cron.db'}"
    stockage.migrer(url_b)

    @contextmanager
    def autre_session():
        with stockage.transaction(url_b) as cnx:
            yield cnx

    with autre_session() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", PASSWORD, ["nathan_owner"])
        identite.creer_personne(cnx, EMPLOYEE, "Employé fictif", PASSWORD, ["employee"])
        profile_b = agents.creer(cnx, deps, {
            "id": PROFILE,
            "departement": "m03-estimation",
            "responsabilite": "Préparer des dossiers fictifs sans action externe.",
            "palier_modele": "rapide",
            "outils": [],
            "budget_jour": 1000,
            "budget_mois": 10000,
            "limite_tours": 8,
            "limite_reessais": 1,
            "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        }, par=OWNER, mutation_id="create-other-db-profile-fictif")
        agents.definir_actif(
            cnx, PROFILE, deps, True, par=OWNER, mutation_id="activate-other-db-profile-fictif",
            revision_attendue=profile_b["revision"],
        )
    monkeypatch.setenv("OPSYS_BASE_URL", url_a)
    app_b = application.creer_application(Configuration(SECRET), deps, autre_session)
    with TestClient(app_b, base_url="https://testserver/opsys") as client_b:
        csrf = _login(client_b)
        form = _form({"revision": 2}, csrf, mutation="cross-db-cron-console-fictif")
        refus = client_b.post(f"/agents/{PROFILE}/declencheurs/cron/demander", data=form)
        assert refus.status_code == 400

    assert _lignes(session) == {"intentions": [], "commandes": [], "journal": []}
    assert _lignes(autre_session) == {"intentions": [], "commandes": [], "journal": []}
