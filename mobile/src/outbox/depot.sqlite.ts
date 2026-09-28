import type { SQLiteDatabase } from "expo-sqlite";

import type { DepotOutbox } from "./depot";
import type { MutationOutbox, StatutMutation, TypeMutation } from "./types";

/**
 * DDL de la table `outbox` (R12 §4). `payload` est du JSON sérialisé (jamais de binaire — les
 * photos référencent un URI `expo-file-system` + un hachage, voir R12 §4 « Photos
 * volumineuses », hors périmètre de ce squelette). `depends_on` référence une autre ligne de
 * la même table.
 */
export const DDL_OUTBOX = `
CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY NOT NULL,
  type TEXT NOT NULL,
  chantier_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  depends_on TEXT REFERENCES outbox(id),
  statut TEXT NOT NULL,
  tentatives INTEGER NOT NULL DEFAULT 0,
  created_at_local TEXT NOT NULL
);
`.trim();

export async function initialiserSchemaOutbox(db: SQLiteDatabase): Promise<void> {
  await db.execAsync(DDL_OUTBOX);
}

interface LigneOutboxBrute {
  id: string;
  type: string;
  chantier_id: string;
  payload: string;
  depends_on: string | null;
  statut: string;
  tentatives: number;
  created_at_local: string;
}

function versMutation(ligne: LigneOutboxBrute): MutationOutbox {
  return {
    id: ligne.id,
    type: ligne.type as TypeMutation,
    chantierId: ligne.chantier_id,
    payload: JSON.parse(ligne.payload) as Record<string, unknown>,
    dependsOn: ligne.depends_on,
    statut: ligne.statut as StatutMutation,
    tentatives: ligne.tentatives,
    createdAtLocal: ligne.created_at_local,
  };
}

/**
 * Adaptateur `expo-sqlite` de `DepotOutbox` (R12 §4). Non exercé par les tests unitaires :
 * SQLite natif n'existe pas dans l'environnement Jest, et la logique elle-même est déjà
 * couverte à 100 % via `DepotOutboxMemoire` (mission T1.4-a item 4) — ce fichier ne fait que
 * la traduction SQL <-> `MutationOutbox`, appelable une fois un vrai appareil/simulateur
 * disponible (hors périmètre de ce squelette).
 */
export function creerDepotOutboxSqlite(db: SQLiteDatabase): DepotOutbox {
  return {
    async lister() {
      const lignes = await db.getAllAsync<LigneOutboxBrute>("SELECT * FROM outbox ORDER BY chantier_id, created_at_local");
      return lignes.map(versMutation);
    },

    async obtenir(id) {
      const ligne = await db.getFirstAsync<LigneOutboxBrute>("SELECT * FROM outbox WHERE id = ?", [id]);
      return ligne ? versMutation(ligne) : null;
    },

    async inserer(mutation) {
      await db.runAsync(
        `INSERT INTO outbox (id, type, chantier_id, payload, depends_on, statut, tentatives, created_at_local)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          mutation.id,
          mutation.type,
          mutation.chantierId,
          JSON.stringify(mutation.payload),
          mutation.dependsOn,
          mutation.statut,
          mutation.tentatives,
          mutation.createdAtLocal,
        ],
      );
    },

    async mettreAJour(mutation) {
      await db.runAsync(
        `UPDATE outbox
         SET type = ?, chantier_id = ?, payload = ?, depends_on = ?, statut = ?, tentatives = ?, created_at_local = ?
         WHERE id = ?`,
        [
          mutation.type,
          mutation.chantierId,
          JSON.stringify(mutation.payload),
          mutation.dependsOn,
          mutation.statut,
          mutation.tentatives,
          mutation.createdAtLocal,
          mutation.id,
        ],
      );
    },
  };
}
