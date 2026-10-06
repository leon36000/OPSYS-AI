// POSTFLIGHT facts of the OPSYS context engine (OPSYS-AI PLAN T3.3-suite): pure functions, no I/O.
//
// After an agent turn the core hands M10 (`m10_deposer_faits_candidats`) what the department TOOLS
// did during the turn: tool, outcome (`ok` or `refus`), code. Everything is read from the tool's
// own structured answer (`opsys.outils.executer`: `{ok, resultat | erreur}`), never from what the
// model wrote: a model's text is not a source (AGENTS.md, the code computes, the LLM orchestrates).
// A tool answer that cannot be read with certainty produces no fact at all.
import { createHash } from "node:crypto";
import { isRecord } from "@openclaw/normalization-core/record-coerce";

export type OpsysDepositFact = Readonly<{
  cle: string;
  outil: string;
  resultat: "ok" | "refus";
  code: string | null;
}>;

// Same shape as M10 accepts for a code (`faits_candidats.py`): anything else becomes `null`.
const CODE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/u;
const TOOL_NAME_SEPARATOR = "__";

/**
 * Model-facing tool names are `<server>__<tool>` (`agent-bundle-mcp-names.ts`): a result belongs to
 * a configured tool when it carries exactly that tool name, with or without the server prefix.
 */
function matchDepositTool(toolName: string, depositTools: readonly string[]): string | undefined {
  return depositTools.find(
    (tool) => toolName === tool || toolName.endsWith(`${TOOL_NAME_SEPARATOR}${tool}`),
  );
}

function textOf(content: unknown): string | undefined {
  if (!Array.isArray(content)) {
    return undefined;
  }
  const parts: string[] = [];
  for (const block of content) {
    if (isRecord(block) && block.type === "text" && typeof block.text === "string") {
      parts.push(block.text);
    }
  }
  return parts.length > 0 ? parts.join("") : undefined;
}

function safeCode(value: unknown): string | null {
  return typeof value === "string" && CODE_PATTERN.test(value) ? value : null;
}

type Outcome = Readonly<{ resultat: "ok" | "refus"; code: string | null }>;

/**
 * The outcome carried by a tool answer, or `undefined` when it is not certain: unreadable text, an
 * action that waits for an approval (it did NOT happen), or a transport error that says nothing
 * about what the tool did.
 */
function readOutcome(text: string): Outcome | undefined {
  let envelope: unknown;
  try {
    envelope = JSON.parse(text);
  } catch {
    return undefined;
  }
  if (!isRecord(envelope)) {
    return undefined;
  }
  if (envelope.ok === false) {
    return { resultat: "refus", code: safeCode(envelope.erreur) };
  }
  if (envelope.ok !== true || envelope.statut === "en_attente_approbation") {
    return undefined;
  }
  const result = envelope.resultat;
  if (isRecord(result) && result.accepte === false) {
    return { resultat: "refus", code: safeCode(result.verdict) };
  }
  return { resultat: "ok", code: null };
}

/** Stable per tool call, and independent of the characters a provider puts in its call ids. */
export function depositKey(sessionId: string, toolCallId: string): string {
  const digest = createHash("sha256").update(`${sessionId}\u0000${toolCallId}`).digest("hex");
  return `tc-${digest.slice(0, 40)}`;
}

/** The facts to deposit for the messages of ONE turn, in transcript order, one per tool call. */
export function collectDepositFacts(params: {
  sessionId: string;
  messages: readonly unknown[];
  depositTools: readonly string[];
}): OpsysDepositFact[] {
  const facts: OpsysDepositFact[] = [];
  const seen = new Set<string>();
  for (const message of params.messages) {
    if (
      !isRecord(message) ||
      message.role !== "toolResult" ||
      typeof message.toolName !== "string" ||
      typeof message.toolCallId !== "string"
    ) {
      continue;
    }
    const tool = matchDepositTool(message.toolName, params.depositTools);
    const text = textOf(message.content);
    if (tool === undefined || text === undefined) {
      continue;
    }
    const outcome = readOutcome(text);
    const cle = depositKey(params.sessionId, message.toolCallId);
    if (outcome === undefined || seen.has(cle)) {
      continue;
    }
    seen.add(cle);
    facts.push({ cle, outil: tool, resultat: outcome.resultat, code: outcome.code });
  }
  return facts;
}

/** Parse one observed runtime result with the same conservative rules as transcript collection. */
export function collectDepositFactForToolResult(params: {
  sessionId: string;
  toolCallId: string;
  toolName: string;
  content: unknown;
  isError: boolean;
  depositTools: readonly string[];
}): OpsysDepositFact | undefined {
  if (params.isError) {
    return undefined;
  }
  const tool = matchDepositTool(params.toolName, params.depositTools);
  const text = textOf(params.content);
  if (tool === undefined || text === undefined) {
    return undefined;
  }
  const outcome = readOutcome(text);
  if (!outcome) {
    return undefined;
  }
  return {
    cle: depositKey(params.sessionId, params.toolCallId),
    outil: tool,
    resultat: outcome.resultat,
    code: outcome.code,
  };
}

/** The text a person or a system sent in the turn: user messages only, runtime carriers excluded. */
export function collectUserText(messages: readonly unknown[]): string {
  const parts: string[] = [];
  for (const message of messages) {
    if (!isRecord(message) || message.role !== "user" || message.runtimeContextCarrier === true) {
      continue;
    }
    const content = message.content;
    const text = typeof content === "string" ? content : textOf(content);
    if (text !== undefined) {
      parts.push(text);
    }
  }
  return parts.join("\n");
}
