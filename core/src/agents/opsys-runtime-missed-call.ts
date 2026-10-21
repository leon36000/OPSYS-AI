import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import type { PluginRuntimeCapabilityLease } from "../plugins/capability-lease.js";
import type {
  HostMissedCallImportInputV1,
  HostMissedCallImportResultV1,
  HostMissedCallProviderV1,
} from "../plugins/plugin-registration.types.js";

type ToolCall = (params: {
  config: OpenClawConfig | undefined;
  server: string;
  tool: string;
  args: Record<string, unknown>;
  timeoutMs: number;
  signal: AbortSignal;
}) => Promise<unknown>;

const TIMEOUT_MS = 8_000;
const PROVIDERS = new Set<HostMissedCallProviderV1>(["mock", "twilio", "telnyx", "plivo"]);
const PROFILE_ID = /^[a-z][a-z0-9-]{1,63}$/u;
const PHONE = /^\+[1-9]\d{6,14}$/u;
const CONTROL_CHARS = /\p{Cc}/u;

function isBoundedOpaqueId(value: unknown, maxLength: number): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= maxLength &&
    value.trim() === value &&
    !CONTROL_CHARS.test(value)
  );
}

/** Creates one fixed, lease-bound host operation for a bundled voice-call service. */
export function createHostMissedCallImporterV1(params: {
  config: OpenClawConfig;
  getCurrentConfig: () => OpenClawConfig;
  isServiceScopeCurrent: () => boolean;
  isStopping: () => boolean;
  signal: AbortSignal;
  agentId: string;
  lease: PluginRuntimeCapabilityLease;
  callTool?: ToolCall;
}): (input: HostMissedCallImportInputV1) => Promise<HostMissedCallImportResultV1> {
  const match = /^opsys-agent-([a-z][a-z0-9-]{1,63})$/u.exec(params.agentId);
  const profileId = match?.[1];
  const binding = params.config.agents?.entries?.[params.agentId]?.opsysRuntimeAdmission;
  if (
    !profileId ||
    !PROFILE_ID.test(profileId) ||
    !binding ||
    binding.profileId !== profileId ||
    typeof binding.profileRevision !== "number" ||
    !Number.isSafeInteger(binding.profileRevision) ||
    binding.profileRevision < 1
  ) {
    throw new Error("OPSYS missed-call import refused: valid runtime profile binding required");
  }
  const server = `opsys_runtime_${profileId}`;
  const revision = binding.profileRevision;

  const assertCurrent = (config: OpenClawConfig) => {
    params.lease.assertActive("OPSYS missed-call importer");
    if (params.signal.aborted || params.isStopping()) {
      throw new Error("OPSYS missed-call import refused: service is stopping");
    }
    if (!params.isServiceScopeCurrent()) {
      throw new Error("OPSYS missed-call import refused: captured service scope changed");
    }
    const liveBinding = config.agents?.entries?.[params.agentId]?.opsysRuntimeAdmission;
    if (
      !liveBinding ||
      liveBinding.profileId !== profileId ||
      liveBinding.profileRevision !== revision ||
      !config.mcp?.servers?.[server]
    ) {
      throw new Error("OPSYS missed-call import refused: live profile binding changed");
    }
  };

  // Validate startup binding too, so an opt-in service cannot start with a stale target.
  assertCurrent(params.getCurrentConfig());
  return async (input) => {
    // Copy all callback scalars before any await; retained/mutated plugin objects have no authority.
    const snapshot = Object.freeze({
      provider: input.provider,
      eventId: input.eventId,
      callId: input.callId,
      startedAt: input.startedAt,
      from: input.from,
      terminal: input.terminal,
    });
    if (
      !PROVIDERS.has(snapshot.provider) ||
      !isBoundedOpaqueId(snapshot.eventId, 200) ||
      !isBoundedOpaqueId(snapshot.callId, 200) ||
      (snapshot.terminal !== "no-answer" && snapshot.terminal !== "busy") ||
      !PHONE.test(snapshot.from) ||
      !isBoundedOpaqueId(snapshot.startedAt, 40) ||
      !Number.isFinite(Date.parse(snapshot.startedAt)) ||
      new Date(snapshot.startedAt).toISOString() !== snapshot.startedAt
    ) {
      throw new Error("OPSYS missed-call import refused: invalid versioned input");
    }

    let requestConfig = params.getCurrentConfig();
    assertCurrent(requestConfig);
    params.signal.throwIfAborted();
    const args = Object.freeze({
      provider: snapshot.provider,
      event_id: snapshot.eventId,
      call_id: snapshot.callId,
      occurred_at: snapshot.startedAt,
      telephone: snapshot.from,
      revision_profil: revision,
    });

    const deadline = new AbortController();
    const timer = setTimeout(
      () => deadline.abort(new Error("OPSYS missed-call import deadline exceeded")),
      TIMEOUT_MS,
    );
    const signal = AbortSignal.any([params.signal, deadline.signal]);
    try {
      let callTool = params.callTool;
      if (!callTool) {
        callTool = (await import("../context-engine/opsys-contexte-mcp.js")).callOpsysMcpTool;
      }
      requestConfig = params.getCurrentConfig();
      assertCurrent(requestConfig);
      signal.throwIfAborted();
      const value = await callTool({
        config: requestConfig,
        server,
        tool: "opsys_runtime_importer_appel_manque",
        args,
        timeoutMs: TIMEOUT_MS,
        signal,
      });
      assertCurrent(params.getCurrentConfig());
      signal.throwIfAborted();
      const ack = isRecord(value) ? value : undefined;
      if (
        ack?.ok !== true ||
        ack.source !== `voice-call:${snapshot.provider}` ||
        ack.call_id !== snapshot.callId ||
        ack.status !== "manque" ||
        Object.keys(ack).length !== 4
      ) {
        throw new Error("OPSYS missed-call import refused: backend acknowledgement mismatch");
      }
      return Object.freeze({
        ok: true,
        source: `voice-call:${snapshot.provider}`,
        call_id: snapshot.callId,
        status: "manque",
      });
    } finally {
      clearTimeout(timer);
    }
  };
}
