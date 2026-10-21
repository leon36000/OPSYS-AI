import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  hashControlUiTranslationText,
  materializeControlUiLocaleCatalog,
} from "./lib/control-ui-i18n-catalog-values.ts";
import {
  compareStringArrays,
  createControlUiLocaleSyncPlan,
  flattenTranslations,
  type LocaleMeta,
  type TranslationMemoryEntry,
} from "./lib/control-ui-i18n-sync-plan.ts";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const CURATED_SOURCE_PATH = "ui/src/i18n/curated/fr-CA.r47.json";
export const CURATED_KEYS = [
  "chat.sessionRoute.agentUnavailable",
  "chat.sessionRoute.agentRosterUnavailable",
] as const;
const MEMORY_PATH = "ui/src/i18n/.i18n/fr-CA.tm.jsonl";
const META_PATH = "ui/src/i18n/.i18n/fr-CA.meta.json";

type CuratedEntry = { key: string; text_hash: string; translated: string };
export type CuratedPlan = {
  addedRecords: number;
  beforeMemory: string;
  beforeMeta: string;
  nextMemory: string;
  nextMeta: string;
  fallbackKeys: string[];
  sourceHash: string;
};

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return compareStringArrays(Object.keys(value).toSorted(), keys.toSorted());
}

function parseCuratedEntries(value: unknown, source: ReadonlyMap<string, string>): CuratedEntry[] {
  if (
    !isObject(value) ||
    !hasExactKeys(value, ["workflow", "provider", "sourceLocale", "locale", "entries"]) ||
    value.workflow !== 1 ||
    value.provider !== "curated-local" ||
    value.sourceLocale !== "en" ||
    value.locale !== "fr-CA" ||
    !Array.isArray(value.entries) ||
    value.entries.length !== CURATED_KEYS.length
  ) {
    throw new Error("invalid curated fr-CA document");
  }
  const found = new Set<string>();
  const entries: CuratedEntry[] = [];
  for (const item of value.entries) {
    if (
      !isObject(item) ||
      !hasExactKeys(item, ["key", "text_hash", "translated"]) ||
      typeof item.key !== "string" ||
      !CURATED_KEYS.some((key) => key === item.key) ||
      found.has(item.key) ||
      typeof item.text_hash !== "string" ||
      !/^[a-f0-9]{64}$/.test(item.text_hash) ||
      typeof item.translated !== "string" ||
      item.translated !== item.translated.trim() ||
      item.translated.length === 0
    ) {
      throw new Error("invalid or duplicate curated target");
    }
    const text = source.get(item.key);
    if (text === undefined || hashControlUiTranslationText(text) !== item.text_hash) {
      throw new Error("curated source text hash does not match the current catalogue");
    }
    // These two source messages have no interpolation tokens. The reviewed
    // translations must not introduce template syntax or control characters.
    const hasControlCharacter = [...item.translated].some((character) => {
      const code = character.charCodeAt(0);
      return code < 0x20 || code === 0x7f;
    });
    if (/[{}]/.test(item.translated) || hasControlCharacter) {
      throw new Error("invalid curated message syntax");
    }
    found.add(item.key);
    entries.push({ key: item.key, text_hash: item.text_hash, translated: item.translated });
  }
  return entries.toSorted((left, right) => left.key.localeCompare(right.key));
}

function parseMemory(text: string): Map<string, TranslationMemoryEntry> {
  if (text && !text.endsWith("\n")) {
    throw new Error("translation memory must end with a newline; refusing legacy rewrite");
  }
  const memory = new Map<string, TranslationMemoryEntry>();
  for (const line of text.split("\n")) {
    if (!line.trim()) {
      continue;
    }
    const value: unknown = JSON.parse(line);
    if (
      !isObject(value) ||
      ![
        "cache_key",
        "segment_id",
        "source_path",
        "src_lang",
        "text",
        "text_hash",
        "tgt_lang",
        "translated",
        "updated_at",
      ].every((key) => typeof value[key] === "string") ||
      !value.cache_key ||
      !(value.translated as string).trim() ||
      (value.segment_ids !== undefined &&
        (!Array.isArray(value.segment_ids) ||
          !value.segment_ids.every((key) => typeof key === "string"))) ||
      memory.has(value.cache_key as string)
    ) {
      throw new Error("invalid or duplicate translation memory record");
    }
    memory.set(value.cache_key as string, value as unknown as TranslationMemoryEntry);
  }
  return memory;
}

