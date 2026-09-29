import { obtenirStatutChantier, statutAffichable } from "./statut";
import type { ResultatStatutChantier } from "./statut";
import { ecrireCacheChantiers } from "./cache";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { invoquerOutil } from "../protocole/client";
import type { InterventionM4 } from "../m4/interventions";

const PERSONNE = "etienne";

function reponseHttp(status: number, corps: unknown, ok = status >= 200 && status < 300): Response {
  return { ok, status, json: async () => corps } as unknown as Response;
}

function reponseStatut(interventionId: string, statut: string | null): Response {
  return reponseHttp(200, { ok: true, result: { ok: true, resultat: { intervention_id: interventionId, statut } } });
}

function creerConfig(depot: DepotCleValeurMemoire, fetchImpl: typeof fetch, personne = PERSONNE) {
  return { depot, appelerOutil: invoquerOutil, fetchImpl, urlBase: "https://grs.exemple.ca", jeton: "jeton-test", personne };
}

const INTERVENTION_CACHE: InterventionM4 = {
  intervention_id: "I1",
  statut: "planifiee",
  lead_id: "L1",
  type_travaux: "gouttieres",
  devis_id: null,
};

async function depotAvecCache(): Promise<DepotCleValeurMemoire> {
  const depot = new DepotCleValeurMemoire();
  await ecrireCacheChantiers(depot, PERSONNE, { interventions: [INTERVENTION_CACHE], misAJourLe: "2026-09-28T08:00:00.000Z" });
  return depot;
}

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
    const depot = await depotAvecCache();
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

  test("le cache d'une AUTRE personne sur le même téléphone n'est jamais lu", async () => {
    const depot = await depotAvecCache();
    const fetchImpl = jest.fn().mockRejectedValueOnce(new TypeError("Network request failed"));
    const resultat = await obtenirStatutChantier(creerConfig(depot, fetchImpl as unknown as typeof fetch, "sophie"), "I1");
    expect(resultat.source).toBe("aucune");
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

describe("obtenirStatutChantier — un appareil refusé ne relit JAMAIS le statut gardé (PLAN T1.4-n)", () => {
  test.each([
    ["401 : jeton inconnu ou révoqué", 401, {}, "http_401"],
    ["403 : la porte d'appareil refuse", 403, { ok: false, error: { type: "tool_call_blocked", message: "device_unknown" } }, "tool_call_blocked"],
    ["403 sans le corps du core", 403, "interdit", "http_403"],
    ["400 du core", 400, { ok: false, error: { type: "invalid_request", message: "x" } }, "invalid_request"],
    ["404 du core", 404, { ok: false, error: { type: "not_found", message: "x" } }, "not_found"],
  ])("%s : refus, le cache n'est ni lu ni écrit", async (_nom, status, corps, code) => {
    const depot = await depotAvecCache();
    const lire = jest.spyOn(depot, "lire");
    const ecrire = jest.spyOn(depot, "ecrire");
    const resultat = await obtenirStatutChantier(
      creerConfig(depot, jest.fn(async () => reponseHttp(status, corps)) as unknown as typeof fetch),
      "I1",
    );
    expect(resultat).toMatchObject({ source: "refus", verdict: { code } });
    expect(lire).not.toHaveBeenCalled();
    expect(ecrire).not.toHaveBeenCalled();
  });

  test.each([
    ["l'identité que la base ne confirme plus", { ok: false, erreur: "refus_metier", details: "REJ-IDENTITE-APPAREIL-INVALIDE : personne inactive" }, "refus_metier"],
    ["l'outil hors de la portée du rôle", { ok: false, erreur: "hors_portee_role", details: "employee" }, "hors_portee_role"],
  ])("%s (refus technique, HTTP 200) : refus, jamais le statut gardé", async (_nom, technique, code) => {
    const depot = await depotAvecCache();
    const resultat = await obtenirStatutChantier(
      creerConfig(depot, jest.fn(async () => reponseHttp(200, { ok: true, result: technique })) as unknown as typeof fetch),
      "I1",
    );
    expect(resultat).toMatchObject({ source: "refus", verdict: { code } });
  });

  test.each([
    ["500", 500, { ok: false, error: { type: "tool_error", message: "panne" } }, "tool_error"],
    ["503", 503, {}, "http_503"],
    ["408", 408, {}, "http_408"],
    ["429", 429, {}, "http_429"],
    ["404 qui n'est pas du core (mandataire)", 404, "<html>", "http_404"],
  ])("HTTP %s : le serveur n'a pas pu répondre, le statut gardé est servi, marqué", async (_nom, status, corps, code) => {
    const depot = await depotAvecCache();
    const resultat = await obtenirStatutChantier(
      creerConfig(depot, jest.fn(async () => reponseHttp(status, corps)) as unknown as typeof fetch),
      "I1",
    );
    expect(resultat).toMatchObject({ source: "cache", statut: "planifiee", raisonHorsLigne: { code } });
  });

  test("l'état passager de l'instance (budget épuisé) n'est pas un refus : le statut gardé est servi", async () => {
    const depot = await depotAvecCache();
    const resultat = await obtenirStatutChantier(
      creerConfig(depot, jest.fn(async () => reponseHttp(200, { ok: true, result: { ok: false, erreur: "budget_epuise", details: "trop" } })) as unknown as typeof fetch),
      "I1",
    );
    expect(resultat).toMatchObject({ source: "cache", raisonHorsLigne: { code: "budget_epuise" } });
  });
});

describe("statutAffichable : le statut que l'écran peut montrer, et dont il dérive ses boutons", () => {
  const cas: readonly (readonly [string, ResultatStatutChantier | null, string | null])[] = [
    ["le serveur", { source: "serveur", statut: "sur_site" }, "sur_site"],
    ["le serveur, intervention inconnue", { source: "serveur", statut: null }, null],
    ["le cache marqué", { source: "cache", statut: "planifiee", raisonHorsLigne: { code: "erreur_reseau", detail: "" } }, "planifiee"],
    ["un refus : aucun statut, donc aucun bouton de transition", { source: "refus", verdict: { code: "http_401", detail: "" } }, null],
    ["rien de lu", { source: "aucune", raisonHorsLigne: { code: "erreur_reseau", detail: "" } }, null],
    ["aucune session", null, null],
  ];
  test.each(cas)("%s", (_nom, resultat, attendu) => {
    expect(statutAffichable(resultat)).toBe(attendu);
  });
});
