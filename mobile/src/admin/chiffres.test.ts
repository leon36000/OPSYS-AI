import { OUTIL_ECHEANCES_FISCALES, OUTIL_ETAT_TRESORERIE, OUTIL_PREVOIR_TRESORERIE } from "../m5/tresorerie";
import type { PrevisionTresorerie } from "../m5/tresorerie";
import { OUTIL_VUE_EXECUTIVE } from "../m8/vueExecutive";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { lireCacheSection } from "./cache";
import { creerChargeurChiffres, sectionEcheances, sectionPrevision, SECTION_TRESORERIE, SECTION_VUE_EXECUTIVE } from "./chiffres";
import {
  config,
  echecHttp,
  enveloppeCouple,
  enveloppeEnErreur,
  enveloppeRefusee,
  fauxTransport,
  reponse,
  transportEnEchec,
  transportHorsLigne,
} from "./donneesDeTest";

/** Le serveur du propriétaire : les quatre outils de « Chiffres », et la suite de la prévision par son rang. */
function serveur(surcharges: Record<string, (args: Record<string, unknown>) => unknown> = {}) {
  return fauxTransport({
    [OUTIL_VUE_EXECUTIVE]: () => reponse("vue_executive"),
    [OUTIL_ETAT_TRESORERIE]: () => reponse("tresorerie"),
    [OUTIL_PREVOIR_TRESORERIE]: (args) => reponse(args.depart === undefined ? "prevision" : "prevision_longue_page_2"),
    [OUTIL_ECHEANCES_FISCALES]: () => reponse("echeances"),
    ...surcharges,
  });
}

async function premierePageLongue(): Promise<PrevisionTresorerie> {
  const transport = serveur({ [OUTIL_PREVOIR_TRESORERIE]: () => reponse("prevision_longue_page_1") });
  const lu = await creerChargeurChiffres(config(transport)).chargerPrevision();
  if (lu.source !== "serveur" || lu.valeur.genre !== "prevision") {
    throw new Error("la première page devrait être lue");
  }
  return lu.valeur;
}

