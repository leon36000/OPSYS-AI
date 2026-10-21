import { describe, expect, it, vi } from "vitest";
import { resolveCronJobConfigRevision } from "../cron/config-revision.js";
import { createTrustedCronScheduledToolPolicy } from "../cron/scheduled-tool-policy.js";
import type { CronServiceContract } from "../cron/service-contract.js";
import type { CronJobCreate, CronStoredJob } from "../cron/types.js";
import { createOpsysCronLiveAuthorityValidator } from "./opsys-cron-live-validator.js";
import { OpsysCronPrivateClient, type CronDeclaration } from "./opsys-cron-private-client.js";

const PROFILE = "finance";
const INTENTION = "a".repeat(64);
const SECRET = "b".repeat(64);
const DECLARATION = {
  name: "OPSYS profil finance",
  declarationKey: `opsys-profile:${INTENTION}`,
  agentId: `opsys-agent-${PROFILE}`,
  enabled: true,
  sessionTarget: "isolated",
  wakeMode: "now",
  schedule: { kind: "cron", expr: "0 8 * * 1", tz: "Europe/Paris" },
  payload: {
    kind: "agentTurn",
    message: "Exécute le mandat interne canonique du profil finance, révision 3.",
    timeoutSeconds: 120,
    toolsAllow: [],
  },
  delivery: { mode: "none" },
} satisfies CronJobCreate;
const WIRE = {
  name: DECLARATION.name,
  declarationKey: DECLARATION.declarationKey!,
  agentId: DECLARATION.agentId!,
  sessionTarget: DECLARATION.sessionTarget,
  wakeMode: DECLARATION.wakeMode,
  schedule: DECLARATION.schedule,
  payload: DECLARATION.payload,
  delivery: DECLARATION.delivery,
} satisfies CronDeclaration;

function job(overrides: Partial<CronStoredJob> = {}): CronStoredJob {
  return {
    ...DECLARATION,
    id: "job-1",
    createdAtMs: 1,
    updatedAtMs: 1,
    state: {},
    scheduledToolPolicy: createTrustedCronScheduledToolPolicy(),
    runtimeAuthority: {
      version: 1,
      runtimeId: "openclaw",
      namespace: "opsys-cron-authority-v1",
      payload: {
        version: 1,
        profil_id: PROFILE,
        intention_id: INTENTION,
        epoch: 2,
        lease_epoch: 1,
        capabilite: SECRET,
        declaration: WIRE,
      },
    },
    ...overrides,
  };
}

function privateClient(fetchImpl: typeof fetch) {
  return new OpsysCronPrivateClient({
    healthUrl: "http://127.0.0.1:8765/sante",
    operatorToken: "o".repeat(32),
    publicMcpToken: "p".repeat(32),
    fetchImpl,
  });
}

