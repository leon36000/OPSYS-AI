import {
  OUTIL_OBTENIR_CLIENT_360,
  OUTIL_SUGGERER_PROCHAINE_ACTION,
  OUTIL_TROUVER_CLIENT_DE_LEAD,
} from "../m2/client360";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ConfigurationChargeurVendeur } from "./appel";
import { creerChargeurFiche } from "./chargeurFiche";
import {
  CLIENT_DE_LEAD_BRUT,
  ECHECS_QUI_SONT_UN_REFUS,
  ECHECS_QUI_SONT_UNE_PANNE,
  SUGGESTION_BRUTE,
  client360Brut,
  echecHttp,
  enveloppeAcceptee,
  enveloppeRefusee,
  fauxTransport,
  transportEnEchec,
  transportHorsLigne,
} from "./donneesDeTest";

const HORLOGE = { maintenant: new Date("2026-09-29T18:03:22.000Z"), decalageMinutesUTC: -240 };

function config(appelerOutil: jest.Mock, depot: DepotCleValeur = new DepotCleValeurMemoire(), personne = "vendeur.a"): ConfigurationChargeurVendeur {
  return {
    depot,
    appelerOutil,
    fetchImpl: jest.fn() as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-vendeur",
    personne,
    horloge: () => HORLOGE,
  };
}

const SERVEUR_COMPLET = {
  [OUTIL_SUGGERER_PROCHAINE_ACTION]: () => enveloppeAcceptee(SUGGESTION_BRUTE),
  [OUTIL_TROUVER_CLIENT_DE_LEAD]: () => enveloppeAcceptee(CLIENT_DE_LEAD_BRUT),
  [OUTIL_OBTENIR_CLIENT_360]: () => enveloppeAcceptee(client360Brut()),
};

describe("chargerFiche — en ligne", () => {
  test("suggestion avec sa règle, client du lead, Client 360 : trois lectures, dans l'ordre, date de l'appareil", async () => {
    const transport = fauxTransport(SERVEUR_COMPLET);
    const resultat = await creerChargeurFiche(config(transport)).chargerFiche("lead-a-01");

    expect(resultat.source).toBe("serveur");
    if (resultat.source !== "serveur") {
      return;
    }
    expect(resultat.fiche.misAJourLe).toBe("2026-09-29T18:03:22.000Z");
    expect(resultat.fiche.suggestion).toMatchObject({ genre: "lue", valeur: { regle: "transmettre_m3" } });
    expect(resultat.fiche.client).toMatchObject({ genre: "lue", valeur: { clientId: "a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346" } });
    expect(transport.mock.calls.map((c) => c[0].requete.tool)).toEqual([
      "m2_suggerer_prochaine_action",
      "m2_trouver_client_de_lead",
      "m2_obtenir_client_360",
    ]);
  });

  test("les arguments : exactement ceux des schémas ; le client_id vient de la réponse du serveur, jamais deviné ; aucune personne", async () => {
    const transport = fauxTransport(SERVEUR_COMPLET);
    await creerChargeurFiche(config(transport)).chargerFiche("lead-a-01");

    const requetes = transport.mock.calls.map((c) => c[0].requete);
    expect(requetes[0].args).toEqual({ lead_id: "lead-a-01", horodatage: "2026-09-29T14:03:22-04:00" });
    expect(requetes[1].args).toEqual({ lead_id: "lead-a-01" });
    expect(requetes[2].args).toEqual({ client_id: "a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346" });
    for (const requete of requetes) {
      expect(requete.idempotencyKey).toBeUndefined();
      expect(JSON.stringify(requete)).not.toContain("vendeur.a");
    }
  });

  test("le cache est écrit avec les mots du serveur, sous la personne, et sert hors ligne", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurFiche(config(fauxTransport(SERVEUR_COMPLET), depot)).chargerFiche("lead-a-01");

    const hors = await creerChargeurFiche(config(transportHorsLigne(), depot)).chargerFiche("lead-a-01");

    expect(hors.source).toBe("cache");
    if (hors.source === "cache") {
      expect(hors.fiche.misAJourLe).toBe("2026-09-29T18:03:22.000Z");
      expect(hors.fiche.suggestion).toMatchObject({ genre: "lue", valeur: { regle: "transmettre_m3" } });
      expect(hors.fiche.client).toMatchObject({ genre: "lue", valeur: { contact: { nom: "Cliente Fictive" } } });
      expect(hors.raisonHorsLigne).toEqual({ code: "erreur_reseau", detail: "Network request failed" });
    }
  });

  test("un lead clos : le refus de la suggestion est une réponse (fiche du serveur), le client reste lu", async () => {
    const transport = fauxTransport({
      ...SERVEUR_COMPLET,
      [OUTIL_SUGGERER_PROCHAINE_ACTION]: () => enveloppeRefusee("REJ-CONVERSATION-CLOSE", "lead clos (statut=perdu)"),
    });
    const resultat = await creerChargeurFiche(config(transport)).chargerFiche("lead-a-01");
    expect(resultat.source).toBe("serveur");
    expect(resultat.source === "serveur" && resultat.fiche.suggestion).toEqual({
      genre: "verdict",
      verdict: { code: "REJ-CONVERSATION-CLOSE", detail: "lead clos (statut=perdu)" },
    });
    expect(resultat.source === "serveur" && resultat.fiche.client.genre).toBe("lue");
  });

  test("le lead d'un autre vendeur : le même refus partout, aucun Client 360 demandé, le cache n'est pas servi", async () => {
    const depot = new DepotCleValeurMemoire();
    const refus = () => enveloppeRefusee("REJ-LEAD-NON-ASSIGNE", "lead lead-b-01 non assigné");
    const transport = fauxTransport({
      [OUTIL_SUGGERER_PROCHAINE_ACTION]: refus,
      [OUTIL_TROUVER_CLIENT_DE_LEAD]: refus,
      [OUTIL_OBTENIR_CLIENT_360]: () => {
        throw new Error("ne devrait jamais être appelé");
      },
    });
    const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-b-01");

    const attendu = { genre: "verdict", verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead lead-b-01 non assigné" } };
    expect(resultat.source === "serveur" && [resultat.fiche.suggestion, resultat.fiche.client]).toEqual([attendu, attendu]);
    expect(transport.mock.calls.map((c) => c[0].requete.tool)).toEqual(["m2_suggerer_prochaine_action", "m2_trouver_client_de_lead"]);
  });
});

