import { ecrireWctIdCompletion, lireWctIdCompletion } from "./wctIdCompletion";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";

describe("lireWctIdCompletion / ecrireWctIdCompletion", () => {
  test("rien de mémorisé -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await lireWctIdCompletion(depot, "I1")).toBeNull();
  });

  test("écriture puis lecture -> le même wct_id", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireWctIdCompletion(depot, "I1", "W1");
    expect(await lireWctIdCompletion(depot, "I1")).toBe("W1");
  });

  test("ne garde qu'un identifiant : aucune copie du WCT n'est écrite au dépôt", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireWctIdCompletion(depot, "I1", "W1");
    expect(await depot.lire("wct_id_I1_v1")).toBe("W1");
    // L'ancienne clé, qui portait le WCT complet en JSON, n'est ni écrite ni lue.
    expect(await depot.lire("wct_I1_v1")).toBeNull();
  });

  test("un chantier ne voit jamais le wct_id d'un autre", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireWctIdCompletion(depot, "I1", "W1");
    expect(await lireWctIdCompletion(depot, "I2")).toBeNull();
  });

  test("une valeur vide en dépôt -> null, jamais un identifiant deviné", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("wct_id_I1_v1", "");
    expect(await lireWctIdCompletion(depot, "I1")).toBeNull();
  });

  test("un ancien WCT en cache (ancienne clé) n'est jamais pris pour un wct_id", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("wct_I1_v1", JSON.stringify({ wct_id: "W-ancien", intervention_id: "I1" }));
    expect(await lireWctIdCompletion(depot, "I1")).toBeNull();
  });

  test("une nouvelle écriture remplace l'ancienne, jamais une fusion", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireWctIdCompletion(depot, "I1", "W1");
    await ecrireWctIdCompletion(depot, "I1", "W2");
    expect(await lireWctIdCompletion(depot, "I1")).toBe("W2");
  });
});
