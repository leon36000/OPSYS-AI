import type { SQLiteDatabase } from "expo-sqlite";

import type { DepotOutbox } from "./depot";
import type { MutationOutbox, StatutMutation, TypeMutation } from "./types";

/**
 * DDL de la table `outbox` (R12 §4). `payload` est du JSON sérialisé (jamais de binaire — les
 * photos référencent un URI `expo-file-system` + un hachage, voir R12 §4 « Photos
 * volumineuses », hors périmètre de ce squelette). `depends_on` référence une autre ligne de
 * la même table.
 *
 * `sequence` : entier strictement croissant assigné à l'insertion (voir `inserer` ci-dessous),
 * c'est lui qui fait foi pour l'ordre d'envoi — pas `created_at_local` (texte d'heure locale
 * avec décalage, mal comparable d'un décalage à l'autre). `id` (UUID) reste la clé primaire
 * (c'est elle qui sert d'`idempotencyKey`), `sequence` est une colonne ordinaire, calculée par
 * sous-requête plutôt que via `INTEGER PRIMARY KEY AUTOINCREMENT` (réservé à UNE seule colonne,
 * déjà prise par `id`) ; sûr en écrivain unique (l'app mobile), pas conçu pour des écritures
 * concurrentes.
 * `prochaine_tentative_a` : instant UTC avant lequel un renvoi ne doit pas être tenté (`NULL` =
 * due immédiatement) — posé par `marquerEchecReessayable` (src/outbox/mutation.ts).
 * `proprietaire` (PLAN T1.4-l) : la personne sous laquelle la mutation a été créée, posée à l'insertion
 * et jamais réécrite ; `NULL` pour une ligne d'avant cette colonne (voir `initialiserSchemaOutbox`).
 */
export const DDL_OUTBOX = `
CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY NOT NULL,
  sequence INTEGER NOT NULL,
  type TEXT NOT NULL,
  chantier_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  depends_on TEXT REFERENCES outbox(id),
  statut TEXT NOT NULL,
  tentatives INTEGER NOT NULL DEFAULT 0,
  created_at_local TEXT NOT NULL,
  prochaine_tentative_a TEXT,
  proprietaire TEXT
);
`.trim();

/**
 * Crée la table si elle manque, puis ajoute la colonne `proprietaire` à une table créée avant PLAN
 * T1.4-l (`CREATE TABLE IF NOT EXISTS` ne modifie jamais une table existante). Les lignes déjà là gardent
 * `NULL` : propriétaire inconnu, donc en quarantaine (jamais envoyées sous une identité devinée, jamais
 * supprimées). Idempotent : la colonne n'est ajoutée qu'une fois.
 */
export async function initialiserSchemaOutbox(db: SQLiteDatabase): Promise<void> {
  await db.execAsync(DDL_OUTBOX);
  const colonnes = await db.getAllAsync<{ name: string }>("PRAGMA table_info(outbox)");
  if (!colonnes.some((colonne) => colonne.name === "proprietaire")) {
    await db.execAsync("ALTER TABLE outbox ADD COLUMN proprietaire TEXT");
  }
}

interface LigneOutboxBrute {
  id: string;
  sequence: number;
  type: string;
  chantier_id: string;
  payload: string;
  depends_on: string | null;
  statut: string;
  tentatives: number;
  created_at_local: string;
  prochaine_tentative_a: string | null;
  proprietaire: string | null;
}

function versMutation(ligne: LigneOutboxBrute): MutationOutbox {
  return {
    id: ligne.id,
    sequence: ligne.sequence,
    type: ligne.type as TypeMutation,
    chantierId: ligne.chantier_id,
    payload: JSON.parse(ligne.payload) as Record<string, unknown>,
    dependsOn: ligne.depends_on,
    statut: ligne.statut as StatutMutation,
    tentatives: ligne.tentatives,
    createdAtLocal: ligne.created_at_local,
    prochaineTentativeA: ligne.prochaine_tentative_a,
    proprietaire: ligne.proprietaire,
  };
}

/**
 * Adaptateur `expo-sqlite` de `DepotOutbox` (R12 §4). SQLite natif n'existe pas dans l'environnement
 * Jest ; la logique est couverte via `DepotOutboxMemoire` (mission T1.4-a item 4) et, depuis PLAN
 * T1.4-l, le SQL lui-même l'est par `depot.sqlite.test.ts`, qui fait tourner CE fichier sur un vrai
 * moteur SQLite (`node:sqlite`) derrière la même petite interface — la migration de la colonne `proprietaire` en particulier. Reste hors
 * preuve : le pont natif d'`expo-sqlite` (appareil ou simulateur).
 */
export function creerDepotOutboxSqlite(db: SQLiteDatabase): DepotOutbox {
  return {
    async lister() {
      const lignes = await db.getAllAsync<LigneOutboxBrute>("SELECT * FROM outbox ORDER BY chantier_id, sequence");
      return lignes.map(versMutation);
    },

    async obtenir(id) {
      const ligne = await db.getFirstAsync<LigneOutboxBrute>("SELECT * FROM outbox WHERE id = ?", [id]);
      return ligne ? versMutation(ligne) : null;
    },

    async inserer(mutation) {
      // `sequence` est calculée dans la même instruction (sous-requête), jamais lue puis
      // réécrite séparément : pas de fenêtre entre "lire le max" et "insérer" où une autre
      // écriture pourrait glisser la même valeur (écrivain unique de toute façon, mais autant
      // rester correct). `RETURNING` (SQLite ≥ 3.35, libSQL d'expo-sqlite) renvoie la valeur
      // exacte assignée par la base, pas une valeur recalculée côté JS.
      const ligne = await db.getFirstAsync<{ sequence: number }>(
        `INSERT INTO outbox
           (id, sequence, type, chantier_id, payload, depends_on, statut, tentatives, created_at_local,
            prochaine_tentative_a, proprietaire)
         VALUES
           (?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM outbox), ?, ?, ?, ?, ?, ?, ?, ?, ?)
         RETURNING sequence`,
        [
          mutation.id,
          mutation.type,
          mutation.chantierId,
          JSON.stringify(mutation.payload),
          mutation.dependsOn,
          mutation.statut,
          mutation.tentatives,
          mutation.createdAtLocal,
          mutation.prochaineTentativeA,
          mutation.proprietaire,
        ],
      );
      if (!ligne) {
        throw new Error(`échec d'insertion dans outbox, aucune séquence retournée : ${mutation.id}`);
      }
      return { ...mutation, sequence: ligne.sequence };
    },

    async mettreAJour(mutation) {
      // `sequence` et `proprietaire` ne sont jamais réécrites ici : assignées une fois à l'insertion,
      // immuables ensuite (un statut qui change ne change pas à qui appartient la mutation).
      await db.runAsync(
        `UPDATE outbox
         SET type = ?, chantier_id = ?, payload = ?, depends_on = ?, statut = ?, tentatives = ?,
             created_at_local = ?, prochaine_tentative_a = ?
         WHERE id = ?`,
        [
          mutation.type,
          mutation.chantierId,
          JSON.stringify(mutation.payload),
          mutation.dependsOn,
          mutation.statut,
          mutation.tentatives,
          mutation.createdAtLocal,
          mutation.prochaineTentativeA,
          mutation.id,
        ],
      );
    },
  };
}
