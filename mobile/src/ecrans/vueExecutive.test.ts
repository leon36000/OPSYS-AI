import { reponse } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import { lireVueExecutive } from "../m8/vueExecutive";
import type { VueExecutive } from "../m8/vueExecutive";
import { duCache, duServeur, vueExecutiveDe } from "./donneesDeVue";
import { mesureFormatee, presenterVueExecutive, vueDEnsemble } from "./vueExecutive";

const NBSP = " ";
const n = (texte: string): string => texte.replace(/ /g, NBSP);
const DECALAGE = -240;

function vueDeBrut(brut: unknown): VueExecutive {
  const lu = interpreter(brut, "directe", lireVueExecutive);
  if (!lu.ok) {
    throw new Error(`vue illisible : ${lu.verdict.code}`);
  }
  return lu.valeur;
}

function vue(nom = "vue_executive", langue: "fr-CA" | "en-CA" = "fr-CA") {
  return presenterVueExecutive(vueExecutiveDe(nom), langue, DECALAGE);
}

describe("la mesure d'un entonnoir, avec son unité, sans jamais devenir un nombre", () => {
  test("chaque unité connue a son format ; le montant suit la langue", () => {
    expect(mesureFormatee("4", "leads", "fr-CA")).toEqual({ cle: "admin.unites.leads", params: { valeur: "4" } });
    expect(mesureFormatee("2", "devis", "fr-CA")).toEqual({ cle: "admin.unites.devis", params: { valeur: "2" } });
    expect(mesureFormatee("12.5", "pourcentage", "fr-CA")).toEqual({ cle: "admin.unites.pourcentage", params: { valeur: "12,5" } });
    expect(mesureFormatee("12.5", "pourcentage", "en-CA")).toEqual({ cle: "admin.unites.pourcentage", params: { valeur: "12.5" } });
    expect(mesureFormatee("0.00", "jours", "fr-CA")).toEqual({ cle: "admin.unites.jours", params: { valeur: "0,00" } });
    expect(mesureFormatee("1200.00", "CAD", "fr-CA")).toEqual({ cle: "admin.unites.CAD", params: { valeur: n("1 200,00 $") } });
    expect(mesureFormatee("1200.00", "CAD", "en-CA")).toEqual({ cle: "admin.unites.CAD", params: { valeur: "$1,200.00" } });
  });

  test("une unité que l'app ne connaît pas est montrée telle quelle, avec la valeur", () => {
    expect(mesureFormatee("7", "kg", "fr-CA")).toEqual({ cle: "admin.unites.autre", params: { valeur: "7", unite: "kg" } });
  });
});

