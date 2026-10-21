import type { EchecAppelOutil } from "./client";
import { classerEchec, verdictDepuisEchec } from "./echec";
import type { ErreurOutilsInvoke, TypeErreurOutilsInvoke } from "./types";

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
    ["401 : jeton refusé, corps du core", echec({ status: 401, erreur: erreurDuCore("tool_call_blocked", "jeton") }), "refuse"],
    ["403 : porte d'appareil, corps du core", echec({ status: 403, erreur: CORE }), "refuse"],
    ["403 sans corps du core : jamais un cache pour un appareil refusé", echec({ status: 403 }), "refuse"],
    ["400 du core", echec({ status: 400, erreur: erreurDuCore("invalid_request") }), "refuse"],
    ["404 du core (outil absent)", echec({ status: 404, erreur: erreurDuCore("not_found") }), "refuse"],
    ["404 qui n'est pas du core (mandataire, page de connexion)", echec({ status: 404 }), "injoignable"],
    ["200 dont le corps n'est pas du JSON (page de connexion d'un réseau d'hôtel)", echec({ status: 200 }), "injoignable"],
    ["un échec marqué réessayable n'est jamais un refus (le drapeau du client passe avant le statut)", echec({ status: 401, reessayable: true }), "injoignable"],
  ])("%s : %s", (_nom, e, attendu) => {
    expect(classerEchec(e)).toBe(attendu);
  });

  test("un échec de réseau ou de délai n'est jamais un refus, même avec un statut et un corps du core", () => {
    expect(classerEchec(echec({ origine: "reseau", reessayable: false, status: 403, erreur: CORE }))).toBe("injoignable");
    expect(classerEchec(echec({ origine: "delai", reessayable: false, status: 401 }))).toBe("injoignable");
  });
});

describe("le verdict d'un échec d'appel", () => {
  test("il garde le mot du core, sinon le fait", () => {
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
