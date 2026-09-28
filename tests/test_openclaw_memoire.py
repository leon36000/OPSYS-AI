"""PLAN T0.14 : cloisonnement inter-agents et mémoire native (Couche A, ADR-0010).

Preuve que `openclaw.generer()` écrit désormais `tools.json` (cloisonnement), `memory.json`
(fournisseur d'embeddings partagé) et `plugins.json` (dreaming de `memory-core`), en fail-closed
si les variables d'embeddings manquent, et que chaque clé écrite existe réellement dans le schéma
du fork (`core/src/config/zod-schema.*.ts`, `core/extensions/memory-core/openclaw.plugin.json`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opsys import openclaw
from opsys.memoire.embeddings import ENV_CLE, ENV_MODELE, ENV_URL, ErreurEmbeddings

RACINE = Path(__file__).resolve().parents[1]
CONFIG_FORK = RACINE / "core" / "src" / "config"
PLUGIN_MEMOIRE = RACINE / "core" / "extensions" / "memory-core" / "openclaw.plugin.json"

PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}
ENVIRON_EMBEDDINGS = {ENV_URL: "http://embeddings-test:11434/v1", ENV_MODELE: "bge-m3"}


# --- 1. Cloisonnement (tools.json) -----------------------------------------------------------


def test_partage_entre_agents_desactive(departements_demo, tmp_path):
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, environ=ENVIRON_EMBEDDINGS)
    outils = json.loads(fichiers["tools"].read_text(encoding="utf-8"))
    assert outils["agentToAgent"] == {"enabled": False}


def test_visibilite_sessions_restreinte(departements_demo, tmp_path):
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, environ=ENVIRON_EMBEDDINGS)
    outils = json.loads(fichiers["tools"].read_text(encoding="utf-8"))
    # "tree" (pas "self") : voir openclaw._configuration_outils.__doc__ et
    # test_visibilite_tree_est_la_plus_restrictive_sans_casser_les_sous_agents ci-dessous.
    assert outils["sessions"] == {"visibility": "tree"}


def test_racine_inclut_les_nouveaux_fragments(tmp_path):
    racine = openclaw.racine_si_absente(tmp_path)
    contenu = json.loads(racine.read_text(encoding="utf-8"))
    assert contenu["tools"] == {"$include": ["./opsys/tools.json"]}
    assert contenu["memory"] == {"$include": ["./opsys/memory.json"]}
    assert contenu["plugins"] == {"$include": ["./opsys/plugins.json"]}


def test_visibilite_tree_est_la_plus_restrictive_sans_casser_les_sous_agents():
    """Preuve par le code réel (pas seulement le schéma) : `core/src/plugin-sdk/
    session-visibility-internal.ts::createSessionVisibilityDecisionChecker` n'autorise un
    sous-agent natif/enfant ACP engendré par la session courante (`isSubagentSessionKey`/
    `isAcpSessionKey`, ligne ~156-165) que si `visibility` vaut "tree" ou "all" ; avec "self",
    la même session engendrée est refusée en ligne ~197 (`self_visibility_restricted`), faute
    d'être la session courante elle-même (`isRequesterSession`).
    """
    texte = (RACINE / "core" / "src" / "plugin-sdk" / "session-visibility-internal.ts").read_text(
        encoding="utf-8"
    )
    # Le chemin qui laisse passer un sous-agent natif exige tree/all, jamais self seul.
    assert '(params.visibility === "tree" || params.visibility === "all")' in texte
    assert 'isSubagentSessionKey(targetSessionKey)' in texte
    # "self" refuse toute session qui n'est pas la session requérante elle-même.
    assert 'params.visibility === "self" && !isRequesterSession' in texte
    assert '"self_visibility_restricted"' in texte


# --- 2. Mémoire native Couche A (memory.json, plugins.json) ----------------------------------


def test_configuration_memoire_presente(departements_demo, tmp_path):
    environ = {**ENVIRON_EMBEDDINGS, ENV_CLE: "secret-test"}
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, environ=environ)
    recherche = json.loads(fichiers["memory"].read_text(encoding="utf-8"))["search"]
    assert recherche["provider"] == "openai-compatible"
    assert recherche["model"] == "bge-m3"
    assert recherche["remote"]["baseUrl"] == "http://embeddings-test:11434/v1"
    assert recherche["remote"]["apiKey"] == f"${{{ENV_CLE}}}"  # jamais la clé en clair


def test_cle_embeddings_omise_si_non_fournie(departements_demo, tmp_path):
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, environ=ENVIRON_EMBEDDINGS)
    recherche = json.loads(fichiers["memory"].read_text(encoding="utf-8"))["search"]
    assert "apiKey" not in recherche["remote"]


def test_dreaming_configure_et_aligne_sur_le_fuseau(departements_demo, tmp_path):
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, fuseau="America/Toronto",
                                 environ=ENVIRON_EMBEDDINGS)
    plugins = json.loads(fichiers["plugins"].read_text(encoding="utf-8"))
    dreaming = plugins["entries"]["memory-core"]["config"]["dreaming"]
    assert dreaming == {"enabled": True, "timezone": "America/Toronto"}


def test_provenance_non_inventee(departements_demo, tmp_path):
    """La provenance (owner/agent/untrusted/system) est structurelle à `memory-core`, pas une
    clé de configSchema (voir openclaw._configuration_memoire.__doc__) : aucun fragment généré
    ne doit prétendre la configurer.
    """
    fichiers = openclaw.generer(departements_demo, tmp_path, PALIERS, environ=ENVIRON_EMBEDDINGS)
    for cle in ("memory", "plugins", "tools"):
        assert "provenance" not in fichiers[cle].read_text(encoding="utf-8")


# --- Fail-closed : variable d'embeddings manquante --------------------------------------------


def test_fail_closed_generer_sans_url_embeddings(departements_demo, tmp_path):
    with pytest.raises(ValueError, match=ENV_URL):
        openclaw.generer(departements_demo, tmp_path, PALIERS, environ={})


def test_fail_closed_configuration_memoire_sans_url(monkeypatch):
    monkeypatch.delenv(ENV_URL, raising=False)
    with pytest.raises(ValueError, match=ENV_URL):
        openclaw._configuration_memoire(None)  # défaut : os.environ, nettoyé ci-dessus


def test_fail_closed_url_presente_mais_modele_absent():
    with pytest.raises(ErreurEmbeddings, match=ENV_MODELE):
        openclaw._configuration_memoire({ENV_URL: "http://embeddings-test:11434/v1"})


def test_fail_closed_url_malformee():
    with pytest.raises(ErreurEmbeddings):
        openclaw._configuration_memoire({ENV_URL: "pas-une-url", ENV_MODELE: "bge-m3"})


# --- 3. Chaque clé écrite existe dans le schéma du fork (lecture du .ts / du plugin.json) ------


def test_cle_agent_to_agent_existe_dans_le_schema_du_fork():
    texte = (CONFIG_FORK / "zod-schema.agent-runtime.ts").read_text(encoding="utf-8")
    assert "agentToAgent: z" in texte
    assert "enabled: z.boolean().optional()," in texte
    assert "remain reachable under tree/all visibility" in texte  # justifie "tree" plutôt que "self"


def test_cle_sessions_visibility_existe_dans_le_schema_du_fork():
    texte = (CONFIG_FORK / "zod-schema.agent-runtime.ts").read_text(encoding="utf-8")
    assert "sessions: z" in texte
    assert 'visibility: z.enum(["self", "tree", "agent", "all"]).optional(),' in texte


def test_cles_memory_search_existent_dans_le_schema_du_fork():
    texte = (CONFIG_FORK / "zod-schema.memory-search.ts").read_text(encoding="utf-8")
    for extrait in (
        "provider: z.string().optional(),",
        "model: z.string().optional(),",
        "baseUrl: z.string().optional(),",
        "apiKey: SecretInputSchema.optional().register(sensitive),",
    ):
        assert extrait in texte, extrait


def test_valeur_openai_compatible_verifiee_dans_le_fork_pas_seulement_dans_ladr():
    texte = (CONFIG_FORK / "schema.help.models.ts").read_text(encoding="utf-8")
    assert '"memory.search.provider":' in texte
    assert '"openai-compatible"' in texte


def test_cles_racine_tools_memory_plugins_existent_dans_le_schema_du_fork():
    texte = (CONFIG_FORK / "zod-schema.root-shape.ts").read_text(encoding="utf-8")
    assert "tools: ToolsSchema," in texte
    assert "memory: MemorySchema," in texte
    assert "plugins: z" in texte
    assert "entries: z.record(z.string(), PluginEntrySchema).optional()," in texte


def test_plugin_entry_config_existe_dans_le_schema_du_fork():
    texte = (RACINE / "core" / "src" / "config" / "zod-schema.root-support.ts").read_text(
        encoding="utf-8"
    )
    assert "export const PluginEntrySchema = z.strictObject({" in texte
    assert "config: z.record(z.string(), z.unknown()).optional()," in texte


def test_dreaming_genere_valide_contre_le_configschema_du_plugin():
    """Vérification des clés contre `configSchema` (jsonschema n'est pas une dépendance déclarée
    de ce paquet — voir pyproject.toml — donc pas utilisé ici pour ne pas en ajouter une non
    justifiée/consignée dans docs/research/INGREDIENTS.md)."""
    manifeste = json.loads(PLUGIN_MEMOIRE.read_text(encoding="utf-8"))
    schema_dreaming = manifeste["configSchema"]["properties"]["dreaming"]
    assert schema_dreaming["type"] == "object"
    assert schema_dreaming["additionalProperties"] is False
    proprietes = schema_dreaming["properties"]
    type_python = {"boolean": bool, "string": str, "integer": int, "number": (int, float)}

    genere = openclaw._configuration_plugins("America/Toronto")["entries"]["memory-core"]["config"]
    assert set(genere) <= {"dreaming"}  # rien en dehors de ce que configGroups déclare (memory-policy, dreaming)
    for cle, valeur in genere["dreaming"].items():
        assert cle in proprietes, f"clé generée {cle!r} absente de configSchema.properties.dreaming"
        assert isinstance(valeur, type_python[proprietes[cle]["type"]])


def test_configschema_memory_core_ne_declare_aucune_propriete_provenance():
    """Confirme l'absence d'une clé "provenance" dans le configSchema du plugin (audit M10, §1.1
    règle 6) : justifie pourquoi `_configuration_memoire`/`_configuration_plugins` n'en écrivent
    pas — ce n'est pas un oubli, la clé n'existe pas côté fork.
    """
    manifeste = json.loads(PLUGIN_MEMOIRE.read_text(encoding="utf-8"))
    proprietes_dreaming = set(manifeste["configSchema"]["properties"]["dreaming"]["properties"])
    proprietes_racine = set(manifeste["configSchema"]["properties"])
    assert "provenance" not in proprietes_dreaming
    assert "provenance" not in proprietes_racine
