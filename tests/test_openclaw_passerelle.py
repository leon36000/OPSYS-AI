from __future__ import annotations

import http.server
import json
import subprocess
import threading
from pathlib import Path

import pytest

from opsys import modeles as modeles_config
from opsys import openclaw, passerelle

PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}

# Mêmes noms que `deploy/.env.example`/`src/opsys/memoire/embeddings.py` (voir aussi
# tests/test_openclaw_memoire.py) : requis depuis que generer() écrit la config mémoire (ADR-0010).
ENVIRON_EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1",
                      "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}


def test_fragments_openclaw(departements_demo, tmp_path):
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, fuseau="America/Toronto",
                                 environ=ENVIRON_EMBEDDINGS)
    catalog = json.loads(fichiers["models"].read_text(encoding="utf-8"))
    assert catalog["mode"] == "merge"
    assert catalog["providers"]["anthropic"]["apiKey"] == "${ANTHROPIC_API_KEY}"
    assert catalog["providers"]["anthropic"]["models"] == [
        {"id": "claude-haiku-4-5-20251001", "name": "claude-haiku-4-5-20251001"},
        {"id": "claude-sonnet-5", "name": "claude-sonnet-5"},
    ]
    assert catalog["providers"]["opsys-local"] == {
        "models": [{"id": "qwen3:8b", "name": "qwen3:8b"}],
        "baseUrl": "http://ollama:11434/v1",
        "api": "openai-completions",
        "apiKey": "local",
        "request": {"allowPrivateNetwork": True},
    }

    fragment_agents = json.loads(fichiers["agents"].read_text(encoding="utf-8"))
    assert fragment_agents["defaults"]["contextPruning"] == {"mode": "cache-ttl", "ttl": "1h"}
    # Dix agents sans agent par défaut : le fork exige un roster explicite (E2E T1.5-b).
    assert fragment_agents["ownership"] == "explicit"
    assert not any(entree.get("default") for entree in fragment_agents["entries"].values())
    agents = fragment_agents["entries"]
    assert agents["m09-demo"] == {
        "name": "M9 · Démo",
        "workspace": "./opsys/espaces/m09-demo",
        "model": "anthropic/claude-sonnet-5",
        "opsysIsolation": {"exec": "sandbox-required"},
        "tools": {"deny": ["opsys_context_*__*", "opsys_runtime_*__*"]},
    }

    mcp = json.loads(fichiers["mcp"].read_text(encoding="utf-8"))["servers"]["opsys_m9"]
    assert mcp["url"] == "http://opsys:8765/mcp/m09-demo"
    assert mcp["transport"] == "streamable-http"
    assert mcp["headers"] == {"Authorization": "Bearer ${OPSYS_MCP_JETON}"}

    script = fichiers["automatisations"].read_text(encoding="utf-8")
    assert "--agent m09-demo" in script and "--cron '0 7 * * 1-5'" in script
    assert "--tz America/Toronto" in script

    espace = tmp_path / "opsys" / "espaces" / "m09-demo"
    assert "`m9_payer` (T3)" in (espace / "SOUL.md").read_text(encoding="utf-8")
    assert "en_attente_approbation" in (espace / "AGENTS.md").read_text(encoding="utf-8")
    assert (espace / "skills" / "procedure-demo" / "SKILL.md").is_file()


def test_litellm_est_un_mode_de_compatibilite_explicite(departements_demo, tmp_path):
    fichiers = openclaw.generer(
        departements_demo,
        tmp_path,
        PALIERS,
        mode_fournisseur="litellm",
        url_passerelle="http://litellm-test:4000/v1",
        environ=ENVIRON_EMBEDDINGS,
    )

    catalog = json.loads(fichiers["models"].read_text(encoding="utf-8"))
    assert "opsys-m9" in catalog["providers"]
    assert catalog["providers"]["opsys-m9"]["baseUrl"] == "http://litellm-test:4000/v1"
    assert json.loads(fichiers["agents"].read_text(encoding="utf-8"))["entries"]["m09-demo"]["model"] == (
        "opsys-m9/opsys-standard"
    )


