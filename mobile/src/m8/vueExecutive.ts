import {
  decimalNullable,
  entierPositifOuNull,
  estObjet,
  listeDeTextes,
  lireListe,
  texteNullable,
  texteOuNull,
} from "../admin/lecteurs";
import type { ListeLue } from "../admin/lecteurs";
import { estJourCashLibre, lireCashLibreDeM8 } from "./cashLibre";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import type { CashLibreDeM8 } from "./cashLibre";
export type { CashLibreDeM8, ConstatCashLibre, AgeConstatCashLibre } from "./cashLibre";

/**
 * Contrat mobile de `m8_lire_vue_executive` (§9.5 M8 « tableau de bord exécutif », PLAN T4.19 ; écran
 * `(admin)/chiffres.tsx`, PLAN T4.20). Lecture SEULE de
 * `departments/m08-analytics/src/m8_analytics/vue_executive.py` et de `outils.py` (`lire_vue_executive`) — jamais
 * exécuté ici (ADR-0008) ; la forme d'une VRAIE réponse du moteur est celle de `src/admin/fixtures/reponses-moteur.json`
 * (`tests/e2e/test_admin_appareil.py`).
 *
 * Forme directe : `{ok: true, resultat: V}` où `V` est la vue elle-même (`vue: "executive"`) ; un refus est une
 * enveloppe `ok: false` (`refus_metier`, personne désactivée ou rôle retiré).
 *
 * **M8 lit, il ne recalcule pas — l'app non plus.** Chaque chiffre est un texte que M8, M5 ou M6 a arrêté (valeur d'une
 * mesure, marge réelle de M5, ...) ; l'app ne le convertit en nombre, ne l'additionne ni ne l'arrondit jamais. Une
 * donnée absente est « non calculable » ET dit ce qui manque : ce que ce lecteur refuse de lire autrement.
 *  - une mesure « calculée » a une valeur, une mesure « non calculable » n'en a pas : une contradiction (une valeur sur
 *    une mesure non calculable, un statut inconnu) rend la mesure illisible, jamais un zéro montré à sa place ;
 *  - un zéro écrit par le serveur (« 0 » devis envoyés) est un zéro : il est lu comme tel ;
 *  - le cash libre reprend le constat publié par M5, ou son absence, sans calcul ; un statut
 *    que cette version ne connaît pas est dit inconnu, il ne casse pas la vue et n'est pas deviné.
 */

export const OUTIL_VUE_EXECUTIVE = "m8_lire_vue_executive";

/** Jour explicitement fourni, utilisé par M8 pour l'âge seulement ; absent conserve l'appel v1. */
export function construireArgumentsVueExecutive(aujourdHui?: string): { aujourd_hui?: string } {
  if (aujourdHui === undefined) return {};
  if (!estJourCashLibre(aujourdHui)) throw new Error("aujourd_hui doit être une date AAAA-MM-JJ valide");
  return { aujourd_hui: aujourdHui };
}

/** `mesures_chantier.py` (`STATUT_CALCULEE`, `STATUT_NON_CALCULABLE`). */
export const STATUT_MESURE_CALCULEE = "calculee";
export const STATUT_MESURE_NON_CALCULABLE = "non_calculable";
/** `mesures_chantier.py` (`SEUIL_FRANCHI`, `SEUIL_NON_FRANCHI`). */
export const STATUTS_SEUIL_EVALUE: readonly string[] = ["franchi", "non_franchi"];
/** `nombres.py` (`SENS_AU_DESSUS`, `SENS_AU_DESSOUS`) : de quel côté d'un seuil la mesure est en alerte. */
export const SENS_DE_SEUIL: readonly string[] = ["au_dessus", "au_dessous"];
/** `metrics/m8-entonnoir.v1.yaml` : les unités que l'app sait mettre en forme ; toute autre est montrée telle quelle. */
export const UNITES_CONNUES: readonly string[] = ["leads", "devis", "pourcentage", "jours", "CAD"];

export interface MesureEntonnoir {
  readonly metricId: string;
  readonly nom: string;
  /** `null` : non calculable. Un zéro écrit par le serveur est la chaîne « 0 », jamais `null`. */
  readonly valeur: string | null;
  readonly unite: string;
  readonly calculee: boolean;
  readonly proprietaire: string;
  /** Ce qui manque, dit par M8 (champs des faits attendus), pour une mesure non calculable. */
  readonly manque: readonly string[];
}

