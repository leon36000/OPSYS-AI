import enCA from "../i18n/locales/en-CA";
import frCA from "../i18n/locales/fr-CA";
import { SEGMENTS_LEAD, STATUTS_LEAD } from "../m2/listeLeads";
import { STATUTS_DEVIS } from "../m3/devis";
import { ORIGINES_DEVIS } from "./devisConnus";

const LANGUES = [
  ["fr-CA", frCA],
  ["en-CA", enCA],
] as const;

/** Aplatit un arbre de textes en `chemin -> texte`. */
function aplatir(noeud: unknown, chemin = ""): Record<string, string> {
  if (typeof noeud === "string") {
    return { [chemin]: noeud };
  }
  if (typeof noeud === "object" && noeud !== null) {
    return Object.entries(noeud).reduce<Record<string, string>>(
      (acc, [cle, valeur]) => ({ ...acc, ...aplatir(valeur, chemin === "" ? cle : `${chemin}.${cle}`) }),
      {},
    );
  }
  return {};
}

const marques = (texte: string): string[] => (texte.match(/\{\{\s*\w+\s*\}\}/g) ?? []).map((m) => m.replace(/\s/g, "")).sort();

describe.each(LANGUES)("textes du profil vendeur (%s)", (_langue, ressources) => {
  const textes = aplatir(ressources.vendeur);

  test("aucun texte vide", () => {
    for (const [chemin, texte] of Object.entries(textes)) {
      expect(`${chemin}: ${texte.trim()}`).not.toBe(`${chemin}: `);
    }
  });

  test.each(STATUTS_LEAD)("le statut de lead %s a son libellé", (statut) => {
    expect(ressources.vendeur.statuts[statut]?.trim()).toBeTruthy();
  });

  test.each(SEGMENTS_LEAD)("le segment %s a son libellé", (segment) => {
    expect(ressources.vendeur.segments[segment]?.trim()).toBeTruthy();
  });

  test.each(STATUTS_DEVIS)("le statut de devis %s a son libellé", (statut) => {
    expect(ressources.vendeur.quotes.statuts[statut]?.trim()).toBeTruthy();
  });

  test.each(ORIGINES_DEVIS)("l'origine de devis %s a son libellé", (origine) => {
    expect(ressources.vendeur.quotes.origine[origine]?.trim()).toBeTruthy();
  });

  test("les catalogues de libellés sont exactement ceux du serveur (rien en trop, rien en moins)", () => {
    expect(Object.keys(ressources.vendeur.statuts).sort()).toEqual([...STATUTS_LEAD].sort());
    expect(Object.keys(ressources.vendeur.segments).sort()).toEqual([...SEGMENTS_LEAD].sort());
    expect(Object.keys(ressources.vendeur.quotes.statuts).sort()).toEqual([...STATUTS_DEVIS].sort());
    expect(Object.keys(ressources.vendeur.quotes.origine).sort()).toEqual([...ORIGINES_DEVIS].sort());
  });

  test("un segment non calculable et une note refusée disent le verdict du serveur (code et détail)", () => {
    expect(ressources.vendeur.leads.segmentNonCalculable).toContain("{{detail}}");
    expect(ressources.vendeur.lead.notes.resultat.refusee).toContain("{{code}}");
    expect(ressources.vendeur.lead.notes.resultat.refusee).toContain("{{detail}}");
    expect(ressources.vendeur.commun.cache).toContain("{{date}}");
  });
});

describe("fr-CA et en-CA disent la même chose", () => {
  const fr = aplatir(frCA.vendeur);
  const en = aplatir(enCA.vendeur);

  test("les mêmes clés", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(fr).sort());
  });

  test("les mêmes variables d'interpolation, clé par clé", () => {
    for (const chemin of Object.keys(fr)) {
      expect({ chemin, marques: marques(en[chemin]) }).toEqual({ chemin, marques: marques(fr[chemin]) });
    }
  });
});
