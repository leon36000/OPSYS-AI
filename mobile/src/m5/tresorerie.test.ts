import { reponse } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import {
  COMPOSANTES_DU_CASH_LIBRE,
  construireArgumentsEcheances,
  construireArgumentsEtatTresorerie,
  construireArgumentsPrevision,
  lireEcheancesFiscales,
  lireEtatTresorerie,
  lirePrevisionTresorerie,
  OUTIL_ECHEANCES_FISCALES,
  OUTIL_ETAT_TRESORERIE,
  OUTIL_PREVOIR_TRESORERIE,
  STATUTS_ALERTE_PREVISION,
  STATUTS_ECHEANCE,
} from "./tresorerie";
import type { EcheancesFiscales, EtatTresorerie, PrevisionTresorerie } from "./tresorerie";

const MENTION = "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle.";

/** La valeur lue par M5 dans l'enveloppe d'une réponse enregistrée. `couple` : `resultat.resultat` ; `directe` : `resultat`. */
function valeurCouple(nom: string): any {
  return reponse(nom).resultat.resultat;
}
function valeurDirecte(nom: string): any {
  return reponse(nom).resultat;
}

function etat(nom: string): EtatTresorerie {
  const lu = lireEtatTresorerie(valeurDirecte(nom));
  if (lu === null) {
    throw new Error(`« ${nom} » devrait être lisible`);
  }
  return lu;
}
function prevision(nom: string): PrevisionTresorerie {
  const lu = lirePrevisionTresorerie(valeurCouple(nom));
  if (lu === null || lu.genre !== "prevision") {
    throw new Error(`« ${nom} » devrait être une prévision lisible`);
  }
  return lu;
}
function echeances(nom: string): EcheancesFiscales {
  const lu = lireEcheancesFiscales(valeurCouple(nom));
  if (lu === null) {
    throw new Error(`« ${nom} » devrait être lisible`);
  }
  return lu;
}

describe("les noms et les arguments", () => {
  test("le nom nu des trois outils", () => {
    expect([OUTIL_ETAT_TRESORERIE, OUTIL_PREVOIR_TRESORERIE, OUTIL_ECHEANCES_FISCALES]).toEqual([
      "m5_etat_tresorerie",
      "m5_prevoir_tresorerie",
      "m5_lire_echeances_fiscales",
    ]);
  });

  test("l'état de trésorerie n'a aucun argument : ni `role` ni `autorise_couts`", () => {
    expect(construireArgumentsEtatTresorerie()).toEqual({});
  });

  test("la prévision n'envoie que le jour de l'appareil, et le rang de la page suivante quand elle est demandée", () => {
    expect(construireArgumentsPrevision("2026-09-29")).toEqual({ aujourd_hui: "2026-09-29" });
    expect(construireArgumentsPrevision("2026-09-29", 0)).toEqual({ aujourd_hui: "2026-09-29" });
    expect(construireArgumentsPrevision("2026-09-29", 19)).toEqual({ aujourd_hui: "2026-09-29", depart: 19 });
    for (const args of [construireArgumentsPrevision("2026-09-29", 5), construireArgumentsEcheances("2026-09-29")]) {
      for (const interdit of ["horizon_semaines", "semaine", "role", "autorise_couts", "montant", "seuil", "limite", "personne"]) {
        expect(Object.keys(args)).not.toContain(interdit);
      }
    }
  });

  test("les échéances n'envoient que le jour de l'appareil", () => {
    expect(construireArgumentsEcheances("2026-09-29")).toEqual({ aujourd_hui: "2026-09-29" });
  });
});