export interface SourceEntonnoir {
  readonly evenement: string;
  readonly n: number;
  /** `null` : rien reçu de cette source. */
  readonly dernierFaitLe: string | null;
}

export interface DevisEnAttente {
  readonly n: number;
  readonly devis: readonly string[];
  /** Devis en attente que le serveur n'a pas cités (borne de la réponse). */
  readonly reste: number;
}

export interface SeuilEvalue {
  readonly metricId: string;
  readonly statut: string;
  readonly valeur: string | null;
  readonly unite: string;
  readonly sens: string | null;
  readonly seuil: string | null;
}

export interface SeuilsEntonnoir {
  /** Les métriques dont le seuil est « à configurer » (GATE NATHAN) : jamais une alerte, un manque nommé. */
  readonly aConfigurer: readonly string[];
  readonly invalides: readonly string[];
  readonly ignores: readonly string[];
  readonly evalues: readonly SeuilEvalue[];
  /** Où définir les seuils, quand il en manque. */
  readonly configuration: string | null;
  readonly illisibles: number;
}

export interface Entonnoir {
  readonly mesures: readonly MesureEntonnoir[];
  readonly mesuresIllisibles: number;
  readonly sources: readonly SourceEntonnoir[];
  readonly sourcesIllisibles: number;
  readonly sansReponse: DevisEnAttente;
  readonly brouillonsEnRetard: DevisEnAttente;
  readonly seuils: SeuilsEntonnoir;
}

export interface ChantierMarge {
  readonly wctId: string;
  readonly devisId: string | null;
  readonly horodatageCompletion: string | null;
  /** `null` : M5 ne l'a pas chiffrée ; `raison` dit pourquoi. */
  readonly margeReelleCad: string | null;
  readonly raison: string | null;
}

export interface MargeReelle {
  readonly source: string;
  readonly nChantiers: number;
  readonly nMargeConnue: number;
  readonly nNonCalculable: number;
  readonly chantiers: readonly ChantierMarge[];
  readonly illisibles: number;
  /** Chantiers que la réponse n'a pas montrés (borne). */
  readonly reste: number;
}

export interface ArticleACommander {
  readonly id: string;
  /** Le résumé de M6, tel quel : quantités et seuils viennent de M6. */
  readonly resume: string;
  readonly depuis: string | null;
  readonly actionProposee: string | null;
}

export type StockACommander =
  | {
      readonly genre: "lu";
      readonly source: string;
      readonly nArticles: number;
      readonly articles: readonly ArticleACommander[];
      readonly illisibles: number;
      readonly reste: number;
      readonly seuilsAConfigurer: boolean;
    }
  | { readonly genre: "manque"; readonly source: string; readonly manque: readonly string[] };

export interface ManqueDeLaVue {
  readonly champ: string;
  readonly source: string;
  readonly raison: string;
}

export interface VueExecutive {
  readonly portee: string;
  readonly entonnoir: Entonnoir;
  readonly margeReelle: MargeReelle;
  readonly stock: StockACommander;
  readonly cashLibre: CashLibreDeM8;
  readonly manques: readonly ManqueDeLaVue[];
  /** Éléments de la liste des manques que ce client n'a pas su lire. */
  readonly manquesIllisibles: number;
}

// -- l'entonnoir ------------------------------------------------------------------------------------------------------
function lireMesure(brut: unknown): MesureEntonnoir | null {
  if (!estObjet(brut)) {
    return null;
  }
  const metricId = texteOuNull(brut.metric_id);
  const nom = texteOuNull(brut.nom);
  const unite = texteOuNull(brut.unite);
  const proprietaire = texteOuNull(brut.proprietaire);
  const valeur = decimalNullable(brut.valeur);
  if (metricId === null || nom === null || unite === null || proprietaire === null || valeur === undefined) {
    return null;
  }
  // « calculée » = une valeur ; « non calculable » = aucune. Toute autre combinaison est une contradiction du serveur.
  if (brut.statut === STATUT_MESURE_CALCULEE && valeur !== null) {
    return { metricId, nom, valeur, unite, calculee: true, proprietaire, manque: [] };
  }
  if (brut.statut === STATUT_MESURE_NON_CALCULABLE && valeur === null) {
    const manque = brut.manque === undefined ? [] : listeDeTextes(brut.manque);
    return manque === null ? null : { metricId, nom, valeur: null, unite, calculee: false, proprietaire, manque };
  }
  return null;
}

