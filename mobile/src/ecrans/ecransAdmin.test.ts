import fs from "node:fs";
import path from "node:path";

import { OUTIL_LISTER_DEMANDES } from "../approbations/chargeur";
import { OUTIL_LISTER_INTERVENTIONS, OUTIL_PRODUIRE_DIGEST, OUTIL_VERIFIER_PREPARATION } from "../m4/dispatch";
import { OUTIL_ECHEANCES_FISCALES, OUTIL_ETAT_TRESORERIE, OUTIL_PREVOIR_TRESORERIE } from "../m5/tresorerie";
import { OUTIL_VUE_EXECUTIVE } from "../m8/vueExecutive";

/**
 * Les règles du profil admin que les tests de comportement ne peuvent pas voir, lues dans le SOURCE (PLAN T4.20) : les
 * écrans sont du câblage mince que Jest ne rend pas, et une règle qu'un écran enfreindrait sans que rien ne casse est
 * une règle qui n'existe pas. Chaque garde ci-dessous échoue si la règle est enfreinte, avec le fichier fautif.
 *
 * Lecture SEULE : aucun outil d'écriture, aucune file sortante ; le nom NU de l'outil (le core pose le rôle et la personne) ;
 * aucun réseau en dur (tout passe par `service.ts`, qui prend le jeton et la personne de la session) ; aucune arithmétique
 * sur un montant, un pourcentage ou une date (le code du serveur calcule, l'app met en forme).
 */

const RACINE = path.join(__dirname, "..", "..");

function lire(fichier: string): string {
  return fs.readFileSync(path.join(RACINE, fichier), "utf8");
}

