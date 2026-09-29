// Covers the OPSYS instance layout: the canonical state directory of the `opsys` profile, the fallback to
// its former directory until Doctor moves it, and the config file names.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { withTempDirSync } from "../test-helpers/temp-dir.js";
import {
  dirHasEntries,
  isOpsysProfile,
  OPSYS_CONFIG_FILENAME,
  OPSYS_LEGACY_CONFIG_FILENAME,
  resolveLegacyOpsysProfileStateDir,
  resolveOpsysConfigPath,
  resolveOpsysCoreStateDir,
  resolveOpsysProfileStateDir,
} from "./opsys-instance.js";

const DIR_LINK_TYPE = process.platform === "win32" ? "junction" : "dir";

function withHome(run: (home: string) => void): void {
  withTempDirSync({ prefix: "opsys-instance-" }, run);
}

function seedState(dir: string): void {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, ".env"), "OPSYS_MCP_JETON=fictif-0123456789abcdef\n", "utf8");
}

describe("OPSYS instance directories", () => {
  it("puts the core state in the instance directory and names the former profile directory", () => {
    expect(resolveOpsysCoreStateDir("/home/marie")).toBe(path.join("/home/marie", ".opsys", "core"));
    expect(resolveLegacyOpsysProfileStateDir("/home/marie")).toBe(
      path.join("/home/marie", ".openclaw-opsys"),
    );
  });

  it("recognizes the exact profile name only", () => {
    expect(isOpsysProfile("opsys")).toBe(true);
    expect(isOpsysProfile(" opsys ")).toBe(true);
    for (const other of ["OPSYS", "Opsys", "opsys2", "opsys-dev", "default", "", undefined, null]) {
      expect(isOpsysProfile(other)).toBe(false);
    }
  });
});

describe("dirHasEntries", () => {
  it("is true for a directory that holds something and false for everything else", () => {
    withHome((home) => {
      const empty = path.join(home, "empty");
      const full = path.join(home, "full");
      const file = path.join(home, "file");
      fs.mkdirSync(empty);
      seedState(full);
      fs.writeFileSync(file, "x", "utf8");

      expect(dirHasEntries(full)).toBe(true);
      expect(dirHasEntries(empty)).toBe(false);
      expect(dirHasEntries(file)).toBe(false);
      expect(dirHasEntries(path.join(home, "missing"))).toBe(false);
    });
  });
});

describe("resolveOpsysProfileStateDir", () => {
  it("is the canonical directory on a new poste", () => {
    withHome((home) => {
      expect(resolveOpsysProfileStateDir(home)).toBe(path.join(home, ".opsys", "core"));
    });
  });

  it("keeps the former profile directory while it is the only one that holds state", () => {
    withHome((home) => {
      const legacy = path.join(home, ".openclaw-opsys");
      seedState(legacy);

      expect(resolveOpsysProfileStateDir(home)).toBe(legacy);
    });
  });

  it("prefers the canonical directory once it holds state, even next to the former one", () => {
    withHome((home) => {
      const canonical = path.join(home, ".opsys", "core");
      seedState(canonical);
      seedState(path.join(home, ".openclaw-opsys"));

      expect(resolveOpsysProfileStateDir(home)).toBe(canonical);
    });
  });

  it("does not let an empty canonical directory hide the former state", () => {
    withHome((home) => {
      const legacy = path.join(home, ".openclaw-opsys");
      fs.mkdirSync(path.join(home, ".opsys", "core"), { recursive: true });
      seedState(legacy);

      expect(resolveOpsysProfileStateDir(home)).toBe(legacy);
    });
  });

  it("ignores an empty former directory", () => {
    withHome((home) => {
      fs.mkdirSync(path.join(home, ".openclaw-opsys"));

      expect(resolveOpsysProfileStateDir(home)).toBe(path.join(home, ".opsys", "core"));
    });
  });

  it("is the canonical directory once Doctor left a link at the former path", () => {
    withHome((home) => {
      const canonical = path.join(home, ".opsys", "core");
      seedState(canonical);
      fs.symlinkSync(canonical, path.join(home, ".openclaw-opsys"), DIR_LINK_TYPE);

      expect(resolveOpsysProfileStateDir(home)).toBe(canonical);
    });
  });
});

describe("resolveOpsysConfigPath", () => {
  it("names opsys.json for a new instance", () => {
    withHome((stateDir) => {
      expect(resolveOpsysConfigPath(stateDir)).toBe(path.join(stateDir, OPSYS_CONFIG_FILENAME));
    });
  });

  it("keeps reading openclaw.json when it is the only config file", () => {
    withHome((stateDir) => {
      fs.writeFileSync(path.join(stateDir, OPSYS_LEGACY_CONFIG_FILENAME), "{}\n", "utf8");

      expect(resolveOpsysConfigPath(stateDir)).toBe(
        path.join(stateDir, OPSYS_LEGACY_CONFIG_FILENAME),
      );
    });
  });

  it("prefers opsys.json when both exist", () => {
    withHome((stateDir) => {
      fs.writeFileSync(path.join(stateDir, OPSYS_LEGACY_CONFIG_FILENAME), "{}\n", "utf8");
      fs.writeFileSync(path.join(stateDir, OPSYS_CONFIG_FILENAME), "{}\n", "utf8");

      expect(resolveOpsysConfigPath(stateDir)).toBe(path.join(stateDir, OPSYS_CONFIG_FILENAME));
    });
  });
});
