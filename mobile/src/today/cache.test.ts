import { ecrireCacheChantiers, lireCacheChantiers, lireInterventionEnCache } from "./cache";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { ChantiersCache } from "./types";

const CACHE_VALIDE: ChantiersCache = {
  interventions: [
    { intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "gouttieres", devis_id: null },
  ],
  misAJourLe: "2026-09-28T12:00:00.000Z",
};

describe("lireCacheChantiers / ecrireCacheChantiers", () => {
  test("aller-retour : ce qui est écrit est ce qui est relu", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, CACHE_VALIDE);
    expect(await lireCacheChantiers(depot)).toEqual(CACHE_VALIDE);
  });

  test("aucun cache encore écrit -> null, jamais un cache inventé", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await lireCacheChantiers(depot)).toBeNull();
  });

  test("valeur corrompue (JSON invalide) -> null, fail-closed", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("today_chantiers_v1", "{ceci n'est pas du JSON");
    expect(await lireCacheChantiers(depot)).toBeNull();
  });

  test("forme reconnaissable mais invalide (intervention mal formée) -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(
      "today_chantiers_v1",
      JSON.stringify({ interventions: [{ intervention_id: "I1" }], misAJourLe: "2026-09-28T12:00:00.000Z" }),
    );
    expect(await lireCacheChantiers(depot)).toBeNull();
  });

  test("misAJourLe manquant -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("today_chantiers_v1", JSON.stringify({ interventions: [] }));
    expect(await lireCacheChantiers(depot)).toBeNull();
  });

  test("une seconde écriture remplace entièrement la précédente", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, CACHE_VALIDE);
    const nouveau: ChantiersCache = { interventions: [], misAJourLe: "2026-09-28T13:00:00.000Z" };
    await ecrireCacheChantiers(depot, nouveau);
    expect(await lireCacheChantiers(depot)).toEqual(nouveau);
  });
});

describe("lireInterventionEnCache", () => {
  test("trouve l'intervention par id dans le dernier cache écrit", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, CACHE_VALIDE);
    expect(await lireInterventionEnCache(depot, "I1")).toEqual(CACHE_VALIDE.interventions[0]);
  });

  test("id absent du cache -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, CACHE_VALIDE);
    expect(await lireInterventionEnCache(depot, "I-inconnue")).toBeNull();
  });

  test("aucun cache -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await lireInterventionEnCache(depot, "I1")).toBeNull();
  });
});