describe("la vue d'ensemble : l'entonnoir", () => {
  test("une mesure calculée dit sa valeur ; un zéro écrit par le serveur est un zéro", () => {
    const { mesures } = vue().entonnoir;
    expect(mesures).toHaveLength(8);
    const parId = Object.fromEntries(mesures.map((m) => [m.metricId, m]));
    expect(parId.m8_leads_recus).toMatchObject({
      nom: "Leads reçus",
      calculee: true,
      valeur: { cle: "admin.unites.leads", params: { valeur: "4" } },
    });
    expect(parId.m8_devis_envoyes.valeur).toEqual({ cle: "admin.unites.devis", params: { valeur: "0" } });
    expect(parId.m8_delai_lead_acceptation_jours.valeur).toEqual({ cle: "admin.unites.jours", params: { valeur: "0,00" } });
    expect(parId.m8_carnet_signe_cad.valeur).toEqual({ cle: "admin.unites.CAD", params: { valeur: n("1 200,00 $") } });
  });

  test("UNE MESURE NON CALCULABLE dit ce qui lui manque, jamais « 0 » ni un tiret", () => {
    const taux = vue().entonnoir.mesures.find((m) => m.metricId === "m8_taux_acceptation_pct");
    expect(taux).toEqual({
      metricId: "m8_taux_acceptation_pct",
      nom: "Taux d'acceptation des devis",
      calculee: false,
      valeur: { cle: "admin.chiffres.vue.mesureNonCalculable", params: { manque: "m3.devis_envoye" } },
    });
  });

  test("une mesure non calculable sans précision le dit aussi", () => {
    const brut = reponse("vue_executive");
    brut.resultat.entonnoir.mesures[5].manque = [];
    const taux = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).entonnoir.mesures[5];
    expect(taux.valeur).toEqual({ cle: "admin.chiffres.vue.mesureNonCalculableSansPrecision" });
  });

  test("les sources : le nombre de faits et le dernier, à l'heure de l'appareil ; une source muette dit qu'elle n'a rien reçu", () => {
    const { sources } = vue().entonnoir;
    expect(sources).toHaveLength(5);
    expect(sources[0]).toEqual({
      cle: "admin.chiffres.vue.sourceDatee",
      params: { evenement: "m2.client_associe", n: 4, date: "2026-09-23 07:00" },
    });
    expect(sources[2]).toEqual({ cle: "admin.chiffres.vue.sourceSansDate", params: { evenement: "m3.devis_envoye", n: 0 } });
  });

  test("les devis en attente : le compte et les numéros que le serveur cite, « — » quand il n'en cite aucun", () => {
    const { sansReponse, brouillonsEnRetard } = vue().entonnoir;
    expect(sansReponse).toEqual({ resume: { cle: "admin.chiffres.vue.sansReponse", params: { n: 0, devis: "—" } }, reste: null });
    expect(brouillonsEnRetard.resume.cle).toBe("admin.chiffres.vue.brouillonsEnRetard");
    const brut = reponse("vue_executive");
    brut.resultat.entonnoir.devis_en_attente.sans_reponse = { n: 5, devis: ["DEVIS-1", "DEVIS-2"], reste: 3 };
    const autre = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).entonnoir.sansReponse;
    expect(autre.resume.params).toEqual({ n: 5, devis: "DEVIS-1, DEVIS-2" });
    expect(autre.reste).toEqual({ cle: "admin.chiffres.vue.devisReste", params: { reste: 3 } });
  });

  test("DES SEUILS À CONFIGURER ne sont pas une alerte : les mesures par leur nom, et où les déclarer", () => {
    const { seuils } = vue().entonnoir;
    expect(seuils.aConfigurer).toEqual({
      cle: "admin.chiffres.vue.seuilsAConfigurer",
      params: {
        mesures: "Devis sans réponse, Délai du lead à l'acceptation, Carnet signé",
        configuration: "department.yaml de m08-analytics, configuration.seuils_entonnoir",
      },
    });
    expect(seuils.invalides).toBeNull();
    expect(seuils.ignores).toBeNull();
    expect(seuils.evalues).toEqual([]);
    expect(seuils.illisibles).toBeNull();
  });

  test("sans endroit où déclarer les seuils, le manque est dit sans l'inventer", () => {
    const brut = reponse("vue_executive");
    brut.resultat.entonnoir.seuils.configuration = null;
    const { seuils } = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).entonnoir;
    expect(seuils.aConfigurer?.cle).toBe("admin.chiffres.vue.seuilsAConfigurerSansEndroit");
    expect(seuils.aConfigurer?.params).toEqual({ mesures: "Devis sans réponse, Délai du lead à l'acceptation, Carnet signé" });
  });

  test("des seuils évalués : franchi ou non, avec la valeur, le seuil et de quel côté l'alerte se lève", () => {
    const brut = reponse("vue_executive");
    const seuils = brut.resultat.entonnoir.seuils;
    seuils.a_configurer = ["m8_devis_sans_reponse"];
    seuils.invalides = ["m8_leads_recus"];
    seuils.ignores = ["m8_mesure_inconnue"];
    seuils.evalues = [
      { metric_id: "m8_taux_acceptation_pct", statut: "franchi", valeur: "12.5", unite: "pourcentage", sens: "au_dessous", seuil: "20.0" },
      { metric_id: "m8_carnet_signe_cad", statut: "non_franchi", valeur: "1200.00", unite: "CAD", sens: "au_dessous", seuil: "1000.00" },
    ];
    const { seuils: vueSeuils } = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).entonnoir;
    expect(vueSeuils.evalues).toEqual([
      {
        nom: "Taux d'acceptation des devis",
        statut: { cle: "admin.chiffres.vue.seuilStatuts.franchi" },
        valeur: { cle: "admin.unites.pourcentage", params: { valeur: "12,5" } },
        seuil: { cle: "admin.unites.pourcentage", params: { valeur: "20,0" } },
        sens: { cle: "admin.chiffres.vue.sens.au_dessous" },
      },
      {
        nom: "Carnet signé",
        statut: { cle: "admin.chiffres.vue.seuilStatuts.non_franchi" },
        valeur: { cle: "admin.unites.CAD", params: { valeur: n("1 200,00 $") } },
        seuil: { cle: "admin.unites.CAD", params: { valeur: n("1 000,00 $") } },
        sens: { cle: "admin.chiffres.vue.sens.au_dessous" },
      },
    ]);
    expect(vueSeuils.aConfigurer?.params?.mesures).toBe("Devis sans réponse");
    expect(vueSeuils.invalides).toEqual({ cle: "admin.chiffres.vue.seuilsInvalides", params: { mesures: "Leads reçus" } });
    // Une mesure que la vue ne contient pas est nommée par son identifiant, jamais cachée.
    expect(vueSeuils.ignores).toEqual({ cle: "admin.chiffres.vue.seuilsIgnores", params: { mesures: "m8_mesure_inconnue" } });
  });

  test("un statut ou un côté de seuil inconnus sont dits inconnus ; un côté absent reste absent", () => {
    const brut = reponse("vue_executive");
    brut.resultat.entonnoir.seuils.evalues = [
      { metric_id: "m8_carnet_signe_cad", statut: "prudence", valeur: null, unite: "CAD", sens: "en_diagonale", seuil: null },
      { metric_id: "m8_leads_recus", statut: "franchi", valeur: "4", unite: "leads", sens: null, seuil: "3" },
    ];
    const [premier, second] = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).entonnoir.seuils.evalues;
    expect(premier.statut).toEqual({ cle: "admin.commun.inconnu", params: { valeur: "prudence" } });
    expect(premier.sens).toEqual({ cle: "admin.commun.inconnu", params: { valeur: "en_diagonale" } });
    expect(premier.valeur).toBeNull();
    expect(premier.seuil).toBeNull();
    expect(second.sens).toBeNull();
  });
});