function parseMeta(text: string): LocaleMeta {
  const value: unknown = JSON.parse(text);
  if (
    !isObject(value) ||
    value.locale !== "fr-CA" ||
    value.workflow !== 1 ||
    typeof value.generatedAt !== "string" ||
    typeof value.sourceHash !== "string" ||
    !Number.isInteger(value.totalKeys) ||
    !Number.isInteger(value.translatedKeys) ||
    !Array.isArray(value.fallbackKeys) ||
    !value.fallbackKeys.every((key) => typeof key === "string")
  ) {
    throw new Error("invalid fr-CA metadata");
  }
  return value as unknown as LocaleMeta;
}

export function planCuratedFrCaImport(input: {
  curated: unknown;
  sourceFlat: ReadonlyMap<string, string>;
  sourceHash: string;
  memoryText: string;
  metaText: string;
  generatedAt: string;
}): CuratedPlan {
  const selected = parseCuratedEntries(input.curated, input.sourceFlat);
  const memory = parseMemory(input.memoryText);
  const previousMeta = parseMeta(input.metaText);
  const existingFlat = flattenTranslations(
    materializeControlUiLocaleCatalog(input.sourceFlat, memory),
  );
  const missing = selected.filter((item) => {
    const existing = existingFlat.get(item.key);
    if (existing !== undefined && existing !== item.translated) {
      throw new Error("curated target already has a conflicting current translation");
    }
    return existing === undefined;
  });
  const selectedSource = new Map(
    missing.map((item) => [item.key, input.sourceFlat.get(item.key)!]),
  );
  const plan = createControlUiLocaleSyncPlan({
    allowTranslate: true,
    cacheKeyFor: (key, hash) =>
      sha256(["wf=1|engine=curated-local", "en", "fr-CA", key, hash].join("|")),
    entry: { exportName: "fr_CA", fileName: "fr-CA.ts", languageKey: "fr_CA", locale: "fr-CA" },
    existingFlat: new Map(),
    force: false,
    hashText: hashControlUiTranslationText,
    previousMeta: null,
    sourceFlat: selectedSource,
    sourceHash: input.sourceHash,
    translationMemory: new Map(),
  });
  plan.recordTranslations(
    plan.pending,
    new Map(missing.map((item) => [item.key, item.translated])),
    {
      sourceLocale: "en",
      sourcePath: CURATED_SOURCE_PATH,
      provider: "curated-local",
      updatedAt: () => input.generatedAt,
    },
  );
  const rendered = plan.render({
    defaultGlossary: [],
    glossary: [],
    generatedAt: input.generatedAt,
    workflow: 1,
  });
  const appended = parseMemory(rendered.translationMemory);
  if (appended.size !== missing.length) {
    throw new Error("curated generator did not produce the exact selected records");
  }
  for (const [key, record] of appended) {
    if (memory.has(key)) {
      throw new Error("curated cache key collides with legacy memory");
    }
    memory.set(key, record);
  }
  const nextMemory = input.memoryText + rendered.translationMemory;
  const materialized = flattenTranslations(
    materializeControlUiLocaleCatalog(input.sourceFlat, memory),
  );
  const fallbackKeys = [
    ...new Set([
      ...[...input.sourceFlat.keys()].filter((key) => !materialized.has(key)),
      ...previousMeta.fallbackKeys.filter(
        (key) => input.sourceFlat.has(key) && !CURATED_KEYS.some((target) => target === key),
      ),
    ]),
  ].toSorted((left, right) => left.localeCompare(right));
  const translatedKeys = input.sourceFlat.size - fallbackKeys.length;
  const changed =
    previousMeta.sourceHash !== input.sourceHash ||
    previousMeta.totalKeys !== input.sourceFlat.size ||
    previousMeta.translatedKeys !== translatedKeys ||
    !compareStringArrays(previousMeta.fallbackKeys, fallbackKeys);
  const meta: LocaleMeta = {
    fallbackKeys,
    generatedAt: changed ? input.generatedAt : previousMeta.generatedAt,
    locale: "fr-CA",
    sourceHash: input.sourceHash,
    totalKeys: input.sourceFlat.size,
    translatedKeys,
    workflow: 1,
  };
  return {
    addedRecords: appended.size,
    beforeMemory: input.memoryText,
    beforeMeta: input.metaText,
    nextMemory,
    nextMeta: `${JSON.stringify(meta, null, 2)}\n`,
    fallbackKeys,
    sourceHash: input.sourceHash,
  };
}

export function parseCuratedArgs(args: string[]): { write: boolean; evidenceDir?: string } {
  let mode: "check" | "write" | undefined;
  let evidenceDir: string | undefined;
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if ((arg === "--check" || arg === "--write") && mode === undefined) {
      mode = arg === "--write" ? "write" : "check";
    } else if (arg === "--evidence-dir" && evidenceDir === undefined) {
      const value = args[++index];
      if (!value || value.startsWith("--") || !path.isAbsolute(value)) {
        throw new Error("--evidence-dir requires an absolute local path");
      }
      evidenceDir = path.resolve(value);
    } else {
      throw new Error("unsupported or repeated curated import argument");
    }
  }
  if (mode === "write" ? !evidenceDir : evidenceDir !== undefined) {
    throw new Error("--write requires --evidence-dir; --check never writes evidence");
  }
  return { write: mode === "write", ...(evidenceDir ? { evidenceDir } : {}) };
}

