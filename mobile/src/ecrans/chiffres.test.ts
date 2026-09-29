import { reponse } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import { fusionnerPagePrevision } from "../m5/pagesPrevision";
import { lireEcheancesFiscales, lireEtatTresorerie, lirePrevisionTresorerie } from "../m5/tresorerie";
import type { EcheancesFiscales, EtatTresorerie, PrevisionLue, PrevisionTresorerie } from "../m5/tresorerie";
import {
  decisionSuitePrevision,
  ligneDeManque,
  presenterEcheances,
  presenterPrevision,
  presenterTresorerie,
  previsionAPoursuivre,
  remplacerPrevision,
  vueEcheances,
  vuePrevision,
  vueTresorerie,
} from "./chiffres";
import type { VuePrevisionComplete } from "./chiffres";
import { duCache, duServeur, echeancesDe, previsionDe, tresorerieDe } from "./donneesDeVue";

const NBSP = " ";
/** Écrit un montant fr-CA avec des espaces ordinaires (plus lisible) : le formateur met des espaces insécables. */
const n = (texte: string): string => texte.replace(/ /g, NBSP);
const DECALAGE = -240;
const MENTION = "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle.";

function etatDeBrut(brut: unknown): EtatTresorerie {
  const lu = interpreter(brut, "directe", lireEtatTresorerie);
  if (!lu.ok) {
    throw new Error(`état illisible : ${lu.verdict.code}`);
  }
  return lu.valeur;
}

function previsionDeBrut(brut: unknown): PrevisionLue {
  const lu = interpreter(brut, "couple", lirePrevisionTresorerie);
  if (!lu.ok) {
    throw new Error(`prévision illisible : ${lu.verdict.code}`);
  }
  return lu.valeur;
}

function echeancesDeBrut(brut: unknown): EcheancesFiscales {
  const lu = interpreter(brut, "couple", lireEcheancesFiscales);
  if (!lu.ok) {
    throw new Error(`échéances illisibles : ${lu.verdict.code}`);
  }
  return lu.valeur;
}

function complete(prevision: PrevisionLue): VuePrevisionComplete {
  const vue = presenterPrevision(prevision, "fr-CA", DECALAGE);
  if (vue.genre !== "prevision") {
    throw new Error("une prévision complète était attendue");
  }
  return vue;
}

function tresorerieEnPrevision(nom: string): PrevisionTresorerie {
  const prevision = previsionDe(nom);
  if (prevision.genre !== "prevision") {
    throw new Error("une prévision complète était attendue");
  }
  return prevision;
}

