// Covers what `--profile opsys` projects (T0.7 lot 3): the OPSYS instance directory as state, opsys.json as
// config (an existing openclaw.json is still read), the former profile directory until Doctor moves it, and
// the guarantee that every other profile keeps the generic rule.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { withTempDirSync } from "../test-helpers/temp-dir.js";
import { applyCliProfileEnv } from "./profile.js";
import {
  listCanonicalProfileConfigPaths,
  resolveProfileConfigPath,
  resolveProfileStateDir,
} from "./profile-utils.js";

const DIR_LINK_TYPE = process.platform === "win32" ? "junction" : "dir";

function withHome(run: (home: string) => void): void {
  withTempDirSync({ prefix: "opsys-profile-" }, run);
}

function seedState(dir: string, ...names: string[]): void {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, ".env"), "OPSYS_MCP_JETON=fictif-0123456789abcdef\n", "utf8");
  for (const name of names) {
    fs.writeFileSync(path.join(dir, name), "{}\n", "utf8");
  }
}

function project(home: string, env: Record<string, string | undefined> = {}) {
  applyCliProfileEnv({ profile: "opsys", env, homedir: () => home });
  return env;
}

describe("resolveProfileStateDir for the opsys profile", () => {
  it("is the OPSYS instance directory, not ~/.openclaw-opsys", () => {
    withHome((home) => {
      expect(resolveProfileStateDir("opsys", {}, () => home)).toBe(
        path.join(home, ".opsys", "core"),
      );
    });
  });

  it("stays the generic rule for every other profile, mixed case included", () => {
    withHome((home) => {
      for (const profile of ["work", "dev", "Opsys", "OPSYS", "opsys2"]) {
        expect(resolveProfileStateDir(profile, {}, () => home)).toBe(
          path.join(home, `.openclaw-${profile}`),
        );
      }
      expect(resolveProfileStateDir("default", {}, () => home)).toBe(path.join(home, ".openclaw"));
    });
  });
});

describe("applyCliProfileEnv for the opsys profile", () => {
  it("projects the instance directory and opsys.json for a new instance", () => {
    withHome((home) => {
      const env = project(home);

      const stateDir = path.join(home, ".opsys", "core");
      expect(env.OPENCLAW_PROFILE).toBe("opsys");
      expect(env.OPENCLAW_STATE_DIR).toBe(stateDir);
      expect(env.OPENCLAW_CONFIG_PATH).toBe(path.join(stateDir, "opsys.json"));
    });
  });

  it("keeps reading an openclaw.json that is the only config file", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      seedState(stateDir, "openclaw.json");

      const env = project(home);

      expect(env.OPENCLAW_STATE_DIR).toBe(stateDir);
      expect(env.OPENCLAW_CONFIG_PATH).toBe(path.join(stateDir, "openclaw.json"));
    });
  });

  it("prefers opsys.json when both config files exist", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      seedState(stateDir, "openclaw.json", "opsys.json");

      expect(project(home).OPENCLAW_CONFIG_PATH).toBe(path.join(stateDir, "opsys.json"));
    });
  });

  it("uses the former profile directory, and its openclaw.json, until Doctor moves the state", () => {
    withHome((home) => {
      const legacy = path.join(home, ".openclaw-opsys");
      seedState(legacy, "openclaw.json");

      const env = project(home);

      expect(env.OPENCLAW_STATE_DIR).toBe(legacy);
      expect(env.OPENCLAW_CONFIG_PATH).toBe(path.join(legacy, "openclaw.json"));
    });
  });

  it("uses the instance directory again once Doctor moved the state and left a link", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      seedState(stateDir, "openclaw.json");
      fs.symlinkSync(stateDir, path.join(home, ".openclaw-opsys"), DIR_LINK_TYPE);

      const env = project(home);

      expect(env.OPENCLAW_STATE_DIR).toBe(stateDir);
      expect(env.OPENCLAW_CONFIG_PATH).toBe(path.join(stateDir, "openclaw.json"));
    });
  });

  it("does not override an explicit state directory or config path", () => {
    withHome((home) => {
      const env = project(home, {
        OPENCLAW_STATE_DIR: "/custom",
        OPENCLAW_CONFIG_PATH: "/custom/mine.json",
      });

      expect(env.OPENCLAW_STATE_DIR).toBe("/custom");
      expect(env.OPENCLAW_CONFIG_PATH).toBe("/custom/mine.json");
    });
  });

  it("replaces the opsys selectors when another profile is selected on top of them", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      for (const inheritedConfig of ["opsys.json", "openclaw.json"]) {
        seedState(stateDir, inheritedConfig);
        const env: Record<string, string | undefined> = {
          OPENCLAW_PROFILE: "opsys",
          OPENCLAW_STATE_DIR: stateDir,
          OPENCLAW_CONFIG_PATH: path.join(stateDir, inheritedConfig),
        };

        applyCliProfileEnv({ profile: "work", env, homedir: () => home });

        const workDir = path.join(home, ".openclaw-work");
        expect(env.OPENCLAW_PROFILE).toBe("work");
        expect(env.OPENCLAW_STATE_DIR).toBe(workDir);
        expect(env.OPENCLAW_CONFIG_PATH).toBe(path.join(workDir, "openclaw.json"));
      }
    });
  });

  it("keeps the generic projection for the other profiles", () => {
    withHome((home) => {
      const env: Record<string, string | undefined> = {};

      applyCliProfileEnv({ profile: "work", env, homedir: () => home });

      expect(env.OPENCLAW_STATE_DIR).toBe(path.join(home, ".openclaw-work"));
      expect(env.OPENCLAW_CONFIG_PATH).toBe(path.join(home, ".openclaw-work", "openclaw.json"));
    });
  });
});

describe("profile config helpers", () => {
  it("name opsys.json first for the opsys profile and only openclaw.json for the others", () => {
    expect(listCanonicalProfileConfigPaths("opsys", "/s")).toEqual([
      path.join("/s", "opsys.json"),
      path.join("/s", "openclaw.json"),
    ]);
    expect(listCanonicalProfileConfigPaths("work", "/s")).toEqual([path.join("/s", "openclaw.json")]);
    expect(listCanonicalProfileConfigPaths("default", "/s")).toEqual([
      path.join("/s", "openclaw.json"),
    ]);
  });

  it("project the file that exists, else the canonical name", () => {
    withHome((stateDir) => {
      expect(resolveProfileConfigPath("opsys", stateDir)).toBe(path.join(stateDir, "opsys.json"));
      expect(resolveProfileConfigPath("work", stateDir)).toBe(path.join(stateDir, "openclaw.json"));
      fs.writeFileSync(path.join(stateDir, "openclaw.json"), "{}\n", "utf8");
      expect(resolveProfileConfigPath("opsys", stateDir)).toBe(path.join(stateDir, "openclaw.json"));
    });
  });
});
