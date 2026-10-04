import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  applyCuratedFrCaImport,
  CURATED_KEYS,
  CURATED_SOURCE_PATH,
  parseCuratedArgs,
  planCuratedFrCaImport,
} from "../../scripts/control-ui-i18n-curated.ts";
import {
  hashControlUiTranslationText,
  loadControlUiTranslationMemory,
  materializeControlUiLocaleCatalog,
} from "../../scripts/lib/control-ui-i18n-catalog-values.ts";
import {
  createControlUiLocaleSyncPlan,
  flattenTranslations,
} from "../../scripts/lib/control-ui-i18n-sync-plan.ts";

const sourceFlat = new Map([
  [CURATED_KEYS[0], "Agent unavailable"],
  [CURATED_KEYS[1], "Agent status is unavailable. Reconnect and try again."],
  ["legacy.title", "Preserved title"],
  ["unrelated.missing", "Another new message"],
]);
const translations = [
  "Agent indisponible",
  "Impossible de vérifier l’état de cet agent. Reconnectez-vous et réessayez.",
];
const oldRecord = {
  cache_key: "legacy-key",
  segment_id: "legacy.title",
  source_path: "legacy.ts",
  src_lang: "en",
  text: "Preserved title",
  text_hash: hashControlUiTranslationText("Preserved title"),
  tgt_lang: "fr-CA",
  translated: "Titre conservé",
  updated_at: "2026-01-01T00:00:00.000Z",
};
// Deliberate whitespace/legacy fields: a canonical rewrite would break this prefix.
const memoryText = ` ${JSON.stringify({ ...oldRecord, model: "legacy-private-fixture" })} \n\n`;
const metaText = `${JSON.stringify({ fallbackKeys: [], generatedAt: "2026-01-01T00:00:00.000Z", locale: "fr-CA", sourceHash: "old", totalKeys: 1, translatedKeys: 1, workflow: 1 }, null, 2)}\n`;
const created: string[] = [];
afterEach(() => {
  for (const directory of created.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});
function curated() {
  return {
    workflow: 1,
    provider: "curated-local",
    sourceLocale: "en",
    locale: "fr-CA",
    entries: CURATED_KEYS.map((key, index) => ({
      key,
      text_hash: hashControlUiTranslationText(sourceFlat.get(key)!),
      translated: translations[index],
    })),
  };
}
function plan(overrides: Partial<Parameters<typeof planCuratedFrCaImport>[0]> = {}) {
  return planCuratedFrCaImport({
    curated: curated(),
    sourceFlat,
    sourceHash: "current-source",
    memoryText,
    metaText,
    generatedAt: "2026-10-02T00:00:00.000Z",
    ...overrides,
  });
}
function fixture() {
  const directory = mkdtempSync(path.join(tmpdir(), "control-ui-curated-"));
  created.push(directory);
  const memoryPath = path.join(directory, "fr-CA.tm.jsonl");
  const metaPath = path.join(directory, "fr-CA.meta.json");
  writeFileSync(memoryPath, memoryText);
  writeFileSync(metaPath, metaText);
  return { directory, memoryPath, metaPath, evidenceDir: path.join(directory, "evidence") };
}

describe("curated fr-CA import", () => {
  it("appends exactly two generated records while preserving every legacy byte", () => {
    const value = plan();
    const prefix = Buffer.from(memoryText);
    expect(Buffer.from(value.nextMemory).subarray(0, prefix.length)).toEqual(prefix);
    const appended = value.nextMemory
      .slice(memoryText.length)
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(value.addedRecords).toBe(2);
    expect(appended).toHaveLength(2);
    expect(appended.map((item) => item.segment_id).toSorted()).toEqual(
      [...CURATED_KEYS].toSorted(),
    );
    expect(
      appended.every(
        (item) =>
          item.provider === "curated-local" &&
          item.source_path === CURATED_SOURCE_PATH &&
          !("model" in item),
      ),
    ).toBe(true);
    expect(appended.map((item) => item.cache_key)).toEqual(
      appended.map((item) => item.cache_key).toSorted(),
    );
    expect(value.fallbackKeys).toEqual(["unrelated.missing"]);
    expect(JSON.parse(value.nextMeta)).toMatchObject({
      totalKeys: 4,
      translatedKeys: 3,
      fallbackKeys: ["unrelated.missing"],
    });
  });

  it("uses the same official loader/materializer as the virtual locale and is idempotent", () => {
    const files = fixture();
    const value = plan();
    writeFileSync(files.memoryPath, value.nextMemory);
    const materialized = flattenTranslations(
      materializeControlUiLocaleCatalog(
        sourceFlat,
        loadControlUiTranslationMemory(files.memoryPath),
      ),
    );
    expect(materialized.get(CURATED_KEYS[0])).toBe(translations[0]);
    expect(materialized.get(CURATED_KEYS[1])).toBe(translations[1]);
    expect(materialized.get("legacy.title")).toBe("Titre conservé");
    expect(materialized.has("unrelated.missing")).toBe(false);
    const repeated = plan({
      memoryText: value.nextMemory,
      metaText: value.nextMeta,
      generatedAt: "2026-10-03T00:00:00.000Z",
    });
    expect(repeated.addedRecords).toBe(0);
    expect(repeated.nextMemory).toBe(value.nextMemory);
    expect(repeated.nextMeta).toBe(value.nextMeta);
  });

  it("preserves unrelated declared fallbacks even when a memory record exists", () => {
    const value = plan({
      metaText: JSON.stringify({ ...JSON.parse(metaText), fallbackKeys: ["legacy.title"] }),
    });
    expect(value.fallbackKeys).toEqual(["legacy.title", "unrelated.missing"]);
  });

  it("rejects outdated source hashes without echoing message values", () => {
    const value = curated();
    value.entries[0]!.text_hash = "0".repeat(64);
    expect(() => plan({ curated: value })).toThrow("source text hash");
    expect(() =>
      plan({ sourceFlat: new Map([...sourceFlat, [CURATED_KEYS[0], "Changed English"]]) }),
    ).toThrow("source text hash");
  });

  it.each([
    "duplicate",
    "unknown",
    "missing",
    "extra field",
    "model",
    "empty",
    "template",
    "wrong locale",
  ])("refuses %s curated input", (reason) => {
    const value = curated();
    if (reason === "duplicate") {
      value.entries[1] = value.entries[0]!;
    }
    if (reason === "unknown") {
      value.entries[0]!.key = "unrelated.missing" as (typeof CURATED_KEYS)[number];
    }
    if (reason === "missing") {
      value.entries.pop();
    }
    if (reason === "extra field") {
      Object.assign(value.entries[0]!, { source_path: "https://private.invalid" });
    }
    if (reason === "model") {
      Object.assign(value, { model: "invented-model" });
    }
    if (reason === "empty") {
      value.entries[0]!.translated = "";
    }
    if (reason === "template") {
      value.entries[0]!.translated = "{secret}";
    }
    if (reason === "wrong locale") {
      value.locale = "fr";
    }
    expect(() => plan({ curated: value })).toThrow();
  });

  it("refuses malformed memory, duplicate cache keys and a missing final newline", () => {
    expect(() => plan({ memoryText: "not json\n" })).toThrow();
    expect(() => plan({ memoryText: memoryText + memoryText })).toThrow("duplicate");
    expect(() => plan({ memoryText: memoryText.trimEnd() })).toThrow("newline");
    expect(() => plan({ metaText: "{}" })).toThrow("metadata");
  });

  it("rejects conflicting current translations instead of silently overriding them", () => {
    const conflict = {
      ...oldRecord,
      cache_key: "conflict",
      segment_id: CURATED_KEYS[0],
      text_hash: hashControlUiTranslationText(sourceFlat.get(CURATED_KEYS[0])!),
      translated: "Autre traduction",
    };
    expect(() => plan({ memoryText: memoryText + JSON.stringify(conflict) + "\n" })).toThrow(
      "conflicting",
    );
  });

  it("preserves curated provenance in subsequent canonical generation without exposing legacy model fields", () => {
    const files = fixture();
    writeFileSync(files.memoryPath, plan().nextMemory);
    const memory = loadControlUiTranslationMemory(files.memoryPath);
    const next = createControlUiLocaleSyncPlan({
      allowTranslate: false,
      cacheKeyFor: (key, hash) => `${key}:${hash}`,
      entry: { locale: "fr-CA", exportName: "fr_CA", fileName: "fr-CA.ts", languageKey: "fr_CA" },
      existingFlat: flattenTranslations(materializeControlUiLocaleCatalog(sourceFlat, memory)),
      force: false,
      hashText: hashControlUiTranslationText,
      previousMeta: null,
      sourceFlat,
      sourceHash: "source",
      translationMemory: memory,
    });
    const rendered = next.render({
      defaultGlossary: [],
      glossary: [],
      generatedAt: "2026-10-03T00:00:00.000Z",
      workflow: 1,
    });
    const records = rendered.translationMemory
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(records.filter((item) => item.provider === "curated-local")).toHaveLength(2);
    expect(rendered.translationMemory).not.toContain("legacy-private-fixture");
  });

  it("defaults to check and requires explicit write plus a local evidence path", () => {
    expect(parseCuratedArgs([])).toEqual({ write: false });
    expect(parseCuratedArgs(["--check"])).toEqual({ write: false });
    expect(parseCuratedArgs(["--write", "--evidence-dir", "/tmp/proof"])).toEqual({
      write: true,
      evidenceDir: "/tmp/proof",
    });
  });

  it.each([
    ["--write"],
    ["--write", "--check"],
    ["--check", "--check"],
    ["--input", "/tmp/other"],
    ["--write", "--evidence-dir", "relative"],
    ["--evidence-dir", "/tmp/proof"],
    ["--write", "--evidence-dir", "/tmp/a", "--evidence-dir", "/tmp/b"],
    ["--write", "--evidence-dir", "--check"],
  ])("refuses unsupported CLI arguments %j", (...args) => {
    expect(() => parseCuratedArgs(args)).toThrow();
  });

  it("creates durable preimages and verifies exact applied hashes", () => {
    const files = fixture();
    const value = plan();
    const receipt = applyCuratedFrCaImport({ plan: value, ...files });
    expect(receipt.status).toBe("applied");
    expect(readFileSync(path.join(files.evidenceDir, "fr-CA.tm.jsonl.before"), "utf8")).toBe(
      memoryText,
    );
    expect(readFileSync(path.join(files.evidenceDir, "fr-CA.meta.json.before"), "utf8")).toBe(
      metaText,
    );
    expect(readFileSync(files.memoryPath, "utf8")).toBe(value.nextMemory);
    expect(readFileSync(files.metaPath, "utf8")).toBe(value.nextMeta);
    const observed = receipt.observed as { name: string; sha256: string }[];
    expect(observed.find((item) => item.name === "fr-CA.tm.jsonl")!.sha256).toBe(
      createHash("sha256").update(value.nextMemory).digest("hex"),
    );
    expect(readdirSync(files.directory).some((name) => name.endsWith(".tmp"))).toBe(false);
  });

  it("rolls the memory back if the metadata rename fails and retains a failure receipt", () => {
    const files = fixture();
    let calls = 0;
    expect(() =>
      applyCuratedFrCaImport({ plan: plan(), ...files }, (from, to) => {
        if (++calls === 2) {
          throw new Error("fake metadata rename failure");
        }
        renameSync(from, to);
      }),
    ).toThrow("failed-rolled-back");
    expect(calls).toBe(3);
    expect(readFileSync(files.memoryPath, "utf8")).toBe(memoryText);
    expect(readFileSync(files.metaPath, "utf8")).toBe(metaText);
    expect(
      JSON.parse(readFileSync(path.join(files.evidenceDir, "result.json"), "utf8")).status,
    ).toBe("failed-rolled-back");
    expect(readdirSync(files.directory).some((name) => name.endsWith(".tmp"))).toBe(false);
  });

  it("refuses a changed input or a symlink before writing product output", () => {
    const files = fixture();
    writeFileSync(files.metaPath, "changed");
    expect(() => applyCuratedFrCaImport({ plan: plan(), ...files })).toThrow("changed");
    expect(readFileSync(files.memoryPath, "utf8")).toBe(memoryText);
    writeFileSync(files.metaPath, metaText);
    rmSync(files.memoryPath);
    symlinkSync(files.metaPath, files.memoryPath);
    expect(() => applyCuratedFrCaImport({ plan: plan(), ...files })).toThrow("regular local files");
  });

  it("rolls both outputs back if the success receipt cannot be written", () => {
    const files = fixture();
    let calls = 0;
    expect(() =>
      applyCuratedFrCaImport({ plan: plan(), ...files }, (from, to) => {
        renameSync(from, to);
        if (++calls === 2) {
          mkdirSync(path.join(files.evidenceDir, "result.json"));
        }
      }),
    ).toThrow("failed-rolled-back; final receipt unavailable");
    expect(readFileSync(files.memoryPath, "utf8")).toBe(memoryText);
    expect(readFileSync(files.metaPath, "utf8")).toBe(metaText);
    expect(readFileSync(path.join(files.evidenceDir, "fr-CA.tm.jsonl.before"), "utf8")).toBe(
      memoryText,
    );
    expect(
      JSON.parse(readFileSync(path.join(files.evidenceDir, "prepared.json"), "utf8")).status,
    ).toBe("prepared");
  });

  it("does not overwrite an independent writer when rollback cannot be completed", () => {
    const files = fixture();
    let calls = 0;
    expect(() =>
      applyCuratedFrCaImport({ plan: plan(), ...files }, (from, to) => {
        renameSync(from, to);
        if (++calls === 2) {
          writeFileSync(files.memoryPath, "independent writer\n");
        }
      }),
    ).toThrow("failed-rollback-incomplete");
    expect(readFileSync(files.memoryPath, "utf8")).toBe("independent writer\n");
    expect(readFileSync(files.metaPath, "utf8")).toBe(metaText);
    expect(readFileSync(path.join(files.evidenceDir, "fr-CA.tm.jsonl.before"), "utf8")).toBe(
      memoryText,
    );
  });
});