describe("la trésorerie et le cash libre", () => {
  test("un solde connu : le solde, l'argent disponible AVEC sa note, et un cash libre calculé", () => {
    const vue = presenterTresorerie(tresorerieDe("tresorerie"), "fr-CA", DECALAGE);
    expect(vue.solde).toEqual({
      genre: "connu",
      texte: { cle: "admin.chiffres.tresorerie.solde", params: { montant: n("20 000,00 $") } },
      manque: [],
    });
    expect(vue.argentDisponible).toEqual({
      texte: { cle: "admin.chiffres.tresorerie.argentDisponible", params: { montant: n("19 500,00 $") } },
      note: "solde moins les réserves posées seulement : ce n'est PAS le cash libre, lire cash_libre",
    });
    expect(vue.cashLibre?.calculable).toBe(true);
    expect(vue.cashLibre?.resume).toEqual({ cle: "admin.chiffres.cashLibre.calcule", params: { montant: n("14 106,32 $") } });
    expect(vue.cashLibre?.enDeficit).toBeNull();
    expect(vue.cashLibre?.auPlus).toBeNull();
    expect(vue.cashLibre?.reserves).toEqual({ cle: "admin.chiffres.reserves", params: { reserves: "REJ-AP-UNITE-PRIX-NON-CONFIRMEE" } });
    expect(vue.cashLibre?.hypotheses).toHaveLength(6);
    expect(vue.cashLibre?.lecture).toContain("Cash libre : 14106.32 $");
  });

  test("le solde d'abord, puis les six composantes retranchées, chacune avec son libellé", () => {
    const composantes = presenterTresorerie(tresorerieDe("tresorerie"), "fr-CA", DECALAGE).cashLibre?.composantes ?? [];
    expect(composantes.map((c) => c.libelle.cle)).toEqual([
      "admin.chiffres.composantes.solde",
      "admin.chiffres.composantes.taxes_a_remettre",
      "admin.chiffres.composantes.paies",
      "admin.chiffres.composantes.das",
      "admin.chiffres.composantes.comptes_a_payer",
      "admin.chiffres.composantes.dettes",
      "admin.chiffres.composantes.reserves",
    ]);
    expect(composantes.every((c) => c.calculee)).toBe(true);
    expect(composantes[2].valeur).toEqual({ cle: "admin.chiffres.composante.montant", params: { montant: n("3 000,00 $") } });
    expect(composantes[2].source.params?.source).toContain("déclaration du propriétaire");
  });

  test("la dernière pièce d'une composante : un jour reste un jour, un instant passe à l'heure de l'appareil", () => {
    const [solde, taxes, , , comptes] = presenterTresorerie(tresorerieDe("tresorerie"), "fr-CA", DECALAGE).cashLibre?.composantes ?? [];
    expect(solde.dernierePiece?.params).toEqual({ date: "2026-09-10 12:00" }); // 12:00-04:00 = 12:00 à Montréal
    expect(taxes.dernierePiece?.params).toEqual({ date: "2026-09-14" }); // un jour n'est pas décalé d'une journée
    expect(comptes.dernierePiece?.params).toEqual({ date: "2026-09-14 09:00" });
    const utc = presenterTresorerie(tresorerieDe("tresorerie"), "fr-CA", 0).cashLibre?.composantes ?? [];
    expect(utc[0].dernierePiece?.params).toEqual({ date: "2026-09-10 16:00" });
    expect(utc[1].dernierePiece?.params).toEqual({ date: "2026-09-14" });
  });

  test("les réserves d'une composante (un manque de confirmation que M5 garde ouvert) sont dites avec elle", () => {
    const comptes = presenterTresorerie(tresorerieDe("tresorerie"), "fr-CA", DECALAGE).cashLibre?.composantes[4];
    expect(comptes?.reserves).toEqual({ cle: "admin.chiffres.reserves", params: { reserves: "REJ-AP-UNITE-PRIX-NON-CONFIRMEE" } });
  });

  test("LE PIÈGE DU « 0 » : un registre vide rend solde « 0 » ; l'app dit « non calculable » avec ce qui manque, jamais 0", () => {
    const vue = presenterTresorerie(tresorerieDe("tresorerie_sans_solde"), "fr-CA", DECALAGE);
    expect(vue.solde.genre).toBe("inconnu");
    expect(vue.solde.texte).toEqual({ cle: "admin.chiffres.tresorerie.soldeInconnu" });
    expect(vue.solde.manque).toEqual([
      {
        cle: "admin.commun.manqueLigne",
        params: {
          code: "REJ-CASH-SOLDE-ABSENT",
          detail: "aucun mouvement au registre : le solde d'ouverture n'a pas été enregistré, le solde n'est pas connu",
        },
      },
    ]);
    // L'argent disponible gelé (« 0 ») n'est pas montré : il n'a de sens qu'avec un solde connu.
    expect(vue.argentDisponible).toBeNull();
    expect(vue.cashLibre?.calculable).toBe(false);
    expect(vue.cashLibre?.resume).toEqual({ cle: "admin.chiffres.cashLibre.nonCalculable" });
    expect(vue.cashLibre?.auPlus).toBeNull();
    expect(vue.cashLibre?.enDeficit).toBeNull();
  });

  test("chaque composante non calculable dit « non calculable » sans aucun montant, et ce que M5 dit qu'il faut déclarer", () => {
    const composantes = presenterTresorerie(tresorerieDe("tresorerie_sans_solde"), "fr-CA", DECALAGE).cashLibre?.composantes ?? [];
    const nonCalculees = composantes.filter((c) => !c.calculee);
    expect(nonCalculees.map((c) => c.id)).toEqual(["solde", "taxes_a_remettre", "paies", "das", "dettes", "reserves"]);
    for (const composante of nonCalculees) {
      expect(composante.valeur).toEqual({ cle: "admin.chiffres.composante.nonCalculable" });
      expect(composante.manque.length).toBeGreaterThan(0);
      expect(composante.manque[0].cle).toBe("admin.commun.manqueLigne");
    }
    const paies = composantes.find((c) => c.id === "paies");
    expect(paies?.manque[0].params?.code).toBe("REJ-CASH-PAIE-A-DECLARER");
    expect(paies?.manque[0].params?.detail).toContain("Déclarer configuration.obligations_declarees.paies");
    // Un zéro que le registre a écrit (comptes à payer : aucun) reste un zéro écrit : il n'est pas confondu avec l'absence.
    const comptes = composantes.find((c) => c.id === "comptes_a_payer");
    expect(comptes?.valeur).toEqual({ cle: "admin.chiffres.composante.montant", params: { montant: n("0,00 $") } });
  });

  test("les manques du cash libre sont dits ligne par ligne, tels que M5 les écrit", () => {
    const cash = presenterTresorerie(tresorerieDe("tresorerie_sans_solde"), "fr-CA", DECALAGE).cashLibre;
    expect(cash?.manque).toEqual([
      "solde : REJ-CASH-SOLDE-ABSENT",
      "taxes_a_remettre : REJ-FISCAL-FREQUENCE-A-DECLARER",
      "paies : REJ-CASH-PAIE-A-DECLARER",
      "das : REJ-CASH-DAS-A-DECLARER",
      "dettes : REJ-CASH-DETTES-A-DECLARER",
      "reserves : REJ-CASH-RESERVES-A-DECLARER",
    ]);
  });

  test("un cash libre non calculable donne un repère « au plus », qui n'est pas de l'argent disponible", () => {
    const vue = presenterTresorerie(tresorerieDe("tresorerie_sans_paies"), "fr-CA", DECALAGE);
    expect(vue.solde.genre).toBe("connu");
    expect(vue.cashLibre?.calculable).toBe(false);
    expect(vue.cashLibre?.resume).toEqual({ cle: "admin.chiffres.cashLibre.nonCalculable" });
    expect(vue.cashLibre?.auPlus).toEqual({ cle: "admin.chiffres.cashLibre.auPlus", params: { montant: n("17 106,32 $") } });
    const paies = vue.cashLibre?.composantes.find((c) => c.id === "paies");
    expect(paies?.calculee).toBe(false);
    expect(paies?.valeur).toEqual({ cle: "admin.chiffres.composante.nonCalculable" });
    expect(paies?.plancher).toBeNull();
  });

  test("le plancher d'une composante non calculable est dit « au moins », jamais comme son montant", () => {
    const brut = reponse("tresorerie_sans_paies");
    const paies = brut.resultat.cash_libre.composantes.find((c: { id: string }) => c.id === "paies");
    paies.plancher = "1000.00";
    const composante = presenterTresorerie(etatDeBrut(brut), "fr-CA", DECALAGE).cashLibre?.composantes.find((c) => c.id === "paies");
    expect(composante?.valeur).toEqual({ cle: "admin.chiffres.composante.nonCalculable" });
    expect(composante?.plancher).toEqual({ cle: "admin.chiffres.composante.plancher", params: { montant: n("1 000,00 $") } });
  });

  test("un déficit est un montant négatif, avec son signe, et dit en déficit", () => {
    const brut = reponse("tresorerie");
    brut.resultat.cash_libre.cash_libre = "-120.50";
    brut.resultat.cash_libre.en_deficit = true;
    const cash = presenterTresorerie(etatDeBrut(brut), "fr-CA", DECALAGE).cashLibre;
    expect(cash?.resume).toEqual({ cle: "admin.chiffres.cashLibre.calcule", params: { montant: n("-120,50 $") } });
    expect(cash?.enDeficit).toEqual({ cle: "admin.chiffres.cashLibre.enDeficit" });
  });

  test("les vues sans droit de voir les montants : « montants non affichés », ni solde ni cash libre", () => {
    const brut = reponse("tresorerie");
    brut.resultat.cash_libre = null;
    brut.resultat.solde = null;
    brut.resultat.argent_disponible = null;
    const vue = presenterTresorerie(etatDeBrut(brut), "fr-CA", DECALAGE);
    expect(vue.solde).toEqual({ genre: "masque", texte: { cle: "admin.chiffres.tresorerie.masque" }, manque: [] });
    expect(vue.argentDisponible).toBeNull();
    expect(vue.cashLibre).toBeNull();
    expect(vue.mention).toBe(MENTION);
  });

  test("un argent disponible SANS la note qui dit que ce n'est pas le cash libre n'est pas montré", () => {
    const brut = reponse("tresorerie");
    delete brut.resultat.argent_disponible_note;
    const vue = presenterTresorerie(etatDeBrut(brut), "fr-CA", DECALAGE);
    expect(vue.solde.genre).toBe("connu");
    expect(vue.argentDisponible).toBeNull();
  });

  test("les hypothèses et le détail que M5 a retirés de sa réponse sont dits", () => {
    const brut = reponse("tresorerie");
    brut.resultat.cash_libre.hypotheses_omises = 2;
    brut.resultat.cash_libre.detail_omis = true;
    const cash = presenterTresorerie(etatDeBrut(brut), "fr-CA", DECALAGE).cashLibre;
    expect(cash?.hypothesesOmises).toEqual({ cle: "admin.chiffres.cashLibre.hypothesesOmises", params: { nombre: 2 } });
    expect(cash?.detailOmis).toBe(true);
    const sans = presenterTresorerie(tresorerieDe("tresorerie"), "fr-CA", DECALAGE).cashLibre;
    expect(sans?.hypothesesOmises).toBeNull();
    expect(sans?.detailOmis).toBe(false);
  });

  test("LA MENTION « Analyse préparatoire IA » voyage avec la donnée, telle que M5 l'écrit", () => {
    for (const nom of ["tresorerie", "tresorerie_sans_solde", "tresorerie_sans_paies"]) {
      expect(presenterTresorerie(tresorerieDe(nom), "fr-CA", DECALAGE).mention).toBe(MENTION);
    }
  });

  test("en-CA : les montants suivent la langue, sans jamais devenir des nombres", () => {
    const vue = presenterTresorerie(tresorerieDe("tresorerie"), "en-CA", DECALAGE);
    expect(vue.solde.texte.params).toEqual({ montant: "$20,000.00" });
    expect(vue.cashLibre?.resume.params).toEqual({ montant: "$14,106.32" });
  });

  test("un code de réserve inconnu d'un catalogue n'a pas de catalogue : la composante inconnue est dite inconnue", () => {
    const brut = reponse("tresorerie");
    // Une composante de plus, ajoutée par une version plus récente du serveur : montrée telle quelle, jamais cachée.
    const copie = JSON.parse(JSON.stringify(brut.resultat.cash_libre.composantes[3]));
    copie.id = "assurances";
    brut.resultat.cash_libre.composantes.push(copie);
    const composantes = presenterTresorerie(etatDeBrut(brut), "fr-CA", DECALAGE).cashLibre?.composantes ?? [];
    expect(composantes[composantes.length - 1].libelle).toEqual({ cle: "admin.commun.inconnu", params: { valeur: "assurances" } });
  });

  test("ligneDeManque : le code et le détail de M5, tels quels", () => {
    expect(ligneDeManque({ code: "REJ-X", detail: "déclarer x" })).toEqual({
      cle: "admin.commun.manqueLigne",
      params: { code: "REJ-X", detail: "déclarer x" },
    });
  });
});

