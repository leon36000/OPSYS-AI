// INERT candidate: no native execution admitted. All inputs and people are fictitious.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const native = vi.hoisted(() => ({ publish: vi.fn() }));
vi.mock("./update-cli/update-command-service-publication.js", () => ({
  withGatewayRuntimeArtifactPublication: native.publish,
}));

import { runOpsysMetierCliWithPublication } from "./opsys-metier-cli.js";

type Publisher = (assertCurrent: () => Promise<void>) => Promise<void>;
const roots: string[] = [];

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "opsys-generation-bridge-fictif-"));
  roots.push(root);
  const software = path.join(root, "software");
  const generation = path.join(software, "generations", "generation-fictive");
  const source = path.join(generation, "source");
  const venv = path.join(generation, "venv");
  const python = path.join(venv, "bin", "python");
  const core = path.join(root, "core");
  const dir = path.join(root, "state", "opsys");
  for (const directory of [source, path.dirname(python), core, dir]) {
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  }
  fs.writeFileSync(python, "#!/bin/sh\n# fictif: true; never execute\nexit 99\n", { mode: 0o555 });
  const manifest = path.join(generation, "generation.json");
  fs.writeFileSync(
    manifest,
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
  const config = path.join(dir, "metier.json");
  const previous = Buffer.from(
    JSON.stringify(
      {
        actif: true,
        dossier: "/previous/source",
        hote: "127.0.0.1",
        port: 8765,
        commande: ["/previous/python", "-m", "opsys.serveur_mcp", "--http", "--port", "8765"],
        commande_cli: ["/previous/python", "-m", "opsys.cli"],
        env: { OPSYS_HOME: "/instance-fictive", CHOIX_FICTIF: "conserver sans evaluation" },
        delai_pret_ms: 120000,
        option_future_fictive: { conserver: true },
      },
      null,
      3,
    ) + "\n",
  );
  fs.writeFileSync(config, previous, { mode: 0o600 });
  const chunks: string[] = [];
  const deps = {
    root: core,
    dir,
    env: { HOME: path.join(root, "home"), OPENCLAW_PROFILE: "opsys" },
    stderr: { write: (text: string) => chunks.push(text) },
  };
  const invocation = {
    kind: "metier" as const,
    args: ["instance", "publier-generation", "--generation", generation, "--logiciel", software],
  };
  return {
    root,
    software,
    generation,
    source,
    venv,
    python,
    core,
    dir,
    manifest,
    config,
    previous,
    chunks,
    deps,
    invocation,
  };
}

