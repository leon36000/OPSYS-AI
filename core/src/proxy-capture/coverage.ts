// Proxy capture coverage helpers summarize which network calls were captured.
import { resolveDebugProxySettings, type DebugProxySettings } from "./env.js";
import type { CaptureProtocol } from "./types.js";

// Debug-proxy coverage records which transport seams are fully captured versus
// merely routed through a proxy, so operators know where packet evidence is weak.
export type DebugProxyCoverageStatus = "captured" | "proxy-only" | "uncovered";

export type DebugProxyCoverageEntry = {
  id: string;
  label: string;
  modulePath: string;
  protocols: CaptureProtocol[];
  status: DebugProxyCoverageStatus;
  notes: string;
};

export type DebugProxyCoverageSummary = {
  total: number;
  captured: number;
  proxyOnly: number;
  uncovered: number;
};

// T0.6 : retiré les six entrées pour discord/mattermost/microsoft/feishu (extensions
// élaguées, `extensions/<id>` absent du fork) — un rapport de couverture qui les listait
// encore induirait en erreur un opérateur sur des canaux non installés. Les deux seules
// entrées « proxy-only » étaient feishu-client-http/-ws ; avec elles disparaît aussi tout
// canal « proxy-only » connu parmi les extensions conservées (voir le test associé).
const DEBUG_PROXY_COVERAGE_ENTRIES: readonly DebugProxyCoverageEntry[] = [
  {
    id: "provider-transport-fetch",
    label: "Provider HTTP transport",
    modulePath: "src/agents/provider-transport-fetch.ts",
    protocols: ["http", "https", "sse"],
    status: "captured",
    notes:
      "Central provider fetch seam routes through explicit proxy overrides and records request/response payloads.",
  },
  {
    id: "telegram-fetch",
    label: "Telegram fetch resolver",
    modulePath: "extensions/telegram/src/fetch.ts",
    protocols: ["http", "https"],
    status: "captured",
    notes:
      "Telegram API fetch fallback picks up debug proxy env and records outbound/inbound exchanges.",
  },
  {
    id: "openai-realtime-voice",
    label: "OpenAI realtime voice bridge",
    modulePath: "extensions/openai/realtime-voice-provider.ts",
    protocols: ["wss"],
    status: "captured",
    notes:
      "Realtime voice bridge now routes through the debug proxy agent and records websocket frames.",
  },
  {
    id: "openai-realtime-transcription",
    label: "OpenAI realtime transcription",
    modulePath: "extensions/openai/realtime-transcription-provider.ts",
    protocols: ["wss"],
    status: "captured",
    notes:
      "Realtime transcription sessions now route through the debug proxy agent and record websocket frames.",
  },
  {
    id: "openai-tts",
    label: "OpenAI text-to-speech",
    modulePath: "extensions/openai/tts.ts",
    protocols: ["https"],
    status: "captured",
    notes:
      "Direct OpenAI TTS fetches record request/response payloads while inheriting proxy env routing.",
  },
];

let warnedCoverageSessionKey: string | null = null;

function listDebugProxyCoverageEntries(
  entries: readonly DebugProxyCoverageEntry[] = DEBUG_PROXY_COVERAGE_ENTRIES,
): DebugProxyCoverageEntry[] {
  // Return copies because callers may render/sort/filter entries for CLI output.
  return entries.map((entry) => ({
    ...entry,
    protocols: [...entry.protocols],
  }));
}

function summarizeDebugProxyCoverage(
  entries: readonly DebugProxyCoverageEntry[] = DEBUG_PROXY_COVERAGE_ENTRIES,
): DebugProxyCoverageSummary {
  let captured = 0;
  let proxyOnly = 0;
  let uncovered = 0;
  for (const entry of entries) {
    if (entry.status === "captured") {
      captured += 1;
      continue;
    }
    if (entry.status === "proxy-only") {
      proxyOnly += 1;
      continue;
    }
    uncovered += 1;
  }
  return {
    total: entries.length,
    captured,
    proxyOnly,
    uncovered,
  };
}

export function buildDebugProxyCoverageReport(
  sourceEntries: readonly DebugProxyCoverageEntry[] = DEBUG_PROXY_COVERAGE_ENTRIES,
) {
  const entries = listDebugProxyCoverageEntries(sourceEntries);
  return {
    summary: summarizeDebugProxyCoverage(entries),
    entries,
  };
}

export function maybeWarnAboutDebugProxyCoverage(
  settings: DebugProxySettings = resolveDebugProxySettings(),
  warn: (message: string) => void = (message) => console.warn(message),
  // Test-only seam (default: the real, live entries): lets a test exercise the warning's
  // message format for a gap deterministically, without asserting that some specific kept
  // extension is truthfully incomplete — see the T0.6 note above DEBUG_PROXY_COVERAGE_ENTRIES.
  sourceEntries: readonly DebugProxyCoverageEntry[] = DEBUG_PROXY_COVERAGE_ENTRIES,
): void {
  if (!settings.enabled || !settings.required) {
    return;
  }
  const sessionKey = `${settings.sessionId}:${settings.proxyUrl ?? ""}`;
  // Warn once per capture session/proxy URL; the gaps are static enough that
  // repeating them during a run only adds noise.
  if (warnedCoverageSessionKey === sessionKey) {
    return;
  }
  warnedCoverageSessionKey = sessionKey;

  const report = buildDebugProxyCoverageReport(sourceEntries);
  const { summary } = report;
  const partial = report.entries.filter((entry) => entry.status !== "captured");
  if (partial.length === 0) {
    return;
  }
  warn(
    `[openclaw proxy] debug proxy coverage: ${summary.captured}/${summary.total} captured, ${summary.proxyOnly} proxy-only, ${summary.uncovered} uncovered.`,
  );
  warn(
    `[openclaw proxy] remaining gaps: ${partial.map((entry) => entry.id).join(", ")}. Run \`openclaw proxy coverage\` for details.`,
  );
}
