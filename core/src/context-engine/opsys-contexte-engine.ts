// OPSYS context engine (OPSYS-AI PLAN T3.3-suite, ADR-0010 decisions 3 and 4).
//
// A `ContextEngine` selected by `plugins.slots.contextEngine: "opsys"` (written by
// `src/opsys/openclaw.py` together with `opsys/contexte.json`). It adds two things to a department
// agent's turn and reuses everything else from the fork:
//   - PREFLIGHT, in `assemble()`: asks M10 for the packet of the case the turn is about
//     (`m10_paquet_contexte_affaire`, through the existing MCP road) and returns it as the
//     `systemPromptAddition` the runner already prepends to the system prompt. The assembly of the
//     messages is the legacy engine's own, untouched;
//   - POSTFLIGHT, in `afterTurn()`: hands M10 what the department tools did during the turn
//     (`m10_deposer_faits_candidats`), never what the model wrote.
// Compaction stays the runtime's (`delegateCompactionToRuntime`, same as the legacy engine).
//
// One thing a non-legacy engine owes the host: the runner leaves the memory guidance (memory-core
// tools, citations) out of the system prompt for every engine but "legacy" and expects the engine to
// add it (`buildMemorySystemPromptAddition`, see `delegate.ts`). This engine always does, so agents
// keep the native memory of ADR-0010 layer A whatever `contexte.json` says.
//
// Fail-closed AND never blocking. Whatever goes wrong (engine unreachable, too slow, invalid or
// oversized packet, no case in the request), the turn continues WITHOUT a packet, carries an
// explicit "contexte d'entreprise indisponible" marker, and leaves one journal line. A packet is
// never invented, repaired or shortened, and every call to the engine is bounded by `delai_ms`.
// `assemble()` and `afterTurn()` never throw: the registry would quarantine an engine that does.
//
// Transparent by default: without `opsys/contexte.json` carrying `"actif": true`, or for an agent
// the file does not name, the engine behaves exactly like the legacy one.
import { normalizeAgentId } from "@openclaw/normalization-core/agent-id";
import { estimateTokensFromChars } from "@openclaw/normalization-core/cjk-chars";
import { isRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { formatErrorMessage } from "../infra/errors.js";
import { createSubsystemLogger } from "../logging/subsystem.js";
import { parseAgentSessionKey } from "../routing/session-key.js";
import { createLazyRuntimeModule } from "../shared/lazy-runtime.js";
import { buildMemorySystemPromptAddition, delegateCompactionToRuntime } from "./delegate.js";
import { LegacyContextEngine } from "./legacy.js";
import {
  readOpsysContexteConfig,
  type OpsysContexteConfig,
  type OpsysContexteConfigResult,
} from "./opsys-contexte-config.js";
import { collectDepositFacts, collectUserText, type OpsysDepositFact } from "./opsys-contexte-depot.js";
import {
  extractAffaireId,
  parsePaquetEnvelope,
  renderPaquet,
  renderUnavailable,
} from "./opsys-contexte-paquet.js";
import { CONTEXT_ENGINE_HOST_PARAMS } from "./registry-contract.js";
import type { AssembleResult, ContextEngine, ContextEngineInfo } from "./types.js";

/** Id the engine is registered and selected under (`plugins.slots.contextEngine`). */
export const OPSYS_CONTEXT_ENGINE_ID = "opsys";
/** Subsystem name of the engine's lines in the Gateway journal. */
export const OPSYS_CONTEXTE_LOG_SUBSYSTEM = "opsys-contexte";

// M10 accepts at most this many facts per deposit (`faits_candidats.py`, NB_FAITS_MAX_PAR_DEPOT).
const DEPOSIT_BATCH_SIZE = 20;

const loadMcpCaller = createLazyRuntimeModule(() => import("./opsys-contexte-mcp.js"));

export type OpsysContexteLog = {
  debug: (message: string) => void;
  info: (message: string) => void;
  warn: (message: string) => void;
};

/** One bounded call to a tool of the business engine. Resolves with the parsed OPSYS answer. */
export type OpsysContexteToolCaller = (params: {
  tool: string;
  args: Record<string, unknown>;
  timeoutMs: number;
  signal: AbortSignal;
}) => Promise<unknown>;

/** Seams for tests. Production passes none of them. */
export type OpsysContexteEngineDeps = {
  readConfig?: () => OpsysContexteConfigResult;
  callTool?: OpsysContexteToolCaller;
  /** Starts a timer and returns its cancel function. */
  startTimer?: (ms: number, onExpire: () => void) => () => void;
  nowMs?: () => number;
  log?: OpsysContexteLog;
};

type Assemble = ContextEngine["assemble"];
type AfterTurn = NonNullable<ContextEngine["afterTurn"]>;
type Settings =
  | { kind: "off" }
  | { kind: "invalid"; reason: string }
  | { kind: "on"; config: OpsysContexteConfig };

class DeadlineError extends Error {}

function startRealTimer(ms: number, onExpire: () => void): () => void {
  const timer = setTimeout(onExpire, ms);
  timer.unref();
  return () => clearTimeout(timer);
}

function describeError(error: unknown): string {
  return error instanceof DeadlineError ? error.message : formatErrorMessage(error);
}

export class OpsysContextEngine implements ContextEngine {
  readonly info: ContextEngineInfo = {
    id: OPSYS_CONTEXT_ENGINE_ID,
    name: "OPSYS Context Engine",
    version: "1.0.0",
    acceptedHostParams: [...CONTEXT_ENGINE_HOST_PARAMS],
    ownsCompaction: false,
    // Without these two capabilities the packet would silently never be injected: refuse instead.
    hostRequirements: {
      "agent-run": {
        requiredCapabilities: ["assemble-before-prompt", "after-turn"],
        unsupportedMessage:
          "The OPSYS context engine injects the enterprise context before the prompt and deposits " +
          "facts after the turn: run department agents on the embedded runner.",
      },
    },
  };

  // Message assembly and ingestion stay the legacy engine's own: this engine adds a system prompt
  // addition and a post-turn deposit, it does not rewrite the assembly.
  private readonly legacy = new LegacyContextEngine();
  // The canonical runtime delegate keeps its watchdog ownership (see `legacy.ts`).
  readonly compact = delegateCompactionToRuntime;

  private readonly config: OpenClawConfig | undefined;
  private readonly readConfig: () => OpsysContexteConfigResult;
  private readonly callTool: OpsysContexteToolCaller;
  private readonly startTimer: (ms: number, onExpire: () => void) => () => void;
  private readonly nowMs: () => number;
  private readonly log: OpsysContexteLog;

  constructor(config: OpenClawConfig | undefined, deps: OpsysContexteEngineDeps = {}) {
    this.config = config;
    this.readConfig = deps.readConfig ?? (() => readOpsysContexteConfig());
    this.callTool = deps.callTool ?? ((params) => this.callThroughMcp(params));
    this.startTimer = deps.startTimer ?? startRealTimer;
    this.nowMs = deps.nowMs ?? Date.now;
    this.log = deps.log ?? createSubsystemLogger(OPSYS_CONTEXTE_LOG_SUBSYSTEM);
  }

  ingest(params: Parameters<ContextEngine["ingest"]>[0]) {
    return this.legacy.ingest(params);
  }

  async assemble(params: Parameters<Assemble>[0]): Promise<AssembleResult> {
    const assembled = await this.legacy.assemble(params);
    const memory = this.memoryGuidance(params);
    let packet: string | undefined;
    try {
      packet = await this.composeAddition(params);
    } catch (error) {
      // Unreachable by construction; kept so no failure can ever cost the turn its assembly.
      this.log.warn(`opsys-contexte: unexpected failure in assemble: ${describeError(error)}`);
      packet = renderUnavailable("erreur interne du moteur de contexte");
    }
    const addition = [memory, packet].filter((part) => part !== undefined).join("\n\n");
    return addition === "" ? assembled : { ...assembled, systemPromptAddition: addition };
  }

  async afterTurn(params: Parameters<AfterTurn>[0]): Promise<void> {
    try {
      await this.deposit(params);
    } catch (error) {
      this.log.warn(`opsys-contexte: POSTFLIGHT abandoned: ${describeError(error)}`);
    }
  }

  /**
   * The memory guidance the runner no longer puts in the system prompt for a non-legacy engine. It
   * must never cost the turn its packet, nor the packet its turn: a failure here is only journaled.
   */
  private memoryGuidance(params: Parameters<Assemble>[0]): string | undefined {
    try {
      return buildMemorySystemPromptAddition({
        availableTools: params.availableTools ?? new Set<string>(),
        citationsMode: params.citationsMode,
        agentSessionKey: params.sessionKey,
      });
    } catch (error) {
      this.log.warn(`opsys-contexte: memory guidance unavailable: ${describeError(error)}`);
      return undefined;
    }
  }

  private async callThroughMcp(params: Parameters<OpsysContexteToolCaller>[0]): Promise<unknown> {
    const settings = this.resolveSettings();
    if (settings.kind !== "on") {
      throw new Error("the OPSYS context engine is not configured");
    }
    const { callOpsysMcpTool } = await loadMcpCaller();
    return await callOpsysMcpTool({
      config: this.config,
      server: settings.config.server,
      tool: params.tool,
      args: params.args,
      timeoutMs: params.timeoutMs,
      signal: params.signal,
    });
  }

  private resolveSettings(): Settings {
    const result = this.readConfig();
    if (result.kind === "enabled") {
      return { kind: "on", config: result.config };
    }
    if (result.kind === "invalid") {
      return { kind: "invalid", reason: result.reason };
    }
    return { kind: "off" };
  }

  /** Runs `call` with a hard bound: past `timeoutMs` the turn goes on and the call is aborted. */
  private async bounded(
    timeoutMs: number,
    call: (signal: AbortSignal) => Promise<unknown>,
  ): Promise<unknown> {
    const controller = new AbortController();
    let cancelTimer: () => void = () => undefined;
    const expired = new Promise<never>((resolve, reject) => {
      cancelTimer = this.startTimer(timeoutMs, () => {
        controller.abort();
        reject(new DeadlineError(`pas de réponse en ${String(timeoutMs)} ms`));
      });
    });
    try {
      return await Promise.race([call(controller.signal), expired]);
    } finally {
      cancelTimer();
    }
  }

  private unavailable(agentId: string, affaireId: string | undefined, reason: string): string {
    const scope = affaireId === undefined ? agentId : `${agentId}, affaire ${affaireId}`;
    this.log.warn(`opsys-contexte: contexte d'entreprise indisponible (${scope}) : ${reason}`);
    return renderUnavailable(reason);
  }

  private async composeAddition(params: Parameters<Assemble>[0]): Promise<string | undefined> {
    const settings = this.resolveSettings();
    if (settings.kind === "off") {
      return undefined;
    }
    const agentId = agentIdOf(params.sessionKey);
    if (settings.kind === "invalid") {
      // A broken configuration is loud: the operator selected this engine, so the turn says it is
      // running without the context it was promised.
      return this.unavailable(agentId ?? "agent inconnu", undefined, `configuration invalide (${settings.reason})`);
    }
    const { config } = settings;
    if (agentId === undefined || !config.agents.has(agentId)) {
      return undefined;
    }
    const lookup = extractAffaireId(params.prompt);
    if (lookup.kind !== "found") {
      const why =
        lookup.kind === "none"
          ? "aucune affaire (ligne « affaire_id: ... ») dans la demande"
          : "plusieurs affaires dans la demande";
      return this.unavailable(agentId, undefined, why);
    }
    const { affaireId } = lookup;

    let envelope: unknown;
    try {
      envelope = await this.bounded(config.timeoutMs, (signal) =>
        this.callTool({
          tool: config.packetTool,
          args: { affaire_id: affaireId, horodatage: this.horodatage() },
          timeoutMs: config.timeoutMs,
          signal,
        }),
      );
    } catch (error) {
      return this.unavailable(agentId, affaireId, `moteur métier injoignable ou trop lent (${describeError(error)})`);
    }
    const parsed = parsePaquetEnvelope(envelope, affaireId);
    if (!parsed.ok) {
      return this.unavailable(agentId, affaireId, `paquet inutilisable (${parsed.reason})`);
    }
    const rendered = renderPaquet(parsed.paquet);
    // M10 computed the budget; the core does not shorten the packet to fit, it refuses it.
    if (rendered.bodyChars > parsed.paquet.budgetCaracteres) {
      return this.unavailable(
        agentId,
        affaireId,
        `paquet hors du budget de M10 (${String(rendered.bodyChars)} sur ${String(parsed.paquet.budgetCaracteres)} caractères), non tronqué`,
      );
    }
    const tokenBudget = params.tokenBudget;
    if (
      typeof tokenBudget === "number" &&
      Number.isFinite(tokenBudget) &&
      estimateTokensFromChars(rendered.text.length) > tokenBudget
    ) {
      return this.unavailable(agentId, affaireId, "paquet plus grand que le budget de contexte disponible, non tronqué");
    }
    this.log.debug(
      `opsys-contexte: paquet injecté (${agentId}, affaire ${affaireId}, ${String(parsed.paquet.caracteresUtilises)} caractères)`,
    );
    return rendered.text;
  }

  private async deposit(params: Parameters<AfterTurn>[0]): Promise<void> {
    if (params.isHeartbeat === true) {
      return;
    }
    const settings = this.resolveSettings();
    if (settings.kind !== "on") {
      return;
    }
    const { config } = settings;
    const agentId = agentIdOf(params.sessionKey);
    const depositTools = agentId === undefined ? undefined : config.agents.get(agentId);
    if (agentId === undefined || depositTools === undefined || depositTools.length === 0) {
      return;
    }
    const turnMessages = params.messages.slice(params.prePromptMessageCount);
    const facts = collectDepositFacts({
      sessionId: params.sessionId,
      messages: turnMessages,
      depositTools,
    });
    if (facts.length === 0) {
      return;
    }
    const lookup = extractAffaireId(collectUserText(turnMessages));
    if (lookup.kind !== "found") {
      this.log.warn(
        `opsys-contexte: POSTFLIGHT sans affaire identifiable (${agentId}) : ${String(facts.length)} fait(s) non déposé(s)`,
      );
      return;
    }
    for (let start = 0; start < facts.length; start += DEPOSIT_BATCH_SIZE) {
      await this.depositBatch(config, agentId, lookup.affaireId, facts.slice(start, start + DEPOSIT_BATCH_SIZE));
    }
  }

  private async depositBatch(
    config: OpsysContexteConfig,
    agentId: string,
    affaireId: string,
    facts: OpsysDepositFact[],
  ): Promise<void> {
    let envelope: unknown;
    try {
      envelope = await this.bounded(config.timeoutMs, (signal) =>
        this.callTool({
          tool: config.depositTool,
          args: {
            affaire_id: affaireId,
            departement: agentId,
            faits: facts,
            horodatage: this.horodatage(),
          },
          timeoutMs: config.timeoutMs,
          signal,
        }),
      );
    } catch (error) {
      this.log.warn(
        `opsys-contexte: POSTFLIGHT indisponible (${agentId}, affaire ${affaireId}) : ${String(facts.length)} fait(s) non déposé(s) (${describeError(error)})`,
      );
      return;
    }
    const outcome = readDepositOutcome(envelope);
    if (outcome.ok) {
      this.log.info(
        `opsys-contexte: POSTFLIGHT (${agentId}, affaire ${affaireId}) : ${String(outcome.ecrits)} écrit(s), ${String(outcome.dejaDeposes)} déjà déposé(s)`,
      );
      return;
    }
    this.log.warn(
      `opsys-contexte: POSTFLIGHT refusé par M10 (${agentId}, affaire ${affaireId}) : ${outcome.reason}`,
    );
  }

  /** ISO 8601 with an explicit offset, from the core's clock: M10 never reads one. */
  private horodatage(): string {
    return new Date(this.nowMs()).toISOString().replace("Z", "+00:00");
  }
}

function agentIdOf(sessionKey: string | undefined): string | undefined {
  const parsed = parseAgentSessionKey(sessionKey);
  return parsed?.agentId ? normalizeAgentId(parsed.agentId) : undefined;
}

type DepositOutcome =
  | { ok: true; ecrits: number; dejaDeposes: number }
  | { ok: false; reason: string };

function readDepositOutcome(envelope: unknown): DepositOutcome {
  if (!isRecord(envelope)) {
    return { ok: false, reason: "réponse illisible" };
  }
  if (envelope.ok !== true) {
    return { ok: false, reason: typeof envelope.erreur === "string" ? envelope.erreur : "erreur inconnue" };
  }
  const answer = envelope.resultat;
  if (!isRecord(answer)) {
    return { ok: false, reason: "réponse sans résultat" };
  }
  if (answer.accepte !== true) {
    return { ok: false, reason: typeof answer.verdict === "string" ? answer.verdict : "refus sans verdict" };
  }
  const counts = isRecord(answer.resultat) ? answer.resultat : {};
  return {
    ok: true,
    ecrits: typeof counts.ecrits === "number" ? counts.ecrits : 0,
    dejaDeposes: typeof counts.deja_deposes === "number" ? counts.deja_deposes : 0,
  };
}

/** Factory for the registry: one engine per resolution, bound to the runtime configuration. */
export function createOpsysContextEngine(
  config: OpenClawConfig | undefined,
  deps: OpsysContexteEngineDeps = {},
): OpsysContextEngine {
  return new OpsysContextEngine(config, deps);
}
