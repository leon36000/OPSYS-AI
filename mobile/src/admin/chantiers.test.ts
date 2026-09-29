import { STATUTS_DU_DISPATCH, OUTIL_LISTER_INTERVENTIONS, OUTIL_PRODUIRE_DIGEST, OUTIL_VERIFIER_PREPARATION } from "../m4/dispatch";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { lireCacheSection } from "./cache";
import { creerChargeurChantiers, sectionDigest, sectionInterventions, sectionPreparation } from "./chantiers";
import { config, echecHttp, enveloppeEnErreur, fauxTransport, reponse, transportHorsLigne } from "./donneesDeTest";
import { lireSection } from "./lecture";

/** Le serveur : la liste d'un statut, le digest du jour et la préparation d'une intervention. */
function serveur(surcharges: Record<string, (args: Record<string, unknown>) => unknown> = {}) {
  return fauxTransport({
    [OUTIL_LISTER_INTERVENTIONS]: (args) => reponse(`interventions_${String(args.statut)}`),
    [OUTIL_PRODUIRE_DIGEST]: () => reponse("digest"),
    [OUTIL_VERIFIER_PREPARATION]: () => reponse("preparation_lead_v2"),
    ...surcharges,
  });
}

const DATE_DE_L_APPAREIL = "2026-09-29";
const INSTANT_DE_L_APPAREIL = "2026-09-29T14:03:22-04:00";

describe("les interventions du dispatch, un groupe par statut", () => {
  test("un appel par statut du dispatch, dans l'ordre, avec le seul argument `statut`", async () => {
    const transport = serveur();

    const groupes = await creerChargeurChantiers(config(transport)).chargerGroupes();

    expect(groupes.map((g) => g.statut)).toEqual([...STATUTS_DU_DISPATCH]);
    expect(transport.mock.calls.map((appel) => appel[0].requete)).toEqual(
      STATUTS_DU_DISPATCH.map((statut) => ({ tool: "m4_lister_interventions", args: { statut } })),
    );
    expect(groupes.every((g) => g.resultat.source === "serveur")).toBe(true);
  });

  test("les groupes lus sont ceux du moteur : deux planifiées, une à planifier, une à revoir, les autres vides", async () => {
    const groupes = await creerChargeurChantiers(config(serveur())).chargerGroupes();
    const compte = Object.fromEntries(
      groupes.map((g) => [g.statut, g.resultat.source === "serveur" ? g.resultat.valeur.interventions.length : -1]),
    );
    expect(compte).toEqual({ en_route: 0, sur_site: 0, en_revue: 0, planifiee: 2, a_planifier: 1, reportee: 0, completed_pending_review: 1 });
  });

  test("chaque groupe est gardé sous son statut et sa personne", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChantiers(config(serveur(), { depot })).chargerGroupes();
    for (const statut of STATUTS_DU_DISPATCH) {
      expect(await lireCacheSection(depot, "nathan", `interventions:${statut}`)).not.toBeNull();
      expect(await lireCacheSection(depot, "sophie", `interventions:${statut}`)).toBeNull();
    }
  });

  test("UN GROUPE QUI ÉCHOUE NE CACHE PAS LES AUTRES : `planifiee` trop gros pour le serveur (cache), `sur_site` refusé (403), le reste lu", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChantiers(config(serveur(), { depot })).chargerGroupes();
    const transport = jest.fn(async (params: { requete: { tool: string; args?: Record<string, unknown> } }) => {
      const statut = params.requete.args?.statut;
      if (statut === "planifiee") {
        return { ok: true, result: { ok: true, tronque: true, apercu: "[" } };
      }
      if (statut === "sur_site") {
        return echecHttp(403, "tool_call_blocked", "hors portée");
      }
      return { ok: true, result: reponse(`interventions_${String(statut)}`) };
    });

    const groupes = await creerChargeurChantiers(config(transport, { depot })).chargerGroupes();
    const par = Object.fromEntries(groupes.map((g) => [g.statut, g.resultat]));

    expect(par.planifiee).toMatchObject({ source: "cache", raisonHorsLigne: { code: "reponse_tronquee" } });
    expect(par.planifiee.source === "cache" && par.planifiee.valeur.interventions).toHaveLength(2);
    expect(par.sur_site).toEqual({ source: "refus", verdict: { code: "tool_call_blocked", detail: "hors portée" } });
    expect(par.a_planifier.source).toBe("serveur");
    expect(par.completed_pending_review.source).toBe("serveur");
  });

  test("hors ligne et sans cache : chaque groupe est « aucune » avec sa raison, jamais une liste vide", async () => {
    const groupes = await creerChargeurChantiers(config(transportHorsLigne())).chargerGroupes();
    for (const { resultat } of groupes) {
      expect(resultat).toEqual({ source: "aucune", raison: { code: "erreur_reseau", detail: "Network request failed" } });
    }
  });

  test("le groupe d'un statut n'est jamais servi par le cache d'un autre", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChantiers(config(serveur(), { depot })).chargerGroupes();
    const groupes = await creerChargeurChantiers(config(transportHorsLigne(), { depot })).chargerGroupes();
    for (const { statut, resultat } of groupes) {
      expect(resultat.source === "cache" && resultat.valeur.statut).toBe(statut);
    }
  });

  test("une personne désactivée : refus_metier pour chaque groupe, aucun cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChantiers(config(serveur(), { depot })).chargerGroupes();
    const desactivee = serveur({ [OUTIL_LISTER_INTERVENTIONS]: () => reponse("refus_identite_interventions") });
    const groupes = await creerChargeurChantiers(config(desactivee, { depot })).chargerGroupes();
    for (const { resultat } of groupes) {
      expect(resultat).toMatchObject({ source: "refus", verdict: { code: "refus_metier" } });
    }
  });

  test("un statut hors catalogue : le refus « arguments invalides » du serveur, jamais une liste vide", async () => {
    const refusant = serveur({
      [OUTIL_LISTER_INTERVENTIONS]: () => enveloppeEnErreur("arguments_invalides", ["statut : hors liste"]),
    });

    const lu = await lireSection(config(refusant), sectionInterventions("inconnu"));

    expect(lu).toMatchObject({ source: "refus", verdict: { code: "arguments_invalides", detail: "statut : hors liste" } });
  });
});