describe("chargerFiche — hors ligne et pannes", () => {
  test("réseau tombé SANS cache : aucune, jamais une fiche inventée", async () => {
    expect(await creerChargeurFiche(config(transportHorsLigne())).chargerFiche("lead-a-01")).toEqual({
      source: "aucune",
      raison: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });

  test("une panne au milieu (le Client 360 ne répond plus) : la fiche gardée, jamais un mélange frais/gardé", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurFiche(config(fauxTransport(SERVEUR_COMPLET), depot)).chargerFiche("lead-a-01");
    const suggestionPlusRecente = { ...SUGGESTION_BRUTE, regle: "planifier_chantier", suggestion: "AUTRE TEXTE" };
    const transport = fauxTransport({
      [OUTIL_SUGGERER_PROCHAINE_ACTION]: () => enveloppeAcceptee(suggestionPlusRecente),
      [OUTIL_TROUVER_CLIENT_DE_LEAD]: () => enveloppeAcceptee(CLIENT_DE_LEAD_BRUT),
      [OUTIL_OBTENIR_CLIENT_360]: () => ({ ok: true, tronque: true, apercu: "{" }),
    });

    const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");

    expect(resultat.source).toBe("cache");
    if (resultat.source === "cache") {
      expect(resultat.raisonHorsLigne.code).toBe("reponse_tronquee");
      expect(JSON.stringify(resultat.fiche)).not.toContain("AUTRE TEXTE");
      expect(resultat.fiche.suggestion).toMatchObject({ genre: "lue", valeur: { regle: "transmettre_m3" } });
    }
  });

  test("le cache d'une AUTRE personne, ou d'un AUTRE lead, n'est jamais servi", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurFiche(config(fauxTransport(SERVEUR_COMPLET), depot)).chargerFiche("lead-a-01");
    expect((await creerChargeurFiche(config(transportHorsLigne(), depot, "vendeur.b")).chargerFiche("lead-a-01")).source).toBe("aucune");
    expect((await creerChargeurFiche(config(transportHorsLigne(), depot)).chargerFiche("lead-a-02")).source).toBe("aucune");
  });

  test("une réponse d'un autre lead ou d'un autre client n'est pas montrée : verdict illisible, jamais un mélange", async () => {
    const transport = fauxTransport({
      ...SERVEUR_COMPLET,
      [OUTIL_TROUVER_CLIENT_DE_LEAD]: () => enveloppeAcceptee({ lead_id: "lead-b-09", client_id: "b7c3e1a9d5f2468013579bdf02468ace13579bdf02468ace13579bdf02468ace" }),
    });
    const resultat = await creerChargeurFiche(config(transport)).chargerFiche("lead-a-01");
    expect(resultat.source === "serveur" && resultat.fiche.client).toMatchObject({
      genre: "verdict",
      verdict: { code: "reponse_illisible" },
    });
  });

  test("la passerelle refuse un outil (403) : refus, avec la raison ; rien n'est gardé, rien n'est écrit", async () => {
    const depot = new DepotCleValeurMemoire();
    const ecrire = jest.spyOn(depot, "ecrire");
    const sans = await creerChargeurFiche(config(fauxTransport({}), depot)).chargerFiche("lead-a-01");
    expect(sans).toMatchObject({ source: "refus", verdict: { code: "tool_call_blocked" } });
    expect(ecrire).not.toHaveBeenCalled();
  });

  test.each(ECHECS_QUI_SONT_UNE_PANNE)("%s : le serveur n'a pas pu répondre, la fiche gardée est servie, marquée", async (_nom, status, type, code) => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurFiche(config(fauxTransport(SERVEUR_COMPLET), depot)).chargerFiche("lead-a-01");
    const resultat = await creerChargeurFiche(config(transportEnEchec(status, type), depot)).chargerFiche("lead-a-01");
    expect(resultat.source).toBe("cache");
    expect(resultat.source === "cache" && resultat.raisonHorsLigne.code).toBe(code);
  });

  test("l'écriture du cache qui échoue ne cache pas une fiche lue", async () => {
    const espion = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const depot = {
      lire: async () => null,
      ecrire: async () => {
        throw new Error("disque plein");
      },
      supprimer: async () => undefined,
      supprimerParPrefixe: async () => undefined,
    };
    const resultat = await creerChargeurFiche(config(fauxTransport(SERVEUR_COMPLET), depot)).chargerFiche("lead-a-01");
    expect(resultat.source).toBe("serveur");
    espion.mockRestore();
  });
});

