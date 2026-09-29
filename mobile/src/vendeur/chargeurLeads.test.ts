import { CODE_SEGMENT_NON_CALCULABLE, OUTIL_LISTER_LEADS } from "../m2/listeLeads";
import type { FiltreLeads } from "../m2/listeLeads";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { lireCacheLeads } from "./cache";
import { creerChargeurLeads } from "./chargeurLeads";
import type { ConfigurationChargeurVendeur } from "./appel";
import {
  NON_CALCULABLES_FICTIFS,
  enveloppeAcceptee,
  enveloppeRefusee,
  fauxTransport,
  leadBrut,
  pageBrute,
  transportHorsLigne,
} from "./donneesDeTest";

const AUCUN: FiltreLeads = { statut: null, segment: null };
const MAINTENANT = new Date("2026-09-29T18:03:22.000Z");
const HORLOGE = { maintenant: MAINTENANT, decalageMinutesUTC: -240 };

function config(
  appelerOutil: jest.Mock,
  depot: DepotCleValeur = new DepotCleValeurMemoire(),
  personne = "vendeur.a",
): ConfigurationChargeurVendeur {
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

/** 7 leads du vendeur, servis par pages de 3 comme le fait la borne de sortie du serveur. */
const TOUS = Array.from({ length: 7 }, (_, i) => leadBrut(`lead-${i}`));
function serveurParPages(filtre: FiltreLeads = AUCUN) {
  return (args: Record<string, unknown>) => {
    const decalage = typeof args.decalage === "number" ? args.decalage : 0;
    return enveloppeAcceptee(pageBrute({ leads: TOUS.slice(decalage, decalage + 3), decalage, total: 7, filtre }));
  };
}

describe("chargerLeads — en ligne", () => {
  test("succès : source serveur, première page, cache écrit sous la personne, date de l'appareil", async () => {
    const depot = new DepotCleValeurMemoire();
    const transport = fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages() });
    const chargeur = creerChargeurLeads(config(transport, depot));

    const resultat = await chargeur.chargerLeads(AUCUN);

    expect(resultat.source).toBe("serveur");
    if (resultat.source !== "serveur") {
      return;
    }
    expect(resultat.lus.leads.map((l) => l.leadId)).toEqual(["lead-0", "lead-1", "lead-2"]);
    expect(resultat.lus).toMatchObject({ total: 7, suivant: 3, reste: 4, misAJourLe: "2026-09-29T18:03:22.000Z" });
    expect((await lireCacheLeads(depot, "vendeur.a", AUCUN))?.leads).toHaveLength(3);
    expect(await lireCacheLeads(depot, "vendeur.b", AUCUN)).toBeNull();
  });

  test("l'appel : le bon outil, l'instant de l'appareil, aucun argument qui désigne une personne, aucune clé d'idempotence", async () => {
    const transport = fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages({ statut: "qualifie", segment: "hot_lead" }) });
    await creerChargeurLeads(config(transport)).chargerLeads({ statut: "qualifie", segment: "hot_lead" });

    const params = transport.mock.calls[0][0];
    expect(params.urlBase).toBe("https://grs.exemple.ca");
    expect(params.jeton).toBe("jeton-vendeur");
    expect(params.requete).toEqual({
      tool: "m2_lister_leads",
      args: { horodatage: "2026-09-29T14:03:22-04:00", statut: "qualifie", segment: "hot_lead" },
    });
    expect(params.requete.idempotencyKey).toBeUndefined();
    expect(JSON.stringify(params.requete)).not.toContain("vendeur.a");
  });

  test("les pages se lisent bout à bout : 7 leads en 3 pages, chacun une fois, cache mis à jour à chaque page", async () => {
    const depot = new DepotCleValeurMemoire();
    const transport = fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages() });
    const chargeur = creerChargeurLeads(config(transport, depot));

    const premiere = await chargeur.chargerLeads(AUCUN);
    if (premiere.source !== "serveur") {
      throw new Error("première page attendue en ligne");
    }
    let courant = premiere.lus;
    const rangsDemandes: unknown[] = [];
    while (courant.suivant !== null) {
      const suite = await chargeur.chargerSuite(courant);
      expect(suite.genre).toBe("fusionnee");
      if (suite.genre !== "fusionnee") {
        return;
      }
      courant = suite.lus;
      rangsDemandes.push(transport.mock.calls[transport.mock.calls.length - 1][0].requete.args.decalage);
      expect((await lireCacheLeads(depot, "vendeur.a", AUCUN))?.leads.length).toBe(courant.leads.length);
    }
    expect(rangsDemandes).toEqual([3, 6]);
    expect(courant.leads.map((l) => l.leadId)).toEqual(TOUS.map((l) => l.lead_id));
    expect(courant).toMatchObject({ total: 7, suivant: null, reste: 0 });
  });

  test("« Voir plus » sans suite : rien à demander, aucun appel", async () => {
    const transport = fauxTransport({
      [OUTIL_LISTER_LEADS]: () => enveloppeAcceptee(pageBrute({ leads: [leadBrut("seul")] })),
    });
    const chargeur = creerChargeurLeads(config(transport));
    const resultat = await chargeur.chargerLeads(AUCUN);
    if (resultat.source !== "serveur") {
      throw new Error("première page attendue en ligne");
    }
    expect(resultat.lus.suivant).toBeNull();
    expect(await chargeur.chargerSuite(resultat.lus)).toEqual({ genre: "sans_suite" });
    expect(transport).toHaveBeenCalledTimes(1);
  });

  test("la suite : les rangs ont glissé (le total change) -> à relire, le cache n'est pas touché", async () => {
    const depot = new DepotCleValeurMemoire();
    let total = 7;
    const transport = fauxTransport({
      [OUTIL_LISTER_LEADS]: (args) => {
        const decalage = typeof args.decalage === "number" ? args.decalage : 0;
        return enveloppeAcceptee(pageBrute({ leads: TOUS.slice(decalage, decalage + 3), decalage, total }));
      },
    });
    const chargeur = creerChargeurLeads(config(transport, depot));
    const premiere = await chargeur.chargerLeads(AUCUN);
    if (premiere.source !== "serveur") {
      throw new Error("première page attendue en ligne");
    }
    const cacheAvant = await depot.lire("vendeur:vendeur.a:leads:*|*_v1");

    total = 8;
    const suite = await chargeur.chargerSuite(premiere.lus);

    expect(suite).toEqual({ genre: "a_relire", raison: "liste_changee" });
    expect(await depot.lire("vendeur:vendeur.a:leads:*|*_v1")).toBe(cacheAvant);
  });

  test("la suite : le serveur ne répond pas -> échec avec le verdict, les leads lus restent", async () => {
    const transport = fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages() });
    const chargeur = creerChargeurLeads(config(transport));
    const premiere = await chargeur.chargerLeads(AUCUN);
    if (premiere.source !== "serveur") {
      throw new Error("première page attendue en ligne");
    }
    const horsLigne = creerChargeurLeads(config(transportHorsLigne()));
    expect(await horsLigne.chargerSuite(premiere.lus)).toEqual({
      genre: "echec",
      verdict: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });
});