beforeEach(() => {
  native.publish.mockReset();
  native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
    await publish(async () => {});
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const root of roots.splice(0)) {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

describe("public metier generation publication bridge", () => {
  it("declares the Python physical scope and refuses before effects when the existing owner refuses", async () => {
    const f = fixture();
    native.publish.mockRejectedValue(new Error("fictif: real owner held"));
    const code = await runOpsysMetierCliWithPublication(f.invocation, f.deps);
    expect(code).toBe(1);
    expect(fs.readFileSync(f.config)).toEqual(f.previous);
    expect(native.publish).toHaveBeenCalledWith(
      expect.objectContaining({
        root: f.core,
        python: { softwareRoot: f.software, candidate: f.generation },
      }),
      expect.any(Function),
    );
    expect(fs.readdirSync(f.dir)).toEqual(["metier.json"]);
  });

  it("publishes only runtime paths under the held owner and preserves env, server arguments and options", async () => {
    const f = fixture();
    const order: string[] = [];
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      order.push("held");
      await publish(async () => {
        order.push("fresh");
      });
      expect(JSON.parse(fs.readFileSync(f.config, "utf8")).dossier).toBe(f.source);
      order.push("released");
    });
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(0);
    const before = JSON.parse(f.previous.toString());
    const after = JSON.parse(fs.readFileSync(f.config, "utf8"));
    expect(after).toEqual({
      ...before,
      dossier: f.source,
      commande: [f.python, ...before.commande.slice(1)],
      commande_cli: [f.python, ...before.commande_cli.slice(1)],
    });
    expect(fs.statSync(f.config).mode & 0o777).toBe(0o600);
    expect(order[0]).toBe("held");
    expect(order.at(-1)).toBe("released");
    expect(fs.readdirSync(f.dir)).toEqual(["metier.json"]);
  });

  it("joins byte-exact rollback and temporary cleanup before owner release after post-rename invalidation", async () => {
    const f = fixture();
    let releasedBytes: Buffer | undefined;
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      let observations = 0;
      try {
        await publish(async () => {
          observations += 1;
          if (observations === 3) {
            throw new Error("fictif: invalidated after rename");
          }
        });
      } finally {
        releasedBytes = fs.readFileSync(f.config);
        expect(fs.readdirSync(f.dir)).toEqual(["metier.json"]);
      }
    });
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
    expect(releasedBytes).toEqual(f.previous);
    expect(fs.readFileSync(f.config)).toEqual(f.previous);
  });

  it("refuses an absent or foreign instance config without creating or replacing it", async () => {
    const f = fixture();
    fs.unlinkSync(f.config);
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
    expect(fs.existsSync(f.config)).toBe(false);
    const foreign = Buffer.from('{"actif":true,"commande":["foreign"],"fictif":true}\n');
    fs.writeFileSync(f.config, foreign);
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
    expect(fs.readFileSync(f.config)).toEqual(foreign);
  });

  it.each([new Error("fictif: primary publication failure"), undefined])(
    "preserves an exact primary rejection together with cleanup failure before owner release: %s",
    async (primary) => {
      const f = fixture();
      const cleanup = new Error("fictif: pending cleanup EIO");
      const rejectPrimary = vi.fn<() => Promise<void>>().mockRejectedValue(primary);
      const remove = fs.rmSync;
      let released = false;
      const capture: { value?: { error: unknown; released: boolean; bytes: Buffer } } = {};
      let cleanupBeforeRelease = false;
      vi.spyOn(fs, "rmSync").mockImplementation((target, options) => {
        if (String(target).includes(".metier-generation-")) {
          cleanupBeforeRelease = !released;
          throw cleanup;
        }
        remove(target, options);
      });
      native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
        let observations = 0;
        try {
          await publish(async () => {
            observations += 1;
            if (observations === 2) {
              await rejectPrimary();
            }
          });
        } catch (error) {
          capture.value = { error, released, bytes: fs.readFileSync(f.config) };
          throw error;
        } finally {
          released = true;
        }
      });
      expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
      expect(rejectPrimary).toHaveBeenCalledOnce();
      expect(cleanupBeforeRelease).toBe(true);
      const observed = capture.value;
      expect(observed).toBeDefined();
      if (!observed) {
        throw new Error("Expected the owner to observe callback failure before release.");
      }
      expect(observed.released).toBe(false);
      expect(observed.bytes).toEqual(f.previous);
      expect(observed.error).toBeInstanceOf(AggregateError);
      if (!(observed.error instanceof AggregateError)) {
        throw new Error("Expected both exact failures to remain observable.");
      }
      expect(observed.error.errors).toEqual([primary, cleanup]);
      expect(observed.error.errors[0]).toBe(primary);
      expect(observed.error.errors[1]).toBe(cleanup);
      expect(observed.error.cause).toBe(primary);
      expect(released).toBe(true);
      expect(fs.readFileSync(f.config)).toEqual(f.previous);
      expect(f.chunks.join("")).not.toContain("fictif: primary publication failure");
      expect(f.chunks.join("")).not.toContain("fictif: pending cleanup EIO");
    },
  );

  it("retains the previous-byte rollback artifact without clobbering a foreign concurrent config", async () => {
    const f = fixture();
    const foreign = Buffer.from('{"fictif":true,"foreignConcurrentWriter":true}\n');
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      let observations = 0;
      await publish(async () => {
        observations += 1;
        if (observations === 3) {
          fs.writeFileSync(f.config, foreign);
          throw new Error("fictif: foreign config writer");
        }
      });
    });
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
    expect(fs.readFileSync(f.config)).toEqual(foreign);
    const rollback = fs.readdirSync(f.dir).filter((name) => name.startsWith(".metier-rollback-"));
    expect(rollback).toHaveLength(1);
    expect(fs.readFileSync(path.join(f.dir, rollback[0]!))).toEqual(f.previous);
    expect(f.chunks.join("")).toContain("restauration incomplète");
  });

  it("reports committed publication and retains old bytes when private cleanup fails after owner fulfillment", async () => {
    const f = fixture();
    const original = fs.unlinkSync;
    let injected = false;
    let ownerFulfilled = false;
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      await publish(async () => {});
      ownerFulfilled = true;
    });
    vi.spyOn(fs, "unlinkSync").mockImplementation((target) => {
      if (!injected && String(target).includes(".metier-rollback-")) {
        expect(ownerFulfilled).toBe(true);
        injected = true;
        throw new Error("fictif: one cleanup EIO");
      }
      original(target);
    });
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(0);
    expect(injected).toBe(true);
    expect(JSON.parse(fs.readFileSync(f.config, "utf8")).dossier).toBe(f.source);
    const backups = fs.readdirSync(f.dir).filter((name) => name.startsWith(".metier-rollback-"));
    expect(backups).toHaveLength(1);
    expect(fs.readFileSync(path.join(f.dir, backups[0]!))).toEqual(f.previous);
    expect(f.chunks.join("")).toContain("publication effectuée");
    expect(f.chunks.join("")).toContain("nettoyage privé incomplet");
    expect(f.chunks.join("")).toContain(path.join(f.dir, backups[0]!));
  });

  it("retains old bytes through all owner awaits and joins backup-only cleanup before public return", async () => {
    const f = fixture();
    let finishOwner!: () => void;
    let callbackDone!: () => void;
    const ownerGate = new Promise<void>((resolve) => {
      finishOwner = resolve;
    });
    const observed = new Promise<void>((resolve) => {
      callbackDone = resolve;
    });
    let ownerFulfilled = false;
    let cleanupJoined = false;
    const original = fs.unlinkSync;
    vi.spyOn(fs, "unlinkSync").mockImplementation((target) => {
      if (String(target).includes(".metier-rollback-")) {
        expect(ownerFulfilled).toBe(true);
        cleanupJoined = true;
      }
      original(target);
    });
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      await publish(async () => {});
      callbackDone();
      await ownerGate;
      ownerFulfilled = true;
    });
    let returned = false;
    const result = runOpsysMetierCliWithPublication(f.invocation, f.deps).then((code) => {
      returned = true;
      expect(cleanupJoined).toBe(true);
      return code;
    });
    await observed;
    expect(returned).toBe(false);
    const backups = fs.readdirSync(f.dir).filter((name) => name.startsWith(".metier-rollback-"));
    expect(backups).toHaveLength(1);
    expect(fs.readFileSync(path.join(f.dir, backups[0]!))).toEqual(f.previous);
    finishOwner();
    expect(await result).toBe(0);
    expect(fs.readdirSync(f.dir)).toEqual(["metier.json"]);
  });

  it("validates retained backup identity after owner fulfillment and preserves a foreign replacement", async () => {
    const f = fixture();
    const foreign = Buffer.from("fictif: foreign backup bytes\n");
    let backup = "";
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      await publish(async () => {});
      const names = fs.readdirSync(f.dir).filter((name) => name.startsWith(".metier-rollback-"));
      expect(names).toHaveLength(1);
      backup = path.join(f.dir, names[0]!);
      fs.unlinkSync(backup);
      fs.writeFileSync(backup, foreign, { mode: 0o600 });
    });
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(0);
    expect(fs.readFileSync(backup)).toEqual(foreign);
    expect(JSON.parse(fs.readFileSync(f.config, "utf8")).dossier).toBe(f.source);
    expect(f.chunks.join("")).toContain("nettoyage privé incomplet");
  });

  it("revalidates the config parent after owner fulfillment without touching a replacement directory", async () => {
    const f = fixture();
    const moved = path.join(f.root, "retained-original-parent");
    let backupName = "";
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      await publish(async () => {});
      const names = fs.readdirSync(f.dir).filter((name) => name.startsWith(".metier-rollback-"));
      expect(names).toHaveLength(1);
      backupName = names[0]!;
      fs.renameSync(f.dir, moved);
      fs.mkdirSync(f.dir, { mode: 0o700 });
      fs.writeFileSync(path.join(f.dir, backupName), "fictif: replacement parent", { mode: 0o600 });
    });
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(0);
    expect(fs.readFileSync(path.join(moved, backupName))).toEqual(f.previous);
    expect(fs.readFileSync(path.join(f.dir, backupName), "utf8")).toBe(
      "fictif: replacement parent",
    );
    expect(JSON.parse(fs.readFileSync(path.join(moved, "metier.json"), "utf8")).dossier).toBe(
      f.source,
    );
    expect(f.chunks.join("")).toContain("nettoyage privé incomplet");
  });

  it("refuses source escape, non-prepared manifests and generation symlink aliases", async () => {
    const f = fixture();
    const raw = JSON.parse(fs.readFileSync(f.manifest, "utf8"));
    fs.chmodSync(f.manifest, 0o600);
    fs.writeFileSync(f.manifest, JSON.stringify({ ...raw, source: f.root }));
    fs.chmodSync(f.manifest, 0o400);
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
    fs.chmodSync(f.manifest, 0o600);
    fs.writeFileSync(f.manifest, JSON.stringify({ ...raw, state: "pending" }));
    fs.chmodSync(f.manifest, 0o400);
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
    const alias = path.join(f.software, "generations", "alias-fictif");
    fs.symlinkSync(f.generation, alias);
    const args = [...f.invocation.args];
    args[3] = alias;
    expect(await runOpsysMetierCliWithPublication({ kind: "metier", args }, f.deps)).toBe(1);
    expect(fs.readFileSync(f.config)).toEqual(f.previous);
  });

  it("revalidates the manifest across owner awaits before the first config write", async () => {
    const f = fixture();
    native.publish.mockImplementation(async (_params: unknown, publish: Publisher) => {
      await publish(async () => {
        fs.chmodSync(f.manifest, 0o600);
        fs.writeFileSync(f.manifest, '{"state":"changed-fictif"}\n');
        fs.chmodSync(f.manifest, 0o400);
      });
    });
    expect(await runOpsysMetierCliWithPublication(f.invocation, f.deps)).toBe(1);
    expect(fs.readFileSync(f.config)).toEqual(f.previous);
  });

  it("refuses exec-shell callers, another profile and arbitrary command arguments before owner acquisition", async () => {
    const f = fixture();
    expect(
      await runOpsysMetierCliWithPublication(f.invocation, {
        ...f.deps,
        env: { ...f.deps.env, OPENCLAW_SHELL: "exec" },
      }),
    ).toBe(1);
    expect(
      await runOpsysMetierCliWithPublication(f.invocation, {
        ...f.deps,
        env: { ...f.deps.env, OPENCLAW_PROFILE: "another-fictif" },
      }),
    ).toBe(1);
    expect(
      await runOpsysMetierCliWithPublication(
        {
          kind: "metier",
          args: [...f.invocation.args, "--exec", "/foreign/fictif"],
        },
        f.deps,
      ),
    ).toBe(1);
    expect(native.publish).not.toHaveBeenCalled();
    expect(fs.readFileSync(f.config)).toEqual(f.previous);
  });

  it("keeps the existing synchronous forwarding behavior for ordinary commands", async () => {
    const f = fixture();
    const launcher = vi.fn(() => ({ status: 3, signal: null }));
    expect(
      await runOpsysMetierCliWithPublication(
        { kind: "metier", args: ["verifier"] },
        {
          ...f.deps,
          spawnSync: launcher as unknown as typeof spawnSync,
        },
      ),
    ).toBe(3);
    expect(launcher).toHaveBeenCalledOnce();
    expect(native.publish).not.toHaveBeenCalled();
  });
});