describe("chargerFiche — un appareil refusé ne relit JAMAIS la fiche gardée (PLAN T1.4-n)", () => {
  const CLE = "vendeur:vendeur.a:fiche:lead-a-01_v1";

  async function avecFicheGardee() {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurFiche(config(fauxTransport(SERVEUR_COMPLET), depot)).chargerFiche("lead-a-01");
    const avant = await depot.lire(CLE);
    expect(avant).not.toBeNull();
    return { depot, avant, lire: jest.spyOn(depot, "lire"), ecrire: jest.spyOn(depot, "ecrire") };
  }

  test.each(ECHECS_QUI_SONT_UN_REFUS)(
    "%s : refus, la fiche gardée n'est ni lue ni remplacée, rien n'est écrit, une seule requête",
    async (_nom, status, type, code) => {
      const { depot, avant, lire, ecrire } = await avecFicheGardee();
      const transport = transportEnEchec(status, type, "refusé");

      const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");

      expect(resultat).toEqual({ source: "refus", verdict: { code, detail: "refusé" } });
      expect(lire).not.toHaveBeenCalled();
      expect(ecrire).not.toHaveBeenCalled();
      expect(await depot.lire(CLE)).toBe(avant);
      expect(transport).toHaveBeenCalledTimes(1);
    },
  );

  // Le refus vient de la 2e ou de la 3e lecture : la première a réussi, mais la fiche n'est pas un mélange de lectures
  // fraîches et gardées, ni une fiche à moitié montrée : tout est refusé.
  test.each([
    ["la deuxième lecture (le client du lead)", OUTIL_TROUVER_CLIENT_DE_LEAD, 2],
    ["la troisième lecture (le Client 360)", OUTIL_OBTENIR_CLIENT_360, 3],
  ])("le refus arrive à %s : toute la fiche est refusée, rien n'est écrit", async (_nom, outilRefuse, appelsAttendus) => {
    const { depot, avant, lire, ecrire } = await avecFicheGardee();
    const transport = jest.fn(async (params: { requete: { tool: string; args?: Record<string, unknown> } }) =>
      params.requete.tool === outilRefuse
        ? echecHttp(403, "tool_call_blocked", "device_unknown")
        : { ok: true, result: SERVEUR_COMPLET[params.requete.tool as keyof typeof SERVEUR_COMPLET]() },
    );

    const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");

    expect(resultat).toEqual({ source: "refus", verdict: { code: "tool_call_blocked", detail: "device_unknown" } });
    expect(transport).toHaveBeenCalledTimes(appelsAttendus);
    expect(lire).not.toHaveBeenCalled();
    expect(ecrire).not.toHaveBeenCalled();
    expect(await depot.lire(CLE)).toBe(avant);
  });

  // « Personne désactivée, rôle retiré » : 200, mais par un refus technique (`ok: false`).
  test.each([
    ["l'identité que la base ne confirme plus", { ok: false, erreur: "refus_metier", details: "REJ-IDENTITE-APPAREIL-INVALIDE : personne 'sophie' inactive" }],
    ["l'outil hors de la portée du rôle", { ok: false, erreur: "hors_portee_role", details: "seller" }],
  ])("%s (refus technique) : toute la fiche est refusée, la fiche gardée n'est pas lue", async (_nom, brut) => {
    const { depot, lire, ecrire } = await avecFicheGardee();
    const transport = fauxTransport({ ...SERVEUR_COMPLET, [OUTIL_SUGGERER_PROCHAINE_ACTION]: () => brut });

    const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");

    expect(resultat).toMatchObject({ source: "refus", verdict: { code: (brut as { erreur: string }).erreur } });
    expect(lire).not.toHaveBeenCalled();
    expect(ecrire).not.toHaveBeenCalled();
    expect(transport).toHaveBeenCalledTimes(1);
  });

  test("l'état passager de l'instance (budget épuisé) n'est pas un refus : la fiche gardée est servie, avec la raison", async () => {
    const { depot } = await avecFicheGardee();
    const transport = fauxTransport({ ...SERVEUR_COMPLET, [OUTIL_SUGGERER_PROCHAINE_ACTION]: () => ({ ok: false, erreur: "budget_epuise", details: "trop" }) });
    const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");
    expect(resultat.source).toBe("cache");
    expect(resultat.source === "cache" && resultat.raisonHorsLigne.code).toBe("budget_epuise");
  });
});

