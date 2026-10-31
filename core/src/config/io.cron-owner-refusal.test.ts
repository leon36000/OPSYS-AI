import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { expect, it, vi } from "vitest";
import type {
  CronOwnerProjection,
  LegacyCronRepairState,
} from "../commands/doctor/cron/legacy-repair.js";
import { readActiveGatewayLockIdentity, resolveGatewayLockPaths } from "../infra/gateway-lock.js";
import {
  isCronOwnerWriteRefusalError,
  prepareCronOwnerWriteRefusal,
} from "./io.cron-owner-refusal.js";
import { assertAutomaticBindingsWriteAllowed } from "./io.ownership-write-guard.js";

const state = (
  rawJobs: Array<Record<string, unknown>>,
  invalidConfigRows: Array<Record<string, unknown>> = [],
  projectedOwnersByJobId: ReadonlyMap<string, CronOwnerProjection> = new Map(),
) =>
  ({
    rawJobs,
    invalidConfigRows,
    projectedOwnersByJobId,
  }) as unknown as LegacyCronRepairState;
const deps = (
  activeGateway?: {
    pid: number;
    port: number;
    cronOwnerProjection?: "dynamic-default-v1";
  },
  jobs?: Record<string, unknown>[],
) => ({
  readActiveGatewayLockIdentity: vi.fn(async () =>
    activeGateway ? { ...activeGateway, createdAt: new Date(0).toISOString() } : undefined,
  ),
  loadLegacyCronRepairState: vi.fn(async () => (jobs ? state(jobs) : null)),
  materializeLegacyDefaultCronJobOwners: vi.fn(async () => 0),
});
const cfg = { agents: { entries: { ops: {} } } };

it.each([
  { lockKind: "configLockPath", stage: "admission" },
  { lockKind: "stateLockPath", stage: "admission" },
  { lockKind: "configLockPath", stage: "recheck" },
  { lockKind: "stateLockPath", stage: "recheck" },
] as const)(
  "refuses a malformed $lockKind during ownership $stage",
  async ({ lockKind, stage }) => {
    const home = await fs.mkdtemp(path.join(os.tmpdir(), "opsys-cron-gateway-"));
    const env = {
      HOME: home,
      OPENCLAW_STATE_DIR: path.join(home, "state"),
      OPENCLAW_CONFIG_PATH: path.join(home, "openclaw.json"),
      OPENCLAW_LOAD_SHELL_ENV: "0",
    };
    try {
      await fs.mkdir(env.OPENCLAW_STATE_DIR, { recursive: true });
      await fs.writeFile(env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg), { mode: 0o600 });
      const storePath = path.join(env.OPENCLAW_STATE_DIR, "cron", "jobs.json");
      const plan = await prepareCronOwnerWriteRefusal(cfg, { storePath, env });
      const lockPath = resolveGatewayLockPaths(env)[lockKind];
      expect(path.relative(home, lockPath).startsWith("..")).toBe(false);
      await fs.mkdir(path.dirname(lockPath), { recursive: true });
      const malformed = "not-a-valid-gateway-lock";
      await fs.writeFile(lockPath, malformed, { mode: 0o600 });

      // Discovery is deliberately permissive. Mutation preflight must preserve
      // the real helper's uncertainty without repairing or removing this lock.
      await expect(readActiveGatewayLockIdentity({ env })).resolves.toBeUndefined();
      await expect(
        readActiveGatewayLockIdentity({ env, requireInspection: true }),
      ).rejects.toThrow();
      const result =
        stage === "recheck"
          ? plan.recheck()
          : prepareCronOwnerWriteRefusal(cfg, { storePath, env });
      await expect(result).rejects.toMatchObject({
        code: "CONFIG_WRITE_REJECTED",
        refusal: "cron-owner-safety",
      });
      expect(await fs.readFile(lockPath, "utf8")).toBe(malformed);
    } finally {
      await fs.rm(home, { recursive: true, force: true });
    }
  },
);

it("allows an ownership-safe live Gateway with a projected dynamic row and rechecks at commit", async () => {
  const injected = deps(
    {
      pid: process.pid + 1,
      port: 18_789,
      cronOwnerProjection: "dynamic-default-v1",
    },
    [{ id: "dynamic" }],
  );
  injected.loadLegacyCronRepairState.mockResolvedValueOnce(
    state(
      [{ id: "dynamic" }],
      [],
      new Map([["dynamic", { kind: "runtime-default" as const, agentId: "ops" }]]),
    ),
  );
  const plan = await prepareCronOwnerWriteRefusal(cfg, { storePath: "/tmp/cron.json" }, injected);
  injected.loadLegacyCronRepairState.mockResolvedValueOnce(state([{ id: "ownerless" }]));
  await expect(plan.recheck()).rejects.toThrow("ownerless legacy cron job");
});

it("refuses an unproven live Gateway without suggesting doctor", async () => {
  const injected = deps({ pid: process.pid + 1, port: 18_789 });
  const refusal = prepareCronOwnerWriteRefusal(cfg, { storePath: "/tmp/cron.json" }, injected);
  await expect(refusal).rejects.toThrow("live external Gateway");
  await expect(refusal).rejects.not.toThrow("doctor --fix");
});

