// `expo-sqlite` est natif : absent de Jest. Ce test fait tourner le VRAI SQL de `depot.sqlite.ts` sur un
// moteur SQLite réel (`node:sqlite`, Node 22.5+, celui de la CI mobile) derrière la petite interface
// qu'`expo-sqlite` expose et que l'adaptateur utilise (`execAsync`, `getAllAsync`, `getFirstAsync`,
// `runAsync`). Il prouve le SQL et la migration ; il ne prouve PAS le pont natif d'`expo-sqlite`.
import { DatabaseSync } from "node:sqlite";

import type { SQLiteDatabase } from "expo-sqlite";

import { creerDepotOutboxSqlite, DDL_OUTBOX, initialiserSchemaOutbox } from "./depot.sqlite";
import { creerMutation, marquerEnvoi, soumettreMutation } from "./mutation";
import { avecProprietaire } from "./proprietaire";

type Parametres = (string | number | null)[];

function baseReelle(): { base: SQLiteDatabase; brute: DatabaseSync } {
  const brute = new DatabaseSync(":memory:");
  const base = {
    async execAsync(sql: string): Promise<void> {
      brute.exec(sql);
    },
    async getAllAsync<T>(sql: string, parametres: Parametres = []): Promise<T[]> {
      return brute.prepare(sql).all(...parametres) as T[];
    },
    async getFirstAsync<T>(sql: string, parametres: Parametres = []): Promise<T | null> {
      return (brute.prepare(sql).get(...parametres) as T | undefined) ?? null;
    },
    async runAsync(sql: string, parametres: Parametres = []): Promise<void> {
      brute.prepare(sql).run(...parametres);
    },
  };
  return { base: base as unknown as SQLiteDatabase, brute };
}

const HORLOGE = { maintenant: new Date("2026-09-29T12:00:00.000Z"), decalageMinutesUTC: -240 };
let compteur = 0;
const idDeterministe = () => `id-${++compteur}`;

beforeEach(() => {
  compteur = 0;
});

function nouvelleMutation() {
  return creerMutation({ type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } }, idDeterministe, HORLOGE);
}

function colonnes(brute: DatabaseSync): string[] {
  return (brute.prepare("PRAGMA table_info(outbox)").all() as { name: string }[]).map((c) => c.name);
}

/** La table telle qu'elle existait AVANT PLAN T1.4-l : sans `proprietaire`. */
const DDL_AVANT_T1_4_L = DDL_OUTBOX.replace(",\n  proprietaire TEXT", "");

describe("initialiserSchemaOutbox : la colonne proprietaire", () => {
  test("base neuve : la table naît avec la colonne proprietaire", async () => {
    const { base, brute } = baseReelle();
    await initialiserSchemaOutbox(base);
    expect(colonnes(brute)).toContain("proprietaire");
  });

  test("le gabarit d'avant T1.4-l n'a bien PAS la colonne (le test de migration teste ce qu'il croit tester)", () => {
    const { brute } = baseReelle();
    brute.exec(DDL_AVANT_T1_4_L);
    expect(colonnes(brute)).not.toContain("proprietaire");
  });

  test("base d'avant T1.4-l : la colonne est ajoutée, les lignes existantes sont gardées, propriétaire NULL", async () => {
    const { base, brute } = baseReelle();
    brute.exec(DDL_AVANT_T1_4_L);
    brute
      .prepare(
        `INSERT INTO outbox (id, sequence, type, chantier_id, payload, depends_on, statut, tentatives, created_at_local, prochaine_tentative_a)
         VALUES ('vieille', 1, 'punch_in', 'interv-1', '{"action":"arrivee"}', NULL, 'en_attente', 2, '2026-09-01T08:00:00-04:00', NULL)`,
      )
      .run();

    await initialiserSchemaOutbox(base);

    expect(colonnes(brute)).toContain("proprietaire");
    const lignes = await creerDepotOutboxSqlite(base).lister();
    expect(lignes).toHaveLength(1);
    expect(lignes[0]).toMatchObject({ id: "vieille", statut: "en_attente", tentatives: 2, proprietaire: null });
  });

  test("idempotent : un second démarrage ne casse rien et n'ajoute pas la colonne deux fois", async () => {
    const { base, brute } = baseReelle();
    brute.exec(DDL_AVANT_T1_4_L);
    await initialiserSchemaOutbox(base);
    await initialiserSchemaOutbox(base);
    expect(colonnes(brute).filter((nom) => nom === "proprietaire")).toHaveLength(1);
  });
});

describe("creerDepotOutboxSqlite : le propriétaire de chaque mutation", () => {
  test("inserer écrit le propriétaire, lister et obtenir le relisent, avec la sequence assignée par la base", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);

    const persistee = await depot.inserer({ ...nouvelleMutation(), proprietaire: "jdupont" });

    expect(persistee.sequence).toBe(1);
    expect(persistee.proprietaire).toBe("jdupont");
    expect((await depot.obtenir(persistee.id))?.proprietaire).toBe("jdupont");
    expect((await depot.lister())[0]).toEqual(persistee);
  });

  test("une mutation sans propriétaire est écrite avec NULL et relue null (jamais une chaîne vide ou un défaut)", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);

    const persistee = await depot.inserer(nouvelleMutation());

    expect(persistee.proprietaire).toBeNull();
    expect((await depot.obtenir(persistee.id))?.proprietaire).toBeNull();
  });

  test("mettreAJour change le statut mais jamais le propriétaire (même si la mutation passée en porte un autre)", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);
    const persistee = await depot.inserer({ ...nouvelleMutation(), proprietaire: "jdupont" });

    const enEnvoi = marquerEnvoi(soumettreMutation(persistee));
    await depot.mettreAJour({ ...enEnvoi, proprietaire: "mtremblay" });

    const relue = await depot.obtenir(persistee.id);
    expect(relue?.statut).toBe("envoi");
    expect(relue?.proprietaire).toBe("jdupont");
  });

  test("avec le dépôt de l'app (avecProprietaire) : la personne courante est posée à l'insertion, en base", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = avecProprietaire(creerDepotOutboxSqlite(base), () => "mtremblay");

    const persistee = await depot.inserer(nouvelleMutation());

    expect(persistee.proprietaire).toBe("mtremblay");
    expect((await creerDepotOutboxSqlite(base).obtenir(persistee.id))?.proprietaire).toBe("mtremblay");
  });

  test("la sequence croît d'une insertion à l'autre, quel que soit le propriétaire", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);

    const a = await depot.inserer({ ...nouvelleMutation(), proprietaire: "jdupont" });
    const b = await depot.inserer({ ...nouvelleMutation(), proprietaire: "mtremblay" });

    expect([a.sequence, b.sequence]).toEqual([1, 2]);
  });
});
