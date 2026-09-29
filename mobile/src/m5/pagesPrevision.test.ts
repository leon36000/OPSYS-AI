import { reponse } from "../admin/donneesDeTest";
import { fusionnerPagePrevision } from "./pagesPrevision";
import { lirePrevisionTresorerie } from "./tresorerie";
import type { PrevisionTresorerie } from "./tresorerie";

function page(nom: string, modification?: (brut: any) => void): PrevisionTresorerie {
  const brut = reponse(nom).resultat.resultat;
  modification?.(brut);
  const lue = lirePrevisionTresorerie(brut);
  if (lue === null || lue.genre !== "prevision") {
    throw new Error(`« ${nom} » devrait être une prévision lisible`);
  }
  return lue;
}

describe("recoller la page suivante de la prévision", () => {
  test("les deux pages d'un même horizon se recollent : vingt-six semaines, dans l'ordre, l'en-tête de la première", () => {
    const premiere = page("prevision_longue_page_1");
    const seconde = page("prevision_longue_page_2");

    const fusion = fusionnerPagePrevision(premiere, seconde);

    expect(fusion.genre).toBe("fusionnee");
    if (fusion.genre !== "fusionnee") {
      return;
    }
    const { prevision } = fusion;
    expect(prevision.semaines.map((s) => s.semaine)).toEqual(Array.from({ length: 26 }, (_, i) => i + 1));
    expect(prevision).toMatchObject({ total: 26, depart: 0, affichees: 26, reste: 0, prochainDepart: null, previsionId: premiere.previsionId });
    expect(prevision.lecture).toBe(premiere.lecture);
    expect(prevision.alerte).toEqual(premiere.alerte);
    expect(prevision.semainesIllisibles).toBe(0);
  });

  test("une prévision refaite entre les deux pages (autre empreinte) n'est PAS recollée : relire depuis le début", () => {
    const premiere = page("prevision_longue_page_1");
    const autre = page("prevision_longue_page_2", (b) => (b.prevision_id = "f".repeat(64)));
    expect(fusionnerPagePrevision(premiere, autre)).toEqual({ genre: "a_relire", raison: "prevision_changee" });
  });

  test("un autre total avec la même empreinte est aussi une prévision changée", () => {
    const premiere = page("prevision_longue_page_1");
    const autre = page("prevision_longue_page_2", (b) => Object.assign(b, { total: 27, reste: 1, prochain_depart: 26 }));
    expect(fusionnerPagePrevision(premiere, autre)).toEqual({ genre: "a_relire", raison: "prevision_changee" });
  });

  test("ce n'est pas la page demandée : incohérent (jamais recollée)", () => {
    const premiere = page("prevision_longue_page_1");
    expect(fusionnerPagePrevision(premiere, premiere)).toEqual({ genre: "a_relire", raison: "incoherente" });
    const decalee: PrevisionTresorerie = { ...page("prevision_longue_page_2"), depart: 18 };
    expect(fusionnerPagePrevision(premiere, decalee)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("rien ne suit dans ce qui est lu : il n'y a rien à recoller", () => {
    const complete = page("prevision");
    expect(complete.prochainDepart).toBeNull();
    expect(fusionnerPagePrevision(complete, page("prevision_longue_page_2"))).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("une page absente ou masquée n'est pas une prévision", () => {
    const premiere = page("prevision_longue_page_1");
    expect(fusionnerPagePrevision(premiere, null)).toEqual({ genre: "a_relire", raison: "incoherente" });
    const masquee = lirePrevisionTresorerie({ role: "admin", montants_masques: true, horizon_semaines: 26, mention: "m" });
    expect(fusionnerPagePrevision(premiere, masquee)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("une page qui répète une semaine déjà affichée n'est pas recollée", () => {
    const premiere = page("prevision_longue_page_1");
    const repetee = page("prevision_longue_page_2", (b) => (b.semaines[0].semaine = 19));
    expect(fusionnerPagePrevision(premiere, repetee)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("une page qui ne fait pas progresser la lecture (rien de lu, ou un rang suivant qui n'avance pas) n'est pas recollée : « Voir plus » ne tourne pas en rond", () => {
    const premiere = page("prevision_longue_page_1");
    const vide: PrevisionTresorerie = { ...page("prevision_longue_page_2"), affichees: 0, semaines: [] };
    expect(fusionnerPagePrevision(premiere, vide)).toEqual({ genre: "a_relire", raison: "incoherente" });
    const enRond: PrevisionTresorerie = { ...page("prevision_longue_page_2"), reste: 3, prochainDepart: 19 };
    expect(fusionnerPagePrevision(premiere, enRond)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("les semaines illisibles des deux pages s'additionnent, jamais perdues", () => {
    const premiere = page("prevision_longue_page_1", (b) => delete b.semaines[3].solde_fin);
    const seconde = page("prevision_longue_page_2", (b) => delete b.semaines[2].solde_fin);
    expect(premiere.semainesIllisibles).toBe(1);
    const fusion = fusionnerPagePrevision(premiere, seconde);
    expect(fusion.genre === "fusionnee" && fusion.prevision.semainesIllisibles).toBe(2);
    expect(fusion.genre === "fusionnee" && fusion.prevision.semaines).toHaveLength(24);
  });

  test("la fusion ne modifie ni la page lue ni la page reçue", () => {
    const premiere = page("prevision_longue_page_1");
    const seconde = page("prevision_longue_page_2");
    const avant = JSON.stringify([premiere, seconde]);
    fusionnerPagePrevision(premiere, seconde);
    expect(JSON.stringify([premiere, seconde])).toBe(avant);
  });
});
