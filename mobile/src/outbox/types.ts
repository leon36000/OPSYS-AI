/** Statuts de la file sortante, dans l'ordre du cycle de vie normal (R12 §4). */
export type StatutMutation = "brouillon" | "en_attente" | "envoi" | "envoyee" | "echec_permanent";

/**
 * Catalogue fermé des types de mutation terrain (R12 §4, dont la liste documentée se termine par
 * « … » — extensible). PLAN T1.4-f ajoute deux entrées :
 *  - `fichier_bloc` : UN bloc (262 144 octets, contrat `m4_deposer_fichier`) d'un envoi de fichier
 *    par la file sortante — distinct de `photo_upload`/`signature_capture`, qui restent les
 *    enregistrements LOCAUX (URI + SHA-256 capturés, toujours `brouillon`, T1.4-e inchangé) : un
 *    fichier capturé produit PLUSIEURS mutations `fichier_bloc` (une par bloc), voir
 *    `src/fichiers/envoiOrchestrateur.ts`.
 *  - `job_completion` : `m4_completer_intervention` (« Terminer », `complete.tsx`) — type DÉDIÉ
 *    plutôt que de réutiliser `job_status_change` (déjà à sens unique vers `m4_demarrer_route`,
 *    voir `src/outbox/descripteurs.ts`), même principe que documenté dans `src/ecrans/job.ts`
 *    pour une future transition distincte (report, annulation…).
 * PLAN T1.4-k ajoute `gps_consent_change` : `m4_definir_consentement_gps` — l'employé retire (ou
 * donne) SON consentement à la géolocalisation (POLITIQUE-geolocalisation §4), `consent.tsx`, voir
 * `src/m4/consentementGps.ts`. Type DÉDIÉ : ce n'est ni un pointage ni une transition de statut.
 *  - `approval_decision` (PLAN T1.4-f, étape 6) : la décision du propriétaire sur UNE demande
 *    d'approbation (`m9_decider_demande_approbation`, `(admin)/approvals.tsx`). Une mutation par
 *    décision, `chantierId` fixe (`approbations`, pas un chantier) : son id est la clé d'idempotence
 *    qui fait qu'une décision renvoyée ne s'applique qu'une fois.
 *  - `lead_note` (PLAN T4.8) : une note du vendeur sur SON lead (`m2_enregistrer_interaction`,
 *    `(seller)/lead/[id].tsx`, `src/m2/interaction.ts`). Une mutation par note, `chantierId` = `lead:<id>` (une
 *    note n'appartient à aucun chantier) : son id est la clé d'idempotence qui fait qu'une note renvoyée après
 *    une réponse perdue n'est écrite qu'une fois.
 */
export type TypeMutation =
  | "punch_in"
  | "punch_out"
  | "job_status_change"
  | "materials_submit"
  | "materials_submit_with_proofs"
  | "checklist_step"
  | "incident_report"
  | "photo_upload"
  | "signature_capture"
  | "po_receive_scan"
  | "fichier_bloc"
  /** Reçu local durable des indices confirmés par `m4_etat_fichier`; jamais envoyé. */
  | "fichier_bloc_reconcilie"
  | "job_completion"
  | "gps_consent_change"
  | "approval_decision"
  /** Décision humaine M7 ; preuve locale dans payload JSON, args RPC projetés par son descripteur. */
  | "marketing_decision"
  /** Arbitrage humain M10 d’un signalement réel ; aucun acteur fourni dans le payload. */
  | "memory_revision_arbitration"
  | "lead_note";

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
  /**
   * La personne (`personnes.identifiant`, celle que le serveur a confirmée pour l'appareil) sous laquelle
   * cette mutation a été créée (PLAN T1.4-l) — posée UNE fois, à l'insertion, par `src/outbox/proprietaire.ts`,
   * puis jamais modifiée. La file sortante n'envoie une mutation que sous cette personne : après un nouvel
   * appairage pour quelqu'un d'autre, elle reste en file, en quarantaine visible, jamais supprimée ni
   * envoyée sous la nouvelle identité. `null` : propriétaire inconnu (ligne d'avant T1.4-l, ou mutation pas
   * encore insérée) — même traitement, fail-closed : jamais envoyée.
   */
  readonly proprietaire: string | null;
  /** Accusé métier conservé avec le statut terminal pour permettre la reprise hors écran. */
  readonly resumeAccepte?: unknown | null;
}