describe("chargerFiche — le cache ne garde pas une fiche faite de verdicts (PLAN T1.4-n)", () => {
  test("le lead d'un autre vendeur : la fiche du serveur (deux verdicts), rien n'est écrit, la fiche gardée d'avant n'est pas servie", async () => {
    const depot = new DepotCleValeurMemoire();
    // Le lead était à ce vendeur : sa fiche est gardée.
    await creerChargeurFiche(config(fauxTransport(SERVEUR_COMPLET), depot)).chargerFiche("lead-a-01");
    const avant = await depot.lire("vendeur:vendeur.a:fiche:lead-a-01_v1");
    const ecrire = jest.spyOn(depot, "ecrire");
    const refus = () => enveloppeRefusee("REJ-LEAD-NON-ASSIGNE", "lead lead-a-01 non assigné");
    const transport = fauxTransport({
      [OUTIL_SUGGERER_PROCHAINE_ACTION]: refus,
      [OUTIL_TROUVER_CLIENT_DE_LEAD]: refus,
    });

    const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");

    expect(resultat.source).toBe("serveur");
    expect(resultat.source === "serveur" && resultat.fiche.client).toEqual({
      genre: "verdict",
      verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead lead-a-01 non assigné" },
    });
    expect(ecrire).not.toHaveBeenCalled();
    expect(await depot.lire("vendeur:vendeur.a:fiche:lead-a-01_v1")).toBe(avant);
  });

  test("un lead clos : le Client 360 est lu, la fiche est gardée (son historique se lit hors ligne)", async () => {
    const depot = new DepotCleValeurMemoire();
    const transport = fauxTransport({
      ...SERVEUR_COMPLET,
      [OUTIL_SUGGERER_PROCHAINE_ACTION]: () => enveloppeRefusee("REJ-CONVERSATION-CLOSE", "lead clos (statut=perdu)"),
    });
    await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");

    const hors = await creerChargeurFiche(config(transportHorsLigne(), depot)).chargerFiche("lead-a-01");

    expect(hors.source).toBe("cache");
    expect(hors.source === "cache" && hors.fiche.client.genre).toBe("lue");
    expect(hors.source === "cache" && hors.fiche.suggestion.genre).toBe("verdict");
  });

  test("un client dont la réponse est illisible (pas de Client 360 lu) : la fiche est montrée, rien n'est écrit", async () => {
    const depot = new DepotCleValeurMemoire();
    const ecrire = jest.spyOn(depot, "ecrire");
    const transport = fauxTransport({
      ...SERVEUR_COMPLET,
      [OUTIL_TROUVER_CLIENT_DE_LEAD]: () => enveloppeAcceptee({ lead_id: "lead-a-01" }),
    });
    const resultat = await creerChargeurFiche(config(transport, depot)).chargerFiche("lead-a-01");
    expect(resultat.source).toBe("serveur");
    expect(ecrire).not.toHaveBeenCalled();
  });
});
