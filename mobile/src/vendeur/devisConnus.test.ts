import { lirePageLeads } from "../m2/listeLeads";
import type { LeadListe } from "../m2/listeLeads";
import { leadBrut, pageBrute } from "./donneesDeTest";
import {
  devisCitesParLeads,
  estDevisConnuValide,
  fusionnerDevisConnus,
  memesDevisConnus,
} from "./devisConnus";
import type { DevisConnu } from "./devisConnus";

function leads(...bruts: Record<string, unknown>[]): readonly LeadListe[] {
  return lirePageLeads(pageBrute({ leads: bruts }))!.leads;
}

const CONVERTI = {
  segment: "won_pending_schedule",
  regle: "soumission_acceptee_a_planifier",
  donnee: { statut: "converti", reference_devis_m3: "devis-a-01" },
};
const PERIME = {
  segment: "quote_stale",
  regle: "devis_envoye_sans_reponse_perime",
  donnee: { devis_id: "devis-a-02", statut_devis: "envoye", jours_ecoules: 12, seuil_jours: 7 },
};

describe("devisCitesParLeads — la seule source de numéros de devis de l'app", () => {
  test("le devis accepté d'un lead converti et le devis envoyé resté sans réponse, chacun avec son lead", () => {
    const cites = devisCitesParLeads(
      leads(leadBrut("lead-1", { segments: [CONVERTI] }), leadBrut("lead-2", { segments: [PERIME] })),
    );
    expect(cites).toEqual([
      { devisId: "devis-a-01", leadId: "lead-1", origine: "lead_converti" },
      { devisId: "devis-a-02", leadId: "lead-2", origine: "soumission_perimee" },
    ]);
  });

  test("un lead sans segment de devis n'en cite aucun ; les autres segments sont ignorés", () => {
    const hot = { segment: "hot_lead", regle: "urgence_declaree_lead_ouvert", donnee: { devis_id: "piege" } };
    expect(devisCitesParLeads(leads(leadBrut("lead-1"), leadBrut("lead-2", { segments: [hot] })))).toEqual([]);
  });

  test.each([
    ["absent", { statut: "converti" }],
    ["nul", { reference_devis_m3: null }],
    ["vide", { reference_devis_m3: "  " }],
    ["pas un texte", { reference_devis_m3: 42 }],
  ])("un numéro de devis %s n'est pas un devis : rien n'est deviné", (_nom, donnee) => {
    expect(devisCitesParLeads(leads(leadBrut("lead-1", { segments: [{ ...CONVERTI, donnee }] })))).toEqual([]);
  });
});

describe("fusionnerDevisConnus", () => {
  const saisi: DevisConnu = { devisId: "devis-b", leadId: null, origine: "saisi" };
  const converti: DevisConnu = { devisId: "devis-a", leadId: "lead-1", origine: "lead_converti" };

  test("un par numéro, triés par numéro", () => {
    expect(fusionnerDevisConnus([saisi], [converti])).toEqual([converti, saisi]);
    expect(fusionnerDevisConnus([], [])).toEqual([]);
  });

  test("un devis cité par un lead remplace le même numéro seulement saisi (il dit d'où il vient)", () => {
    const saisiA: DevisConnu = { devisId: "devis-a", leadId: null, origine: "saisi" };
    expect(fusionnerDevisConnus([saisiA], [converti])).toEqual([converti]);
  });

  test("un numéro saisi ne remplace pas un devis déjà cité ; deux citations gardent la première", () => {
    const saisiA: DevisConnu = { devisId: "devis-a", leadId: null, origine: "saisi" };
    expect(fusionnerDevisConnus([converti], [saisiA])).toEqual([converti]);
    const autre: DevisConnu = { devisId: "devis-a", leadId: "lead-9", origine: "soumission_perimee" };
    expect(fusionnerDevisConnus([converti], [autre])).toEqual([converti]);
  });

  test("ne modifie pas ses entrées ; memesDevisConnus compare numéro, lead et origine", () => {
    const existants = [saisi];
    fusionnerDevisConnus(existants, [converti]);
    expect(existants).toEqual([saisi]);
    expect(memesDevisConnus([converti, saisi], [converti, saisi])).toBe(true);
    expect(memesDevisConnus([converti], [{ ...converti, leadId: "lead-2" }])).toBe(false);
    expect(memesDevisConnus([converti], [])).toBe(false);
  });
});

describe("estDevisConnuValide", () => {
  test.each([
    [{ devisId: "d", leadId: null, origine: "saisi" }, true],
    [{ devisId: "d", leadId: "l", origine: "lead_converti" }, true],
    [{ devisId: "", leadId: null, origine: "saisi" }, false],
    [{ devisId: "d", leadId: "", origine: "saisi" }, false],
    [{ devisId: "d", leadId: null, origine: "invente" }, false],
    [{ devisId: "d", origine: "saisi" }, false],
    [null, false],
    ["d", false],
  ])("%j -> %s", (valeur, attendu) => {
    expect(estDevisConnuValide(valeur)).toBe(attendu);
  });
});
