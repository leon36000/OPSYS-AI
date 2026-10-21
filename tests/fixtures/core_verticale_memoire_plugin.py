"""Read canonical M10 facts through Core on the existing fictional affair; no RAG claim."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from opsys import agents, stockage

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = ROOT / "core/test/fixtures/opsys-verticale"
pytest_plugins = ["core_verticale_profil_plugin"]
PROFILE = "qualification-affaire-m10"
SESSION_FINANCE = "agent:m05-financecore:webchat:direct:verticale-fictive"


@pytest.fixture(autouse=True)
def qualifier_memoire_affaire(qualifier_raccord_core, request):
    yield
    moteur = request.getfixturevalue("moteur")
    module = request.module
    ((_, lead_event),) = module._evenements("m1.lead_qualifie")
    lead_id = lead_event["lead"]["lead_id"]
    financial = module._evenements("m5.rentabilite_chantier")
    assert financial and financial[-1][1]["marge_reelle_cad"] == "114.00"
    wct_id = financial[-1][1]["wct_id"]
    assert all(row["wct_id"] == wct_id for _, row in financial)
    with stockage.transaction():
        rows = list(stockage.maillons("m10-memoire", "evenements"))
    retained = [row for row in rows if row.get("evenement_id") in {event_id for event_id, _ in financial}]
    assert len(retained) == len(financial)
    for event_id, charge in financial:
        row = next(row for row in retained if row["evenement_id"] == event_id)
        assert row["confidentialite"] == "FINANCIAL" and row["type_entree"] == "evenement_memorise"
        assert all(row[key] == value for key, value in charge.items())
    specification = {
        "id": PROFILE,
        "departement": "m10-memoire",
        "responsabilite": "Lire la liaison et auditer l'affaire fictive.",
        "palier_modele": "standard",
        "outils": ["m10_affaire_de_la_session", "m10_auditer_non_oubli"],
        "budget_jour": 200000,
        "budget_mois": 200000,
        "limite_tours": 4,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }
    with stockage.transaction() as cnx:
        agents.creer(
            cnx, moteur.departements, specification, par="nathan", mutation_id="profil-memoire-affaire-create-fictif"
        )
        profile = agents.definir_actif(
            cnx,
            PROFILE,
            moteur.departements,
            True,
            par="nathan",
            mutation_id="profil-memoire-affaire-active-fictif",
            revision_attendue=1,
        )
    assert profile["revision"] == 2
    driver = DRIVERS / "core_verticale_memoire_driver.mjs"
    repo = ROOT
    events = []
    http_requests = []
    observed_configs = []

    def observe_http():
        config = moteur._serveur.config
        if any(config is previous for previous in observed_configs):
            return
        original = config.loaded_app

        async def forward(scope, receive, send):
            async def observe_send(message):
                if message["type"] == "http.response.start":
                    http_requests.append(
                        {"method": scope["method"], "path": scope["path"], "status": message["status"]}
                    )
                await send(message)

            await original(scope, receive, observe_send)

        config.loaded_app = forward
        observed_configs.append(config)

    def call(phase, tool=None, args=None, *, private=False, public_token=False, catalog=False):
        before = module._empreinte(moteur)
        observe_http()
        trace_start = len(http_requests)
        manifest = moteur.dossier / f"memoire-{phase}-fictif.json"
        manifest.write_text(
            json.dumps(
                {
                    "fictif": True,
                    "phase": phase,
                    "profileId": PROFILE,
                    "workspaceDir": str(moteur.dossier),
                    "serverName": "opsys_context_m5" if private else "opsys_m10",
                    "url": f"http://127.0.0.1:{moteur.port}/mcp/"
                    + ("contexte/m05-financecore" if private else "m10-memoire"),
                    "bearer": module.JETON_MCP if not private or public_token else module.JETON_CONTEXTE_FICTIF,
                    "tool": tool,
                    "args": args or {},
                    "catalog": catalog,
                }
            )
        )
        manifest.chmod(0o600)
        env = {
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "HOME": str(moteur.dossier),
            "OPENCLAW_STATE_DIR": str(moteur.dossier / "core-memoire-etat-fictif"),
            "OPENCLAW_CONFIG_PATH": str(moteur.dossier / "config-inexistant-memoire-fictif.json"),
            "OPSYS_QUALIFICATION_REPO": str(repo),
        }
        evidence = Path(os.environ["OPSYS_MEMOIRE_QUALIFICATION_PREUVE"]).parent
        stdout_path = evidence / f"memoire-{phase}-stdout.log"
        stderr_path = evidence / f"memoire-{phase}-stderr.log"
        try:
            with stdout_path.open("x", encoding="utf-8") as stdout, stderr_path.open("x", encoding="utf-8") as stderr:
                result = subprocess.run(
                    ["node", "--import", "./scripts/tsx.mjs", str(driver), str(manifest)],
                    cwd=repo / "core",
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=90,
                )
        finally:
            manifest.unlink(missing_ok=True)
        stdout_text = stdout_path.read_text(encoding="utf-8")
        stderr_text = stderr_path.read_text(encoding="utf-8")
        assert result.returncode == 0, stderr_text[-3000:]
        lines = [
            line.removeprefix("OPSYS_PROOF_JSON:")
            for line in stdout_text.splitlines()
            if line.startswith("OPSYS_PROOF_JSON:")
        ]
        assert len(lines) == 1, stdout_text[-3000:]
        proof = json.loads(lines[0])
        proof["http_trace"] = http_requests[trace_start:]
        assert module._empreinte(moteur) == before, phase
        proof["all_meta_unchanged"] = True
        proof["meta_sha256_before_after"] = before["contenu_sha256"]
        events.append(proof)
        return proof

    def data(proof):
        assert proof.get("envelope", {}).get("ok") is True and not proof.get("isError"), proof
        return proof["envelope"]["resultat"]

    expected_ids = [
        {"type_evenement": "m5.rentabilite_chantier", "identifiant": event_id} for event_id, _ in financial
    ] + [{"type_evenement": "m4.travaux_termines", "identifiant": wct_id}]
    link = data(call("liaison-session", "m10_affaire_de_la_session", {"cle_session": SESSION_FINANCE}))
    assert link["lie"] is True and link["affaire_id"] == lead_id and link["lie_par"] == "nathan", link
    audit = data(call("audit-non-oubli", "m10_auditer_non_oubli", {"identifiants_attendus": expected_ids}))
    assert (
        audit["nb_oublis"] == 0
        and audit["chaine_evenements_intacte"] is True
        and audit["chaine_affaires_intacte"] is True
    ), audit
    public_catalog = call("catalogue-public", catalog=True)
    assert "tools" in public_catalog and "m10_paquet_contexte_affaire" not in public_catalog["tools"]
    packet_args = {"affaire_id": lead_id, "horodatage": module.iso(moteur.horloge.maintenant)}
    packet = data(call("paquet-prive-m5", "m10_paquet_contexte_affaire", packet_args, private=True))

    def assert_packet(packet):
        assert packet["affaire_id"] == lead_id and packet["affaire"]["connue"] is True
        assert packet["confidentialite"]["agent"] == "m05-financecore" and packet["confidentialite"][
            "nb_retenus"
        ] >= len(financial)
        text = json.dumps(packet, ensure_ascii=False)
        assert "marge_reelle_cad" not in text and "cout_reel_cad" not in text
        assert all(event_id not in text for event_id, _ in financial)
        assert "cliente-verticale@exemple.test" not in text
        assert len(packet["couches"]) == 4

    assert_packet(packet)
    hidden = call("paquet-interdit-route-publique", "m10_paquet_contexte_affaire", packet_args)
    assert hidden.get("isError") is True and hidden.get("envelope", {}).get("erreur") == "outil_inconnu", hidden
    unauthorized = call(
        "jeton-public-refuse-route-privee", "m10_paquet_contexte_affaire", packet_args, private=True, public_token=True
    )
    assert "exception" in unauthorized, unauthorized
    assert any(
        row["status"] == 401 and row["path"] == "/mcp/contexte/m05-financecore" for row in unauthorized["http_trace"]
    ), unauthorized
    unknown = data(
        call(
            "affaire-inconnue-explicite",
            "m10_paquet_contexte_affaire",
            {**packet_args, "affaire_id": "affaire-inconnue-fictive"},
            private=True,
        )
    )
    assert unknown["affaire"]["connue"] is False and "INCONNUE" in unknown["affaire"]["verdict"], unknown
    before_restart = module._empreinte(moteur)
    moteur.arreter()
    moteur.demarrer()
    assert module._empreinte(moteur) == before_restart
    packet_restart = data(call("paquet-apres-redemarrage", "m10_paquet_contexte_affaire", packet_args, private=True))
    assert_packet(packet_restart)
    assert packet_restart == packet
    assert (
        data(call("audit-apres-redemarrage", "m10_auditer_non_oubli", {"identifiants_attendus": expected_ids})) == audit
    )
    destination = Path(os.environ["OPSYS_MEMOIRE_QUALIFICATION_PREUVE"])
    with destination.open("x") as stream:
        json.dump(
            {
                "fictif": True,
                "scope": (
                    "lecture relationnelle M10 via vrai Core/HTTP sur même affaire, conservation et filtrage ; sans RAG"
                ),
                "affaire_id": lead_id,
                "wct_id": wct_id,
                "devis_id": financial[-1][1]["devis_id"],
                "financial_sources": financial,
                "m10_retained_rows": retained,
                "phases": events,
                "sources_qualification": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [
                        Path(__file__),
                        driver,
                        Path(__file__).with_name("core_verticale_profil_plugin.py"),
                        DRIVERS / "core_verticale_profil_driver.mjs",
                    ]
                },
                "limites": [
                    "une affaire SQLite fictive",
                    "profil M10 borne les deux outils publics ; origine M5 du paquet fixée par route privée/bearer",
                    "liaison de session ne constitue pas une ACL objet client",
                    "FINANCIAL non restitué même à M5 ; conservation interne comparée aux montants source",
                    "pas d'indexation/recherche vectorielle ni preuve RAG",
                    "isolation métier/développement qualifiée par le reçu dev distinct du parcours composé",
                    "test intégré au job Core tests-opsys ; pas de RAG",
                    "aucun téléphone ou orchestration modèle complète",
                ],
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")