def test_paliers_emettent_des_replis_valides_sans_modeles_alias_inventes(departements_demo, tmp_path):
    paliers = {
        **PALIERS,
        "standard": {**PALIERS["standard"], "fallbacks": ["rapide"]},
        "local": {**PALIERS["local"], "api_key_env": "OPSYS_TEST_LLM_KEY"},
    }
    fichiers = openclaw.generer(departements_demo, tmp_path, paliers, environ=ENVIRON_EMBEDDINGS)
    agent = json.loads(fichiers["agents"].read_text(encoding="utf-8"))["entries"]["m09-demo"]
    providers = json.loads(fichiers["models"].read_text(encoding="utf-8"))["providers"]

    assert agent["model"] == {
        "primary": "anthropic/claude-sonnet-5",
        "fallbacks": ["anthropic/claude-haiku-4-5-20251001"],
    }
    assert providers["opsys-local"]["apiKey"] == "${OPSYS_TEST_LLM_KEY}"
    assert all("opsys-standard" not in model["id"] for entry in providers.values() for model in entry["models"])


def test_configuration_native_est_projetee_depuis_le_fichier_paliers_du_dashboard(departements_demo, tmp_path):
    fichier_paliers = tmp_path / "paliers.yaml"
    modeles_config.enregistrer_paliers({
        "standard": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "rapide": {"provider": "openai", "model": "gpt-5.4-mini"},
        "local": {
            "provider": "custom",
            "model": "qwen3:8b",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key_env": "OPSYS_LOCAL_LLM_KEY",
        },
    }, chemin=fichier_paliers)
    paliers_lus = modeles_config.charger_paliers(fichier_paliers)
    env = {**ENVIRON_EMBEDDINGS, "ANTHROPIC_API_KEY": "secret-fixture-must-not-be-written"}

    fichiers = openclaw.generer(departements_demo, tmp_path / "oc", paliers_lus, environ=env)
    catalog = json.loads(fichiers["models"].read_text(encoding="utf-8"))

    assert catalog["providers"]["anthropic"]["models"] == [
        {"id": "claude-sonnet-4-6", "name": "claude-sonnet-4-6"}
    ]
    assert catalog["providers"]["anthropic"]["apiKey"] == "${ANTHROPIC_API_KEY}"
    assert catalog["providers"]["openai"]["apiKey"] == "${OPENAI_API_KEY}"
    assert catalog["providers"]["opsys-local"]["apiKey"] == "${OPSYS_LOCAL_LLM_KEY}"
    assert "secret-fixture-must-not-be-written" not in fichiers["models"].read_text(encoding="utf-8")

    racine = Path(__file__).resolve().parents[1]
    tsx = racine / "core" / "node_modules" / ".bin" / "tsx"
    if not tsx.is_file():
        pytest.skip("validation croisée désactivée : dépendances TypeScript du core absentes")
    validateur = tmp_path / "valider-modeles.ts"
    schema = (racine / "core" / "src" / "config" / "zod-schema.core.ts").as_posix()
    validateur.write_text(
        "import { readFileSync } from 'node:fs';\n"
        f"import {{ ModelsConfigSchema }} from {json.dumps(schema)};\n"
        "const raw = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        "const parsed = ModelsConfigSchema.safeParse(raw);\n"
        "if (!parsed.success) { process.stderr.write(JSON.stringify(parsed.error.issues)); process.exit(1); }\n",
        encoding="utf-8",
    )
    subprocess.run(
        [str(tsx), str(validateur), str(fichiers["models"])],
        cwd=racine / "core",
        check=True,
        capture_output=True,
        text=True,
    )


def test_refuse_paliers_de_repli_absents_ou_cycliques(departements_demo, tmp_path):
    paliers_absent = {**PALIERS, "standard": {**PALIERS["standard"], "fallbacks": ["fort"]}}
    with pytest.raises(ValueError, match="non configurés"):
        openclaw.generer(departements_demo, tmp_path, paliers_absent, environ=ENVIRON_EMBEDDINGS)

    paliers_cycle = {
        **PALIERS,
        "standard": {**PALIERS["standard"], "fallbacks": ["rapide"]},
        "rapide": {**PALIERS["rapide"], "fallbacks": ["standard"]},
    }
    with pytest.raises(ValueError, match="cycle"):
        openclaw.generer(departements_demo, tmp_path, paliers_cycle, environ=ENVIRON_EMBEDDINGS)


