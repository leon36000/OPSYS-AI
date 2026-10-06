import { Command } from "commander";
import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  inspect: vi.fn(),
  format: vi.fn(),
  json: vi.fn(),
  stdout: vi.fn(),
  exit: vi.fn(),
}));
vi.mock("../opsys-postflight-diagnostic.js", () => ({
  inspectOpsysPostflightDiagnostic: mocks.inspect,
  formatOpsysPostflightDiagnostic: mocks.format,
}));
vi.mock("../../runtime.js", () => ({
  defaultRuntime: { exit: mocks.exit },
  writeRuntimeJson: mocks.json,
  writeRuntimeStdout: mocks.stdout,
}));
import { registerDatabaseCommand } from "./register.database.js";

beforeEach(() => {
  vi.clearAllMocks();
  mocks.inspect.mockReturnValue({
    status: "available",
    agentId: "m03-estimation",
    readOnly: true,
    sourceReplayAllowed: false,
  });
  mocks.format.mockReturnValue("Sortie fictive de diagnostic\n");
});

function program() {
  const cli = new Command()
    .exitOverride()
    .configureOutput({ writeOut: () => {}, writeErr: () => {} });
  registerDatabaseCommand(cli);
  return cli;
}

it("requires an explicit agent without invoking a read or taking main by default", async () => {
  await expect(
    program().parseAsync(["database", "postflight", "--json"], { from: "user" }),
  ).rejects.toMatchObject({ code: "commander.missingMandatoryOptionValue" });
  expect(mocks.inspect).not.toHaveBeenCalled();
  expect(mocks.json).not.toHaveBeenCalled();
});

it("keeps help passive without observing state", async () => {
  await expect(
    program().parseAsync(["database", "postflight", "--help"], { from: "user" }),
  ).rejects.toMatchObject({ code: "commander.helpDisplayed" });
  expect(mocks.inspect).not.toHaveBeenCalled();
});

it("routes the exact selected owner into the diagnostic and emits its structured JSON", async () => {
  await program().parseAsync(["database", "postflight", "--agent-id", "m03-estimation", "--json"], {
    from: "user",
  });
  expect(mocks.inspect).toHaveBeenCalledExactlyOnceWith({ agentId: "m03-estimation" });
  expect(mocks.json).toHaveBeenCalledWith(expect.anything(), mocks.inspect.mock.results[0].value);
  expect(mocks.stdout).not.toHaveBeenCalled();
  expect(mocks.exit).not.toHaveBeenCalled();
});

it("shows human output from the same diagnostic without a second read", async () => {
  await program().parseAsync(["database", "postflight", "--agent-id", "m03-estimation"], {
    from: "user",
  });
  expect(mocks.inspect).toHaveBeenCalledTimes(1);
  expect(mocks.format).toHaveBeenCalledWith(mocks.inspect.mock.results[0].value);
  expect(mocks.stdout).toHaveBeenCalledWith(expect.anything(), "Sortie fictive de diagnostic\n");
  expect(mocks.json).not.toHaveBeenCalled();
});

it("returns nonzero after emitting unavailable JSON without guessing counts", async () => {
  mocks.inspect.mockReturnValue({
    status: "unavailable",
    agentId: "m03-estimation",
    reason: "tables-missing",
    readOnly: true,
    sourceReplayAllowed: false,
  });
  await program().parseAsync(["database", "postflight", "--agent-id", "m03-estimation", "--json"], {
    from: "user",
  });
  expect(mocks.exit).toHaveBeenCalledExactlyOnceWith(1);
  expect(mocks.json.mock.calls[0][1]).not.toHaveProperty("counts");
});

it("rejects a custom path or replay flag before entering the diagnostic", async () => {
  for (const flag of ["--path", "--replay", "--purge"]) {
    await expect(
      program().parseAsync(["database", "postflight", "--agent-id", "main", flag], {
        from: "user",
      }),
    ).rejects.toMatchObject({ code: "commander.unknownOption" });
  }
  expect(mocks.inspect).not.toHaveBeenCalled();
});
