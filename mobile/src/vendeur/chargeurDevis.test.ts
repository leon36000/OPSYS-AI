import { CODE_SEGMENT_NON_CALCULABLE, OUTIL_LISTER_LEADS } from "../m2/listeLeads";
import { LIMITE_PAGE_LISTE_DEVIS, OUTIL_LIRE_DEVIS, OUTIL_LISTER_DEVIS, lireDevisVendeur } from "../m3/devis";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ConfigurationChargeurVendeur } from "./appel";
import {
  ecrireCacheDevis,
  ecrireDevisConnus,
  lireCacheDevis,
  lireDevisConnus,
} from "./cache";
import { MAX_PAGES_DECOUVERTE, creerChargeurDevis } from "./chargeurDevis";
import {
  ECHECS_QUI_SONT_UN_REFUS,
  ECHECS_QUI_SONT_UNE_PANNE,
  devisInterneBrut,
  echecHttp,
  enveloppeAcceptee,
  enveloppeRefusee,
  fauxTransport,
  leadBrut,
  pageBrute,
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

const SEGMENT_CONVERTI = (devisId: string) => ({
  segment: "won_pending_schedule",
  regle: "soumission_acceptee_a_planifier",
  donnee: { statut: "converti", reference_devis_m3: devisId },
});
const SEGMENT_PERIME = (devisId: string) => ({
  segment: "quote_stale",
  regle: "devis_envoye_sans_reponse_perime",
  donnee: { devis_id: devisId, statut_devis: "envoye", jours_ecoules: 12, seuil_jours: 7 },
});

/** Un serveur : les leads par segment, et les devis lisibles par numéro (les autres : introuvables). */
function serveur(options: {
  converti?: Record<string, unknown>[];
  perime?: Record<string, unknown>[] | "non_calculable";
  devis?: Record<string, Record<string, unknown>>;
}) {
  const devis = options.devis ?? {};
  return {
    [OUTIL_LISTER_LEADS]: (args: Record<string, unknown>) => {
      const filtre = { statut: null, segment: args.segment as string };
      const decalage = typeof args.decalage === "number" ? args.decalage : 0;
      if (args.segment === "quote_stale" && options.perime === "non_calculable") {
        return enveloppeRefusee(
          CODE_SEGMENT_NON_CALCULABLE,
          "segment quote_stale : non calculable, manque le seuil jours_soumission_perimee : seuil à configurer",
        );
      }
      const leads = (args.segment === "won_pending_schedule" ? options.converti : (options.perime as Record<string, unknown>[] | undefined)) ?? [];
      return enveloppeAcceptee(pageBrute({ leads: leads.slice(decalage, decalage + 2), decalage, total: leads.length, filtre }));
    },
    [OUTIL_LIRE_DEVIS]: (args: Record<string, unknown>) => {
      const trouve = devis[args.devis_id as string];
      return trouve
        ? enveloppeAcceptee(trouve)
        : enveloppeRefusee("REJ-DEVIS-INTROUVABLE", `devis inconnu : '${String(args.devis_id)}'`);
    },
  };
}

const D1 = devisInterneBrut("devis-1", { statut: "accepte" });
const D2 = devisInterneBrut("devis-2", { statut: "envoye", lead_id: "lead-2" });

describe("chargerDevis — la découverte par les leads, puis la lecture de chaque devis", () => {
  test("les devis cités par les segments sont lus : statut et prix, chacun avec le lead qui le cite", async () => {
    const transport = fauxTransport(
      serveur({
        converti: [leadBrut("lead-1", { statut: "converti", segments: [SEGMENT_CONVERTI("devis-1")] })],
        perime: [leadBrut("lead-2", { segments: [SEGMENT_PERIME("devis-2")] })],
        devis: { "devis-1": D1, "devis-2": D2 },
      }),
    );
    const resultat = await creerChargeurDevis(config(transport)).chargerDevis();

    expect(resultat.entrees.map((e) => [e.connu.devisId, e.connu.leadId, e.connu.origine, e.etat.genre])).toEqual([
      ["devis-1", "lead-1", "lead_converti", "serveur"],
      ["devis-2", "lead-2", "soumission_perimee", "serveur"],
    ]);
    const premier = resultat.entrees[0].etat;
    expect(premier.genre === "serveur" && [premier.devis.statut, premier.devis.prixTotal]).toEqual(["accepte", "360.00"]);
    expect(resultat.sources.map((s) => [s.segment, s.etat.genre])).toEqual([
      ["won_pending_schedule", "lue"],
      ["quote_stale", "lue"],
    ]);
  });

  test("les appels : leads filtrés par segment (jamais une personne), devis par numéro seul (jamais role)", async () => {
    const transport = fauxTransport(
      serveur({ converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })], perime: [], devis: { "devis-1": D1 } }),
    );
    await creerChargeurDevis(config(transport)).chargerDevis();

    const requetes = transport.mock.calls.map((c) => c[0].requete);
    expect(requetes.map((r) => r.tool)).toEqual(["m2_lister_leads", "m2_lister_leads", "m3_lire_devis"]);
    expect(requetes[0].args).toEqual({ horodatage: "2026-09-29T14:03:22-04:00", segment: "won_pending_schedule" });
    expect(requetes[1].args).toEqual({ horodatage: "2026-09-29T14:03:22-04:00", segment: "quote_stale" });
    expect(requetes[2].args).toEqual({ devis_id: "devis-1" });
    for (const requete of requetes) {
      expect(requete.idempotencyKey).toBeUndefined();
      expect(JSON.stringify(requete)).not.toContain("vendeur.a");
    }
  });

  test("un segment non calculable (seuil à configurer) est DIT tel quel, jamais une liste vide ; l'autre segment est lu", async () => {
    const transport = fauxTransport(
      serveur({
        converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })],
        perime: "non_calculable",
        devis: { "devis-1": D1 },
      }),
    );
    const resultat = await creerChargeurDevis(config(transport)).chargerDevis();

    expect(resultat.sources[1]).toEqual({
      segment: "quote_stale",
      etat: {
        genre: "non_calculable",
        verdict: {
          code: "REJ-SEGMENT-NON-CALCULABLE",
          detail: "segment quote_stale : non calculable, manque le seuil jours_soumission_perimee : seuil à configurer",
        },
      },
    });
    expect(resultat.entrees.map((e) => e.connu.devisId)).toEqual(["devis-1"]);
  });

  test("un devis dont le serveur dit « introuvable » (un autre vendeur, inconnu) : refus tel quel, jamais le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    const avant = serveur({ converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })], perime: [], devis: { "devis-1": D1 } });
    await creerChargeurDevis(config(fauxTransport(avant), depot)).chargerDevis();
    expect(await lireCacheDevis(depot, "vendeur.a", "devis-1")).not.toBeNull();

    const apres = serveur({ converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })], perime: [], devis: {} });
    const resultat = await creerChargeurDevis(config(fauxTransport(apres), depot)).chargerDevis();

    expect(resultat.entrees[0].etat).toEqual({
      genre: "refus",
      verdict: { code: "REJ-DEVIS-INTROUVABLE", detail: "devis inconnu : 'devis-1'" },
    });
  });

  test("la découverte est bornée : au plus MAX_PAGES_DECOUVERTE pages par segment, la lecture partielle est DITE", async () => {
    const trop = Array.from({ length: 2 * MAX_PAGES_DECOUVERTE + 3 }, (_, i) =>
      leadBrut(`lead-${String(i).padStart(3, "0")}`, { segments: [SEGMENT_CONVERTI(`devis-${i}`)] }),
    );
    const transport = fauxTransport(serveur({ converti: trop, perime: [], devis: {} }));
    const resultat = await creerChargeurDevis(config(transport)).chargerDevis();

    const appelsLeads = transport.mock.calls.filter((c) => c[0].requete.tool === "m2_lister_leads" && c[0].requete.args.segment === "won_pending_schedule");
    expect(appelsLeads).toHaveLength(MAX_PAGES_DECOUVERTE);
    expect(resultat.sources[0].etat).toMatchObject({ genre: "lue", leadsLus: 2 * MAX_PAGES_DECOUVERTE, reste: 3, depuisCache: null });
    expect(resultat.entrees).toHaveLength(2 * MAX_PAGES_DECOUVERTE);
  });

  test("les rangs glissent pendant la découverte : ce qui est lu reste, la lecture est dite partielle", async () => {
    let appels = 0;
    const transport = fauxTransport({
      ...serveur({ perime: [], devis: {} }),
      [OUTIL_LISTER_LEADS]: (args: Record<string, unknown>) => {
        if (args.segment !== "won_pending_schedule") {
          return enveloppeAcceptee(pageBrute({ leads: [], filtre: { statut: null, segment: "quote_stale" } }));
        }
        appels += 1;
        const decalage = typeof args.decalage === "number" ? args.decalage : 0;
        const leads = [leadBrut(`lead-${appels}a`, { segments: [SEGMENT_CONVERTI(`devis-${appels}`)] })];
        return enveloppeAcceptee(pageBrute({ leads, decalage, total: appels === 1 ? 5 : 6, reste: 1, suivant: decalage + 1, filtre: { statut: null, segment: "won_pending_schedule" } }));
      },
    });
    const resultat = await creerChargeurDevis(config(transport)).chargerDevis();
    expect(appels).toBe(2);
    expect(resultat.sources[0].etat).toMatchObject({ genre: "lue", leadsLus: 1, reste: 1 });
  });
});

