import { ouvrirEnveloppe } from "../admin/enveloppe";
import { estObjet } from "../admin/lecteurs";
import { horodatageM10Valide } from "../m10/contrat";
import type { Reponse } from "../m7/contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
export type { Reponse } from "../m7/contrat";

export const OUTIL_REAPPROVISIONNEMENT = "m6_lire_reapprovisionnement_appareil";
export type StatutReapprovisionnementM6 = "stock_bas" | "stock_suffisant" | "seuil_absent" | "configuration_invalide";
export type CodeConfigurationReapprovisionnementM6 =
  | "REJ-REAPPRO-CONFIGURATION-ILLISIBLE" | "REJ-REAPPRO-ARTICLE-INVALIDE"
  | "REJ-REAPPRO-SEUIL-INVALIDE" | "REJ-REAPPRO-CIBLE-INVALIDE";
export interface ArgumentsReapprovisionnementM6 { readonly decalage: number; readonly limite: number }
export interface ChiffresReapprovisionnementM6 {
  readonly stock_theorique: string; readonly hors_main: string; readonly en_main: string;
  readonly reserve: string; readonly disponible: string;
}
export interface DernierConstatReapprovisionnementM6 {
  readonly reference: { readonly registre: "besoins_commande"; readonly rang: number; readonly empreinte_snapshot: string };
  readonly type_entree: "besoin_commande" | "seuil_a_configurer";
  readonly evenement_declencheur: string; readonly horodatage: string; readonly chantier_id: string | null;
  readonly reference_bus: { readonly type: "m4.travaux_termines"; readonly evenement_id: string };
}
export interface ArticleReapprovisionnementM6 {
  readonly materiau_id: string; readonly statut: StatutReapprovisionnementM6;
  readonly chiffres: ChiffresReapprovisionnementM6;
  readonly seuil_reapprovisionnement: string | null; readonly quantite_cible: string | null;
  readonly quantite_a_commander: string | null; readonly stock_negatif: boolean;
  readonly code_configuration: CodeConfigurationReapprovisionnementM6 | null;
  readonly unite: null; readonly unite_dernier_constat: string | null;
  readonly dernier_constat: DernierConstatReapprovisionnementM6;
}
export interface PaginationReapprovisionnementM6 {
  readonly decalage: number; readonly limite: number; readonly affichees: number; readonly total: number;
  readonly suivant: number | null; readonly reste: number; readonly courante: true;
}
export interface SourceConfigurationReapprovisionnementM6 {
  readonly fichier: "departments/m06-material-control/department.yaml";
  readonly chemin: "configuration.reapprovisionnement.articles"; readonly sha256: string;
}
export interface SourceRegistreReapprovisionnementM6 {
  readonly registre: "besoins_commande" | "principal" | "reservations" | "emplacements";
  readonly lignes: number; readonly empreinte_snapshot: string;
}
export interface SourcePublicationsReapprovisionnementM6 {
  readonly evenements: { readonly type: "m4.travaux_termines"; readonly lignes: number; readonly empreinte_snapshot: string };
  readonly recus_m6: { readonly registre: "wct_recus"; readonly lignes: number; readonly empreinte_snapshot: string };
}
export interface ReapprovisionnementM6 {
  readonly articles: readonly ArticleReapprovisionnementM6[];
  readonly pagination: PaginationReapprovisionnementM6;
  readonly source_configuration: SourceConfigurationReapprovisionnementM6;
  readonly sources_registres: readonly SourceRegistreReapprovisionnementM6[];
  readonly source_publications: SourcePublicationsReapprovisionnementM6;
  readonly couverture: {
    readonly articles: "articles_deja_constates"; readonly stock: "theorique_disponible";
    readonly unites: "homogeneite_non_confirmee"; readonly horodatage: "dernier_constat_sans_date_calcul";
    readonly plafond_lignes: 10000;
  };
  readonly borne_caracteres: 5400; readonly taille_caracteres: number;
}
const REGISTRES = ["besoins_commande", "principal", "reservations", "emplacements"] as const;
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const sansControle = (v: string) => !/[\p{Cc}\p{Cs}]/u.test(v);
const id = (v: unknown): v is string => typeof v === "string" && v.length > 0 && !/^\p{White_Space}+$/u.test(v) && Array.from(v).length <= 256 && sansControle(v);
const hash = (v: unknown): v is string => typeof v === "string" && v.length === 64 && /^[0-9a-f]{64}$/.test(v);
const date = (v: unknown): v is string => typeof v === "string" && v.length <= 64 && sansControle(v) && horodatageM10Valide(v);
function ferme(v: unknown, cles: readonly string[]): v is Record<string, unknown> {
  return estObjet(v) && Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
}
function argsValides(v: unknown): v is ArgumentsReapprovisionnementM6 {
  return ferme(v, ["decalage", "limite"]) && entier(v.decalage) && v.decalage <= 10000 &&
    entier(v.limite) && v.limite >= 1 && v.limite <= 8;
}
export function construireArgumentsReapprovisionnement(decalage = 0, limite = 8): ArgumentsReapprovisionnementM6 {
  const args = { decalage, limite };
  if (!argsValides(args)) throw new Error("Arguments de réapprovisionnement M6 invalides.");
  return args;
}
/** Canonique source : zéro sans signe, ni exposant/plus/zeros initiaux/fractionnels finaux.
 * Une seule chaîne ne peut dépasser la borne de l'enveloppe ; pas de mesure JSON locale. */
