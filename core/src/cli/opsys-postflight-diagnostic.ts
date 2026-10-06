import {
  readOpsysPostflightDiagnosticSnapshot,
  type OpsysPostflightDiagnosticSnapshot,
} from "../agents/harness/opsys-postflight-outbox.worker.js";
import { withFreshOpenClawAgentDatabaseReadOnly } from "../state/openclaw-agent-db-readonly-open.js";

type DiagnosticUnavailableReason =
  | "operator-only"
  | "agent-id-invalid"
  | "database-missing"
  | "schema-missing"
  | "tables-missing"
  | "read-refused";
export type OpsysPostflightDiagnostic = (
  | ({ status: "available" } & OpsysPostflightDiagnosticSnapshot)
  | { status: "unavailable"; reason: DiagnosticUnavailableReason }
) & { agentId: string | null; readOnly: true; sourceReplayAllowed: false };

/** Local operator view, not an MCP tool or a dashboard authorization bridge. */
export function inspectOpsysPostflightDiagnostic(params: {
  agentId: string;
  env?: NodeJS.ProcessEnv;
  now?: number;
}): OpsysPostflightDiagnostic {
  const { agentId } = params;
  const env = params.env ?? process.env;
  const canonical = typeof agentId === "string" && /^[a-z0-9][a-z0-9_-]{0,63}$/u.test(agentId);
  const base = {
    agentId: canonical ? agentId : null,
    readOnly: true as const,
    sourceReplayAllowed: false as const,
  };
  if (env.OPENCLAW_SHELL === "exec") {
    return { ...base, status: "unavailable", reason: "operator-only" };
  }
  // The path helper normalizes unsafe input to main: never let this view fall back silently.
  if (!canonical) {
    return { ...base, status: "unavailable", reason: "agent-id-invalid" };
  }
  try {
    const result = withFreshOpenClawAgentDatabaseReadOnly(
      ({ db, agentId: owner }) => {
        if (owner !== agentId) {
          throw new Error("POSTFLIGHT_DIAGNOSTIC_OWNER_REFUSE");
        }
        return readOpsysPostflightDiagnosticSnapshot(db, params.now ?? Date.now());
      },
      { agentId, env },
    );
    if (!result.found) {
      return { ...base, status: "unavailable", reason: result.reason };
    }
    return result.value.status === "available"
      ? { ...base, status: "available", ...result.value.snapshot }
      : { ...base, ...result.value };
  } catch {
    // Corrupt rows, wrong owners and schema/read failures must not leak payloads or fake zeros.
    return { ...base, status: "unavailable", reason: "read-refused" };
  }
}

export function formatOpsysPostflightDiagnostic(result: OpsysPostflightDiagnostic): string {
  if (result.status === "unavailable") {
    return `M10 postflight indisponible : ${result.reason}. Aucun état de file déduit.\n`;
  }
  const { counts, capacity } = result;
  const lines = [
    `M10 postflight — agent ${result.agentId} — instantané en lecture seule.`,
    `Intentions incertaines : ${counts.uncertain}. Lots pending : ${counts.pending}; retry : ${counts.retry}; revue requise : ${counts.reviewRequired}; échéance atteinte : ${counts.due}.`,
    `Capacité réservée : ${capacity.occupiedSlots}/${result.limits.maxSlots} places, ${capacity.reservedBytes}/${result.limits.maxBytes} octets.`,
    "Incertain = réservation avant l’outil; exécution et résultat inconnus. Ne pas relancer l’action métier à partir de cet état.",
    "Les lots et tentatives concernent la remise à M10. Aucun envoi ni rejeu n’est déclenché; cette vue n’est pas un historique de réussite.",
  ];
  for (const intent of result.uncertainIntents) {
    lines.push(
      `INCERTAIN dossier=${intent.affaireId} département=${intent.departementSource} profil=${intent.profilId}@${intent.revision} outil=${intent.outil} réservé_ms=${intent.createdAt}`,
    );
  }
  for (const lot of result.lots) {
    lines.push(
      `LOT dossier=${lot.affaireId} département=${lot.departementSource} profil=${lot.profilId}@${lot.revision} état=${lot.state} faits=${lot.factCount} tentatives_remise=${lot.attemptCount} prochaine_ms=${lot.nextAttemptAt ?? "aucune"} revue=${lot.reviewRequired ? "oui" : "non"}`,
    );
  }
  return `${lines.join("\n")}\n`;
}