function assertRegularLocalFile(file: string): void {
  if (!lstatSync(file).isFile() || realpathSync(file) !== path.resolve(file)) {
    throw new Error("curated import requires regular local files without symlinks");
  }
}

function readLocalUtf8(file: string): string {
  assertRegularLocalFile(file);
  const bytes = readFileSync(file);
  const text = bytes.toString("utf8");
  if (!bytes.equals(Buffer.from(text, "utf8"))) {
    throw new Error("curated import requires lossless UTF-8 input");
  }
  return text;
}

function writeDurableExclusive(file: string, text: string, mode: number): void {
  const fd = openSync(file, "wx", mode);
  try {
    writeFileSync(fd, text, "utf8");
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

function syncDirectory(directory: string): void {
  const fd = openSync(directory, "r");
  try {
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

export function applyCuratedFrCaImport(
  input: {
    plan: CuratedPlan;
    memoryPath: string;
    metaPath: string;
    evidenceDir: string;
  },
  replaceFile: typeof renameSync = renameSync,
): Record<string, unknown> {
  const { plan } = input;
  const outputs = [
    {
      file: input.memoryPath,
      before: plan.beforeMemory,
      after: plan.nextMemory,
      name: "fr-CA.tm.jsonl",
    },
    {
      file: input.metaPath,
      before: plan.beforeMeta,
      after: plan.nextMeta,
      name: "fr-CA.meta.json",
    },
  ];
  for (const output of outputs) {
    assertRegularLocalFile(output.file);
    if (readLocalUtf8(output.file) !== output.before) {
      throw new Error("curated input changed before application");
    }
  }
  if (!plan.nextMemory.startsWith(plan.beforeMemory)) {
    throw new Error("curated application must preserve the complete legacy prefix");
  }
  const evidenceDir = path.resolve(input.evidenceDir);
  if (
    existsSync(evidenceDir) ||
    realpathSync(path.dirname(evidenceDir)) !== path.dirname(evidenceDir)
  ) {
    throw new Error("evidence directory must be new and have a regular local parent");
  }
  mkdirSync(evidenceDir, { mode: 0o700 });
  syncDirectory(path.dirname(evidenceDir));
  const receipt: Record<string, unknown> = {
    provider: "curated-local",
    sourcePath: CURATED_SOURCE_PATH,
    sourceHash: plan.sourceHash,
    addedRecords: plan.addedRecords,
    legacyPrefixBytes: Buffer.byteLength(plan.beforeMemory),
    fallbackKeys: plan.fallbackKeys,
    outputs: outputs.map((output) => ({
      name: output.name,
      beforeSha256: sha256(output.before),
      afterSha256: sha256(output.after),
    })),
    status: "prepared",
  };
  for (const output of outputs) {
    writeDurableExclusive(path.join(evidenceDir, `${output.name}.before`), output.before, 0o600);
  }
  writeDurableExclusive(
    path.join(evidenceDir, "prepared.json"),
    `${JSON.stringify(receipt, null, 2)}\n`,
    0o600,
  );
  syncDirectory(evidenceDir);
  const prepared: {
    file: string;
    before: string;
    after: string;
    temp: string;
    replaced: boolean;
    mode: number;
  }[] = [];
  const observe = () =>
    outputs.map((output) => {
      try {
        return { name: output.name, sha256: sha256(readLocalUtf8(output.file)) };
      } catch {
        return { name: output.name, status: "unreadable-or-unsafe" };
      }
    });
  const persistReceipt = () => {
    const temp = path.join(evidenceDir, `result-${randomUUID()}.tmp`);
    try {
      writeDurableExclusive(temp, `${JSON.stringify(receipt, null, 2)}\n`, 0o600);
      renameSync(temp, path.join(evidenceDir, "result.json"));
      syncDirectory(evidenceDir);
    } finally {
      if (existsSync(temp)) {
        unlinkSync(temp);
      }
    }
  };
  let failure = false;
  let receiptFailed = false;
  try {
    for (const output of outputs) {
      const temp = `${output.file}.curated-${randomUUID()}.tmp`;
      const item = { ...output, temp, replaced: false, mode: lstatSync(output.file).mode & 0o777 };
      prepared.push(item);
      writeDurableExclusive(temp, output.after, item.mode);
    }
    for (const item of prepared) {
      assertRegularLocalFile(item.file);
      if (readLocalUtf8(item.file) !== item.before) {
        throw new Error("curated input changed during application");
      }
      replaceFile(item.temp, item.file);
      item.replaced = true;
      syncDirectory(path.dirname(item.file));
      if (readLocalUtf8(item.file) !== item.after) {
        throw new Error("curated applied hash mismatch");
      }
    }
    receipt.status = "applied";
    const observed = observe();
    if (observed.some((item, index) => item.sha256 !== sha256(outputs[index]!.after))) {
      throw new Error("curated final output hash mismatch");
    }
    receipt.observed = observed;
    // A durable success receipt is part of the application contract: failure
    // here also rolls the two outputs back while the preimages already exist.
    persistReceipt();
  } catch {
    failure = true;
    let rollbackFailed = false;
    for (const item of prepared.toReversed()) {
      if (!item.replaced) {
        continue;
      }
      try {
        // Do not clobber a concurrent writer while rolling back our own update.
        assertRegularLocalFile(item.file);
        if (readLocalUtf8(item.file) !== item.after) {
          throw new Error("concurrent output change");
        }
        writeDurableExclusive(item.temp, item.before, item.mode);
        replaceFile(item.temp, item.file);
        syncDirectory(path.dirname(item.file));
        if (readLocalUtf8(item.file) !== item.before) {
          throw new Error("rollback hash mismatch");
        }
      } catch {
        rollbackFailed = true;
      }
    }
    receipt.status = rollbackFailed ? "failed-rollback-incomplete" : "failed-rolled-back";
    receipt.observed = observe();
    try {
      persistReceipt();
    } catch {
      receiptFailed = true;
    }
  } finally {
    for (const item of prepared) {
      try {
        if (existsSync(item.temp)) {
          unlinkSync(item.temp);
        }
      } catch {
        failure = true;
      }
    }
  }
  if (failure) {
    throw new Error(
      `curated application ${receipt.status}${receiptFailed ? "; final receipt unavailable" : ""}; preimages and prepared hashes retained`,
    );
  }
  return receipt;
}

async function main(): Promise<void> {
  const args = parseCuratedArgs(process.argv.slice(2));
  const sourcePath = path.join(ROOT, CURATED_SOURCE_PATH);
  const memoryPath = path.join(ROOT, MEMORY_PATH);
  const metaPath = path.join(ROOT, META_PATH);
  for (const file of [sourcePath, memoryPath, metaPath]) {
    assertRegularLocalFile(file);
  }
  const { loadControlUiSourceCatalog, readControlUiSourceCatalog } =
    await import("./lib/control-ui-i18n-catalog.ts");
  const sourceHash = sha256(await readControlUiSourceCatalog());
  const curatedText = readLocalUtf8(sourcePath);
  const plan = planCuratedFrCaImport({
    curated: JSON.parse(curatedText),
    sourceFlat: flattenTranslations(loadControlUiSourceCatalog()),
    sourceHash,
    memoryText: readLocalUtf8(memoryPath),
    metaText: readLocalUtf8(metaPath),
    generatedAt: new Date().toISOString(),
  });
  if (args.write) {
    if (
      sha256(await readControlUiSourceCatalog()) !== sourceHash ||
      readLocalUtf8(sourcePath) !== curatedText
    ) {
      throw new Error("source catalogue changed before application");
    }
    const relativeEvidence = path.relative(ROOT, args.evidenceDir!);
    if (
      !relativeEvidence.startsWith(`..${path.sep}`) &&
      relativeEvidence !== ".." &&
      !path.isAbsolute(relativeEvidence)
    ) {
      throw new Error("curated evidence must be stored outside the source tree");
    }
    console.log(
      JSON.stringify(
        applyCuratedFrCaImport({ plan, memoryPath, metaPath, evidenceDir: args.evidenceDir! }),
      ),
    );
    return;
  }
  console.log(
    JSON.stringify({
      mode: "check",
      provider: "curated-local",
      addedRecords: plan.addedRecords,
      legacyPrefixBytes: Buffer.byteLength(plan.beforeMemory),
      beforeMemorySha256: sha256(plan.beforeMemory),
      afterMemorySha256: sha256(plan.nextMemory),
      metadataChanged: plan.beforeMeta !== plan.nextMeta,
      remainingFallbackKeys: plan.fallbackKeys,
    }),
  );
}

const entrypoint = process.argv[1];
if (entrypoint && import.meta.url === pathToFileURL(path.resolve(entrypoint)).href) {
  main().catch(() => {
    // Input records and paths are not echoed: diagnostics never disclose a
    // legacy provider/model field or arbitrary malformed document content.
    console.error(
      "Curated fr-CA import refused; check arguments, source hashes and retained local evidence.",
    );
    process.exitCode = 1;
  });
}
