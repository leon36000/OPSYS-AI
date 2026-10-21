// Sms tests cover durable Twilio webhook admission and replay.
import { createHmac } from "node:crypto";
import { mkdtemp, realpath, rm } from "node:fs/promises";
import { createServer } from "node:http";
import os from "node:os";
import path from "node:path";
import { createChannelIngressQueueForTests } from "openclaw/plugin-sdk/channel-ingress-test-runtime";
import { createPluginRuntimeMock } from "openclaw/plugin-sdk/channel-test-helpers";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import { saveRemoteMedia } from "openclaw/plugin-sdk/media-runtime";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SmsChannelRuntime } from "./inbound.js";
import { createSmsIngressSpool } from "./ingress-spool.js";
import { installOpsysSmsHostBridge } from "./opsys-host-bridge.js";
import type { ResolvedSmsAccount } from "./types.js";
import { createSmsWebhookHandler } from "./webhook.js";

type SmsIngressPayload = {
  version: number;
  form: Record<string, string>;
  capsule?: unknown;
};

const gateWait = vi.hoisted(() => ({
  run: undefined as undefined | ((ms: number, signal?: AbortSignal) => Promise<void>),
}));
vi.mock("openclaw/plugin-sdk/runtime-env", async (importOriginal) => {
  const actual = await importOriginal<typeof import("openclaw/plugin-sdk/runtime-env")>();
  return {
    ...actual,
    sleepWithAbort: (ms: number, signal?: AbortSignal, options?: { ref?: boolean }) =>
      gateWait.run ? gateWait.run(ms, signal) : actual.sleepWithAbort(ms, signal, options),
  };
});

const account: ResolvedSmsAccount = {
  accountId: "default",
  enabled: true,
  accountSid: "AC123",
  authToken: "secret",
  fromNumber: "+15557654321",
  messagingServiceSid: "",
  defaultTo: "",
  webhookPath: "/webhooks/sms",
  publicWebhookUrl: "https://gateway.example.com/webhooks/sms",
  dangerouslyDisableSignatureValidation: false,
  dmPolicy: "pairing",
  allowFrom: [],
  textChunkLimit: 1500,
};

const stateDirs: string[] = [];
const disposers: Array<() => void | Promise<void>> = [];
type SmsIngressDeliver = NonNullable<Parameters<typeof createSmsIngressSpool>[0]["deliver"]>;
type SmsIngressSpool = ReturnType<typeof createSmsIngressSpool>;

async function createStateDir(): Promise<string> {
  const created = await mkdtemp(path.join(os.tmpdir(), "openclaw-sms-ingress-"));
  const resolved = await realpath(created);
  stateDirs.push(resolved);
  return resolved;
}

function createQueue(stateDir: string) {
  return createChannelIngressQueueForTests<SmsIngressPayload>({
    channelId: "sms",
    accountId: account.accountId,
    stateDir,
  });
}

function form(messageSid: string): Record<string, string> {
  return {
    AccountSid: account.accountSid,
    From: "+15551234567",
    To: "+15557654321",
    Body: "hello",
    MessageSid: messageSid,
  };
}

async function drainSpool(spool: SmsIngressSpool): Promise<void> {
  spool.start();
  await spool.waitForIdle();
}

async function listenSmsTestServer(server: ReturnType<typeof createServer>): Promise<string> {
  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", resolve);
  });
  disposers.push(async () => {
    await new Promise<void>((resolve) => {
      server.close(() => resolve());
    });
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("expected a loopback HTTP server address");
  }
  return `http://127.0.0.1:${address.port}`;
}

afterEach(async () => {
  for (const dispose of disposers.splice(0).toReversed()) {
    await dispose();
  }
  for (const stateDir of stateDirs.splice(0).toReversed()) {
    await rm(stateDir, { recursive: true, force: true });
  }
});

