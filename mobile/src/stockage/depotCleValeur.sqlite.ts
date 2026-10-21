import type { SQLiteDatabase } from "expo-sqlite";

import { ERREUR_PREFIXE_VIDE } from "./depotCleValeur";
import type { DepotCleValeur } from "./depotCleValeur";

/** DDL de la table `cle_valeur` — voir `depotCleValeur.ts` pour le rôle et les clés utilisées
 * (`src/today/cache.ts`, `src/checklist/cache.ts`). */
export const DDL_CLE_VALEUR = `
CREATE TABLE IF NOT EXISTS cle_valeur (
  cle TEXT PRIMARY KEY NOT NULL,
  valeur TEXT NOT NULL
);
`.trim();

export async function initialiserSchemaCleValeur(db: SQLiteDatabase): Promise<void> {
  await db.execAsync(DDL_CLE_VALEUR);
}

/**
 * Adaptateur `expo-sqlite` de `DepotCleValeur`. Non exercé par les tests unitaires (pas de
 * SQLite natif sous Jest, même limite que `src/outbox/depot.sqlite.ts`) : la logique elle-même
 * (sérialisation JSON, décisions de cache) est testée via `DepotCleValeurMemoire`. Le SQL, lui, est exercé sur un vrai
 * moteur (`node:sqlite`) par `depotCleValeur.sqlite.test.ts` ; le pont natif reste à vérifier sur appareil.
 */
export function creerDepotCleValeurSqlite(db: SQLiteDatabase): DepotCleValeur {
  return {
    async lire(cle) {
      const ligne = await db.getFirstAsync<{ valeur: string }>("SELECT valeur FROM cle_valeur WHERE cle = ?", [cle]);
      return ligne ? ligne.valeur : null;
    },

    async ecrire(cle, valeur) {
      await db.runAsync(
        "INSERT INTO cle_valeur (cle, valeur) VALUES (?, ?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        [cle, valeur],
      );
    },

    async supprimer(cle) {
      await db.runAsync("DELETE FROM cle_valeur WHERE cle = ?", [cle]);
    },

    async supprimerParPrefixe(prefixe) {
      if (prefixe === "") {
        throw new Error(ERREUR_PREFIXE_VIDE);
      }
      // `instr(cle, prefixe) = 1` : la première occurrence du préfixe est au tout début. Pas de `LIKE` : `_` et `%`
      // seraient des jokers, et les clés en contiennent (`_v1`).
      await db.runAsync("DELETE FROM cle_valeur WHERE instr(cle, ?) = 1", [prefixe]);
    },
  };
}
