import { creerChargeurChantiers } from "./orchestrateur";
import type { ResultatChargementChantiers } from "./orchestrateur";
import { ecrireCacheChantiers, lireCacheChantiers } from "./cache";
import { ETATS_ACTIFS_AUJOURDHUI } from "./selection";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { invoquerOutil } from "../protocole/client";
import type { InterventionM4, StatutInterventionM4 } from "../m4/interventions";

const PERSONNE = "etienne";
const MAINTENANT = () => new Date("2026-09-28T12:00:00.000Z");
const CLE_CACHE = "employe:etienne:chantiers_v1";

/** Même patron que src/outbox/vidangeur.test.ts. */
function reponseHttp(status: number, corps: unknown, ok = status >= 200 && status < 300): Response {
  return { ok, status, json: async () => corps } as unknown as Response;
}

function reponseListe(interventions: readonly InterventionM4[]): Response {
  return reponseHttp(200, { ok: true, result: { ok: true, resultat: interventions } });
}

function intervention(id: string, statut: StatutInterventionM4, surcharges: Partial<InterventionM4> = {}): InterventionM4 {
  return { intervention_id: id, statut, lead_id: `L-${id}`, type_travaux: "gouttieres", devis_id: null, ...surcharges };
}

const I_PLANIFIEE = intervention("I1", "planifiee");
const I_EN_ROUTE = intervention("I3", "en_route");
const I_SUR_SITE = intervention("I4", "sur_site");
const I_TERMINEE = intervention("I2", "completed_verified");

/** Un serveur : la liste du statut demandé (le serveur filtre par statut), rien d'autre. */
function serveur(parStatut: Partial<Record<StatutInterventionM4, readonly InterventionM4[]>>, surcharge?: (statut: string) => Response | undefined) {
  return jest.fn(async (_url: string, init: RequestInit) => {
    const corps = JSON.parse(init.body as string) as { tool: string; args: { statut: StatutInterventionM4 } };
    return surcharge?.(corps.args.statut) ?? reponseListe(parStatut[corps.args.statut] ?? []);
  });
}

function chargeur(depot: DepotCleValeurMemoire, fetchImpl: jest.Mock, personne = PERSONNE) {
  return creerChargeurChantiers({
    depot,
    appelerOutil: invoquerOutil,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-test",
    personne,
    maintenant: MAINTENANT,
  });
}

const CACHE_D_AVANT = {
  interventions: [I_PLANIFIEE, I_EN_ROUTE],
  misAJourLe: "2026-09-28T08:00:00.000Z",
};

async function depotAvecCache(): Promise<DepotCleValeurMemoire> {
  const depot = new DepotCleValeurMemoire();
  await ecrireCacheChantiers(depot, PERSONNE, CACHE_D_AVANT);
  return depot;
}

const TRONQUEE = () => reponseHttp(200, { ok: true, result: { ok: true, tronque: true, apercu: '[{"intervention_id": "I' } });

