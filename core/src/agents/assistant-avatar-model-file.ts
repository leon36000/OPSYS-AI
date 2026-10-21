import { createHash } from "node:crypto";
import {
  ASSISTANT_AVATAR_MODELS,
  type AssistantAvatarModelId,
} from "../shared/assistant-avatar-model-catalog.js";

const MAX_MODEL_BYTES = 10 * 1024 * 1024;
const MAX_JSON_BYTES = 2 * 1024 * 1024;

function hasForbiddenResourceReference(value: unknown): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  if (Array.isArray(value)) {
    return value.some(hasForbiddenResourceReference);
  }
  return Object.entries(value).some(([key, child]) => {
    if (key === "uri" || key.toLowerCase().startsWith("extension")) {
      return true;
    }
    return hasForbiddenResourceReference(child);
  });
}

/** Validate only the pinned, embedded-buffer GLB profile shipped with the Core. */
export function validateAssistantAvatarModelBytes(
  modelId: AssistantAvatarModelId,
  bytes: Buffer,
): boolean {
  const descriptor = ASSISTANT_AVATAR_MODELS[modelId];
  if (
    bytes.length !== descriptor.bytes ||
    bytes.length > MAX_MODEL_BYTES ||
    createHash("sha256").update(bytes).digest("hex") !== descriptor.sha256 ||
    bytes.toString("ascii", 0, 4) !== "glTF" ||
    bytes.readUInt32LE(4) !== 2 ||
    bytes.readUInt32LE(8) !== bytes.length
  ) {
    return false;
  }
  const jsonLength = bytes.readUInt32LE(12);
  const jsonType = bytes.readUInt32LE(16);
  const binHeaderOffset = 20 + jsonLength;
  if (
    jsonLength > MAX_JSON_BYTES ||
    jsonType !== 0x4e4f534a ||
    binHeaderOffset + 8 > bytes.length ||
    bytes.readUInt32LE(binHeaderOffset + 4) !== 0x004e4942 ||
    binHeaderOffset + 8 + bytes.readUInt32LE(binHeaderOffset) !== bytes.length
  ) {
    return false;
  }
  let document: unknown;
  try {
    document = JSON.parse(bytes.toString("utf8", 20, binHeaderOffset));
  } catch {
    return false;
  }
  if (!document || typeof document !== "object" || hasForbiddenResourceReference(document)) {
    return false;
  }
  const gltf = document as Record<string, unknown>;
  const arrays = [gltf.nodes, gltf.meshes, gltf.accessors, gltf.bufferViews, gltf.animations];
  if (
    gltf.asset === null ||
    typeof gltf.asset !== "object" ||
    (gltf.asset as Record<string, unknown>).version !== "2.0" ||
    arrays.some((entry) => !Array.isArray(entry)) ||
    (gltf.nodes as unknown[]).length > 128 ||
    (gltf.meshes as unknown[]).length > 32 ||
    (gltf.accessors as unknown[]).length > 512 ||
    (gltf.bufferViews as unknown[]).length > 512 ||
    (gltf.animations as unknown[]).length > 64 ||
    (Array.isArray(gltf.materials) && gltf.materials.length > 64) ||
    (Array.isArray(gltf.skins) && gltf.skins.length > 8) ||
    (gltf.materials !== undefined && !Array.isArray(gltf.materials)) ||
    (gltf.skins !== undefined && !Array.isArray(gltf.skins)) ||
    gltf.images !== undefined ||
    gltf.textures !== undefined ||
    !Array.isArray(gltf.buffers) ||
    gltf.buffers.length !== 1 ||
    typeof (gltf.buffers[0] as Record<string, unknown>)?.byteLength !== "number"
  ) {
    return false;
  }
  const binLength = bytes.readUInt32LE(binHeaderOffset);
  const declaredBinLength = (gltf.buffers[0] as { byteLength: number }).byteLength;
  if (
    !Number.isSafeInteger(declaredBinLength) ||
    declaredBinLength < 0 ||
    declaredBinLength > binLength ||
    binLength - declaredBinLength > 3
  ) {
    return false;
  }
  for (const view of gltf.bufferViews as Array<Record<string, unknown>>) {
    if (!view || typeof view !== "object") {
      return false;
    }
    const offset = view.byteOffset === undefined ? 0 : view.byteOffset;
    const length = view.byteLength;
    if (
      view.buffer !== 0 ||
      typeof offset !== "number" ||
      !Number.isSafeInteger(offset) ||
      offset < 0 ||
      typeof length !== "number" ||
      !Number.isSafeInteger(length) ||
      length < 0 ||
      offset + length > declaredBinLength
    ) {
      return false;
    }
  }
  for (const accessor of gltf.accessors as Array<Record<string, unknown>>) {
    if (
      !accessor ||
      typeof accessor !== "object" ||
      typeof accessor.count !== "number" ||
      !Number.isSafeInteger(accessor.count) ||
      accessor.count < 0 ||
      accessor.count > 100_000
    ) {
      return false;
    }
  }
  let primitiveCount = 0;
  let positionVertexCount = 0;
  for (const mesh of gltf.meshes as Array<Record<string, unknown>>) {
    if (!mesh || typeof mesh !== "object" || !Array.isArray(mesh.primitives)) {
      return false;
    }
    for (const primitive of mesh.primitives as Array<Record<string, unknown>>) {
      primitiveCount += 1;
      if (!primitive || typeof primitive !== "object") {
        return false;
      }
      const attributes = primitive.attributes;
      if (!attributes || typeof attributes !== "object" || Array.isArray(attributes)) {
        return false;
      }
      const positionAccessor = (attributes as Record<string, unknown>).POSITION;
      if (
        typeof positionAccessor !== "number" ||
        !Number.isSafeInteger(positionAccessor) ||
        positionAccessor < 0 ||
        positionAccessor >= (gltf.accessors as unknown[]).length
      ) {
        return false;
      }
      const accessor = (gltf.accessors as Array<{ count: number }>)[positionAccessor];
      if (!accessor) {
        return false;
      }
      positionVertexCount += accessor.count;
      if (primitiveCount > 64 || positionVertexCount > 250_000) {
        return false;
      }
    }
  }
  return true;
}