function decimal(v: unknown): v is string {
  return typeof v === "string" && v.length <= 5400 && sansControle(v) &&
    /^-?(?:0|[1-9]\d*)(?:\.\d*[1-9])?$/.test(v) && v !== "-0";
}
/** Comparaison exacte uniquement : aucun stock, prix ou quantité n'est dérivé pour l'affichage. */
function comparer(a: string, b: string): number {
  if (a === b) return 0;
  const negatifA = a.startsWith("-"), negatifB = b.startsWith("-");
  if (negatifA !== negatifB) return negatifA ? -1 : 1;
  const [entierA, fractionA = ""] = (negatifA ? a.slice(1) : a).split(".");
  const [entierB, fractionB = ""] = (negatifB ? b.slice(1) : b).split(".");
  let ordre = entierA.length < entierB.length ? -1 : entierA.length > entierB.length ? 1 :
    entierA < entierB ? -1 : entierA > entierB ? 1 : 0;
  if (ordre === 0) {
    const longueur = Math.max(fractionA.length, fractionB.length);
    const gauche = fractionA.padEnd(longueur, "0"), droite = fractionB.padEnd(longueur, "0");
    ordre = gauche < droite ? -1 : gauche > droite ? 1 : 0;
  }
  return negatifA ? -ordre : ordre;
}
function lireChiffres(v: unknown): ChiffresReapprovisionnementM6 | null {
  if (!ferme(v, ["stock_theorique", "hors_main", "en_main", "reserve", "disponible"]) ||
    !decimal(v.stock_theorique) || !decimal(v.hors_main) || !decimal(v.en_main) || !decimal(v.reserve) || !decimal(v.disponible) ||
    comparer(v.hors_main, "0") < 0 || comparer(v.reserve, "0") < 0) return null;
  return { stock_theorique: v.stock_theorique, hors_main: v.hors_main, en_main: v.en_main, reserve: v.reserve, disponible: v.disponible };
}
function lireConstat(v: unknown, nConstats: number): DernierConstatReapprovisionnementM6 | null {
  if (!ferme(v, ["reference", "type_entree", "evenement_declencheur", "horodatage", "chantier_id", "reference_bus"]) ||
    !ferme(v.reference, ["registre", "rang", "empreinte_snapshot"]) || v.reference.registre !== "besoins_commande" ||
    !entier(v.reference.rang) || v.reference.rang >= nConstats || !hash(v.reference.empreinte_snapshot) ||
    (v.type_entree !== "besoin_commande" && v.type_entree !== "seuil_a_configurer") || !id(v.evenement_declencheur) ||
    !date(v.horodatage) || !(v.chantier_id === null || id(v.chantier_id)) ||
    !ferme(v.reference_bus, ["type", "evenement_id"]) || v.reference_bus.type !== "m4.travaux_termines" ||
    !id(v.reference_bus.evenement_id) || v.reference_bus.evenement_id !== v.evenement_declencheur) return null;
  return { reference: { registre: "besoins_commande", rang: v.reference.rang, empreinte_snapshot: v.reference.empreinte_snapshot },
    type_entree: v.type_entree, evenement_declencheur: v.evenement_declencheur, horodatage: v.horodatage,
    chantier_id: v.chantier_id, reference_bus: { type: "m4.travaux_termines", evenement_id: v.reference_bus.evenement_id } };
}
function codeConfiguration(v: unknown): v is CodeConfigurationReapprovisionnementM6 {
  return v === "REJ-REAPPRO-CONFIGURATION-ILLISIBLE" || v === "REJ-REAPPRO-ARTICLE-INVALIDE" ||
    v === "REJ-REAPPRO-SEUIL-INVALIDE" || v === "REJ-REAPPRO-CIBLE-INVALIDE";
}
function lireArticle(v: unknown, nConstats: number): ArticleReapprovisionnementM6 | null {
  if (!ferme(v, ["materiau_id", "statut", "chiffres", "seuil_reapprovisionnement", "quantite_cible", "quantite_a_commander", "stock_negatif", "code_configuration", "unite", "unite_dernier_constat", "dernier_constat"]) ||
    !id(v.materiau_id) || (v.statut !== "stock_bas" && v.statut !== "stock_suffisant" && v.statut !== "seuil_absent" && v.statut !== "configuration_invalide") ||
    typeof v.stock_negatif !== "boolean" || v.unite !== null || !(v.unite_dernier_constat === null || id(v.unite_dernier_constat))) return null;
  const chiffres = lireChiffres(v.chiffres), dernier_constat = lireConstat(v.dernier_constat, nConstats);
  if (!chiffres || !dernier_constat || v.stock_negatif !== (comparer(chiffres.en_main, "0") < 0)) return null;
  const seuil = v.seuil_reapprovisionnement, cible = v.quantite_cible, quantite = v.quantite_a_commander, code = v.code_configuration;
  if (v.statut === "stock_bas" || v.statut === "stock_suffisant") {
    if (!decimal(seuil) || !decimal(cible) || comparer(seuil, "0") <= 0 || comparer(cible, seuil) < 0 || code !== null ||
      (v.statut === "stock_bas") !== (comparer(chiffres.disponible, seuil) < 0)) return null;
    if (v.statut === "stock_bas" && !v.stock_negatif) {
      if (!decimal(quantite) || comparer(quantite, "0") <= 0) return null;
    } else if (quantite !== null) return null;
  } else {
    if (seuil !== null || cible !== null || quantite !== null ||
      (v.statut === "seuil_absent" ? code !== null : !codeConfiguration(code))) return null;
  }
  // Les branches précédentes ferment les valeurs ; ces gardes rendent leurs types explicites sans cast.
  if (!(seuil === null || typeof seuil === "string") || !(cible === null || typeof cible === "string") ||
    !(quantite === null || typeof quantite === "string") || !(code === null || codeConfiguration(code))) return null;
  return { materiau_id: v.materiau_id, statut: v.statut, chiffres, seuil_reapprovisionnement: seuil, quantite_cible: cible,
    quantite_a_commander: quantite, stock_negatif: v.stock_negatif, code_configuration: code, unite: null,
    unite_dernier_constat: v.unite_dernier_constat, dernier_constat };
}
function lirePage(v: unknown, args: ArgumentsReapprovisionnementM6, longueur: number, nConstats: number): PaginationReapprovisionnementM6 | null {
  if (!ferme(v, ["decalage", "limite", "affichees", "total", "suivant", "reste", "courante"]) ||
    v.decalage !== args.decalage || v.limite !== args.limite || v.courante !== true || !entier(v.affichees) ||
    v.affichees !== longueur || longueur > args.limite || !entier(v.total) || v.total > nConstats || !entier(v.reste) ||
    !(v.suivant === null || entier(v.suivant))) return null;
  const reste = Math.max(0, v.total - args.decalage - longueur);
  if (longueur > Math.max(0, v.total - args.decalage) || (args.decalage < v.total && longueur === 0) ||
    v.reste !== reste || v.suivant !== (reste ? args.decalage + longueur : null)) return null;
  return { decalage: v.decalage, limite: v.limite, affichees: v.affichees, total: v.total, suivant: v.suivant, reste: v.reste, courante: true };
}
function lireSource(v: unknown, registre: SourceRegistreReapprovisionnementM6["registre"]): SourceRegistreReapprovisionnementM6 | null {
  if (!ferme(v, ["registre", "lignes", "empreinte_snapshot"]) || v.registre !== registre || !entier(v.lignes) || v.lignes > 10000 || !hash(v.empreinte_snapshot)) return null;
  return { registre, lignes: v.lignes, empreinte_snapshot: v.empreinte_snapshot };
}
const illisible = (): Reponse<ReapprovisionnementM6> => ({ ok: false, code: "reponse_illisible", detail: "Réapprovisionnement illisible : aucun état partiel affiché." });
/** DIRECT entière. Aucun cache/outbox, calcul de stock ou date du calcul ajoutés. */
export function lireReapprovisionnement(brut: unknown, args: ArgumentsReapprovisionnementM6): Reponse<ReapprovisionnementM6> {
  const a = copierJsonLecture(args);
  if (a === JSON_LECTURE_INVALIDE || !argsValides(a)) return illisible();
  const copie = copierJsonLecture(brut);
  if (copie === JSON_LECTURE_INVALIDE || !estObjet(copie)) return illisible();
  const metier = estObjet(copie.resultat) ? copie.resultat : null;
  if (metier?.accepte === false) {
    if (!ferme(metier.verdict, ["code", "detail"]) || !id(metier.verdict.code) || typeof metier.verdict.detail !== "string") return illisible();
    return { ok: false, code: metier.verdict.code, detail: metier.verdict.detail };
  }
  if (copie.ok === false && (!id(copie.erreur) || !(typeof copie.details === "string" ||
    (Array.isArray(copie.details) && copie.details.every(v => typeof v === "string"))))) return illisible();
  const ouverte = ouvrirEnveloppe(copie, "directe");
  if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  if (!ferme(copie, ["ok", "resultat"])) return illisible();
  const v = ouverte.valeur;
  if (!ferme(v, ["articles", "pagination", "source_configuration", "sources_registres", "source_publications", "couverture", "borne_caracteres", "taille_caracteres"]) ||
    !Array.isArray(v.articles) || v.articles.length > a.limite || !Array.isArray(v.sources_registres) || v.sources_registres.length !== 4 ||
    v.borne_caracteres !== 5400 || !entier(v.taille_caracteres) || v.taille_caracteres < 1 || v.taille_caracteres > 5400 ||
    !ferme(v.source_configuration, ["fichier", "chemin", "sha256"]) || v.source_configuration.fichier !== "departments/m06-material-control/department.yaml" ||
    v.source_configuration.chemin !== "configuration.reapprovisionnement.articles" || !hash(v.source_configuration.sha256) ||
    !ferme(v.source_publications, ["evenements", "recus_m6"]) ||
    !ferme(v.source_publications.evenements, ["type", "lignes", "empreinte_snapshot"]) || v.source_publications.evenements.type !== "m4.travaux_termines" ||
    !entier(v.source_publications.evenements.lignes) || !hash(v.source_publications.evenements.empreinte_snapshot) ||
    !ferme(v.source_publications.recus_m6, ["registre", "lignes", "empreinte_snapshot"]) || v.source_publications.recus_m6.registre !== "wct_recus" ||
    !entier(v.source_publications.recus_m6.lignes) || !hash(v.source_publications.recus_m6.empreinte_snapshot) ||
    !ferme(v.couverture, ["articles", "stock", "unites", "horodatage", "plafond_lignes"]) ||
    v.couverture.articles !== "articles_deja_constates" || v.couverture.stock !== "theorique_disponible" ||
    v.couverture.unites !== "homogeneite_non_confirmee" || v.couverture.horodatage !== "dernier_constat_sans_date_calcul" || v.couverture.plafond_lignes !== 10000) return illisible();
  const sources_registres: SourceRegistreReapprovisionnementM6[] = [];
  for (let i = 0; i < 4; i++) {
    const s = lireSource(v.sources_registres[i], REGISTRES[i]);
    if (!s) return illisible(); sources_registres.push(s);
  }
  const evenements = v.source_publications.evenements, recus = v.source_publications.recus_m6;
  if (!entier(evenements.lignes) || !hash(evenements.empreinte_snapshot) || !entier(recus.lignes) || !hash(recus.empreinte_snapshot)) return illisible();
  const lignes = sources_registres.reduce((n, s) => n + s.lignes, 0) + evenements.lignes + recus.lignes;
  if (lignes > 10000) return illisible();
  const nConstats = sources_registres[0].lignes;
  const pagination = lirePage(v.pagination, a, v.articles.length, nConstats);
  if (!pagination) return illisible();
  const articles: ArticleReapprovisionnementM6[] = [], ids = new Set<string>();
  for (const raw of v.articles) {
    const article = lireArticle(raw, nConstats);
    if (!article || ids.has(article.materiau_id) || (articles.length > 0 && article.dernier_constat.reference.rang >= articles[articles.length - 1].dernier_constat.reference.rang)) return illisible();
    ids.add(article.materiau_id); articles.push(article);
  }
  return { ok: true, value: { articles, pagination,
    source_configuration: { fichier: "departments/m06-material-control/department.yaml", chemin: "configuration.reapprovisionnement.articles", sha256: v.source_configuration.sha256 },
    sources_registres, source_publications: {
      evenements: { type: "m4.travaux_termines", lignes: evenements.lignes, empreinte_snapshot: evenements.empreinte_snapshot },
      recus_m6: { registre: "wct_recus", lignes: recus.lignes, empreinte_snapshot: recus.empreinte_snapshot } },
    couverture: { articles: "articles_deja_constates", stock: "theorique_disponible", unites: "homogeneite_non_confirmee", horodatage: "dernier_constat_sans_date_calcul", plafond_lignes: 10000 },
    borne_caracteres: 5400, taille_caracteres: v.taille_caracteres } };
}
