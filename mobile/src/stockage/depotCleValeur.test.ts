import { DepotCleValeurMemoire, ERREUR_PREFIXE_VIDE } from "./depotCleValeur";

describe("DepotCleValeurMemoire", () => {
  test("écrit, relit, remplace", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await depot.lire("a")).toBeNull();
    await depot.ecrire("a", "1");
    expect(await depot.lire("a")).toBe("1");
    await depot.ecrire("a", "2");
    expect(await depot.lire("a")).toBe("2");
  });

  test("supprimer efface UNE clé ; une clé absente n'est pas une erreur", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("a", "1");
    await depot.ecrire("ab", "2");
    await depot.supprimer("a");
    await depot.supprimer("absente");
    expect(depot.cles()).toEqual(["ab"]);
  });

  test("supprimerParPrefixe efface les clés qui COMMENCENT par le préfixe, et elles seules", async () => {
    const depot = new DepotCleValeurMemoire();
    for (const cle of ["admin:nathan:a_v1", "admin:sophie:b_v1", "vendeur:admin:x", "xadmin:y", "admin", "checklist_c1_v1", "Admin:z"]) {
      await depot.ecrire(cle, "v");
    }
    await depot.supprimerParPrefixe("admin:");
    // « vendeur:admin:x » et « xadmin:y » CONTIENNENT le préfixe sans le commencer ; « admin » et « Admin:z » ne l'ont pas.
    expect(depot.cles()).toEqual(["Admin:z", "admin", "checklist_c1_v1", "vendeur:admin:x", "xadmin:y"]);
  });

  test("un préfixe qui est une clé entière efface cette clé (et celles qui la prolongent)", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("k", "1");
    await depot.ecrire("k2", "2");
    await depot.ecrire("autre", "3");
    await depot.supprimerParPrefixe("k");
    expect(depot.cles()).toEqual(["autre"]);
  });

  test("un préfixe qui ne correspond à rien n'efface rien", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("a", "1");
    await depot.supprimerParPrefixe("zzz");
    expect(depot.cles()).toEqual(["a"]);
  });

  test("un préfixe VIDE est refusé : il effacerait tout le dépôt, checklists et identifiants de complétion compris", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("checklist_c1_v1", "[]");
    await expect(depot.supprimerParPrefixe("")).rejects.toThrow(ERREUR_PREFIXE_VIDE);
    expect(depot.cles()).toEqual(["checklist_c1_v1"]);
  });

  test("cles() rend les clés triées, jamais les valeurs", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("b", "secret");
    await depot.ecrire("a", "secret");
    expect(depot.cles()).toEqual(["a", "b"]);
  });
});
