import { appelerLecture, ecrireSansEchouer } from "./appel";
import type { ConfigurationChargeurVendeur } from "./appel";
import { ECHECS_QUI_SONT_UN_REFUS, ECHECS_QUI_SONT_UNE_PANNE, fauxTransport, transportEnEchec, transportHorsLigne } from "./donneesDeTest";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";

function config(appelerOutil: jest.Mock): ConfigurationChargeurVendeur {
  return {
    depot: new DepotCleValeurMemoire(),
    appelerOutil,
    fetchImpl: jest.fn() as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-vendeur",
    personne: "vendeur.a",
    horloge: () => ({ maintenant: new Date("2026-09-29T18:03:22.000Z"), decalageMinutesUTC: -240 }),
  };
}

describe("appelerLecture (vendeur) : trois issues que rien ne confond", () => {
  test("envoie le nom nu et les arguments EXACTS, rien d'autre : ni clé d'idempotence, ni appareil, ni personne", async () => {
    const transport = fauxTransport({ m2_lister_leads: () => ({ ok: true, resultat: {} }) });
    const c = config(transport);

    await appelerLecture(c, "m2_lister_leads", { horodatage: "2026-09-29T14:03:22-04:00" });

    expect(transport.mock.calls[0][0]).toEqual({
      fetchImpl: c.fetchImpl,
      urlBase: "https://grs.exemple.ca",
      jeton: "jeton-vendeur",
      requete: { tool: "m2_lister_leads", args: { horodatage: "2026-09-29T14:03:22-04:00" } },
    });
  });

  test("le serveur a répondu : l'enveloppe telle que le core l'a donnée", async () => {
    const enveloppe = { ok: true, resultat: { accepte: true, resultat: { a: 1 } } };
    expect(await appelerLecture(config(fauxTransport({ m3_lire_devis: () => enveloppe })), "m3_lire_devis", {})).toEqual({
      genre: "reponse",
      resultat: enveloppe,
    });
  });

  test.each(ECHECS_QUI_SONT_UN_REFUS)("%s : refuse, avec le verdict du core ou le fait", async (_nom, status, type, code) => {
    expect(await appelerLecture(config(transportEnEchec(status, type, "refusé")), "m2_lister_leads", {})).toEqual({
      genre: "refuse",
      verdict: { code, detail: "refusé" },
    });
  });

  test.each(ECHECS_QUI_SONT_UNE_PANNE)("%s : injoignable, un cache peut servir", async (_nom, status, type, code) => {
    expect(await appelerLecture(config(transportEnEchec(status, type, "panne")), "m2_lister_leads", {})).toEqual({
      genre: "injoignable",
      verdict: { code, detail: "panne" },
    });
  });

  test("un réseau coupé est injoignable, jamais une exception", async () => {
    expect(await appelerLecture(config(transportHorsLigne()), "m2_lister_leads", {})).toEqual({
      genre: "injoignable",
      verdict: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });

  test("un délai dépassé garde son nom (`delai_depasse`), il n'est pas dit « réseau »", async () => {
    const delai = jest.fn(async () => ({ ok: false, echec: { origine: "delai", reessayable: true, message: "aborted" } }));
    expect(await appelerLecture(config(delai), "m2_lister_leads", {})).toEqual({
      genre: "injoignable",
      verdict: { code: "delai_depasse", detail: "aborted" },
    });
  });
});

describe("ecrireSansEchouer (vendeur)", () => {
  test("une écriture de cache qui échoue ne fait pas échouer la lecture", async () => {
    const erreur = jest.spyOn(console, "error").mockImplementation(() => undefined);
    await expect(ecrireSansEchouer(async () => Promise.reject(new Error("SQLite plein")))).resolves.toBeUndefined();
    expect(erreur).toHaveBeenCalledTimes(1);
    erreur.mockRestore();
  });
});
