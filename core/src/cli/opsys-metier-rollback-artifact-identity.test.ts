// One INERT regression: no runtime execution authorized by this artifact.
// All filesystem paths and bytes are fictitious; the fake Python file is never run.
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

it("rejects a substituted rollback artifact before rename and never installs foreign bytes or repairs after owner release", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-rollback-identity-fictif-"));
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
  fs.writeFileSync(python, "#!/bin/sh\n# fictif: never execute\nexit 99\n", { mode: 0o555 });
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
  const foreign = Buffer.from("fictif: substituted rollback artifact, NOT original config bytes\n");
  const chunks: string[] = [];
  let observations = 0;
  let artifact = "";
  let released = false;
  let lateRename = false;
  let foreignInstalled = false;
  let bytesAtRelease: Buffer | undefined;
  let artifactAtRelease: Buffer | undefined;
  const originalRename = fs.renameSync;
  vi.spyOn(fs, "renameSync").mockImplementation((from, to) => {
    if (String(to) === file) {
      if (released) {
        lateRename = true;
      }
      if (fs.readFileSync(from).equals(foreign)) {
        foreignInstalled = true;
      }
    }
    originalRename(from, to);
  });
  native.publish.mockImplementation(
    async (
      params: { env: NodeJS.ProcessEnv; python?: { softwareRoot: string; candidate: string } },
      publish: (assertCurrent: () => Promise<void>) => Promise<void>,
    ) => {
      expect(params.env.OPENCLAW_PROFILE).toBe("opsys");
      expect(params.python).toEqual({ softwareRoot: software, candidate: generation });
      try {
        await publish(async () => {
          observations += 1;
          if (observations === 3) {
            expect(JSON.parse(fs.readFileSync(file, "utf8")).dossier).toBe(source);
            const names = fs
              .readdirSync(dir)
              .filter((name) => name.startsWith(".metier-rollback-"));
            expect(names).toHaveLength(1);
            artifact = path.join(dir, names[0]!);
            expect(fs.readFileSync(artifact)).toEqual(previous);
            fs.unlinkSync(artifact);
            fs.writeFileSync(artifact, foreign, { mode: 0o600 });
            throw new Error("fictif: rollback artifact substituted at third assertion");
          }
        });
      } finally {
        bytesAtRelease = fs.readFileSync(file);
        artifactAtRelease = fs.existsSync(artifact) ? fs.readFileSync(artifact) : undefined;
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
  expect(observations).toBe(3);
  expect(code).toBe(1);
  expect(released).toBe(true);
  expect(lateRename).toBe(false);
  expect(foreignInstalled).toBe(false);
  const current = fs.readFileSync(file);
  expect(bytesAtRelease?.equals(foreign)).toBe(false);
  expect(current.equals(foreign)).toBe(false);
  expect(current).toEqual(bytesAtRelease);
  // This is forensic FOREIGN evidence, never a trusted old-byte backup.
  expect(artifactAtRelease).toEqual(foreign);
  expect(fs.readFileSync(artifact)).toEqual(foreign);
  expect(chunks.join("")).toContain("restauration incomplète");
});
