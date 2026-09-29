import fs from "node:fs";
import path from "node:path";

/**
 * Les écrans ne sont pas testés en rendu (pas de `@testing-library/react-native` dans la pile installée,
 * voir MOBILE.md) : ces gardes lisent leur SOURCE. Elles n'ont qu'un but, empêcher le retour d'un
 * identifiant d'employé saisi à la main (PLAN T1.4-c5) et d'un profil choisi d'après le rôle de transport
 * du jeton. La logique de l'identité est testée dans `src/identite/*.test.ts`.
 */
const RACINE_APP = path.resolve(__dirname, "../../app");

function lireEcran(chemin: string): string {
  return fs.readFileSync(path.join(RACINE_APP, chemin), "utf8");
}

/** Les trois écrans de l'employé qui demandaient son identifiant. */
const ECRANS_EMPLOYE = ["(employee)/punch.tsx", "(employee)/consent.tsx", "(employee)/job/[id]/index.tsx"] as const;

describe.each(ECRANS_EMPLOYE)("%s", (ecran) => {
  const source = lireEcran(ecran);

  test("ne demande plus le technicien à la main", () => {
    expect(source).not.toMatch(/setTechnicien/);
    expect(source).not.toMatch(/champTechnicien/);
    expect(source).not.toMatch(/const \[technicien\b/);
  });

  test("envoie la personne appairée que le serveur a confirmée, et affiche qui elle est", () => {
    expect(source).toContain("usePersonneAppairee()");
    expect(source).toContain("<BandeauIdentite />");
  });

  test("refuse d'agir sans personne confirmée (fail-closed), avec le texte d'identité absente", () => {
    expect(source).toMatch(/if \(!personne\)/);
    expect(source).toContain('t("identite.absente")');
  });
});

describe("aiguillage par le rôle nommé", () => {
  test("l'aiguilleur choisit d'après l'état d'identité, jamais d'après le rôle de transport du jeton", () => {
    const source = lireEcran("index.tsx");
    expect(source).toContain("useEtatIdentite()");
    expect(source).toContain("etat.identite.role");
    expect(source).not.toMatch(/session\.role/);
    expect(source).toMatch(/genre === "erreur"|case "erreur"/);
  });

  test("l'appairage ne pose plus de rôle de transport comme profil", () => {
    const source = lireEcran("pairing/index.tsx");
    expect(source).not.toContain("definirSession");
    expect(source).toContain("apresAppairage");
  });

  test("la racine relit l'identité au démarrage, au premier plan et au retour du réseau", () => {
    const source = lireEcran("_layout.tsx");
    expect(source).toContain("restaurer()");
    expect(source).toContain("demarrerDeclencheursVidange(");
    expect(source).toMatch(/await rafraichir\(\);\s*await declencherVidange\(\);/);
  });

  test("la racine relit l'identité quand la file se fait refuser l'appareil, sans relancer de vidange (T1.4-l)", () => {
    const source = lireEcran("_layout.tsx");
    expect(source).toMatch(/ecouterRefusAppareil\(\(\) => \{\s*void rafraichir\(\);\s*\}\)/);
  });

  test("après un appairage réussi, la file repart avec le nouveau jeton une fois l'identité lue (T1.4-l)", () => {
    const source = lireEcran("pairing/index.tsx");
    expect(source).toContain("apresAppairage().then(vidangerEnArrierePlan)");
  });

  test("chaque groupe garde ses écrans par la garde de routes", () => {
    for (const groupe of ["(admin)", "(employee)", "(seller)", "(client)"]) {
      expect(lireEcran(`${groupe}/_layout.tsx`)).toContain("evaluerGarde(");
    }
  });
});