describe("les quatre sections de « Chiffres », chacune lue pour elle-même", () => {
  test("chacune part avec le nom nu de son outil et ses arguments exacts : le jour de l'appareil pour M5, rien pour M8", async () => {
    const transport = serveur();
    const chargeur = creerChargeurChiffres(config(transport));

    await chargeur.chargerVueExecutive();
    await chargeur.chargerTresorerie();
    await chargeur.chargerPrevision();
    await chargeur.chargerEcheances();

    expect(transport.mock.calls.map((appel) => appel[0].requete)).toEqual([
      { tool: "m8_lire_vue_executive", args: {} },
      { tool: "m5_etat_tresorerie", args: {} },
      { tool: "m5_prevoir_tresorerie", args: { aujourd_hui: "2026-09-29" } },
      { tool: "m5_lire_echeances_fiscales", args: { aujourd_hui: "2026-09-29" } },
    ]);
  });

  test("le jour de référence est celui de l'heure LOCALE de l'appareil : 22 h 30 à Montréal est encore le jour même", async () => {
    const transport = serveur();
    const horloge = { maintenant: new Date("2026-09-30T02:30:00.000Z"), decalageMinutesUTC: -240 };
    await creerChargeurChiffres(config(transport, { horloge })).chargerEcheances();
    expect(transport.mock.calls[0][0].requete.args).toEqual({ aujourd_hui: "2026-09-29" });
    const lendemain = { maintenant: new Date("2026-09-30T04:00:00.000Z"), decalageMinutesUTC: -240 };
    const suivant = serveur();
    await creerChargeurChiffres(config(suivant, { horloge: lendemain })).chargerPrevision();
    expect(suivant.mock.calls[0][0].requete.args).toEqual({ aujourd_hui: "2026-09-30" });
  });

  test("les définitions de section : outil, arguments et nom de cache", () => {
    expect(SECTION_VUE_EXECUTIVE).toMatchObject({ outil: "m8_lire_vue_executive", args: {}, cache: "vue_executive" });
    expect(SECTION_TRESORERIE).toMatchObject({ outil: "m5_etat_tresorerie", args: {}, cache: "tresorerie" });
    expect(sectionPrevision("2026-09-29")).toMatchObject({ outil: "m5_prevoir_tresorerie", args: { aujourd_hui: "2026-09-29" }, cache: "prevision" });
    expect(sectionEcheances("2026-09-29")).toMatchObject({ outil: "m5_lire_echeances_fiscales", args: { aujourd_hui: "2026-09-29" }, cache: "echeances" });
  });

  test("en ligne : les quatre sections sont lues et gardées, sous la personne", async () => {
    const depot = new DepotCleValeurMemoire();
    const chargeur = creerChargeurChiffres(config(serveur(), { depot }));

    const [vue, tresorerie, prevision, echeances] = await Promise.all([
      chargeur.chargerVueExecutive(),
      chargeur.chargerTresorerie(),
      chargeur.chargerPrevision(),
      chargeur.chargerEcheances(),
    ]);

    for (const lu of [vue, tresorerie, prevision, echeances]) {
      expect(lu.source).toBe("serveur");
    }
    for (const nom of ["vue_executive", "tresorerie", "prevision", "echeances"]) {
      expect(await lireCacheSection(depot, "nathan", nom)).not.toBeNull();
      expect(await lireCacheSection(depot, "sophie", nom)).toBeNull();
    }
  });

  test("UNE SECTION QUI ÉCHOUE NE CACHE PAS LES AUTRES : refus de M5 (à déclarer), cache pour M8, serveur pour le reste", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChiffres(config(serveur(), { depot })).chargerVueExecutive();
    const transport = jest.fn(async (params: { requete: { tool: string; args?: Record<string, unknown> } }) => {
      switch (params.requete.tool) {
        case OUTIL_VUE_EXECUTIVE:
          return echecHttp(503);
        case OUTIL_PREVOIR_TRESORERIE:
          return { ok: true, result: reponse("prevision_horizon_a_declarer") };
        case OUTIL_ECHEANCES_FISCALES:
          return { ok: true, result: reponse("echeances_frequence_a_declarer") };
        default:
          return { ok: true, result: reponse("tresorerie") };
      }
    });
    const chargeur = creerChargeurChiffres(config(transport, { depot }));

    const [vue, tresorerie, prevision, echeances] = await Promise.all([
      chargeur.chargerVueExecutive(),
      chargeur.chargerTresorerie(),
      chargeur.chargerPrevision(),
      chargeur.chargerEcheances(),
    ]);

    expect(vue).toMatchObject({ source: "cache", raisonHorsLigne: { code: "http_503" } });
    expect(tresorerie.source).toBe("serveur");
    expect(prevision).toMatchObject({ source: "refus", verdict: { code: "REJ-PREVISION-HORIZON-A-CONFIGURER" } });
    expect(echeances).toMatchObject({ source: "refus", verdict: { code: "REJ-FISCAL-FREQUENCE-A-DECLARER" } });
  });

  test("un refus de M5 (« à déclarer ») n'est pas remplacé par la dernière prévision gardée, même si elle existe", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChiffres(config(serveur(), { depot })).chargerPrevision();
    expect(await lireCacheSection(depot, "nathan", "prevision")).not.toBeNull();

    const refus = await creerChargeurChiffres(
      config(fauxTransport({ [OUTIL_PREVOIR_TRESORERIE]: () => reponse("prevision_horizon_a_declarer") }), { depot }),
    ).chargerPrevision();

    expect(refus).toMatchObject({ source: "refus", verdict: { code: "REJ-PREVISION-HORIZON-A-CONFIGURER" } });
    expect(await lireCacheSection(depot, "nathan", "prevision")).not.toBeNull(); // le cache reste, il n'est simplement pas servi
  });

  test("hors ligne, la trésorerie gardée est rendue avec sa date et la raison, jamais comme une lecture fraîche", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChiffres(config(serveur(), { depot })).chargerTresorerie();

    const lu = await creerChargeurChiffres(config(transportHorsLigne(), { depot })).chargerTresorerie();

    expect(lu).toMatchObject({ source: "cache", misAJourLe: "2026-09-29T18:03:22.000Z", raisonHorsLigne: { code: "erreur_reseau" } });
    expect(lu.source === "cache" && lu.valeur.cashLibre?.montant).toBe("14106.32");
  });

  test("le cache d'un état de trésorerie est relu par le même lecteur : le « 0 » gelé d'un registre vide n'y devient pas un solde", async () => {
    const depot = new DepotCleValeurMemoire();
    const serveurVide = serveur({ [OUTIL_ETAT_TRESORERIE]: () => reponse("tresorerie_sans_solde") });
    await creerChargeurChiffres(config(serveurVide, { depot })).chargerTresorerie();

    const lu = await creerChargeurChiffres(config(transportHorsLigne(), { depot })).chargerTresorerie();

    expect(lu.source === "cache" && lu.valeur.solde.genre).toBe("inconnu");
  });

  test("la personne désactivée : refus de M8 (refus_metier) et de M5 (verdict), jamais le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChiffres(config(serveur(), { depot })).chargerVueExecutive();
    await creerChargeurChiffres(config(serveur(), { depot })).chargerTresorerie();
    const desactivee = fauxTransport({
      [OUTIL_VUE_EXECUTIVE]: () => reponse("refus_identite_vue_executive"),
      [OUTIL_ETAT_TRESORERIE]: () => reponse("refus_identite_tresorerie"),
    });
    const chargeur = creerChargeurChiffres(config(desactivee, { depot }));

    expect(await chargeur.chargerVueExecutive()).toMatchObject({ source: "refus", verdict: { code: "refus_metier" } });
    expect(await chargeur.chargerTresorerie()).toMatchObject({ source: "refus", verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" } });
  });
});