function lireSource(brut: unknown): SourceEntonnoir | null {
  if (!estObjet(brut)) {
    return null;
  }
  const evenement = texteOuNull(brut.evenement);
  const n = entierPositifOuNull(brut.n);
  const dernierFaitLe = texteNullable(brut.dernier_fait_le);
  return evenement === null || n === null || dernierFaitLe === undefined ? null : { evenement, n, dernierFaitLe };
}

function lireDevisEnAttente(brut: unknown): DevisEnAttente | null {
  if (!estObjet(brut)) {
    return null;
  }
  const n = entierPositifOuNull(brut.n);
  const reste = entierPositifOuNull(brut.reste);
  const devis = listeDeTextes(brut.devis);
  return n === null || reste === null || devis === null ? null : { n, devis, reste };
}

function lireSeuilEvalue(brut: unknown): SeuilEvalue | null {
  if (!estObjet(brut)) {
    return null;
  }
  const metricId = texteOuNull(brut.metric_id);
  const statut = texteOuNull(brut.statut);
  const unite = texteOuNull(brut.unite);
  const valeur = decimalNullable(brut.valeur);
  const seuil = decimalNullable(brut.seuil);
  const sens = texteNullable(brut.sens);
  if (metricId === null || statut === null || unite === null || valeur === undefined || seuil === undefined || sens === undefined) {
    return null;
  }
  return { metricId, statut, valeur, unite, sens, seuil };
}

function lireSeuils(brut: unknown): SeuilsEntonnoir | null {
  if (!estObjet(brut)) {
    return null;
  }
  const aConfigurer = listeDeTextes(brut.a_configurer);
  const invalides = listeDeTextes(brut.invalides);
  const ignores = listeDeTextes(brut.ignores);
  const evalues = lireListe(brut.evalues, lireSeuilEvalue);
  const configuration = brut.configuration === undefined ? null : texteNullable(brut.configuration);
  if (aConfigurer === null || invalides === null || ignores === null || evalues === null || configuration === undefined) {
    return null;
  }
  return { aConfigurer, invalides, ignores, evalues: evalues.items, configuration, illisibles: evalues.illisibles };
}

function lireEntonnoir(brut: unknown): Entonnoir | null {
  if (!estObjet(brut) || !estObjet(brut.devis_en_attente)) {
    return null;
  }
  const mesures = lireListe(brut.mesures, lireMesure);
  const sources = lireListe(brut.sources, lireSource);
  const sansReponse = lireDevisEnAttente(brut.devis_en_attente.sans_reponse);
  const brouillons = lireDevisEnAttente(brut.devis_en_attente.brouillons_en_retard);
  const seuils = lireSeuils(brut.seuils);
  if (mesures === null || sources === null || sansReponse === null || brouillons === null || seuils === null) {
    return null;
  }
  return {
    mesures: mesures.items,
    mesuresIllisibles: mesures.illisibles,
    sources: sources.items,
    sourcesIllisibles: sources.illisibles,
    sansReponse,
    brouillonsEnRetard: brouillons,
    seuils,
  };
}

// -- la marge réelle, telle que M5 la publie ---------------------------------------------------------------------------
function lireChantierMarge(brut: unknown): ChantierMarge | null {
  if (!estObjet(brut)) {
    return null;
  }
  const wctId = texteOuNull(brut.wct_id);
  const devisId = texteNullable(brut.devis_id);
  const horodatageCompletion = texteNullable(brut.horodatage_completion);
  const marge = decimalNullable(brut.marge_reelle_cad);
  if (wctId === null || devisId === undefined || horodatageCompletion === undefined || marge === undefined) {
    return null;
  }
  const raison = brut.raison === undefined ? null : texteNullable(brut.raison);
  if (raison === undefined) {
    return null;
  }
  if (brut.statut === STATUT_MESURE_CALCULEE && marge !== null) {
    return { wctId, devisId, horodatageCompletion, margeReelleCad: marge, raison: null };
  }
  if (brut.statut === STATUT_MESURE_NON_CALCULABLE && marge === null) {
    return { wctId, devisId, horodatageCompletion, margeReelleCad: null, raison };
  }
  return null;
}

