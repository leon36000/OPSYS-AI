import { randomUUID } from "node:crypto";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const CONTEXTE = {
  version: 2,
  actif: true,
  agents: {
    "m02-revenue-crm": {
      affaire: "session",
      serveur_contexte: "opsys_context_m02-revenue-crm",
    },
    // The unit wire fixture verifies explicit demande origin. The real M3 device path is
    // authenticated at Python and bypasses ticket issuance, so it does not consume this field.
    "m03-estimation": {
      affaire: "demande",
      serveur_contexte: "opsys_context_m03-estimation",
    },
    "m09-strategic-intelligence": {
      affaire: "session",
      serveur_contexte: "opsys_context_m09-strategic-intelligence",
      origine_paquet: "m09-strategic-intelligence",
      depot: [],
    },
  },
  niveaux: {
    m2_enregistrer_interaction: "N3",
    m3_marquer_devis_accepte: "N5",
    m3_demander_envoi_devis: "N4",
    m9_ouvrir_suivi_decision: "N3",
    m9_preparer_suivi_decision: "N0",
    m9_lire_suivi_decision: "N0",
  },
  cibles: {
    m2_enregistrer_interaction: { type: "ticket" },
    m3_marquer_devis_accepte: { type: "ticket" },
    m3_demander_envoi_devis: { type: "ticket" },
    m9_ouvrir_suivi_decision: { type: "ticket" },
  },
};

/**
 * Write the same atomic fixture path for both runtime test files.
 *
 * `OPENCLAW_CONFIG_PATH` is process-scoped in the shared Vitest worker, so per-file config paths
 * and afterEach restoration race when those files run in one shard. The shard process is isolated
 * by the test runner; the shared synthetic config is confined to tmpdir, outside repository state.
 */
export async function acquireOpsysContextTestConfig(): Promise<() => Promise<void>> {
  const root = path.join(tmpdir(), `opsys-c02-context-test-${process.pid}`);
  const opsysDir = path.join(root, "opsys");
  const configPath = path.join(root, "openclaw.json");
  const stagedPath = `${path.join(opsysDir, "contexte.json")}.${randomUUID()}.tmp`;
  await mkdir(opsysDir, { recursive: true });
  await writeFile(stagedPath, JSON.stringify(CONTEXTE), { mode: 0o600 });
  await rename(stagedPath, path.join(opsysDir, "contexte.json"));
  process.env.OPENCLAW_CONFIG_PATH = configPath;
  return async () => {};
}