describe("chargerChantiersAujourdhui — en ligne", () => {
  test("un appel par statut actif, dans l'ordre, sans rien d'autre : jamais l'historique, jamais une personne", async () => {
    const fetchImpl = serveur({ planifiee: [I_PLANIFIEE], en_route: [I_EN_ROUTE], completed_verified: [I_TERMINEE] });
    await chargeur(new DepotCleValeurMemoire(), fetchImpl).chargerChantiersAujourdhui();

    const requetes = fetchImpl.mock.calls.map((appel) => JSON.parse(appel[1].body as string) as Record<string, unknown>);
    expect(requetes).toEqual([
      { tool: "m4_lister_interventions", args: { statut: "en_route" } },
      { tool: "m4_lister_interventions", args: { statut: "sur_site" } },
      { tool: "m4_lister_interventions", args: { statut: "en_revue" } },
      { tool: "m4_lister_interventions", args: { statut: "planifiee" } },
    ]);
    expect(requetes.map((r) => (r.args as { statut: string }).statut)).toEqual([...ETATS_ACTIFS_AUJOURDHUI]);
    expect(JSON.stringify(requetes)).not.toContain(PERSONNE);
    expect(JSON.stringify(requetes)).not.toContain("completed");
  });

  test("succès : source serveur, les quatre groupes réunis et triés par urgence, cache écrit sous la personne", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = serveur({ planifiee: [I_PLANIFIEE], en_route: [I_EN_ROUTE], sur_site: [I_SUR_SITE] });

    const resultat = await chargeur(depot, fetchImpl).chargerChantiersAujourdhui();

    expect(resultat).toEqual({
      source: "serveur",
      items: [I_EN_ROUTE, I_SUR_SITE, I_PLANIFIEE],
      misAJourLe: "2026-09-28T12:00:00.000Z",
    });
    expect(depot.cles()).toEqual([CLE_CACHE]);
    expect((await lireCacheChantiers(depot, PERSONNE))?.interventions.map((i) => i.intervention_id).sort()).toEqual(["I1", "I3", "I4"]);
  });

  test("le cache garde ce qui a été demandé : les quatre statuts actifs, jamais un historique", async () => {
    const depot = new DepotCleValeurMemoire();
    // Un serveur qui ignorerait le filtre et rendrait tout : l'historique ne se retrouve pas montré.
    const tout = [I_PLANIFIEE, I_EN_ROUTE, I_TERMINEE];
    const resultat = await chargeur(depot, jest.fn(async () => reponseListe(tout))).chargerChantiersAujourdhui();
    expect(resultat.source === "serveur" && resultat.items.map((i) => i.intervention_id)).toEqual(["I3", "I1"]);
  });

  test("une intervention rendue deux fois (le serveur ignore le filtre) n'apparaît qu'une fois", async () => {
    const resultat = await chargeur(new DepotCleValeurMemoire(), jest.fn(async () => reponseListe([I_PLANIFIEE, I_EN_ROUTE]))).chargerChantiersAujourdhui();
    expect(resultat.source === "serveur" && resultat.items).toEqual([I_EN_ROUTE, I_PLANIFIEE]);
  });

  test("une liste vide LUE EN ENTIER est une liste vide : le serveur dit qu'il n'y a rien, le cache vide s'écrit", async () => {
    const depot = await depotAvecCache();
    const resultat = await chargeur(depot, serveur({})).chargerChantiersAujourdhui();
    expect(resultat).toEqual({ source: "serveur", items: [], misAJourLe: "2026-09-28T12:00:00.000Z" });
    expect(await lireCacheChantiers(depot, PERSONNE)).toEqual({ interventions: [], misAJourLe: "2026-09-28T12:00:00.000Z" });
  });

  test("une nouvelle réussite après un échec remplace le cache, pas une fusion", async () => {
    const depot = await depotAvecCache();
    await chargeur(depot, serveur({ planifiee: [I_PLANIFIEE] })).chargerChantiersAujourdhui();
    expect((await lireCacheChantiers(depot, PERSONNE))?.interventions).toEqual([I_PLANIFIEE]);
  });

  test("le cache est celui de la personne : un autre employé sur le même téléphone a le sien", async () => {
    const depot = new DepotCleValeurMemoire();
    await chargeur(depot, serveur({ planifiee: [I_PLANIFIEE] })).chargerChantiersAujourdhui();
    await chargeur(depot, serveur({ en_route: [I_EN_ROUTE] }), "sophie").chargerChantiersAujourdhui();
    expect(depot.cles()).toEqual([CLE_CACHE, "employe:sophie:chantiers_v1"]);
    expect((await lireCacheChantiers(depot, PERSONNE))?.interventions).toEqual([I_PLANIFIEE]);
    expect((await lireCacheChantiers(depot, "sophie"))?.interventions).toEqual([I_EN_ROUTE]);
  });
});

