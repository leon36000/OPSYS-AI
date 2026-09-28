import { transitionEstPermise, verifierTransition } from "./transitions";
import type { StatutMutation } from "./types";

const TOUS_LES_STATUTS: readonly StatutMutation[] = [
  "brouillon",
  "en_attente",
  "envoi",
  "envoyee",
  "echec_permanent",
];

const TRANSITIONS_ATTENDUES_PERMISES = new Set([
  "brouillon->en_attente",
  "en_attente->envoi",
  "envoi->envoyee",
  "envoi->en_attente",
  "envoi->echec_permanent",
]);

describe("transitionEstPermise", () => {
  // Matrice exhaustive : les 5 statuts × 5 statuts = 25 paires, chacune vérifiée contre la
  // liste fermée ci-dessus (R12 §4). Toute paire non listée doit être refusée.
  for (const de of TOUS_LES_STATUTS) {
    for (const vers of TOUS_LES_STATUTS) {
      const cle = `${de}->${vers}`;
      const attendu = TRANSITIONS_ATTENDUES_PERMISES.has(cle);
      test(`${cle} => ${attendu ? "permise" : "refusée"}`, () => {
        expect(transitionEstPermise(de, vers)).toBe(attendu);
      });
    }
  }

  test("les statuts terminaux (envoyee, echec_permanent) n'ont aucune transition sortante", () => {
    for (const de of ["envoyee", "echec_permanent"] as const) {
      for (const vers of TOUS_LES_STATUTS) {
        expect(transitionEstPermise(de, vers)).toBe(false);
      }
    }
  });
});

describe("verifierTransition", () => {
  test("transition permise -> { ok: true }", () => {
    expect(verifierTransition("brouillon", "en_attente")).toEqual({ ok: true });
  });

  test("transition interdite -> refus nommant de/vers", () => {
    expect(verifierTransition("brouillon", "envoyee")).toEqual({
      ok: false,
      motif: "transition_interdite",
      de: "brouillon",
      vers: "envoyee",
    });
  });

  test("aucun saut direct brouillon -> envoi (doit passer par en_attente)", () => {
    expect(verifierTransition("brouillon", "envoi").ok).toBe(false);
  });
});
