import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm, stat, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { getSessionMcpRuntimeManagerForTesting } from "./agent-bundle-mcp-manager-api.js";
import { getOrCreateSessionMcpRuntime } from "./agent-bundle-mcp-manager.test-support.js";
import { createOpsysCfoGrantTicketMeta, OPSYS_CFO_MCP_SERVER } from "./opsys-cfo-grant-ticket.js";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../../");
const FIXTURE = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../test/opsys-cfo-grant-fixture.py",
);
const PRIVATE_TOKEN = "fixture-runtime-token-not-a-secret-0001";
const PUBLIC_TOKEN = "fixture-public-token-not-a-secret-0001";
const PROFILE_ID = "m5-cfo-agent";
const AGENT_ID = `opsys-agent-${PROFILE_ID}`;
const SESSION_KEY = `agent:${AGENT_ID}:main`;
const TOOL = "m5_preparer_dossier_decision_cfo";
const ARGS = { aujourd_hui: "2026-10-01", question_posee: "Rapport CFO synthétique de test" };
const children: ChildProcess[] = [];
const tempDirs: string[] = [];

function requiredPython(): string {
  const python = process.env.OPSYS_TEST_PYTHON;
  if (!python) {
    throw new Error("OPSYS_TEST_PYTHON is required for the CFO MCP integration test");
  }
  return python;
}

function fixtureEnv(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUNBUFFERED: "1",
    OPSYS_EVENEMENTS_REPARTITEUR: "0",
    PYTHONPATH: [
      resolve(REPO, "src"),
      ...[
        "m01-front-office",
        "m02-revenue-crm",
        "m03-estimation",
        "m04-field-ops",
        "m05-financecore",
        "m06-material-control",
        "m07-marketing",
        "m08-analytics",
        "m09-strategic-intelligence",
        "m10-memoire",
      ].map((department) => resolve(REPO, `departments/${department}/src`)),
    ].join(delimiter),
    OPSYS_DEPARTMENTS: resolve(REPO, "departments"),
  };
}

async function waitReady(child: ChildProcess): Promise<void> {
  await new Promise<void>((resolveReady, reject) => {
    let output = "";
    const timeout = setTimeout(
      () => reject(new Error("CFO Python fixture startup timed out")),
      15_000,
    );
    const finish = (error?: Error) => {
      clearTimeout(timeout);
      if (error) {
        reject(error);
      } else {
        resolveReady();
      }
    };
    child.stdout?.setEncoding("utf8").on("data", (chunk: string) => {
      output += chunk;
      if (output.includes("READY")) {
        finish();
      }
    });
    child.stderr?.setEncoding("utf8").on("data", (chunk: string) => {
      // Do not surface fixture stderr: it may contain local paths or runtime diagnostics.
      if (chunk.includes("Traceback") || chunk.includes("ERROR")) {
        finish(new Error("CFO Python fixture failed during startup"));
      }
    });
    child.once("error", () => finish(new Error("CFO Python fixture could not start")));
    child.once("exit", () => finish(new Error("CFO Python fixture exited before readiness")));
  });
}

async function stopChild(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return;
  }
  child.kill("SIGTERM");
  const stopped = await new Promise<boolean>((resolveStop) => {
    const timeout = setTimeout(() => resolveStop(false), 2_000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolveStop(true);
    });
  });
  if (stopped || child.exitCode !== null || child.signalCode !== null) {
    return;
  }
  child.kill("SIGKILL");
  const killed = await new Promise<boolean>((resolveKill) => {
    const timeout = setTimeout(() => resolveKill(false), 2_000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolveKill(true);
    });
  });
  if (!killed) {
    throw new Error("CFO fixture process survived SIGKILL");
  }
}

