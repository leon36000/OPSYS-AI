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
  /**
   * Entier strictement croissant assigné par le DÉPÔT à l'insertion (clé auto-incrémentée
   * SQLite, ou compteur de `DepotOutboxMemoire`) — voir `depot.ts`/`depot.sqlite.ts`. `null`
   * uniquement pour une mutation créée en mémoire (`creerMutation`) et pas encore insérée dans
   * un dépôt. C'est CE champ, pas `createdAtLocal`, qui fait foi pour l'ordre d'envoi
   * (`planification.ts`) : un texte d'heure locale avec décalage se compare mal d'un décalage à
   * l'autre (changement d'heure, appareil qui change de fuseau) — correction relevée en relecture
   * après PLAN T1.4-a.
   */
  readonly sequence: number | null;
  readonly type: TypeMutation;
  readonly chantierId: string;
  readonly payload: Readonly<Record<string, unknown>>;
  /** Mutation parente qui doit être `envoyee` avant que celle-ci parte (R12 §4), ou `null`. */
  readonly dependsOn: string | null;
  readonly statut: StatutMutation;
  readonly tentatives: number;
  /** ISO 8601 avec le décalage de fuseau de l'appareil — jamais `Z`/UTC (R12 §4). Affichage
   * seulement (« pointé à 14 h 32 ») — jamais utilisé pour trier ou décider, voir `sequence`. */
  readonly createdAtLocal: string;
  /**
   * Instant UTC (ISO 8601, `Z`) avant lequel un renvoi ne doit pas être tenté — `null` = due
   * immédiatement (jamais encore échouée, ou reprise après crash). Posé par
   * `marquerEchecReessayable` à partir de `src/outbox/recul.ts`, consommé par
   * `selectionnerProchainesEnvoyables`. Sans ce champ, le recul exponentiel calculé n'était
   * jamais appliqué à la sélection — corrigé en relecture après PLAN T1.4-a.
   */
  readonly prochaineTentativeA: string | null;
}