describe("la prévision de trésorerie", () => {
  test("une prévision calculable avec alerte : l'horizon, la lecture de M5, l'alerte et les semaines sous le seuil", () => {
    const vue = complete(previsionDe("prevision"));
    expect(vue.horizon).toEqual({ cle: "admin.chiffres.prevision.horizon", params: { semaines: 6, du: "2026-09-29", au: "2026-11-09" } });
    expect(vue.lecture).toContain("Solde prévu : 20000.00 $ aujourd'hui");
    expect(vue.calculable).toBe(true);
    expect(vue.nonCalculable).toBeNull();
    expect(vue.manque).toEqual([]);
    expect(vue.alerte.statut).toEqual({ cle: "admin.chiffres.alerte.statuts.ALERTE" });
    expect(vue.alerte.enAlerte).toBe(true);
    expect(vue.alerte.seuil).toEqual({ cle: "admin.chiffres.alerte.seuil", params: { montant: n("18 000,00 $") } });
    expect(vue.alerte.sourceDuSeuil).toEqual({
      cle: "admin.chiffres.alerte.sourceDuSeuil",
      params: { source: "décision de Nathan (fictive)", date: "2026-09-25" },
    });
    expect(vue.alerte.semaines).toEqual({ cle: "admin.chiffres.alerte.semaines", params: { semaines: "2" } });
    expect(vue.alerte.nonEvaluee).toBeNull();
    expect(vue.alerte.manque).toBeNull();
    expect(vue.plusBas).toEqual({ cle: "admin.chiffres.prevision.plusBas", params: { semaine: 2, montant: n("17 000,00 $") } });
    expect(vue.premiereSemaineEnDeficit).toBeNull();
    expect(vue.mention).toBe(MENTION);
  });

  test("le solde de départ, sa source datée (à l'heure de l'appareil) et le cash libre d'aujourd'hui", () => {
    const vue = complete(previsionDe("prevision"));
    expect(vue.soldeInitial).toEqual({ cle: "admin.chiffres.prevision.soldeInitial", params: { montant: n("20 000,00 $") } });
    expect(vue.soldeInitialSource).toEqual({
      cle: "admin.chiffres.prevision.soldeInitialSourceDatee",
      params: { source: "registre des mouvements de M5 (somme signée, hors réserves)", date: "2026-09-10 12:00" },
    });
    expect(vue.cashLibreAujourdhui).toEqual({
      cle: "admin.chiffres.prevision.cashLibreAujourdhui",
      params: { montant: n("14 106,32 $") },
    });
    expect(vue.cashLibreAujourdhuiManque).toEqual([]);
  });

  test("les semaines : les montants du serveur mis en forme, sous le seuil dit seulement pour celle qui l'est", () => {
    const vue = complete(previsionDe("prevision"));
    expect(vue.semaines).toHaveLength(6);
    const [premiere, deuxieme] = vue.semaines;
    expect(premiere).toEqual({
      calculee: true,
      semaine: 1,
      titre: { cle: "admin.chiffres.prevision.semaine", params: { semaine: 1, du: "2026-09-29" } },
      entrees: { cle: "admin.chiffres.prevision.entrees", params: { montant: n("0,00 $") } },
      sorties: { cle: "admin.chiffres.prevision.sorties", params: { montant: n("0,00 $") } },
      soldeFin: { cle: "admin.chiffres.prevision.soldeFin", params: { montant: n("20 000,00 $") } },
      cashLibrePrevu: { cle: "admin.chiffres.prevision.cashLibrePrevu", params: { montant: n("14 106,32 $") } },
      sousSeuil: null,
      enDeficit: null,
      lignes: { cle: "admin.chiffres.prevision.lignes", params: { nombre: 0 } },
    });
    expect(deuxieme).toMatchObject({
      semaine: 2,
      sorties: { params: { montant: n("3 000,00 $") } },
      soldeFin: { params: { montant: n("17 000,00 $") } },
      sousSeuil: { cle: "admin.chiffres.prevision.sousSeuil" },
      enDeficit: null,
    });
  });

  test("ce qui est au-delà de l'horizon et les limites de M5 sont dits, avec leurs zéros écrits par le serveur", () => {
    const vue = complete(previsionDe("prevision"));
    expect(vue.auDela).toEqual([
      { cle: "admin.chiffres.prevision.auDelaEntrees", params: { nombre: 0, montant: n("0,00 $"), nonChiffres: 0 } },
      { cle: "admin.chiffres.prevision.auDelaSorties", params: { nombre: 0, montant: n("0,00 $"), nonChiffres: 0 } },
    ]);
    expect(vue.limites).toHaveLength(7);
    expect(vue.limites[0]).toContain("seuls les flux connus et datés sont placés");
    expect(vue.limitesOmises).toBeNull();
    expect(vue.reserves).toEqual({ cle: "admin.chiffres.reserves", params: { reserves: "REJ-AP-UNITE-PRIX-NON-CONFIRMEE" } });
    expect(vue.encaissementsNonComptes).toEqual([]);
  });

  test("un seuil à configurer : dit avec ce qui manque, ce n'est ni une alerte ni « aucune alerte »", () => {
    const vue = complete(previsionDe("prevision_sans_seuil"));
    expect(vue.alerte.statut).toEqual({ cle: "admin.chiffres.alerte.statuts.SEUIL_A_CONFIGURER" });
    expect(vue.alerte.enAlerte).toBe(false);
    expect(vue.alerte.seuil).toBeNull();
    expect(vue.alerte.semaines).toBeNull();
    expect(vue.alerte.manque?.cle).toBe("admin.commun.manqueLigne");
    expect(vue.alerte.manque?.params?.code).toBe("REJ-PREVISION-SEUIL-A-CONFIGURER");
    expect(vue.alerte.manque?.params?.detail).toContain("configuration.prevision.seuil_alerte");
  });

  test("aucune alerte : le statut de M5, avec le seuil déclaré", () => {
    const vue = complete(previsionDe("prevision_sans_alerte"));
    expect(vue.alerte.statut).toEqual({ cle: "admin.chiffres.alerte.statuts.AUCUNE" });
    expect(vue.alerte.enAlerte).toBe(false);
    expect(vue.alerte.seuil?.params).toEqual({ montant: n("1 000,00 $") });
  });

  test("UNE PRÉVISION NON CALCULABLE dit à partir de quelle semaine et ce qui manque ; les semaines non calculables n'ont AUCUN chiffre", () => {
    const vue = complete(previsionDe("prevision_sans_paies"));
    expect(vue.calculable).toBe(false);
    expect(vue.nonCalculable).toEqual({ cle: "admin.chiffres.prevision.nonCalculable", params: { semaine: 2 } });
    expect(vue.manque).toEqual([
      {
        cle: "admin.chiffres.prevision.manque",
        params: {
          code: "REJ-CASH-PAIE-A-DECLARER",
          semaine: 2,
          nombre: 1,
          detail: expect.stringContaining("Déclarer configuration.obligations_declarees.paies"),
          exemples: "obligation:paies",
        },
      },
    ]);
    expect(vue.alerte.statut).toEqual({ cle: "admin.chiffres.alerte.statuts.NON_EVALUEE" });
    expect(vue.alerte.nonEvaluee).toEqual({ cle: "admin.chiffres.alerte.nonEvaluee", params: { semaine: 2 } });
    expect(vue.cashLibreAujourdhui).toEqual({ cle: "admin.chiffres.prevision.cashLibreAujourdhuiNonCalculable" });
    expect(vue.cashLibreAujourdhuiManque).toEqual(["paies : REJ-CASH-PAIE-A-DECLARER"]);
    // La semaine 1 est calculée, mais son cash libre prévu ne l'est pas (celui d'aujourd'hui ne l'est pas).
    expect(vue.semaines[0]).toMatchObject({ calculee: true, cashLibrePrevu: { cle: "admin.chiffres.prevision.cashLibrePrevuNonCalculable" } });
    for (const semaine of vue.semaines.slice(1)) {
      expect(semaine.calculee).toBe(false);
      expect(Object.keys(semaine).sort()).toEqual(["avis", "calculee", "semaine", "titre"]);
      expect(semaine).toMatchObject({ avis: { cle: "admin.chiffres.prevision.semaineNonCalculable" } });
    }
  });

  test("une prévision sans droit de voir les montants : l'horizon seulement", () => {
    const brut = { role: "employee", montants_masques: true, horizon_semaines: 6, mention: MENTION };
    const vue = presenterPrevision(previsionDeBrut({ ok: true, resultat: { accepte: true, resultat: brut } }), "fr-CA", DECALAGE);
    expect(vue).toEqual({
      genre: "masquee",
      horizon: { cle: "admin.chiffres.prevision.horizonMasque", params: { semaines: 6 } },
      mention: MENTION,
    });
  });

  test("la première page d'une longue prévision : les semaines lues sur le total, telles que M5 les compte, et la suite à lire", () => {
    const vue = complete(previsionDe("prevision_longue_page_1"));
    expect(vue.progression).toEqual({ cle: "admin.chiffres.prevision.progression", params: { affichees: 19, total: 26 } });
    expect(vue.prochainDepart).toBe(19);
    expect(vue.semaines).toHaveLength(19);
  });

  test("après « Voir plus », la prévision recollée compte toutes les semaines et n'a plus de suite", () => {
    const premiere = tresorerieEnPrevision("prevision_longue_page_1");
    const seconde = previsionDe("prevision_longue_page_2");
    const fusion = fusionnerPagePrevision(premiere, seconde);
    if (fusion.genre !== "fusionnee") {
      throw new Error("les deux pages devraient se recoller");
    }
    const vue = complete(fusion.prevision);
    expect(vue.progression).toEqual({ cle: "admin.chiffres.prevision.progression", params: { affichees: 26, total: 26 } });
    expect(vue.prochainDepart).toBeNull();
    expect(vue.semaines.map((s) => s.semaine)).toEqual(Array.from({ length: 26 }, (_, i) => i + 1));
  });

  test("des éléments que l'app n'a pas su lire, des limites et des encaissements non comptés sont dits", () => {
    const brut = reponse("prevision");
    const p = brut.resultat.resultat;
    p.limites_omises = 3;
    p.encaissements_non_comptes = [
      { code: "REJ-PREVISION-ENCAISSEMENT-ECHU", nombre: 2, montant_connu: "1200.00", exemples: ["fac-1", "fac-2"] },
    ];
    p.semaines[3] = { semaine: "quatre" };
    const vue = complete(previsionDeBrut(brut));
    expect(vue.limitesOmises).toEqual({ cle: "admin.chiffres.prevision.limitesOmises", params: { nombre: 3 } });
    expect(vue.semainesIllisibles).toEqual({ cle: "admin.chiffres.prevision.semainesIllisibles", params: { nombre: 1 } });
    expect(vue.encaissementsNonComptes).toEqual([
      {
        cle: "admin.chiffres.prevision.encaissementNonCompte",
        params: { code: "REJ-PREVISION-ENCAISSEMENT-ECHU", nombre: 2, montant: n("1 200,00 $"), exemples: "fac-1, fac-2" },
      },
    ]);
  });

  test("une prévision en déficit dit la première semaine en déficit, et la semaine en déficit", () => {
    const brut = reponse("prevision");
    const p = brut.resultat.resultat;
    p.premiere_semaine_en_deficit = 3;
    p.semaines[2].en_deficit = true;
    p.semaines[2].solde_fin = "-250.00";
    const vue = complete(previsionDeBrut(brut));
    expect(vue.premiereSemaineEnDeficit).toEqual({ cle: "admin.chiffres.prevision.premiereSemaineEnDeficit", params: { semaine: 3 } });
    expect(vue.semaines[2]).toMatchObject({ enDeficit: { cle: "admin.chiffres.prevision.enDeficit" }, soldeFin: { params: { montant: n("-250,00 $") } } });
  });

  test("chaque montant d'une semaine vient de SA clé : des entrées, des sorties, un solde et un cash libre tous différents", () => {
    const brut = reponse("prevision");
    Object.assign(brut.resultat.resultat.semaines[0], {
      entrees: "1200.00",
      sorties: "300.00",
      solde_fin: "20900.00",
      cash_libre_prevu: "15006.32",
      lignes: 4,
    });
    const [semaine] = complete(previsionDeBrut(brut)).semaines;
    expect(semaine).toMatchObject({
      entrees: { cle: "admin.chiffres.prevision.entrees", params: { montant: n("1 200,00 $") } },
      sorties: { cle: "admin.chiffres.prevision.sorties", params: { montant: n("300,00 $") } },
      soldeFin: { cle: "admin.chiffres.prevision.soldeFin", params: { montant: n("20 900,00 $") } },
      cashLibrePrevu: { cle: "admin.chiffres.prevision.cashLibrePrevu", params: { montant: n("15 006,32 $") } },
      lignes: { params: { nombre: 4 } },
    });
  });

  test("ce qui est au-delà de l'horizon : les entrées et les sorties chacune avec SON nombre, SON total et SES éléments non chiffrés", () => {
    const brut = reponse("prevision");
    brut.resultat.resultat.au_dela_de_l_horizon = {
      entrees: { nombre: 2, total: "1500.00", non_chiffres: 1 },
      sorties: { nombre: 3, total: "400.00", non_chiffres: 0 },
    };
    expect(complete(previsionDeBrut(brut)).auDela).toEqual([
      { cle: "admin.chiffres.prevision.auDelaEntrees", params: { nombre: 2, montant: n("1 500,00 $"), nonChiffres: 1 } },
      { cle: "admin.chiffres.prevision.auDelaSorties", params: { nombre: 3, montant: n("400,00 $"), nonChiffres: 0 } },
    ]);
  });

  test("un statut d'alerte inconnu est dit inconnu, jamais lu comme « aucune alerte »", () => {
    const brut = reponse("prevision_sans_alerte");
    brut.resultat.resultat.alerte.statut = "PRUDENCE";
    const vue = complete(previsionDeBrut(brut));
    expect(vue.alerte.statut).toEqual({ cle: "admin.commun.inconnu", params: { valeur: "PRUDENCE" } });
    expect(vue.alerte.enAlerte).toBe(false);
  });

  test("les sections : lue, copie marquée, refus de M5 (« à déclarer ») dit sans copie à sa place", () => {
    const prevision = previsionDe("prevision");
    expect(vuePrevision(duServeur(prevision), "fr-CA", DECALAGE)).toMatchObject({ genre: "contenu", horsLigne: null });
    expect(vuePrevision(duCache(prevision), "fr-CA", DECALAGE)).toMatchObject({
      genre: "contenu",
      horsLigne: { cle: "admin.commun.cache" },
    });
    const refus = vuePrevision(
      { source: "refus", verdict: { code: "REJ-PREVISION-HORIZON-A-CONFIGURER", detail: "l'horizon est une décision du propriétaire" } },
      "fr-CA",
      DECALAGE,
    );
    expect(refus).toMatchObject({
      genre: "refus",
      avis: { cle: "admin.commun.refus", params: { code: "REJ-PREVISION-HORIZON-A-CONFIGURER" } },
    });
    expect(vueTresorerie(duServeur(tresorerieDe("tresorerie")), "fr-CA", DECALAGE).genre).toBe("contenu");
    expect(vueEcheances(duCache(echeancesDe("echeances")), "fr-CA", DECALAGE)).toMatchObject({ horsLigne: { cle: "admin.commun.cache" } });
  });
});