describe("real installer public caller", () => {
  it.each([0, 1])(
    "calls only the public Core publisher and preserves refusal, fake Node exit %s",
    (exit) => {
      const f = fixture();
      const installer = fileURLToPath(new URL("../../../install/install.sh", import.meta.url));
      const origin = path.join(f.root, "source Core fictif");
      fs.mkdirSync(path.join(origin, "core"), { recursive: true });
      fs.writeFileSync(path.join(origin, "core", "openclaw.mjs"), "// fictif: true\n");
      const bin = path.join(f.root, "bin");
      fs.mkdirSync(bin);
      const log = path.join(f.root, "node-argv-fictif");
      fs.writeFileSync(
        path.join(bin, "node"),
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$FICTIF_NODE_LOG"\nexit "$FICTIF_NODE_EXIT"\n',
        { mode: 0o700 },
      );
      const result = spawnSync(
        "bash",
        [installer, "--publier-generation", f.generation, "--source", origin],
        {
          env: {
            PATH: `${bin}:/usr/bin:/bin`,
            HOME: path.join(f.root, "home"),
            OPSYS_LOGICIEL: f.software,
            FICTIF_NODE_LOG: log,
            FICTIF_NODE_EXIT: String(exit),
          },
          encoding: "utf8",
        },
      );
      expect(result.status).toBe(exit);
      expect(fs.readFileSync(log, "utf8").trimEnd().split("\n")).toEqual([
        path.join(origin, "core", "openclaw.mjs"),
        "--profile",
        "opsys",
        "metier",
        "instance",
        "publier-generation",
        "--generation",
        f.generation,
        "--logiciel",
        f.software,
      ]);
      expect(fs.readFileSync(f.config)).toEqual(f.previous);
      expect(fs.existsSync(path.join(f.software, "venv"))).toBe(false);
    },
  );
});
