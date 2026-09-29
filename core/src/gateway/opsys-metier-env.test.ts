// Token and environment of the OPSYS business engine (OPSYS-AI PLAN T0.10): one shared secret,
// owned by the Gateway, handed to the engine through its environment only.
import { describe, expect, it, vi } from "vitest";
import {
  buildOpsysMetierChildEnv,
  buildOpsysMetierCliEnv,
  resolveOpsysMcpToken,
} from "./opsys-metier-env.js";

const TOKEN = "jeton-de-test-suffisamment-long-0123456789";

describe("resolveOpsysMcpToken", () => {
  it("reads the token the operator already shares with the MCP client config", () => {
    const randomBytes = vi.fn<(size: number) => Buffer>();

    const result = resolveOpsysMcpToken({ env: { OPSYS_MCP_JETON: TOKEN }, randomBytes });

    expect(result).toStrictEqual({ ok: true, token: TOKEN, source: "env" });
    expect(randomBytes).not.toHaveBeenCalled();
  });

  it.each([
    { title: "absent", env: {} },
    { title: "empty", env: { OPSYS_MCP_JETON: "" } },
  ])("generates a 256-bit token when the variable is $title", ({ env }) => {
    const randomBytes = vi.fn<(size: number) => Buffer>(() => Buffer.alloc(32, 0xab));

    const result = resolveOpsysMcpToken({ env, randomBytes });

    expect(randomBytes).toHaveBeenCalledWith(32);
    expect(result).toStrictEqual({ ok: true, token: "ab".repeat(32), source: "generated" });
  });

  it("generates different tokens from the real random source", () => {
    const first = resolveOpsysMcpToken({ env: {} });
    const second = resolveOpsysMcpToken({ env: {} });

    expect(first).toMatchObject({ ok: true, source: "generated", token: expect.stringMatching(/^[0-9a-f]{64}$/u) });
    expect(second).toMatchObject({ ok: true, source: "generated" });
    expect(first).not.toStrictEqual(second);
  });

  it.each([
    { title: "too short for the engine", value: "court" },
    { title: "padded with whitespace", value: ` ${TOKEN}` },
    { title: "split by whitespace", value: "jeton de test suffisamment long 0123" },
  ])("refuses a token that is $title instead of replacing it", ({ value }) => {
    const result = resolveOpsysMcpToken({ env: { OPSYS_MCP_JETON: value } });

    expect(result).toStrictEqual({
      ok: false,
      reason: "OPSYS_MCP_JETON must be at least 24 characters without whitespace",
    });
  });
});

