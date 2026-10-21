/** Exact business-tool/server contract whose target is resolved by the Python ticket authority. */
export const OPSYS_CIBLE_TICKET_SERVERS = {
  m2_transitionner_statut: "opsys_m2",
  m2_reassigner_lead: "opsys_m2",
  m2_enregistrer_interaction: "opsys_m2",
  m2_preparer_relance: "opsys_m2",
  m2_enregistrer_consentement_contact: "opsys_m2",
  m2_marquer_chantier_termine: "opsys_m2",
  m3_marquer_devis_accepte: "opsys_m3",
  m3_demander_envoi_devis: "opsys_m3",
  m3_creer_devis: "opsys_m3",
  m9_ouvrir_suivi_decision: "opsys_m9",
} as const satisfies Record<string, string>;

export type OpsysCibleTicketTool = keyof typeof OPSYS_CIBLE_TICKET_SERVERS;

export function isOpsysCibleTicketTool(toolName: string): toolName is OpsysCibleTicketTool {
  return Object.hasOwn(OPSYS_CIBLE_TICKET_SERVERS, toolName);
}
