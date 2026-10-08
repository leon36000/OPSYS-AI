import { ouvrirEnveloppe } from "../admin/enveloppe";
import { estDecimal, estObjet } from "../admin/lecteurs";
import { horodatageM10Valide } from "../m10/contrat";
import type { Reponse } from "../m7/contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
export type { Reponse } from "../m7/contrat";

export const OUTIL_LISTE_WCT_PERTES = "m6_lister_wct_pertes_appareil";
export const OUTIL_PERTES_ALERTES_WCT = "m6_lire_pertes_alertes_wct_appareil";
export const STATUTS_HISTORIQUE_VARIANCE_M6 = ["seuil_absent", "prevu_absent", "declaration_absente", "evaluee"] as const;
export type StatutHistoriqueVarianceM6 = (typeof STATUTS_HISTORIQUE_VARIANCE_M6)[number];
export interface ArgumentsListeWctM6 { readonly decalage: number; readonly limite: number }
export interface ArgumentsPertesWctM6 extends ArgumentsListeWctM6 { readonly wct_id: string }
export interface WctPertesM6 {
  readonly wct_id: string; readonly intervention_id: string; readonly devis_id: string | null;
  readonly horodatage_completion: string;
  readonly reference_recu: { readonly registre: "wct_recus"; readonly rang: number; readonly empreinte_contenu: string };
  readonly reference_bus: { readonly type: "m4.travaux_termines"; readonly evenement_id: string };
}
export interface PaginationPertesM6 {
  readonly decalage: number; readonly limite: number; readonly affichees: number; readonly total: number;
  readonly suivant: number | null; readonly reste: number; readonly courante: true;
}
export interface ListeWctPertesM6 {
  readonly wcts: readonly WctPertesM6[]; readonly pagination: PaginationPertesM6;
  readonly couverture: { readonly wcts: "recus_m6_rapproches_m4"; readonly plafond_lignes: 10000 };
  readonly borne_caracteres: 5400; readonly taille_caracteres: number;
}
export interface MouvementPerteBrisM6 {
  readonly type_mouvement: "PERTE" | "BRIS"; readonly chantier_id: string; readonly materiau_id: string;
  readonly quantite_signee: string; readonly unite: null; readonly horodatage: null;
  readonly reference: { readonly registre: "principal"; readonly index: number; readonly hash_maillon: string };
}
export interface PublicationVarianceM6 {
  readonly reference_bus: { readonly type: "m6.variance_chantier"; readonly evenement_id: string };
  readonly chantier_id: string | null; readonly signal_critique: boolean | null; readonly seuil_pourcentage: number | null;
  readonly horodatage_completion: string; readonly horodatage_publication: null;
}
export type SlotHistoriqueVarianceM6 =
  | { readonly statut: StatutHistoriqueVarianceM6; readonly presente: false; readonly publication: null }
  | { readonly statut: StatutHistoriqueVarianceM6; readonly presente: true; readonly publication: PublicationVarianceM6 };