describe("chargerDevis — hors ligne", () => {
  async function avecCache() {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurDevis(
      config(
        fauxTransport(
          serveur({
            converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })],
            perime: [leadBrut("lead-2", { segments: [SEGMENT_PERIME("devis-2")] })],
            devis: { "devis-1": D1, "devis-2": D2 },
          }),
        ),
        depot,
      ),
    ).chargerDevis();
    return depot;
  }

  test("réseau tombé avec un cache : les devis gardés, chacun avec sa date, la raison dite, ni coût ni marge", async () => {
    const depot = await avecCache();
    const horsLigne = creerChargeurDevis({
      ...config(transportHorsLigne(), depot),
      horloge: () => ({ maintenant: new Date("2026-10-02T12:00:00.000Z"), decalageMinutesUTC: -240 }),
    });

    const resultat = await horsLigne.chargerDevis();

    expect(resultat.entrees.map((e) => e.etat.genre)).toEqual(["cache", "cache"]);
    const premier = resultat.entrees[0].etat;
    if (premier.genre === "cache") {
      expect(premier.misAJourLe).toBe("2026-09-29T18:03:22.000Z");
      expect(premier.raisonHorsLigne.code).toBe("erreur_reseau");
      expect(premier.devis.prixTotal).toBe("360.00");
    }
    expect(JSON.stringify(resultat)).not.toMatch(/cout|marge|taux/);
    // Les segments de leads sont lus depuis leur cache, et le disent.
    expect(resultat.sources.map((s) => s.etat.genre === "lue" && s.etat.depuisCache?.code)).toEqual(["erreur_reseau", "erreur_reseau"]);
  });

  test("réseau tombé SANS aucun cache : aucune découverte, aucun devis, jamais une liste inventée", async () => {
    const resultat = await creerChargeurDevis(config(transportHorsLigne())).chargerDevis();
    expect(resultat.entrees).toEqual([]);
    expect(resultat.sources.map((s) => s.etat.genre)).toEqual(["echouee", "echouee"]);
  });

  test("les numéros connus survivent à une découverte impossible : les devis déjà vus restent lisibles hors ligne", async () => {
    const depot = await avecCache();
    // Le cache des leads est effacé, seuls les numéros connus et les devis gardés restent.
    for (const cle of ["won_pending_schedule", "quote_stale"]) {
      await depot.ecrire(`vendeur:vendeur.a:leads:*|${cle}_v1`, "{}");
    }
    const resultat = await creerChargeurDevis(config(transportHorsLigne(), depot)).chargerDevis();
    expect(resultat.sources.map((s) => s.etat.genre)).toEqual(["echouee", "echouee"]);
    expect(resultat.entrees.map((e) => [e.connu.devisId, e.etat.genre])).toEqual([
      ["devis-1", "cache"],
      ["devis-2", "cache"],
    ]);
  });

  test("le cache d'une AUTRE personne sur le même téléphone n'est jamais servi", async () => {
    const depot = await avecCache();
    const resultat = await creerChargeurDevis(config(transportHorsLigne(), depot, "vendeur.b")).chargerDevis();
    expect(resultat.entrees).toEqual([]);
  });

  test("un devis gardé dont la lecture en ligne est illisible ou d'un autre numéro : le cache, avec la raison", async () => {
    const depot = await avecCache();
    const transport = fauxTransport({
      ...serveur({
        converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })],
        perime: [leadBrut("lead-2", { segments: [SEGMENT_PERIME("devis-2")] })],
      }),
      [OUTIL_LIRE_DEVIS]: (args: Record<string, unknown>) =>
        args.devis_id === "devis-1" ? enveloppeAcceptee({ devis_id: "devis-1" }) : enveloppeAcceptee(devisInterneBrut("un-autre")),
    });
    const resultat = await creerChargeurDevis(config(transport, depot)).chargerDevis();
    expect(resultat.entrees.map((e) => e.etat.genre === "cache" && e.etat.raisonHorsLigne.code)).toEqual([
      "reponse_illisible",
      "reponse_illisible",
    ]);
  });

  test("le devis lu en ligne ne garde ni coût ni marge : ni dans le résultat, ni dans le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    const brut = { ...devisInterneBrut("devis-1"), cout_total: "333.33", taux_marge: "0.4444" };
    const transport = fauxTransport(
      serveur({ converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })], perime: [], devis: { "devis-1": brut } }),
    );
    const resultat = await creerChargeurDevis(config(transport, depot)).chargerDevis();
    expect(JSON.stringify(resultat)).not.toMatch(/333\.33|0\.4444|cout|marge|taux/);
    expect(await depot.lire("vendeur:vendeur.a:devis:devis-1_v1")).not.toMatch(/333\.33|0\.4444|cout|marge|taux/);
  });
});

