/** Tests provider env-var candidate and auth evidence lookup. */
import { describe, expect, it } from "vitest";
import type { PluginManifestRecord } from "../plugins/manifest-registry.js";
import {
  loadPluginMetadataSnapshot,
  rebasePluginMetadataSnapshotManifestRegistry,
} from "../plugins/plugin-metadata-snapshot.js";
import {
  getProviderEnvVarsCore,
  listKnownProviderAuthEnvVarNamesCore,
  listKnownSecretEnvVarNames,
  omitEnvKeysCaseInsensitive,
} from "./provider-env-vars.js";

// QA fictif: exercise declared provider metadata independently of bundled selection.
function providerEnvTestParams() {
  const snapshot = loadPluginMetadataSnapshot({
    config: {},
    env: process.env,
    preferPersisted: false,
  });
  const plugin: PluginManifestRecord = {
    id: "qa-provider-env-vars",
    origin: "config",
    channels: [],
    providers: [],
    cliBackends: [],
    skills: [],
    hooks: [],
    rootDir: "/qa-fictif/provider-env-vars",
    source: "/qa-fictif/provider-env-vars/index.js",
    manifestPath: "/qa-fictif/provider-env-vars/openclaw.plugin.json",
    setup: {
      providers: [
        { id: "brave", envVars: ["BRAVE_API_KEY"] },
        { id: "deepgram", envVars: ["DEEPGRAM_API_KEY"] },
        { id: "firecrawl", envVars: ["FIRECRAWL_API_KEY"] },
        { id: "groq", envVars: ["GROQ_API_KEY"] },
        { id: "perplexity", envVars: ["PERPLEXITY_API_KEY"] },
        { id: "openrouter", envVars: ["OPENROUTER_API_KEY"] },
        { id: "tavily", envVars: ["TAVILY_API_KEY"] },
        { id: "minimax-coding-plan", envVars: ["MINIMAX_CODE_PLAN_KEY", "MINIMAX_CODING_API_KEY"] },
        { id: "fal", envVars: ["FAL_KEY", "FAL_API_KEY"] },
      ],
    },
    providerUsageAuthEnvVars: {
      openai: ["OPENAI_ADMIN_KEY"],
      anthropic: ["ANTHROPIC_ADMIN_KEY", "ANTHROPIC_ADMIN_API_KEY"],
    },
  };
  return {
    metadataSnapshot: rebasePluginMetadataSnapshotManifestRegistry(snapshot, {
      plugins: [plugin],
      diagnostics: [],
    }),
  };
}

describe("provider env vars", () => {
  it("keeps declared provider credentials in auth and secret inventories", () => {
    const params = providerEnvTestParams();
    const sharedSecretNames = [
      "ANTHROPIC_OAUTH_TOKEN",
      "BRAVE_API_KEY",
      "DEEPGRAM_API_KEY",
      "FIRECRAWL_API_KEY",
      "GROQ_API_KEY",
      "PERPLEXITY_API_KEY",
      "OPENROUTER_API_KEY",
      "TAVILY_API_KEY",
    ];
    const providerAuthNames = listKnownProviderAuthEnvVarNamesCore(params);
    const secretNames = listKnownSecretEnvVarNames(params);
    for (const name of sharedSecretNames) {
      expect(providerAuthNames).toContain(name);
      expect(secretNames).toContain(name);
    }
    expect(providerAuthNames).toContain("MINIMAX_CODE_PLAN_KEY");
    expect(providerAuthNames).toContain("MINIMAX_CODING_API_KEY");
    expect(providerAuthNames).toContain("OPENAI_ADMIN_KEY");
    expect(providerAuthNames).toContain("ANTHROPIC_ADMIN_KEY");
    expect(providerAuthNames).toContain("ANTHROPIC_ADMIN_API_KEY");
    expect(secretNames).toContain("OPENAI_ADMIN_KEY");
    expect(secretNames).toContain("ANTHROPIC_ADMIN_KEY");
    expect(secretNames).toContain("ANTHROPIC_ADMIN_API_KEY");
    expect(listKnownSecretEnvVarNames(params)).not.toContain("OPENCLAW_API_KEY");
  });

  it.each(["GH_TOKEN", "GITHUB_TOKEN"])("audits %s without activating a provider", (name) => {
    expect(listKnownSecretEnvVarNames()).toContain(name);
    expect(listKnownProviderAuthEnvVarNamesCore()).not.toContain(name);
    expect(getProviderEnvVarsCore("github-copilot")).not.toContain(name);
  });

  it("omits env keys case-insensitively", () => {
    const env = omitEnvKeysCaseInsensitive(
      {
        OpenAI_Api_Key: "openai-secret",
        Github_Token: "gh-secret",
        OPENCLAW_API_KEY: "keep-me",
      },
      ["OPENAI_API_KEY", "GITHUB_TOKEN"],
    );

    expect(env.OpenAI_Api_Key).toBeUndefined();
    expect(env.Github_Token).toBeUndefined();
    expect(env.OPENCLAW_API_KEY).toBe("keep-me");
  });

  it("ignores prototype-chain keys when resolving provider env vars", () => {
    const params = providerEnvTestParams();
    expect(getProviderEnvVarsCore("__proto__", params)).toStrictEqual([]);
    expect(getProviderEnvVarsCore("constructor", params)).toStrictEqual([]);
    expect(getProviderEnvVarsCore("openai", params)).toEqual(["CODEX_API_KEY", "OPENAI_API_KEY"]);
    expect(getProviderEnvVarsCore("anthropic", params)).toEqual([
      "ANTHROPIC_OAUTH_TOKEN",
      "ANTHROPIC_API_KEY",
    ]);
    expect(getProviderEnvVarsCore("fal", params)).toEqual(["FAL_KEY", "FAL_API_KEY"]);
  });
});