describe("buildOpsysMetierChildEnv", () => {
  it("passes what the engine needs to run and drops the Gateway's own secrets", () => {
    const env = buildOpsysMetierChildEnv({
      base: {
        PATH: "/usr/local/bin:/usr/bin",
        HOME: "/home/opsys",
        LANG: "fr_CA.UTF-8",
        LC_ALL: "fr_CA.UTF-8",
        TZ: "America/Toronto",
        UV_CACHE_DIR: "/var/cache/uv",
        OPSYS_HOME: "/var/lib/opsys",
        OPSYS_DATABASE_URL: "postgresql://opsys@db/opsys",
        LITELLM_URL: "http://litellm:4000",
        HTTPS_PROXY: "http://proxy:3128",
        OPENCLAW_GATEWAY_TOKEN: "gateway-secret",
        OPENCLAW_STATE_DIR: "/home/opsys/.openclaw",
        ANTHROPIC_API_KEY: "sk-provider-secret",
        TELEGRAM_BOT_TOKEN: "channel-secret",
      },
      extra: {},
      token: TOKEN,
    });

    expect(env).toStrictEqual({
      PATH: "/usr/local/bin:/usr/bin",
      HOME: "/home/opsys",
      LANG: "fr_CA.UTF-8",
      LC_ALL: "fr_CA.UTF-8",
      TZ: "America/Toronto",
      UV_CACHE_DIR: "/var/cache/uv",
      OPSYS_HOME: "/var/lib/opsys",
      OPSYS_DATABASE_URL: "postgresql://opsys@db/opsys",
      LITELLM_URL: "http://litellm:4000",
      HTTPS_PROXY: "http://proxy:3128",
      PYTHONUNBUFFERED: "1",
      OPSYS_MCP_JETON: TOKEN,
    });
  });

  it("matches variable names case-insensitively, as Windows does", () => {
    const env = buildOpsysMetierChildEnv({
      base: { Path: "C:\\Windows", SystemRoot: "C:\\Windows", Secret_Thing: "no" },
      extra: {},
      token: TOKEN,
    });

    expect(env).toMatchObject({ Path: "C:\\Windows", SystemRoot: "C:\\Windows" });
    expect(env).not.toHaveProperty("Secret_Thing");
  });

  it("lets the operator add variables and override the unbuffered-output default", () => {
    const env = buildOpsysMetierChildEnv({
      base: { PATH: "/usr/bin" },
      extra: { EXTRA_FEATURE: "on", PYTHONUNBUFFERED: "0" },
      token: TOKEN,
    });

    expect(env).toStrictEqual({
      PATH: "/usr/bin",
      EXTRA_FEATURE: "on",
      PYTHONUNBUFFERED: "0",
      OPSYS_MCP_JETON: TOKEN,
    });
  });

  it("never lets the inherited or configured environment override the token", () => {
    const env = buildOpsysMetierChildEnv({
      base: { OPSYS_MCP_JETON: "jeton-herite-qui-ne-doit-pas-passer-0123" },
      extra: { OPSYS_MCP_JETON: "jeton-du-fichier-qui-ne-doit-pas-passer" },
      token: TOKEN,
    });

    expect(env.OPSYS_MCP_JETON).toBe(TOKEN);
  });
});

describe("buildOpsysMetierCliEnv", () => {
  it("passes what the engine's CLI needs, the same set as the supervised engine, and no token", () => {
    const env = buildOpsysMetierCliEnv({
      base: {
        PATH: "/usr/local/bin:/usr/bin",
        HOME: "/home/opsys",
        LANG: "fr_CA.UTF-8",
        UV_CACHE_DIR: "/var/cache/uv",
        OPSYS_EMBEDDINGS_URL: "http://127.0.0.1:11434/v1",
        OPSYS_MCP_JETON: TOKEN,
        OPENCLAW_GATEWAY_TOKEN: "gateway-secret",
        OPENCLAW_PROFILE: "opsys",
        ANTHROPIC_API_KEY: "sk-provider-secret",
        TELEGRAM_BOT_TOKEN: "channel-secret",
      },
      extra: {},
      platform: "linux",
    });

    expect(env).toStrictEqual({
      PATH: "/usr/local/bin:/usr/bin",
      HOME: "/home/opsys",
      LANG: "fr_CA.UTF-8",
      UV_CACHE_DIR: "/var/cache/uv",
      OPSYS_EMBEDDINGS_URL: "http://127.0.0.1:11434/v1",
      OPSYS_MCP_JETON: TOKEN, // the instance .env, as the old `opsys` command exported it
    });
  });

  it("treats the env of metier.json as defaults that the caller's environment overrides", () => {
    const env = buildOpsysMetierCliEnv({
      base: { OPSYS_HOME: "/autre/instance" },
      extra: { OPSYS_HOME: "/instance", OPSYS_SEUIL: "12" },
      platform: "linux",
    });

    expect(env).toStrictEqual({ OPSYS_HOME: "/autre/instance", OPSYS_SEUIL: "12" });
  });

  it("makes Python write UTF-8 on Windows, where a redirected pipe is cp1252, and only there", () => {
    expect(buildOpsysMetierCliEnv({ base: {}, extra: {}, platform: "win32" })).toStrictEqual({
      PYTHONUTF8: "1",
    });
    expect(buildOpsysMetierCliEnv({ base: {}, extra: {}, platform: "darwin" })).toStrictEqual({});
  });
});