describe("chargerLeads — hors ligne : le cache est un cache, dit comme tel", () => {
  async function avecCache(personne = "vendeur.a") {
    const depot = new DepotCleValeurMemoire();
    const chargeur = creerChargeurLeads(config(fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages() }), depot, personne));
    const premiere = await chargeur.chargerLeads(AUCUN);
    if (premiere.source === "serveur") {
      await chargeur.chargerSuite(premiere.lus);
    }
    return depot;
  }

  test("réseau tombé avec un cache : source cache, mêmes leads, date du cache et raison portées", async () => {
    const depot = await avecCache();
    const horsLigne = creerChargeurLeads({
      ...config(transportHorsLigne(), depot),
      horloge: () => ({ maintenant: new Date("2026-09-30T12:00:00.000Z"), decalageMinutesUTC: -240 }),
    });

    const resultat = await horsLigne.chargerLeads(AUCUN);

    expect(resultat.source).toBe("cache");
    if (resultat.source === "cache") {
      expect(resultat.lus.leads.map((l) => l.leadId)).toEqual(["lead-0", "lead-1", "lead-2", "lead-3", "lead-4", "lead-5"]);
      expect(resultat.lus.misAJourLe).toBe("2026-09-29T18:03:22.000Z"); // la date du cache, pas celle d'aujourd'hui
      expect(resultat.raisonHorsLigne).toEqual({ code: "erreur_reseau", detail: "Network request failed" });
    }
  });

  test("réseau tombé SANS cache : aucune, jamais une liste inventée", async () => {
    const resultat = await creerChargeurLeads(config(transportHorsLigne())).chargerLeads(AUCUN);
    expect(resultat).toEqual({ source: "aucune", raison: { code: "erreur_reseau", detail: "Network request failed" } });
  });

  test("le cache d'une AUTRE personne sur le même téléphone n'est jamais servi", async () => {
    const depot = await avecCache("vendeur.a");
    const resultat = await creerChargeurLeads(config(transportHorsLigne(), depot, "vendeur.b")).chargerLeads(AUCUN);
    expect(resultat.source).toBe("aucune");
  });

  test("un autre filtre n'est pas servi par le cache du filtre sans filtre", async () => {
    const depot = await avecCache();
    const resultat = await creerChargeurLeads(config(transportHorsLigne(), depot)).chargerLeads({ statut: "nouveau", segment: null });
    expect(resultat.source).toBe("aucune");
  });

  test("sortie tronquée ou réponse illisible : le cache prend le relais, avec la raison", async () => {
    const depot = await avecCache();
    for (const [reponse, code] of [
      [{ ok: true, tronque: true, apercu: "{" }, "reponse_tronquee"],
      [{ ok: true, resultat: { accepte: true, resultat: { total: "x" } } }, "reponse_illisible"],
      [{ ok: false, erreur: "budget_epuise", details: "trop" }, "budget_epuise"],
    ] as const) {
      const resultat = await creerChargeurLeads(config(fauxTransport({ [OUTIL_LISTER_LEADS]: () => reponse }), depot)).chargerLeads(AUCUN);
      expect(resultat.source).toBe("cache");
      expect(resultat.source === "cache" && resultat.raisonHorsLigne.code).toBe(code);
    }
  });

  test("la passerelle refuse l'outil (403) : la raison est dite, le cache éventuel est montré comme cache", async () => {
    const depot = await avecCache();
    const resultat = await creerChargeurLeads(config(fauxTransport({}), depot)).chargerLeads(AUCUN);
    expect(resultat.source === "cache" && resultat.raisonHorsLigne.code).toBe("tool_call_blocked");
  });

  test("un cache abîmé n'est pas servi : aucune", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("vendeur:vendeur.a:leads:*|*_v1", '{"pages":[{"total":"x"}],"misAJourLe":"2026-09-29T18:00:00.000Z"}');
    const resultat = await creerChargeurLeads(config(transportHorsLigne(), depot)).chargerLeads(AUCUN);
    expect(resultat.source).toBe("aucune");
  });
});

