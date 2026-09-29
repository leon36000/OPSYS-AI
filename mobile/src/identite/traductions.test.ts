import enCA from "../i18n/locales/en-CA";
import frCA from "../i18n/locales/fr-CA";
import { ROLES_NOMMES } from "./contrat";
import { MOTIFS_ERREUR_IDENTITE } from "./etat";

const LANGUES = [
  ["fr-CA", frCA],
  ["en-CA", enCA],
] as const;

describe.each(LANGUES)("textes d'identité (%s)", (_langue, ressources) => {
  test.each(MOTIFS_ERREUR_IDENTITE)("le motif d'erreur %s a son texte, jamais une clé vide ou manquante", (motif) => {
    const texte = ressources.identite.erreur.motifs[motif];
    expect(typeof texte).toBe("string");
    expect(texte.trim()).not.toBe("");
  });

  test("les motifs traduits sont exactement ceux que l'app peut montrer", () => {
    expect(Object.keys(ressources.identite.erreur.motifs).sort()).toEqual([...MOTIFS_ERREUR_IDENTITE].sort());
  });

  test.each(ROLES_NOMMES)("le rôle nommé %s a son libellé", (role) => {
    expect(ressources.identite.roles[role].trim()).not.toBe("");
  });

  test("le bandeau nomme la personne et le rôle, l'écran d'erreur nomme l'appareil", () => {
    expect(ressources.identite.bandeau.connecte).toContain("{{personne}}");
    expect(ressources.identite.bandeau.connecte).toContain("{{role}}");
    expect(ressources.identite.erreur.appareil).toContain("{{appareilId}}");
  });

  test("aucun champ de saisie d'identifiant d'employé ne subsiste", () => {
    expect(ressources.pointage).not.toHaveProperty("champTechnicien");
    expect(ressources.consentementGps).not.toHaveProperty("champTechnicien");
    expect(ressources.consentementGps).not.toHaveProperty("champRequis");
    expect(ressources.job).not.toHaveProperty("champTechnicien");
  });
});