describe("la vue d'ensemble : la marge réelle des chantiers (M5), reprise sans calcul", () => {
  test("le résumé de M5 et chaque chantier : une marge chiffrée, ou « non calculable » avec la raison de M5", () => {
    const marge = vue().margeReelle;
    expect(marge.source).toBe("M5 (m5.rentabilite_chantier), reprise sans aucun calcul");
    expect(marge.resume).toEqual({ cle: "admin.chiffres.vue.margeResume", params: { n: 2, connue: 1, nonCalculable: 1 } });
    expect(marge.chantiers).toHaveLength(2);
    const [chiffre, nonChiffre] = marge.chantiers;
    expect(chiffre).toEqual({
      wctId: expect.stringMatching(/^[0-9a-f]{64}$/),
      titre: { cle: "admin.chiffres.vue.chantier", params: { chantier: expect.stringMatching(/^[0-9a-f]{8}…$/), devis: "DEVIS-ADM-E-fictif" } },
      termineLe: { cle: "admin.chiffres.vue.chantierTermine", params: { date: "2026-09-22 11:00" } },
      calculee: true,
      marge: { cle: "admin.chiffres.vue.margeCalculee", params: { montant: n("114,00 $") } },
    });
    // L'affichage abrège l'identifiant du chantier ; la vue garde l'identifiant entier.
    expect(chiffre.titre.params?.chantier).toBe(`${chiffre.wctId.slice(0, 8)}…`);
    expect(nonChiffre.calculee).toBe(false);
    expect(nonChiffre.marge).toEqual({
      cle: "admin.chiffres.vue.margeNonCalculable",
      params: {
        raison: "M5 n'a pas chiffré la marge réelle : REJ-COUT-PRIX-NON-DISPONIBLE, REJ-COUT-TAUX-HORAIRE-A-CONFIGURER",
      },
    });
  });

  test("les comptes de M5 sont dits chacun à sa place : chantiers terminés, marge connue, non calculable", () => {
    const brut = reponse("vue_executive");
    Object.assign(brut.resultat.marge_reelle, { n_chantiers: 5, n_marge_connue: 3, n_non_calculable: 2 });
    expect(presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).margeReelle.resume).toEqual({
      cle: "admin.chiffres.vue.margeResume",
      params: { n: 5, connue: 3, nonCalculable: 2 },
    });
  });

  test("un chantier sans devis relié, non daté et sans raison : dit tel quel, jamais une marge de 0", () => {
    const brut = reponse("vue_executive");
    brut.resultat.marge_reelle.chantiers[1] = {
      wct_id: "24be933c9957a809a00b0fec00ad64193ae1e629b89c42de8676a220962b8b5c",
      devis_id: null,
      horodatage_completion: null,
      statut: "non_calculable",
      marge_reelle_cad: null,
    };
    const chantier = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).margeReelle.chantiers[1];
    expect(chantier.titre).toEqual({ cle: "admin.chiffres.vue.chantierSansDevis", params: { chantier: "24be933c…" } });
    expect(chantier.termineLe).toBeNull();
    expect(chantier.marge).toEqual({ cle: "admin.chiffres.vue.margeNonCalculableSansRaison" });
  });

  test("des chantiers illisibles ou non montrés sont dits", () => {
    const brut = reponse("vue_executive");
    brut.resultat.marge_reelle.chantiers.push({ wct_id: 12 });
    brut.resultat.marge_reelle.reste = 4;
    const marge = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).margeReelle;
    expect(marge.illisibles).toEqual({ cle: "admin.chiffres.vue.chantiersIllisibles", params: { nombre: 1 } });
    expect(marge.reste).toEqual({ cle: "admin.chiffres.vue.chantiersReste", params: { nombre: 4 } });
  });
});

