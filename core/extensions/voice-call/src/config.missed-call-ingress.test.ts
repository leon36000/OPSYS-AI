import { describe, expect, it } from "vitest";
import {
  VOICE_CALL_SERVICE_RELOAD_CONFIG_PREFIXES,
  VoiceCallConfigSchema,
  validateProviderConfig,
} from "./config.js";

describe("voice-call missed-call ingress config", () => {
  it("defaults off and accepts an explicit opt-in", () => {
    expect(VoiceCallConfigSchema.parse({}).missedCallIngress).toBe(false);
    expect(VoiceCallConfigSchema.parse({ missedCallIngress: true }).missedCallIngress).toBe(true);
  });

  it("reloads for the full agent subtree, including default-owner changes", () => {
    expect(VOICE_CALL_SERVICE_RELOAD_CONFIG_PREFIXES).toEqual([
      "plugins.entries.voice-call",
      "agents",
      "mcp.servers",
    ]);
  });

  it("rejects non-boolean opt-in values", () => {
    expect(() => VoiceCallConfigSchema.parse({ missedCallIngress: "yes" })).toThrow();
  });
});

it("rejects ingress when signature verification is skipped", () => {
  const config = VoiceCallConfigSchema.parse({
    enabled: true,
    missedCallIngress: true,
    provider: "twilio",
    skipSignatureVerification: true,
  });
  const result = validateProviderConfig(config);
  expect(result.valid).toBe(false);
  expect(result.errors).toContain(
    "plugins.entries.voice-call.config.missedCallIngress requires an authenticated non-mock provider webhook",
  );
});

it("rejects ingress on the unauthenticated mock provider", () => {
  const config = VoiceCallConfigSchema.parse({
    enabled: true,
    missedCallIngress: true,
    provider: "mock",
    skipSignatureVerification: false,
  });
  const result = validateProviderConfig(config);
  expect(result.valid).toBe(false);
  expect(result.errors).toContain(
    "plugins.entries.voice-call.config.missedCallIngress requires an authenticated non-mock provider webhook",
  );
});