describe("m5_etat_tresorerie, tel que le moteur le rend", () => {
  test("cash libre calculable : le solde, l'argent disponible et sa note, le cash libre et ses six composantes, à la cent près", () => {
    const lu = etat("tresorerie");

    expect(lu.role).toBe("admin");
    expect(lu.solde).toEqual({ genre: "connu", montant: "20000.00" });
    expect(lu.argentDisponible).toBe("19500.00");
    expect(lu.argentDisponibleNote).toBe("solde moins les réserves posées seulement : ce n'est PAS le cash libre, lire cash_libre");
    expect(lu.mention).toBe(MENTION);
    const cash = lu.cashLibre!;
    expect(cash).toMatchObject({ montant: "14106.32", calculable: true, enDeficit: false, auPlus: null, manque: [] });
    expect(cash.lecture).toBe("Cash libre : 14106.32 $ (solde moins toutes les obligations ci-dessous). Sous réserve : REJ-AP-UNITE-PRIX-NON-CONFIRMEE.");
    expect(cash.composantes.map((c) => c.id)).toEqual([...COMPOSANTES_DU_CASH_LIBRE]);
    expect(cash.composantes.map((c) => c.montant)).toEqual(["748.75", "3000.00", "900.00", "344.93", "400.00", "500.00"]);
    expect(cash.composantes.every((c) => c.calculee && c.plancher === null && c.manque.length === 0)).toBe(true);
    expect(cash.solde).toMatchObject({ id: "solde", montant: "20000.00", pieces: 2, dernierePiece: "2026-09-10T12:00:00-04:00" });
    expect(cash.composantes[1].source).toContain("déclaration du propriétaire");
    expect(cash.composantes[3].reserves).toEqual(["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]);
    expect(cash.reserves).toEqual(["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]);
    expect(cash.hypotheses).toHaveLength(6);
    expect(cash.hypothesesOmises).toBe(0);
    expect(cash.detailOmis).toBe(false);
  });

  test("les composantes du cash libre sont celles du serveur, dans l'ordre de la définition produit", () => {
    expect(COMPOSANTES_DU_CASH_LIBRE).toEqual(["taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"]);
  });

  test("sans les paies déclarées : le cash libre est « non calculable », dit ce qui manque, et n'est PAS zéro ; l'« au plus » est un repère", () => {
    const lu = etat("tresorerie_sans_paies");
    const cash = lu.cashLibre!;

    expect(cash.montant).toBeNull();
    expect(cash.calculable).toBe(false);
    expect(cash.enDeficit).toBeNull();
    expect(cash.auPlus).toBe("17106.32");
    expect(cash.manque).toEqual(["paies : REJ-CASH-PAIE-A-DECLARER"]);
    expect(cash.lecture).toContain("Ce n'est PAS de l'argent disponible");
    const paies = cash.composantes.find((c) => c.id === "paies")!;
    expect(paies).toMatchObject({ calculee: false, montant: null, plancher: null });
    expect(paies.manque).toEqual([{ code: "REJ-CASH-PAIE-A-DECLARER", detail: expect.stringContaining("Déclarer configuration.obligations_declarees.paies") }]);
    expect(cash.composantes.filter((c) => c.calculee)).toHaveLength(5);
    // Le solde, lui, est connu : l'argent disponible reste dit (avec sa note).
    expect(lu.solde).toEqual({ genre: "connu", montant: "20000.00" });
    expect(lu.argentDisponible).toBe("19500.00");
  });

  test("UN REGISTRE VIDE : le solde est INCONNU (aucun solde d'ouverture), jamais le « 0 » de l'état gelé", () => {
    const brute = valeurDirecte("tresorerie_sans_solde");
    expect(brute.solde).toBe("0"); // sans cela, ce test ne prouverait rien : le serveur écrit bien « 0 » ici
    expect(brute.argent_disponible).toBe("0");

    const lu = etat("tresorerie_sans_solde");

    expect(lu.solde).toEqual({
      genre: "inconnu",
      manque: [{ code: "REJ-CASH-SOLDE-ABSENT", detail: expect.stringContaining("le solde n'est pas connu") }],
    });
    expect(lu.argentDisponible).toBeNull();
    expect(lu.cashLibre).toMatchObject({ montant: null, calculable: false, auPlus: null });
    expect(lu.cashLibre!.manque).toEqual([
      "solde : REJ-CASH-SOLDE-ABSENT",
      "taxes_a_remettre : REJ-FISCAL-FREQUENCE-A-DECLARER",
      "paies : REJ-CASH-PAIE-A-DECLARER",
      "das : REJ-CASH-DAS-A-DECLARER",
      "dettes : REJ-CASH-DETTES-A-DECLARER",
      "reserves : REJ-CASH-RESERVES-A-DECLARER",
    ]);
    expect(JSON.stringify(lu.solde)).not.toContain('"0"');
    expect(lu.cashLibre!.composantes.filter((c) => !c.calculee).map((c) => c.id)).toEqual(["taxes_a_remettre", "paies", "das", "dettes", "reserves"]);
    // Un zéro que le registre a écrit reste un zéro : rien à retrancher aux comptes à payer.
    expect(lu.cashLibre!.composantes.find((c) => c.id === "comptes_a_payer")).toMatchObject({ calculee: true, montant: "0.00" });
  });

  test("un refus (personne désactivée) n'est pas un état : le verdict du serveur, par l'enveloppe", () => {
    expect(interpreter(reponse("refus_identite_tresorerie"), "directe", lireEtatTresorerie)).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" },
    });
  });

  test("la vue sans droit de voir les montants : ni solde ni cash libre, dite masquée", () => {
    const masquee = { type: "ETAT_FINANCIER", role: "admin", solde: null, argent_disponible: null, taux_utilises: [], etat_id: "x", cash_libre: null, mention: MENTION };
    expect(lireEtatTresorerie(masquee)).toEqual({
      role: "admin",
      solde: { genre: "masque" },
      argentDisponible: null,
      argentDisponibleNote: null,
      cashLibre: null,
      mention: MENTION,
    });
    // Un montant sans cash libre est une contradiction : rien n'est montré.
    expect(lireEtatTresorerie({ ...masquee, solde: "20000.00" })).toBeNull();
    expect(lireEtatTresorerie({ ...masquee, argent_disponible: "0" })).toBeNull();
  });
});

describe("ce que la lecture de l'état refuse (fail-closed)", () => {
  function modifie(nom: string, modification: (etat: any) => void): EtatTresorerie | null {
    const brut = valeurDirecte(nom);
    modification(brut);
    return lireEtatTresorerie(brut);
  }
  const composante = (etat: any, id: string) => etat.cash_libre.composantes.find((c: any) => c.id === id);

  test.each([
    ["ce n'est pas un état financier", (e: any) => (e.type = "AUTRE")],
    ["LA MENTION « Analyse préparatoire IA » MANQUE : elle voyage avec la donnée", (e: any) => delete e.mention],
    ["la mention est vide", (e: any) => (e.mention = "  ")],
    ["le solde gelé est un nombre (un montant n'est jamais un nombre)", (e: any) => (e.solde = 20000)],
    ["le solde gelé diffère du solde du cash libre : le serveur se contredit", (e: any) => (e.solde = "19999.00")],
    ["l'argent disponible manque alors que le solde est connu", (e: any) => (e.argent_disponible = null)],
    ["le cash libre n'est pas un objet", (e: any) => (e.cash_libre = "14106.32")],
    ["le cash libre n'est pas de type CASH_LIBRE", (e: any) => (e.cash_libre.type = "AUTRE")],
    ["`calculable` n'est pas un booléen", (e: any) => (e.cash_libre.calculable = "oui")],
    ["le cash libre calculable est un nombre", (e: any) => (e.cash_libre.cash_libre = 14106.32)],
    ["le cash libre est calculable sans montant", (e: any) => (e.cash_libre.cash_libre = null)],
    ["le cash libre est calculable sans dire s'il est en déficit", (e: any) => (e.cash_libre.en_deficit = null)],
    ["le cash libre est calculable avec un repère « au plus »", (e: any) => (e.cash_libre.au_plus = "1.00")],
    ["le cash libre est calculable alors que des manques sont dits", (e: any) => (e.cash_libre.manque = ["paies : REJ-CASH-PAIE-A-DECLARER"])],
    ["le cash libre est calculable alors qu'une composante ne l'est pas", (e: any) => Object.assign(composante(e, "paies"), { statut: "NON_CALCULABLE", montant: null })],
    ["la lecture (phrase de M5) manque", (e: any) => delete e.cash_libre.lecture],
    ["la composante solde manque", (e: any) => delete e.cash_libre.solde],
    ["les composantes ne sont pas une liste", (e: any) => (e.cash_libre.composantes = {})],
    ["une composante est illisible", (e: any) => delete composante(e, "paies").source],
    ["une composante « calculée » sans montant", (e: any) => (composante(e, "das").montant = null)],
    ["une composante « non calculable » qui porte un montant", (e: any) => (composante(e, "das").statut = "NON_CALCULABLE")],
    ["une composante au statut inconnu", (e: any) => (composante(e, "das").statut = "ESTIME")],
    ["une composante au montant numérique", (e: any) => (composante(e, "das").montant = 900)],
    ["les réserves ne sont pas une liste de textes", (e: any) => (e.cash_libre.reserves = [1])],
    ["les hypothèses ne sont pas une liste de textes", (e: any) => (e.cash_libre.hypotheses = [1])],
  ])("réponse illisible quand %s", (_nom, modification) => {
    expect(modifie("tresorerie", modification)).toBeNull();
  });

  test.each([
    ["non calculable avec un chiffre de cash libre", (e: any) => (e.cash_libre.cash_libre = "0.00")],
    ["non calculable avec un déficit dit", (e: any) => (e.cash_libre.en_deficit = false)],
    ["non calculable alors que toutes les composantes sont calculées", (e: any) => Object.assign(composante(e, "paies"), { statut: "CALCULE", montant: "3000.00", manque: undefined })],
    ["un « au plus » qui n'est pas un décimal", (e: any) => (e.cash_libre.au_plus = "peu")],
    ["une composante qui dit ce qui manque sans être lisible", (e: any) => (composante(e, "paies").manque = [{ code: "X" }])],
  ])("réponse illisible quand le cash libre est %s", (_nom, modification) => {
    expect(modifie("tresorerie_sans_paies", modification)).toBeNull();
  });

  test.each([
    ["ni objet ni rien", null],
    ["un texte", "état"],
    ["une liste", []],
  ])("%s : illisible", (_nom, brut) => {
    expect(lireEtatTresorerie(brut)).toBeNull();
  });

  test("le détail omis et les hypothèses omises (réponse bornée par le serveur) sont dits, pas devinés", () => {
    const lu = modifie("tresorerie", (e) => {
      e.cash_libre.hypotheses = [];
      e.cash_libre.hypotheses_omises = 6;
      e.cash_libre.detail_omis = true;
    });
    expect(lu?.cashLibre).toMatchObject({ hypotheses: [], hypothesesOmises: 6, detailOmis: true });
    expect(modifie("tresorerie", (e) => (e.cash_libre.hypotheses_omises = -1))).toBeNull();
    expect(modifie("tresorerie", (e) => (e.cash_libre.detail_omis = "oui"))).toBeNull();
  });

  test("un déficit est un montant négatif, rendu tel quel, jamais ramené à zéro", () => {
    const lu = modifie("tresorerie", (e) => {
      e.cash_libre.cash_libre = "-250.00";
      e.cash_libre.en_deficit = true;
    });
    expect(lu?.cashLibre).toMatchObject({ montant: "-250.00", enDeficit: true, calculable: true });
  });
});

describe("m5_prevoir_tresorerie, telle que le moteur la rend", () => {
  test("la prévision calculable : six semaines, l'alerte de la semaine 2, le plus bas, le cash libre prévu", () => {
    const lu = prevision("prevision");

    expect(lu).toMatchObject({
      role: "admin",
      aujourdHui: "2026-09-29",
      horizonSemaines: 6,
      finHorizon: "2026-11-09",
      calculable: true,
      nonCalculableAPartirDe: null,
      manque: [],
      premiereSemaineEnDeficit: null,
      mention: MENTION,
    });
    expect(lu.lecture).toBe("Solde prévu : 20000.00 $ aujourd'hui, 20355.07 $ à la fin de la semaine 6 ; le plus bas : 17000.00 $ (semaine 2). Alerte : sous le seuil de 18000.00 $ en semaine(s) 2.");
    expect(lu.alerte).toEqual({
      statut: "ALERTE",
      seuil: "18000.00",
      sourceDuSeuil: { source: "décision de Nathan (fictive)", au: "2026-09-25" },
      semaines: [2],
      nonEvalueeAPartirDe: null,
      manque: null,
    });
    expect(lu.plusBas).toEqual({ semaine: 2, solde: "17000.00" });
    expect(lu.soldeInitial).toMatchObject({ montant: "20000.00", dernierePiece: "2026-09-10T12:00:00-04:00" });
    expect(lu.cashLibreAujourdhui).toEqual({ montant: "14106.32", manque: [] });
    expect(lu.semaines).toHaveLength(6);
    expect(lu.semaines.map((s) => s.calculee && s.soldeFin)).toEqual(["20000.00", "17000.00", "21503.82", "21503.82", "20355.07", "20355.07"]);
    expect(lu.semaines[1]).toMatchObject({ semaine: 2, du: "2026-10-06", entrees: "0.00", sorties: "3000.00", sousSeuil: true, enDeficit: false, lignes: 1 });
    expect(lu.semaines[2]).toMatchObject({ entrees: "5748.75", sorties: "1244.93", cashLibrePrevu: "19855.07", sousSeuil: false });
    expect(lu.auDela.entrees).toEqual({ nombre: 0, total: "0.00", nonChiffres: 0 });
    expect(lu.reserves).toEqual(["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]);
    expect(lu.limites).toHaveLength(7);
    expect(lu).toMatchObject({ total: 6, depart: 0, affichees: 6, reste: 0, prochainDepart: null, semainesIllisibles: 0 });
  });

  test("sans les paies : « non calculable à partir de la semaine 2 » ; la semaine 1 est calculée, les autres n'ont AUCUN chiffre", () => {
    const lu = prevision("prevision_sans_paies");

    expect(lu.calculable).toBe(false);
    expect(lu.nonCalculableAPartirDe).toBe(2);
    expect(lu.lecture).toContain("non calculable à partir de la semaine 2");
    expect(lu.manque).toEqual([
      {
        code: "REJ-CASH-PAIE-A-DECLARER",
        aPartirDeSemaine: 2,
        nombre: 1,
        exemples: ["obligation:paies"],
        detail: expect.stringContaining("Déclarer configuration.obligations_declarees.paies"),
      },
    ]);
    expect(lu.semaines.map((s) => s.calculee)).toEqual([true, false, false, false, false, false]);
    expect(lu.semaines[0]).toMatchObject({ soldeFin: "20000.00", cashLibrePrevu: null });
    for (const semaine of lu.semaines.slice(1)) {
      expect(Object.keys(semaine).sort()).toEqual(["calculee", "du", "lignes", "semaine"]);
    }
    expect(lu.alerte).toMatchObject({ statut: "NON_EVALUEE", nonEvalueeAPartirDe: 2, seuil: "18000.00" });
    expect(lu.cashLibreAujourdhui).toEqual({ montant: null, manque: ["paies : REJ-CASH-PAIE-A-DECLARER"] });
    expect(lu.plusBas).toEqual({ semaine: 1, solde: "20000.00" });
  });

  test("sans seuil d'alerte : « seuil à configurer », avec ce que M5 demande de déclarer (jamais une alerte inventée)", () => {
    const lu = prevision("prevision_sans_seuil");
    expect(lu.alerte).toMatchObject({
      statut: "SEUIL_A_CONFIGURER",
      seuil: null,
      sourceDuSeuil: null,
      semaines: [],
      manque: { code: "REJ-PREVISION-SEUIL-A-CONFIGURER", detail: expect.stringContaining("à déclarer dans configuration.prevision.seuil_alerte") },
    });
    expect(lu.semaines.every((s) => s.calculee && !s.sousSeuil)).toBe(true);
  });

  test("un seuil que le solde ne franchit pas : aucune alerte, et le seuil est dit", () => {
    expect(prevision("prevision_sans_alerte").alerte).toMatchObject({ statut: "AUCUNE", seuil: "1000.00", semaines: [] });
  });

  test("les statuts d'alerte sont ceux du serveur", () => {
    expect([...STATUTS_ALERTE_PREVISION].sort()).toEqual(["ALERTE", "AUCUNE", "NON_EVALUEE", "SEUIL_A_CONFIGURER"]);
    for (const nom of ["prevision", "prevision_sans_paies", "prevision_sans_seuil", "prevision_sans_alerte"]) {
      expect(STATUTS_ALERTE_PREVISION).toContain(prevision(nom).alerte.statut);
    }
  });

  test("l'horizon non déclaré est un refus qui dit quoi déclarer, pas une prévision", () => {
    expect(interpreter(reponse("prevision_horizon_a_declarer"), "couple", lirePrevisionTresorerie)).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-PREVISION-HORIZON-A-CONFIGURER", detail: expect.stringContaining("configuration.prevision.horizon_semaines") },
    });
  });

  test("vingt-six semaines : deux pages du MÊME horizon (même empreinte), la seconde reprend au rang que la première a dit", () => {
    const premiere = prevision("prevision_longue_page_1");
    const seconde = prevision("prevision_longue_page_2");

    expect(premiere).toMatchObject({ total: 26, depart: 0, affichees: 19, reste: 7, prochainDepart: 19 });
    expect(seconde).toMatchObject({ total: 26, depart: 19, affichees: 7, reste: 0, prochainDepart: null });
    expect(premiere.previsionId).toBe(seconde.previsionId);
    expect(premiere.semaines.map((s) => s.semaine)).toEqual(Array.from({ length: 19 }, (_, i) => i + 1));
    expect(seconde.semaines.map((s) => s.semaine)).toEqual([20, 21, 22, 23, 24, 25, 26]);
  });

  test("la vue sans droit de voir les montants : l'horizon seulement, dite masquée", () => {
    expect(lirePrevisionTresorerie({ role: "admin", montants_masques: true, horizon_semaines: 6, mention: MENTION })).toEqual({
      genre: "masquee",
      role: "admin",
      horizonSemaines: 6,
      mention: MENTION,
    });
    expect(lirePrevisionTresorerie({ role: "admin", montants_masques: true, horizon_semaines: 6 })).toBeNull();
    expect(lirePrevisionTresorerie({ role: "admin", montants_masques: true, mention: MENTION })).toBeNull();
  });
});

describe("ce que la lecture de la prévision refuse (fail-closed)", () => {
  function modifie(nom: string, modification: (page: any) => void): PrevisionTresorerie | null {
    const brut = valeurCouple(nom);
    modification(brut);
    const lu = lirePrevisionTresorerie(brut);
    return lu === null || lu.genre !== "prevision" ? null : lu;
  }

  test.each([
    ["LA MENTION MANQUE", (p: any) => delete p.mention],
    ["ce n'est pas une prévision", (p: any) => (p.type = "AUTRE")],
    ["`calculable` n'est pas un booléen", (p: any) => (p.calculable = "oui")],
    ["`calculable` contredit `non_calculable_a_partir_de`", (p: any) => (p.non_calculable_a_partir_de = 3)],
    ["`non_calculable_a_partir_de` n'est pas un entier", (p: any) => (p.non_calculable_a_partir_de = "3")],
    ["la lecture (phrase de M5) manque", (p: any) => delete p.lecture],
    ["le solde initial manque", (p: any) => delete p.solde_initial],
    ["le solde initial est un nombre", (p: any) => (p.solde_initial.montant = 20000)],
    ["l'alerte manque", (p: any) => delete p.alerte],
    ["le plus bas n'est pas lisible", (p: any) => (p.plus_bas = { semaine: 2 })],
    ["le hors-horizon manque", (p: any) => delete p.au_dela_de_l_horizon],
    ["le total hors-horizon n'est pas un décimal", (p: any) => (p.au_dela_de_l_horizon.sorties.total = 0)],
    ["un manque de la prévision est illisible", (p: any) => (p.manque = [{ code: "X" }])],
    ["les encaissements non comptés sont illisibles", (p: any) => (p.encaissements_non_comptes = [{ code: "X" }])],
    ["l'empreinte de la prévision manque", (p: any) => delete p.prevision_id],
    ["les semaines ne sont pas une liste", (p: any) => (p.semaines = {})],
    ["`affichees` n'est pas le nombre de semaines rendues", (p: any) => (p.affichees = 5)],
    ["le total n'est pas la somme de ce qui précède, de la page et de ce qui reste", (p: any) => (p.total = 7)],
    ["un reste sans rang pour la suite", (p: any) => Object.assign(p, { reste: 2, total: 8, prochain_depart: null })],
    ["un rang pour la suite alors que rien ne suit", (p: any) => (p.prochain_depart = 6)],
    ["les limites ne sont pas des textes", (p: any) => (p.limites = [1])],
  ])("réponse illisible quand %s", (_nom, modification) => {
    expect(modifie("prevision", modification)).toBeNull();
  });

  test("une pagination qui ne progresse pas (le rang suivant n'est pas depart + affichees) est illisible", () => {
    expect(modifie("prevision_longue_page_1", (p) => (p.prochain_depart = 0))).toBeNull();
    expect(modifie("prevision_longue_page_1", (p) => (p.prochain_depart = 18))).toBeNull();
    expect(modifie("prevision_longue_page_1", (p) => (p.reste = 6))).toBeNull();
  });

  test("UNE SEMAINE « calculée » après la semaine où la prévision devient non calculable est illisible (jamais un solde montré)", () => {
    const lu = modifie("prevision_sans_paies", (p) =>
      Object.assign(p.semaines[2], { statut: "CALCULE", entrees: "0.00", sorties: "0.00", solde_fin: "20000.00", cash_libre_prevu: null }),
    );
    expect(lu?.semainesIllisibles).toBe(1);
    expect(lu?.semaines.map((s) => s.semaine)).toEqual([1, 2, 4, 5, 6]);
  });

  test("une semaine « non calculable » qui porte quand même un chiffre est illisible", () => {
    expect(modifie("prevision_sans_paies", (p) => (p.semaines[1].solde_fin = "17000.00"))?.semainesIllisibles).toBe(1);
  });

  test("une semaine « non calculable » alors que la prévision est calculable est illisible", () => {
    expect(modifie("prevision", (p) => (p.semaines[3] = { semaine: 4, du: "2026-10-20", statut: "NON_CALCULABLE", lignes: 0 }))?.semainesIllisibles).toBe(1);
  });

  test("une semaine « calculée » avant la semaine où la prévision devient non calculable, mais devenue non calculable, est illisible", () => {
    expect(modifie("prevision_sans_paies", (p) => (p.semaines[0] = { semaine: 1, du: "2026-09-29", statut: "NON_CALCULABLE", lignes: 0 }))?.semainesIllisibles).toBe(1);
  });

  test.each([
    ["statut inconnu", (s: any) => (s.statut = "ESTIMEE")],
    ["solde de fin numérique", (s: any) => (s.solde_fin = 17000)],
    ["solde de fin absent", (s: any) => delete s.solde_fin],
    ["entrées absentes", (s: any) => delete s.entrees],
    ["sorties non décimales", (s: any) => (s.sorties = "beaucoup")],
    ["cash libre prévu numérique", (s: any) => (s.cash_libre_prevu = 14106)],
    ["numéro de semaine absent", (s: any) => delete s.semaine],
    ["numéro de semaine nul", (s: any) => (s.semaine = 0)],
    ["date de début absente", (s: any) => delete s.du],
    ["indicateur de seuil qui n'est pas un booléen", (s: any) => (s.sous_seuil = "oui")],
    ["nombre de lignes négatif", (s: any) => (s.lignes = -1)],
  ])("une semaine avec %s est comptée illisible, les autres restent lues", (_nom, modification) => {
    const lu = modifie("prevision", (p) => modification(p.semaines[1]));
    expect(lu?.semainesIllisibles).toBe(1);
    expect(lu?.semaines).toHaveLength(5);
  });

  test("un solde négatif est un déficit rendu tel quel, jamais ramené à zéro", () => {
    const lu = modifie("prevision", (p) => Object.assign(p.semaines[1], { solde_fin: "-250.00", en_deficit: true }));
    expect(lu?.semaines[1]).toMatchObject({ calculee: true, soldeFin: "-250.00", enDeficit: true });
  });

  test.each([
    ["ni objet ni rien", null],
    ["un texte", "prévision"],
    ["une liste", []],
  ])("%s : illisible", (_nom, brut) => {
    expect(lirePrevisionTresorerie(brut)).toBeNull();
  });
});

describe("m5_lire_echeances_fiscales, telle que le moteur la rend", () => {
  test("les deux prochaines échéances TPS/TVQ : dates du calendrier, jours restants de M5, taxe nette de la période", () => {
    const lu = echeances("echeances");

    expect(lu).toMatchObject({
      role: "admin",
      aujourdHui: "2026-09-29",
      frequence: "trimestrielle",
      moisFinExercice: 12,
      particulierEnAffaires: null,
      taxesRemisesJusquAu: "2026-06-30",
      nonAffichees: 0,
      manque: [],
      anneesDeclarees: [2025, 2026],
      connuJusquAu: "2027-02-01",
      mention: MENTION,
    });
    expect(lu.echeances.map((e) => [e.periodeFin, e.limitePaiement, e.joursAvantPaiement, e.statut, e.periodeTerminee])).toEqual([
      ["2026-09-30", "2026-11-02", 34, "A_VENIR", false],
      ["2026-12-31", "2027-02-01", 125, "A_VENIR", false],
    ]);
    expect(lu.echeances[0].taxesNettes).toEqual({
      aRemettre: "748.75",
      tps: { collectee: "250.00", creditsIntrants: "0.00", nette: "250.00", aRemettre: "250.00" },
      tvq: { collectee: "498.75", creditsIntrants: "0.00", nette: "498.75", aRemettre: "498.75" },
      facturesClients: 1,
      facturesFournisseurs: 0,
    });
    expect(lu.echeances[1].taxesNettes?.aRemettre).toBe("0.00");
    expect(lu.avertissementCouverture).toContain("l'année 2027 n'est pas déclarée dans le calendrier");
    expect(lu.validationCpa).toEqual({ "2025": "A_VALIDER", "2026": "A_VALIDER" });
    expect(lu.versions).toEqual({ "2025": "2025-v1", "2026": "2026-v1" });
    expect(lu.sources).toHaveLength(4);
    expect(lu.sources[0]).toMatchObject({ organisme: "Revenu Québec", consulteLe: "2026-09-29" });
    expect(lu.horsPerimetre).toHaveLength(2);
    expect(lu.echeancesIllisibles).toBe(0);
  });

  test("une période échue depuis la dernière remise est EN RETARD, avec des jours restants négatifs que M5 a comptés", () => {
    const lu = echeances("echeances_en_retard");
    expect(lu.echeances[0]).toMatchObject({ statut: "EN_RETARD", joursAvantPaiement: -60, joursAvantProduction: -60, periodeTerminee: true });
    expect(lu.echeances.map((e) => e.statut)).toEqual(["EN_RETARD", "A_VENIR", "A_VENIR"]);
    expect([...STATUTS_ECHEANCE].sort()).toEqual(["A_VENIR", "EN_RETARD"]);
  });

  test("la fréquence de production non déclarée est un refus qui dit quoi déclarer : aucune échéance n'est supposée", () => {
    expect(interpreter(reponse("echeances_frequence_a_declarer"), "couple", lireEcheancesFiscales)).toMatchObject({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-FISCAL-FREQUENCE-A-DECLARER", detail: expect.stringContaining("configuration.fiscal.frequence_tps_tvq") },
    });
  });
});

describe("ce que la lecture des échéances refuse ou dit (fail-closed)", () => {
  function modifie(modification: (page: any) => void): EcheancesFiscales | null {
    const brut = valeurCouple("echeances");
    modification(brut);
    return lireEcheancesFiscales(brut);
  }

  test.each([
    ["LA MENTION MANQUE", (e: any) => delete e.mention],
    ["ce n'est pas un calendrier d'échéances", (e: any) => (e.type = "AUTRE")],
    ["le jour de référence manque", (e: any) => delete e.aujourd_hui],
    ["la fréquence manque", (e: any) => delete e.frequence],
    ["le mois de fin d'exercice n'est pas un entier", (e: any) => (e.mois_fin_exercice = "12")],
    ["le statut de particulier en affaires n'est ni un booléen ni nul", (e: any) => (e.particulier_en_affaires = "non")],
    ["le statut de particulier en affaires manque", (e: any) => delete e.particulier_en_affaires],
    ["la date de dernière remise n'est pas un texte", (e: any) => (e.taxes_remises_jusqu_au = 20260630)],
    ["les échéances ne sont pas une liste", (e: any) => (e.echeances = {})],
    ["le compte des échéances non affichées manque", (e: any) => delete e.non_affichees],
    ["les manques sont illisibles", (e: any) => (e.manque = [{ code: "X" }])],
    ["les années déclarées ne sont pas des entiers", (e: any) => (e.annees_declarees = ["2025"])],
    ["l'avertissement de couverture manque", (e: any) => delete e.avertissement_couverture],
    ["les versions ne sont pas un tableau de textes", (e: any) => (e.versions = { 2025: 1 })],
    ["la validation du CPA manque", (e: any) => delete e.validation_cpa],
    ["les sources ne sont pas une liste", (e: any) => (e.sources = "Revenu Québec")],
    ["le hors-périmètre n'est pas une liste de textes", (e: any) => (e.hors_perimetre = [1])],
  ])("réponse illisible quand %s", (_nom, modification) => {
    expect(modifie(modification)).toBeNull();
  });

  test.each([
    ["date de fin absente", (e: any) => delete e.periode_fin],
    ["limite de paiement absente", (e: any) => delete e.limite_paiement],
    ["jours restants non entiers", (e: any) => (e.jours_avant_paiement = "34")],
    ["jours restants décimaux", (e: any) => (e.jours_avant_production = 3.5)],
    ["période terminée qui n'est pas un booléen", (e: any) => (e.periode_terminee = "non")],
    ["statut absent", (e: any) => delete e.statut],
    ["taxe nette illisible (montant numérique)", (e: any) => (e.taxes_nettes.a_remettre = 748.75)],
    ["taxe nette sans TVQ", (e: any) => delete e.taxes_nettes.tvq],
    ["taxe nette dont un détail n'est pas décimal", (e: any) => (e.taxes_nettes.tps.nette = "peu")],
    ["manques de l'échéance illisibles", (e: any) => (e.manque = [1])],
  ])("une échéance avec %s est comptée illisible, l'autre reste lue", (_nom, modification) => {
    const lu = modifie((page) => modification(page.echeances[0]));
    expect(lu?.echeancesIllisibles).toBe(1);
    expect(lu?.echeances).toHaveLength(1);
  });

  test("sans date de dernière remise, M5 ne chiffre aucune taxe : `taxes_nettes` absente = non chiffrée, jamais zéro", () => {
    const lu = modifie((page) => {
      page.taxes_remises_jusqu_au = null;
      for (const e of page.echeances) {
        delete e.taxes_nettes;
      }
      page.manque = [{ code: "REJ-FISCAL-REMISE-A-DECLARER", detail: "aucun retard n'est détectable" }];
    });
    expect(lu?.taxesRemisesJusquAu).toBeNull();
    expect(lu?.echeances.map((e) => e.taxesNettes)).toEqual([null, null]);
    expect(lu?.manque).toEqual([{ code: "REJ-FISCAL-REMISE-A-DECLARER", detail: "aucun retard n'est détectable" }]);
  });

  test("une taxe nette que M5 ne peut pas chiffrer (facture illisible) est nulle, avec son manque", () => {
    const lu = modifie((page) => {
      page.echeances[0].taxes_nettes = null;
      page.echeances[0].manque = [{ code: "REJ-CASH-FACTURE-ILLISIBLE", detail: "1 facture(s) illisible(s)" }];
    });
    expect(lu?.echeances[0]).toMatchObject({
      taxesNettes: null,
      manque: [{ code: "REJ-CASH-FACTURE-ILLISIBLE", detail: "1 facture(s) illisible(s)" }],
    });
  });

  test.each([
    ["ni objet ni rien", null],
    ["un texte", "échéances"],
    ["une liste", []],
  ])("%s : illisible", (_nom, brut) => {
    expect(lireEcheancesFiscales(brut)).toBeNull();
  });
});