describe("la vue d'ensemble : le stock à commander (M6) et le cash libre", () => {
  test("le stock lu : le résumé de M6 tel quel, depuis quand, le geste proposé", () => {
    const { stock } = vue();
    if (stock.genre !== "lu") {
      throw new Error("le stock devrait être lu");
    }
    expect(stock.source).toBe("M6 (attentes du propriétaire, type besoin_commande)");
    expect(stock.resume).toEqual({ cle: "admin.chiffres.vue.stockResume", params: { n: 1 } });
    expect(stock.articles).toHaveLength(1);
    expect(stock.articles[0].id).toBe("besoin_commande:gouttiere-alu-5po-fictif");
    expect(stock.articles[0].resume).toContain("302.0 pi en main dont 120 pi réservé(s)");
    expect(stock.articles[0].depuis).toEqual({ cle: "admin.chiffres.vue.articleDepuis", params: { date: "2026-09-22 11:00" } });
    expect(stock.articles[0].geste?.params?.geste).toContain("un bon de commande se demande en brouillon");
    expect(stock.seuilsAConfigurer).toBeNull();
  });

  test("des seuils de stock à configurer : l'absence d'article ne dit pas que tout va bien", () => {
    const brut = reponse("vue_executive");
    brut.resultat.stock_a_commander.seuils_a_configurer = true;
    brut.resultat.stock_a_commander.articles = [];
    brut.resultat.stock_a_commander.n_articles = 0;
    const { stock } = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE);
    expect(stock).toMatchObject({ genre: "lu", seuilsAConfigurer: { cle: "admin.chiffres.vue.stockSeuilsAConfigurer" } });
  });

  test("un stock non lu dit ce qui manque, sans aucun article", () => {
    const brut = reponse("vue_executive");
    brut.resultat.stock_a_commander = { source: "M6 (attentes du propriétaire)", statut: "manque", manque: ["m6.attentes"] };
    const { stock } = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE);
    expect(stock).toEqual({
      genre: "manque",
      source: "M6 (attentes du propriétaire)",
      avis: { cle: "admin.chiffres.vue.stockManque", params: { manque: "m6.attentes" } },
    });
  });

  test("des articles illisibles ou non montrés sont dits", () => {
    const brut = reponse("vue_executive");
    brut.resultat.stock_a_commander.articles.push({ id: 3 });
    brut.resultat.stock_a_commander.reste = 2;
    const { stock } = presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE);
    expect(stock).toMatchObject({
      illisibles: { cle: "admin.chiffres.vue.articlesIllisibles", params: { nombre: 1 } },
      reste: { cle: "admin.chiffres.vue.articlesReste", params: { nombre: 2 } },
    });
  });

  test("LE CASH LIBRE n'est pas dans cette vue : elle renvoie à la trésorerie, sans chiffre", () => {
    expect(vue().cashLibre).toEqual({ cle: "admin.chiffres.vue.cashLibreAilleurs" });
  });

  test("un statut de cash libre que cette version ne connaît pas est dit tel quel, jamais lu comme un chiffre", () => {
    const brut = reponse("vue_executive");
    brut.resultat.cash_libre = { source: "M5", statut: "lu", montant: "14106.32" };
    expect(presenterVueExecutive(vueDeBrut(brut), "fr-CA", DECALAGE).cashLibre).toEqual({
      cle: "admin.chiffres.vue.cashLibreInconnu",
      params: { statut: "lu" },
    });
  });

  test("ce qui manque à la vue : le champ, sa source et la raison de M8, telle quelle", () => {
    const { manques } = vue();
    expect(manques).toHaveLength(2);
    expect(manques[0]).toEqual({
      cle: "admin.chiffres.vue.manque",
      params: {
        champ: "m3.devis_envoye",
        source: "M3 (m3.devis_envoye)",
        raison: "aucun devis envoyé reçu : le taux n'a pas de dénominateur",
      },
    });
    expect(manques[1].params?.champ).toBe("cash_libre");
  });

  test("la portée de la vue est celle que M8 écrit, telle quelle", () => {
    expect(vue().portee).toContain("Tous les faits reçus par M8, sans fenêtre de période.");
  });

  test("une vue vide (aucun fait reçu) ne montre aucun chiffre inventé : toute mesure calculée ou non l'est par le serveur", () => {
    const vueVide = vue("vue_executive_vide");
    for (const mesure of vueVide.entonnoir.mesures) {
      if (!mesure.calculee) {
        expect(mesure.valeur.cle).toMatch(/^admin\.chiffres\.vue\.mesureNonCalculable/);
        expect(mesure.valeur.params?.valeur).toBeUndefined();
      }
    }
    expect(vueVide.entonnoir.mesures.some((m) => !m.calculee)).toBe(true);
  });

  test("en-CA : les montants suivent la langue", () => {
    const carnet = vue("vue_executive", "en-CA").entonnoir.mesures.find((m) => m.metricId === "m8_carnet_signe_cad");
    expect(carnet?.valeur.params).toEqual({ valeur: "$1,200.00" });
  });
});

describe("la vue d'ensemble selon ce que le chargeur a pu lire", () => {
  test("lue, copie marquée, refusée, absente", () => {
    const lue = vueExecutiveDe("vue_executive");
    expect(vueDEnsemble(duServeur(lue), "fr-CA", DECALAGE)).toMatchObject({ genre: "contenu", horsLigne: null });
    expect(vueDEnsemble(duCache(lue, "http_503"), "fr-CA", DECALAGE)).toMatchObject({
      genre: "contenu",
      horsLigne: { cle: "admin.commun.cache", params: { code: "http_503" } },
    });
    expect(vueDEnsemble({ source: "refus", verdict: { code: "refus_metier", detail: "personne désactivée" } }, "fr-CA", DECALAGE).genre).toBe("refus");
    expect(vueDEnsemble({ source: "aucune", raison: { code: "erreur_reseau", detail: "x" } }, "fr-CA", DECALAGE).genre).toBe("aucune");
  });
});
