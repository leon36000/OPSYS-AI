import { lirePageLeads } from "../m2/listeLeads";
import type { FiltreLeads } from "../m2/listeLeads";
import { lireDevisVendeur } from "../m3/devis";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import {
  ecrireCacheDevis,
  ecrireCacheFiche,
  ecrireCacheLeads,
  ecrireDevisConnus,
  lireCacheDevis,
  lireCacheFiche,
  lireCacheLeads,
  lireDevisConnus,
  purgerCachesDevis,
  supprimerCacheDevis,
} from "./cache";
import { CLIENT_DE_LEAD_BRUT, SUGGESTION_BRUTE, client360Brut, devisInterneBrut, leadBrut, pageBrute } from "./donneesDeTest";
import type { FicheBrute } from "./fiche";
import { demarrerLecture, fusionnerPage } from "./lectureLeads";
import type { LeadsLus } from "./lectureLeads";

const AUCUN: FiltreLeads = { statut: null, segment: null };
const T0 = "2026-09-29T18:00:00.000Z";
const MOI = "vendeur.a";
const AUTRE = "vendeur.b";

function lecture(leads: number, filtre: FiltreLeads = AUCUN, parPage = leads): LeadsLus {
  const tous = Array.from({ length: leads }, (_, i) => leadBrut(`lead-${String(i).padStart(2, "0")}`));
  const brute0 = pageBrute({ leads: tous.slice(0, parPage), total: leads, filtre });
  let lus = demarrerLecture(filtre, lirePageLeads(brute0)!, brute0, T0)!;
  for (let de = parPage; de < leads; de += parPage) {
    const brute = pageBrute({ leads: tous.slice(de, de + parPage), decalage: de, total: leads, filtre });
    const fusion = fusionnerPage(lus, lirePageLeads(brute)!, brute);
    if (fusion.genre !== "fusionnee") {
      throw new Error("fusion de test refusée");
    }
    lus = fusion.lus;
  }
  return lus;
}

describe("cache des leads", () => {
  test("écrit puis relu : mêmes leads, même total, même date de lecture (celle de la première page)", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheLeads(depot, MOI, lecture(5, AUCUN, 2));

    const relu = await lireCacheLeads(depot, MOI, AUCUN);

    expect(relu?.leads.map((l) => l.leadId)).toEqual(["lead-00", "lead-01", "lead-02", "lead-03", "lead-04"]);
    expect(relu).toMatchObject({ total: 5, suivant: null, reste: 0, misAJourLe: T0 });
    expect(relu?.pagesBrutes).toHaveLength(3);
  });

  test("un cache par filtre : le filtre demandé n'est jamais servi par le cache d'un autre", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheLeads(depot, MOI, lecture(3));
    expect(await lireCacheLeads(depot, MOI, { statut: "qualifie", segment: null })).toBeNull();
    expect(await lireCacheLeads(depot, MOI, { statut: null, segment: "hot_lead" })).toBeNull();
    await ecrireCacheLeads(depot, MOI, lecture(2, { statut: "qualifie", segment: null }));
    expect((await lireCacheLeads(depot, MOI, { statut: "qualifie", segment: null }))?.leads).toHaveLength(2);
    expect((await lireCacheLeads(depot, MOI, AUCUN))?.leads).toHaveLength(3);
  });

  test("le cache d'une personne n'est jamais lu pour une autre (même téléphone, autre appairage)", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheLeads(depot, MOI, lecture(3));
    expect(await lireCacheLeads(depot, AUTRE, AUCUN)).toBeNull();
    expect(await lireCacheLeads(depot, MOI, AUCUN)).not.toBeNull();
  });

  test.each([
    ["JSON illisible", "{pas du json"],
    ["un texte", '"leads"'],
    ["sans pages", JSON.stringify({ pages: [], misAJourLe: T0 })],
    ["sans date", JSON.stringify({ pages: [pageBrute({ leads: [leadBrut("l")] })] })],
    ["date illisible", JSON.stringify({ pages: [pageBrute({ leads: [leadBrut("l")] })], misAJourLe: "hier" })],
    ["première page illisible", JSON.stringify({ pages: [{ total: "x" }], misAJourLe: T0 })],
  ])("valeur corrompue (%s) : pas de cache, jamais une liste devinée", async (_nom, valeur) => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(`vendeur:${MOI}:leads:*|*_v1`, valeur);
    expect(await lireCacheLeads(depot, MOI, AUCUN)).toBeNull();
  });

  test("des pages qui ne se recollent pas (total changé) : pas de cache", async () => {
    const depot = new DepotCleValeurMemoire();
    const a = pageBrute({ leads: [leadBrut("a")], total: 2 });
    const b = pageBrute({ leads: [leadBrut("b")], decalage: 1, total: 3 });
    await depot.ecrire(`vendeur:${MOI}:leads:*|*_v1`, JSON.stringify({ pages: [a, b], misAJourLe: T0 }));
    expect(await lireCacheLeads(depot, MOI, AUCUN)).toBeNull();
  });

  test("une page d'un autre filtre dans le cache d'un filtre : pas de cache", async () => {
    const depot = new DepotCleValeurMemoire();
    const page = pageBrute({ leads: [leadBrut("a")], filtre: { statut: "nouveau", segment: null } });
    await depot.ecrire(`vendeur:${MOI}:leads:*|*_v1`, JSON.stringify({ pages: [page], misAJourLe: T0 }));
    expect(await lireCacheLeads(depot, MOI, AUCUN)).toBeNull();
  });
});

