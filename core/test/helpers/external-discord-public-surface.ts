import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import { resolveOpenProviderRuntimeGroupPolicy } from "../../src/config/runtime-group-policy.js";

// Test data provenance only; this helper creates neither H nor a permission grant.
const manifestHash = "0d99cbe880004784fd38a89215495fa5a024198a47b70e71f8424d655145d746";
const apiHash = "40802a34729051f399b51c44cbeffdcf7e7552a8fea12aa3babfa8c47e23536f";
const inventoryRowsHash = "d71332d1e058a6884fd31a1d1478d33272e1ad63043fba103dea46a10833dcfa";
let validatedFixture: string | undefined;
const surfaceHashes: Readonly<Record<string, string>> = {
  "api.js": apiHash,
  "runtime-api.js": "f35b1687dc2b04c933f6f1ab4fbba7e1bcf901ed9d1f2b5f39cc1b0b23643a40",
};

function verifyPhysicalFile(filename: string, expectedHash: string) {
  if (!fs.lstatSync(filename).isFile()) {
    throw new Error("HARNESS_BLOCKED: Discord fixture file is not physical.");
  }
  const data = fs.readFileSync(filename);
  if (createHash("sha256").update(data).digest("hex") !== expectedHash) {
    throw new Error("HARNESS_BLOCKED: Discord fixture bytes differ from the pinned package.");
  }
  return data;
}

function fixtureRoot() {
  const configured = process.env.OPENCLAW_TEST_DISCORD_PLUGIN_ROOT;
  if (!configured || !path.isAbsolute(configured)) {
    throw new Error("HARNESS_BLOCKED: pinned Discord fixture root is required.");
  }
  const root = fs.realpathSync(configured);
  if (root !== path.normalize(configured) || root.split(path.sep).includes("node_modules")) {
    throw new Error("HARNESS_BLOCKED: Discord fixture must be physical and outside node_modules.");
  }
  const inventoryPath = process.env.OPENCLAW_TEST_DISCORD_PLUGIN_INVENTORY;
  if (!inventoryPath || !path.isAbsolute(inventoryPath)) {
    throw new Error("HARNESS_BLOCKED: pinned Discord fixture inventory is required.");
  }
  const inventory: unknown = JSON.parse(fs.readFileSync(inventoryPath, "utf8"));
  if (
    !isRecord(inventory) ||
    inventory.root !== root ||
    inventory.count !== 6013 ||
    !isRecord(inventory.files)
  ) {
    throw new Error("HARNESS_BLOCKED: Discord fixture inventory identity differs.");
  }
  const entries = Object.entries(inventory.files).toSorted(([a], [b]) =>
    a < b ? -1 : a > b ? 1 : 0,
  );
  const rows = entries.map(([name, row]) => {
    if (
      !isRecord(row) ||
      typeof row.sha256 !== "string" ||
      typeof row.size !== "number" ||
      typeof row.mode !== "number"
    ) {
      throw new Error("HARNESS_BLOCKED: malformed Discord fixture inventory.");
    }
    return [name, row.sha256, row.size, row.mode];
  });
  const rowsHash = createHash("sha256").update(JSON.stringify(rows)).digest("hex");
  if (entries.length !== 6013 || rowsHash !== inventoryRowsHash) {
    throw new Error("HARNESS_BLOCKED: Discord fixture inventory is not the pinned archive.");
  }
  const key = JSON.stringify([root, inventoryPath, rowsHash]);
  if (validatedFixture !== key) {
    for (const [name, row] of entries) {
      if (!isRecord(row) || typeof row.sha256 !== "string") {
        throw new Error("HARNESS_BLOCKED: malformed Discord fixture file entry.");
      }
      const filename = path.join(root, name);
      const relative = path.relative(root, filename);
      if (
        !relative ||
        relative.startsWith(`..${path.sep}`) ||
        path.isAbsolute(relative) ||
        fs.realpathSync(filename) !== filename
      ) {
        throw new Error("HARNESS_BLOCKED: Discord fixture file escapes its physical root.");
      }
      const info = fs.lstatSync(filename);
      if (info.size !== row.size || (info.mode & 0o777) !== row.mode) {
        throw new Error("HARNESS_BLOCKED: Discord fixture file size/mode differs.");
      }
      verifyPhysicalFile(filename, row.sha256);
    }
    // The canonical Root wrapper also pins all 6013 files/links before and after the phase.
    validatedFixture = key;
  }
  const metadata: unknown = JSON.parse(
    verifyPhysicalFile(path.join(root, "package.json"), manifestHash).toString("utf8"),
  );
  if (
    !isRecord(metadata) ||
    metadata.name !== "@openclaw/discord" ||
    metadata.version !== "2026.9.6"
  ) {
    throw new Error("HARNESS_BLOCKED: Discord fixture package identity is unavailable.");
  }
  return root;
}

type ExternalDiscordPublicSurfaceLoader = <T extends object>(params: {
  artifactBasename: string;
}) => Promise<T>;

/** Use the canonical Vitest evaluator, whose SDK aliases retain current Core Source. */
export const loadExternalDiscordPublicSurface: ExternalDiscordPublicSurfaceLoader = async (
  params,
) => {
  const expectedHash = surfaceHashes[params.artifactBasename];
  if (!expectedHash) {
    throw new Error("HARNESS_BLOCKED: unsupported Discord fixture surface.");
  }
  const root = fixtureRoot();
  const apiPath = path.join(root, "dist", "api.js");
  verifyPhysicalFile(apiPath, apiHash);
  // This is an actual package re-export of openclaw/plugin-sdk/runtime-group-policy.
  const api = await import(pathToFileURL(apiPath).href);
  if (api.resolveDiscordRuntimeGroupPolicy !== resolveOpenProviderRuntimeGroupPolicy) {
    throw new Error("HARNESS_BLOCKED: Discord SDK public surface uses a foreign Core realm.");
  }
  const modulePath = path.join(root, "dist", params.artifactBasename);
  verifyPhysicalFile(modulePath, expectedHash);
  // No jiti/native require, new alias, mocked facade, or post-import ownership registration.
  return import(pathToFileURL(modulePath).href);
};