function validResponse() {
  return new Response(JSON.stringify({ ok: true, resultat: { valide: true } }), {
    status: 200,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

describe("OPSYS cron live authority validator", () => {
  it("rereads the enabled row and validates the same owner grant before dispatch", async () => {
    const current = job();
    const readJob = vi.fn<CronServiceContract["readJob"]>(async () => current);
    let body: Record<string, unknown> | undefined;
    const fetchImpl = vi.fn<typeof fetch>(async (_url, init) => {
      body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return validResponse();
    });
    const client = privateClient(fetchImpl);
    const revision = resolveCronJobConfigRevision(current);
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => client,
    });
    expect(validator).toBeTypeOf("function");
    await validator!(new AbortController().signal);
    await validator!(new AbortController().signal);
    expect(readJob).toHaveBeenCalledTimes(4);
    expect(readJob).toHaveBeenNthCalledWith(1, "job-1");
    expect(readJob).toHaveBeenNthCalledWith(2, "job-1");
    expect(readJob).toHaveBeenNthCalledWith(3, "job-1");
    expect(readJob).toHaveBeenNthCalledWith(4, "job-1");
    expect(body).toEqual({
      intention_id: INTENTION,
      capabilite: SECRET,
      epoch: 2,
      job_id: "job-1",
      config_revision: revision,
      declaration: WIRE,
    });
    expect(String(fetchImpl.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8765/cron-operateur/v1/finance/valider",
    );
    expect(fetchImpl.mock.calls[0]?.[1]?.headers).toMatchObject({
      authorization: `Bearer ${"o".repeat(32)}`,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("refuses before HTTP if live revision or enabled state changed", async () => {
    const first = job();
    const latest = job({ name: "OPSYS profil finance changed" });
    const fetchImpl = vi.fn<typeof fetch>(async () => validResponse());
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => latest },
      job: first,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => privateClient(fetchImpl),
    });
    await expect(validator!(new AbortController().signal)).rejects.toThrow(/changed/u);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a reserved declaration key after private authority and profile are stripped", () => {
    const reserved = job({
      runtimeAuthority: undefined,
      runtimeAuthorityRecoveryRequired: undefined,
    });
    expect(() =>
      createOpsysCronLiveAuthorityValidator({
        cron: { readJob: async () => reserved },
        job: reserved,
        getClient: () => undefined,
      }),
    ).toThrow(/configured profile/u);
    const ordinary = job({
      declarationKey: "human-job",
      runtimeAuthority: undefined,
      runtimeAuthorityRecoveryRequired: undefined,
    });
    expect(
      createOpsysCronLiveAuthorityValidator({
        cron: { readJob: async () => ordinary },
        job: ordinary,
        getClient: () => undefined,
      }),
    ).toBeUndefined();
  });

  it("does not treat a recovery-required reserved row as an ordinary job without a profile", () => {
    expect(() =>
      createOpsysCronLiveAuthorityValidator({
        cron: { readJob: async () => job() },
        job: job({ runtimeAuthority: undefined, runtimeAuthorityRecoveryRequired: true }),
        getClient: () => undefined,
      }),
    ).toThrow(/configured profile/u);
  });

  it("blocks recovery-required and changed authority rows before HTTP", async () => {
    const first = job();
    const latest = job({ runtimeAuthorityRecoveryRequired: true, runtimeAuthority: undefined });
    const fetchImpl = vi.fn<typeof fetch>(async () => validResponse());
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => latest },
      job: first,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => privateClient(fetchImpl),
    });
    await expect(validator!(new AbortController().signal)).rejects.toThrow(/authority/u);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses after the configured agent profile changes", async () => {
    const current = job();
    const fetchImpl = vi.fn<typeof fetch>(async () => validResponse());
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getProfileId: () => "another-profile",
      getClient: () => privateClient(fetchImpl),
    });
    await expect(validator!(new AbortController().signal)).rejects.toThrow(/profile changed/u);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("does not fall back to the captured profile after that profile is removed", async () => {
    const current = job();
    const fetchImpl = vi.fn<typeof fetch>(async () => validResponse());
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getProfileId: () => undefined,
      getClient: () => privateClient(fetchImpl),
    });
    await expect(validator!(new AbortController().signal)).rejects.toThrow(/profile changed/u);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses when the configured profile revision changes during owner validation", async () => {
    const current = job();
    let markFetchStarted!: () => void;
    let resolveResponse!: (response: Response) => void;
    let profileRevision = 3;
    const fetchStarted = new Promise<void>((resolve) => {
      markFetchStarted = resolve;
    });
    const responsePromise = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      markFetchStarted();
      return await responsePromise;
    });
    const client = privateClient(fetchImpl);
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getProfileRevision: () => profileRevision,
      getClient: () => client,
    });
    const validation = validator!(new AbortController().signal);
    await fetchStarted;
    profileRevision = 4;
    resolveResponse(validResponse());
    await expect(validation).rejects.toThrow(/profile changed during owner validation/u);
  });

  it("rechecks the live job after the owner response before permitting dispatch", async () => {
    const first = job();
    let current = first;
    let markFetchStarted!: () => void;
    let resolveResponse!: (response: Response) => void;
    const fetchStarted = new Promise<void>((resolve) => {
      markFetchStarted = resolve;
    });
    const responsePromise = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      markFetchStarted();
      return await responsePromise;
    });
    const client = privateClient(fetchImpl);
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: first,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => client,
    });
    const validation = validator!(new AbortController().signal);
    await fetchStarted;
    current = job({ name: "OPSYS profil finance changed" });
    resolveResponse(validResponse());
    await expect(validation).rejects.toThrow(/during owner validation/u);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("rechecks that the private client is still live after an in-flight HTTP validation", async () => {
    const current = job();
    let markFetchStarted!: () => void;
    let resolveResponse!: (response: Response) => void;
    const fetchStarted = new Promise<void>((resolve) => {
      markFetchStarted = resolve;
    });
    const responsePromise = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      markFetchStarted();
      return await responsePromise;
    });
    const client = privateClient(fetchImpl);
    let clientAvailable = true;
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => (clientAvailable ? client : undefined),
    });
    const validation = validator!(new AbortController().signal);
    await fetchStarted;
    clientAvailable = false;
    resolveResponse(validResponse());
    await expect(validation).rejects.toThrow(/withdrawn/u);
  });

  it("does not dispatch when cancellation arrives during owner validation", async () => {
    const current = job();
    let markFetchStarted!: () => void;
    let resolveResponse!: (response: Response) => void;
    const fetchStarted = new Promise<void>((resolve) => {
      markFetchStarted = resolve;
    });
    const responsePromise = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    let requestSignal: AbortSignal | null | undefined;
    const fetchImpl = vi.fn<typeof fetch>(async (_url, init) => {
      requestSignal = init?.signal;
      markFetchStarted();
      return await responsePromise;
    });
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => privateClient(fetchImpl),
    });
    const controller = new AbortController();
    const validation = validator!(controller.signal);
    await fetchStarted;
    controller.abort();
    expect(requestSignal?.aborted).toBe(true);
    resolveResponse(validResponse());
    await expect(validation).rejects.toThrow();
  });

  it("fails closed when Python refuses or the private HTTP owner is unavailable", async () => {
    const current = job();
    const refused = privateClient(
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 409 })),
    );
    const validator = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => refused,
    });
    await expect(validator!(new AbortController().signal)).rejects.toThrow();
    const noClient = createOpsysCronLiveAuthorityValidator({
      cron: { readJob: async () => current },
      job: current,
      profileId: PROFILE,
      profileRevision: 3,
      getClient: () => undefined,
    });
    await expect(noClient!(new AbortController().signal)).rejects.toThrow(/unavailable/u);
  });
});
