import type { InterventionM4 } from "../m4/interventions";

/** Dernière liste reçue avec succès de `m4_lister_interventions`, avec l'horodatage de
 * réception — c'est CE cache (pas une copie filtrée par le tri d'affichage) qui est persisté : les statuts lus sont
 * ceux de `ETATS_ACTIFS_AUJOURDHUI` (`src/today/selection.ts`), un appel chacun (`src/today/orchestrateur.ts`), et le
 * tri « chantiers actifs » reste appliqué à la lecture, jamais à l'écriture. Une lecture tronquée ou incomplète
 * n'écrit jamais ce cache. */
export interface ChantiersCache {
  readonly interventions: readonly InterventionM4[];
  /** ISO 8601 UTC — horloge injectée par l'appelant (`src/today/orchestrateur.ts`), jamais lue
   * ici directement (mission item 5, testabilité). */
  readonly misAJourLe: string;
}
