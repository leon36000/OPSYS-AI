import { listAgentEntriesWithSource, readAgentRosterProperty } from "../agents/agent-roster.js";
import { hasConfiguredAccountValue } from "../channels/plugins/account-helpers.js";
import type { getLoadedChannelPluginEntryById } from "../channels/plugins/registry-loaded.js";
import type { ChannelId } from "../channels/plugins/types.public.js";
import { resolveMergedAccountConfig } from "../config/channel-account-config.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { resolveSecretInputString } from "../config/types.secrets.js";
import type { PluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import { normalizeAccountId } from "../routing/account-id.js";
import { normalizeRouteBindingChannelId } from "../routing/binding-scope.js";
import type { CreateOpsysSmsIngressCaptureParams } from "./opsys-sms-ingress-capture.js";

export const OPSYS_SMS_HOST_SELECTION_REFUSED = "REJ-M1-SMS-HOST-SELECTION";
export type OpsysSmsHostRegistration = NonNullable<
  ReturnType<typeof getLoadedChannelPluginEntryById>
>;
export type OpsysSmsHostAuthority = Readonly<{
  publish: () => boolean;
  isCurrent: () => boolean;
  revoke: () => void;
  captureSelection: () => CreateOpsysSmsIngressCaptureParams["selection"];
}>;
export type CreateOpsysSmsHostAuthorityParams = {
  cfg: OpenClawConfig;
  getRuntimeConfig: () => OpenClawConfig;
  channelId: ChannelId;
  accountId: string;
  account: unknown;
  registration: OpsysSmsHostRegistration;
  getCurrentRegistration: () => OpsysSmsHostRegistration | undefined;
  abortSignal: AbortSignal;
  capabilityLease: PluginRuntimeCapabilityLease;
  isCurrentLifetime: () => boolean;
  isCurrentTask: () => boolean;
};

function requireSelection(condition: boolean): asserts condition {
  if (!condition) {
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  }
}

function record(value: unknown): Record<string, unknown> {
  requireSelection(value !== null && typeof value === "object" && !Array.isArray(value));
  const prototype = Object.getPrototypeOf(value);
  requireSelection(prototype === Object.prototype || prototype === null);
  const entries: Array<[string, unknown]> = [];
  for (const key of Reflect.ownKeys(value)) {
    requireSelection(typeof key === "string");
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    requireSelection(descriptor !== undefined && Object.hasOwn(descriptor, "value"));
    entries.push([key, descriptor.value]);
  }
  return Object.fromEntries(entries);
}

function exactKeys(value: Record<string, unknown>, keys: string[]): void {
  requireSelection(
    Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)),
  );
}

function canonicalAccount(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[a-z0-9][a-z0-9_-]{0,63}$/.test(value) &&
    !["__proto__", "prototype", "constructor"].includes(value)
  );
}

// Private value comparison, not a signature or persisted permission. Never log it.
function snapshot(value: unknown, seen = new Set<object>()): string {
  if (value === undefined) {
    return "undefined";
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    requireSelection(Number.isFinite(value));
    return JSON.stringify(value);
  }
  requireSelection(typeof value === "object" && value !== null && !seen.has(value));
  seen.add(value);
  try {
    if (Array.isArray(value)) {
      const items: string[] = [];
      for (let index = 0; index < value.length; index += 1) {
        const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
        requireSelection(descriptor !== undefined && Object.hasOwn(descriptor, "value"));
        items.push(snapshot(descriptor.value, seen));
      }
      return "[" + items.join(",") + "]";
    }
    const object = record(value);
    return (
      "{" +
      Object.keys(object)
        .toSorted()
        .map((key) => JSON.stringify(key) + ":" + snapshot(object[key], seen))
        .join(",") +
      "}"
    );
  } finally {
    seen.delete(value);
  }
}