const HORS_CORPUS = ["stock_courant", "reapprovisionnement", "couts", "responsables", "preuves_photos", "unites_reelles", "dates_perte_bris"] as const;
export interface PertesAlertesWctM6 {
  readonly wct: WctPertesM6; readonly chantier_id: string | null;
  /** Présence de mouvements liés ; ne prouve pas la réception d'un formulaire vide. */
  readonly declaration_presente: boolean;
  readonly pertes_bris: readonly MouvementPerteBrisM6[];
  readonly historique_variance: readonly SlotHistoriqueVarianceM6[];
  readonly evaluee_terminal: boolean; readonly pagination: PaginationPertesM6;
  readonly couverture: {
    readonly mouvements: "PERTE_BRIS_WCT_exact";
    readonly variances: "quatre_statuts_publies_ordre_fixe_sans_chronologie";
    readonly hors_corpus: typeof HORS_CORPUS; readonly plafond_lignes: 10000;
  };
  readonly borne_caracteres: 5400; readonly taille_caracteres: number;
}
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const sansControle = (v: string) => !/[\p{Cc}\p{Cs}]/u.test(v);
// Python strip et Unicode White_Space concordent après exclusion Cc/Cs. Aucun ID ne subit de trim.
const id = (v: unknown): v is string => typeof v === "string" && v.length > 0 && !/^\p{White_Space}+$/u.test(v) && Array.from(v).length <= 256 && sansControle(v);
// Le préfixe/statut canonique peut dépasser les 256 points de code du WCT métier.
const idVariance = (v: unknown): v is string => typeof v === "string" && Array.from(v).length <= 300 && sansControle(v);
const hash = (v: unknown): v is string => typeof v === "string" && v.length === 64 && /^[0-9a-f]{64}$/.test(v);
const date = (v: unknown): v is string => typeof v === "string" && sansControle(v) && horodatageM10Valide(v);
function ferme(v: unknown, cles: readonly string[]): v is Record<string, unknown> {
  return estObjet(v) && Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
}
function pageArguments(v: Record<string, unknown>): boolean {
  return entier(v.decalage) && v.decalage <= 10000 && entier(v.limite) && v.limite >= 1 && v.limite <= 8;
}
function argumentsListe(v: unknown): v is ArgumentsListeWctM6 {
  return ferme(v, ["decalage", "limite"]) && pageArguments(v);
}
function argumentsDetail(v: unknown): v is ArgumentsPertesWctM6 {
  return ferme(v, ["wct_id", "decalage", "limite"]) && id(v.wct_id) && pageArguments(v);
}
export function construireArgumentsListeWct(decalage = 0, limite = 8): ArgumentsListeWctM6 {
  const args = { decalage, limite };
  if (!argumentsListe(args)) throw new Error("Arguments de liste WCT M6 invalides.");
  return args;
}
export function construireArgumentsPertesWct(wctId: string, decalage = 0, limite = 8): ArgumentsPertesWctM6 {
  const args = { wct_id: wctId, decalage, limite };
  if (!argumentsDetail(args)) throw new Error("Arguments de pertes WCT M6 invalides.");
  return args;
}
const illisible = <T>(): Reponse<T> => ({ ok: false, code: "reponse_illisible", detail: "Lecture matériaux illisible : aucun constat partiel affiché." });
/** Le refus natif prime sur les flags ; tout le JSON a été copié sans accesseur auparavant. */
function lireDirect<T>(brut: unknown, parser: (v: unknown) => T | null): Reponse<T> {
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
  const valeur = parser(ouverte.valeur);
  return valeur === null ? illisible() : { ok: true, value: valeur };
}
function lireWct(v: unknown): WctPertesM6 | null {
  if (!ferme(v, ["wct_id", "intervention_id", "devis_id", "horodatage_completion", "reference_recu", "reference_bus"]) ||
    !id(v.wct_id) || !id(v.intervention_id) || !(v.devis_id === null || id(v.devis_id)) || !date(v.horodatage_completion) ||
    !ferme(v.reference_recu, ["registre", "rang", "empreinte_contenu"]) || v.reference_recu.registre !== "wct_recus" ||
    !entier(v.reference_recu.rang) || !hash(v.reference_recu.empreinte_contenu) ||
    !ferme(v.reference_bus, ["type", "evenement_id"]) || v.reference_bus.type !== "m4.travaux_termines" ||
    !id(v.reference_bus.evenement_id) || v.reference_bus.evenement_id !== v.wct_id) return null;
  return { wct_id: v.wct_id, intervention_id: v.intervention_id, devis_id: v.devis_id, horodatage_completion: v.horodatage_completion,
    reference_recu: { registre: "wct_recus", rang: v.reference_recu.rang, empreinte_contenu: v.reference_recu.empreinte_contenu },
    reference_bus: { type: "m4.travaux_termines", evenement_id: v.reference_bus.evenement_id } };
}
function lirePage(v: unknown, args: ArgumentsListeWctM6, longueur: number): PaginationPertesM6 | null {
  if (!ferme(v, ["decalage", "limite", "affichees", "total", "suivant", "reste", "courante"]) ||
    v.decalage !== args.decalage || v.limite !== args.limite || v.courante !== true || !entier(v.affichees) ||
    v.affichees !== longueur || longueur > args.limite || !entier(v.total) || v.total > 10000 || !entier(v.reste) ||
    !(v.suivant === null || entier(v.suivant))) return null;
  const reste = Math.max(0, v.total - args.decalage - longueur);
  if (longueur > Math.max(0, v.total - args.decalage) || (args.decalage < v.total && longueur === 0) ||
    v.reste !== reste || v.suivant !== (reste ? args.decalage + longueur : null)) return null;
  return { decalage: v.decalage, limite: v.limite, affichees: v.affichees, total: v.total,
    suivant: v.suivant, reste: v.reste, courante: true };
}
function borne(v: Record<string, unknown>): v is Record<string, unknown> & { borne_caracteres: 5400; taille_caracteres: number } {
  return v.borne_caracteres === 5400 && entier(v.taille_caracteres) && v.taille_caracteres > 0 && v.taille_caracteres <= 5400;
}
export function lireListeWctPertes(brut: unknown, args: ArgumentsListeWctM6): Reponse<ListeWctPertesM6> {
  const a = copierJsonLecture(args);
  if (a === JSON_LECTURE_INVALIDE || !argumentsListe(a)) return illisible();
  return lireDirect(brut, v => {
    if (!ferme(v, ["wcts", "pagination", "couverture", "borne_caracteres", "taille_caracteres"]) || !borne(v) ||
      !Array.isArray(v.wcts) || !ferme(v.couverture, ["wcts", "plafond_lignes"]) ||
      v.couverture.wcts !== "recus_m6_rapproches_m4" || v.couverture.plafond_lignes !== 10000) return null;
    const pagination = lirePage(v.pagination, a, v.wcts.length);
    if (!pagination) return null;
    const wcts: WctPertesM6[] = [], ids = new Set<string>(), rangs = new Set<number>();
    for (const brutWct of v.wcts) {
      const wct = lireWct(brutWct);
      if (!wct || ids.has(wct.wct_id) || rangs.has(wct.reference_recu.rang) ||
        (wcts.length > 0 && wct.reference_recu.rang >= wcts[wcts.length - 1].reference_recu.rang)) return null;
      ids.add(wct.wct_id); rangs.add(wct.reference_recu.rang); wcts.push(wct);
    }
    return { wcts, pagination, couverture: { wcts: "recus_m6_rapproches_m4", plafond_lignes: 10000 },
      borne_caracteres: 5400, taille_caracteres: v.taille_caracteres };
  });
}
function quantiteNegative(v: unknown): v is string {
  return estDecimal(v) && sansControle(v) && /^-(?:0|[1-9]\d*)(?:\.\d*[1-9])?$/.test(v) && v !== "-0";
}
function lireMouvement(v: unknown, chantierId: string | null): MouvementPerteBrisM6 | null {
  if (!ferme(v, ["type_mouvement", "chantier_id", "materiau_id", "quantite_signee", "unite", "horodatage", "reference"]) ||
    (v.type_mouvement !== "PERTE" && v.type_mouvement !== "BRIS") || !id(v.chantier_id) || v.chantier_id !== chantierId ||
    !id(v.materiau_id) || !quantiteNegative(v.quantite_signee) || v.unite !== null || v.horodatage !== null ||
    !ferme(v.reference, ["registre", "index", "hash_maillon"]) || v.reference.registre !== "principal" ||
    !entier(v.reference.index) || !hash(v.reference.hash_maillon)) return null;
  return { type_mouvement: v.type_mouvement, chantier_id: v.chantier_id, materiau_id: v.materiau_id,
    quantite_signee: v.quantite_signee, unite: null, horodatage: null,
    reference: { registre: "principal", index: v.reference.index, hash_maillon: v.reference.hash_maillon } };
}
function lireSlot(v: unknown, statut: StatutHistoriqueVarianceM6, wct: WctPertesM6, chantierId: string | null): SlotHistoriqueVarianceM6 | null {
  if (!ferme(v, ["statut", "presente", "publication"]) || v.statut !== statut || typeof v.presente !== "boolean") return null;
  if (!v.presente) return v.publication === null ? { statut, presente: false, publication: null } : null;
  const p = v.publication;
  if (!ferme(p, ["reference_bus", "chantier_id", "signal_critique", "seuil_pourcentage", "horodatage_completion", "horodatage_publication"]) ||
    !(p.chantier_id === null || id(p.chantier_id)) || (p.chantier_id !== null && p.chantier_id !== chantierId) ||
    p.horodatage_completion !== wct.horodatage_completion || p.horodatage_publication !== null ||
    !ferme(p.reference_bus, ["type", "evenement_id"]) || p.reference_bus.type !== "m6.variance_chantier" ||
    !idVariance(p.reference_bus.evenement_id) || p.reference_bus.evenement_id !== `m6-variance-${wct.wct_id}-${statut}`) return null;
  let signal: boolean | null = null, seuil: number | null = null;
  if (statut === "evaluee") { if (typeof p.signal_critique !== "boolean") return null; signal = p.signal_critique; }
  else if (p.signal_critique !== null) return null;
  if (statut === "seuil_absent") { if (p.seuil_pourcentage !== null) return null; }
  else {
    if (typeof p.seuil_pourcentage !== "number" || !Number.isFinite(p.seuil_pourcentage) || p.seuil_pourcentage <= 0) return null;
    seuil = p.seuil_pourcentage;
  }
  return { statut, presente: true, publication: {
    reference_bus: { type: "m6.variance_chantier", evenement_id: p.reference_bus.evenement_id },
    chantier_id: p.chantier_id, signal_critique: signal, seuil_pourcentage: seuil,
    horodatage_completion: p.horodatage_completion, horodatage_publication: null } };
}
export function lirePertesAlertesWct(brut: unknown, args: ArgumentsPertesWctM6): Reponse<PertesAlertesWctM6> {
  const a = copierJsonLecture(args);
  if (a === JSON_LECTURE_INVALIDE || !argumentsDetail(a)) return illisible();
  return lireDirect(brut, v => {
    if (!ferme(v, ["wct", "chantier_id", "declaration_presente", "pertes_bris", "historique_variance", "evaluee_terminal", "pagination", "couverture", "borne_caracteres", "taille_caracteres"]) ||
      !borne(v) || !(v.chantier_id === null || id(v.chantier_id)) || typeof v.declaration_presente !== "boolean" ||
      !Array.isArray(v.pertes_bris) || !Array.isArray(v.historique_variance) || v.historique_variance.length !== 4 ||
      typeof v.evaluee_terminal !== "boolean" || !ferme(v.couverture, ["mouvements", "variances", "hors_corpus", "plafond_lignes"]) ||
      v.couverture.mouvements !== "PERTE_BRIS_WCT_exact" || v.couverture.variances !== "quatre_statuts_publies_ordre_fixe_sans_chronologie" ||
      v.couverture.plafond_lignes !== 10000 || !Array.isArray(v.couverture.hors_corpus) ||
      v.couverture.hors_corpus.length !== HORS_CORPUS.length || v.couverture.hors_corpus.some((c, i) => c !== HORS_CORPUS[i])) return null;
    const wct = lireWct(v.wct), pagination = lirePage(v.pagination, a, v.pertes_bris.length);
    if (!wct || wct.wct_id !== a.wct_id || !pagination || (!v.declaration_presente && pagination.total !== 0) ||
      (v.declaration_presente && v.chantier_id === null) || (v.evaluee_terminal && !v.declaration_presente)) return null;
    const chantierId = v.chantier_id;
    const pertes_bris: MouvementPerteBrisM6[] = [], indices = new Set<number>(), hashes = new Set<string>();
    for (const brutMouvement of v.pertes_bris) {
      const m = lireMouvement(brutMouvement, chantierId);
      if (!m || indices.has(m.reference.index) || hashes.has(m.reference.hash_maillon) ||
        (pertes_bris.length > 0 && m.reference.index <= pertes_bris[pertes_bris.length - 1].reference.index)) return null;
      indices.add(m.reference.index); hashes.add(m.reference.hash_maillon); pertes_bris.push(m);
    }
    const historique_variance: SlotHistoriqueVarianceM6[] = [];
    for (let i = 0; i < 4; i++) {
      const slot = lireSlot(v.historique_variance[i], STATUTS_HISTORIQUE_VARIANCE_M6[i], wct, chantierId);
      if (!slot) return null;
      historique_variance.push(slot);
    }
    if (v.evaluee_terminal !== historique_variance[3].presente) return null;
    return { wct, chantier_id: chantierId, declaration_presente: v.declaration_presente, pertes_bris, historique_variance,
      evaluee_terminal: v.evaluee_terminal, pagination,
      couverture: { mouvements: "PERTE_BRIS_WCT_exact", variances: "quatre_statuts_publies_ordre_fixe_sans_chronologie", hors_corpus: HORS_CORPUS, plafond_lignes: 10000 },
      borne_caracteres: 5400, taille_caracteres: v.taille_caracteres };
  });
}
