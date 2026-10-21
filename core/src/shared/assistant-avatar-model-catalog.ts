/** Operator-selected 3D avatar models shipped privately with the Gateway. */
export const ASSISTANT_AVATAR_MODELS = {
  "robotexpressive-quaternius-cc0-v1": {
    assetPath: "assets/avatar-models/robotexpressive-quaternius-cc0-v1.glb",
    bytes: 463_988,
    sha256: "047f5e5fb3bb6d378bd1df16ca6137f2a596c99b3a1b5690b4020c05aaf6f319",
    license: "CC0-1.0",
  },
  "mpfb-human-cc0-v1": {
    assetPath: "assets/avatar-models/mpfb-human-cc0-v1.glb",
    bytes: 6_600_124,
    sha256: "47d377b91d9872e439cbcc363b20630bcf68cda057218683aa0565372509b4df",
    license: "CC0-1.0",
  },
} as const;

export type AssistantAvatarModelId = keyof typeof ASSISTANT_AVATAR_MODELS;

export function isAssistantAvatarModelId(value: unknown): value is AssistantAvatarModelId {
  return typeof value === "string" && Object.hasOwn(ASSISTANT_AVATAR_MODELS, value);
}