it.each([
  ["without a live Gateway", undefined],
  [
    "with an ownership-safe live Gateway",
    {
      pid: process.pid + 1,
      port: 18_789,
      cronOwnerProjection: "dynamic-default-v1" as const,
    },
  ],
])("refuses ownerless and corrupt cron rows %s", async (_name, activeGateway) => {
  await expect(
    prepareCronOwnerWriteRefusal(
      cfg,
      { storePath: "/tmp/cron.json" },
      deps(activeGateway, [
        { id: "null", agentId: null },
        { id: "blank", agentId: " " },
      ]),
    ),
  ).rejects.toThrow("contains 2 ownerless legacy cron job");

  const corrupt = deps(activeGateway);
  corrupt.loadLegacyCronRepairState.mockResolvedValueOnce(
    state([], [{ id: "corrupt", reason: "invalid config" }]),
  );
  await expect(
    prepareCronOwnerWriteRefusal(cfg, { storePath: "/tmp/cron.json" }, corrupt),
  ).rejects.toThrow("contains 1 corrupt row");
});

it("keeps include-owned binding writes fail closed", () => {
  expect(() =>
    assertAutomaticBindingsWriteAllowed({
      bindingsIncludeOwned: true,
      ownershipPaths: [["bindings"]],
    }),
  ).toThrow("cannot append to $include-owned bindings");
});

it("materializes a proven retained owner before the commit recheck", async () => {
  for (const safe of [deps(), deps(undefined, [{ id: "owned", agentId: "research" }])]) {
    await prepareCronOwnerWriteRefusal(
      cfg,
      { storePath: "/tmp/cron.json", provenOwnerAgentId: "ops" },
      safe,
    );
    expect(safe.materializeLegacyDefaultCronJobOwners).not.toHaveBeenCalled();
  }

  const injected = deps(undefined, [{ id: "ownerless" }, { id: "owned", agentId: "research" }]);
  injected.loadLegacyCronRepairState.mockResolvedValueOnce(
    state(
      [{ id: "ownerless" }, { id: "owned", agentId: "research" }],
      [],
      new Map([
        ["ownerless", { kind: "runtime-default" as const, agentId: "ops" }],
        ["owned", { kind: "explicit" as const, agentId: "research" }],
      ]),
    ),
  );
  injected.materializeLegacyDefaultCronJobOwners.mockImplementationOnce(async () => {
    injected.loadLegacyCronRepairState.mockResolvedValue(
      state([
        { id: "ownerless", agentId: "ops" },
        { id: "owned", agentId: "research" },
      ]),
    );
    return 1;
  });

  const plan = await prepareCronOwnerWriteRefusal(
    cfg,
    {
      storePath: "/tmp/custom-cron.json",
      provenOwnerAgentId: "ops",
      env: { OPENCLAW_STATE_DIR: "/tmp/state" },
    },
    injected,
  );
  await plan.recheck();

  expect(injected.materializeLegacyDefaultCronJobOwners).toHaveBeenCalledOnce();
  expect(injected.materializeLegacyDefaultCronJobOwners).toHaveBeenCalledWith({
    storePath: "/tmp/custom-cron.json",
    legacyDefaultAgentId: "ops",
    env: { OPENCLAW_STATE_DIR: "/tmp/state" },
  });
});

it("keeps ambiguous and failed owner handoffs as typed refusals", async () => {
  const ambiguous = deps(undefined, [{ id: "ownerless" }]);
  await expect(
    prepareCronOwnerWriteRefusal(cfg, { storePath: "/tmp/cron.json" }, ambiguous),
  ).rejects.toSatisfy(isCronOwnerWriteRefusalError);
  expect(ambiguous.materializeLegacyDefaultCronJobOwners).not.toHaveBeenCalled();

  const failed = deps(undefined, [{ id: "ownerless" }]);
  failed.materializeLegacyDefaultCronJobOwners.mockImplementationOnce(async () => {
    throw new Error("database is temporarily read-only");
  });
  const failure = prepareCronOwnerWriteRefusal(
    cfg,
    { storePath: "/tmp/cron.json", provenOwnerAgentId: "ops" },
    failed,
  );
  await expect(failure).rejects.toSatisfy(isCronOwnerWriteRefusalError);
  await expect(failure).rejects.toThrow("database is temporarily read-only");

  const corrupt = deps();
  corrupt.loadLegacyCronRepairState.mockRejectedValueOnce(
    new Error("database disk image is malformed"),
  );
  const unreadable = prepareCronOwnerWriteRefusal(
    cfg,
    { storePath: "/tmp/corrupt-cron.json", provenOwnerAgentId: "ops" },
    corrupt,
  );
  await expect(unreadable).rejects.toSatisfy(isCronOwnerWriteRefusalError);
  await expect(unreadable).rejects.toThrow("database disk image is malformed");
  expect(corrupt.materializeLegacyDefaultCronJobOwners).not.toHaveBeenCalled();
});
