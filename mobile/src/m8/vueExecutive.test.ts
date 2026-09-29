import { appel, reponse } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import {
  construireArgumentsVueExecutive,
  lireVueExecutive,
  OUTIL_VUE_EXECUTIVE,
  STATUT_MESURE_CALCULEE,
  STATUT_MESURE_NON_CALCULABLE,
  UNITES_CONNUES,
} from "./vueExecutive";
import type { VueExecutive } from "./vueExecutive";

/** La vue telle que le moteur la rend (`resultat` de l'enveloppe directe). */
function brute(nom: string): any {
  return reponse(nom).resultat;
}

function lue(nom: string): VueExecutive {
  const vue = lireVueExecutive(brute(nom));
  if (vue === null) {
    throw new Error(`la fixture « ${nom} » devrait être lisible`);
  }
  return vue;
}

describe("la vue exécutive, telle que le moteur la rend", () => {
  test("la vue d'une entreprise qui a travaillé : entonnoir, marge réelle de M5, stock de M6, cash libre « manque »", () => {
    const vue = lue("vue_executive");

    const mesures = Object.fromEntries(vue.entonnoir.mesures.map((m) => [m.metricId, m]));
    expect(Object.keys(mesures)).toHaveLength(8);
    expect(vue.entonnoir.mesuresIllisibles).toBe(0);
    // Un zéro écrit par le serveur est un zéro : « 0 » devis envoyés (statut calculé), pas « non calculable ».
    expect(mesures.m8_devis_envoyes).toMatchObject({ valeur: "0", calculee: true, unite: "devis", nom: "Devis envoyés" });
    expect(mesures.m8_leads_recus).toMatchObject({ valeur: "4", calculee: true, proprietaire: "m02-revenue-crm" });
    expect(mesures.m8_carnet_signe_cad).toMatchObject({ valeur: "1200.00", unite: "CAD" });
    // Sans devis envoyé, le taux n'a pas de dénominateur : non calculable, avec ce qui manque, JAMAIS un zéro.
    expect(mesures.m8_taux_acceptation_pct).toEqual({
      metricId: "m8_taux_acceptation_pct",
      nom: "Taux d'acceptation des devis",
      valeur: null,
      unite: "pourcentage",
      calculee: false,
      proprietaire: "m03-estimation",
      manque: ["m3.devis_envoye"],
    });
    expect(vue.entonnoir.sources.map((s) => [s.evenement, s.n, s.dernierFaitLe === null])).toEqual([
      ["m2.client_associe", 4, false],
      ["m2.lead_assigne", 4, false],
      ["m3.devis_envoye", 0, true],
      ["m3.devis_accepte", 4, false],
      ["m3.devis_sans_reponse", 0, true],
    ]);
    expect(vue.entonnoir.sansReponse).toEqual({ n: 0, devis: [], reste: 0 });
    expect(vue.entonnoir.seuils).toMatchObject({
      aConfigurer: ["m8_devis_sans_reponse", "m8_delai_lead_acceptation_jours", "m8_carnet_signe_cad"],
      evalues: [],
      invalides: [],
      ignores: [],
      configuration: expect.stringContaining("seuils_entonnoir"),
    });

    // La marge réelle de M5, telle quelle : un chantier chiffré, un chantier que M5 n'a pas pu chiffrer (et pourquoi).
    expect(vue.margeReelle).toMatchObject({ nChantiers: 2, nMargeConnue: 1, nNonCalculable: 1, reste: 0, illisibles: 0 });
    expect(vue.margeReelle.chantiers.map((c) => [c.devisId, c.margeReelleCad, c.raison])).toEqual([
      ["DEVIS-ADM-E-fictif", "114.00", null],
      ["DEVIS-ADM-A-fictif", null, "M5 n'a pas chiffré la marge réelle : REJ-COUT-PRIX-NON-DISPONIBLE, REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"],
    ]);

    // Le stock à commander : le résumé de M6, mot pour mot.
    expect(vue.stock).toMatchObject({ genre: "lu", nArticles: 1, reste: 0, seuilsAConfigurer: false, illisibles: 0 });
    expect(vue.stock.genre === "lu" && vue.stock.articles[0].resume).toContain("sous le seuil de 450 pi");
    expect(vue.stock.genre === "lu" && vue.stock.articles[0].actionProposee).toContain("bon de commande");

    // Le cash libre : M8 ne le lit pas, l'app ne le remplace par aucun chiffre.
    expect(vue.cashLibre).toEqual({
      genre: "manque",
      source: "M5 (m5_etat_tresorerie, T4.16)",
      manque: ["cash_libre"],
      aLire: "m5_etat_tresorerie (admin), avec la décomposition du cash libre",
    });
    expect(vue.manques.map((m) => m.champ)).toEqual(["m3.devis_envoye", "cash_libre"]);
    expect(vue.manques[1].raison).toContain("ne peut ni le lire ni le recalculer");
    expect(vue.portee).toContain("sans recalcul");
  });

  test("la vue d'une instance neuve : chaque mesure est « non calculable » et dit ce qui manque, aucune n'est zéro", () => {
    const vue = lue("vue_executive_vide");

    expect(vue.entonnoir.mesures).toHaveLength(8);
    for (const mesure of vue.entonnoir.mesures) {
      expect(mesure.calculee).toBe(false);
      expect(mesure.valeur).toBeNull();
      expect(mesure.manque.length).toBeGreaterThan(0);
    }
    expect(vue.entonnoir.mesures.find((m) => m.metricId === "m8_taux_acceptation_pct")?.manque).toEqual(["m3.devis_envoye", "m3.devis_accepte"]);
    expect(vue.entonnoir.sources.every((s) => s.n === 0 && s.dernierFaitLe === null)).toBe(true);
    expect(vue.margeReelle).toMatchObject({ nChantiers: 0, nMargeConnue: 0, nNonCalculable: 0, chantiers: [] });
    // M6 ne signale que ce qu'il a constaté : une liste vide est ce qu'il publie, pas un manque.
    expect(vue.stock).toMatchObject({ genre: "lu", nArticles: 0, articles: [] });
    expect(vue.manques.map((m) => m.champ)).toEqual([
      "m2.client_associe",
      "m2.lead_assigne",
      "m3.devis_envoye",
      "m3.devis_accepte",
      "m3.devis_sans_reponse",
      "cash_libre",
    ]);
  });

  test("passe par l'enveloppe : les deux vues sont lues, un refus de la personne désactivée n'est pas une vue", () => {
    expect(interpreter(reponse("vue_executive"), "directe", lireVueExecutive)).toMatchObject({ ok: true });
    expect(interpreter(reponse("refus_identite_vue_executive"), "directe", lireVueExecutive)).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "refus_metier" },
    });
  });

  test("le nom nu de l'outil et aucun argument", () => {
    expect(OUTIL_VUE_EXECUTIVE).toBe("m8_lire_vue_executive");
    expect(construireArgumentsVueExecutive()).toEqual({});
    expect(appel("vue_executive")).toEqual({ outil: OUTIL_VUE_EXECUTIVE, args: {} });
    expect(UNITES_CONNUES).toEqual(["leads", "devis", "pourcentage", "jours", "CAD"]);
  });
});

