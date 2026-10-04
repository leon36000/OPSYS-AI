import { Value } from "typebox/value";
import { describe, expect, it } from "vitest";
import { TalkCatalogResultSchema, TalkSessionCloseParamsSchema } from "./channels.js";

function catalogWithActiveVoicePolicy(activeVoiceSelectionPolicy: unknown) {
  return {
    modes: ["realtime"],
    transports: ["gateway-relay"],
    brains: ["agent-consult"],
    speech: { providers: [] },
    transcription: { providers: [] },
    realtime: {
      providers: [
        {
          id: "realtime",
          label: "Realtime",
          configured: true,
          voices: ["provider-voice"],
          activeVoices: ["active-voice"],
          activeVoiceSelectionPolicy,
        },
      ],
    },
  };
}

describe("TalkCatalogResultSchema", () => {
  it("accepts only the authoritative voice allowlist policy", () => {
    expect(
      Value.Check(TalkCatalogResultSchema, catalogWithActiveVoicePolicy("allowlist-default")),
    ).toBe(true);
    expect(Value.Check(TalkCatalogResultSchema, catalogWithActiveVoicePolicy("free-form"))).toBe(
      false,
    );
  });
});

describe("TalkSessionCloseParamsSchema", () => {
  it("accepts an optional strict discardAudio intent", () => {
    expect(Value.Check(TalkSessionCloseParamsSchema, { sessionId: "s1" })).toBe(true);
    expect(
      Value.Check(TalkSessionCloseParamsSchema, { sessionId: "s1", discardAudio: false }),
    ).toBe(true);
    expect(Value.Check(TalkSessionCloseParamsSchema, { sessionId: "s1", discardAudio: true })).toBe(
      true,
    );
    expect(
      Value.Check(TalkSessionCloseParamsSchema, { sessionId: "s1", discardAudio: "true" }),
    ).toBe(false);
    expect(Value.Check(TalkSessionCloseParamsSchema, { sessionId: "s1", extra: true })).toBe(false);
  });
});