describe("ouvrirParNumero — le numéro d'une soumission que le vendeur a en main", () => {
  test("un devis lu est rendu, puis gardé avec les numéros connus (il reste lisible hors ligne)", async () => {
    const depot = new DepotCleValeurMemoire();
    const transport = fauxTransport(serveur({ devis: { "devis-9": devisInterneBrut("devis-9", { statut: "brouillon" }) } }));
    const chargeur = creerChargeurDevis(config(transport, depot));

    const entree = await chargeur.ouvrirParNumero("  devis-9 ");

    expect(entree?.connu).toEqual({ devisId: "devis-9", leadId: null, origine: "saisi" });
    expect(entree?.etat.genre).toBe("serveur");
    expect(await lireDevisConnus(depot, "vendeur.a")).toEqual([{ devisId: "devis-9", leadId: null, origine: "saisi" }]);
    expect(transport.mock.calls[0][0].requete).toEqual({ tool: "m3_lire_devis", args: { devis_id: "devis-9" } });
    const hors = await creerChargeurDevis(config(transportHorsLigne(), depot)).ouvrirParNumero("devis-9");
    expect(hors?.etat.genre).toBe("cache");
  });

  test("un numéro inconnu ou d'un autre vendeur : le refus du serveur, et JAMAIS gardé", async () => {
    const depot = new DepotCleValeurMemoire();
    const entree = await creerChargeurDevis(config(fauxTransport(serveur({})), depot)).ouvrirParNumero("devis-fantome");
    expect(entree?.etat).toEqual({
      genre: "refus",
      verdict: { code: "REJ-DEVIS-INTROUVABLE", detail: "devis inconnu : 'devis-fantome'" },
    });
    expect(await lireDevisConnus(depot, "vendeur.a")).toEqual([]);
  });

  test("un numéro vide : rien n'est demandé", async () => {
    const transport = fauxTransport(serveur({}));
    expect(await creerChargeurDevis(config(transport)).ouvrirParNumero("   ")).toBeNull();
    expect(transport).not.toHaveBeenCalled();
  });

  test("hors ligne, sans cache : indisponible avec la raison, jamais gardé", async () => {
    const depot = new DepotCleValeurMemoire();
    const entree = await creerChargeurDevis(config(transportHorsLigne(), depot)).ouvrirParNumero("devis-9");
    expect(entree?.etat).toEqual({ genre: "indisponible", raison: { code: "erreur_reseau", detail: "Network request failed" } });
    expect(await lireDevisConnus(depot, "vendeur.a")).toEqual([]);
  });
});