describe("« Voir plus » : ce que l'écran fait de la suite", () => {
  test("seule une lecture faite au serveur à l'instant, avec des semaines à lire, se poursuit", () => {
    const page1 = tresorerieEnPrevision("prevision_longue_page_1");
    expect(previsionAPoursuivre(duServeur<PrevisionLue>(page1))).toBe(page1);
    // Une copie gardée ne se prolonge pas : hors ligne, la suite n'est pas inventée.
    expect(previsionAPoursuivre(duCache<PrevisionLue>(page1))).toBeNull();
    // Rien ne suit.
    expect(previsionAPoursuivre(duServeur<PrevisionLue>(tresorerieEnPrevision("prevision")))).toBeNull();
    // Refus, absence, vue masquée : aucune suite.
    expect(previsionAPoursuivre({ source: "refus", verdict: { code: "x", detail: "y" } })).toBeNull();
    expect(previsionAPoursuivre(null)).toBeNull();
    const masquee: PrevisionLue = { genre: "masquee", role: "employee", horizonSemaines: 6, mention: MENTION };
    expect(previsionAPoursuivre(duServeur(masquee))).toBeNull();
  });

  test("les semaines recollées remplacent la valeur d'une lecture faite au serveur ; une copie gardée n'est jamais touchée", () => {
    const page1 = tresorerieEnPrevision("prevision_longue_page_1");
    const autre = tresorerieEnPrevision("prevision");
    const lue = duServeur<PrevisionLue>(page1, "2026-09-29T18:03:22.000Z");
    expect(remplacerPrevision(lue, autre)).toEqual({ source: "serveur", valeur: autre, misAJourLe: "2026-09-29T18:03:22.000Z" });
    const copie = duCache<PrevisionLue>(page1);
    expect(remplacerPrevision(copie, autre)).toBe(copie);
  });

  test("chaque issue de la suite a sa décision", () => {
    const prevision = tresorerieEnPrevision("prevision");
    expect(decisionSuitePrevision({ genre: "fusionnee", prevision })).toEqual({ genre: "remplacer", prevision });
    expect(decisionSuitePrevision({ genre: "a_relire", raison: "prevision_changee" })).toEqual({
      genre: "relire",
      avis: { cle: "admin.chiffres.prevision.suite.prevision_changee" },
    });
    expect(decisionSuitePrevision({ genre: "a_relire", raison: "incoherente" })).toEqual({
      genre: "relire",
      avis: { cle: "admin.chiffres.prevision.suite.incoherente" },
    });
    expect(decisionSuitePrevision({ genre: "refus", verdict: { code: "tool_call_blocked", detail: "hors portée" } })).toEqual({
      genre: "avis",
      avis: { cle: "admin.chiffres.prevision.suite.refus", params: { code: "tool_call_blocked", detail: "hors portée" } },
    });
    expect(decisionSuitePrevision({ genre: "echec", verdict: { code: "erreur_reseau", detail: "Network request failed" } })).toEqual({
      genre: "avis",
      avis: { cle: "admin.chiffres.prevision.suite.echec", params: { code: "erreur_reseau", detail: "Network request failed" } },
    });
    expect(decisionSuitePrevision({ genre: "sans_suite" })).toEqual({ genre: "rien" });
  });
});

