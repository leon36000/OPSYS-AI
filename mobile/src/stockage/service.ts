import * as SQLite from "expo-sqlite";

import { creerDepotCleValeurSqlite, initialiserSchemaCleValeur } from "./depotCleValeur.sqlite";
import type { DepotCleValeur } from "./depotCleValeur";

/**
 * Câblage RÉEL du dépôt clé/valeur partagé (`expo-sqlite`, base SÉPARÉE de la file sortante —
 * `opsys-local.db` plutôt que `opsys-outbox.db` : cache de lecture et brouillons d'écran n'ont
 * aucune raison de partager la base de la file de mutations serveur). Non exercé par les tests
 * unitaires, même limite que `src/outbox/service.ts`.
 */
const NOM_BASE = "opsys-local.db";

let depotPromesse: Promise<DepotCleValeur> | null = null;

export function obtenirDepotLocal(): Promise<DepotCleValeur> {
  if (!depotPromesse) {
    depotPromesse = (async () => {
      const base = await SQLite.openDatabaseAsync(NOM_BASE);
      await initialiserSchemaCleValeur(base);
      return creerDepotCleValeurSqlite(base);
    })();
  }
  return depotPromesse;
}
