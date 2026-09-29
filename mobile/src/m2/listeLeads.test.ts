import {
  CODE_SEGMENT_NON_CALCULABLE,
  FILTRE_AUCUN,
  OUTIL_LISTER_LEADS,
  SEGMENTS_LEAD,
  STATUTS_LEAD,
  construireArgumentsListerLeads,
  interpreterResultatListerLeads,
  lirePageLeads,
} from "./listeLeads";
import {
  NON_CALCULABLES_FICTIFS,
  REGLES_FICTIVES,
  SEGMENT_URGENT,
  enveloppeAcceptee,
  enveloppeRefusee,
  leadBrut,
  pageBrute,
} from "../vendeur/donneesDeTest";

describe("arguments de m2_lister_leads", () => {
  test("première page sans filtre : seulement l'instant de référence", () => {
    expect(construireArgumentsListerLeads("2026-09-29T12:00:00-04:00", FILTRE_AUCUN, 0)).toEqual({
      horodatage: "2026-09-29T12:00:00-04:00",
    });
  });

  test("filtre et rang : exactement les clés du schéma, jamais une personne ni une limite", () => {
    const args = construireArgumentsListerLeads("2026-09-29T12:00:00-04:00", { statut: "qualifie", segment: "hot_lead" }, 20);
    expect(args).toEqual({ horodatage: "2026-09-29T12:00:00-04:00", statut: "qualifie", segment: "hot_lead", decalage: 20 });
    expect(Object.keys(args).sort()).toEqual(["decalage", "horodatage", "segment", "statut"]);
    for (const interdit of ["owner", "proprietaire", "vendeur", "personne", "role", "limite"]) {
      expect(args).not.toHaveProperty(interdit);
    }
  });

  test("un filtre sur le seul statut n'envoie pas de segment", () => {
    const args = construireArgumentsListerLeads("2026-09-29T12:00:00-04:00", { statut: "nouveau", segment: null }, 0);
    expect(args).toEqual({ horodatage: "2026-09-29T12:00:00-04:00", statut: "nouveau" });
  });

  test("les catalogues fermés sont ceux de M2 : 9 statuts, 14 segments, sans doublon", () => {
    expect(OUTIL_LISTER_LEADS).toBe("m2_lister_leads");
    expect(STATUTS_LEAD).toHaveLength(9);
    expect(SEGMENTS_LEAD).toHaveLength(14);
    expect(new Set(SEGMENTS_LEAD).size).toBe(14);
    expect(new Set(STATUTS_LEAD).size).toBe(9);
  });
});

