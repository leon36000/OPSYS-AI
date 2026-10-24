// Publishes only the prepared Python runtime of an already initialized OPSYS profile.
// No Python process, schema migration, arbitrary command, new lock or service management.
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { isRecord, isStringRecord } from "@openclaw/normalization-core/record-coerce";
import {
  OPSYS_MCP_TOKEN_ENV,
  OPSYS_METIER_CONFIG_FILENAME,
  resolveOpsysDir,
} from "../gateway/opsys-metier-config.js";
import { withGatewayRuntimeArtifactPublication } from "./update-cli/update-command-service-publication.js";

type Snapshot = { bytes: Buffer; stat: fs.Stats };
type PreparedGeneration = {
  softwareRoot: string;
  candidate: string;
  source: string;
  python: string;
  manifest: string;
  snapshot: Snapshot;
  directories: Array<{ path: string; stat: fs.Stats }>;
  pythonLink: fs.Stats;
  pythonReal: string;
  pythonTarget: fs.Stats;
};

function refuse(): never {
  throw new Error("Prepared generation or initialized instance contract refused.");
}

function physicalDirectory(input: string): string {
  if (!path.isAbsolute(input)) {
    refuse();
  }
  const normalized = path.resolve(input);
  if (fs.realpathSync(normalized) !== normalized || !fs.statSync(normalized).isDirectory()) {
    refuse();
  }
  return normalized;
}

function readSnapshot(file: string, maximum: number, readonly = false): Snapshot {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const stat = fs.fstatSync(fd);
    if (
      !stat.isFile() ||
      stat.nlink !== 1 ||
      stat.size > maximum ||
      (process.getuid && stat.uid !== process.getuid()) ||
      (readonly && (stat.mode & 0o222) !== 0)
    ) {
      refuse();
    }
    const buffer = Buffer.alloc(maximum + 1);
    const read = fs.readSync(fd, buffer, 0, buffer.length, 0);
    const after = fs.fstatSync(fd);
    if (
      read !== stat.size ||
      after.size !== stat.size ||
      after.mtimeMs !== stat.mtimeMs ||
      after.ctimeMs !== stat.ctimeMs ||
      read > maximum
    ) {
      refuse();
    }
    return { bytes: buffer.subarray(0, read), stat };
  } finally {
    fs.closeSync(fd);
  }
}

function sameSnapshot(before: Snapshot, current: Snapshot): boolean {
  return (
    before.stat.dev === current.stat.dev &&
    before.stat.ino === current.stat.ino &&
    before.stat.mode === current.stat.mode &&
    before.stat.uid === current.stat.uid &&
    before.stat.mtimeMs === current.stat.mtimeMs &&
    before.stat.ctimeMs === current.stat.ctimeMs &&
    before.bytes.equals(current.bytes)
  );
}

function preparedGeneration(args: readonly string[]): PreparedGeneration {
  const values = new Map<string, string>();
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    const value = args[index + 1];
    if ((flag !== "--generation" && flag !== "--logiciel") || !value || values.has(flag)) {
      refuse();
    }
    values.set(flag, value);
  }
  const softwareInput = values.get("--logiciel");
  const candidateInput = values.get("--generation");
  if (!softwareInput || !candidateInput) {
    refuse();
  }
  const softwareRoot = physicalDirectory(softwareInput);
  const candidate = physicalDirectory(candidateInput);
  const generations = physicalDirectory(path.join(softwareRoot, "generations"));
  // Exactly one declared generation below this software root; no root or alias publication.
  if (path.dirname(candidate) !== generations) {
    refuse();
  }
  const manifest = path.join(candidate, "generation.json");
  const snapshot = readSnapshot(manifest, 65536, true);
  const raw: unknown = JSON.parse(snapshot.bytes.toString("utf8"));
  if (
    !isRecord(raw) ||
    raw.state !== "prepared" ||
    raw.publication !== "not-published" ||
    raw.generation !== candidate ||
    typeof raw.source !== "string" ||
    typeof raw.venv !== "string" ||
    typeof raw.python !== "string" ||
    raw.source !== path.join(candidate, "source") ||
    raw.venv !== path.join(candidate, "venv") ||
    typeof raw.commit !== "string" ||
    !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u.test(raw.commit)
  ) {
    refuse();
  }
  const source = physicalDirectory(raw.source);
  const venv = physicalDirectory(raw.venv);
  const plain = path.join(candidate, "venv", "bin", "python");
  const sqlite = path.join(candidate, "runtime", "sqlite-privee", "python");
  if (raw.python !== plain && raw.python !== sqlite) {
    refuse();
  }
  // A system interpreter symlink remains an explicit dependency of the prepared venv.
  // The private SQLite wrapper itself must stay physically inside this generation.
  if (raw.python === sqlite) {
    physicalDirectory(path.dirname(sqlite));
    if (fs.lstatSync(sqlite).isSymbolicLink() || fs.realpathSync(sqlite) !== sqlite) {
      refuse();
    }
  }
  if (!fs.statSync(raw.python).isFile()) {
    refuse();
  }
  fs.accessSync(raw.python, fs.constants.X_OK);
  return {
    softwareRoot,
    candidate,
    source,
    python: raw.python,
    manifest,
    snapshot,
    directories: [softwareRoot, generations, candidate, source, venv, path.dirname(raw.python)].map(
      (directory) => ({ path: physicalDirectory(directory), stat: fs.statSync(directory) }),
    ),
    pythonLink: fs.lstatSync(raw.python),
    pythonReal: fs.realpathSync(raw.python),
    pythonTarget: fs.statSync(raw.python),
  };
}