function selectedMarker(
  cfg: OpenClawConfig,
  accountId: string,
): { id: string; marker: Record<string, unknown> } | undefined {
  const root = record(cfg);
  if (root.agents === undefined) {
    return undefined;
  }
  const agents = record(root.agents);
  const roster = readAgentRosterProperty({ agents });
  if (!roster) {
    return undefined;
  }
  const entries = roster.kind === "entries" ? record(roster.value) : undefined;
  requireSelection(roster.kind === "entries" || Array.isArray(roster.value));
  const listed = entries
    ? listAgentEntriesWithSource({ agents: { entries } })
    : listAgentEntriesWithSource({
        agents: { list: Array.isArray(roster.value) ? roster.value : [] },
      });
  const matches: Array<{ id: string; marker: Record<string, unknown> }> = [];
  for (const item of listed) {
    const entry = record(item.entry);
    if (entry.opsysRuntimeAdmission === undefined) {
      continue;
    }
    const marker = record(entry.opsysRuntimeAdmission);
    if (!Object.hasOwn(marker, "smsIngress")) {
      continue;
    }
    const ingress = record(marker.smsIngress);
    exactKeys(ingress, ["version", "accountId", "accountSid"]);
    requireSelection(ingress.version === 1 && canonicalAccount(ingress.accountId));
    if (ingress.accountId !== accountId) {
      continue;
    }
    exactKeys(marker, ["profileId", "profileRevision", "smsIngress"]);
    requireSelection(
      typeof marker.profileId === "string" && /^[a-z][a-z0-9-]{1,63}$/.test(marker.profileId),
    );
    requireSelection(
      typeof marker.profileRevision === "number" &&
        Number.isSafeInteger(marker.profileRevision) &&
        marker.profileRevision >= 1,
    );
    requireSelection(
      typeof ingress.accountSid === "string" && /^AC[0-9a-fA-F]{32}$/.test(ingress.accountSid),
    );
    requireSelection(entry.id === "opsys-agent-" + marker.profileId);
    if (item.source.kind === "entries") {
      const authored = record(entries?.[item.source.key]);
      requireSelection(!Object.hasOwn(authored, "id"));
    }
    requireSelection(typeof entry.id === "string");
    matches.push({ id: entry.id, marker });
  }
  requireSelection(matches.length <= 1);
  return matches[0];
}

function selectedBinding(
  cfg: OpenClawConfig,
  accountId: string,
  agentId: string,
): Record<string, unknown> {
  const root = record(cfg);
  requireSelection(Array.isArray(root.bindings));
  const matches: Record<string, unknown>[] = [];
  for (const raw of root.bindings) {
    const binding = record(raw);
    const match = record(binding.match);
    if (
      typeof match.channel !== "string" ||
      normalizeRouteBindingChannelId(match.channel) !== "sms"
    ) {
      continue;
    }
    requireSelection(match.accountId === undefined || typeof match.accountId === "string");
    const accountPattern = typeof match.accountId === "string" ? match.accountId.trim() : undefined;
    if (accountPattern !== "*" && normalizeAccountId(accountPattern) !== accountId) {
      continue;
    }
    // Normalization identifies conflicts only; accepted selection stays verbatim and exact.
    requireSelection(match.channel === "sms" && match.accountId === accountId);
    exactKeys(match, ["channel", "accountId"]);
    requireSelection(
      binding.agentId === agentId && (binding.type === undefined || binding.type === "route"),
    );
    requireSelection(
      Object.keys(binding).every((key) =>
        ["agentId", "match", "type", "comment", "session"].includes(key),
      ),
    );
    if (Object.hasOwn(binding, "comment")) {
      requireSelection(typeof binding.comment === "string");
    }
    if (Object.hasOwn(binding, "session")) {
      const session = record(binding.session);
      exactKeys(session, ["dmScope"]);
      requireSelection(session.dmScope === "per-channel-peer");
    }
    matches.push(binding);
  }
  requireSelection(matches.length === 1);
  return matches[0];
}

