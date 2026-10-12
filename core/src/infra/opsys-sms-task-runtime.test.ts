// Fictitious Task fixture; configuration alone is not SMS/provider admission.
import { afterEach, expect, it, vi } from "vitest";
import { createNativeChannelIngressOwner } from "../../test/helpers/native-channel-ingress-owner.js";
import {
  buildChannelInboundEventContext,
  buildHostChannelInboundEventContext,
} from "../channels/inbound-event/context.js";
import { createHostChannelInboundEventContextBuilder } from "../channels/inbound-event/host-context-builder.js";
import * as admission from "../channels/message-access/admission-evidence.js";
import { createHostChannelIngressRuntime } from "../channels/message-access/runtime.js";
import { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import { runChannelTurn } from "../channels/turn/run-channel-turn.js";
import { createOpsysSmsHostAuthority } from "../gateway/opsys-sms-host-authority.js";
import type { OpsysSmsHostAuthority } from "../gateway/opsys-sms-host-authority.js";
import type { GatewayRequestContext } from "../gateway/server-methods/types.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { PluginInstance } from "../plugins/plugin-instance.js";
import { createEmptyPluginRegistry } from "../plugins/registry.js";
import { createRuntimeChannel } from "../plugins/runtime/runtime-channel.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";

it("captures Task references without consulting unpublished Host authority", async () => {
  const { createOpsysSmsRequiredTaskRuntime } = await import("./opsys-sms-task-runtime.js");
  const isCurrent = vi.fn(() => false);
  const captureSelection = vi.fn<OpsysSmsHostAuthority["captureSelection"]>(() => {
    throw new Error("REJ-M1-SMS-HOST-SELECTION");
  });
  const authority: OpsysSmsHostAuthority = Object.freeze({
    isCurrent,
    captureSelection,
    publish: () => false,
    revoke: () => {},
  });
  const assertCurrent = vi.fn(() => {
    throw new Error("REJ-M1-SMS-HOST-SELECTION");
  });
  const runtime = createRuntimeChannel();
  const task = createOpsysSmsRequiredTaskRuntime({
    runtime,
    authority,
    accountId: "default",
    lifetime: Object.freeze({}),
    abortSignal: new AbortController().signal,
    assertCurrent,
  });
  expect(isCurrent).not.toHaveBeenCalled();
  expect(captureSelection).not.toHaveBeenCalled();
  expect(assertCurrent).not.toHaveBeenCalled();
  expect(task.runtime.inbound).toBe(task.runtime.turn);
  expect(task.runtime.inbound).not.toBe(runtime.inbound);
  task.dispose();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});
// Eagerly import the actual kernel; lazy transformation is not a behavior timeout.
void runChannelTurn;
const sessionRecord = vi.hoisted(() => vi.fn(async () => undefined));
const routedDispatch = vi.hoisted(() =>
  vi.fn(async () => ({ queuedFinal: false, counts: { tool: 0, block: 0, final: 0 } })),
);
vi.mock("../channels/session.js", async (original) => ({
  ...(await original<typeof import("../channels/session.js")>()),
  recordInboundSession: sessionRecord,
}));
vi.mock("../auto-reply/dispatch.js", async (original) => ({
  ...(await original<typeof import("../auto-reply/dispatch.js")>()),
  dispatchInboundMessageWithRoutedChannelDispatcher: routedDispatch,
}));
// Only session persistence and the transport dispatcher leaves are fictitious in routed cases.
const refused = "REJ-M1-SMS-HOST-SELECTION";
const builderInput = () => ({
  channel: "sms",
  accountId: "default",
  messageId: "SM-fictif",
  from: "sms:sender-a",
  sender: { id: "sender-a" },
  conversation: { kind: "direct" as const, id: "dm-fictif" },
  route: { agentId: "main", routeSessionKey: "agent:main:sms:dm:fictif" },
  reply: { to: "sms:receiver" },
  message: { rawBody: "texte fictif" },
});

async function taskFixture(runtime = createRuntimeChannel(), guard = vi.fn<() => void>()) {
  const { createOpsysSmsRequiredTaskRuntime } = await import("./opsys-sms-task-runtime.js");
  const sid = `AC${"1".repeat(32)}`;
  const sms = {
    enabled: true,
    accountSid: sid,
    authToken: "token-fictif-test",
    fromNumber: "+15145550101",
    publicWebhookUrl: "https://fictif.invalid/webhooks/sms",
    dangerouslyDisableSignatureValidation: false,
  };
  const cfg = {
    channels: { sms },
    agents: {
      list: [
        {
          id: "opsys-agent-demo",
          opsysRuntimeAdmission: {
            profileId: "demo",
            profileRevision: 1,
            smsIngress: { version: 1 as const, accountId: "default", accountSid: sid },
          },
        },
      ],
    },
    bindings: [{ agentId: "opsys-agent-demo", match: { channel: "sms", accountId: "default" } }],
  };
  const registry = createEmptyPluginRegistry();
  registry.channels.push({
    pluginId: "sms",
    source: "fictif",
    origin: "bundled",
    plugin: createChannelTestPluginBase({ id: "sms" }),
    captureReadAuthority: () => () => true,
  });
  const registration = getLoadedChannelPluginEntryById("sms", registry)!;
  const abort = new AbortController();
  let live = true;
  const host = createOpsysSmsHostAuthority({
    cfg,
    getRuntimeConfig: () => cfg,
    channelId: "sms",
    accountId: "default",
    account: { ...sms, accountId: "default" },
    registration,
    getCurrentRegistration: () => registration,
    abortSignal: abort.signal,
    capabilityLease: createPluginRuntimeCapabilityLease("fictitious test Task"),
    isCurrentLifetime: () => live,
    isCurrentTask: () => live,
  });
  if (!host) {
    throw new Error("Missing real selected Host fixture");
  }
  const task = createOpsysSmsRequiredTaskRuntime({
    runtime,
    authority: host,
    accountId: "default",
    lifetime: Object.freeze({}),
    abortSignal: abort.signal,
    assertCurrent: guard,
  });
  expect(host.publish()).toBe(true);
  return {
    task,
    host,
    runtime,
    abort,
    guard,
    replace: () => {
      live = false;
    },
  };
}

function preparedInput(context = buildChannelInboundEventContext(builderInput())) {
  const record = vi.fn(async () => undefined);
  const dispatch = vi.fn(async () => ({
    queuedFinal: true,
    counts: { tool: 0, block: 0, final: 1 },
  }));
  return {
    input: {
      channel: "sms",
      accountId: "default",
      ctxPayload: context,
      routeSessionKey: "agent:main:sms:dm:fictif",
      storePath: "/fictif/sessions.json",
      recordInboundSession: record,
      runDispatch: dispatch,
    },
    record,
    dispatch,
  };
}

it("does not launder existing Host evidence or resolver into a mutated scope", async () => {
  const audit = admission.createChannelAdmissionAudit({ enabled: true });
  const gateway = {
    channelAdmissionAudit: audit,
    getRuntimeConfig: () => ({}),
  } as GatewayRequestContext;
  const owner = createNativeChannelIngressOwner({
    channelId: "sms",
    resolveGatewayContext: () => gateway,
  }).owner;
  const params = builderInput();
  const channelIngress = await createHostChannelIngressRuntime(owner).resolveStable({
    channelId: "sms",
    accountId: "default",
    subject: { stableId: "sender-a" },
    conversation: { kind: "direct", id: "dm-fictif" },
    contextBinding: {
      agentId: "main",
      sessionKey: params.route.routeSessionKey,
      messageId: params.messageId,
      inboundEventKind: "user_request",
    },
    dmPolicy: "allowlist",
    groupPolicy: "allowlist",
    allowFrom: ["sender-a"],
  });
  const context = await createHostChannelInboundEventContextBuilder(
    buildChannelInboundEventContext,
    owner,
  )({ ...params, channelIngress });
  expect(admission.readChannelContextGatewayContextResolver(context)?.()).toBe(gateway);
  context.From = "sms:sender-b";
  admission.bindRequiredSmsTaskContext(context, Object.freeze({}));
  const copy = { ...context };
  admission.copyChannelParticipantAdmissionEvidence(context, copy);
  expect(admission.readChannelContextGatewayContextResolver(copy)).toBeUndefined();
  expect(
    admission.consumeChannelAdmissionEvidence(admission.readChannelContextAdmissionEvidence(copy))
      .ingressState,
  ).toBe("unknown");
  audit.close();
});

it("closes after a native guard throws and cannot be revived", async () => {
  const guard = vi.fn<() => void>().mockImplementationOnce(() => {
    throw new Error("native guard failed");
  });
  const f = await taskFixture(undefined, guard);
  expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
  expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
});

it("checks original Host before a callback that could affect a successor", async () => {
  const f = await taskFixture();
  f.replace();
  expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
  expect(f.guard).not.toHaveBeenCalled();
});

it("does not consult accessors while capturing the runtime", async () => {
  const { createOpsysSmsRequiredTaskRuntime } = await import("./opsys-sms-task-runtime.js");
  const runtime = createRuntimeChannel();
  const getter = vi.fn(() => "untrusted");
  Object.defineProperty(runtime.inbound, "extra", { enumerable: true, get: getter });
  const authority: OpsysSmsHostAuthority = Object.freeze({
    isCurrent: () => false,
    captureSelection: () => {
      throw new Error(refused);
    },
    publish: () => false,
    revoke: () => {},
  });
  expect(() =>
    createOpsysSmsRequiredTaskRuntime({
      runtime,
      authority,
      accountId: "default",
      lifetime: {},
      abortSignal: new AbortController().signal,
      assertCurrent: () => {},
    }),
  ).toThrow(refused);
  expect(getter).not.toHaveBeenCalled();
});

it("rejects a prepared accessor without executing it or native record", async () => {
  const f = await taskFixture();
  const p = preparedInput();
  const getter = vi.fn(() => 1);
  Object.defineProperty(p.input, "extra", { enumerable: true, get: getter });
  expect(() => f.task.runtime.inbound.runPreparedReply(p.input)).toThrow(refused);
  expect(getter).not.toHaveBeenCalled();
  expect(p.record).not.toHaveBeenCalled();
});

it("rechecks after a reentrant prior guard before native record", async () => {
  const f = await taskFixture();
  const p = preparedInput();
  await expect(
    f.task.runtime.inbound.runPreparedReply({
      ...p.input,
      assertDispatchCurrent: () => f.task.dispose(),
    }),
  ).rejects.toThrow(refused);
  expect(p.record).not.toHaveBeenCalled();
  expect(p.dispatch).not.toHaveBeenCalled();
});

it("uses the real canonical builder and prepared kernel without granting Source", async () => {
  const f = await taskFixture();
  const bind = vi.spyOn(admission, "bindRequiredSmsTaskContext");
  const context = f.task.runtime.inbound.buildContext(builderInput());
  expect(context).not.toBeInstanceOf(Promise);
  const owner = bind.mock.calls.at(-1)![1];
  expect(admission.isRequiredSmsTaskContextCurrent(context, owner)).toBe(true);
  expect(admission.readChannelContextAdmissionEvidence(context)).toBeUndefined();
  const p = preparedInput(context);
  const result = await f.task.runtime.turn.runPreparedReply(p.input);
  expect(result.dispatched).toBe(true);
  expect(p.record).toHaveBeenCalledTimes(1);
  expect(p.dispatch).toHaveBeenCalledTimes(1);
});

it("retains the native resolver before an await and fences stale results", async () => {
  const f = await taskFixture();
  const p = preparedInput();
  let release!: (v: typeof p.input) => void;
  const pending = new Promise<typeof p.input>((resolve) => {
    release = resolve;
  });
  let entered!: () => void;
  const atResolve = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const resolveTurn = vi.fn(() => {
    entered();
    return pending;
  });
  const adapter = { ingest: () => ({ rawText: "fictif" }), resolveTurn };
  const run = f.task.runtime.inbound.run({
    channel: "sms",
    accountId: "default",
    raw: {},
    adapter,
  });
  await atResolve;
  adapter.resolveTurn = vi.fn(() => Promise.resolve(p.input));
  f.abort.abort();
  release(p.input);
  await expect(run).rejects.toThrow(refused);
  expect(p.record).not.toHaveBeenCalled();
  expect(p.dispatch).not.toHaveBeenCalled();
});

it("rejects unknown Proxy input without any traps", async () => {
  const f = await taskFixture();
  const trap = vi.fn();
  const proxy = new Proxy(builderInput(), {
    get: trap,
    ownKeys: trap,
    getOwnPropertyDescriptor: trap,
  });
  expect(() => f.task.runtime.inbound.buildContext(proxy)).toThrow(refused);
  expect(trap).not.toHaveBeenCalled();
});

it("traverses actual managed runtime and context views without unwrapping", async () => {
  const f = await taskFixture();
  const instance = new PluginInstance("fictitious SMS Task");
  const runtime = instance.wrap(f.task.runtime);
  expect(runtime.inbound).toBe(runtime.turn);
  const context = runtime.inbound.buildContext(builderInput());
  const p = preparedInput(context);
  const result = await runtime.turn.runPreparedReply(p.input);
  expect(result.dispatched).toBe(true);
  expect(p.record).toHaveBeenCalledTimes(1);
  await instance.dispose();
});

it("captures a real async builder result only while the original Task is current", async () => {
  const native = createRuntimeChannel();
  const original = native.inbound.buildContext;
  let release!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  const deferred = new Proxy(original, {
    apply: async (fn, receiver, args) => {
      await wait;
      return Reflect.apply(fn, receiver, args);
    },
  });
  native.inbound.buildContext = deferred;
  const f = await taskFixture(native);
  const pending = f.task.runtime.inbound.buildContext(builderInput());
  f.replace();
  release();
  await expect(pending).rejects.toThrow(refused);
  expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
});

it("does not turn another Task context into a current requirement", async () => {
  const first = await taskFixture();
  const second = await taskFixture();
  const context = first.task.runtime.inbound.buildContext(builderInput());
  const p = preparedInput(context);
  await expect(second.task.runtime.inbound.runPreparedReply(p.input)).rejects.toThrow(refused);
  expect(p.record).not.toHaveBeenCalled();
  expect(p.dispatch).not.toHaveBeenCalled();
});

it.each(["abort", "dispose", "method replacement"])(
  "keeps %s closed without invoking native work",
  async (reason) => {
    const f = await taskFixture();
    if (reason === "abort") {
      f.abort.abort();
    }
    if (reason === "dispose") {
      f.task.dispose();
    }
    if (reason === "method replacement") {
      f.runtime.inbound.buildContext = createRuntimeChannel().inbound.buildContext.bind({});
    }
    expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
    expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
  },
);

it.each([
  { channel: "webform", accountId: "default" },
  { channel: "sms", accountId: "foreign" },
])("rejects foreign public channel/account without native record", async (scope) => {
  const f = await taskFixture();
  const p = preparedInput();
  expect(() => f.task.runtime.inbound.runPreparedReply({ ...p.input, ...scope })).toThrow(refused);
  expect(p.record).not.toHaveBeenCalled();
});

it("captures adapter getters before ingest and does not execute them", async () => {
  const f = await taskFixture();
  const ingest = vi.fn(() => ({ id: "SM-fictif", rawText: "fictif" }));
  const adapter = { ingest };
  const getter = vi.fn(() => () => preparedInput().input);
  Object.defineProperty(adapter, "resolveTurn", { enumerable: true, get: getter });
  expect(() =>
    f.task.runtime.inbound.run({ channel: "sms", accountId: "default", raw: {}, adapter } as never),
  ).toThrow(refused);
  expect(getter).not.toHaveBeenCalled();
  expect(ingest).not.toHaveBeenCalled();
});

it("preserves top and plan guards, callbacks captured before await and canonical finalization", async () => {
  const f = await taskFixture();
  const p = preparedInput();
  const top = vi.fn();
  const plan = vi.fn();
  const finalize = vi.fn();
  let release!: () => void;
  let entered!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  const atIngest = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const originalResolve = vi.fn(() => ({ ...p.input, assertDispatchCurrent: plan }));
  const adapter = {
    ingest: async () => {
      entered();
      await wait;
      return { id: "SM-fictif", rawText: "fictif" };
    },
    resolveTurn: originalResolve,
    onFinalize: finalize,
  };
  const run = f.task.runtime.inbound.run({
    channel: "sms",
    accountId: "default",
    raw: {},
    adapter,
    assertDispatchCurrent: top,
  });
  await atIngest;
  adapter.resolveTurn = vi.fn(() => {
    throw new Error("replacement resolver");
  });
  release();
  const result = await run;
  expect(result.dispatched).toBe(true);
  expect(originalResolve).toHaveBeenCalledTimes(1);
  expect(adapter.resolveTurn).not.toHaveBeenCalled();
  expect(top).toHaveBeenCalled();
  expect(plan).toHaveBeenCalled();
  expect(finalize).toHaveBeenCalledWith(expect.objectContaining({ dispatched: true }));
  expect(p.record).toHaveBeenCalledTimes(1);
  expect(p.dispatch).toHaveBeenCalledTimes(1);
});

it("retains native failed finalization after a plan guard rejects", async () => {
  const f = await taskFixture();
  const p = preparedInput();
  const finalize = vi.fn();
  await expect(
    f.task.runtime.inbound.run({
      channel: "sms",
      accountId: "default",
      raw: {},
      adapter: {
        ingest: () => ({ id: "SM-fictif", rawText: "fictif" }),
        resolveTurn: () => ({
          ...p.input,
          assertDispatchCurrent: () => {
            throw new Error("rejected guard");
          },
        }),
        onFinalize: finalize,
      },
    }),
  ).rejects.toThrow(refused);
  expect(finalize).toHaveBeenCalledWith(expect.objectContaining({ dispatched: false }));
  expect(p.record).not.toHaveBeenCalled();
  expect(p.dispatch).not.toHaveBeenCalled();
});

it.each(["prepared", "routed", "assembled"])(
  "runs the actual %s branch with a private Task requirement",
  async (branch) => {
    const f = await taskFixture();
    const p = preparedInput();
    const bind = vi.spyOn(admission, "bindRequiredSmsTaskContext");
    const resolved =
      branch === "prepared"
        ? p.input
        : branch === "routed"
          ? {
              cfg: {},
              channel: "sms",
              accountId: "default",
              ctxPayload: p.input.ctxPayload,
              route: { agentId: "main", sessionKey: p.input.routeSessionKey },
              delivery: { deliver: async () => undefined },
            }
          : {
              cfg: {},
              channel: "sms",
              accountId: "default",
              ctxPayload: p.input.ctxPayload,
              agentId: "main",
              routeSessionKey: p.input.routeSessionKey,
              storePath: p.input.storePath,
              recordInboundSession: p.record,
              dispatchReplyWithBufferedBlockDispatcher: routedDispatch,
              delivery: { deliver: async () => undefined },
            };
    const result = await f.task.runtime.inbound.run({
      channel: "sms",
      accountId: "default",
      raw: {},
      adapter: {
        ingest: () => ({ id: "SM-fictif", rawText: "fictif" }),
        resolveTurn: () => resolved,
      },
    } as never);
    expect(result.dispatched).toBe(true);
    expect(bind).toHaveBeenCalled();
    const owner = bind.mock.calls.at(-1)![1];
    expect(admission.isRequiredSmsTaskContextCurrent(p.input.ctxPayload, owner)).toBe(true);
    if (branch === "routed") {
      expect(sessionRecord).toHaveBeenCalledTimes(1);
    } else {
      expect(p.record).toHaveBeenCalledTimes(1);
    }
  },
);

it.each(["dispatch", "dispatchReply"] as const)(
  "stamps %s and refuses a stale Task before native dispatch",
  async (method) => {
    const f = await taskFixture();
    const p = preparedInput();
    const input =
      method === "dispatch"
        ? {
            cfg: {},
            channel: "sms",
            accountId: "default",
            ctxPayload: p.input.ctxPayload,
            route: { agentId: "main", sessionKey: p.input.routeSessionKey },
            delivery: { deliver: async () => undefined },
          }
        : {
            cfg: {},
            channel: "sms",
            accountId: "default",
            ctxPayload: p.input.ctxPayload,
            agentId: "main",
            routeSessionKey: p.input.routeSessionKey,
            storePath: p.input.storePath,
            recordInboundSession: p.record,
            dispatchReplyWithBufferedBlockDispatcher: routedDispatch,
            delivery: { deliver: async () => undefined },
          };
    await expect(f.task.runtime.turn[method](input as never)).resolves.toMatchObject({
      dispatched: true,
    });
    f.task.dispose();
    expect(() => f.task.runtime.turn[method](input as never)).toThrow(refused);
  },
);

it("leaves nonselected webform context and ordinary runtime aliases unchanged", () => {
  const runtime = createRuntimeChannel();
  const context = runtime.inbound.buildContext({ ...builderInput(), channel: "webform" });
  expect(runtime.inbound).toBe(runtime.turn);
  expect(context.Provider).toBe("webform");
});

it("rejects a context getter without reading its body or recording the turn", async () => {
  const f = await taskFixture();
  const p = preparedInput();
  const getter = vi.fn(() => "untrusted body");
  Object.defineProperty(p.input.ctxPayload, "Body", { enumerable: true, get: getter });
  expect(() => f.task.runtime.inbound.runPreparedReply(p.input)).toThrow(refused);
  expect(getter).not.toHaveBeenCalled();
  expect(p.record).not.toHaveBeenCalled();
});

it("rechecks Task liveness after a reentrant native guard", async () => {
  let close = () => {};
  const guard = vi.fn(() => close());
  const f = await taskFixture(undefined, guard);
  close = f.task.dispose;
  expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
  expect(() => f.task.runtime.inbound.buildContext(builderInput())).toThrow(refused);
});

it.each(["unchanged", "retarget"])(
  "preserves Task1 requirement under public Host finalize rebind to Task2 (%s)",
  async (scope) => {
    const first = await taskFixture();
    const original = first.task.runtime.inbound.buildContext(builderInput());
    if (scope === "retarget") {
      original.From = "sms:sender-b";
    }
    const native = createRuntimeChannel();
    native.inbound.buildContext = buildHostChannelInboundEventContext;
    const second = await taskFixture(native);
    const finalize = vi.fn(() => original);
    const rebound = second.task.runtime.inbound.buildContext({
      ...builderInput(),
      from: original.From,
      finalize,
    });
    expect(rebound).toBe(original);
    expect(finalize).toHaveBeenCalledTimes(1);
    const p = preparedInput(rebound);
    await expect(second.task.runtime.inbound.runPreparedReply(p.input)).rejects.toThrow(refused);
    expect(p.record).not.toHaveBeenCalled();
    expect(p.dispatch).not.toHaveBeenCalled();
  },
);

it("cannot reset the same Task's changed-scope poison through the public Host builder", async () => {
  const f = await taskFixture();
  const original = f.task.runtime.inbound.buildContext(builderInput());
  original.From = "sms:sender-b";
  // Stamp the changed scope with this same Task first; the poison is already terminal for the context.
  f.task.runtime.inbound.buildContext({
    ...builderInput(),
    from: "sms:sender-b",
    finalize: () => original,
  });
  expect(
    buildHostChannelInboundEventContext({
      ...builderInput(),
      from: "sms:sender-b",
      finalize: () => original,
    }),
  ).toBe(original);
  const p = preparedInput(original);
  await expect(f.task.runtime.inbound.runPreparedReply(p.input)).rejects.toThrow(refused);
  expect(p.record).not.toHaveBeenCalled();
  expect(p.dispatch).not.toHaveBeenCalled();
});

it("does not clear a target Task requirement when ordinary participant evidence is copied onto it", async () => {
  const f = await taskFixture();
  const target = f.task.runtime.inbound.buildContext(builderInput());
  const ordinary = buildHostChannelInboundEventContext(builderInput());
  admission.copyChannelParticipantAdmissionEvidence(ordinary, target);
  target.From = "sms:sender-b";
  const native = createRuntimeChannel();
  native.inbound.buildContext = buildHostChannelInboundEventContext;
  const second = await taskFixture(native);
  second.task.runtime.inbound.buildContext({
    ...builderInput(),
    from: "sms:sender-b",
    finalize: () => target,
  });
  const p = preparedInput(target);
  await expect(second.task.runtime.inbound.runPreparedReply(p.input)).rejects.toThrow(refused);
  expect(p.record).not.toHaveBeenCalled();
  expect(p.dispatch).not.toHaveBeenCalled();
});

it("keeps fresh public Host finalize contexts and nonselected webform controls ordinary", async () => {
  const native = createRuntimeChannel();
  native.inbound.buildContext = buildHostChannelInboundEventContext;
  const f = await taskFixture(native);
  const context = f.task.runtime.inbound.buildContext(builderInput());
  const p = preparedInput(context);
  await expect(f.task.runtime.inbound.runPreparedReply(p.input)).resolves.toMatchObject({
    dispatched: true,
  });
  expect(p.record).toHaveBeenCalledTimes(1);
  const ordinary = buildHostChannelInboundEventContext({ ...builderInput(), channel: "webform" });
  expect(ordinary.Provider).toBe("webform");
});

it.each(["prepared", "public builder"])(
  "retains exact-context Task denial after public configurable-symbol deletion (%s)",
  async (entry) => {
    const first = await taskFixture();
    const retained = first.task.runtime.inbound.buildContext(builderInput());
    // Public reflection only: no imported private symbol or fabricated admission cell.
    let deleted = 0;
    for (const key of Reflect.ownKeys(retained)) {
      if (typeof key === "symbol" && Object.getOwnPropertyDescriptor(retained, key)?.configurable) {
        expect(Reflect.deleteProperty(retained, key)).toBe(true);
        deleted += 1;
      }
    }
    expect(deleted).toBeGreaterThan(0);
    const native = createRuntimeChannel();
    if (entry === "public builder") {
      native.inbound.buildContext = buildHostChannelInboundEventContext;
    }
    const second = await taskFixture(native);
    const context =
      entry === "public builder"
        ? second.task.runtime.inbound.buildContext({
            ...builderInput(),
            finalize: () => retained,
          })
        : retained;
    const p = preparedInput(context);
    await expect(second.task.runtime.inbound.runPreparedReply(p.input)).rejects.toThrow(refused);
    expect(p.record).not.toHaveBeenCalled();
    expect(p.dispatch).not.toHaveBeenCalled();
  },
);