def test_palier_par_defaut_manquant(departements_demo, tmp_path):
    with pytest.raises(ValueError, match="palier par défaut 'standard' non configuré"):
        openclaw.generer(departements_demo, tmp_path, {"rapide": PALIERS["rapide"]})


def test_racine_creee_une_seule_fois(tmp_path):
    racine = openclaw.racine_si_absente(tmp_path)
    assert json.loads(racine.read_text(encoding="utf-8"))["agents"] == {"$include": ["./opsys/agents.json"]}
    racine.write_text('{"gateway": {"port": 18789}}', encoding="utf-8")
    assert openclaw.racine_si_absente(tmp_path) is None
    assert "18789" in racine.read_text(encoding="utf-8")


def test_config_litellm_depuis_paliers():
    config = passerelle.config_litellm(PALIERS)
    modeles = {m["model_name"]: m["litellm_params"] for m in config["model_list"]}
    assert list(modeles) == ["opsys-local", "opsys-rapide", "opsys-standard"]
    assert modeles["opsys-standard"] == {"model": "anthropic/claude-sonnet-5",
                                         "api_key": "os.environ/ANTHROPIC_API_KEY"}
    assert modeles["opsys-local"] == {"model": "openai/qwen3:8b", "api_base": "http://ollama:11434/v1",
                                      "api_key": "local"}
    assert config["litellm_settings"]["cache_params"] == {"type": "redis", "host": "valkey", "port": 6379}
    with pytest.raises(ValueError, match="aucun palier"):
        passerelle.config_litellm({})


class _FauxLiteLLM(http.server.BaseHTTPRequestHandler):
    cles: dict[str, dict] = {}
    appels: list[tuple[str, str, dict | None]] = []

    def _repondre(self, statut, corps):
        donnees = json.dumps(corps).encode()
        self.send_response(statut)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def do_GET(self):  # noqa: N802
        self.appels.append(("GET", self.path, None))
        empreinte = self.path.split("key=")[1]
        if empreinte in self.cles:
            self._repondre(200, {"key": empreinte, "info": self.cles[empreinte]})
        else:
            self._repondre(404, {"error": "introuvable"})

    def do_POST(self):  # noqa: N802
        corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.appels.append(("POST", self.path, corps))
        assert self.headers["Authorization"] == "Bearer maitre-de-test"
        self.cles[passerelle.empreinte_cle(corps["key"])] = {"spend": 0.0, **corps}
        self._repondre(200, {"key": corps["key"]})

    def log_message(self, *args):
        return


@pytest.fixture
def faux_litellm():
    _FauxLiteLLM.cles, _FauxLiteLLM.appels = {}, []
    serveur = http.server.HTTPServer(("127.0.0.1", 0), _FauxLiteLLM)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{serveur.server_address[1]}"
    serveur.shutdown()


def test_cle_departement_creee_puis_mise_a_jour(departements_demo, faux_litellm):
    client = passerelle.ClientLiteLLM(faux_litellm, "maitre-de-test")
    dep = departements_demo["m09-demo"]
    cle = "sk-opsys-m9-0123456789abcdef0123"
    assert client.enregistrer_departement(dep, cle, ["opsys-standard"]) == "cree"
    assert client.enregistrer_departement(dep, cle, ["opsys-standard"], budget_usd_mois=25.0) == "mis_a_jour"
    methodes = [(m, chemin.split("?")[0]) for m, chemin, _ in _FauxLiteLLM.appels]
    assert methodes == [("GET", "/key/info"), ("POST", "/key/generate"), ("GET", "/key/info"), ("POST", "/key/update")]
    assert all(cle not in chemin for _, chemin, _ in _FauxLiteLLM.appels)  # jamais la clé brute dans l'URL
    creation = _FauxLiteLLM.appels[1][2]
    assert creation["tpd_limit"] == dep.budget.tokens_jour and creation["key_alias"] == "opsys-m09-demo"
    assert creation["enable_prompt_caching"] is True
    assert _FauxLiteLLM.appels[3][2]["max_budget"] == 25.0