describe("cache de la fiche d'un lead", () => {
  const fiche: FicheBrute = {
    suggestion: { genre: "accepte", valeur: SUGGESTION_BRUTE },
    clientDuLead: { genre: "accepte", valeur: CLIENT_DE_LEAD_BRUT },
    vue: { genre: "accepte", valeur: client360Brut() },
    misAJourLe: T0,
  };

  test("écrit puis relu à l'identique, par lead et par personne", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheFiche(depot, MOI, "lead-a-01", fiche);
    expect(await lireCacheFiche(depot, MOI, "lead-a-01")).toEqual(fiche);
    expect(await lireCacheFiche(depot, MOI, "lead-a-02")).toBeNull();
    expect(await lireCacheFiche(depot, AUTRE, "lead-a-01")).toBeNull();
  });

  test("valeur corrompue ou d'une autre forme : pas de cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(`vendeur:${MOI}:fiche:lead-a-01_v1`, "{");
    expect(await lireCacheFiche(depot, MOI, "lead-a-01")).toBeNull();
    await depot.ecrire(`vendeur:${MOI}:fiche:lead-a-01_v1`, JSON.stringify({ suggestion: 1 }));
    expect(await lireCacheFiche(depot, MOI, "lead-a-01")).toBeNull();
  });
});

describe("cache des devis : ni coût ni marge, jamais", () => {
  const devis = lireDevisVendeur(devisInterneBrut("devis-a-01"))!;

  test("écrit puis relu avec sa date ; la base ne contient ni coût ni marge", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheDevis(depot, MOI, devis, T0);

    expect(await lireCacheDevis(depot, MOI, "devis-a-01")).toEqual({ devis, misAJourLe: T0 });
    const stocke = (await depot.lire(`vendeur:${MOI}:devis:devis-a-01_v1`)) ?? "";
    for (const interdit of ["cout", "marge", "taux", "10.00", "300.00", "0.20"]) {
      expect(stocke).not.toContain(interdit);
    }
    expect(stocke).toContain("360.00");
  });

  test("un cache qui porterait un coût ou une marge est refusé, jamais affiché", async () => {
    const depot = new DepotCleValeurMemoire();
    const pollue = { devis: { ...devis, coutTotal: "300.00" }, misAJourLe: T0 };
    await depot.ecrire(`vendeur:${MOI}:devis:devis-a-01_v1`, JSON.stringify(pollue));
    expect(await lireCacheDevis(depot, MOI, "devis-a-01")).toBeNull();
  });

  test("le devis d'un autre numéro sous la même clé est refusé ; un autre vendeur ne le lit pas", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(`vendeur:${MOI}:devis:devis-a-02_v1`, JSON.stringify({ devis, misAJourLe: T0 }));
    expect(await lireCacheDevis(depot, MOI, "devis-a-02")).toBeNull();
    await ecrireCacheDevis(depot, MOI, devis, T0);
    expect(await lireCacheDevis(depot, AUTRE, "devis-a-01")).toBeNull();
  });

  test("sans date lisible ou en JSON illisible : pas de cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(`vendeur:${MOI}:devis:devis-a-01_v1`, JSON.stringify({ devis, misAJourLe: "hier" }));
    expect(await lireCacheDevis(depot, MOI, "devis-a-01")).toBeNull();
    await depot.ecrire(`vendeur:${MOI}:devis:devis-a-01_v1`, "nul");
    expect(await lireCacheDevis(depot, MOI, "devis-a-01")).toBeNull();
  });
});

