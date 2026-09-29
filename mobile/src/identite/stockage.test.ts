import type { CoffreAppairage } from "../appairage/stockage";
import { chargerIdentiteMemorisee, effacerIdentiteMemorisee, sauvegarderIdentiteMemorisee } from "./stockage";

function creerFauxCoffre(initial: Record<string, string> = {}): CoffreAppairage {
  const magasin = new Map(Object.entries(initial));
  return {
    getItemAsync: async (cle) => magasin.get(cle) ?? null,
    setItemAsync: async (cle, valeur) => {
      magasin.set(cle, valeur);
    },
    deleteItemAsync: async (cle) => {
      magasin.delete(cle);
    },
  };
}

const APPAREIL = "a".repeat(64);
const CLE = "opsys_identite_confirmee_v1";
const MEMORISEE = { appareilId: APPAREIL, personne: "jdupont", role: "employee", confirmeLe: "2026-09-28T08:00:00.000Z" } as const;

describe("identité confirmée gardée hors ligne", () => {
  test("aller-retour simple", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderIdentiteMemorisee(MEMORISEE, coffre);
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toEqual(MEMORISEE);
  });

  test("rien de gardé -> null", async () => {
    await expect(chargerIdentiteMemorisee(APPAREIL, creerFauxCoffre())).resolves.toBeNull();
  });

  test("effacer retire l'identité gardée", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderIdentiteMemorisee(MEMORISEE, coffre);
    await effacerIdentiteMemorisee(coffre);
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toBeNull();
  });

  test("l'identité gardée pour un AUTRE appareil n'est jamais rendue", async () => {
    const coffre = creerFauxCoffre();
    await sauvegarderIdentiteMemorisee(MEMORISEE, coffre);
    await expect(chargerIdentiteMemorisee("b".repeat(64), coffre)).resolves.toBeNull();
  });

  test("valeur corrompue (JSON invalide) -> null, fail-closed", async () => {
    await expect(chargerIdentiteMemorisee(APPAREIL, creerFauxCoffre({ [CLE]: "{ pas du json" }))).resolves.toBeNull();
  });

  test.each([
    ["rôle inconnu", { ...MEMORISEE, role: "operator" }],
    ["rôle vide", { ...MEMORISEE, role: "" }],
    ["rôle en majuscules", { ...MEMORISEE, role: "ADMIN" }],
    ["rôle client", { ...MEMORISEE, role: "client" }],
    ["rôle absent", { appareilId: APPAREIL, personne: "jdupont", confirmeLe: MEMORISEE.confirmeLe }],
    ["personne vide", { ...MEMORISEE, personne: "  " }],
    ["personne absente", { appareilId: APPAREIL, role: "employee", confirmeLe: MEMORISEE.confirmeLe }],
    ["date de confirmation absente", { appareilId: APPAREIL, personne: "jdupont", role: "employee" }],
    ["date de confirmation illisible", { ...MEMORISEE, confirmeLe: "hier" }],
    ["appareil absent", { personne: "jdupont", role: "employee", confirmeLe: MEMORISEE.confirmeLe }],
    ["valeur nulle", null],
    ["tableau", []],
    ["chaîne", "employee"],
  ])("valeur d'une forme inconnue (%s) -> null, jamais un profil deviné ou complété", async (_nom, valeur) => {
    const coffre = creerFauxCoffre({ [CLE]: JSON.stringify(valeur) });
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toBeNull();
  });

  test("ne rend que les quatre champs connus (rien d'autre du coffre ne passe)", async () => {
    const coffre = creerFauxCoffre({ [CLE]: JSON.stringify({ ...MEMORISEE, jeton: "secret", admin: true }) });
    await expect(chargerIdentiteMemorisee(APPAREIL, coffre)).resolves.toEqual(MEMORISEE);
  });
});