function currentGeneration(generation: PreparedGeneration): void {
  for (const directory of generation.directories) {
    sameDirectory(directory.path, directory.stat);
  }
  const link = fs.lstatSync(generation.python);
  const target = fs.statSync(generation.python);
  if (
    link.dev !== generation.pythonLink.dev ||
    link.ino !== generation.pythonLink.ino ||
    link.mode !== generation.pythonLink.mode ||
    link.uid !== generation.pythonLink.uid ||
    fs.realpathSync(generation.python) !== generation.pythonReal ||
    target.dev !== generation.pythonTarget.dev ||
    target.ino !== generation.pythonTarget.ino ||
    target.mode !== generation.pythonTarget.mode ||
    target.uid !== generation.pythonTarget.uid ||
    target.size !== generation.pythonTarget.size ||
    target.mtimeMs !== generation.pythonTarget.mtimeMs ||
    target.ctimeMs !== generation.pythonTarget.ctimeMs
  ) {
    refuse();
  }
  if (!sameSnapshot(generation.snapshot, readSnapshot(generation.manifest, 65536, true))) {
    refuse();
  }
}

function runtimeConfig(bytes: Buffer, generation: PreparedGeneration): Buffer {
  const raw: unknown = JSON.parse(bytes.toString("utf8"));
  if (
    !isRecord(raw) ||
    typeof raw.actif !== "boolean" ||
    typeof raw.dossier !== "string" ||
    !path.isAbsolute(raw.dossier) ||
    (raw.env !== undefined && !isStringRecord(raw.env))
  ) {
    refuse();
  }
  if (isRecord(raw.env) && Object.hasOwn(raw.env, OPSYS_MCP_TOKEN_ENV)) {
    refuse();
  }
  const server = raw.commande;
  const cli = raw.commande_cli;
  if (
    !Array.isArray(server) ||
    !Array.isArray(cli) ||
    !server.every((part): part is string => typeof part === "string" && part.length > 0) ||
    !cli.every((part): part is string => typeof part === "string" && part.length > 0) ||
    server.length < 3 ||
    cli.length !== 3 ||
    !path.isAbsolute(server[0]!) ||
    server[0] !== cli[0] ||
    server[1] !== "-m" ||
    server[2] !== "opsys.serveur_mcp" ||
    cli[1] !== "-m" ||
    cli[2] !== "opsys.cli"
  ) {
    refuse();
  }
  // Preserve all server arguments, environment values and unknown future config fields.
  const updated = {
    ...raw,
    dossier: generation.source,
    commande: [generation.python, ...server.slice(1)],
    commande_cli: [generation.python, ...cli.slice(1)],
  };
  return Buffer.from(JSON.stringify(updated, null, 2) + "\n");
}

