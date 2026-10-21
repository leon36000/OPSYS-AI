// `expo-sqlite` est natif : absent de Jest. Ce test fait tourner le VRAI SQL de `depotCleValeur.sqlite.ts` sur un moteur
// SQLite réel (`node:sqlite`, Node 22.5+, celui de la CI mobile) derrière la petite interface qu'`expo-sqlite` expose et que
// l'adaptateur utilise (`execAsync`, `getFirstAsync`, `runAsync`). Il prouve le SQL, en particulier l'effacement par
// préfixe (PLAN T1.4-n) ; il ne prouve PAS le pont natif d'`expo-sqlite`. Même patron que `outbox/depot.sqlite.test.ts`.
import { DatabaseSync } from "node:sqlite";

import type { SQLiteDatabase } from "expo-sqlite";

import { ERREUR_PREFIXE_VIDE } from "./depotCleValeur";
import type { DepotCleValeur } from "./depotCleValeur";
import { creerDepotCleValeurSqlite, DDL_CLE_VALEUR, initialiserSchemaCleValeur } from "./depotCleValeur.sqlite";

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

async function depotNeuf(): Promise<{ depot: DepotCleValeur; cles: () => string[] }> {
  const { base, brute } = baseReelle();
  await initialiserSchemaCleValeur(base);
  return {
    depot: creerDepotCleValeurSqlite(base),
    cles: () => (brute.prepare("SELECT cle FROM cle_valeur ORDER BY cle").all() as { cle: string }[]).map((ligne) => ligne.cle),
  };
}

describe("creerDepotCleValeurSqlite (SQL réel)", () => {
  test("le schéma est celui du dépôt : une table cle_valeur (cle, valeur)", () => {
    expect(DDL_CLE_VALEUR).toContain("cle TEXT PRIMARY KEY NOT NULL");
  });

  test("écrit, relit, remplace", async () => {
    const { depot } = await depotNeuf();
    expect(await depot.lire("a")).toBeNull();
    await depot.ecrire("a", "1");
    await depot.ecrire("a", "2");
    expect(await depot.lire("a")).toBe("2");
  });

  test("supprimer efface UNE clé ; une clé absente n'est pas une erreur", async () => {
    const { depot, cles } = await depotNeuf();
    await depot.ecrire("a", "1");
    await depot.ecrire("ab", "2");
    await depot.supprimer("a");
    await depot.supprimer("absente");
    expect(cles()).toEqual(["ab"]);
  });

  test("supprimerParPrefixe efface les clés qui COMMENCENT par le préfixe, et elles seules", async () => {
    const { depot, cles } = await depotNeuf();
    for (const cle of ["admin:nathan:a_v1", "admin:sophie:b_v1", "vendeur:admin:x", "xadmin:y", "admin", "checklist_c1_v1", "Admin:z"]) {
      await depot.ecrire(cle, "v");
    }
    await depot.supprimerParPrefixe("admin:");
    expect(cles()).toEqual(["Admin:z", "admin", "checklist_c1_v1", "vendeur:admin:x", "xadmin:y"]);
  });

  test("`_` et `%` sont des caractères, pas des jokers (les clés en contiennent : `_v1`)", async () => {
    const { depot, cles } = await depotNeuf();
    for (const cle of ["a_b:1", "axb:2", "a%b:3", "azzb:4", "a%:5"]) {
      await depot.ecrire(cle, "v");
    }
    await depot.supprimerParPrefixe("a_b");
    expect(cles()).toEqual(["a%:5", "a%b:3", "axb:2", "azzb:4"]);
    await depot.supprimerParPrefixe("a%");
    expect(cles()).toEqual(["axb:2", "azzb:4"]);
  });

  test("un préfixe qui apparaît PLUS LOIN dans la clé, ou après une première occurrence différente, n'efface pas", async () => {
    const { depot, cles } = await depotNeuf();
    await depot.ecrire("zadmin:x", "v"); // le préfixe apparaît en 2e position
    await depot.ecrire("admin:x:admin:y", "v"); // il commence ET se répète
    await depot.supprimerParPrefixe("admin:");
    expect(cles()).toEqual(["zadmin:x"]);
  });

  test("les personnes à accents et à symboles (clé encodée ou non) s'effacent par leur préfixe", async () => {
    const { depot, cles } = await depotNeuf();
    await depot.ecrire("employe:%C3%89tienne:chantiers_v1", "v");
    await depot.ecrire("employe:étienne:chantiers_v1", "v");
    await depot.ecrire("autre:x", "v");
    await depot.supprimerParPrefixe("employe:");
    expect(cles()).toEqual(["autre:x"]);
  });

  test("un préfixe VIDE est refusé avant tout SQL : il effacerait tout le dépôt", async () => {
    const { depot, cles } = await depotNeuf();
    await depot.ecrire("checklist_c1_v1", "[]");
    await expect(depot.supprimerParPrefixe("")).rejects.toThrow(ERREUR_PREFIXE_VIDE);
    expect(cles()).toEqual(["checklist_c1_v1"]);
  });
});
