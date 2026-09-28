/** Statuts de la file sortante, dans l'ordre du cycle de vie normal (R12 §4). */
export type StatutMutation = "brouillon" | "en_attente" | "envoi" | "envoyee" | "echec_permanent";

/** Catalogue fermé des types de mutation terrain (R12 §4). */
export type TypeMutation =
  | "punch_in"
  | "punch_out"
  | "job_status_change"
  | "materials_submit"
  | "checklist_step"
  | "incident_report"
  | "photo_upload"
  | "signature_capture"
  | "po_receive_scan";

/**
 * Une ligne de la file sortante SQLite (`outbox`, R12 §4). `id` est le `mutation_id` UUID créé
 * sur l'appareil avant tout réseau ; il sert aussi d'`idempotencyKey` à `src/protocole`.
 */
export interface MutationOutbox {
  readonly id: string;
  readonly type: TypeMutation;
  readonly chantierId: string;
  readonly payload: Readonly<Record<string, unknown>>;
  /** Mutation parente qui doit être `envoyee` avant que celle-ci parte (R12 §4), ou `null`. */
  readonly dependsOn: string | null;
  readonly statut: StatutMutation;
  readonly tentatives: number;
  /** ISO 8601 avec le décalage de fuseau de l'appareil — jamais `Z`/UTC (R12 §4). */
  readonly createdAtLocal: string;
}