describe("« Voir plus » : les semaines qui suivent", () => {
  test("sans suite à lire, aucun appel n'est fait", async () => {
    const transport = serveur();
    const lu = await creerChargeurChiffres(config(transport)).chargerPrevision();
    if (lu.source !== "serveur" || lu.valeur.genre !== "prevision") {
      throw new Error("prévision attendue");
    }
    transport.mockClear();

    expect(await creerChargeurChiffres(config(transport)).chargerSuitePrevision(lu.valeur)).toEqual({ genre: "sans_suite" });
    expect(transport).not.toHaveBeenCalled();
  });

  test("la page demandée est celle du rang que M5 a dit, pour le MÊME jour de référence que la première page ; elle se recolle", async () => {
    const premiere = await premierePageLongue();
    const transport = serveur();
    // L'appareil a changé de jour entre les deux lectures : la suite garde le jour de la première page.
    const lendemain = { maintenant: new Date("2026-09-30T18:00:00.000Z"), decalageMinutesUTC: -240 };

    const suite = await creerChargeurChiffres(config(transport, { horloge: lendemain })).chargerSuitePrevision(premiere);

    expect(transport.mock.calls[0][0].requete).toEqual({ tool: "m5_prevoir_tresorerie", args: { aujourd_hui: "2026-09-29", depart: 19 } });
    expect(suite.genre).toBe("fusionnee");
    expect(suite.genre === "fusionnee" && suite.prevision.semaines).toHaveLength(26);
    expect(suite.genre === "fusionnee" && suite.prevision.prochainDepart).toBeNull();
  });

  test("la suite ne s'écrit pas au cache : hors ligne, elle n'est pas inventée", async () => {
    const premiere = await premierePageLongue();
    const depot = new DepotCleValeurMemoire();
    await creerChargeurChiffres(config(serveur(), { depot })).chargerSuitePrevision(premiere);
    expect(await lireCacheSection(depot, "nathan", "prevision")).toBeNull();
  });

  test("une prévision refaite entre-temps : la page ne se recolle pas, l'écran relit depuis le début", async () => {
    const premiere = await premierePageLongue();
    const autre = reponse("prevision_longue_page_2");
    autre.resultat.resultat.prevision_id = "e".repeat(64);

    const suite = await creerChargeurChiffres(config(serveur({ [OUTIL_PREVOIR_TRESORERIE]: () => autre }))).chargerSuitePrevision(premiere);

    expect(suite).toEqual({ genre: "a_relire", raison: "prevision_changee" });
  });

  test("le serveur ne répond pas : l'échec est dit, les semaines déjà lues restent, rien n'est inventé", async () => {
    const premiere = await premierePageLongue();
    expect(await creerChargeurChiffres(config(transportHorsLigne())).chargerSuitePrevision(premiere)).toEqual({
      genre: "echec",
      verdict: { code: "erreur_reseau", detail: "Network request failed" },
    });
    expect(await creerChargeurChiffres(config(transportEnEchec(500, "tool_error", "panne"))).chargerSuitePrevision(premiere)).toEqual({
      genre: "echec",
      verdict: { code: "tool_error", detail: "panne" },
    });
  });

  test("une page illisible ou tronquée est un échec, pas une page vide", async () => {
    const premiere = await premierePageLongue();
    for (const brut of [enveloppeCouple({ type: "PREVISION_TRESORERIE" }), { ok: true, tronque: true, apercu: "{" }]) {
      const suite = await creerChargeurChiffres(config(serveur({ [OUTIL_PREVOIR_TRESORERIE]: () => brut }))).chargerSuitePrevision(premiere);
      expect(suite.genre).toBe("echec");
    }
  });

  test("un refus (porte d'appareil ou outil) est un refus, avec son verdict", async () => {
    const premiere = await premierePageLongue();
    expect(await creerChargeurChiffres(config(transportEnEchec(403, "tool_call_blocked", "hors portée"))).chargerSuitePrevision(premiere)).toEqual({
      genre: "refus",
      verdict: { code: "tool_call_blocked", detail: "hors portée" },
    });
    const refusOutil = serveur({ [OUTIL_PREVOIR_TRESORERIE]: () => enveloppeRefusee("REJ-PREVISION-DEPART-INVALIDE", "depart hors de l'horizon") });
    expect(await creerChargeurChiffres(config(refusOutil)).chargerSuitePrevision(premiere)).toEqual({
      genre: "refus",
      verdict: { code: "REJ-PREVISION-DEPART-INVALIDE", detail: "depart hors de l'horizon" },
    });
    const enErreur = serveur({ [OUTIL_PREVOIR_TRESORERIE]: () => enveloppeEnErreur("arguments_invalides", ["depart : minimum 0"]) });
    expect(await creerChargeurChiffres(config(enErreur)).chargerSuitePrevision(premiere)).toMatchObject({ genre: "refus" });
  });
});