function stageFile(file: string, bytes: Buffer, mode: number, created: () => void): void {
  const fd = fs.openSync(
    file,
    fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL,
    0o600,
  );
  created();
  try {
    fs.fchmodSync(fd, mode & 0o777);
    fs.writeFileSync(fd, bytes);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
}

function syncDirectory(directory: string): void {
  const fd = fs.openSync(directory, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY);
  try {
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
}

function sameDirectory(directory: string, before: fs.Stats): void {
  physicalDirectory(directory);
  const current = fs.statSync(directory);
  if (
    before.dev !== current.dev ||
    before.ino !== current.ino ||
    before.mode !== current.mode ||
    before.uid !== current.uid
  ) {
    refuse();
  }
}

type RetainedRollback = { file: string; directory: string; parent: fs.Stats; snapshot: Snapshot };

class RollbackFailure extends Error {
  constructor(
    readonly artifact: string,
    options?: ErrorOptions,
  ) {
    super("Generation publication rollback incomplete; preserve private artifact.", options);
  }
}

function removeRetainedRollback(artifact: RetainedRollback): void {
  // Only private artifact housekeeping is permitted after the owner fully fulfills.
  // Never follow an alias or delete a replacement belonging to another writer.
  sameDirectory(artifact.directory, artifact.parent);
  if (!sameSnapshot(artifact.snapshot, readSnapshot(artifact.file, 1048576))) {
    refuse();
  }
  sameDirectory(artifact.directory, artifact.parent);
  fs.unlinkSync(artifact.file);
}

/** Narrow operation of the existing public `opsys metier` dispatcher, not an exec API. */
export async function runOpsysMetierGenerationPublication(
  args: readonly string[],
  params: {
    root?: string;
    env: NodeJS.ProcessEnv;
    dir?: string;
    stderr: { write: (text: string) => unknown };
  },
): Promise<number> {
  if (
    params.env.OPENCLAW_SHELL === "exec" ||
    params.env.OPENCLAW_PROFILE !== "opsys" ||
    process.platform !== "linux" ||
    !params.root
  ) {
    params.stderr.write(
      "opsys metier : publication de génération réservée à l’opérateur du profil opsys sous Linux.\n",
    );
    return 1;
  }
  const outcome: { retained?: RetainedRollback } = {};
  const scope = new AbortController();
  let interrupted = 0;
  const interrupt = () => {
    interrupted = 130;
    scope.abort();
  };
  const terminate = () => {
    interrupted = 143;
    scope.abort();
  };
  process.on("SIGINT", interrupt);
  process.on("SIGTERM", terminate);
  try {
    const generation = preparedGeneration(args);
    const root = physicalDirectory(params.root);
    await withGatewayRuntimeArtifactPublication(
      {
        root,
        env: params.env,
        timeoutMs: 10000,
        assertCurrent: () => scope.signal.throwIfAborted(),
        python: { softwareRoot: generation.softwareRoot, candidate: generation.candidate },
      },
      async (assertPublicationCurrent) => {
        await assertPublicationCurrent();
        currentGeneration(generation);
        // Existing initialized instance only. No dotenv secrets, Python CLI, migration or wrapper synthesis.
        const directory = physicalDirectory(params.dir ?? resolveOpsysDir(params.env));
        const parent = fs.statSync(directory);
        if ((parent.mode & 0o022) !== 0 || (process.getuid && parent.uid !== process.getuid())) {
          refuse();
        }
        const file = path.join(directory, OPSYS_METIER_CONFIG_FILENAME);
        const before = readSnapshot(file, 1048576);
        const next = runtimeConfig(before.bytes, generation);
        const pending = path.join(directory, `.metier-generation-${randomUUID()}`);
        const rollback = path.join(directory, `.metier-rollback-${randomUUID()}`);
        let replaced = false;
        let preserveRollback = false;
        let callbackCompleted = false;
        let staged: Snapshot | undefined;
        let rollbackSnapshot: Snapshot | undefined;
        let pendingOwned = false;
        let rollbackOwned = false;
        let callbackIssue: { failed: false } | { failed: true; error: unknown } = { failed: false };
        try {
          // Keep a complete fsynced old-byte artifact before the first replacement effect.
          stageFile(rollback, before.bytes, before.stat.mode, () => {
            rollbackOwned = true;
          });
          rollbackSnapshot = readSnapshot(rollback, 1048576);
          stageFile(pending, next, before.stat.mode, () => {
            pendingOwned = true;
          });
          staged = readSnapshot(pending, 1048576);
          await assertPublicationCurrent();
          currentGeneration(generation);
          sameDirectory(directory, parent);
          if (!sameSnapshot(before, readSnapshot(file, 1048576))) {
            refuse();
          }
          fs.renameSync(pending, file);
          pendingOwned = false;
          replaced = true;
          syncDirectory(directory);
          await assertPublicationCurrent();
          currentGeneration(generation);
          sameDirectory(directory, parent);
          const installed = readSnapshot(file, 1048576);
          if (
            installed.stat.dev !== staged.stat.dev ||
            installed.stat.ino !== staged.stat.ino ||
            !installed.bytes.equals(next)
          ) {
            refuse();
          }
          // Callback completion is provisional: the owner still asserts and releases.
          // Retain exact old bytes until its entire returned Promise has settled.
          outcome.retained = { file: rollback, directory, parent, snapshot: rollbackSnapshot };
          callbackCompleted = true;
        } catch (error) {
          callbackIssue = { failed: true, error };
          if (replaced) {
            // Join rollback inside the callback even if fresh admission now refuses.
            // Never overwrite a foreign concurrent writer, whose custody is not established here.
            preserveRollback = true;
            try {
              sameDirectory(directory, parent);
              const installed = readSnapshot(file, 1048576);
              if (
                !rollbackOwned ||
                !staged ||
                installed.stat.dev !== staged.stat.dev ||
                installed.stat.ino !== staged.stat.ino ||
                !installed.bytes.equals(next)
              ) {
                refuse();
              }
              // An await may have replaced our rollback pathname. Never install or
              // delete a foreign artifact merely because its temporary name matches.
              if (
                !rollbackSnapshot ||
                !sameSnapshot(rollbackSnapshot, readSnapshot(rollback, 1048576))
              ) {
                refuse();
              }
              sameDirectory(directory, parent);
              fs.renameSync(rollback, file);
              rollbackOwned = false;
              preserveRollback = false;
              syncDirectory(directory);
            } catch (rollbackError) {
              callbackIssue = {
                failed: true,
                error: new RollbackFailure(rollback, {
                  cause: new AggregateError([error, rollbackError]),
                }),
              };
            }
          }
        } finally {
          // Failed callback cleanup remains joined under the held owner. Successful
          // callback backup cleanup must wait for the full owner Promise instead.
          if (!callbackCompleted) {
            try {
              // An O_EXCL collision never grants ownership of the existing file.
              if (pendingOwned) {
                fs.rmSync(pending, { force: true });
              }
              if (!preserveRollback && rollbackOwned) {
                fs.rmSync(rollback, { force: true });
              }
            } catch (cleanupError) {
              const previous = callbackIssue;
              const combined = previous.failed
                ? new AggregateError(
                    [previous.error, cleanupError],
                    "Publication and cleanup failed.",
                    {
                      cause: previous.error,
                    },
                  )
                : cleanupError;
              const artifact =
                previous.failed && previous.error instanceof RollbackFailure
                  ? previous.error.artifact
                  : preserveRollback
                    ? rollback
                    : undefined;
              callbackIssue = {
                failed: true,
                error: artifact ? new RollbackFailure(artifact, { cause: combined }) : combined,
              };
            }
          }
        }
        if (callbackIssue.failed) {
          throw callbackIssue.error;
        }
      },
    );
    // Includes owner post-callback checks, release and outer operation finalization.
    // Only remove our own retained artifact here; no metier.json write or rollback.
    const retained = outcome.retained;
    if (retained) {
      try {
        removeRetainedRollback(retained);
        delete outcome.retained;
      } catch {
        params.stderr.write(
          `opsys metier : publication effectuée ; nettoyage privé incomplet ; conserver l’artefact privé ${retained.file}, fiabilité non confirmée.\n`,
        );
      }
    }
    return 0;
  } catch (error) {
    const artifact = error instanceof RollbackFailure ? error.artifact : outcome.retained?.file;
    params.stderr.write(
      artifact
        ? `opsys metier : publication en échec et restauration incomplète ; conserver l’artefact privé ${artifact}, fiabilité non confirmée ; réconciliation manuelle requise.\n`
        : "opsys metier : publication de génération refusée ; vérifier la génération préparée, l’instance déjà initialisée et le Gateway hors ligne de ce profil.\n",
    );
    return interrupted || 1;
  } finally {
    process.removeListener("SIGINT", interrupt);
    process.removeListener("SIGTERM", terminate);
    scope.abort();
  }
}
