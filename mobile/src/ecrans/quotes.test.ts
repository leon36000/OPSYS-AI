import { lireDevisVendeur } from "../m3/devis";
import type { EntreeDevis, SourceDevis } from "../vendeur/chargeurDevis";
import { devisInterneBrut } from "../vendeur/donneesDeTest";
import { avisDesSources, formaterMontant, formaterQuantite, presenterDevis, presenterEntree } from "./quotes";

const NBSP = " ";
const devis = lireDevisVendeur({
  ...devisInterneBrut("devis-a-01", { statut: "accepte", prix_total: "12345.60" }),
  cout_total: "999.99",
  taux_marge: "0.7777",
})!;
const connu = { devisId: "devis-a-01", leadId: "lead-a-01", origine: "lead_converti" as const };

describe("formaterMontant — mis en forme, jamais converti en nombre", () => {
  test.each([
    ["360.00", "fr-CA", `360,00${NBSP}$`],
    ["12345.60", "fr-CA", `12${NBSP}345,60${NBSP}$`],
    ["1234567.89", "fr-CA", `1${NBSP}234${NBSP}567,89${NBSP}$`],
    ["0.05", "fr-CA", `0,05${NBSP}$`],
    ["-12.00", "fr-CA", `-12,00${NBSP}$`],
    ["360.00", "en-CA", "$360.00"],
    ["12345.60", "en-CA", "$12,345.60"],
    ["1234567.89", "en-CA", "$1,234,567.89"],
    ["-12.00", "en-CA", "-$12.00"],
    ["5", "en-CA", "$5"],
  ] as const)("%s (%s) -> %s", (texte, langue, attendu) => {
    expect(formaterMontant(texte, langue)).toBe(attendu);
  });

  test("aucune perte de précision : un texte très long de chiffres reste exact (aucun flottant)", () => {
    expect(formaterMontant("12345678901234567890.12", "en-CA")).toBe("$12,345,678,901,234,567,890.12");
  });

  test("les décimales ne sont ni arrondies ni complétées : ce que M3 a calculé, tel quel", () => {
    expect(formaterMontant("1234.5", "fr-CA")).toBe(`1${NBSP}234,5${NBSP}$`);
    expect(formaterMontant("1.005", "en-CA")).toBe("$1.005");
  });

  test.each([[null], [""], ["douze"], ["12,00"], ["1e3"], [" 12.00"], ["12."], [".5"]])(
    "%j : absent (null), jamais 0 ni un texte inventé",
    (texte) => {
      expect(formaterMontant(texte, "fr-CA")).toBeNull();
      expect(formaterMontant(texte, "en-CA")).toBeNull();
    },
  );

  test("les quantités : mêmes règles, sans symbole", () => {
    expect(formaterQuantite("30", "fr-CA")).toBe("30");
    expect(formaterQuantite("12.5", "fr-CA")).toBe("12,5");
    expect(formaterQuantite("1200.5", "en-CA")).toBe("1,200.5");
    expect(formaterQuantite(null, "fr-CA")).toBeNull();
    expect(formaterQuantite("beaucoup", "fr-CA")).toBeNull();
  });
});

describe("presenterDevis — statut et prix, ni coût ni marge", () => {
  test("statut, prix total et lignes mis en forme", () => {
    const carte = presenterDevis(devis, "lead_converti", null, "2026-09-29T18:03:22.000Z", "fr-CA");
    expect(carte).toMatchObject({
      devisId: "devis-a-01",
      leadId: "lead-a-01",
      origine: "lead_converti",
      statut: "accepte",
      statutConnu: true,
      prixTotal: `12${NBSP}345,60${NBSP}$`,
      cache: null,
    });
    expect(carte.lignes[0]).toEqual({
      referenceLigne: "devis-a-01-L0",
      description: "Gouttière alu 5 po (fictif)",
      quantite: "30",
      unite: "pi_lin",
      prixUnitaire: `12,00${NBSP}$`,
      prixLigne: `360,00${NBSP}$`,
    });
  });

  test("ce que l'écran reçoit ne porte ni coût ni marge, même quand le serveur les a rendus", () => {
    const texte = JSON.stringify(presenterDevis(devis, "saisi", null, "2026-09-29T18:03:22.000Z", "en-CA"));
    for (const interdit of ["999.99", "0.7777", "cout", "marge", "taux"]) {
      expect(texte).not.toContain(interdit);
    }
  });

  test("un prix absent est dit absent (null) ; l'app ne recalcule aucun total", () => {
    const sansPrix = lireDevisVendeur(devisInterneBrut("d", { prix_total: undefined }))!;
    const carte = presenterDevis(sansPrix, "saisi", null, "2026-09-29T18:03:22.000Z", "fr-CA");
    expect(carte.prixTotal).toBeNull();
    expect(carte.lignes[0].prixLigne).not.toBeNull(); // la ligne, elle, garde son prix : rien n'est déduit du total
  });

  test("un statut inconnu de ce code est gardé tel quel et dit inconnu", () => {
    const inconnu = lireDevisVendeur(devisInterneBrut("d", { statut: "expire" }))!;
    expect(presenterDevis(inconnu, "saisi", null, "t", "fr-CA")).toMatchObject({ statut: "expire", statutConnu: false });
    for (const statut of ["brouillon", "envoye", "accepte"]) {
      const connuDuCode = lireDevisVendeur(devisInterneBrut("d", { statut }))!;
      expect(presenterDevis(connuDuCode, "saisi", null, "t", "fr-CA").statutConnu).toBe(true);
    }
  });
});

