import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { ExpectedCliError } from "./cli/failure-output.js";
import { runOpsysMetierCliWithPublication } from "./cli/opsys-metier-cli.js";
import { runMainOrRootHelp } from "./entry.js";

// The engine launcher is proven in opsys-metier-cli.test.ts; here only the dispatch is.
vi.mock("./cli/opsys-metier-cli.js", () => ({
  runOpsysMetierCliWithPublication: vi.fn(async () => 7),
}));

describe("entry run-main boundary", () => {
  it("retains JSON console routing through process finalization", async () => {
    const runCli = vi.fn(async () => undefined);

    await runMainOrRootHelp(["node", "openclaw", "status"], {
      loadRunCli: async () => ({ runCli }),
    });

    expect(runCli).toHaveBeenCalledWith(["node", "openclaw", "status"], {
      additionalStartupTrace: expect.any(Object),
      runtimeRecoveryEnv: expect.any(Object),
      retainConsoleRoutingUntilProcessExit: true,
    });
  });

  it("hands `metier` and the retired engine commands to the launcher, never to Commander", async () => {
    const previousExitCode = process.exitCode;
    const installRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
    const runCli = vi.fn(async () => undefined);
    vi.mocked(runOpsysMetierCliWithPublication).mockClear();
    process.exitCode = undefined;
    try {
      await runMainOrRootHelp(["node", "openclaw", "metier", "verifier", "--help"], {
        loadRunCli: async () => ({ runCli }),
      });
      expect(runOpsysMetierCliWithPublication).toHaveBeenLastCalledWith(
        {
          kind: "metier",
          args: ["verifier", "--help"],
        },
        { root: installRoot },
      );
      expect(process.exitCode).toBe(7);

      await runMainOrRootHelp(["node", "openclaw", "personnes", "creer", "alice.fictive"], {
        loadRunCli: async () => ({ runCli }),
      });
      expect(runOpsysMetierCliWithPublication).toHaveBeenLastCalledWith(
        {
          kind: "moved",
          command: "personnes",
          args: ["creer", "alice.fictive"],
        },
        { root: installRoot },
      );
      expect(runOpsysMetierCliWithPublication).toHaveBeenCalledTimes(2);
      expect(runCli).not.toHaveBeenCalled();
    } finally {
      process.exitCode = previousExitCode;
    }
  });

  it("frames a command-phase failure as a command failure, not a startup failure", async () => {
    const previousExitCode = process.exitCode;
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    process.exitCode = undefined;
    try {
      await runMainOrRootHelp(["node", "openclaw", "onboard", "recommendations"], {
        loadRunCli: async () => ({
          runCli: vi.fn(async () => {
            throw new Error(
              "Multiple agents are configured, but this operation has no explicit owner.",
            );
          }),
        }),
      });
      expect(process.exitCode).toBe(1);
      expect(errorSpy).toHaveBeenCalledWith("[openclaw] The CLI command failed.");
      expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining("Could not start the CLI"));
    } finally {
      errorSpy.mockRestore();
      process.exitCode = previousExitCode;
    }
  });

  it("frames a failure before the command runs as a startup failure", async () => {
    const previousExitCode = process.exitCode;
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    process.exitCode = undefined;
    try {
      await runMainOrRootHelp(["node", "openclaw", "status"], {
        loadRunCli: async () => {
          throw new Error("cannot load run-main");
        },
      });
      expect(process.exitCode).toBe(1);
      expect(errorSpy).toHaveBeenCalledWith("[openclaw] Could not start the CLI.");
      expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining("The CLI command failed"));
    } finally {
      errorSpy.mockRestore();
      process.exitCode = previousExitCode;
    }
  });

  it("keeps expected conditions at exit 1 without crash framing", async () => {
    const previousExitCode = process.exitCode;
    const message =
      'The `openclaw workboard` command is provided by the "workboard" plugin, but that bundled plugin is disabled by default. Run `openclaw plugins enable workboard` to enable that CLI surface.';
    const error = new ExpectedCliError({
      message,
      humanOutput: message,
      machineOutput: message,
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    process.exitCode = undefined;

    try {
      await runMainOrRootHelp(["node", "openclaw", "workboard", "list"], {
        loadRunCli: async () => ({
          runCli: vi.fn(async () => {
            throw error;
          }),
        }),
      });

      expect(process.exitCode).toBe(1);
      expect(errorSpy.mock.calls).toEqual([[message]]);
      expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining("OPENCLAW_DEBUG"));
      expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining("openclaw doctor"));
      expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining("Could not start the CLI"));
    } finally {
      errorSpy.mockRestore();
      process.exitCode = previousExitCode;
    }
  });
});
