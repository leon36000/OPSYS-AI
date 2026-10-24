// One INERT regression. Root admission is required before any execution.
// All paths, runtime bytes and instance data are fictitious; no Python child.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, expect, it, vi } from "vitest";

const native = vi.hoisted(() => ({ publish: vi.fn() }));
vi.mock("./update-cli/update-command-service-publication.js", () => ({
  withGatewayRuntimeArtifactPublication: native.publish,
}));
import { runOpsysMetierCliWithPublication } from "./opsys-metier-cli.js";

let fixtureRoot: string | undefined;
afterEach(() => {
  vi.restoreAllMocks();
  if (fixtureRoot) {
    fs.rmSync(fixtureRoot, { recursive: true, force: true });
  }
  fixtureRoot = undefined;
});

it("owner rejection after a successful callback restores before release or explicitly retains old bytes without late rollback", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-final-owner-fictif-"));
  fixtureRoot = root;
  const software = path.join(root, "software");
  const generation = path.join(software, "generations", "generation-fictive");
  const source = path.join(generation, "source");
  const venv = path.join(generation, "venv");
  const python = path.join(venv, "bin", "python");
  const dir = path.join(root, "state", "opsys");
  const core = path.join(root, "core");
  for (const directory of [source, path.dirname(python), dir, core]) {
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  }
  fs.writeFileSync(python, "#!/bin/sh\n# fictif: true; not executable by this test\nexit 99\n", {
    mode: 0o555,
  });
  fs.writeFileSync(
    path.join(generation, "generation.json"),
    JSON.stringify({
      state: "prepared",
      publication: "not-published",
      generation,
      source,
      venv,
      python,
      commit: "bdaf308db88cd18a760b04d08f5a1a59cf1be0ee",
      core_build: "not-prepared",
    }),
    { mode: 0o400 },
  );
  const file = path.join(dir, "metier.json");
  const previous = Buffer.from(
    JSON.stringify(
      {
        actif: true,
        dossier: "/previous/source-fictif",
        port: 8765,
        commande: ["/previous/python-fictif", "-m", "opsys.serveur_mcp", "--http"],
        commande_cli: ["/previous/python-fictif", "-m", "opsys.cli"],
        env: { OPSYS_HOME: "/instance-fictive", OPTION_FICTIVE: "conserver" },
      },
      null,
      3,
    ) + "\n",
  );
  fs.writeFileSync(file, previous, { mode: 0o600 });
  const chunks: string[] = [];
  let callbackSucceeded = false;
  let released = false;
  let unsafeLateRename = false;
  let bytesAtRelease: Buffer | undefined;
  let backupsAtRelease: Buffer[] = [];
  const originalRename = fs.renameSync;
  vi.spyOn(fs, "renameSync").mockImplementation((from, to) => {
    if (released && String(to) === file) {
      unsafeLateRename = true;
    }
    originalRename(from, to);
  });
  const oldByteArtifacts = () =>
    fs
      .readdirSync(dir)
      .filter((name) => name.startsWith(".metier-rollback-"))
      .map((name) => fs.readFileSync(path.join(dir, name)));
  native.publish.mockImplementation(
    async (
      params: { env: NodeJS.ProcessEnv; python?: { softwareRoot: string; candidate: string } },
      publish: (assertCurrent: () => Promise<void>) => Promise<void>,
    ) => {
      expect(params.env.OPENCLAW_PROFILE).toBe("opsys");
      expect(params.python).toEqual({ softwareRoot: software, candidate: generation });
      try {
        await publish(async () => {});
        callbackSucceeded = true;
        expect(JSON.parse(fs.readFileSync(file, "utf8")).dossier).toBe(source);
        // Faithful extra boundary: real owner asserts again AFTER awaiting publish.
        throw new Error("fictif: ownerfinalassert invalidated");
      } finally {
        bytesAtRelease = fs.readFileSync(file);
        backupsAtRelease = oldByteArtifacts();
        released = true;
      }
    },
  );
  const code = await runOpsysMetierCliWithPublication(
    {
      kind: "metier",
      args: ["instance", "publier-generation", "--generation", generation, "--logiciel", software],
    },
    {
      root: core,
      dir,
      env: { HOME: path.join(root, "home"), OPENCLAW_PROFILE: "opsys" },
      stderr: { write: (text: string) => chunks.push(text) },
    },
  );
  expect(callbackSucceeded).toBe(true);
  expect(code).toBe(1);
  expect(released).toBe(true);
  expect(unsafeLateRename).toBe(false);
  const current = fs.readFileSync(file);
  const restoredBeforeRelease =
    bytesAtRelease?.equals(previous) === true && current.equals(previous);
  const explicitIncompleteWithOldBytes =
    chunks.join("").includes("restauration incomplète") &&
    bytesAtRelease !== undefined &&
    current.equals(bytesAtRelease) &&
    backupsAtRelease.some((bytes) => bytes.equals(previous)) &&
    oldByteArtifacts().some((bytes) => bytes.equals(previous));
  expect(restoredBeforeRelease || explicitIncompleteWithOldBytes).toBe(true);
});