def test_cle_trop_courte_et_maitre_absent(departements_demo, faux_litellm):
    with pytest.raises(ValueError, match="clé maître"):
        passerelle.ClientLiteLLM(faux_litellm, "")
    client = passerelle.ClientLiteLLM(faux_litellm, "maitre-de-test")
    with pytest.raises(ValueError, match="trop courte"):
        client.enregistrer_departement(departements_demo["m09-demo"], "sk-court", ["opsys-standard"])


class _FauxActivite(http.server.BaseHTTPRequestHandler):
    pages = {
        1: {"results": [{"date": "2026-09-27", "metrics": {"prompt_tokens": 900, "completion_tokens": 100},
                         "breakdown": {"models": {"claude-sonnet-5": {"metrics": {
                             "prompt_tokens": 900, "completion_tokens": 100, "cache_read_input_tokens": 400,
                             "successful_requests": 3}}}}}],
            "metadata": {"page": 1, "total_pages": 2}},
        2: {"results": [{"date": "2026-09-28", "metrics": {"prompt_tokens": 50, "completion_tokens": 5,
                                                           "successful_requests": 1}}],
            "metadata": {"page": 2, "total_pages": 2}},
    }
    vus: list[str] = []

    def do_GET(self):  # noqa: N802
        self.vus.append(self.path)
        page = int(self.path.split("page=")[1].split("&")[0])
        donnees = json.dumps(self.pages[page]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def log_message(self, *args):
        return


def test_synchronisation_usage_depuis_litellm(departements_demo, session):
    import datetime as dt

    from opsys import jetons

    _FauxActivite.vus = []
    serveur = http.server.HTTPServer(("127.0.0.1", 0), _FauxActivite)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    try:
        client = passerelle.ClientLiteLLM(f"http://127.0.0.1:{serveur.server_address[1]}", "maitre-de-test")
        debut, fin = dt.date(2026, 9, 27), dt.date(2026, 9, 28)
        with session() as cnx:
            assert passerelle.synchroniser_usage(client, cnx, departements_demo.values(), debut, fin) == 2
            assert passerelle.synchroniser_usage(client, cnx, departements_demo.values(), debut, fin) == 2
            assert jetons.consommation(cnx, "m09-demo", debut, debut) == 1000  # idempotent : pas de double
            assert jetons.consommation(cnx, "m09-demo", fin, fin) == 55
            budget = jetons.etat_budget(cnx, "m09-demo", departements_demo["m09-demo"].budget, debut)
    finally:
        serveur.shutdown()
    assert budget["niveau"] == "epuise"
    assert all("tags=m09-demo" in chemin for chemin in _FauxActivite.vus)


def test_regenerer_ne_supprime_jamais_ce_que_le_core_a_ecrit_dans_l_espace_de_travail(departements_demo, tmp_path):
    # Le core écrit la mémoire d'un agent dans son espace de travail ; `generer` est rejouée à chaque mise à jour.
    openclaw.generer(departements_demo, tmp_path, PALIERS, environ=ENVIRON_EMBEDDINGS)
    espace = tmp_path / "opsys" / "espaces" / "m09-demo"
    (espace / "MEMORY.md").write_text("mémoire de l'agent (fictif)\n", encoding="utf-8")
    (espace / "memory").mkdir()
    (espace / "memory" / "2026-09-29.md").write_text("note du jour (fictif)\n", encoding="utf-8")
    (espace / "SOUL.md").write_text("modifié à la main\n", encoding="utf-8")
    (espace / "skills" / "procedure-retiree").mkdir()
    (espace / "skills" / "procedure-retiree" / "SKILL.md").write_text("ancien skill\n", encoding="utf-8")

    openclaw.generer(departements_demo, tmp_path, PALIERS, environ=ENVIRON_EMBEDDINGS)

    assert (espace / "MEMORY.md").read_text(encoding="utf-8") == "mémoire de l'agent (fictif)\n"
    assert (espace / "memory" / "2026-09-29.md").read_text(encoding="utf-8") == "note du jour (fictif)\n"
    assert "`m9_payer` (T3)" in (espace / "SOUL.md").read_text(encoding="utf-8")  # ce qui est à OPSYS est réécrit
    assert (espace / "skills" / "procedure-demo" / "SKILL.md").is_file()
    assert not (espace / "skills" / "procedure-retiree").exists()  # un skill retiré du manifeste disparaît
