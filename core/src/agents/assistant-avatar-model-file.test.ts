import fs from "node:fs";
import { describe, expect, it } from "vitest";
import { validateAssistantAvatarModelBytes } from "./assistant-avatar-model-file.js";

const MODEL_ID = "robotexpressive-quaternius-cc0-v1";
const MODEL_PATH = new URL(
  "../../assets/avatar-models/robotexpressive-quaternius-cc0-v1.glb",
  import.meta.url,
);
const HUMAN_MODEL_ID = "mpfb-human-cc0-v1";
const HUMAN_MODEL_PATH = new URL(
  "../../assets/avatar-models/mpfb-human-cc0-v1.glb",
  import.meta.url,
);

describe("pinned assistant avatar model", () => {
  it("accepts only the pinned embedded-buffer GLB bytes", () => {
    const bytes = fs.readFileSync(MODEL_PATH);
    expect(validateAssistantAvatarModelBytes(MODEL_ID, bytes)).toBe(true);
    const changed = Buffer.from(bytes);
    changed[0] = 0;
    expect(validateAssistantAvatarModelBytes(MODEL_ID, changed)).toBe(false);
    expect(validateAssistantAvatarModelBytes(MODEL_ID, bytes.subarray(0, 64))).toBe(false);
  });

  it("accepts the complete pinned MPFB candidate and rejects altered, truncated, or other-model bytes", () => {
    const bytes = fs.readFileSync(HUMAN_MODEL_PATH);
    expect(validateAssistantAvatarModelBytes(HUMAN_MODEL_ID, bytes)).toBe(true);

    const altered = Buffer.from(bytes);
    const lastByteIndex = altered.length - 1;
    altered[lastByteIndex] = altered[lastByteIndex]! ^ 0xff;
    expect(validateAssistantAvatarModelBytes(HUMAN_MODEL_ID, altered)).toBe(false);
    expect(validateAssistantAvatarModelBytes(HUMAN_MODEL_ID, bytes.subarray(0, -1))).toBe(false);

    const robotBytes = fs.readFileSync(MODEL_PATH);
    expect(validateAssistantAvatarModelBytes(HUMAN_MODEL_ID, robotBytes)).toBe(false);
  });
});
