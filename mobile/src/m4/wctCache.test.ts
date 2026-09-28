import { ecrireWctEnCache, lireWctEnCache } from "./wctCache";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { WctRecuM4 } from "./completion";

const WCT: WctRecuM4 = {
  wct_id: "W1",
  intervention_id: "I1",
  lead_id: "L1",
  technicien_id: "T1",
  horodatage_completion: "2026-09-28T14:00:00-04:00",
  statut: "completed_pending_review",
};

describe("lireWctEnCache / ecrireWctEnCache", () => {
  test("rien en cache -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await lireWctEnCache(depot, "I1")).toBeNull();
  });

  test("écriture puis lecture -> le même WCT, tous les champs préservés", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireWctEnCache(depot, "I1", WCT);
    expect(await lireWctEnCache(depot, "I1")).toEqual(WCT);
  });

  test("un chantier ne voit jamais le WCT d'un autre", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireWctEnCache(depot, "I1", WCT);
    expect(await lireWctEnCache(depot, "I2")).toBeNull();
  });

  test("valeur corrompue en dépôt -> null, jamais un WCT deviné", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("wct_I1_v1", "{ceci n'est pas du JSON");
    expect(await lireWctEnCache(depot, "I1")).toBeNull();
  });

  test("valeur JSON valide mais sans wct_id/intervention_id -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("wct_I1_v1", JSON.stringify({ statut: "completed_pending_review" }));
    expect(await lireWctEnCache(depot, "I1")).toBeNull();
  });

  test("une nouvelle écriture remplace l'ancienne, jamais une fusion", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireWctEnCache(depot, "I1", WCT);
    const autre: WctRecuM4 = { ...WCT, wct_id: "W2", statut: "completed_verified" };
    await ecrireWctEnCache(depot, "I1", autre);
    expect(await lireWctEnCache(depot, "I1")).toEqual(autre);
  });
});
