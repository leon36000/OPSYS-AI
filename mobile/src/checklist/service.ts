import { ecrireChecklist, lireChecklist } from "./cache";
import type { ItemChecklist } from "./types";
import { obtenirDepotLocal } from "../stockage/service";

/** Câblage RÉEL (`expo-sqlite` via `src/stockage/service.ts`) — non exercé par les tests
 * unitaires, même limite que `src/outbox/service.ts` ; la logique (`logique.ts`) et la
 * sérialisation (`cache.ts`) sont, elles, testées intégralement. */
export async function chargerChecklist(chantierId: string): Promise<ItemChecklist[]> {
  return lireChecklist(await obtenirDepotLocal(), chantierId);
}

export async function sauvegarderChecklist(chantierId: string, items: readonly ItemChecklist[]): Promise<void> {
  await ecrireChecklist(await obtenirDepotLocal(), chantierId, items);
}
