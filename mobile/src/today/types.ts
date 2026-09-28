import type { InterventionM4 } from "../m4/interventions";

/** Dernière liste reçue avec succès de `m4_lister_interventions`, avec l'horodatage de
 * réception — c'est CE cache (pas une copie filtrée) qui est persisté : le filtrage « chantiers
 * actifs » (`src/today/selection.ts`) reste appliqué à la lecture, jamais à l'écriture, pour ne
 * rien perdre si la définition de « actif » change un jour. */
export interface ChantiersCache {
  readonly interventions: readonly InterventionM4[];
  /** ISO 8601 UTC — horloge injectée par l'appelant (`src/today/orchestrateur.ts`), jamais lue
   * ici directement (mission item 5, testabilité). */
  readonly misAJourLe: string;
}