function selectionSnapshot(
  cfg: OpenClawConfig,
  accountId: string,
  accountValue: unknown,
  capturePublicSelection = false,
):
  | {
      fingerprint: string;
      selection: CreateOpsysSmsIngressCaptureParams["selection"] | undefined;
    }
  | undefined {
  const selected = selectedMarker(cfg, accountId);
  if (!selected) {
    return undefined;
  }
  requireSelection(canonicalAccount(accountId));
  const root = record(cfg);
  const channels = record(root.channels);
  const channel = record(channels.sms);
  const accounts = channel.accounts === undefined ? {} : record(channel.accounts);
  const ownAccount = Object.hasOwn(accounts, accountId) ? record(accounts[accountId]) : undefined;
  requireSelection(
    accountId === "default"
      ? ownAccount !== undefined ||
          [
            channel.accountSid,
            channel.authToken,
            channel.fromNumber,
            channel.messagingServiceSid,
          ].some(hasConfiguredAccountValue)
      : ownAccount !== undefined,
  );
  requireSelection(
    !Object.keys(accounts).some(
      (key) => key !== accountId && key.trim().toLowerCase() === accountId,
    ),
  );
  requireSelection(channel.enabled === undefined || channel.enabled === true);
  requireSelection(ownAccount?.enabled === undefined || ownAccount.enabled === true);
  const merged = resolveMergedAccountConfig({
    channelConfig: channel,
    accounts: ownAccount === undefined ? undefined : { [accountId]: ownAccount },
    accountId,
    channelId: "sms",
    omitKeys: ["defaultAccount"],
  });
  requireSelection(
    merged.dangerouslyDisableSignatureValidation === undefined ||
      merged.dangerouslyDisableSignatureValidation === false,
  );
  const account = record(accountValue);
  const ingress = record(selected.marker.smsIngress);
  requireSelection(
    account.accountId === accountId &&
      account.accountSid === ingress.accountSid &&
      account.enabled === true &&
      account.dangerouslyDisableSignatureValidation === false,
  );
  requireSelection(typeof account.authToken === "string" && account.authToken.trim().length > 0);
  requireSelection(
    typeof merged.accountSid === "string" && merged.accountSid === ingress.accountSid,
  );
  const credential = resolveSecretInputString({
    value: merged.authToken,
    path: "channels.sms.authToken",
  });
  requireSelection(credential.status === "available" && credential.value === account.authToken);
  const binding = selectedBinding(cfg, accountId, selected.id);
  // Projection only: validation stays with the existing marker/account selection above.
  // Missing capture-only fields do not alter the historical lifetime controller.
  const selection: CreateOpsysSmsIngressCaptureParams["selection"] | undefined =
    capturePublicSelection &&
    typeof account.fromNumber === "string" &&
    account.fromNumber.length > 0 &&
    typeof account.publicWebhookUrl === "string" &&
    account.publicWebhookUrl.length > 0 &&
    typeof ingress.accountSid === "string" &&
    typeof selected.marker.profileId === "string" &&
    typeof selected.marker.profileRevision === "number"
      ? Object.freeze({
          accountId,
          accountSid: ingress.accountSid,
          fromNumber: account.fromNumber,
          publicWebhookUrl: account.publicWebhookUrl,
          permission: Object.freeze({
            profil_id: selected.marker.profileId,
            revision_profil: selected.marker.profileRevision,
            outil_m1: "opsys_m1__m1_recevoir_message_canal",
          }),
        })
      : undefined;
  return {
    fingerprint: snapshot({ selected, binding, channelEnabled: channel.enabled, merged, account }),
    selection,
  };
}

/** Host-only lifetime controller. Owner callbacks are trusted process seams, not plugin/RPC input. */
export function createOpsysSmsHostAuthority(
  params: CreateOpsysSmsHostAuthorityParams,
): OpsysSmsHostAuthority | undefined {
  if (params.channelId !== "sms") {
    return undefined;
  }
  try {
    const initial = selectionSnapshot(params.cfg, params.accountId, params.account, true);
    if (initial === undefined) {
      return undefined;
    }
    const { plugin, pluginId, origin, captureReadAuthority } = params.registration;
    requireSelection(
      plugin.id === "sms" &&
        pluginId === "sms" &&
        origin === "bundled" &&
        typeof captureReadAuthority === "function",
    );
    const grant = captureReadAuthority();
    requireSelection(typeof grant === "function" && grant());
    let published = false;
    let revoked = false;
    let releaseLease: (() => void) | undefined;
    const revoke = () => {
      if (revoked) {
        return;
      }
      revoked = true;
      published = false;
      params.abortSignal.removeEventListener("abort", revoke);
      const release = releaseLease;
      releaseLease = undefined;
      release?.();
    };
    const ownerCurrent = () => {
      const current = params.getCurrentRegistration();
      return (
        !params.abortSignal.aborted &&
        params.capabilityLease.isActive() &&
        params.isCurrentLifetime() &&
        current?.plugin === plugin &&
        current.pluginId === pluginId &&
        current.origin === origin &&
        current.captureReadAuthority === captureReadAuthority &&
        grant() &&
        selectionSnapshot(params.getRuntimeConfig(), params.accountId, params.account)
          ?.fingerprint === initial.fingerprint
      );
    };
    requireSelection(ownerCurrent());
    params.abortSignal.addEventListener("abort", revoke, { once: true });
    releaseLease = params.capabilityLease.retain(revoke);
    const isCurrent = () => {
      if (revoked || !published) {
        return false;
      }
      try {
        if (ownerCurrent() && params.isCurrentTask()) {
          return true;
        }
      } catch {
        // No raw config/credential/callback error crosses the private controller.
      }
      revoke();
      return false;
    };
    const publish = () => {
      if (revoked) {
        return false;
      }
      try {
        if (ownerCurrent() && params.isCurrentTask()) {
          published = true;
          return true;
        }
      } catch {
        // Failed publication cannot be adopted as legacy or a later regrant.
      }
      revoke();
      return false;
    };
    const captureSelection = () => {
      requireSelection(isCurrent() && initial.selection !== undefined);
      return initial.selection;
    };
    return Object.freeze({ publish, isCurrent, revoke, captureSelection });
  } catch {
    throw new Error(OPSYS_SMS_HOST_SELECTION_REFUSED);
  }
}
