# @openclaw/voice-call

Official Voice Call plugin for **OpenClaw**.

Providers:

- **Twilio** (Programmable Voice + Media Streams)
- **Telnyx** (Call Control v2)
- **Plivo** (Voice API + XML transfer + GetInput speech)
- **Mock** (dev/no network)

Docs: `https://docs.openclaw.ai/plugins/voice-call`
Plugin system: `https://docs.openclaw.ai/tools/plugin`

## Install

```bash
openclaw plugins install @openclaw/voice-call
```

Restart the Gateway afterwards.

## Local dev install

```bash
PLUGIN_HOME=~/.openclaw/extensions
mkdir -p "$PLUGIN_HOME"
cp -R <local-plugin-checkout> "$PLUGIN_HOME/voice-call"
cd "$PLUGIN_HOME/voice-call" && pnpm install
```

## Config

Put under `plugins.entries.voice-call.config`:

```json5
{
  provider: "twilio", // or "telnyx" | "plivo" | "mock"
  fromNumber: "+15550001234",
  toNumber: "+15550005678",
  sessionScope: "per-phone", // or "per-call" | "main"
  missedCallIngress: false, // opt in only with an admitted OPSYS profile

  twilio: {
    accountSid: "ACxxxxxxxx",
    authToken: "your_token",
  },

  telnyx: {
    apiKey: "KEYxxxx",
    connectionId: "CONNxxxx",
    // Telnyx webhook public key from the Telnyx Mission Control Portal
    // (Base64 string; can also be set via TELNYX_PUBLIC_KEY).
    publicKey: "...",
  },

  plivo: {
    authId: "MAxxxxxxxxxxxxxxxxxxxx",
    authToken: "your_token",
  },

  // Webhook server
  serve: {
    port: 3334,
    path: "/voice/webhook",
  },

  // Public exposure (pick one):
  // publicUrl: "https://example.ngrok.app/voice/webhook",
  // tunnel: { provider: "ngrok" },
  // tailscale: { mode: "funnel", port: 8443, path: "/voice/webhook" }

  outbound: {
    defaultMode: "notify", // or "conversation"
  },

  // Optional response agent workspace. Defaults to "main".
  agentId: "main",

  streaming: {
    enabled: true,
    // optional; if omitted, Voice Call picks the first registered
    // realtime-transcription provider by autoSelectOrder
    provider: "<realtime-transcription-provider-id>",
    streamPath: "/voice/stream",
    providers: {
      "<realtime-transcription-provider-id>": {
        // provider-owned options
      },
    },
    preStartTimeoutMs: 5000,
    maxPendingConnections: 32,
    maxPendingConnectionsPerIp: 4,
    maxConnections: 128,
  },
}
```

Notes:

- `missedCallIngress` defaults to `false`. When enabled, only verified inbound `no-answer` and `busy` events with a persisted call record are imported through the host-bound `opsys_runtime_<profileId>` route. The service requires a valid admitted profile and fails closed if the host capability is unavailable.
- Twilio/Telnyx/Plivo require a **publicly reachable** webhook URL.
- `tailscale.port` defaults to `443` and owns the external HTTPS port for both legacy `tailscale.mode` and unified Tailscale tunnel providers. Funnel supports `443`, `8443`, or `10000`; Serve accepts any valid TCP port.
- Twilio defaults to US1. For a non-US Region, set `twilio.region` to `ie1` or `au1` and use credentials created in that Region; see [Twilio's regional REST API guide](https://www.twilio.com/docs/global-infrastructure/using-the-twilio-rest-api-in-a-non-us-region).
- `mock` is a local dev provider (no network calls).
- Telnyx requires `telnyx.publicKey` (or `TELNYX_PUBLIC_KEY`) unless `skipSignatureVerification` is true.
- Runtime accepts canonical config only. If older configs still use `provider: "log"`, `twilio.from`, or legacy `streaming.*` OpenAI keys, run `openclaw doctor --fix` to rewrite them.
- advanced webhook, streaming, and tunnel notes: `https://docs.openclaw.ai/plugins/voice-call`
- `responseModel` is optional. When unset, voice responses use the runtime default model.
- `sessionScope` defaults to `per-phone`, preserving caller memory across calls. Use `per-call` for reception, booking, IVR, and bridge flows where each carrier call should start fresh. Use `main` to share the configured agent's main session (`agent:<agentId>:main`, or `global` when core `session.scope` is `"global"`). Custom core `session.mainKey` values are ignored.
- `realtime.consultThinkingLevel` is optional. When set, it overrides the thinking level used by the model behind realtime `openclaw_agent_consult` calls.
- `realtime.consultFastMode` is optional. When set, it toggles fast mode for realtime `openclaw_agent_consult` calls.

## Stale call reaper

See the plugin docs for recommended ranges and production examples:
`https://docs.openclaw.ai/plugins/voice-call#stale-call-reaper`

## TTS for calls

Voice Call uses the core `tts` configuration for
streaming speech on calls. Override examples and provider caveats live here:
`https://docs.openclaw.ai/plugins/voice-call#tts-for-calls`

## CLI

```bash
openclaw voicecall call --to "+15555550123" --message "Hello from OpenClaw"
openclaw voicecall continue --call-id <id> --message "Any questions?"
openclaw voicecall speak --call-id <id> --message "One moment"
openclaw voicecall end --call-id <id>
openclaw voicecall status --json
openclaw voicecall status --call-id <id>
openclaw voicecall tail
openclaw voicecall expose --mode funnel
```

## Tool

Tool name: `voice_call`

Actions:

- `initiate_call` (message, to?, mode?)
- `continue_call` (callId, message)
- `speak_to_user` (callId, message)
- `end_call` (callId)
- `get_status` (callId)

## Gateway RPC

- `voicecall.initiate` (to?, message, mode?)
- `voicecall.continue` (callId, message)
- `voicecall.speak` (callId, message)
- `voicecall.end` (callId)
- `voicecall.status` (callId)

## Notes

- Uses webhook signature verification for Twilio/Telnyx/Plivo.
- Adds replay protection for Twilio and Plivo webhooks (valid duplicate callbacks are ignored safely).
- Twilio speech turns include a per-turn token so stale/replayed callbacks cannot complete a newer turn.
- `responseModel` / `responseSystemPrompt` control AI auto-responses.
- Voice-call auto-responses enforce a spoken JSON contract (`{"spoken":"..."}`) and filter reasoning/meta output before playback.
- While a Twilio stream is active, playback does not fall back to TwiML `<Say>`; stream-TTS failures fail the playback request.
- Outbound conversation calls suppress barge-in only while the initial greeting is actively speaking, then re-enable normal interruption.
- Twilio stream disconnect auto-end uses a short grace window so quick reconnects do not end the call.
- Realtime provider selection is generic. Configure `streaming.provider` / `realtime.provider` and put provider-owned options under `providers.<id>`.

## OPSYS missed-call host contract (V1)

`HostMissedCallImportInputV1`, `HostMissedCallImportResultV1`, and
`HostMissedCallImporterV1` are exported as types by the existing
`openclaw/plugin-sdk/core` and `openclaw/plugin-sdk/plugin-entry` subpaths.
The service descriptor opts in with `hostMissedCallIngress: { version: 1, agentId }`.
The optional context field preserves source compatibility for other services; when
ingress is enabled, this plugin requires a host capability for the effective agent
and refuses startup if that capability is absent or targets a different agent.

The host grants this fixed operation only to the bundled `voice-call` plugin's
`voicecall` service. A workspace plugin does not obtain it by copying the descriptor.
It is a private OPSYS operation, absent from agent tool catalogues, and cannot
select an arbitrary profile, MCP server, or tool. The admitted profile, revision,
service lease, and committed configuration scope are checked before and after
awaited work. Stop or reload aborts pending imports immediately, before asynchronous
service cleanup finishes; retained capability copies are also revoked.

Production ingress requires a verified Twilio, Telnyx, or Plivo webhook. Keep
`skipSignatureVerification` false; the mock provider is rejected for public ingress
because its verifier is not an authentication boundary. The constructed provider
must match the configured provider. The host validates a known inbound call that
was never answered and ended with `no-answer` or `busy`, then uses the verified
event key and stored start time. This Core verification is the trust boundary:
the private Python port does not independently authenticate carrier webhooks.

Only `{ ok, source, call_id, status }` is accepted as the backend acknowledgement.
It must arrive before manager processing and the provider HTTP acknowledgement.
Failure releases the existing webhook replay reservation for redelivery; the
backend's durable idempotence prevents a second human follow-up. This is not a
claim of exactly-once delivery across processes. No LLM or outgoing communication
is needed by this import operation.

A plugin configuration reload recreates its descriptor. A service-only reload
that changes the effective default agent can retain an old descriptor: startup
fails closed on the target mismatch, and the Gateway's existing recovery restart
re-registers the plugin. This recovery path still needs integration qualification.
Tests may mock the private MCP transport or provider verifier; those tests do not
qualify a carrier signature, a real phone call, or a production deployment.