describe("le digest du jour", () => {
  test("le jour et l'instant de l'appareil, et le cache du digest de CE jour", async () => {
    const transport = serveur();
    const depot = new DepotCleValeurMemoire();

    const lu = await creerChargeurChantiers(config(transport, { depot })).chargerDigest();

    expect(transport.mock.calls[0][0].requete).toEqual({
      tool: "m4_produire_digest",
      args: { date_cible: DATE_DE_L_APPAREIL, horodatage_reference: INSTANT_DE_L_APPAREIL },
    });
    expect(lu).toMatchObject({ source: "serveur", valeur: { dateCible: "2026-09-21" } });
    expect(await lireCacheSection(depot, "nathan", `digest:${DATE_DE_L_APPAREIL}`)).not.toBeNull();
  });

  test("le digest d'un jour n'est jamais servi pour un autre : le lendemain, hors ligne, il n'y a pas de cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChantiers(config(serveur(), { depot })).chargerDigest();

    const lendemain = { maintenant: new Date("2026-09-30T18:00:00.000Z"), decalageMinutesUTC: -240 };
    const lu = await creerChargeurChantiers(config(transportHorsLigne(), { depot, horloge: lendemain })).chargerDigest();
    expect(lu.source).toBe("aucune");

    const memeJour = await creerChargeurChantiers(config(transportHorsLigne(), { depot })).chargerDigest();
    expect(memeJour.source).toBe("cache");
  });

  test("la section porte le jour dans son nom de cache", () => {
    expect(sectionDigest("2026-09-21", "2026-09-21T18:00:00-04:00")).toMatchObject({
      outil: "m4_produire_digest",
      args: { date_cible: "2026-09-21", horodatage_reference: "2026-09-21T18:00:00-04:00" },
      cache: "digest:2026-09-21",
    });
  });
});

describe("la préparation d'une intervention, à la demande", () => {
  const ID = "bc40348bbff5df996888ea3e1fbb1de49a4858f3a8178120f937e0d7e2cd289d";

  test("un appel avec le seul numéro d'intervention ; le résultat est gardé sous CE numéro et CETTE personne", async () => {
    const transport = serveur();
    const depot = new DepotCleValeurMemoire();

    const lu = await creerChargeurChantiers(config(transport, { depot })).chargerPreparation(ID);

    expect(transport.mock.calls[0][0].requete).toEqual({ tool: "m4_verifier_preparation", args: { intervention_id: ID } });
    expect(lu).toMatchObject({ source: "serveur", valeur: { verdict: "bloque", pret: false } });
    expect(await lireCacheSection(depot, "nathan", `preparation:${ID}`)).not.toBeNull();
    expect(await lireCacheSection(depot, "nathan", "preparation:autre")).toBeNull();
    expect(sectionPreparation(ID).cache).toBe(`preparation:${ID}`);
  });

  test("hors ligne, la préparation gardée de CETTE intervention est rendue marquée ; celle d'une autre ne l'est pas", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChantiers(config(serveur(), { depot })).chargerPreparation(ID);
    const chargeur = creerChargeurChantiers(config(transportHorsLigne(), { depot }));

    expect(await chargeur.chargerPreparation(ID)).toMatchObject({ source: "cache", valeur: { interventionId: ID }, raisonHorsLigne: { code: "erreur_reseau" } });
    expect(await chargeur.chargerPreparation("autre")).toMatchObject({ source: "aucune" });
  });

  test("une intervention qui n'est plus à préparer : le refus de M4, jamais la préparation gardée", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChantiers(config(serveur(), { depot })).chargerPreparation(ID);
    const terminee = serveur({ [OUTIL_VERIFIER_PREPARATION]: () => reponse("preparation_terminee") });

    const lu = await creerChargeurChantiers(config(terminee, { depot })).chargerPreparation(ID);

    expect(lu).toMatchObject({ source: "refus", verdict: { code: "REJ-TRANSITION-ILLEGALE" } });
  });
});