describe("ce que ce lecteur refuse de lire (fail-closed)", () => {
  function modifiee(modification: (vue: any) => void): VueExecutive | null {
    const vue = brute("vue_executive");
    modification(vue);
    return lireVueExecutive(vue);
  }
  const mesure = (vue: any, id: string) => vue.entonnoir.mesures.find((m: any) => m.metric_id === id);

  test.each([
    ["ce n'est pas une vue exécutive", (v: any) => (v.vue = "autre")],
    ["la portée manque", (v: any) => delete v.portee],
    ["l'entonnoir manque", (v: any) => delete v.entonnoir],
    ["les devis en attente manquent", (v: any) => delete v.entonnoir.devis_en_attente],
    ["les seuils manquent", (v: any) => delete v.entonnoir.seuils],
    ["la marge réelle manque", (v: any) => delete v.marge_reelle],
    ["le stock manque", (v: any) => delete v.stock_a_commander],
    ["le cash libre manque", (v: any) => delete v.cash_libre],
    ["les manques ne sont pas une liste", (v: any) => (v.manques = "aucun")],
    ["les mesures ne sont pas une liste", (v: any) => (v.entonnoir.mesures = {})],
    ["un compte de chantiers négatif", (v: any) => (v.marge_reelle.n_chantiers = -1)],
    ["un reste de devis qui n'est pas un entier", (v: any) => (v.entonnoir.devis_en_attente.sans_reponse.reste = "0")],
    ["un statut de stock inconnu", (v: any) => (v.stock_a_commander.statut = "peut-etre")],
    ["un stock lu sans son indicateur de seuils", (v: any) => delete v.stock_a_commander.seuils_a_configurer],
  ])("réponse illisible quand %s", (_nom, modification) => {
    expect(modifiee(modification)).toBeNull();
  });

  test.each([
    ["ni objet ni rien", null],
    ["un texte", "vue"],
    ["une liste", []],
    ["un objet vide", {}],
  ])("%s : illisible", (_nom, valeur) => {
    expect(lireVueExecutive(valeur)).toBeNull();
  });

  test("une mesure « calculée » sans valeur est illisible : jamais un zéro montré à sa place", () => {
    const vue = modifiee((v) => (mesure(v, "m8_leads_recus").valeur = null));
    expect(vue?.entonnoir.mesuresIllisibles).toBe(1);
    expect(vue?.entonnoir.mesures.map((m) => m.metricId)).not.toContain("m8_leads_recus");
  });

  test("une mesure « non calculable » qui porte quand même une valeur est illisible (le serveur se contredit)", () => {
    const vue = modifiee((v) => (mesure(v, "m8_taux_acceptation_pct").valeur = "0.00"));
    expect(vue?.entonnoir.mesuresIllisibles).toBe(1);
    expect(vue?.entonnoir.mesures.map((m) => m.metricId)).not.toContain("m8_taux_acceptation_pct");
  });

  test.each([
    ["statut inconnu", (m: any) => (m.statut = "estimee")],
    ["valeur qui n'est pas un décimal", (m: any) => (m.valeur = "beaucoup")],
    ["valeur numérique (un montant n'est jamais un nombre)", (m: any) => (m.valeur = 4)],
    ["nom absent", (m: any) => delete m.nom],
    ["unité absente", (m: any) => delete m.unite],
    ["propriétaire absent", (m: any) => delete m.proprietaire],
  ])("une mesure avec %s est comptée illisible, les autres restent lues", (_nom, modification) => {
    const vue = modifiee((v) => modification(mesure(v, "m8_devis_acceptes")));
    expect(vue?.entonnoir.mesuresIllisibles).toBe(1);
    expect(vue?.entonnoir.mesures).toHaveLength(7);
  });

  test("le manque d'une mesure non calculable doit être une liste de textes", () => {
    const vue = modifiee((v) => (mesure(v, "m8_taux_acceptation_pct").manque = [1, 2]));
    expect(vue?.entonnoir.mesuresIllisibles).toBe(1);
  });

  test("une marge « calculée » sans montant, ou « non calculable » avec un montant, est illisible", () => {
    expect(modifiee((v) => (v.marge_reelle.chantiers[0].marge_reelle_cad = null))?.margeReelle.illisibles).toBe(1);
    expect(modifiee((v) => (v.marge_reelle.chantiers[1].marge_reelle_cad = "0.00"))?.margeReelle.illisibles).toBe(1);
    expect(modifiee((v) => (v.marge_reelle.chantiers[0].marge_reelle_cad = 114))?.margeReelle.illisibles).toBe(1);
    expect(modifiee((v) => (v.marge_reelle.chantiers[0].statut = "estimee"))?.margeReelle.illisibles).toBe(1);
  });

  test("une marge non calculable sans raison reste « non calculable » (la raison est absente, pas inventée)", () => {
    const vue = modifiee((v) => delete v.marge_reelle.chantiers[1].raison);
    expect(vue?.margeReelle.chantiers[1]).toMatchObject({ margeReelleCad: null, raison: null });
  });

  test("un article de stock illisible est compté, jamais montré à moitié", () => {
    const vue = modifiee((v) => delete v.stock_a_commander.articles[0].resume);
    expect(vue?.stock).toMatchObject({ genre: "lu", articles: [], illisibles: 1 });
  });

  test("un stock « manque » est un manque nommé, pas « rien à commander »", () => {
    const vue = modifiee((v) => (v.stock_a_commander = { source: "M6", statut: "manque", manque: ["stock_a_commander"] }));
    expect(vue?.stock).toEqual({ genre: "manque", source: "M6", manque: ["stock_a_commander"] });
  });

  test("un cash libre dont le statut est inconnu de cette version est dit inconnu, jamais lu comme un chiffre", () => {
    const vue = modifiee((v) => (v.cash_libre = { statut: "calcule", cash_libre: "14106.32", source: "M5" }));
    expect(vue?.cashLibre).toEqual({ genre: "inconnu", statut: "calcule" });
    expect(JSON.stringify(vue?.cashLibre)).not.toContain("14106");
  });

  test("un manque de la vue illisible est compté", () => {
    const vue = modifiee((v) => delete v.manques[0].raison);
    expect(vue?.manques).toHaveLength(1);
    expect(vue?.manquesIllisibles).toBe(1);
  });

  test("les seuils évalués sont lus tels quels (seuil franchi : un constat chiffré du serveur)", () => {
    const vue = modifiee((v) => {
      v.entonnoir.seuils.evalues = [
        { metric_id: "m8_devis_sans_reponse", statut: "franchi", valeur: "3", unite: "devis", sens: "au_dessus", seuil: "2" },
      ];
    });
    expect(vue?.entonnoir.seuils.evalues).toEqual([
      { metricId: "m8_devis_sans_reponse", statut: "franchi", valeur: "3", unite: "devis", sens: "au_dessus", seuil: "2" },
    ]);
    expect(modifiee((v) => (v.entonnoir.seuils.evalues = [{ metric_id: "x" }]))?.entonnoir.seuils.illisibles).toBe(1);
  });

  test("les statuts de mesure sont ceux du serveur", () => {
    expect([STATUT_MESURE_CALCULEE, STATUT_MESURE_NON_CALCULABLE]).toEqual(["calculee", "non_calculable"]);
  });
});
