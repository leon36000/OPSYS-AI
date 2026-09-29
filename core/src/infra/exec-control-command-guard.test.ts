import { describe, expect, it } from "vitest";
import {
  detectUnsafeExecControlShellCommand,
  rejectUnsafeExecControlShellCommand,
} from "./exec-control-command-guard.js";

function nestedCommandSubstitution(inner: string, depth: number): string {
  return "$( ".repeat(depth) + inner + " )".repeat(depth);
}

describe("exec control command guard", () => {
  it("rejects a control command below deeply nested command substitutions", async () => {
    const command = nestedCommandSubstitution("/approve abc123 allow-once", 5_000);

    await expect(detectUnsafeExecControlShellCommand(command)).resolves.toBe("approve");
    await expect(rejectUnsafeExecControlShellCommand(command)).rejects.toThrow(
      /exec cannot run \/approve commands/,
    );
  });

  // `opsys` is the command of OPSYS-CORE and `openclaw` its alias (PLAN T0.7 lot 2): the guard on
  // the interactive channel login must not be side-stepped by typing the other name.
  it.each([
    "openclaw channels login --channel whatsapp",
    "opsys channels login --channel whatsapp",
    "opsys channel login",
    "/home/opsys/.local/bin/opsys channels login --verbose",
    "opsys.cmd channels login",
    "pnpm exec opsys channels login --channel whatsapp --verbose",
    "npx --yes opsys channels login",
  ])("rejects the interactive channel login typed as `%s`", async (command) => {
    await expect(detectUnsafeExecControlShellCommand(command)).resolves.toBe("channel-login");
    await expect(rejectUnsafeExecControlShellCommand(command)).rejects.toThrow(
      /exec cannot run interactive OpenClaw channel login commands/,
    );
  });

  it("leaves the other `opsys` commands alone", async () => {
    await expect(detectUnsafeExecControlShellCommand("opsys channels status")).resolves.toBeNull();
    await expect(detectUnsafeExecControlShellCommand("opsys metier base etat")).resolves.toBeNull();
  });

  it("rejects commands that exceed the explanation work limit", async () => {
    const command = nestedCommandSubstitution("echo hi", 11_000);

    await expect(detectUnsafeExecControlShellCommand(command)).resolves.toBe("incomplete-analysis");
    await expect(rejectUnsafeExecControlShellCommand(command)).rejects.toThrow(
      /exceeds the command explanation work limit/,
    );
  });
});