/** Le code seul : sans commentaires (les docblocks disent ce qui est interdit) ni chaînes de texte. */
function code(fichier: string): string {
  return lire(fichier)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/(?<=[;,{}()\s])\/\/[^\n"'`]*$/gm, "");
}

const ECRANS = ["app/(admin)/admin.tsx", "app/(admin)/chiffres.tsx", "app/(admin)/chantiers.tsx"];
const RENDUS = ["src/admin/composants.tsx", "src/admin/vuesChiffres.tsx"];
const MODELES_DE_VUE = [
  "src/ecrans/admin.ts",
  "src/ecrans/adminCommun.ts",
  "src/ecrans/chiffres.ts",
  "src/ecrans/vueExecutive.ts",
  "src/ecrans/chantiers.ts",
  "src/ecrans/manquesM4.ts",
  "src/ecrans/texteSur.ts",
];
const CHARGEURS_ET_LECTEURS = [
  "src/admin/appel.ts",
  "src/admin/enveloppe.ts",
  "src/admin/lecture.ts",
  "src/admin/cache.ts",
  "src/admin/lecteurs.ts",
  "src/admin/horloge.ts",
  "src/admin/aVoir.ts",
  "src/admin/chiffres.ts",
  "src/admin/chantiers.ts",
  "src/m4/dispatch.ts",
  "src/m5/tresorerie.ts",
  "src/m5/pagesPrevision.ts",
  "src/m8/vueExecutive.ts",
];

const OUTILS_DE_LECTURE = [
  OUTIL_LISTER_DEMANDES,
  OUTIL_VUE_EXECUTIVE,
  OUTIL_ETAT_TRESORERIE,
  OUTIL_PREVOIR_TRESORERIE,
  OUTIL_ECHEANCES_FISCALES,
  OUTIL_LISTER_INTERVENTIONS,
  OUTIL_VERIFIER_PREPARATION,
  OUTIL_PRODUIRE_DIGEST,
];

describe("les outils que le profil admin appelle", () => {
  test("les huit sont exactement ceux de la mission, sous leur nom NU, et ce sont des lectures", () => {
    expect([...OUTILS_DE_LECTURE].sort()).toEqual(
      [
        "m4_lister_interventions",
        "m4_produire_digest",
        "m4_verifier_preparation",
        "m5_etat_tresorerie",
        "m5_lire_echeances_fiscales",
        "m5_prevoir_tresorerie",
        "m8_lire_vue_executive",
        "m9_lister_demandes_approbation",
      ].sort(),
    );
    for (const outil of OUTILS_DE_LECTURE) {
      // Le nom nu : jamais préfixé par un serveur (`serveur__outil`, `serveur.outil`), jamais avec un chemin.
      expect(outil).toMatch(/^m\d+_[a-z_]+$/);
      expect(outil).toMatch(/^m\d+_(lister|lire|etat|prevoir|verifier|produire)_/);
    }
  });

  test("aucune source du profil admin ne nomme un outil qui écrit, décide ou propose", () => {
    for (const fichier of [...CHARGEURS_ET_LECTEURS, ...MODELES_DE_VUE, ...RENDUS, ...ECRANS, "src/admin/service.ts"]) {
      const litteraux = [...code(fichier).matchAll(/["'`](m\d+_[a-z_]+)["'`]/g)].map((m) => m[1]);
      for (const outil of litteraux) {
        expect({ fichier, outil, autorise: OUTILS_DE_LECTURE.includes(outil) }).toEqual({ fichier, outil, autorise: true });
      }
    }
  });

  test("aucun écran ne nomme un outil : les chargeurs les nomment, par des constantes", () => {
    for (const fichier of ECRANS) {
      expect({ fichier, nomme: /\bm\d+_[a-z]/.test(code(fichier)) }).toEqual({ fichier, nomme: false });
    }
  });
});

describe("les écrans : câblage mince, lecture seule", () => {
  test.each(ECRANS)("%s ne touche ni le réseau, ni la file sortante, ni une décision", (fichier) => {
    const source = code(fichier);
    expect(source).not.toMatch(/\bfetch\s*\(/);
    expect(source).not.toContain("/tools/invoke");
    expect(source).not.toMatch(/invoquerOutil|appelerOutil/);
    expect(source).not.toMatch(/@\/outbox|creerMutation|soumettreMutation|declencherVidange|obtenirDepot\b/);
    expect(source).not.toMatch(/approuver|refuser|decider/i);
  });

  test.each(ECRANS)("%s ne lit que par `@/admin/service`", (fichier) => {
    const importsDeDonnees = [...code(fichier).matchAll(/from\s+"@\/(admin\/service|approbations\/[a-z]+|protocole\/[a-zA-Z]+)"/g)].map((m) => m[1]);
    expect([...new Set(importsDeDonnees)]).toEqual(["admin/service"]);
  });

  test("le câblage réel passe par la session de l'appareil, le transport du core et le dépôt local ; aucun jeton ni personne en dur", () => {
    const source = code("src/admin/service.ts");
    expect(source).toContain("obtenirSessionEnvoi()");
    expect(source).toContain("appelerOutil: invoquerOutil");
    expect(source).toContain("obtenirDepotLocal()");
    expect(source).toContain("personne: session.personne");
    expect(source).toContain("jeton: session.jeton");
    expect(source).not.toMatch(/https?:\/\//);
    // Sans session : `null`, jamais une lecture inventée.
    expect(source).toContain("return null;");
    // L'heure de l'appareil, avec son décalage : le jour de référence que M5 et M4 demandent.
    expect(source).toContain("decalageMinutesUTC: -new Date().getTimezoneOffset()");
  });

  test("le groupe (admin) reste gardé par le rôle admin : un jeton employé ou vendeur n'y entre pas", () => {
    const layout = code("app/(admin)/_layout.tsx");
    expect(layout).toContain('evaluerGarde(session, "admin")');
    expect(layout).toContain("<Redirect");
  });
});

describe("l'écran des chantiers ne montre jamais le texte de M4 tel quel (PLAN T1.4-n)", () => {
  // Le `manque` de M4 est écrit pour un agent : il cite le fichier du serveur et les commandes `opsys-metier`. L'écran dit une
  // phrase de l'app (`src/ecrans/manquesM4.ts`, choisie par le code) ; le détail d'un volet PRÊT est un fait, déjà filtré.
  test("le manque, son code et ce qu'il faut fournir passent par une phrase de l'app (`Ligne`), jamais par un `<Text>` brut", () => {
    const source = code("app/(admin)/chantiers.tsx");
    expect(source).toContain("<Ligne m={volet.manque}");
    expect(source).toContain("<Ligne m={volet.code}");
    expect(source).toContain("<Ligne m={entree.manque}");
    expect(source).not.toMatch(/\.manque\s*\}\s*<\/Text>/);
    expect(source).not.toMatch(/<Text[^>]*>\s*\{[^}]*\.manque\b/);
  });

  test("l'avertissement de couverture fiscale est rendu avec le montant dans chaque échéance", () => {
    const source = code("src/admin/vuesChiffres.tsx");
    expect(source).toContain("echeance.couvertureTaxes !== null");
    expect(source).toContain("<Ligne m={echeance.couvertureTaxes}");
  });

  test("le modèle de vue ne lit jamais `.manque` d'un volet pour le montrer : la phrase vient de `direLeManque`", () => {
    const source = code("src/ecrans/chantiers.ts");
    expect(source).toContain("direLeManque(");
    expect(source).not.toMatch(/manque:\s*(volet|entree)\.manque\b/);
  });

  test("les deux gardes de texte n'ont ni réseau, ni stockage, ni horloge : des fonctions pures", () => {
    for (const fichier of ["src/ecrans/manquesM4.ts", "src/ecrans/texteSur.ts"]) {
      const source = code(fichier);
      expect(source).not.toMatch(/\bfetch\s*\(|\bDate\b|\bMath\b|localStorage|AsyncStorage|expo-sqlite|react-native/);
    }
  });
});

describe("aucune arithmétique sur un montant, un pourcentage ou une date", () => {
  const INTERDIT = /\b(parseFloat|parseInt|toFixed|BigInt|Decimal)\b|\bNumber\s*\(|\bMath\s*\.|\.reduce\s*\(/;

  test.each([...ECRANS, ...RENDUS, ...MODELES_DE_VUE, ...CHARGEURS_ET_LECTEURS])("%s", (fichier) => {
    const trouve = code(fichier).match(INTERDIT);
    expect({ fichier, interdit: trouve === null ? null : trouve[0] }).toEqual({ fichier, interdit: null });
  });

  test("le garde-fou voit bien ce qu'il interdit", () => {
    for (const exemple of ["parseFloat(x)", "Number(x)", "x.toFixed(2)", "Math.round(x)", "l.reduce((a, b) => a + b)", "new Decimal(1)", "BigInt(3)"]) {
      expect(INTERDIT.test(exemple)).toBe(true);
    }
    // Un identifiant qui contient le mot (`estDecimal`) n'est pas une conversion.
    expect(INTERDIT.test("estDecimal(valeur)")).toBe(false);
  });
});