describe("chargerDevis — un appareil refusé ne relit JAMAIS ses devis gardés (PLAN T1.4-n)", () => {
  const CLE_DEVIS = "vendeur:vendeur.a:devis:devis-1_v1";
  const CLE_CONNUS = "vendeur:vendeur.a:devis_connus_v1";

  async function avecCache() {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurDevis(
      config(
        fauxTransport(
          serveur({ converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })], perime: [], devis: { "devis-1": D1 } }),
        ),
        depot,
      ),
    ).chargerDevis();
    const devis = await depot.lire(CLE_DEVIS);
    const connus = await depot.lire(CLE_CONNUS);
    expect(devis).not.toBeNull();
    expect(connus).not.toBeNull();
    return { depot, devis, connus, lire: jest.spyOn(depot, "lire"), ecrire: jest.spyOn(depot, "ecrire") };
  }

  test.each(ECHECS_QUI_SONT_UN_REFUS)(
    "%s (partout) : aucun devis, aucun numéro gardé n'est montré, rien n'est lu ni écrit ; les deux segments le disent",
    async (_nom, status, type, code) => {
      const { depot, devis, connus, lire, ecrire } = await avecCache();
      const transport = transportEnEchec(status, type, "refusé");

      const resultat = await creerChargeurDevis(config(transport, depot)).chargerDevis();

      expect(resultat.entrees).toEqual([]);
      expect(resultat.sources).toEqual([
        { segment: "won_pending_schedule", etat: { genre: "echouee", verdict: { code, detail: "refusé" }, refuse: true } },
        { segment: "quote_stale", etat: { genre: "echouee", verdict: { code, detail: "refusé" }, refuse: true } },
      ]);
      // Aucune requête de devis n'est faite pour un appareil refusé : les deux lectures de leads suffisent à le savoir.
      expect(transport).toHaveBeenCalledTimes(2);
      expect(lire).not.toHaveBeenCalled();
      expect(ecrire).not.toHaveBeenCalled();
      expect(await depot.lire(CLE_DEVIS)).toBe(devis);
      expect(await depot.lire(CLE_CONNUS)).toBe(connus);
    },
  );

  test("un refus de la requête dit par un refus technique (identité que la base ne confirme plus) : même arrêt", async () => {
    const { depot, lire } = await avecCache();
    const transport = fauxTransport({
      [OUTIL_LISTER_LEADS]: () => ({ ok: false, erreur: "refus_metier", details: "REJ-IDENTITE-APPAREIL-INVALIDE : rôle retiré" }),
    });
    const resultat = await creerChargeurDevis(config(transport, depot)).chargerDevis();
    expect(resultat.entrees).toEqual([]);
    expect(resultat.sources.map((s) => s.etat)).toEqual([
      { genre: "echouee", verdict: { code: "refus_metier", detail: "REJ-IDENTITE-APPAREIL-INVALIDE : rôle retiré" }, refuse: true },
      { genre: "echouee", verdict: { code: "refus_metier", detail: "REJ-IDENTITE-APPAREIL-INVALIDE : rôle retiré" }, refuse: true },
    ]);
    expect(lire).not.toHaveBeenCalled();
  });

  test.each(ECHECS_QUI_SONT_UNE_PANNE)(
    "%s (partout) : le serveur n'a pas pu répondre, les devis gardés sont servis, marqués",
    async (_nom, status, type, code) => {
      const { depot } = await avecCache();
      const resultat = await creerChargeurDevis(config(transportEnEchec(status, type), depot)).chargerDevis();
      expect(resultat.entrees.map((e) => e.etat.genre)).toEqual(["cache"]);
      expect(resultat.entrees[0].etat.genre === "cache" && resultat.entrees[0].etat.raisonHorsLigne.code).toBe(code);
      expect(resultat.sources.map((s) => s.etat.genre === "lue" && s.etat.depuisCache?.code)).toEqual([code, code]);
    },
  );

  test("un segment refusé pour une raison métier autre que « non calculable » n'arrête pas la lecture des devis connus", async () => {
    const { depot } = await avecCache();
    const transport = fauxTransport({
      [OUTIL_LISTER_LEADS]: () => enveloppeRefusee("REJ-SEGMENT-INCONNU", "segment inconnu"),
      [OUTIL_LIRE_DEVIS]: () => enveloppeAcceptee(D1),
    });
    const resultat = await creerChargeurDevis(config(transport, depot)).chargerDevis();
    expect(resultat.sources.map((s) => s.etat)).toEqual([
      { genre: "echouee", verdict: { code: "REJ-SEGMENT-INCONNU", detail: "segment inconnu" }, refuse: false },
      { genre: "echouee", verdict: { code: "REJ-SEGMENT-INCONNU", detail: "segment inconnu" }, refuse: false },
    ]);
    expect(resultat.entrees.map((e) => [e.connu.devisId, e.etat.genre])).toEqual([["devis-1", "serveur"]]);
  });

  test("un devis dont la lecture est refusée (403 sur m3_lire_devis seulement) : refus, le devis gardé n'est ni lu ni remplacé", async () => {
    const { depot, devis, ecrire } = await avecCache();
    const donnees = serveur({ converti: [leadBrut("lead-1", { segments: [SEGMENT_CONVERTI("devis-1")] })], perime: [], devis: { "devis-1": D1 } });
    const transport = jest.fn(async (params: { requete: { tool: string; args?: Record<string, unknown> } }) =>
      params.requete.tool === OUTIL_LIRE_DEVIS
        ? echecHttp(403, "tool_call_blocked", "hors portée")
        : { ok: true, result: donnees[OUTIL_LISTER_LEADS](params.requete.args ?? {}) },
    );
    const lireDevis = jest.spyOn(depot, "lire");

    const resultat = await creerChargeurDevis(config(transport, depot)).chargerDevis();

    expect(resultat.entrees.map((e) => e.etat)).toEqual([
      { genre: "refus", verdict: { code: "tool_call_blocked", detail: "hors portée" } },
    ]);
    expect(lireDevis.mock.calls.map((c) => c[0])).not.toContain(CLE_DEVIS);
    expect(ecrire).not.toHaveBeenCalledWith(CLE_DEVIS, expect.anything());
    expect(await depot.lire(CLE_DEVIS)).toBe(devis);
  });

  test.each(ECHECS_QUI_SONT_UN_REFUS)("ouvrirParNumero, %s : refus, rien n'est lu, écrit ni ajouté aux numéros connus", async (_nom, status, type, code) => {
    const { depot, connus, lire, ecrire } = await avecCache();

    const entree = await creerChargeurDevis(config(transportEnEchec(status, type, "refusé"), depot)).ouvrirParNumero("devis-1");

    expect(entree?.etat).toEqual({ genre: "refus", verdict: { code, detail: "refusé" } });
    expect(lire).not.toHaveBeenCalled();
    expect(ecrire).not.toHaveBeenCalled();
    expect(await depot.lire(CLE_CONNUS)).toBe(connus);
  });
});


