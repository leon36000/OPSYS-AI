import { afterEach, describe, expect, it, vi } from "vitest";
import { smsPlugin } from "../../extensions/sms/channel-plugin-api.js";
import { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { createPluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { createEmptyPluginRegistry } from "../plugins/registry.js";
import { createChannelTestPluginBase } from "../test-utils/channel-plugins.js";
import {
  createOpsysSmsHostAuthority,
  OPSYS_SMS_HOST_SELECTION_REFUSED,
  type CreateOpsysSmsHostAuthorityParams,
} from "./opsys-sms-host-authority.js";

// Fictitious host-owned config/account/grant seams; no provider or SQL authority.
function fixture(accountId = "default") {
  const accountSid = "AC" + "1".repeat(32);
  const accounts: Record<string, Record<string, unknown>> = accountId === "default"
    ? {}
    : { [accountId]: {} };
  const sms = {
    enabled: true,
    accountSid,
    authToken: "host-token-fictif",
    fromNumber: "+15145550101",
    publicWebhookUrl: "https://sms-fictif.example/webhooks/sms",
    dangerouslyDisableSignatureValidation: false,
    accounts,
  };
  const marker = {
    profileId: "sms-demo",
    profileRevision: 7,
    smsIngress: { version: 1 as const, accountId, accountSid },
  };
  const cfg: OpenClawConfig = {
    agents: { list: [{ id: "opsys-agent-sms-demo", opsysRuntimeAdmission: marker }] },
    channels: { sms },
    bindings: [{ agentId: "opsys-agent-sms-demo", match: { channel: "sms", accountId } }],
  };
  let runtimeConfig = cfg;
  const account = {
    accountId,
    accountSid,
    enabled: true,
    authToken: "host-token-fictif",
    dangerouslyDisableSignatureValidation: false,
    fromNumber: sms.fromNumber,
    messagingServiceSid: "",
    defaultTo: "",
    publicWebhookUrl: sms.publicWebhookUrl,
    webhookPath: "/webhooks/sms",
    dmPolicy: "pairing",
    allowFrom: [],
    textChunkLimit: 1500,
  };
  const registry = createEmptyPluginRegistry();
  const plugin = createChannelTestPluginBase({ id: "sms" });
  let grantActive = true;
  const grant = vi.fn(() => grantActive);
  const capture = vi.fn(() => grant);
  registry.channels.push({
    pluginId: "sms",
    source: "fictif",
    origin: "bundled",
    plugin,
    captureReadAuthority: capture,
  });
  const registration = getLoadedChannelPluginEntryById("sms", registry);
  if (!registration) {
    throw new Error("Missing fictitious registration");
  }
  let currentRegistration = registration;
  let lifetimeCurrent = true;
  let taskCurrent = false;
  const task = vi.fn(() => taskCurrent);
  const abort = new AbortController();
  const lease = createPluginRuntimeCapabilityLease("fictitious SMS lifetime");
  const params: CreateOpsysSmsHostAuthorityParams = {
    cfg,
    getRuntimeConfig: () => runtimeConfig,
    channelId: "sms",
    accountId,
    account,
    registration,
    getCurrentRegistration: () => currentRegistration,
    abortSignal: abort.signal,
    capabilityLease: lease,
    isCurrentLifetime: () => lifetimeCurrent,
    isCurrentTask: task,
  };
  return {
    fictif: true,
    params,
    cfg,
    sms,
    marker,
    account,
    registration,
    capture,
    grant,
    abort,
    lease,
    task,
    setConfig: (next: OpenClawConfig) => {
      runtimeConfig = next;
    },
    setRegistration: (next: typeof registration) => {
      currentRegistration = next;
    },
    setGrant: (value: boolean) => {
      grantActive = value;
    },
    setLifetime: (value: boolean) => {
      lifetimeCurrent = value;
    },
    setTask: (value: boolean) => {
      taskCurrent = value;
    },
  };
}

function prepared(f = fixture()) {
  const host = createOpsysSmsHostAuthority(f.params);
  if (!host) {
    throw new Error("Expected selected fictitious SMS host");
  }
  return host;
}

function live(f = fixture()) {
  const host = prepared(f);
  f.setTask(true);
  expect(host.publish()).toBe(true);
  expect(host.isCurrent()).toBe(true);
  return host;
}

afterEach(() => vi.restoreAllMocks());

describe("private SMS host authority", () => {
  it("prepares an explicit base/default without consulting the unpublished task", () => {
    const f = fixture();
    const host = prepared(f);
    expect(host.isCurrent()).toBe(false);
    expect(f.task).not.toHaveBeenCalled();
    expect(f.capture).toHaveBeenCalledTimes(1);
    f.setTask(true);
    expect(host.publish()).toBe(true);
    expect(host.isCurrent()).toBe(true);
    expect(f.capture).toHaveBeenCalledTimes(1);
    expect(Object.keys(host).toSorted()).toEqual([
      "captureSelection",
      "isCurrent",
      "publish",
      "revoke",
    ]);
  });

  it.each(["default", "support"])("accepts an explicitly owned %s account", (id) => {
    const f = fixture(id);
    Object.assign(f.sms.accounts, { [id]: {} });
    live(f);
  });

  it("leaves non-SMS and genuinely unselected legacy SMS inert", () => {
    const f = fixture();
    expect(createOpsysSmsHostAuthority({ ...f.params, channelId: "discord" })).toBeUndefined();
    Reflect.deleteProperty(f.marker, "smsIngress");
    expect(createOpsysSmsHostAuthority(f.params)).toBeUndefined();
    expect(f.capture).not.toHaveBeenCalled();
    expect(f.task).not.toHaveBeenCalled();
  });

  it.each([
    [
      "account alias",
      (f: ReturnType<typeof fixture>) => {
        f.marker.smsIngress.accountId = "Default";
      },
    ],
    [
      "SID coercion",
      (f: ReturnType<typeof fixture>) => {
        f.sms.accountSid += " ";
      },
    ],
    [
      "marker extra",
      (f: ReturnType<typeof fixture>) => {
        Object.assign(f.marker.smsIngress, { actor: "fictif" });
      },
    ],
    [
      "bool revision",
      (f: ReturnType<typeof fixture>) => {
        Object.assign(f.marker, { profileRevision: true });
      },
    ],
    [
      "unsafe revision",
      (f: ReturnType<typeof fixture>) => {
        f.marker.profileRevision = 2 ** 53;
      },
    ],
    [
      "wrong agent",
      (f: ReturnType<typeof fixture>) => {
        if (f.cfg.agents?.list) {
          f.cfg.agents.list[0].id = "other";
        }
      },
    ],
    [
      "disabled",
      (f: ReturnType<typeof fixture>) => {
        f.sms.enabled = false;
      },
    ],
    [
      "dangerous raw",
      (f: ReturnType<typeof fixture>) => {
        f.sms.dangerouslyDisableSignatureValidation = true;
      },
    ],
    [
      "dangerous resolved",
      (f: ReturnType<typeof fixture>) => {
        f.account.dangerouslyDisableSignatureValidation = true;
      },
    ],
    [
      "resolved SID",
      (f: ReturnType<typeof fixture>) => {
        f.account.accountSid = "AC" + "2".repeat(32);
      },
    ],
    [
      "masked credential",
      (f: ReturnType<typeof fixture>) => {
        f.account.authToken = "other-fictif";
      },
    ],
    [
      "homonymous registration",
      (f: ReturnType<typeof fixture>) => {
        Object.assign(f.registration, { pluginId: "other" });
      },
    ],
    [
      "official nonbundled",
      (f: ReturnType<typeof fixture>) => {
        Object.assign(f.registration, { origin: "global", trustedOfficialInstall: true });
      },
    ],
    [
      "missing capture",
      (f: ReturnType<typeof fixture>) => {
        Object.assign(f.registration, { captureReadAuthority: undefined });
      },
    ],
    [
      "missing binding",
      (f: ReturnType<typeof fixture>) => {
        f.cfg.bindings = [];
      },
    ],
    [
      "foreign owner",
      (f: ReturnType<typeof fixture>) => {
        if (f.cfg.bindings) {
          f.cfg.bindings[0].agentId = "foreign";
        }
      },
    ],
  ])("refuses selected malformed %s with a constant error", (_, change) => {
    const f = fixture();
    change(f);
    expect(() => createOpsysSmsHostAuthority(f.params)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    expect(f.task).not.toHaveBeenCalled();
  });

  it("rejects ENV-only selection and a missing named account before the shared base merge", () => {
    const f = fixture();
    f.setConfig({ ...f.cfg, channels: { sms: {} } });
    f.params.cfg = { ...f.cfg, channels: { sms: {} } };
    expect(() => createOpsysSmsHostAuthority(f.params)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    const named = fixture("support");
    delete named.sms.accounts.support;
    expect(() => createOpsysSmsHostAuthority(named.params)).toThrow(
      OPSYS_SMS_HOST_SELECTION_REFUSED,
    );
  });

  it.each(["account", "profile", "SID"])(
    "rejects a final newline in the complete %s identity",
    (field) => {
      const f = fixture();
      if (field === "account") {
        f.marker.smsIngress.accountId += "\n";
      }
      if (field === "profile") {
        f.marker.profileId += "\n";
        if (f.cfg.agents?.list) {
          f.cfg.agents.list[0].id += "\n";
        }
        if (f.cfg.bindings) {
          f.cfg.bindings[0].agentId += "\n";
        }
      }
      if (field === "SID") {
        f.marker.smsIngress.accountSid += "\n";
        f.sms.accountSid += "\n";
        f.account.accountSid += "\n";
      }
      expect(() => createOpsysSmsHostAuthority(f.params)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
      expect(f.capture).not.toHaveBeenCalled();
      expect(f.task).not.toHaveBeenCalled();
    },
  );

  it("rejects a resolved SID supplied without a raw selected SID even with configured credentials", () => {
    const f = fixture();
    Reflect.deleteProperty(f.sms, "accountSid");
    expect(f.sms.authToken).toBe(f.account.authToken);
    expect(f.account.accountSid).toBe(f.marker.smsIngress.accountSid);
    expect(() => createOpsysSmsHostAuthority(f.params)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    expect(f.capture).not.toHaveBeenCalled();
  });

  it("refuses ambiguous selections and roster entries hiding their real ID", () => {
    const f = fixture();
    f.cfg.agents?.list?.push({ id: "opsys-agent-sms-demo", opsysRuntimeAdmission: f.marker });
    expect(() => createOpsysSmsHostAuthority(f.params)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    const g = fixture();
    g.cfg.agents = { entries: { "opsys-agent-sms-demo": { opsysRuntimeAdmission: g.marker } } };
    live(g);
    const entry = g.cfg.agents.entries?.["opsys-agent-sms-demo"];
    if (!entry) {
      throw new Error("Missing fictitious entry");
    }
    Object.assign(entry, { id: "hidden-agent" });
    expect(() => createOpsysSmsHostAuthority(g.params)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
  });

  it.each(["owner", "task", "abort", "lease", "grant", "capture", "origin", "plugin"])(
    "revokes irreversibly after observed %s replacement",
    (kind) => {
      const f = fixture();
      const host = live(f);
      if (kind === "owner") {
        f.setLifetime(false);
      }
      if (kind === "task") {
        f.setTask(false);
      }
      if (kind === "abort") {
        f.abort.abort();
      }
      if (kind === "lease") {
        f.lease.revoke();
      }
      if (kind === "grant") {
        f.setGrant(false);
      }
      if (kind === "capture") {
        f.setRegistration({ ...f.registration, captureReadAuthority: () => () => true });
      }
      if (kind === "origin") {
        f.setRegistration({ ...f.registration, origin: "global" });
      }
      if (kind === "plugin") {
        f.setRegistration({ ...f.registration, plugin: { ...f.registration.plugin } });
      }
      expect(host.isCurrent()).toBe(false);
      f.setLifetime(true);
      f.setTask(true);
      f.setGrant(true);
      f.setRegistration(f.registration);
      expect(host.publish()).toBe(false);
      expect(host.isCurrent()).toBe(false);
      expect(f.capture).toHaveBeenCalledTimes(1);
    },
  );

  it.each([
    "authToken",
    "fromNumber",
    "publicWebhookUrl",
    "textChunkLimit",
    "allowFrom",
    "configWrites",
  ])("closes on visible selected config change %s", (field) => {
    const f = fixture();
    const host = live(f);
    Object.assign(f.sms, { [field]: field === "textChunkLimit" ? 1400 : "changed-fictif" });
    expect(host.isCurrent()).toBe(false);
    expect(host.publish()).toBe(false);
  });

  it("observes mutations of the resolved account, rather than retaining initial facts", () => {
    const f = fixture();
    const host = live(f);
    f.account.webhookPath = "/different";
    expect(host.isCurrent()).toBe(false);
  });

  it("ignores unrelated sibling changes but closes visible selected marker revision", () => {
    const f = fixture("support");
    const host = live(f);
    Object.assign(f.sms.accounts, { other: { authToken: "sibling-fictif" } });
    expect(host.isCurrent()).toBe(true);
    f.marker.profileRevision += 1;
    expect(host.isCurrent()).toBe(false);
  });

  it("closes on selected binding removal without adopting a new owner", () => {
    const f = fixture();
    const host = live(f);
    f.cfg.bindings = [];
    expect(host.isCurrent()).toBe(false);
    f.cfg.bindings = [
      { agentId: "opsys-agent-sms-demo", match: { channel: "sms", accountId: "default" } },
    ];
    expect(host.publish()).toBe(false);
  });

  it("does not publish without a current task, and revoke is idempotent", () => {
    const f = fixture();
    const host = prepared(f);
    expect(host.publish()).toBe(false);
    f.setTask(true);
    expect(host.publish()).toBe(false);
    host.revoke();
    host.revoke();
    expect(host.isCurrent()).toBe(false);
  });
});

describe("selected SMS binding scope (fictitious config)", () => {
  it.each([undefined, "", " ", "DEFAULT", "Default", "default\n", "!!!", "*"])(
    "refuses an applicable competing default binding %j before borrowing a grant",
    (accountId) => {
      const f = fixture();
      f.cfg.bindings?.unshift({ agentId: "foreign-agent", match: { channel: "sms", accountId } });
      expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
      expect(f.capture).not.toHaveBeenCalled();
    },
  );

  it.each([" SMS ", "SMS"])("refuses a relevant channel alias %s", (channel) => {
    const f = fixture();
    f.cfg.bindings?.unshift({ agentId: "foreign-agent", match: { channel, accountId: "default" } });
    expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
  });

  it.each(["sales", " SALES ", "*"])(
    "refuses an applicable named-account competitor %s",
    (accountId) => {
      const f = fixture("sales");
      f.cfg.bindings?.unshift({ agentId: "foreign-agent", match: { channel: "sms", accountId } });
      expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    },
  );

  it("refuses a higher-priority peer on the same account", () => {
    const f = fixture();
    f.cfg.bindings?.unshift({
      agentId: "foreign-agent",
      match: {
        channel: "sms",
        accountId: "default",
        peer: { kind: "direct", id: "+15145550102" },
      },
    });
    expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
  });

  it("preserves genuinely foreign channels/accounts and ignores their live metadata", () => {
    const f = fixture("sales");
    const foreign = { agentId: "foreign-agent", comment: "foreign", match: { channel: "sms" } };
    f.cfg.bindings?.unshift(foreign, {
      agentId: "foreign-agent",
      match: { channel: "telegram", accountId: "*" },
    });
    const host = live(f);
    foreign.comment = "changed elsewhere";
    expect(host.isCurrent()).toBe(true);
  });

  it("accepts the generator metadata shape without weakening exact account selection", () => {
    const f = fixture();
    Object.assign(f.cfg.bindings?.[0] ?? {}, {
      type: "route",
      comment: "OPSYS selected SMS route",
      session: { dmScope: "per-channel-peer" },
    });
    expect(live(f).isCurrent()).toBe(true);
  });

  it.each([
    { comment: 7 },
    { session: null },
    { session: {} },
    { session: { dmScope: "main" } },
    { session: { dmScope: "per-channel-peer", extra: true } },
    { extra: true },
  ])("refuses malformed selected metadata %j", (metadata) => {
    const f = fixture();
    Object.assign(f.cfg.bindings?.[0] ?? {}, metadata);
    expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
  });

  it.each(["comment", "session"])("revokes when selected %s metadata changes live", (key) => {
    const f = fixture();
    Object.assign(f.cfg.bindings?.[0] ?? {}, {
      comment: "original",
      session: { dmScope: "per-channel-peer" },
    });
    const host = live(f);
    Object.assign(f.cfg.bindings?.[0] ?? {}, { [key]: key === "comment" ? "changed" : undefined });
    expect(host.isCurrent()).toBe(false);
    Object.assign(f.cfg.bindings?.[0] ?? {}, {
      comment: "original",
      session: { dmScope: "per-channel-peer" },
    });
    expect(host.isCurrent()).toBe(false);
  });
});

describe("selected configured credential (fictitious env only)", () => {
  it("refuses default ENV-only auth even with explicit config SID and a real resolved account", () => {
    const f = fixture();
    Object.assign(f.sms, { authToken: undefined });
    vi.stubEnv("TWILIO_AUTH_TOKEN", "env-token-fictif");
    try {
      const account = smsPlugin.config.resolveAccount(f.cfg, "default");
      expect(account.authToken).toBe("env-token-fictif");
      expect(account.accountSid).toBe(f.marker.smsIngress.accountSid);
      f.params.account = account;
      expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
      expect(f.capture).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("keeps an unselected legacy ENV fallback outside this constructor", () => {
    const f = fixture();
    Object.assign(f.sms, { authToken: undefined });
    f.cfg.agents = { list: [{ id: "legacy" }] };
    vi.stubEnv("TWILIO_AUTH_TOKEN", "env-token-fictif");
    try {
      f.params.account = smsPlugin.config.resolveAccount(f.cfg, "default");
      expect(createOpsysSmsHostAuthority(f.params)).toBeUndefined();
      expect(f.capture).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it.each([
    null,
    "",
    " ",
    { source: "env", provider: "default", id: "SMS_FICTIF_TOKEN" },
    "${SMS_FICTIF_TOKEN}",
  ])("refuses unavailable selected config auth %j with a constant error", (authToken) => {
    const f = fixture();
    Object.assign(f.sms, { authToken });
    expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    expect(f.capture).not.toHaveBeenCalled();
  });

  it("keeps a visible SecretRef rotation sticky after publication", () => {
    const f = fixture();
    const host = live(f);
    Object.assign(f.sms, {
      authToken: { source: "env", provider: "default", id: "SMS_FICTIF_TOKEN" },
    });
    expect(host.isCurrent()).toBe(false);
    Object.assign(f.sms, { authToken: "host-token-fictif" });
    expect(host.isCurrent()).toBe(false);
    expect(host.publish()).toBe(false);
  });

  it("requires the selected own credential rather than a sibling's value", () => {
    const f = fixture("support");
    Object.assign(f.sms, { authToken: undefined });
    Object.assign(f.sms.accounts, { other: { authToken: "host-token-fictif" } });
    expect(() => prepared(f)).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
  });

  it("accepts a selected own literal token resolved by the real account owner", () => {
    const f = fixture("support");
    f.sms.accounts.support = { authToken: "selected-token-fictif" };
    f.params.account = smsPlugin.config.resolveAccount(f.cfg, "support");
    expect(live(f).isCurrent()).toBe(true);
  });
});

describe("captureSelection private seam", () => {
  it.each(["default", "support"])("captures frozen original public scalars for %s", (accountId) => {
    const f = fixture(accountId);
    const host = live(f);
    const selection = host.captureSelection();
    expect(selection).toEqual({
      accountId,
      accountSid: f.account.accountSid,
      fromNumber: f.account.fromNumber,
      publicWebhookUrl: f.account.publicWebhookUrl,
      permission: {
        profil_id: "sms-demo",
        revision_profil: 7,
        outil_m1: "opsys_m1__m1_recevoir_message_canal",
      },
    });
    expect(Object.isFrozen(selection)).toBe(true);
    expect(Object.isFrozen(selection.permission)).toBe(true);
    expect(Object.keys(selection).toSorted()).toEqual([
      "accountId",
      "accountSid",
      "fromNumber",
      "permission",
      "publicWebhookUrl",
    ]);
    expect(Object.keys(selection.permission).toSorted()).toEqual([
      "outil_m1",
      "profil_id",
      "revision_profil",
    ]);
    expect(JSON.stringify(selection)).not.toContain("host-token-fictif");
    expect(Reflect.set(selection.permission, "revision_profil", 9)).toBe(false);
    expect(selection.permission.revision_profil).toBe(7);
    expect(host.captureSelection()).toBe(selection);
  });

  it("refuses captureSelection before publish without poisoning later publication", () => {
    const f = fixture();
    const host = prepared(f);
    expect(() => host.captureSelection()).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    expect(f.task).not.toHaveBeenCalled();
    f.setTask(true);
    expect(host.publish()).toBe(true);
    expect(host.captureSelection().permission.revision_profil).toBe(7);
  });

  it.each(["revoked", "lifetime", "task", "grant", "abort"])(
    "refuses captureSelection after %s authority loss",
    (kind) => {
      const f = fixture();
      const host = live(f);
      if (kind === "revoked") {
        host.revoke();
      }
      if (kind === "lifetime") {
        f.setLifetime(false);
      }
      if (kind === "task") {
        f.setTask(false);
      }
      if (kind === "grant") {
        f.setGrant(false);
      }
      if (kind === "abort") {
        f.abort.abort();
      }
      expect(() => host.captureSelection()).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
      f.setLifetime(true);
      f.setTask(true);
      f.setGrant(true);
      expect(() => host.captureSelection()).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    },
  );

  it.each(["fromNumber", "publicWebhookUrl"])(
    "missing %s only closes captureSelection, preserving historical publication",
    (field) => {
      const f = fixture();
      Reflect.deleteProperty(f.account, field);
      const host = live(f);
      expect(host.isCurrent()).toBe(true);
      expect(() => host.captureSelection()).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
      expect(host.isCurrent()).toBe(true);
    },
  );

  it("does not recapture current P after captureSelection revocation", () => {
    const f = fixture();
    const host = live(f);
    const original = host.captureSelection();
    f.marker.profileRevision = 8;
    expect(() => host.captureSelection()).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    f.marker.profileRevision = 7;
    expect(() => host.captureSelection()).toThrow(OPSYS_SMS_HOST_SELECTION_REFUSED);
    expect(original.permission.revision_profil).toBe(7);
  });
});
