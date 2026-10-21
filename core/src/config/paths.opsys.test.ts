// Covers the service-management gate for the opsys profile (T0.7 lot 3): the core installs a service only for
// the canonical state directory of a profile, so ~/.opsys/core (or the former directory until Doctor moves it)
// must count as canonical, with opsys.json or the former openclaw.json as its config file.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { withTempDirSync } from "../test-helpers/temp-dir.js";
import { isDefaultInstallIdentity } from "./paths.js";

const DIR_LINK_TYPE = process.platform === "win32" ? "junction" : "dir";

function withHome(run: (home: string) => void): void {
  withTempDirSync({ prefix: "opsys-paths-" }, run);
}

function seedState(dir: string, ...configNames: string[]): void {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, ".env"), "OPSYS_MCP_JETON=fictif-0123456789abcdef\n", "utf8");
  for (const name of configNames) {
    fs.writeFileSync(path.join(dir, name), "{}\n", "utf8");
  }
}

function opsysEnv(home: string, stateDir: string, configPath: string): NodeJS.ProcessEnv {
  return {
    HOME: home,
    OPENCLAW_PROFILE: "opsys",
    OPENCLAW_STATE_DIR: stateDir,
    OPENCLAW_CONFIG_PATH: configPath,
  };
}

describe("isDefaultInstallIdentity for the opsys profile", () => {
  it("accepts the instance directory with opsys.json", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      seedState(stateDir, "opsys.json");

      const env = opsysEnv(home, stateDir, path.join(stateDir, "opsys.json"));

      expect(isDefaultInstallIdentity(env, () => home, "linux")).toBe(true);
    });
  });

  it("accepts the instance directory with the former openclaw.json", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      seedState(stateDir, "openclaw.json");

      const env = opsysEnv(home, stateDir, path.join(stateDir, "openclaw.json"));

      expect(isDefaultInstallIdentity(env, () => home, "linux")).toBe(true);
    });
  });

  it("accepts the former profile directory until Doctor moves it", () => {
    withHome((home) => {
      const legacy = path.join(home, ".openclaw-opsys");
      seedState(legacy, "openclaw.json");

      const env = opsysEnv(home, legacy, path.join(legacy, "openclaw.json"));

      expect(isDefaultInstallIdentity(env, () => home, "linux")).toBe(true);
    });
  });

  it("accepts a service that still names the former path once Doctor left a link there", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      const legacy = path.join(home, ".openclaw-opsys");
      seedState(stateDir, "openclaw.json");
      fs.symlinkSync(stateDir, legacy, DIR_LINK_TYPE);

      const env = opsysEnv(home, legacy, path.join(legacy, "openclaw.json"));

      expect(isDefaultInstallIdentity(env, () => home, "linux")).toBe(true);
    });
  });

  it("refuses a state directory or a config file that is not the profile's own", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      seedState(stateDir, "opsys.json");

      expect(
        isDefaultInstallIdentity(
          opsysEnv(home, path.join(home, "elsewhere"), path.join(stateDir, "opsys.json")),
          () => home,
          "linux",
        ),
      ).toBe(false);
      expect(
        isDefaultInstallIdentity(
          opsysEnv(home, stateDir, path.join(home, "other-config.json")),
          () => home,
          "linux",
        ),
      ).toBe(false);
      expect(
        isDefaultInstallIdentity(
          { ...opsysEnv(home, stateDir, path.join(stateDir, "opsys.json")), OPENCLAW_HOME: home },
          () => home,
          "linux",
        ),
      ).toBe(false);
    });
  });

  it("does not turn the opsys config names into canonical names of another profile", () => {
    withHome((home) => {
      const workDir = path.join(home, ".openclaw-work");
      seedState(workDir, "opsys.json", "openclaw.json");
      const env = {
        HOME: home,
        OPENCLAW_PROFILE: "work",
        OPENCLAW_STATE_DIR: workDir,
        OPENCLAW_CONFIG_PATH: path.join(workDir, "opsys.json"),
      };

      expect(isDefaultInstallIdentity(env, () => home, "linux")).toBe(false);
      expect(
        isDefaultInstallIdentity(
          { ...env, OPENCLAW_CONFIG_PATH: path.join(workDir, "openclaw.json") },
          () => home,
          "linux",
        ),
      ).toBe(true);
    });
  });
});