describe("inventaire vendeur `m3_lister_devis`", () => {
  const page = (devis: Record<string, unknown>[], curseur_suivant: string | null) =>
    enveloppeAcceptee({ devis, curseur_suivant });

  test(
    "la page M3 courante remplace les IDs gardés, conserve tous les statuts et filtre les montants sensibles",
    async () => {
      const depot = new DepotCleValeurMemoire();
      const ancienne = lireDevisVendeur(devisInterneBrut("ancien-devis"))!;
      await ecrireCacheDevis(depot, "vendeur.a", ancienne, HORLOGE.maintenant.toISOString());
      await ecrireDevisConnus(depot, "vendeur.a", [
        { devisId: "ancien-devis", leadId: "lead-ancien", origine: "saisi" },
      ]);
      const transport = fauxTransport({
        [OUTIL_LISTER_DEVIS]: () =>
          page(
            [
              devisInterneBrut("M3-DEVIS-001", { statut: "brouillon" }),
              devisInterneBrut("M3-DEVIS-002", { statut: "envoye" }),
              devisInterneBrut("M3-DEVIS-003", { statut: "accepte" }),
            ],
            null,
          ),
      });

      const resultat = await creerChargeurDevis(config(transport, depot)).chargerInventaire();

      expect(resultat.entrees.map((entree) => [
        entree.connu.devisId,
        entree.connu.origine,
        entree.etat.genre === "serveur" ? entree.etat.devis.statut : "erreur",
      ])).toEqual([
        ["M3-DEVIS-001", "liste_vendeur", "brouillon"],
        ["M3-DEVIS-002", "liste_vendeur", "envoye"],
        ["M3-DEVIS-003", "liste_vendeur", "accepte"],
      ]);
      expect(resultat.etat.genre).toBe("serveur");
      expect(resultat.curseurSuivant).toBeNull();
      expect(JSON.stringify(resultat)).not.toMatch(/cout|marge|taux/i);
      expect(JSON.stringify(resultat)).not.toContain("ancien-devis");
      expect(transport).toHaveBeenCalledTimes(1);
      expect(transport.mock.calls[0][0].requete).toEqual({
        tool: OUTIL_LISTER_DEVIS,
        args: { limite: LIMITE_PAGE_LISTE_DEVIS },
      });
      expect(JSON.stringify(transport.mock.calls[0][0].requete)).not.toContain("vendeur.a");
    },
  );

  test("la suite envoie seulement le curseur opaque et ne duplique pas les pages", async () => {
    const transport = fauxTransport({
      [OUTIL_LISTER_DEVIS]: (args: Record<string, unknown>) => args.curseur === undefined
        ? page([devisInterneBrut("M3-DEVIS-001")], "suite-opaque")
        : page([devisInterneBrut("M3-DEVIS-002")], null),
    });
    const chargeur = creerChargeurDevis(config(transport));
    const premiere = await chargeur.chargerInventaire();
    const suite = await chargeur.chargerInventaire(premiere.curseurSuivant ?? undefined);

    expect(premiere.curseurSuivant).toBe("suite-opaque");
    expect(suite.entrees.map((e) => e.connu.devisId)).toEqual(["M3-DEVIS-002"]);
    expect(transport.mock.calls.map((appel) => appel[0].requete.args)).toEqual([
      { limite: LIMITE_PAGE_LISTE_DEVIS },
      { limite: LIMITE_PAGE_LISTE_DEVIS, curseur: "suite-opaque" },
    ]);
  });

  test("le chargeur arrête une suite dont le curseur ne progresse pas", async () => {
    const transport = fauxTransport({
      [OUTIL_LISTER_DEVIS]: () => page([devisInterneBrut("M3-DEVIS-001")], "curseur-courant"),
    });

    const resultat = await creerChargeurDevis(config(transport)).chargerInventaire("curseur-courant");

    expect(resultat.entrees).toEqual([]);
    expect(resultat.curseurSuivant).toBeNull();
    expect(resultat.etat.genre).toBe("illisible");
    expect(transport.mock.calls[0][0].requete.args).toEqual({
      limite: LIMITE_PAGE_LISTE_DEVIS,
      curseur: "curseur-courant",
    });
  });

  test("une page M3 au-delà de la borne ne produit aucune carte ni écriture de cache", async () => {
    const depot = new DepotCleValeurMemoire();
    const ecrire = jest.spyOn(depot, "ecrire");
    const devis = Array.from({ length: LIMITE_PAGE_LISTE_DEVIS + 1 }, (_, index) =>
      devisInterneBrut(`M3-DEVIS-${String(index).padStart(3, "0")}`),
    );
    const transport = fauxTransport({ [OUTIL_LISTER_DEVIS]: () => page(devis, null) });

    const resultat = await creerChargeurDevis(config(transport, depot)).chargerInventaire();

    expect(resultat.entrees).toEqual([]);
    expect(resultat.etat.genre).toBe("illisible");
    expect(ecrire).not.toHaveBeenCalled();
  });

  test("un refus du serveur purge les devis de cette personne, jamais ceux d'une autre", async () => {
    const depot = new DepotCleValeurMemoire();
    const devisA = lireDevisVendeur(devisInterneBrut("devis-a"))!;
    const devisB = lireDevisVendeur(devisInterneBrut("devis-b"))!;
    await ecrireCacheDevis(depot, "vendeur.a", devisA, HORLOGE.maintenant.toISOString());
    await ecrireCacheDevis(depot, "vendeur.b", devisB, HORLOGE.maintenant.toISOString());
    const transport = fauxTransport({
      [OUTIL_LISTER_DEVIS]: () => enveloppeRefusee("REJ-IDENTITE-APPAREIL-INVALIDE", "rôle retiré"),
    });

    const resultat = await creerChargeurDevis(config(transport, depot)).chargerInventaire();

    expect(resultat).toMatchObject({ entrees: [], curseurSuivant: null, etat: { genre: "refus" } });
    expect(await lireCacheDevis(depot, "vendeur.a", "devis-a")).toBeNull();
    expect(await lireCacheDevis(depot, "vendeur.b", "devis-b")).not.toBeNull();
  });

  test.each(ECHECS_QUI_SONT_UN_REFUS)(
    "un accès M3 refusé (%s) vide l'inventaire et purge les copies de cette personne",
    async (_nom, status, type) => {
      const depot = new DepotCleValeurMemoire();
      await ecrireCacheDevis(
        depot,
        "vendeur.a",
        lireDevisVendeur(devisInterneBrut("devis-a"))!,
        HORLOGE.maintenant.toISOString(),
      );
      await ecrireCacheDevis(
        depot,
        "vendeur.b",
        lireDevisVendeur(devisInterneBrut("devis-b"))!,
        HORLOGE.maintenant.toISOString(),
      );

      const resultat = await creerChargeurDevis(config(transportEnEchec(status, type), depot)).chargerInventaire();

      expect(resultat.entrees).toEqual([]);
      expect(resultat.curseurSuivant).toBeNull();
      expect(resultat.etat.genre).toBe("refus");
      expect(await lireCacheDevis(depot, "vendeur.a", "devis-a")).toBeNull();
      expect(await lireCacheDevis(depot, "vendeur.b", "devis-b")).not.toBeNull();
    },
  );

  test("hors ligne, la liste est indisponible et ne relit aucun cache par numéro", async () => {
    const depot = new DepotCleValeurMemoire();
    const devis = lireDevisVendeur(devisInterneBrut("devis-cache"))!;
    await ecrireCacheDevis(depot, "vendeur.a", devis, HORLOGE.maintenant.toISOString());
    const lire = jest.spyOn(depot, "lire");

    const resultat = await creerChargeurDevis(config(transportHorsLigne(), depot)).chargerInventaire();

    expect(resultat.entrees).toEqual([]);
    expect(resultat.curseurSuivant).toBeNull();
    expect(resultat.etat).toMatchObject({ genre: "indisponible" });
    expect(lire).not.toHaveBeenCalled();
  });

  test("réponse illisible ne sert jamais un cache ancien", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheDevis(
      depot,
      "vendeur.a",
      lireDevisVendeur(devisInterneBrut("devis-cache"))!,
      HORLOGE.maintenant.toISOString(),
    );
    const transport = fauxTransport({ [OUTIL_LISTER_DEVIS]: () => page([{ devis_id: "partiel" }], null) });

    const resultat = await creerChargeurDevis(config(transport, depot)).chargerInventaire();

    expect(resultat.entrees).toEqual([]);
    expect(resultat.etat).toMatchObject({ genre: "illisible" });
    expect(await lireCacheDevis(depot, "vendeur.a", "devis-cache")).toBeNull();
  });
});
