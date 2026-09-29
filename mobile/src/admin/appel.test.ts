import type { EchecAppelOutil } from "../protocole/client";
import type { ErreurOutilsInvoke, TypeErreurOutilsInvoke } from "../protocole/types";
import { appelerLecture, classerEchec, ecrireSansEchouer, verdictDepuisEchec } from "./appel";
import { config, echecHttp, fauxTransport, transportEnEchec, transportHorsLigne } from "./donneesDeTest";

function echec(surcharges: Partial<EchecAppelOutil>): EchecAppelOutil {
  return { origine: "http", reessayable: false, message: "m", ...surcharges };
}
const CORE: ErreurOutilsInvoke = { type: "tool_call_blocked", message: "refusé" };
function erreurDuCore(type: TypeErreurOutilsInvoke, message = "x"): ErreurOutilsInvoke {
  return { type, message };
}

describe("le serveur a-t-il dit non, ou n'a-t-il pas pu répondre ?", () => {
  test.each([
    ["réseau coupé", echec({ origine: "reseau", reessayable: true }), "injoignable"],
    ["délai dépassé", echec({ origine: "delai", reessayable: true }), "injoignable"],
    ["408 : délai côté serveur", echec({ status: 408, reessayable: true }), "injoignable"],
    ["429 : débit", echec({ status: 429, reessayable: true, erreur: CORE }), "injoignable"],
    ["500 : panne d'outil du core", echec({ status: 500, reessayable: true, erreur: erreurDuCore("tool_error") }), "injoignable"],
    ["503 : passerelle indisponible", echec({ status: 503, reessayable: true }), "injoignable"],
    ["401 : jeton refusé, sans corps du core", echec({ status: 401 }), "refuse"],
    ["403 : porte d'appareil, corps du core", echec({ status: 403, erreur: CORE }), "refuse"],
    ["403 sans corps du core : jamais un cache pour un appareil refusé", echec({ status: 403 }), "refuse"],
    ["400 du core", echec({ status: 400, erreur: erreurDuCore("invalid_request") }), "refuse"],
    ["404 du core (outil absent)", echec({ status: 404, erreur: erreurDuCore("not_found") }), "refuse"],
    ["404 qui n'est pas du core (mandataire, page de connexion)", echec({ status: 404 }), "injoignable"],
    ["200 dont le corps n'est pas du JSON (page de connexion d'un réseau d'hôtel)", echec({ status: 200 }), "injoignable"],
  ])("%s : %s", (_nom, e, attendu) => {
    expect(classerEchec(e)).toBe(attendu);
  });

  test("le verdict garde le mot du core, sinon le fait", () => {
    expect(verdictDepuisEchec(echec({ status: 403, erreur: CORE }))).toEqual({ code: "tool_call_blocked", detail: "refusé" });
    expect(verdictDepuisEchec(echec({ status: 401, message: "réponse HTTP 401 inattendue" }))).toEqual({
      code: "http_401",
      detail: "réponse HTTP 401 inattendue",
    });
    expect(verdictDepuisEchec(echec({ origine: "reseau", reessayable: true, message: "Network request failed" }))).toEqual({
      code: "erreur_reseau",
      detail: "Network request failed",
    });
    expect(verdictDepuisEchec(echec({ origine: "delai", reessayable: true, message: "abort" }))).toEqual({
      code: "delai_depasse",
      detail: "abort",
    });
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