describe("createSmsIngressSpool", () => {
  it("retries acknowledged MMS provider outages before adopting later same-sender messages", async () => {
    const stateDir = await createStateDir();
    let now = 1_700_000_000_000;
    const nowSpy = vi.spyOn(Date, "now").mockImplementation(() => now);
    disposers.push(() => nowSpy.mockRestore());
    vi.stubEnv("OPENCLAW_STATE_DIR", stateDir);
    disposers.push(() => {
      vi.unstubAllEnvs();
    });
    const mediaBytes = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a0cAAAAASUVORK5CYII=",
      "base64",
    );
    let mediaRequests = 0;
    let authenticatedMediaRequests = 0;
    const mediaOrigin = await listenSmsTestServer(
      createServer((req, res) => {
        mediaRequests += 1;
        if (req.headers.authorization?.startsWith("Basic ")) {
          authenticatedMediaRequests += 1;
        }
        if (mediaRequests === 1) {
          res.statusCode = 429;
          res.end("Twilio rate limited");
          return;
        }
        res.setHeader("content-type", "image/png");
        res.end(mediaBytes);
      }),
    );
    const sender = "+15551234567";
    const messageSid = `MM${"a".repeat(32)}`;
    const testAccount = {
      ...account,
      accountSid: `AC${"c".repeat(32)}`,
      dmPolicy: "allowlist" as const,
      allowFrom: [sender],
    };
    const deliveries: Array<{ id: string; body: string; attachments: number }> = [];
    const channelRuntime = {
      commands: {
        shouldComputeCommandAuthorized: () => false,
        isControlCommandMessage: () => false,
      },
      pairing: { readAllowFromStore: async () => [] },
      routing: {
        resolveAgentRoute: () => ({
          agentId: "main",
          accountId: account.accountId,
          sessionKey: `agent:main:sms:direct:${sender}`,
        }),
      },
      media: {
        saveRemoteMedia: async (options: Parameters<typeof saveRemoteMedia>[0]) =>
          await saveRemoteMedia({
            ...options,
            // The guard resolves Twilio before the loopback fetch override runs.
            lookupFn: async () => [{ address: "93.184.216.34", family: 4 }],
            fetchImpl: async (_url, init) =>
              await fetch(`${mediaOrigin}/twilio-media`, {
                headers: init?.headers,
                signal: init?.signal,
              }),
          }),
      },
      inbound: {
        ingress: createPluginRuntimeMock().channel.inbound.ingress,
        buildContext: (input: Parameters<SmsChannelRuntime["inbound"]["buildContext"]>[0]) => {
          deliveries.push({
            id: String(input.extra?.MessageSid),
            body: input.message.bodyForAgent ?? input.message.rawBody,
            attachments: input.media?.length ?? 0,
          });
          return {};
        },
        run: async (input: Parameters<SmsChannelRuntime["inbound"]["run"]>[0]) => {
          const turnInput = await input.adapter.ingest(input.raw);
          if (!turnInput) {
            throw new Error("expected normalized SMS turn");
          }
          await input.adapter.resolveTurn(
            turnInput,
            { kind: "message", canStartAgentTurn: true },
            {},
          );
          await input.turnAdoptionLifecycle?.onAdopted();
        },
      },
      reply: {},
      session: {},
    } as unknown as SmsChannelRuntime;
    const queue = createQueue(stateDir);
    const spool = createSmsIngressSpool({
      cfg: {},
      account: testAccount,
      channelRuntime,
      queue,
      log: { warn: () => undefined },
    });
    disposers.push(spool.stop);
    const webhookHandler = createSmsWebhookHandler({
      cfg: {},
      account: testAccount,
      ingress: spool,
    });
    const webhookOrigin = await listenSmsTestServer(
      createServer((req, res) => {
        void webhookHandler(req, res).catch((error: unknown) => {
          res.statusCode = 500;
          res.end(error instanceof Error ? error.message : String(error));
        });
      }),
    );
    testAccount.publicWebhookUrl = `${webhookOrigin}/webhooks/sms`;
    spool.start();

    async function postSignedCallback(callback: Record<string, string>) {
      const signatureData =
        testAccount.publicWebhookUrl +
        Object.keys(callback)
          .toSorted()
          .map((key) => `${key}${callback[key] ?? ""}`)
          .join("");
      const signature = createHmac("sha1", testAccount.authToken)
        .update(signatureData)
        .digest("base64");
      return await fetch(testAccount.publicWebhookUrl, {
        method: "POST",
        headers: { "x-twilio-signature": signature },
        body: new URLSearchParams(callback),
      });
    }

    const mediaCallback = {
      ...form(messageSid),
      AccountSid: testAccount.accountSid,
      Body: "keep this attachment",
      NumMedia: "1",
      MediaUrl0: `https://api.twilio.com/2010-04-01/Accounts/${testAccount.accountSid}/Messages/${messageSid}/Media/ME${"b".repeat(32)}`,
      MediaContentType0: "image/png",
    };
    const firstResponse = await postSignedCallback(mediaCallback);
    expect(firstResponse.status).toBe(200);
    expect(firstResponse.headers.get("x-openclaw-delivery-accepted")).toBe("durable");
    await spool.waitForIdle();
    expect(mediaRequests).toBe(1);
    expect(await queue.listPending()).toEqual([
      expect.objectContaining({ id: messageSid, lastError: expect.stringContaining("HTTP 429") }),
    ]);
    expect(deliveries).toEqual([]);

    now += 1_000;
    const secondSid = `SM${"d".repeat(32)}`;
    const secondResponse = await postSignedCallback({
      ...form(secondSid),
      AccountSid: testAccount.accountSid,
      Body: "the later message",
    });
    expect(secondResponse.status).toBe(200);
    await spool.waitForIdle();
    expect(deliveries).toEqual([
      { id: messageSid, body: "keep this attachment", attachments: 1 },
      { id: secondSid, body: "the later message", attachments: 0 },
    ]);
    expect(mediaRequests).toBe(2);
    expect(authenticatedMediaRequests).toBe(2);
    expect(await spool.enqueue(mediaCallback)).toMatchObject({
      kind: "completed",
      duplicate: true,
    });
    expect(await queue.listPending()).toEqual([]);
  });

  it("recovers an uncompleted message with a fresh drain instance", async () => {
    const stateDir = await createStateDir();
    const first = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver: vi.fn<SmsIngressDeliver>(async () => undefined),
    });
    disposers.push(first.stop);
    await first.enqueue(form("SM-restart"));
    await first.stop();

    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const recovered = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(recovered.stop);
    await drainSpool(recovered);

    expect(deliver).toHaveBeenCalledOnce();
  });

  it("durably admits a handler selected before route shutdown after the pump stops", async () => {
    const stateDir = await createStateDir();
    const retired = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver: vi.fn<SmsIngressDeliver>(async () => undefined),
    });
    disposers.push(retired.stop);
    retired.start();
    await retired.stop();

    await expect(retired.enqueue(form("SM-late-handler"))).resolves.toMatchObject({
      kind: "accepted",
    });

    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const recovered = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(recovered.stop);
    await drainSpool(recovered);

    expect(deliver).toHaveBeenCalledOnce();
  });

  it("does not let a non-cooperative delivery block route replacement shutdown", async () => {
    const stateDir = await createStateDir();
    let markDeliveryStarted!: () => void;
    const deliveryStarted = new Promise<void>((resolve) => {
      markDeliveryStarted = resolve;
    });
    let deliverySignal: AbortSignal | undefined;
    const spool = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver: vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
        deliverySignal = lifecycle.abortSignal;
        markDeliveryStarted();
        await new Promise<void>(() => {});
      }),
    });
    disposers.push(spool.stop);
    spool.start();
    await spool.enqueue(form("SM-non-cooperative-stop"));
    await deliveryStarted;

    await spool.stop();

    expect(deliverySignal?.aborted).toBe(true);
  });

  it("keeps a completed MessageSid tombstone from dispatching twice", async () => {
    const stateDir = await createStateDir();
    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const spool = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(spool.stop);

    expect(await spool.enqueue(form("SM-completed"))).toMatchObject({
      kind: "accepted",
      duplicate: false,
    });
    await drainSpool(spool);
    expect(await spool.enqueue(form("SM-completed"))).toMatchObject({
      kind: "completed",
      duplicate: true,
    });
    await drainSpool(spool);

    expect(deliver).toHaveBeenCalledOnce();
  });

  it.each(["SmsSid", "SmsMessageSid"])("accepts the legacy %s event id alias", async (key) => {
    const stateDir = await createStateDir();
    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const spool = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(spool.stop);
    const rawForm = form("SM-alias");
    delete rawForm.MessageSid;
    rawForm[key] = "SM-alias";

    expect(await spool.enqueue(rawForm)).toMatchObject({ kind: "accepted", duplicate: false });
    await drainSpool(spool);

    expect(deliver).toHaveBeenCalledWith(
      expect.objectContaining({ messageSid: "SM-alias" }),
      expect.any(Object),
      expect.any(Number),
    );
  });

  it("uses the canonical sender as the durable lane", async () => {
    const stateDir = await createStateDir();
    const queue = createQueue(stateDir);
    const spool = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue,
      deliver: vi.fn<SmsIngressDeliver>(async () => undefined),
    });
    disposers.push(spool.stop);

    await spool.enqueue({ ...form("SM-canonical-lane"), From: "RcS:+1 (555) 123-4567" });

    expect(await queue.listPending()).toEqual([
      expect.objectContaining({ laneKey: "sender:+15551234567" }),
    ]);
  });

  it("replays with the original webhook receipt timestamp", async () => {
    const stateDir = await createStateDir();
    const receivedAt = 1_700_000_000_456;
    const now = vi
      .spyOn(Date, "now")
      .mockReturnValueOnce(receivedAt)
      .mockReturnValue(receivedAt + 60_000);
    const first = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver: vi.fn<SmsIngressDeliver>(async () => undefined),
    });
    disposers.push(first.stop);
    await first.enqueue(form("SM-received-at"));
    await first.stop();
    now.mockRestore();

    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const recovered = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(recovered.stop);
    await drainSpool(recovered);

    expect(deliver).toHaveBeenCalledWith(expect.any(Object), expect.any(Object), receivedAt);
  });

  it("preserves the old handler-reload replay guard scenario with a tombstone", async () => {
    const stateDir = await createStateDir();
    const firstDeliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const first = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver: firstDeliver,
    });
    disposers.push(first.stop);
    await first.enqueue(form("SM-handler-reload"));
    await drainSpool(first);
    await first.stop();

    const reloadedDeliver = vi.fn<SmsIngressDeliver>(async () => undefined);
    const reloaded = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver: reloadedDeliver,
    });
    disposers.push(reloaded.stop);
    expect(await reloaded.enqueue(form("SM-handler-reload"))).toMatchObject({
      kind: "completed",
      duplicate: true,
    });
    await drainSpool(reloaded);

    expect(firstDeliver).toHaveBeenCalledOnce();
    expect(reloadedDeliver).not.toHaveBeenCalled();
  });

  it("dispatches callbacks bound to the configured Messaging Service", async () => {
    const stateDir = await createStateDir();
    const serviceAccount = {
      ...account,
      fromNumber: "",
      messagingServiceSid: "MG123",
    };
    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const spool = createSmsIngressSpool({
      cfg: {},
      account: serviceAccount,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(spool.stop);

    await spool.enqueue({
      ...form("SM-service"),
      MessagingServiceSid: "MG123",
    });
    await drainSpool(spool);

    expect(deliver).toHaveBeenCalledWith(
      expect.objectContaining({ messagingServiceSid: "MG123" }),
      expect.any(Object),
      expect.any(Number),
    );
  });

  it.each([
    {
      name: "fromNumber-only RCS compatibility",
      ingressAccount: account,
      rawForm: {
        ...form("SM-rcs-number"),
        From: "rcs:+15551234567",
        To: "rcs:example-agent",
      },
    },
    {
      name: "Messaging Service RCS identity",
      ingressAccount: { ...account, fromNumber: "", messagingServiceSid: "MG123" },
      rawForm: {
        ...form("SM-rcs-service"),
        From: "rcs:+15551234567",
        To: "rcs:example-agent",
        MessagingServiceSid: "MG123",
      },
    },
  ])("preserves $name", async ({ ingressAccount, rawForm }) => {
    const stateDir = await createStateDir();
    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const spool = createSmsIngressSpool({
      cfg: {},
      account: ingressAccount,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(spool.stop);

    await spool.enqueue(rawForm);
    await drainSpool(spool);

    expect(deliver).toHaveBeenCalledOnce();
  });

  it("preserves shipped RCS text while ignoring unsupported media fields", async () => {
    const stateDir = await createStateDir();
    const deliver = vi.fn<SmsIngressDeliver>(async (_message, lifecycle) => {
      await lifecycle.onAdopted();
    });
    const spool = createSmsIngressSpool({
      cfg: {},
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(spool.stop);

    await spool.enqueue({
      ...form("SM-rcs-text-media"),
      Body: "keep this RCS text",
      From: "rcs:+15551234567",
      To: "rcs:example-agent",
      NumMedia: "1",
      MediaUrl0: "https://api.twilio.com/media/photo",
    });
    await drainSpool(spool);

    expect(deliver).toHaveBeenCalledWith(
      expect.objectContaining({
        body: "keep this RCS text",
        media: [],
      }),
      expect.any(Object),
      expect.any(Number),
    );
  });

  it.each([
    {
      name: "invalid payload",
      ingressAccount: account,
      rawForm: { MessageSid: "SM-invalid", From: "+15551234567" },
    },
    {
      name: "missing account",
      ingressAccount: account,
      rawForm: { ...form("SM-account-missing"), AccountSid: "" },
    },
    {
      name: "account mismatch",
      ingressAccount: account,
      rawForm: { ...form("SM-account"), AccountSid: "AC-other" },
    },
    {
      name: "recipient mismatch",
      ingressAccount: account,
      rawForm: {
        ...form("MM-recipient"),
        To: "+15550000000",
        NumMedia: "1",
        MediaUrl0: "https://api.twilio.com/media/photo",
      },
    },
    {
      name: "Messaging Service mismatch",
      ingressAccount: { ...account, fromNumber: "", messagingServiceSid: "MG123" },
      rawForm: {
        ...form("SM-service-mismatch"),
        MessagingServiceSid: "MG-other",
      },
    },
    {
      name: "missing Messaging Service",
      ingressAccount: { ...account, fromNumber: "", messagingServiceSid: "MG123" },
      rawForm: form("SM-service-missing"),
    },
    {
      name: "fromNumber precedence",
      ingressAccount: { ...account, messagingServiceSid: "MG123" },
      rawForm: {
        ...form("SM-number-precedence"),
        To: "+15550000000",
        MessagingServiceSid: "MG123",
      },
    },
    {
      name: "RCS media-only",
      ingressAccount: account,
      rawForm: {
        ...form("MM-rcs-media"),
        Body: "",
        From: "rcs:+15551234567",
        To: "rcs:example-agent",
        NumMedia: "1",
        MediaUrl0: "https://api.twilio.com/media/photo",
      },
    },
  ])("dead-letters a permanent $name failure", async ({ ingressAccount, rawForm }) => {
    const stateDir = await createStateDir();
    const deliver = vi.fn<SmsIngressDeliver>(async () => undefined);
    const spool = createSmsIngressSpool({
      cfg: {},
      account: ingressAccount,
      channelRuntime: {} as SmsChannelRuntime,
      queue: createQueue(stateDir),
      deliver,
    });
    disposers.push(spool.stop);

    await spool.enqueue(rawForm);
    await drainSpool(spool);

    expect(await spool.enqueue(rawForm)).toMatchObject({ kind: "failed", duplicate: true });
    expect(deliver).not.toHaveBeenCalled();
  });
});

const selectedCfg = {
  agents: {
    entries: {
      "opsys-agent-front": {
        opsysRuntimeAdmission: {
          profileId: "front",
          profileRevision: 1,
          smsIngress: { version: 1 as const, accountId: "default", accountSid: "AC123" },
        },
      },
    },
  },
};

describe("selected SMS Gate retention", () => {
  it("refuses a fresh selected capture without a Host bridge before any durable append", async () => {
    const queue = createQueue(await createStateDir());
    const spool = createSmsIngressSpool({
      cfg: selectedCfg,
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue,
    });
    disposers.push(spool.stop);
    await expect(
      spool.enqueue(form("SM-selected-missing"), {
        signature: "fictif",
        signatureUrl: account.publicWebhookUrl,
      }),
    ).rejects.toThrow();
    expect(await queue.listPending()).toEqual([]);
  });

  it("uses the monitor receipt time and persists the exact sealed v2 rather than a legacy form", async () => {
    const queue = createQueue(await createStateDir());
    const locator = Object.freeze({});
    const handle = Object.freeze({});
    let sealed: unknown;
    const invoke = vi.fn((_locator: object, input: unknown) => {
      const request = input as { kind: string; receivedAt?: number };
      if (request.kind === "capture") {
        return handle;
      }
      if (request.kind === "encode") {
        sealed = {
          version: 2,
          form: form("SM-selected-sealed"),
          capsule: { fictif: true, received_at: request.receivedAt },
        };
        return sealed;
      }
      throw new Error("unexpected fake RPC");
    });
    const registration = installOpsysSmsHostBridge("default", { locator, invoke });
    disposers.push(() => registration.dispose());
    const spool = createSmsIngressSpool({
      cfg: selectedCfg,
      account,
      channelRuntime: {} as SmsChannelRuntime,
      queue,
    });
    disposers.push(spool.stop);
    await spool.enqueue(form("SM-selected-sealed"), {
      signature: "fictif",
      signatureUrl: account.publicWebhookUrl,
    });
    const [row] = await queue.listPending();
    expect(invoke.mock.calls.map((call) => (call[1] as { kind: string }).kind)).toEqual([
      "capture",
      "encode",
    ]);
    expect(row?.payload).toEqual(sealed);
    expect(row?.payload).toMatchObject({ version: 2, capsule: { received_at: row?.receivedAt } });
  });
});

describe("selected SMS replay Gate retention", () => {
  it.each([
    { name: "selected v1", cfg: selectedCfg, payload: { version: 1, form: form("SM-kept") } },
    {
      name: "selected malformed",
      cfg: selectedCfg,
      payload: { version: 91, form: form("SM-other") },
    },
    {
      name: "v2 after marker removal",
      cfg: {},
      payload: {
        version: 2,
        form: form("SM-kept"),
        capsule: { fictif: true, permission: { revision: 1 }, received_at: 1700000000000 },
      },
    },
  ])(
    "preserves $name and cancels without inbound, attempts or completing",
    async ({ cfg, payload }) => {
      const stateDir = await createStateDir();
      const queue = createQueue(stateDir);
      const receivedAt = 1_700_000_000_000;
      await queue.enqueue("SM-kept", payload, { receivedAt, laneKey: "sender:+15551234567" });
      const [before] = await queue.listPending();
      const complete = vi.spyOn(queue, "complete");
      const fail = vi.spyOn(queue, "fail");
      const release = vi.spyOn(queue, "release");
      const invoke = vi.fn(async (_locator: object, _input: unknown) => ({
        status: "received",
        fictif: true,
      }));
      const registration = installOpsysSmsHostBridge("default", {
        locator: Object.freeze({}),
        invoke,
      });
      disposers.push(() => registration.dispose());
      let resume: (() => void) | undefined;
      const wait = vi.fn(
        (ms: number, signal?: AbortSignal) =>
          new Promise<void>((resolve) => {
            resume = resolve;
            signal?.addEventListener("abort", () => resolve(), { once: true });
          }),
      );
      gateWait.run = wait;
      disposers.push(() => {
        gateWait.run = undefined;
      });
      const deliver = vi.fn<SmsIngressDeliver>(async () => undefined);
      const spool = createSmsIngressSpool({
        cfg,
        account,
        channelRuntime: {} as SmsChannelRuntime,
        queue,
        deliver,
      });
      disposers.push(spool.stop);
      spool.start();
      await vi.waitFor(() => expect(wait).toHaveBeenCalledOnce());
      expect(wait.mock.calls[0]?.[0]).toBe(5000);
      const [claimed] = await queue.listClaims();
      expect(invoke).toHaveBeenCalledExactlyOnceWith(expect.any(Object), {
        kind: "resolve",
        payload,
        id: "SM-kept",
        token: claimed?.claim.token,
        ownerId: claimed?.claim.ownerId,
        receivedAt,
      });
      expect(complete).not.toHaveBeenCalled();
      expect(release).not.toHaveBeenCalled();
      expect(deliver).not.toHaveBeenCalled();
      const paused = spool.pause();
      resume?.();
      await paused;
      await spool.waitForIdle();
      const [after] = await queue.listPending();
      expect(after).toMatchObject({
        id: before?.id,
        payload,
        receivedAt,
        attempts: before?.attempts,
        laneKey: before?.laneKey,
      });
      expect(release).toHaveBeenCalledOnce();
      expect(release.mock.calls[0]?.[1]).toMatchObject({ recordAttempt: false });
      expect(complete).not.toHaveBeenCalled();
      expect(fail).not.toHaveBeenCalled();
      expect(deliver).not.toHaveBeenCalled();
      await spool.stop();
      const restarted = createSmsIngressSpool({
        cfg,
        account,
        queue: createQueue(stateDir),
        channelRuntime: {} as SmsChannelRuntime,
        deliver,
      });
      disposers.push(restarted.stop);
      restarted.start();
      await vi.waitFor(() => expect(wait).toHaveBeenCalledTimes(2));
      expect(invoke.mock.calls[1]?.[1]).toMatchObject({
        kind: "resolve",
        payload,
        id: "SM-kept",
        receivedAt,
      });
      const pauseRestart = restarted.pause();
      resume?.();
      await pauseRestart;
      await restarted.waitForIdle();
      expect((await queue.listPending())[0]).toMatchObject({
        payload,
        receivedAt,
        attempts: before?.attempts,
      });
      expect(deliver).not.toHaveBeenCalled();
      expect(complete).not.toHaveBeenCalled();
    },
  );

  it("retains v2 on abort and release failure without terminal fallback", async () => {
    const queue = createQueue(await createStateDir());
    const payload = { version: 2, form: form("SM-release-failed"), capsule: { fictif: true } };
    await queue.enqueue("SM-release-failed", payload, { laneKey: "sender:+15551234567" });
    const complete = vi.spyOn(queue, "complete");
    const fail = vi.spyOn(queue, "fail");
    const release = vi
      .spyOn(queue, "release")
      .mockRejectedValue(new Error("fictif release unavailable"));
    const wait = vi.fn(
      (_ms: number, signal?: AbortSignal) =>
        new Promise<void>((resolve) => {
          signal?.addEventListener("abort", () => resolve(), { once: true });
        }),
    );
    gateWait.run = wait;
    disposers.push(() => {
      gateWait.run = undefined;
    });
    const deliver = vi.fn<SmsIngressDeliver>(async () => undefined);
    const spool = createSmsIngressSpool({
      cfg: {},
      account,
      queue,
      channelRuntime: {} as SmsChannelRuntime,
      deliver,
    });
    disposers.push(spool.stop);
    spool.start();
    await vi.waitFor(() => expect(wait).toHaveBeenCalledOnce());
    await spool.stop();
    await spool.waitForIdle();
    expect(release).toHaveBeenCalledOnce();
    expect(complete).not.toHaveBeenCalled();
    expect(fail).not.toHaveBeenCalled();
    expect(deliver).not.toHaveBeenCalled();
    expect(await queue.listClaims()).toMatchObject([
      { id: "SM-release-failed", payload, attempts: 0 },
    ]);
  });

  it("never swaps the captured carrier for a replacement or downgrades after cfg mutation", async () => {
    const queue = createQueue(await createStateDir());
    const config: OpenClawConfig = structuredClone(selectedCfg);
    const first = vi.fn(() => {
      throw new Error("fictif revoked");
    });
    const a = installOpsysSmsHostBridge("default", { locator: Object.freeze({}), invoke: first });
    disposers.push(() => a.dispose());
    const spool = createSmsIngressSpool({
      cfg: config,
      account,
      queue,
      channelRuntime: {} as SmsChannelRuntime,
    });
    disposers.push(spool.stop);
    const next = vi.fn();
    const b = installOpsysSmsHostBridge("default", { locator: Object.freeze({}), invoke: next });
    disposers.push(() => b.dispose());
    if (config.agents) {
      config.agents.entries = {};
    }
    await expect(
      spool.enqueue(form("SM-retired"), {
        signature: "fictif",
        signatureUrl: account.publicWebhookUrl,
      }),
    ).rejects.toThrow();
    expect(first).toHaveBeenCalledOnce();
    expect(next).not.toHaveBeenCalled();
    expect(await queue.listPending()).toEqual([]);
  });
});

describe("selected route cancellation", () => {
  it("refuses new selected capture after only the route gate signal aborts", async () => {
    const queue = createQueue(await createStateDir());
    const gate = new AbortController();
    const invoke = vi.fn();
    const registration = installOpsysSmsHostBridge("default", {
      locator: Object.freeze({}),
      invoke,
    });
    disposers.push(() => registration.dispose());
    const spool = createSmsIngressSpool({
      cfg: selectedCfg,
      account,
      queue,
      channelRuntime: {} as SmsChannelRuntime,
      gateAbortSignal: gate.signal,
    });
    disposers.push(spool.stop);
    gate.abort();
    await expect(
      spool.enqueue(form("SM-aborted"), {
        signature: "fictif",
        signatureUrl: account.publicWebhookUrl,
      }),
    ).rejects.toThrow();
    expect(invoke).not.toHaveBeenCalled();
    expect(await queue.listPending()).toEqual([]);
  });
  it("preserves legacy durable admission when the separate route gate signal is already aborted", async () => {
    const queue = createQueue(await createStateDir());
    const gate = new AbortController();
    gate.abort();
    const spool = createSmsIngressSpool({
      cfg: {},
      account,
      queue,
      channelRuntime: {} as SmsChannelRuntime,
      gateAbortSignal: gate.signal,
    });
    disposers.push(spool.stop);
    await expect(spool.enqueue(form("SM-legacy-gate-aborted"))).resolves.toMatchObject({
      kind: "accepted",
    });
    expect((await queue.listPending())[0]?.payload).toEqual({
      version: 1,
      form: form("SM-legacy-gate-aborted"),
    });
  });
  it("routes a decoded JSON null payload to the Gate without turning it into a permanent error", async () => {
    const queue = createChannelIngressQueueForTests<unknown>({
      channelId: "sms",
      accountId: "default",
      stateDir: await createStateDir(),
    });
    await queue.enqueue("SM-null", null, { laneKey: "event:SM-null", receivedAt: 1700000000000 });
    const invoke = vi.fn(async (_locator: object, _input: unknown) => ({ status: "unresolved" }));
    const registration = installOpsysSmsHostBridge("default", {
      locator: Object.freeze({}),
      invoke,
    });
    disposers.push(() => registration.dispose());
    const wait = vi.fn(
      (_ms: number, signal?: AbortSignal) =>
        new Promise<void>((resolve) => {
          signal?.addEventListener("abort", () => resolve(), { once: true });
        }),
    );
    gateWait.run = wait;
    disposers.push(() => {
      gateWait.run = undefined;
    });
    const deliver = vi.fn<SmsIngressDeliver>(async () => undefined);
    const spool = createSmsIngressSpool({
      cfg: selectedCfg,
      account,
      queue,
      channelRuntime: {} as SmsChannelRuntime,
      deliver,
    });
    disposers.push(spool.stop);
    spool.start();
    await vi.waitFor(() => expect(wait).toHaveBeenCalledOnce());
    expect(invoke.mock.calls[0]?.[1]).toMatchObject({
      payload: null,
      id: "SM-null",
      receivedAt: 1700000000000,
    });
    await spool.stop();
    await spool.waitForIdle();
    expect(deliver).not.toHaveBeenCalled();
    expect(await queue.listFailed?.()).toEqual([]);
    expect((await queue.listPending())[0]?.payload).toBeNull();
  });
});
