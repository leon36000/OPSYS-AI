import {
  CLES_HERITEES_SANS_PERSONNE,
  PREFIXE_CACHE_ADMIN,
  PREFIXE_CACHE_EMPLOYE,
  PREFIXE_CACHE_VENDEUR,
  PREFIXES_DES_CACHES_PAR_PERSONNE,
  cleDeCachePersonne,
} from "./cles";

describe("les clés des caches par personne", () => {
  test("trois profils, trois préfixes, dans le registre", () => {
    expect([PREFIXE_CACHE_ADMIN, PREFIXE_CACHE_VENDEUR, PREFIXE_CACHE_EMPLOYE]).toEqual(["admin:", "vendeur:", "employe:"]);
    expect([...PREFIXES_DES_CACHES_PAR_PERSONNE].sort()).toEqual(["admin:", "employe:", "vendeur:"]);
  });

  test("aucun préfixe n'en prolonge un autre : effacer l'un n'efface jamais le cache d'un autre profil", () => {
    for (const a of PREFIXES_DES_CACHES_PAR_PERSONNE) {
      for (const b of PREFIXES_DES_CACHES_PAR_PERSONNE) {
        if (a !== b) {
          expect({ a, b, prolonge: a.startsWith(b) }).toEqual({ a, b, prolonge: false });
        }
      }
    }
  });

  test("la clé est `<préfixe><personne encodée>:<nom>` : deux personnes ne partagent jamais une clé", () => {
    expect(cleDeCachePersonne(PREFIXE_CACHE_ADMIN, "nathan", "a_voir_v1")).toBe("admin:nathan:a_voir_v1");
    // Une personne qui contient « : » n'usurpe pas la clé d'une autre.
    expect(cleDeCachePersonne(PREFIXE_CACHE_VENDEUR, "a:b", "x")).toBe("vendeur:a%3Ab:x");
    expect(cleDeCachePersonne(PREFIXE_CACHE_VENDEUR, "a", "b:x")).toBe("vendeur:a:b:x");
    expect(cleDeCachePersonne(PREFIXE_CACHE_VENDEUR, "a:b", "x")).not.toBe(cleDeCachePersonne(PREFIXE_CACHE_VENDEUR, "a", "b:x"));
  });

  test("les clés d'avant T1.4-n (sans personne) sont nommées pour être effacées, et ne portent aucun préfixe de personne", () => {
    expect(CLES_HERITEES_SANS_PERSONNE).toEqual(["today_chantiers_v1"]);
    for (const cle of CLES_HERITEES_SANS_PERSONNE) {
      expect(PREFIXES_DES_CACHES_PAR_PERSONNE.some((prefixe) => cle.startsWith(prefixe))).toBe(false);
    }
  });
});