describe("les échéances fiscales", () => {
  test("la fréquence, la dernière remise de taxes et les échéances à venir, avec les jours comptés par M5", () => {
    const vue = presenterEcheances(echeancesDe("echeances"), "fr-CA");
    expect(vue.frequence).toEqual({ cle: "admin.chiffres.echeances.frequences.trimestrielle" });
    expect(vue.moisFinExercice).toEqual({ cle: "admin.chiffres.echeances.moisFinExercice", params: { mois: 12 } });
    expect(vue.particulierEnAffaires).toEqual({ cle: "admin.chiffres.echeances.particulierNonDeclare" });
    expect(vue.taxesRemises).toEqual({ cle: "admin.chiffres.echeances.taxesRemises", params: { date: "2026-06-30" } });
    expect(vue.echeances).toHaveLength(2);
    const [premiere] = vue.echeances;
    expect(premiere.cle).toBe("2026-07-01:2026-09-30");
    expect(premiere.periode).toEqual({ cle: "admin.chiffres.echeances.periode", params: { debut: "2026-07-01", fin: "2026-09-30" } });
    expect(premiere.statut).toEqual({ cle: "admin.chiffres.echeances.statuts.A_VENIR" });
    expect(premiere.enRetard).toBe(false);
    expect(premiere.limitePaiement).toEqual({ cle: "admin.chiffres.echeances.limitePaiement", params: { date: "2026-11-02", jours: 34 } });
    expect(premiere.limiteProduction).toEqual({ cle: "admin.chiffres.echeances.limiteProduction", params: { date: "2026-11-02", jours: 34 } });
    expect(vue.mention).toBe(MENTION);
  });

  test("les taxes nettes : TPS et TVQ séparées, chaque montant du serveur mis en forme", () => {
    const [premiere] = presenterEcheances(echeancesDe("echeances"), "fr-CA").echeances;
    expect(premiere.taxes).toEqual({
      aRemettre: { cle: "admin.chiffres.echeances.aRemettre", params: { montant: n("748,75 $") } },
      tps: {
        cle: "admin.chiffres.echeances.tps",
        params: { collectee: n("250,00 $"), credits: n("0,00 $"), nette: n("250,00 $"), aRemettre: n("250,00 $") },
      },
      tvq: {
        cle: "admin.chiffres.echeances.tvq",
        params: { collectee: n("498,75 $"), credits: n("0,00 $"), nette: n("498,75 $"), aRemettre: n("498,75 $") },
      },
      factures: { cle: "admin.chiffres.echeances.factures", params: { clients: 1, fournisseurs: 0 } },
    });
    expect(premiere.taxesNonChiffrees).toBeNull();
  });

  test("la limite de paiement et la limite de production sont chacune celle de M5, avec SES jours restants", () => {
    const brut = reponse("echeances");
    Object.assign(brut.resultat.resultat.echeances[0], {
      limite_paiement: "2026-11-02",
      limite_production: "2026-11-30",
      jours_avant_paiement: 34,
      jours_avant_production: 62,
    });
    const [premiere] = presenterEcheances(echeancesDeBrut(brut), "fr-CA").echeances;
    expect(premiere.limitePaiement).toEqual({
      cle: "admin.chiffres.echeances.limitePaiement",
      params: { date: "2026-11-02", jours: 34 },
    });
    expect(premiere.limiteProduction).toEqual({
      cle: "admin.chiffres.echeances.limiteProduction",
      params: { date: "2026-11-30", jours: 62 },
    });
  });

  test("chaque montant d'une taxe vient de SA clé : collectée, crédits d'intrants, nette et à remettre tous différents", () => {
    const brut = reponse("echeances");
    const taxes = brut.resultat.resultat.echeances[0].taxes_nettes;
    taxes.tps = { collectee: "250.00", credits_intrants: "40.00", nette: "210.00", a_remettre: "200.00" };
    taxes.tvq = { collectee: "498.75", credits_intrants: "80.00", nette: "418.75", a_remettre: "410.00" };
    taxes.factures_clients = 3;
    taxes.factures_fournisseurs = 5;
    const [premiere] = presenterEcheances(echeancesDeBrut(brut), "fr-CA").echeances;
    expect(premiere.taxes?.tps).toEqual({
      cle: "admin.chiffres.echeances.tps",
      params: { collectee: n("250,00 $"), credits: n("40,00 $"), nette: n("210,00 $"), aRemettre: n("200,00 $") },
    });
    expect(premiere.taxes?.tvq.params).toEqual({
      collectee: n("498,75 $"),
      credits: n("80,00 $"),
      nette: n("418,75 $"),
      aRemettre: n("410,00 $"),
    });
    expect(premiere.taxes?.factures).toEqual({ cle: "admin.chiffres.echeances.factures", params: { clients: 3, fournisseurs: 5 } });
  });

  test("une échéance en retard : les jours négatifs de M5 sont montrés tels quels, sans que l'app les recompte", () => {
    const vue = presenterEcheances(echeancesDe("echeances_en_retard"), "fr-CA");
    const [enRetard, aVenir] = vue.echeances;
    expect(enRetard.enRetard).toBe(true);
    expect(enRetard.statut).toEqual({ cle: "admin.chiffres.echeances.statuts.EN_RETARD" });
    expect(enRetard.limitePaiement.params).toEqual({ date: "2026-07-31", jours: -60 });
    expect(aVenir.enRetard).toBe(false);
    expect(vue.taxesRemises.params).toEqual({ date: "2026-03-31" });
  });

  test("des taxes que M5 ne chiffre pas : dit non chiffré, avec ce qui manque, jamais « à remettre : 0 »", () => {
    const brut = reponse("echeances");
    const echeance = brut.resultat.resultat.echeances[0];
    echeance.taxes_nettes = null;
    echeance.manque = [{ code: "REJ-FISCAL-FACTURE-ILLISIBLE", detail: "une facture de la période est illisible" }];
    const [premiere] = presenterEcheances(echeancesDeBrut(brut), "fr-CA").echeances;
    expect(premiere.taxes).toBeNull();
    expect(premiere.taxesNonChiffrees).toEqual({ cle: "admin.chiffres.echeances.taxesNonChiffrees" });
    expect(premiere.manque).toEqual([
      { cle: "admin.commun.manqueLigne", params: { code: "REJ-FISCAL-FACTURE-ILLISIBLE", detail: "une facture de la période est illisible" } },
    ]);
  });

  test("la dernière remise non déclarée est dite : aucun retard n'est détectable", () => {
    const brut = reponse("echeances");
    brut.resultat.resultat.taxes_remises_jusqu_au = null;
    const vue = presenterEcheances(echeancesDeBrut(brut), "fr-CA");
    expect(vue.taxesRemises).toEqual({ cle: "admin.chiffres.echeances.taxesRemisesNonDeclarees" });
  });

  test("particulier en affaires : oui, non ou non déclaré", () => {
    const brut = reponse("echeances");
    brut.resultat.resultat.particulier_en_affaires = true;
    expect(presenterEcheances(echeancesDeBrut(brut), "fr-CA").particulierEnAffaires.cle).toBe("admin.chiffres.echeances.particulierOui");
    brut.resultat.resultat.particulier_en_affaires = false;
    expect(presenterEcheances(echeancesDeBrut(brut), "fr-CA").particulierEnAffaires.cle).toBe("admin.chiffres.echeances.particulierNon");
  });

  test("la validation du CPA de chaque année déclarée, avec la version du calendrier", () => {
    const vue = presenterEcheances(echeancesDe("echeances"), "fr-CA");
    expect(vue.validations).toEqual([
      { cle: "admin.chiffres.echeances.validations.A_VALIDER", params: { annee: "2025", version: "2025-v1" } },
      { cle: "admin.chiffres.echeances.validations.A_VALIDER", params: { annee: "2026", version: "2026-v1" } },
    ]);
    const brut = reponse("echeances");
    brut.resultat.resultat.validation_cpa["2026"] = "VALIDE_PAR_LE_CPA";
    brut.resultat.resultat.validation_cpa["2025"] = "VALIDE_PAR_NATHAN";
    const autre = presenterEcheances(echeancesDeBrut(brut), "fr-CA").validations;
    expect(autre[0]).toEqual({
      cle: "admin.chiffres.echeances.validationInconnue",
      params: { annee: "2025", version: "2025-v1", validation: "VALIDE_PAR_NATHAN" },
    });
    expect(autre[1].cle).toBe("admin.chiffres.echeances.validations.VALIDE_PAR_LE_CPA");
  });

  test("une fréquence que l'app ne connaît pas est dite inconnue, jamais lue comme une autre", () => {
    const brut = reponse("echeances");
    brut.resultat.resultat.frequence = "hebdomadaire";
    expect(presenterEcheances(echeancesDeBrut(brut), "fr-CA").frequence).toEqual({
      cle: "admin.commun.inconnu",
      params: { valeur: "hebdomadaire" },
    });
  });

  test("la couverture du calendrier, les sources et ce qui est hors calendrier sont ceux de M5, tels quels", () => {
    const vue = presenterEcheances(echeancesDe("echeances"), "fr-CA");
    expect(vue.couverture).toBe("aucune échéance n'est connue après le 2027-02-01 : l'année 2027 n'est pas déclarée dans le calendrier");
    expect(vue.connuJusquAu).toEqual({ cle: "admin.chiffres.echeances.connuJusquAu", params: { date: "2027-02-01" } });
    expect(vue.sources).toHaveLength(4);
    expect(vue.sources[0]).toEqual({
      reference: {
        cle: "admin.chiffres.echeances.source",
        params: {
          organisme: "Revenu Québec",
          titre: "Calendriers TVQ et TPS/TVH (dates limites de paiement, périodes mensuelles, trimestrielles et annuelles)",
          date: "2026-09-29",
        },
      },
      url: "https://www.revenuquebec.ca/fr/calendriers-tvq-et-tpstvh-taxe-sur-les-primes-dassurance-taxe-sur-les-boissons-alcooliques-et-pneus-neufs/",
    });
    expect(vue.horsPerimetre).toHaveLength(2);
    expect(vue.nonAffichees).toBeNull();
    expect(vue.echeancesIllisibles).toBeNull();
  });

  test("des échéances non affichées ou illisibles sont dites", () => {
    const brut = reponse("echeances");
    brut.resultat.resultat.non_affichees = 3;
    brut.resultat.resultat.echeances.push({ periode_debut: 12 });
    const vue = presenterEcheances(echeancesDeBrut(brut), "fr-CA");
    expect(vue.nonAffichees).toEqual({ cle: "admin.chiffres.echeances.nonAffichees", params: { nombre: 3 } });
    expect(vue.echeancesIllisibles).toEqual({ cle: "admin.chiffres.echeances.illisibles", params: { nombre: 1 } });
  });

  test("en-CA : les montants suivent la langue", () => {
    const [premiere] = presenterEcheances(echeancesDe("echeances"), "en-CA").echeances;
    expect(premiere.taxes?.aRemettre.params).toEqual({ montant: "$748.75" });
  });
});