describe("chargerLeads — le refus du serveur n'est ni un cache ni une liste vide", () => {
  test("un segment non calculable : refus avec le « manque X » du serveur, le cache n'est PAS servi", async () => {
    const depot = new DepotCleValeurMemoire();
    const filtre = { statut: null, segment: "quote_sent" };
    const detail = "segment quote_sent : non calculable, manque le fait « devis envoyé » de M3 (m3.devis_envoye, T4.7)";
    // Un cache existe (d'avant) pour ce filtre : il ne doit pas cacher le refus d'aujourd'hui.
    await creerChargeurLeads(
      config(fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages(filtre) }), depot),
    ).chargerLeads(filtre);
    expect(await lireCacheLeads(depot, "vendeur.a", filtre)).not.toBeNull();

    const resultat = await creerChargeurLeads(
      config(fauxTransport({ [OUTIL_LISTER_LEADS]: () => enveloppeRefusee(CODE_SEGMENT_NON_CALCULABLE, detail) }), depot),
    ).chargerLeads(filtre);

    expect(resultat).toEqual({ source: "refus", verdict: { code: "REJ-SEGMENT-NON-CALCULABLE", detail } });
  });

  test("identité invalide (rôle retiré) : refus, pas de cache", async () => {
    const resultat = await creerChargeurLeads(
      config(fauxTransport({ [OUTIL_LISTER_LEADS]: () => enveloppeRefusee("REJ-IDENTITE-APPAREIL-INVALIDE", "rôle retiré") })),
    ).chargerLeads(AUCUN);
    expect(resultat).toMatchObject({ source: "refus", verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" } });
  });

  test("le serveur répond pour un autre filtre que celui demandé : ce n'est pas la liste demandée", async () => {
    const resultat = await creerChargeurLeads(
      config(fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages({ statut: "nouveau", segment: null }) })),
    ).chargerLeads(AUCUN);
    expect(resultat).toMatchObject({ source: "aucune", raison: { code: "reponse_illisible" } });
  });

  test("la page rend aussi les segments non calculables de tous les leads, jamais perdus", async () => {
    const transport = fauxTransport({
      [OUTIL_LISTER_LEADS]: () =>
        enveloppeAcceptee(pageBrute({ leads: [leadBrut("l1")], nonCalculables: NON_CALCULABLES_FICTIFS })),
    });
    const resultat = await creerChargeurLeads(config(transport)).chargerLeads(AUCUN);
    expect(resultat.source === "serveur" && resultat.lus.segmentsNonCalculables).toEqual(NON_CALCULABLES_FICTIFS);
  });
});

describe("le cache est facultatif : sa panne ne cache pas une lecture réussie", () => {
  test("écriture impossible : la lecture est rendue quand même", async () => {
    const depot: DepotCleValeur = {
      lire: async () => null,
      ecrire: async () => {
        throw new Error("disque plein");
      },
    };
    const espion = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const resultat = await creerChargeurLeads(config(fauxTransport({ [OUTIL_LISTER_LEADS]: serveurParPages() }), depot)).chargerLeads(AUCUN);
    expect(resultat.source).toBe("serveur");
    expect(espion).toHaveBeenCalled();
    espion.mockRestore();
  });
});