afterEach(async () => {
  const manager = getSessionMcpRuntimeManagerForTesting();
  await manager.disposeSession("opsys-cfo-grant-real-http");
  await manager.disposeSession("opsys-cfo-grant-stale-profile");
  for (const child of children.splice(0)) {
    await stopChild(child);
  }
  await Promise.all(
    tempDirs.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

function config(base: Record<string, string>, revision: number | undefined): OpenClawConfig {
  const admission = {
    profileId: PROFILE_ID,
    ...(revision === undefined ? {} : { profileRevision: revision }),
  };
  return {
    agents: { entries: { [AGENT_ID]: { opsysRuntimeAdmission: admission } } },
    plugins: { enabled: false },
    mcp: {
      servers: {
        opsys_m5: {
          url: `${base.baseUrl}${base.businessPath}`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: new URL(base.baseUrl).origin },
          headers: { Authorization: `Bearer ${PUBLIC_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
        [`opsys_runtime_${PROFILE_ID}`]: {
          url: `${base.baseUrl}${base.privateIssuerPath}`,
          transport: "streamable-http",
          transportSecurity: { insecureHttpOrigin: new URL(base.baseUrl).origin },
          headers: { Authorization: `Bearer ${PRIVATE_TOKEN}` },
          connectionTimeoutMs: 5_000,
          requestTimeoutMs: 10_000,
        },
      },
    },
  } satisfies OpenClawConfig;
}

describe("CFO grant ticket through Core runtime and real Python MCP HTTP", () => {
  it("issues privately from host profile config, attaches one-use meta, and refuses stale revision", async () => {
    const python = requiredPython();
    const temp = await mkdtemp(resolve(tmpdir(), "opsys-cfo-grant-http-"));
    tempDirs.push(temp);
    const manifestPath = resolve(temp, "fixture.json");
    const child = spawn(python, [FIXTURE, "--manifest", manifestPath], {
      cwd: REPO,
      env: fixtureEnv(),
      stdio: ["ignore", "pipe", "pipe"],
    });
    children.push(child);
    await waitReady(child);
    const manifestStat = await stat(manifestPath);
    expect(manifestStat.mode & 0o777).toBe(0o600);
    const fixture = JSON.parse(await readFile(manifestPath, "utf8")) as Record<string, string>;
    expect(fixture.syntheticOnly).toBe(true);
    expect(fixture.businessHandlerSource).toBe(
      resolve(REPO, "departments/m05-financecore/src/m5_financecore/outils.py"),
    );

    const runtime = await getOrCreateSessionMcpRuntime({
      sessionId: "opsys-cfo-grant-real-http",
      sessionKey: SESSION_KEY,
      workspaceDir: temp,
      cfg: config(fixture, Number(fixture.profileRevision)),
    });
    const result = await runtime.callTool("opsys_m5", TOOL, ARGS);
    expect(result.isError).not.toBe(true);
    const resultContent = result.content[0];
    if (!resultContent || resultContent.type !== "text") {
      throw new Error("CFO MCP business tool returned no textual result");
    }
    const accepted = JSON.parse(resultContent.text) as { ok?: boolean; resultat?: unknown };
    expect(accepted.ok).toBe(true);
    expect(accepted.resultat, JSON.stringify(accepted.resultat)).toMatchObject({ accepte: true });
    const report = (
      accepted.resultat as {
        resultat: {
          rubriques: Array<{ source_refs?: unknown }>;
          reference: { snapshot_id: string };
        };
      }
    ).resultat;
    expect(report.rubriques).toHaveLength(25);
    expect(report.reference.snapshot_id).toBeTruthy();
    expect(report.rubriques[4]?.source_refs).toMatchObject({
      colonnes: ["departement", "registre", "taille", "tete"],
    });
    if (typeof runtime.listTools !== "function") {
      throw new Error("CFO MCP runtime does not expose a public tool catalog");
    }
    const publicTools = await runtime.listTools("opsys_m5");
    expect(publicTools.tools.map((tool) => tool.name)).not.toContain("opsys_runtime_cfo_ticket");
    expect(JSON.stringify(result)).not.toContain(fixture.privateBearer);
    expect(JSON.stringify(result)).not.toContain(fixture.businessBearer);

    await expect(
      createOpsysCfoGrantTicketMeta({
        config: config(fixture, Number(fixture.profileRevision) + 1),
        serverName: OPSYS_CFO_MCP_SERVER,
        toolName: TOOL,
        toolParams: ARGS,
        sessionKey: SESSION_KEY,
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow(/issuer returned an invalid or expired ticket/);
    await unlink(manifestPath);
  });
});