describe("numéros de devis connus", () => {
  test("écrits puis relus, par personne", async () => {
    const depot = new DepotCleValeurMemoire();
    const connus = [{ devisId: "d1", leadId: "l1", origine: "lead_converti" as const }];
    await ecrireDevisConnus(depot, MOI, connus);
    expect(await lireDevisConnus(depot, MOI)).toEqual(connus);
    expect(await lireDevisConnus(depot, AUTRE)).toEqual([]);
  });

  test("valeur illisible ou dont un élément est invalide : aucun numéro (jamais deviné)", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(`vendeur:${MOI}:devis_connus_v1`, "{");
    expect(await lireDevisConnus(depot, MOI)).toEqual([]);
    await depot.ecrire(
      `vendeur:${MOI}:devis_connus_v1`,
      JSON.stringify([{ devisId: "d1", leadId: null, origine: "saisi" }, { devisId: "" }]),
    );
    expect(await lireDevisConnus(depot, MOI)).toEqual([]);
  });
});


describe("purge ciblée du cache des devis vendeur", () => {
  const devis = lireDevisVendeur(devisInterneBrut("devis-a-01"))!;
  const autre = lireDevisVendeur(devisInterneBrut("devis-b-01"))!;

  test("un refus par devis supprime sa copie et sa référence, sans toucher aux autres devis", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheDevis(depot, MOI, devis, T0);
    await ecrireCacheDevis(depot, MOI, autre, T0);
    await ecrireDevisConnus(depot, MOI, [
      { devisId: devis.devisId, leadId: devis.leadId, origine: "saisi" },
      { devisId: autre.devisId, leadId: autre.leadId, origine: "saisi" },
    ]);

    await supprimerCacheDevis(depot, MOI, devis.devisId);

    expect(await lireCacheDevis(depot, MOI, devis.devisId)).toBeNull();
    expect(await lireCacheDevis(depot, MOI, autre.devisId)).not.toBeNull();
    expect((await lireDevisConnus(depot, MOI)).map((d) => d.devisId)).toEqual([autre.devisId]);
  });

  test("refus d'inventaire purge seulement les devis et IDs de cette personne", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheDevis(depot, MOI, devis, T0);
    await ecrireDevisConnus(depot, MOI, [{ devisId: devis.devisId, leadId: devis.leadId, origine: "saisi" }]);
    await ecrireCacheDevis(depot, AUTRE, autre, T0);
    await depot.ecrire(`vendeur:${MOI}:fiche:lead-a-01_v1`, "fiche-conservee");

    await purgerCachesDevis(depot, MOI);

    expect(await lireCacheDevis(depot, MOI, devis.devisId)).toBeNull();
    expect(await lireDevisConnus(depot, MOI)).toEqual([]);
    expect(await lireCacheDevis(depot, AUTRE, autre.devisId)).not.toBeNull();
    expect(await depot.lire(`vendeur:${MOI}:fiche:lead-a-01_v1`)).toBe("fiche-conservee");
  });
});
