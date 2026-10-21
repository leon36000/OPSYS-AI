// Covers the state directory the service files of the opsys profile live in when the environment carries the
// profile but no explicit OPENCLAW_STATE_DIR (T0.7 lot 3): the instance directory, or the former profile
// directory until Doctor moves it. Every other profile keeps the generic `.openclaw-<profile>` rule.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { withTempDirSync } from "../test-helpers/temp-dir.js";
import { resolveGatewayStateDir, resolveGatewayTaskScriptPath } from "./paths.js";

const DIR_LINK_TYPE = process.platform === "win32" ? "junction" : "dir";

function withHome(run: (home: string) => void): void {
  withTempDirSync({ prefix: "opsys-daemon-paths-" }, run);
}

function seedState(dir: string): void {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, ".env"), "OPSYS_MCP_JETON=fictif-0123456789abcdef\n", "utf8");
}

describe("resolveGatewayStateDir for the opsys profile", () => {
  it("is the instance directory on a new poste", () => {
    withHome((home) => {
      expect(resolveGatewayStateDir({ HOME: home, OPENCLAW_PROFILE: "opsys" })).toBe(
        path.join(home, ".opsys", "core"),
      );
    });
  });

  it("is the former profile directory while it is the only one that holds state", () => {
    withHome((home) => {
      const legacy = path.join(home, ".openclaw-opsys");
      seedState(legacy);

      expect(resolveGatewayStateDir({ HOME: home, OPENCLAW_PROFILE: "opsys" })).toBe(legacy);
    });
  });

  it("is the instance directory once it holds the state, whatever sits at the former path", () => {
    withHome((home) => {
      const stateDir = path.join(home, ".opsys", "core");
      seedState(stateDir);
      fs.symlinkSync(stateDir, path.join(home, ".openclaw-opsys"), DIR_LINK_TYPE);

      expect(resolveGatewayStateDir({ HOME: home, OPENCLAW_PROFILE: "opsys" })).toBe(stateDir);
    });
  });

  it("puts the task script of the Windows service in the state directory", () => {
    withHome((home) => {
      expect(resolveGatewayTaskScriptPath({ HOME: home, OPENCLAW_PROFILE: "opsys" })).toBe(
        path.join(home, ".opsys", "core", "gateway.cmd"),
      );
    });
  });

  it("still lets an explicit OPENCLAW_STATE_DIR win", () => {
    withHome((home) => {
      seedState(path.join(home, ".openclaw-opsys"));

      expect(
        resolveGatewayStateDir({
          HOME: home,
          OPENCLAW_PROFILE: "opsys",
          OPENCLAW_STATE_DIR: path.join(home, "custom"),
        }),
      ).toBe(path.join(home, "custom"));
    });
  });

  it("leaves the other profiles on the generic rule, mixed case included", () => {
    withHome((home) => {
      for (const profile of ["rescue", "Opsys", "opsys2"]) {
        expect(resolveGatewayStateDir({ HOME: home, OPENCLAW_PROFILE: profile })).toBe(
          path.join(home, `.openclaw-${profile}`),
        );
      }
      expect(resolveGatewayStateDir({ HOME: home })).toBe(path.join(home, ".openclaw"));
    });
  });
});