describe("presenterEntree — les quatre états d'un devis", () => {
  const raison = { code: "erreur_reseau", detail: "Network request failed" };

  test("lu à l'instant : sans mention de cache", () => {
    const entree: EntreeDevis = { connu, etat: { genre: "serveur", devis, misAJourLe: "2026-09-29T18:03:22.000Z" } };
    const vue = presenterEntree(entree, "en-CA");
    expect(vue.genre === "devis" && [vue.carte.cache, vue.carte.prixTotal]).toEqual([null, "$12,345.60"]);
  });

  test("lu dans le cache : MARQUÉ comme cache, avec la date du cache et la raison", () => {
    const entree: EntreeDevis = {
      connu,
      etat: { genre: "cache", devis, misAJourLe: "2026-09-27T12:00:00.000Z", raisonHorsLigne: raison },
    };
    const vue = presenterEntree(entree, "fr-CA");
    expect(vue.genre === "devis" && vue.carte.cache).toEqual({ misAJourLe: "2026-09-27T12:00:00.000Z", raison });
    expect(vue.genre === "devis" && vue.carte.misAJourLe).toBe("2026-09-27T12:00:00.000Z");
  });

  test("le serveur dit non : le verdict tel quel ; ni serveur ni cache : indisponible avec la raison", () => {
    const verdict = { code: "REJ-DEVIS-INTROUVABLE", detail: "devis inconnu : 'x'" };
    expect(presenterEntree({ connu, etat: { genre: "refus", verdict } }, "fr-CA")).toEqual({
      genre: "refus",
      devisId: "devis-a-01",
      verdict,
    });
    expect(presenterEntree({ connu, etat: { genre: "indisponible", raison } }, "fr-CA")).toEqual({
      genre: "indisponible",
      devisId: "devis-a-01",
      raison,
    });
  });
});

describe("avisDesSources — la liste ne paraît jamais complète quand elle ne l'est pas", () => {
  const raison = { code: "erreur_reseau", detail: "Network request failed" };

  test("rien à signaler : une lecture complète, en ligne", () => {
    const sources: SourceDevis[] = [
      { segment: "won_pending_schedule", etat: { genre: "lue", leadsLus: 3, reste: 0, depuisCache: null } },
      { segment: "quote_stale", etat: { genre: "lue", leadsLus: 0, reste: 0, depuisCache: null } },
    ];
    expect(avisDesSources(sources)).toEqual([]);
  });

  test("un segment non calculable : son « manque X » tel que M2 le dit (seuil à configurer)", () => {
    const detail = "segment quote_stale : non calculable, manque le seuil jours_soumission_perimee : seuil à configurer";
    expect(
      avisDesSources([{ segment: "quote_stale", etat: { genre: "non_calculable", verdict: { code: "REJ-SEGMENT-NON-CALCULABLE", detail } } }]),
    ).toEqual([{ genre: "non_calculable", segment: "quote_stale", manque: detail }]);
  });

  test("une lecture en échec, partielle ou venue du cache : dite, avec ce qu'il faut savoir", () => {
    const sources: SourceDevis[] = [
      { segment: "won_pending_schedule", etat: { genre: "lue", leadsLus: 20, reste: 3, depuisCache: raison } },
      { segment: "quote_stale", etat: { genre: "echouee", verdict: raison, refuse: false } },
    ];
    expect(avisDesSources(sources)).toEqual([
      { genre: "depuis_cache", segment: "won_pending_schedule", raison },
      { genre: "partielle", segment: "won_pending_schedule", reste: 3 },
      { genre: "echouee", segment: "quote_stale", verdict: raison },
    ]);
  });
});