describe("chargerChantiersAujourdhui — une réponse tronquée n'est ni une liste vide ni une liste complète (PLAN T1.4-n)", () => {
  test("un statut tronqué : « incomplet », ce qui a été lu en entier, jamais le cache écrasé", async () => {
    const depot = await depotAvecCache();
    const avant = await depot.lire(CLE_CACHE);
    const ecrire = jest.spyOn(depot, "ecrire");
    const fetchImpl = serveur({ en_route: [I_EN_ROUTE], sur_site: [I_SUR_SITE] }, (statut) => (statut === "planifiee" ? TRONQUEE() : undefined));

    const resultat = await chargeur(depot, fetchImpl).chargerChantiersAujourdhui();

    expect(resultat).toEqual({
      source: "incomplet",
      items: [I_EN_ROUTE, I_SUR_SITE],
      groupesIncomplets: ["planifiee"],
      misAJourLe: "2026-09-28T12:00:00.000Z",
    });
    expect(ecrire).not.toHaveBeenCalled();
    expect(await depot.lire(CLE_CACHE)).toBe(avant);
  });

  test("tous les statuts tronqués : « incomplet » SANS chantier, jamais « serveur » avec une liste vide", async () => {
    const depot = await depotAvecCache();
    const avant = await depot.lire(CLE_CACHE);

    const resultat = await chargeur(depot, jest.fn(async () => TRONQUEE())).chargerChantiersAujourdhui();

    expect(resultat).toEqual({
      source: "incomplet",
      items: [],
      groupesIncomplets: ["en_route", "sur_site", "en_revue", "planifiee"],
      misAJourLe: "2026-09-28T12:00:00.000Z",
    });
    expect(await depot.lire(CLE_CACHE)).toBe(avant);
  });

  test("tronqué SANS cache : rien n'est écrit non plus (aucun cache vide qui se ferait passer pour une lecture)", async () => {
    const depot = new DepotCleValeurMemoire();
    await chargeur(depot, jest.fn(async () => TRONQUEE())).chargerChantiersAujourdhui();
    expect(depot.cles()).toEqual([]);
  });

  test("le socle coupe la réponse SANS `resultat` : l'aperçu n'est jamais lu comme la liste", async () => {
    const resultat = await chargeur(
      new DepotCleValeurMemoire(),
      jest.fn(async () => reponseHttp(200, { ok: true, result: { ok: true, tronque: true, apercu: JSON.stringify([I_PLANIFIEE]).slice(0, 40) } })),
    ).chargerChantiersAujourdhui();
    expect(resultat.source).toBe("incomplet");
    expect(resultat.source === "incomplet" && resultat.items).toEqual([]);
  });

  test("un statut tronqué et un autre injoignable : le cache prend le relais (le serveur n'a pas pu répondre), marqué", async () => {
    const depot = await depotAvecCache();
    const fetchImpl = serveur({}, (statut) => (statut === "sur_site" ? TRONQUEE() : statut === "planifiee" ? reponseHttp(503, {}) : undefined));
    const resultat = await chargeur(depot, fetchImpl).chargerChantiersAujourdhui();
    expect(resultat.source).toBe("cache");
    expect(resultat.source === "cache" && resultat.raisonHorsLigne.code).toBe("http_503");
  });
});

describe("chargerChantiersAujourdhui — une forme inconnue n'est jamais « aucune intervention »", () => {
  test.each([
    ["un résultat nul", { ok: true, result: { ok: true, resultat: null } }],
    ["un résultat qui n'est pas une liste", { ok: true, result: { ok: true, resultat: { intervention_id: "I1" } } }],
    ["un résultat absent", { ok: true, result: { ok: true } }],
    ["une enveloppe qui est une liste", { ok: true, result: [] }],
  ])("%s : le cache, marqué reponse_illisible, et RIEN n'est écrit", async (_nom, corps) => {
    const depot = await depotAvecCache();
    const avant = await depot.lire(CLE_CACHE);
    const ecrire = jest.spyOn(depot, "ecrire");

    const resultat = await chargeur(depot, jest.fn(async () => reponseHttp(200, corps))).chargerChantiersAujourdhui();

    expect(resultat.source).toBe("cache");
    expect(resultat.source === "cache" && resultat.raisonHorsLigne.code).toBe("reponse_illisible");
    expect(ecrire).not.toHaveBeenCalled();
    expect(await depot.lire(CLE_CACHE)).toBe(avant);
  });

  test("forme inconnue SANS cache : aucune, jamais une liste inventée", async () => {
    const resultat = await chargeur(
      new DepotCleValeurMemoire(),
      jest.fn(async () => reponseHttp(200, { ok: true, result: { ok: true, resultat: null } })),
    ).chargerChantiersAujourdhui();
    expect(resultat).toMatchObject({ source: "aucune", raisonHorsLigne: { code: "reponse_illisible" } });
  });
});