function lireMargeReelle(brut: unknown): MargeReelle | null {
  if (!estObjet(brut)) {
    return null;
  }
  const source = texteOuNull(brut.source);
  const nChantiers = entierPositifOuNull(brut.n_chantiers);
  const nMargeConnue = entierPositifOuNull(brut.n_marge_connue);
  const nNonCalculable = entierPositifOuNull(brut.n_non_calculable);
  const reste = entierPositifOuNull(brut.reste);
  const chantiers = lireListe(brut.chantiers, lireChantierMarge);
  if (source === null || nChantiers === null || nMargeConnue === null || nNonCalculable === null || reste === null || chantiers === null) {
    return null;
  }
  return { source, nChantiers, nMargeConnue, nNonCalculable, chantiers: chantiers.items, illisibles: chantiers.illisibles, reste };
}

// -- le stock à commander, tel que M6 le publie ------------------------------------------------------------------------
function lireArticle(brut: unknown): ArticleACommander | null {
  if (!estObjet(brut)) {
    return null;
  }
  const id = texteOuNull(brut.id);
  const resume = texteOuNull(brut.resume);
  const depuis = texteNullable(brut.depuis);
  const actionProposee = texteNullable(brut.action_proposee);
  return id === null || resume === null || depuis === undefined || actionProposee === undefined
    ? null
    : { id, resume, depuis, actionProposee };
}

function lireStock(brut: unknown): StockACommander | null {
  if (!estObjet(brut)) {
    return null;
  }
  const source = texteOuNull(brut.source);
  if (source === null) {
    return null;
  }
  if (brut.statut === "manque") {
    const manque = listeDeTextes(brut.manque);
    return manque === null ? null : { genre: "manque", source, manque };
  }
  if (brut.statut === "lu" && typeof brut.seuils_a_configurer === "boolean") {
    const nArticles = entierPositifOuNull(brut.n_articles);
    const reste = entierPositifOuNull(brut.reste);
    const articles = lireListe(brut.articles, lireArticle);
    if (nArticles === null || reste === null || articles === null) {
      return null;
    }
    return {
      genre: "lu",
      source,
      nArticles,
      articles: articles.items,
      illisibles: articles.illisibles,
      reste,
      seuilsAConfigurer: brut.seuils_a_configurer,
    };
  }
  return null;
}

function lireManque(brut: unknown): ManqueDeLaVue | null {
  if (!estObjet(brut)) {
    return null;
  }
  const champ = texteOuNull(brut.champ);
  const source = texteOuNull(brut.source);
  const raison = texteOuNull(brut.raison);
  return champ === null || source === null || raison === null ? null : { champ, source, raison };
}

/**
 * Lit la vue exécutive. `null` si ce n'est pas `vue: "executive"`, ou si une section n'a pas la forme attendue : la
 * réponse entière est alors illisible (un tableau de bord à moitié lu serait pire qu'aucun). Un ÉLÉMENT illisible d'une
 * liste (une mesure, un chantier, un article) est compté, jamais deviné.
 */
export function lireVueExecutive(brut: unknown): VueExecutive | null {
  brut = copierJsonLecture(brut);
  if (brut === JSON_LECTURE_INVALIDE) return null;
  if (!estObjet(brut) || brut.vue !== "executive") {
    return null;
  }
  const portee = texteOuNull(brut.portee);
  const entonnoir = lireEntonnoir(brut.entonnoir);
  const margeReelle = lireMargeReelle(brut.marge_reelle);
  const stock = lireStock(brut.stock_a_commander);
  const cashLibre = lireCashLibreDeM8(brut.cash_libre);
  const manques: ListeLue<ManqueDeLaVue> | null = lireListe(brut.manques, lireManque);
  if (portee === null || entonnoir === null || margeReelle === null || stock === null || cashLibre === null || manques === null) {
    return null;
  }
  return {
    portee,
    entonnoir,
    margeReelle,
    stock,
    cashLibre,
    manques: manques.items,
    manquesIllisibles: manques.illisibles,
  };
}