describe("lecture d'une page de leads", () => {
  test("un lead complet : chaque champ lu, segments avec règle citée et donnée déclenchante", () => {
    const lead = leadBrut("lead-a-01", { urgence_declaree: true, segments: [SEGMENT_URGENT] });
    const lecture = interpreterResultatListerLeads(
      enveloppeAcceptee(pageBrute({ leads: [lead], regles: REGLES_FICTIVES, nonCalculables: NON_CALCULABLES_FICTIFS })),
    );
    expect(lecture.ok).toBe(true);
    if (!lecture.ok) {
      return;
    }
    expect(lecture.page.total).toBe(1);
    expect(lecture.page.suivant).toBeNull();
    expect(lecture.page.leads[0]).toEqual({
      leadId: "lead-a-01",
      statut: "qualifie",
      proprietaire: "vendeur.fictif",
      travaux: "renovation_totale",
      ville: "Repentigny",
      urgenceDeclaree: true,
      ingereLe: "2026-09-01T09:00:00-04:00",
      derniereActivite: "2026-09-02T09:00:00-04:00",
      prochaineAction: { description: "Appeler le client (fictif)", echeance: "2026-09-05T09:00:00-04:00" },
      segments: [SEGMENT_URGENT],
      nonCalculables: [],
    });
    expect(lecture.page.regles.urgence_declaree_lead_ouvert).toContain("Urgence déclarée");
  });

  test("les segments non calculables gardent leur « manque X » : jamais une liste vide", () => {
    const lecture = interpreterResultatListerLeads(
      enveloppeAcceptee(pageBrute({ leads: [leadBrut("l1")], nonCalculables: NON_CALCULABLES_FICTIFS })),
    );
    expect(lecture.ok && lecture.page.segmentsNonCalculables).toEqual(NON_CALCULABLES_FICTIFS);
  });

  test("une valeur absente est absente : null, jamais un texte ni une valeur par défaut", () => {
    const lead = leadBrut("l1", {
      statut: null,
      proprietaire: null,
      travaux: null,
      ville: null,
      urgence_declaree: null,
      derniere_activite: null,
      prochaine_action: null,
    });
    const lecture = interpreterResultatListerLeads(enveloppeAcceptee(pageBrute({ leads: [lead] })));
    expect(lecture.ok && lecture.page.leads[0]).toMatchObject({
      statut: null,
      proprietaire: null,
      travaux: null,
      ville: null,
      urgenceDeclaree: null,
      derniereActivite: null,
      prochaineAction: null,
    });
  });

  test("le non_calculable propre à un lead est lu et gardé", () => {
    const lead = leadBrut("l1", { non_calculables: [NON_CALCULABLES_FICTIFS[1]] });
    const lecture = interpreterResultatListerLeads(enveloppeAcceptee(pageBrute({ leads: [lead] })));
    expect(lecture.ok && lecture.page.leads[0].nonCalculables).toEqual([NON_CALCULABLES_FICTIFS[1]]);
  });

  test("la pagination : suivant et reste lus tels que le serveur les donne", () => {
    const lecture = interpreterResultatListerLeads(
      enveloppeAcceptee(pageBrute({ leads: [leadBrut("l1"), leadBrut("l2")], total: 5, decalage: 0 })),
    );
    expect(lecture.ok && [lecture.page.suivant, lecture.page.reste, lecture.page.affichees, lecture.page.total]).toEqual([2, 3, 2, 5]);
  });

  test("une page au-delà de la fin est vide, sans suivant, et lue comme telle (pas une erreur)", () => {
    const lecture = interpreterResultatListerLeads(enveloppeAcceptee(pageBrute({ leads: [], decalage: 500, total: 24 })));
    expect(lecture.ok && lecture.page.leads).toEqual([]);
    expect(lecture.ok && lecture.page.suivant).toBeNull();
  });

  test("le filtre rendu par le serveur est gardé (le rang n'a de sens que pour ce filtre)", () => {
    const lecture = interpreterResultatListerLeads(
      enveloppeAcceptee(pageBrute({ leads: [], filtre: { statut: "qualifie", segment: "hot_lead" } })),
    );
    expect(lecture.ok && lecture.page.filtre).toEqual({ statut: "qualifie", segment: "hot_lead" });
  });

  test.each([
    ["sans lead_id", { lead_id: undefined }],
    ["sans ingere_le", { ingere_le: undefined }],
    ["segments qui n'est pas une liste", { segments: "hot_lead" }],
    ["un segment sans règle", { segments: [{ segment: "hot_lead", donnee: {} }] }],
    ["un segment sans donnée", { segments: [{ segment: "hot_lead", regle: "r" }] }],
    ["un non_calculable sans manque", { non_calculables: [{ segment: "needs_photos" }] }],
    ["une prochaine action sans description", { prochaine_action: { echeance: "x" } }],
  ])("un lead illisible (%s) n'est pas montré à moitié : compté, jamais deviné", (_nom, surcharge) => {
    const bon = leadBrut("bon");
    const mauvais = { ...leadBrut("mauvais"), ...surcharge };
    const lecture = interpreterResultatListerLeads(enveloppeAcceptee(pageBrute({ leads: [bon, mauvais] })));
    expect(lecture.ok).toBe(true);
    if (lecture.ok) {
      expect(lecture.page.leads.map((l) => l.leadId)).toEqual(["bon"]);
      expect(lecture.page.illisibles).toBe(1);
    }
  });

  test.each([
    ["total texte", { total: "24" }],
    ["décalage négatif", { decalage: -1 }],
    ["reste manquant", { reste: undefined }],
    ["leads qui n'est pas une liste", { leads: {} }],
    ["règles dont une valeur n'est pas un texte", { regles: { r: 3 } }],
    ["segments_non_calculables manquant", { segments_non_calculables: undefined }],
    ["un non_calculable illisible dans la liste globale", { segments_non_calculables: [{ segment: "x" }] }],
    ["filtre absent", { filtre: undefined }],
    ["reste sans suivant : des leads manqueraient en silence", { total: 30, reste: 10, suivant: null }],
    ["suivant sans reste", { total: 2, reste: 0, suivant: 2 }],
    ["suivant qui ne progresse pas : « Voir plus » tournerait en rond", { total: 30, decalage: 10, reste: 10, suivant: 10 }],
    ["suivant en arrière", { total: 30, decalage: 10, reste: 10, suivant: 5 }],
    ["suivant décimal", { total: 30, reste: 10, suivant: 1.5 }],
  ])("une page illisible (%s) : réponse illisible, jamais une liste vide", (_nom, surcharge) => {
    const page = { ...pageBrute({ leads: [leadBrut("l1")] }), ...surcharge };
    expect(lirePageLeads(page)).toBeNull();
    expect(interpreterResultatListerLeads(enveloppeAcceptee(page))).toMatchObject({
      ok: false,
      genre: "illisible",
      verdict: { code: "reponse_illisible" },
    });
  });

  test("le refus d'un segment non calculable garde son code et son « manque X » : genre refus", () => {
    const detail = "segment quote_sent : non calculable, manque le fait « devis envoyé » de M3 (m3.devis_envoye, T4.7)";
    const lecture = interpreterResultatListerLeads(enveloppeRefusee(CODE_SEGMENT_NON_CALCULABLE, detail));
    expect(lecture).toEqual({ ok: false, genre: "refus", verdict: { code: "REJ-SEGMENT-NON-CALCULABLE", detail } });
  });

  test("un refus d'identité ou technique garde son genre (le cache ne remplace pas un refus)", () => {
    expect(interpreterResultatListerLeads(enveloppeRefusee("REJ-IDENTITE-APPAREIL-INVALIDE", "rôle retiré"))).toMatchObject({
      ok: false,
      genre: "refus",
    });
    expect(interpreterResultatListerLeads({ ok: false, erreur: "arguments_invalides", details: ["x"] })).toMatchObject({
      ok: false,
      genre: "technique",
    });
    expect(interpreterResultatListerLeads({ ok: true, tronque: true, apercu: "{" })).toMatchObject({
      ok: false,
      genre: "technique",
      verdict: { code: "reponse_tronquee" },
    });
  });
});
