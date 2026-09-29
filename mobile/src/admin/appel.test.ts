import { classerEchec as classerEchecPartagee, verdictDepuisEchec as verdictDepuisEchecPartage } from "../protocole/echec";
import { appelerLecture, classerEchec, ecrireSansEchouer, verdictDepuisEchec } from "./appel";
import { config, echecHttp, fauxTransport, transportEnEchec, transportHorsLigne } from "./donneesDeTest";

describe("la règle « refus ou panne »", () => {
  test("elle est celle de `protocole/echec.ts`, la même pour l'admin, le vendeur et l'employé", () => {
    expect(classerEchec).toBe(classerEchecPartagee);
    expect(verdictDepuisEchec).toBe(verdictDepuisEchecPartage);
  });
});

describe("appelerLecture", () => {
  test("envoie le nom nu et les arguments EXACTS, rien d'autre : ni clé d'idempotence, ni appareil, ni personne", async () => {
    const transport = fauxTransport({ m5_etat_tresorerie: () => ({ ok: true, resultat: {} }) });
    const c = config(transport);

    await appelerLecture(c, "m5_etat_tresorerie", { aujourd_hui: "2026-09-29" });

    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][0]).toEqual({
      fetchImpl: c.fetchImpl,
      urlBase: "https://grs.exemple.ca",
      jeton: "jeton-admin",
      requete: { tool: "m5_etat_tresorerie", args: { aujourd_hui: "2026-09-29" } },
    });
    expect(Object.keys(transport.mock.calls[0][0].requete).sort()).toEqual(["args", "tool"]);
  });

  test("rend l'enveloppe telle que le core l'a donnée", async () => {
    const enveloppe = { ok: true, resultat: { a: 1 } };
    const lu = await appelerLecture(config(fauxTransport({ m8_lire_vue_executive: () => enveloppe })), "m8_lire_vue_executive", {});
    expect(lu).toEqual({ genre: "reponse", resultat: enveloppe });
  });

  test("un réseau coupé est injoignable, jamais une exception", async () => {
    const lu = await appelerLecture(config(transportHorsLigne()), "m8_lire_vue_executive", {});
    expect(lu).toEqual({ genre: "injoignable", verdict: { code: "erreur_reseau", detail: "Network request failed" } });
  });

  test("un 403 de la porte est un refus, un 500 est injoignable", async () => {
    const refus = await appelerLecture(config(transportEnEchec(403, "tool_call_blocked", "hors portée")), "m8_lire_vue_executive", {});
    expect(refus).toEqual({ genre: "refuse", verdict: { code: "tool_call_blocked", detail: "hors portée" } });
    const panne = await appelerLecture(config(transportEnEchec(500, "tool_error", "panne")), "m8_lire_vue_executive", {});
    expect(panne).toEqual({ genre: "injoignable", verdict: { code: "tool_error", detail: "panne" } });
    expect(echecHttp(401).echec.erreur).toBeUndefined();
  });

  test("les arguments donnés ne sont pas modifiés par l'appel", async () => {
    const args = { aujourd_hui: "2026-09-29" };
    const transport = fauxTransport({ m5_prevoir_tresorerie: () => ({ ok: true, resultat: {} }) });
    await appelerLecture(config(transport), "m5_prevoir_tresorerie", args);
    expect(args).toEqual({ aujourd_hui: "2026-09-29" });
    expect(transport.mock.calls[0][0].requete.args).not.toBe(args);
  });
});

describe("ecrireSansEchouer", () => {
  test("une écriture de cache qui échoue ne fait pas échouer la lecture", async () => {
    const erreur = jest.spyOn(console, "error").mockImplementation(() => undefined);
    await expect(ecrireSansEchouer(async () => Promise.reject(new Error("SQLite plein")))).resolves.toBeUndefined();
    expect(erreur).toHaveBeenCalledTimes(1);
    erreur.mockRestore();
  });

  test("une écriture qui réussit est faite une fois", async () => {
    const ecriture = jest.fn(async () => undefined);
    await ecrireSansEchouer(ecriture);
    expect(ecriture).toHaveBeenCalledTimes(1);
  });
});
