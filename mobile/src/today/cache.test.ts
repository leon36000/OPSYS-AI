import { ecrireCacheChantiers, lireCacheChantiers, lireInterventionEnCache } from "./cache";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { ChantiersCache } from "./types";

const PERSONNE = "etienne";
const CLE = "employe:etienne:chantiers_v1";

const CACHE_VALIDE: ChantiersCache = {
  interventions: [
    { intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "gouttieres", devis_id: null },
  ],
  misAJourLe: "2026-09-28T12:00:00.000Z",
};

describe("lireCacheChantiers / ecrireCacheChantiers", () => {
  test("aller-retour : ce qui est écrit est ce qui est relu", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, PERSONNE, CACHE_VALIDE);
    expect(await lireCacheChantiers(depot, PERSONNE)).toEqual(CACHE_VALIDE);
  });

  test("UNE CLÉ PAR PERSONNE : `employe:<personne>:chantiers_v1`, la personne encodée", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, PERSONNE, CACHE_VALIDE);
    await ecrireCacheChantiers(depot, "a:b c", CACHE_VALIDE);
    expect(depot.cles()).toEqual(["employe:a%3Ab%20c:chantiers_v1", CLE]);
  });

  test("le cache d'une AUTRE personne sur le même téléphone n'est jamais relu", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, PERSONNE, CACHE_VALIDE);
    expect(await lireCacheChantiers(depot, "sophie")).toBeNull();
    expect(await lireInterventionEnCache(depot, "sophie", "I1")).toBeNull();
  });

  test("la clé d'avant T1.4-n (une seule pour tout l'appareil, sans personne) n'est plus jamais relue", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("today_chantiers_v1", JSON.stringify(CACHE_VALIDE));
    expect(await lireCacheChantiers(depot, PERSONNE)).toBeNull();
    expect(await lireInterventionEnCache(depot, PERSONNE, "I1")).toBeNull();
  });

  test("aucun cache encore écrit -> null, jamais un cache inventé", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await lireCacheChantiers(depot, PERSONNE)).toBeNull();
  });

  test("valeur corrompue (JSON invalide) -> null, fail-closed", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(CLE, "{ceci n'est pas du JSON");
    expect(await lireCacheChantiers(depot, PERSONNE)).toBeNull();
  });

  test("forme reconnaissable mais invalide (intervention mal formée) -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(CLE, JSON.stringify({ interventions: [{ intervention_id: "I1" }], misAJourLe: "2026-09-28T12:00:00.000Z" }));
    expect(await lireCacheChantiers(depot, PERSONNE)).toBeNull();
  });

  test("misAJourLe manquant -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(CLE, JSON.stringify({ interventions: [] }));
    expect(await lireCacheChantiers(depot, PERSONNE)).toBeNull();
  });

  test("une seconde écriture remplace entièrement la précédente", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, PERSONNE, CACHE_VALIDE);
    const nouveau: ChantiersCache = { interventions: [], misAJourLe: "2026-09-28T13:00:00.000Z" };
    await ecrireCacheChantiers(depot, PERSONNE, nouveau);
    expect(await lireCacheChantiers(depot, PERSONNE)).toEqual(nouveau);
  });
});

describe("lireInterventionEnCache", () => {
  test("trouve l'intervention par id dans le dernier cache écrit pour cette personne", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, PERSONNE, CACHE_VALIDE);
    expect(await lireInterventionEnCache(depot, PERSONNE, "I1")).toEqual(CACHE_VALIDE.interventions[0]);
  });

  test("id absent du cache -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, PERSONNE, CACHE_VALIDE);
    expect(await lireInterventionEnCache(depot, PERSONNE, "I-inconnue")).toBeNull();
  });

  test("aucun cache -> null", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await lireInterventionEnCache(depot, PERSONNE, "I1")).toBeNull();
  });
});