describe("chargerChantiersAujourdhui — hors ligne : le cache est un cache, dit comme tel", () => {
  test("échec réseau avec un cache déjà présent : source cache, items filtrés, raison portée", async () => {
    const depot = await depotAvecCache();
    const fetchImpl = jest.fn().mockRejectedValue(new TypeError("Network request failed"));

    const resultat = await chargeur(depot, fetchImpl).chargerChantiersAujourdhui();

    expect(resultat).toEqual({
      source: "cache",
      items: [I_EN_ROUTE, I_PLANIFIEE],
      misAJourLe: "2026-09-28T08:00:00.000Z",
      raisonHorsLigne: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });

  test("échec réseau SANS cache : source aucune, jamais une liste inventée", async () => {
    const resultat = await chargeur(new DepotCleValeurMemoire(), jest.fn().mockRejectedValue(new TypeError("Network request failed"))).chargerChantiersAujourdhui();
    expect(resultat).toEqual({ source: "aucune", raisonHorsLigne: { code: "erreur_reseau", detail: "Network request failed" } });
  });

  test.each([
    ["500", 500, { ok: false, error: { type: "tool_error", message: "panne" } }, "tool_error"],
    ["502", 502, {}, "http_502"],
    ["503", 503, {}, "http_503"],
    ["408", 408, {}, "http_408"],
    ["429", 429, { ok: false, error: { type: "tool_call_blocked", message: "débit" } }, "tool_call_blocked"],
    ["404 qui n'est pas du core (mandataire, page de connexion)", 404, "<html>", "http_404"],
  ])("HTTP %s : le serveur n'a pas pu répondre, le cache est servi, marqué", async (_nom, status, corps, code) => {
    const depot = await depotAvecCache();
    const resultat = await chargeur(depot, jest.fn(async () => reponseHttp(status, corps))).chargerChantiersAujourdhui();
    expect(resultat.source).toBe("cache");
    expect(resultat.source === "cache" && resultat.raisonHorsLigne.code).toBe(code);
  });

  test("l'état passager de l'instance (budget épuisé, outil pas encore déployé) : le cache prend le relais", async () => {
    const depot = await depotAvecCache();
    for (const erreur of ["budget_epuise", "outil_inconnu", "departement_appelant_inconnu"]) {
      const resultat = await chargeur(
        depot,
        jest.fn(async () => reponseHttp(200, { ok: true, result: { ok: false, erreur, details: "instance" } })),
      ).chargerChantiersAujourdhui();
      expect(resultat.source).toBe("cache");
      expect(resultat.source === "cache" && resultat.raisonHorsLigne).toEqual({ code: erreur, detail: "instance" });
    }
  });

  test("le cache d'une AUTRE personne, et l'ancienne clé sans personne, ne sont jamais servis", async () => {
    const depot = await depotAvecCache();
    await depot.ecrire("today_chantiers_v1", JSON.stringify(CACHE_D_AVANT));
    const resultat = await chargeur(depot, jest.fn().mockRejectedValue(new TypeError("hors ligne")), "sophie").chargerChantiersAujourdhui();
    expect(resultat).toMatchObject({ source: "aucune" });
  });
});

describe("chargerChantiersAujourdhui — un appareil refusé ne relit JAMAIS la liste gardée (PLAN T1.4-n)", () => {
  async function refuse(fetchImpl: jest.Mock): Promise<{ resultat: ResultatChargementChantiers; depot: DepotCleValeurMemoire; avant: string | null }> {
    const depot = await depotAvecCache();
    const avant = await depot.lire(CLE_CACHE);
    const lire = jest.spyOn(depot, "lire");
    const ecrire = jest.spyOn(depot, "ecrire");
    const resultat = await chargeur(depot, fetchImpl).chargerChantiersAujourdhui();
    expect(lire).not.toHaveBeenCalled();
    expect(ecrire).not.toHaveBeenCalled();
    expect(await depot.lire(CLE_CACHE)).toBe(avant);
    return { resultat, depot, avant };
  }

  test.each([
    ["401 : jeton inconnu ou révoqué", 401, {}, "http_401"],
    ["403 : la porte d'appareil refuse (device_unknown)", 403, { ok: false, error: { type: "tool_call_blocked", message: "device_unknown" } }, "tool_call_blocked"],
    ["403 sans le corps du core", 403, "interdit", "http_403"],
    ["400 du core", 400, { ok: false, error: { type: "invalid_request", message: "statut" } }, "invalid_request"],
    ["404 du core", 404, { ok: false, error: { type: "not_found", message: "outil" } }, "not_found"],
  ])("%s : refus, la liste gardée n'est ni lue ni remplacée, rien n'est écrit", async (_nom, status, corps, code) => {
    const { resultat } = await refuse(jest.fn(async () => reponseHttp(status, corps)));
    expect(resultat).toMatchObject({ source: "refus", verdict: { code } });
    expect(resultat.source === "refus" && "items" in resultat).toBe(false);
  });

  test.each([
    ["l'identité que la base ne confirme plus (personne désactivée, rôle retiré)", { ok: false, erreur: "refus_metier", details: "REJ-IDENTITE-APPAREIL-INVALIDE : personne 'etienne' inactive" }, "refus_metier"],
    ["l'outil hors de la portée du rôle", { ok: false, erreur: "hors_portee_role", details: "employee" }, "hors_portee_role"],
    ["un statut refusé", { ok: false, erreur: "arguments_invalides", details: ["statut : valeur hors liste"] }, "arguments_invalides"],
  ])("%s (refus technique, HTTP 200) : refus, jamais la liste gardée", async (_nom, resultatTechnique, code) => {
    const { resultat } = await refuse(jest.fn(async () => reponseHttp(200, { ok: true, result: resultatTechnique })));
    expect(resultat).toMatchObject({ source: "refus", verdict: { code } });
  });

  test("un seul statut refusé sur quatre suffit : toute la lecture est refusée, jamais un mélange", async () => {
    const fetchImpl = serveur({ en_route: [I_EN_ROUTE] }, (statut) => (statut === "en_revue" ? reponseHttp(403, { ok: false, error: { type: "tool_call_blocked", message: "x" } }) : undefined));
    const { resultat } = await refuse(fetchImpl);
    expect(resultat).toMatchObject({ source: "refus", verdict: { code: "tool_call_blocked" } });
  });

  test("un refus et une panne : le refus l'emporte (le cache ne dit pas ce que le serveur refuse)", async () => {
    const fetchImpl = serveur({}, (statut) => (statut === "en_route" ? reponseHttp(503, {}) : statut === "planifiee" ? reponseHttp(401, {}) : undefined));
    const { resultat } = await refuse(fetchImpl);
    expect(resultat).toMatchObject({ source: "refus", verdict: { code: "http_401" } });
  });

  test("un refus n'écrit rien même sans cache", async () => {
    const depot = new DepotCleValeurMemoire();
    const ecrire = jest.spyOn(depot, "ecrire");
    const resultat = await chargeur(depot, jest.fn(async () => reponseHttp(401, {}))).chargerChantiersAujourdhui();
    expect(resultat.source).toBe("refus");
    expect(ecrire).not.toHaveBeenCalled();
  });
});
