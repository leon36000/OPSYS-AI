import { obtenirStatutChantier } from "./statut";
import { ecrireCacheChantiers } from "./cache";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { invoquerOutil } from "../protocole/client";
import type { InterventionM4 } from "../m4/interventions";

function reponseHttp(status: number, corps: unknown, ok = status >= 200 && status < 300): Response {
  return { ok, status, json: async () => corps } as unknown as Response;
}

function reponseStatut(interventionId: string, statut: string | null): Response {
  return reponseHttp(200, { ok: true, result: { ok: true, resultat: { intervention_id: interventionId, statut } } });
}

function creerConfig(depot: DepotCleValeurMemoire, fetchImpl: typeof fetch) {
  return { depot, appelerOutil: invoquerOutil, fetchImpl, urlBase: "https://grs.exemple.ca", jeton: "jeton-test" };
}

const INTERVENTION_CACHE: InterventionM4 = {
  intervention_id: "I1",
  statut: "planifiee",
  lead_id: "L1",
  type_travaux: "gouttieres",
  devis_id: null,
};

describe("obtenirStatutChantier", () => {
  test("en ligne : source serveur", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseStatut("I1", "sur_site"));
    const resultat = await obtenirStatutChantier(creerConfig(depot, fetchImpl as unknown as typeof fetch), "I1");
    expect(resultat).toEqual({ source: "serveur", statut: "sur_site" });
  });

  test("intervention inconnue côté serveur (statut null) N'EST PAS un échec", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseStatut("I-inconnue", null));
    const resultat = await obtenirStatutChantier(creerConfig(depot, fetchImpl as unknown as typeof fetch), "I-inconnue");
    expect(resultat).toEqual({ source: "serveur", statut: null });
  });

  test("hors ligne avec ce chantier dans le cache de today.tsx : source cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheChantiers(depot, { interventions: [INTERVENTION_CACHE], misAJourLe: "2026-09-28T08:00:00.000Z" });
    const fetchImpl = jest.fn().mockRejectedValueOnce(new TypeError("Network request failed"));
    const resultat = await obtenirStatutChantier(creerConfig(depot, fetchImpl as unknown as typeof fetch), "I1");
    expect(resultat).toEqual({
      source: "cache",
      statut: "planifiee",
      raisonHorsLigne: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });

  test("hors ligne sans ce chantier en cache : source aucune", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = jest.fn().mockRejectedValueOnce(new TypeError("Network request failed"));
    const resultat = await obtenirStatutChantier(creerConfig(depot, fetchImpl as unknown as typeof fetch), "I1");
    expect(resultat).toEqual({
      source: "aucune",
      raisonHorsLigne: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });

  test("appelle le bon outil avec le bon intervention_id", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseStatut("I1", "planifiee"));
    await obtenirStatutChantier(creerConfig(depot, fetchImpl as unknown as typeof fetch), "I1");
    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    const corps = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(corps.tool).toBe("m4_statut_intervention");
    expect(corps.args).toEqual({ intervention_id: "I1" });
  });
});
