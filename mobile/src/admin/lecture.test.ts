import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { ecrireCacheSection, lireCacheSection } from "./cache";
import { config, enveloppeCouple, enveloppeEnErreur, enveloppeRefusee, fauxTransport, transportEnEchec, transportHorsLigne } from "./donneesDeTest";
import { interpreter } from "./enveloppe";
import { lireSection } from "./lecture";
import type { DefinitionSection } from "./lecture";

/** Une section de test : la valeur est un objet `{n: <entier>}`, en forme `couple`. */
const SECTION: DefinitionSection<{ n: number }> = {
  outil: "m5_etat_tresorerie",
  args: { aujourd_hui: "2026-09-29" },
  cache: "section_de_test",
  interpreter: (brut) =>
    interpreter(brut, "couple", (v) => {
      const n = (v as { n?: unknown }).n;
      return typeof n === "number" ? { n } : null;
    }),
};
const OUTIL = SECTION.outil;
const HORS_LIGNE = { code: "erreur_reseau", detail: "Network request failed" };

function serveurQuiRepond(reponse: unknown) {
  return fauxTransport({ [OUTIL]: () => reponse });
}

describe("lireSection : la lecture d'une section, ses quatre issues", () => {
  test("un interprète de cache opt-in ne sert jamais à interpréter la réponse du transport", async () => {
    const depot = new DepotCleValeurMemoire();
    const interpreterCache = jest.fn(() => ({ ok: true as const, valeur: { n: 42 } }));
    const section = { ...SECTION, interpreterCache };
    expect(await lireSection(config(serveurQuiRepond(enveloppeCouple({ n: 7 })), { depot }), section))
      .toMatchObject({ source: "serveur", valeur: { n: 7 } });
    expect(interpreterCache).not.toHaveBeenCalled();
    expect(await lireSection({ ...config(transportHorsLigne(), { depot }), enLigne: () => false }, section))
      .toMatchObject({ source: "cache", valeur: { n: 42 } });
    expect(interpreterCache).toHaveBeenCalledTimes(1);
  });
  test("déconnexion connue : cache personnel daté, sans appeler le réseau", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");
    const transport = serveurQuiRepond(enveloppeCouple({ n: 9 }));
    const lu = await lireSection({ ...config(transport, { depot }), enLigne: () => false }, SECTION);
    expect(transport).not.toHaveBeenCalled();
    expect(lu).toMatchObject({ source: "cache", valeur: { n: 5 }, misAJourLe: "2026-09-28T12:00:00.000Z", raisonHorsLigne: { code: "hors_ligne" } });
    const autre = await lireSection({ ...config(transport, { depot, personne: "autre.fictif" }), enLigne: () => false }, SECTION);
    expect(autre).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
    expect(transport).not.toHaveBeenCalled();
  });
  test("SERVEUR : la valeur lue, la date de l'appareil, et le cache écrit", async () => {
    const depot = new DepotCleValeurMemoire();
    const c = config(serveurQuiRepond(enveloppeCouple({ n: 7 })), { depot });

    const lu = await lireSection(c, SECTION);

    expect(lu).toEqual({ source: "serveur", valeur: { n: 7 }, misAJourLe: "2026-09-29T18:03:22.000Z" });
    expect(await lireCacheSection(depot, "nathan", "section_de_test")).toEqual({
      resultat: enveloppeCouple({ n: 7 }),
      misAJourLe: "2026-09-29T18:03:22.000Z",
    });
  });

  test("l'appel part avec le nom nu et les arguments exacts de la section", async () => {
    const transport = serveurQuiRepond(enveloppeCouple({ n: 1 }));
    await lireSection(config(transport), SECTION);
    expect(transport.mock.calls[0][0].requete).toEqual({ tool: OUTIL, args: { aujourd_hui: "2026-09-29" } });
  });

  test("CACHE : le réseau tombe, le cache de CETTE section et de CETTE personne est rendu avec sa date et la raison", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");

    const lu = await lireSection(config(transportHorsLigne(), { depot }), SECTION);

    expect(lu).toEqual({ source: "cache", valeur: { n: 5 }, misAJourLe: "2026-09-28T12:00:00.000Z", raisonHorsLigne: HORS_LIGNE });
  });

  test.each([
    ["un 500 du core", transportEnEchec(500, "tool_error", "tool execution failed"), { code: "tool_error", detail: "tool execution failed" }],
    ["un 503 de la passerelle", transportEnEchec(503), { code: "http_503", detail: "réponse HTTP 503 inattendue" }],
    ["un 429 (débit)", transportEnEchec(429, "tool_error", "trop de requêtes"), { code: "tool_error", detail: "trop de requêtes" }],
  ])("CACHE : %s n'est pas un refus, le cache sert", async (_nom, transport, raison) => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");
    const lu = await lireSection(config(transport, { depot }), SECTION);
    expect(lu).toMatchObject({ source: "cache", valeur: { n: 5 }, raisonHorsLigne: raison });
  });

  test("AUCUNE : ni serveur ni cache, la raison est dite et aucune valeur n'est inventée", async () => {
    const lu = await lireSection(config(transportHorsLigne()), SECTION);
    expect(lu).toEqual({ source: "aucune", raison: HORS_LIGNE });
  });

  test("REFUS de la porte (403) : le cache ne le remplace JAMAIS, et reste tel quel", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");

    const lu = await lireSection(config(transportEnEchec(403, "tool_call_blocked", "hors portée"), { depot }), SECTION);

    expect(lu).toEqual({ source: "refus", verdict: { code: "tool_call_blocked", detail: "hors portée" } });
    expect((await lireCacheSection(depot, "nathan", "section_de_test"))?.misAJourLe).toBe("2026-09-28T12:00:00.000Z");
  });

  test("REFUS d'un jeton révoqué (401) : jamais le cache d'un appareil qu'on vient de refuser", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");
    const lu = await lireSection(config(transportEnEchec(401), { depot }), SECTION);
    expect(lu).toEqual({ source: "refus", verdict: { code: "http_401", detail: "réponse HTTP 401 inattendue" } });
  });

  test("REFUS de l'outil (`accepte: false`) : son verdict tel quel, jamais le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");

    const lu = await lireSection(
      config(serveurQuiRepond(enveloppeRefusee("REJ-FISCAL-FREQUENCE-A-DECLARER", "la déclarer dans configuration.fiscal")), { depot }),
      SECTION,
    );

    expect(lu).toEqual({ source: "refus", verdict: { code: "REJ-FISCAL-FREQUENCE-A-DECLARER", detail: "la déclarer dans configuration.fiscal" } });
  });

  test("REFUS `refus_metier` (personne désactivée) : jamais le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");
    const lu = await lireSection(
      config(serveurQuiRepond(enveloppeEnErreur("refus_metier", "REJ-IDENTITE-APPAREIL-INVALIDE : personne inactive")), { depot }),
      SECTION,
    );
    expect(lu).toMatchObject({ source: "refus", verdict: { code: "refus_metier" } });
  });

  test("un refus n'écrit rien dans le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await lireSection(config(transportEnEchec(403, "tool_call_blocked"), { depot }), SECTION);
    await lireSection(config(serveurQuiRepond(enveloppeRefusee("REJ-X")), { depot }), SECTION);
    expect(await lireCacheSection(depot, "nathan", "section_de_test")).toBeNull();
  });

  test.each([
    ["une sortie tronquée", { ok: true, tronque: true, apercu: "{" }, "reponse_tronquee"],
    ["une réponse illisible", { ok: true, resultat: { accepte: true, resultat: { n: "sept" } } }, "reponse_illisible"],
    ["une panne passagère de l'instance", enveloppeEnErreur("outil_inconnu", "m5_etat_tresorerie"), "outil_inconnu"],
  ])("CACHE : %s n'est pas un refus, le cache sert avec la raison", async (_nom, brut, code) => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");

    const lu = await lireSection(config(serveurQuiRepond(brut), { depot }), SECTION);

    expect(lu).toMatchObject({ source: "cache", valeur: { n: 5 }, raisonHorsLigne: { code } });
  });

  test("une réponse illisible sans cache : aucune, avec sa raison ; rien n'est écrit", async () => {
    const depot = new DepotCleValeurMemoire();
    const lu = await lireSection(config(serveurQuiRepond({ ok: true, resultat: { accepte: true, resultat: {} } }), { depot }), SECTION);
    expect(lu).toMatchObject({ source: "aucune", raison: { code: "reponse_illisible" } });
    expect(await lireCacheSection(depot, "nathan", "section_de_test")).toBeNull();
  });

  test("un cache corrompu ou d'une autre forme est « pas de cache » : la raison du serveur est dite", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: "pas un nombre" }), "2026-09-28T12:00:00.000Z");
    expect(await lireSection(config(transportHorsLigne(), { depot }), SECTION)).toEqual({ source: "aucune", raison: HORS_LIGNE });

    await depot.ecrire("admin:nathan:section_de_test_v1", "{pas du json");
    expect(await lireSection(config(transportHorsLigne(), { depot }), SECTION)).toEqual({ source: "aucune", raison: HORS_LIGNE });
  });

  test("UN CACHE PAR PERSONNE : le cache de Nathan n'est jamais servi à Sophie", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "section_de_test", enveloppeCouple({ n: 5 }), "2026-09-28T12:00:00.000Z");

    const lu = await lireSection(config(transportHorsLigne(), { depot, personne: "sophie" }), SECTION);

    expect(lu).toEqual({ source: "aucune", raison: HORS_LIGNE });
  });

  test("une lecture réussie écrit sous la personne de la configuration", async () => {
    const depot = new DepotCleValeurMemoire();
    await lireSection(config(serveurQuiRepond(enveloppeCouple({ n: 3 })), { depot, personne: "sophie" }), SECTION);
    expect(await lireCacheSection(depot, "sophie", "section_de_test")).not.toBeNull();
    expect(await lireCacheSection(depot, "nathan", "section_de_test")).toBeNull();
  });

  test("le cache écrit est celui de la dernière lecture réussie : une lecture plus récente remplace l'ancienne", async () => {
    const depot = new DepotCleValeurMemoire();
    await lireSection(config(serveurQuiRepond(enveloppeCouple({ n: 1 })), { depot }), SECTION);
    await lireSection(config(serveurQuiRepond(enveloppeCouple({ n: 2 })), { depot }), SECTION);
    expect(await lireSection(config(transportHorsLigne(), { depot }), SECTION)).toMatchObject({ source: "cache", valeur: { n: 2 } });
  });

  test("la panne du cache (écriture) ne cache pas une lecture réussie", async () => {
    const erreur = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const depot: DepotCleValeur = {
      lire: async () => null,
      ecrire: async () => Promise.reject(new Error("SQLite plein")),
      supprimer: async () => undefined,
      supprimerParPrefixe: async () => undefined,
    };

    const lu = await lireSection(config(serveurQuiRepond(enveloppeCouple({ n: 9 })), { depot }), SECTION);

    expect(lu).toMatchObject({ source: "serveur", valeur: { n: 9 } });
    erreur.mockRestore();
  });

  test("epurerPourLeCache : ce qui est gardé est la version épurée, relue par le même lecteur qu'en ligne", async () => {
    const depot = new DepotCleValeurMemoire();
    const epuree: DefinitionSection<{ n: number }> = {
      ...SECTION,
      epurerPourLeCache: (brut) => {
        const { secret: _secret, ...reste } = (brut as { resultat: { resultat: { secret?: string } } }).resultat.resultat;
        return enveloppeCouple(reste);
      },
    };

    const en_ligne = await lireSection(config(serveurQuiRepond(enveloppeCouple({ n: 4, secret: "arguments-de-la-demande" })), { depot }), epuree);
    expect(en_ligne).toMatchObject({ source: "serveur", valeur: { n: 4 } });

    const gardee = await lireCacheSection(depot, "nathan", "section_de_test");
    expect(JSON.stringify(gardee)).not.toContain("arguments-de-la-demande");
    expect(await lireSection(config(transportHorsLigne(), { depot }), epuree)).toMatchObject({ source: "cache", valeur: { n: 4 } });
  });

  test("sans épuration, le cache garde l'enveloppe du serveur telle quelle", async () => {
    const depot = new DepotCleValeurMemoire();
    await lireSection(config(serveurQuiRepond(enveloppeCouple({ n: 4, en_plus: "gardé" })), { depot }), SECTION);
    expect(JSON.stringify(await lireCacheSection(depot, "nathan", "section_de_test"))).toContain("gardé");
  });
});
