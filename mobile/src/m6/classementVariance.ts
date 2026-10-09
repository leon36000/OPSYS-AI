import { estDecimal } from "../admin/lecteurs";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { ouvrirEnveloppe } from "../admin/enveloppe";
import { horodatageM10Valide } from "../m10/contrat";
import type { Reponse } from "../m7/contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { InterpretationResultatMetier } from "../outbox/vidangeur";
import type { SessionEnvoi } from "../protocole/configuration";

export const OUTIL_LISTE_VARIANCES = "m6_lister_variances_classables_wct_appareil";
export const OUTIL_CLASSEMENT_VARIANCE = "m6_classer_cause_variance_appareil";
export const OUTIL_HISTORIQUE_CLASSEMENTS = "m6_lire_historique_classement_variance_appareil";
export const CAUSES_VARIANCE = ["estimation_error", "field_change", "waste", "breakage", "data_entry_error", "unexplained_usage"] as const;
export type CauseVariance = typeof CAUSES_VARIANCE[number];
export interface ReferenceVarianceM6 { readonly type: "m6.variance_chantier"; readonly evenement_id: string; readonly empreinte_charge: string }
export interface SelectionVarianceM6 {
  readonly wct_id: string; readonly reference_variance: ReferenceVarianceM6;
  readonly position_ligne: number; readonly materiau_id: string;
}
export interface ReferenceClassementM6 { readonly registre: "classements_variance"; readonly index: number; readonly hash_maillon: string }
export interface PieceClassementM6 {
  readonly reference_mouvement: { readonly registre: "principal"; readonly index: number; readonly hash_maillon: string };
  readonly reference_preuve: { readonly registre: "preuves_pertes_bris"; readonly index: number; readonly hash_maillon: string } | null;
  readonly positions_photos: readonly number[];
}
export interface IntentionClassementM6 {
  readonly appareil_id: string; readonly intention_uuid: string; readonly empreinte_arguments: string;
}
export interface ClassementVarianceM6V1 {
  readonly reference: ReferenceClassementM6; readonly selection: SelectionVarianceM6; readonly cause: CauseVariance;
  readonly motif: string; readonly reference_precedente: ReferenceClassementM6 | null;
  readonly auteur: { readonly personne: string; readonly role: "admin"; readonly source: "appareil" };
  readonly appareil_id: string; readonly classe_le: string; readonly horodatage_appareil_declare: string;
  readonly references_pieces: readonly PieceClassementM6[];
}
export interface ClassementVarianceM6V2 extends ClassementVarianceM6V1 {
  readonly version_schema: 2; readonly intention: IntentionClassementM6;
}
export type ClassementVarianceM6 = ClassementVarianceM6V1 | ClassementVarianceM6V2;
export interface LigneVarianceClassableM6 {
  readonly selection: SelectionVarianceM6;
  readonly source_ligne: { readonly materiau: string; readonly unite: string | null; readonly quantite_prevue: string;
    readonly quantite_reelle: string; readonly ecart_pourcentage: string | null; readonly critique: boolean };
  readonly pieces_disponibles_a_selectionner: readonly PieceClassementM6[];
  readonly classement_courant: ClassementVarianceM6 | null;
}
export interface PaginationClassementsM6 {
  readonly decalage: number; readonly limite: number; readonly total: number; readonly affichees: number;
  readonly reste: number; readonly decalage_suivant: number | null; readonly borne_atteinte: boolean;
}
const COUVERTURE = {
  eligibilite: "critique_publiee_ou_perte_bris_liee", autres_ecarts: "hors_perimetre",
  preuves: "association_sans_inference_de_cause_ni_authenticite_scene",
  dates: "reception_serveur_sans_date_du_dommage", plafond_sources: 10000,
} as const;
export interface SourceVarianceM6 extends ReferenceVarianceM6 { readonly statut_variance: "evaluee"; readonly horodatage_completion: string }
export interface PageVariancesM6 {
  readonly wct: { readonly wct_id: string; readonly intervention_id: string; readonly chantier_id: string };
  readonly source_variance: SourceVarianceM6; readonly lignes: readonly LigneVarianceClassableM6[];
  readonly pagination: PaginationClassementsM6; readonly couverture: typeof COUVERTURE;
}
export interface PageHistoriqueClassementsM6 {
  readonly selection: SelectionVarianceM6; readonly source_variance: SourceVarianceM6;
  readonly historique: readonly ClassementVarianceM6[]; readonly pagination: PaginationClassementsM6;
  readonly couverture: typeof COUVERTURE;
}
export interface ArgumentsListeVariancesM6 { readonly wct_id: string; readonly decalage: number; readonly limite: number }
export interface ArgumentsHistoriqueClassementsM6 { readonly selection: SelectionVarianceM6; readonly decalage: number; readonly limite: number }
export interface ArgumentsClassementVarianceM6 {
  readonly selection: SelectionVarianceM6; readonly cause: CauseVariance; readonly motif: string;
  readonly classement_attendu: ReferenceClassementM6 | null; readonly references_pieces: readonly PieceClassementM6[];
}
export type RecuClassementVarianceM6 = ClassementVarianceM6 & {
  readonly registre_confirmation: { readonly taille: number; readonly hash_tete: string };
};
export type InterpretationClassementVariance =
  | { readonly accepte: true; readonly resume: RecuClassementVarianceM6 }
  | { readonly accepte: false; readonly verdict: { readonly code: string; readonly detail: string } };
const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const ferme = (v: unknown, keys: readonly string[]): v is Record<string, unknown> => objet(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const entier = (v: unknown, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
const id = (v: unknown): v is string => typeof v === "string" && [...v].length <= 256 && /[^\p{White_Space}]/u.test(v) && !/[\p{Cc}\p{Cs}]/u.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const date = (v: unknown): v is string => typeof v === "string" && horodatageM10Valide(v);
export const motifClassementValide = (v: unknown): v is string => typeof v === "string" && [...v].length <= 500 && /[^\p{White_Space}]/u.test(v) && !/[^\P{Cc}\t\r\n]|\p{Cs}/u.test(v);
const cause = (v: unknown): v is CauseVariance => CAUSES_VARIANCE.some(c => c === v);
const egal = (a: unknown, b: unknown): boolean => {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => egal(v, b[i]));
  return objet(a) && objet(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && egal(a[k], b[k]));
};
function reference(v: unknown, registre: string): boolean {
  return ferme(v, ["registre", "index", "hash_maillon"]) && v.registre === registre && entier(v.index, 9999) && hash(v.hash_maillon);
}
function selection(v: unknown): v is SelectionVarianceM6 {
  return ferme(v, ["wct_id", "reference_variance", "position_ligne", "materiau_id"]) && id(v.wct_id) && id(v.materiau_id) && entier(v.position_ligne, 9999) &&
    ferme(v.reference_variance, ["type", "evenement_id", "empreinte_charge"]) && v.reference_variance.type === "m6.variance_chantier" &&
    v.reference_variance.evenement_id === `m6-variance-${v.wct_id}-evaluee` && hash(v.reference_variance.empreinte_charge);
}
function pieces(v: unknown, max = 8): v is readonly PieceClassementM6[] {
  if (!Array.isArray(v) || v.length > max) return false;
  const vus = new Set<number>();
  return v.every(p => {
    if (!ferme(p, ["reference_mouvement", "reference_preuve", "positions_photos"]) || !reference(p.reference_mouvement, "principal") ||
      !(p.reference_preuve === null || reference(p.reference_preuve, "preuves_pertes_bris")) || !Array.isArray(p.positions_photos) || p.positions_photos.length > 3 ||
      !p.positions_photos.every(n => entier(n, 2)) || new Set(p.positions_photos).size !== p.positions_photos.length ||
      (p.reference_preuve === null && p.positions_photos.length !== 0)) return false;
    const n = (p.reference_mouvement as Record<string, unknown>).index as number;
    if (vus.has(n)) return false; vus.add(n); return true;
  });
}
const CLES_CLASSEMENT = ["reference", "selection", "cause", "motif", "reference_precedente", "auteur", "appareil_id", "classe_le", "horodatage_appareil_declare", "references_pieces"];
function intention(v: unknown): v is IntentionClassementM6 {
  return ferme(v, ["appareil_id", "intention_uuid", "empreinte_arguments"]) && id(v.appareil_id) && id(v.intention_uuid) && hash(v.empreinte_arguments);
}
function auteur(v: unknown): v is ClassementVarianceM6V1["auteur"] {
  return ferme(v, ["personne", "role", "source"]) && id(v.personne) && v.role === "admin" && v.source === "appareil";
}
function classement(v: unknown, sel: SelectionVarianceM6): v is ClassementVarianceM6 {
  if (!objet(v)) return false;
  const v2 = Object.hasOwn(v, "version_schema");
  if (!ferme(v, [...CLES_CLASSEMENT, ...(v2 ? ["version_schema", "intention"] : [])]) ||
    (v2 && (v.version_schema !== 2 || !intention(v.intention) || v.intention.appareil_id !== v.appareil_id)) ||
    !reference(v.reference, "classements_variance") || !selection(v.selection) || !egal(v.selection, sel) || !cause(v.cause) || !motifClassementValide(v.motif) ||
    !(v.reference_precedente === null || reference(v.reference_precedente, "classements_variance")) ||
    !auteur(v.auteur) ||
    !id(v.appareil_id) || !date(v.classe_le) || !date(v.horodatage_appareil_declare) || !pieces(v.references_pieces)) return false;
  if (v2 && (v.intention as IntentionClassementM6).empreinte_arguments !== empreinteArgumentsClassementVariance({
    selection: v.selection, cause: v.cause, motif: v.motif, classement_attendu: v.reference_precedente, references_pieces: v.references_pieces,
  })) return false;
  return v.reference_precedente === null || (v.reference_precedente as Record<string, unknown>).index! < (v.reference as Record<string, unknown>).index!;
}
function source(v: unknown, wct: string): v is SourceVarianceM6 {
  return ferme(v, ["type", "evenement_id", "empreinte_charge", "statut_variance", "horodatage_completion"]) &&
    v.type === "m6.variance_chantier" && v.evenement_id === `m6-variance-${wct}-evaluee` && hash(v.empreinte_charge) && v.statut_variance === "evaluee" && date(v.horodatage_completion);
}
function sourceSelection(s: SelectionVarianceM6, src: SourceVarianceM6): boolean {
  return s.reference_variance.type === src.type && s.reference_variance.evenement_id === src.evenement_id && s.reference_variance.empreinte_charge === src.empreinte_charge;
}
function page(v: unknown, count: number, args: { readonly decalage: number; readonly limite: number }): v is PaginationClassementsM6 {
  if (!ferme(v, ["decalage", "limite", "total", "affichees", "reste", "decalage_suivant", "borne_atteinte"]) || v.decalage !== args.decalage || v.limite !== args.limite ||
    !entier(v.total, 10000) || v.total < args.decalage || v.affichees !== count || count > args.limite || count > v.total - args.decalage) return false;
  const reste = v.total - args.decalage - count;
  return v.reste === reste && v.decalage_suivant === (reste ? args.decalage + count : null) && (!reste || count > 0) && v.borne_atteinte === (count < Math.min(args.limite, v.total - args.decalage));
}
function couverture(v: unknown): boolean { return ferme(v, Object.keys(COUVERTURE)) && egal(v, COUVERTURE); }
function argumentsPage(v: unknown): v is Record<string, unknown> & { readonly decalage: number; readonly limite: number } {
  return objet(v) && entier(v.decalage, 10000) && entier(v.limite, 8) && v.limite > 0;
}
export function construireArgumentsListeVariances(wctId: string, decalage = 0, limite = 8): ArgumentsListeVariancesM6 {
  if (!id(wctId) || !argumentsPage({ decalage, limite })) throw new Error("Lecture de variance invalide.");
  return { wct_id: wctId, decalage, limite };
}
export function construireArgumentsHistoriqueClassements(sel: SelectionVarianceM6, decalage = 0, limite = 8): ArgumentsHistoriqueClassementsM6 {
  const c = copierJsonLecture(sel); if (c === JSON_LECTURE_INVALIDE || !selection(c) || !argumentsPage({ decalage, limite })) throw new Error("Historique de classement invalide.");
  return { selection: c, decalage, limite };
}
function lire<T>(brut: unknown, parser: (v: unknown) => T | null): Reponse<T> {
  const c = copierJsonLecture(brut);
  if (c === JSON_LECTURE_INVALIDE) return illisible();
  const ouvert = ouvrirEnveloppe(c, "couple");
  if (!ouvert.ok) return { ok: false, code: ouvert.verdict.code, detail: ouvert.verdict.detail };
  if (!ferme(c, ["ok", "resultat"]) || !ferme(c.resultat, ["accepte", "resultat"])) return illisible();
  const valeur = parser(ouvert.valeur); return valeur ? { ok: true, value: valeur } : illisible();
}
const illisible = <T>(): Reponse<T> => ({ ok: false, code: "reponse_illisible", detail: "Classement illisible : aucun état partiel affiché." });
export function lireVariancesClassables(brut: unknown, args: unknown): Reponse<PageVariancesM6> {
  const a = copierJsonLecture(args);
  if (!ferme(a, ["wct_id", "decalage", "limite"]) || !id(a.wct_id) || !argumentsPage(a)) return illisible();
  const requete = a as unknown as ArgumentsListeVariancesM6;
  return lire(brut, v => {
    if (!ferme(v, ["wct", "source_variance", "lignes", "pagination", "couverture"]) || !ferme(v.wct, ["wct_id", "intervention_id", "chantier_id"]) ||
      v.wct.wct_id !== requete.wct_id || !id(v.wct.intervention_id) || !id(v.wct.chantier_id) || !source(v.source_variance, requete.wct_id) ||
      !Array.isArray(v.lignes) || !page(v.pagination, v.lignes.length, requete) || !couverture(v.couverture)) return null;
    const positions = new Set<number>();
    for (const l of v.lignes) {
      if (!ferme(l, ["selection", "source_ligne", "pieces_disponibles_a_selectionner", "classement_courant"]) || !selection(l.selection) || l.selection.wct_id !== requete.wct_id ||
        !sourceSelection(l.selection, v.source_variance) || positions.has(l.selection.position_ligne) ||
        !ferme(l.source_ligne, ["materiau", "unite", "quantite_prevue", "quantite_reelle", "ecart_pourcentage", "critique"]) || l.source_ligne.materiau !== l.selection.materiau_id ||
        !(l.source_ligne.unite === null || id(l.source_ligne.unite)) || !estDecimal(l.source_ligne.quantite_prevue) || !estDecimal(l.source_ligne.quantite_reelle) ||
        !(l.source_ligne.ecart_pourcentage === null || estDecimal(l.source_ligne.ecart_pourcentage)) || typeof l.source_ligne.critique !== "boolean" || !pieces(l.pieces_disponibles_a_selectionner, 10000) ||
        (!l.source_ligne.critique && l.pieces_disponibles_a_selectionner.length === 0) || !(l.classement_courant === null || classement(l.classement_courant, l.selection))) return null;
      positions.add(l.selection.position_ligne);
    }
    return v as unknown as PageVariancesM6;
  });
}
export function lireHistoriqueClassements(brut: unknown, args: unknown): Reponse<PageHistoriqueClassementsM6> {
  const a = copierJsonLecture(args);
  if (!ferme(a, ["selection", "decalage", "limite"]) || !selection(a.selection) || !argumentsPage(a)) return illisible();
  const requete = a as unknown as ArgumentsHistoriqueClassementsM6;
  return lire(brut, v => {
    if (!ferme(v, ["selection", "source_variance", "historique", "pagination", "couverture"]) || !egal(v.selection, requete.selection) || !source(v.source_variance, requete.selection.wct_id) ||
      !sourceSelection(requete.selection, v.source_variance) || !Array.isArray(v.historique) || !page(v.pagination, v.historique.length, requete) || !couverture(v.couverture)) return null;
    let precedent: ClassementVarianceM6 | null = null;
    for (const c of v.historique) {
      if (!classement(c, requete.selection) || (precedent && (c.reference.index <= precedent.reference.index || !egal(c.reference_precedente, precedent.reference)))) return null;
      precedent = c;
    }
    if (v.historique.length && ((requete.decalage === 0) !== (v.historique[0].reference_precedente === null))) return null;
    return v as unknown as PageHistoriqueClassementsM6;
  });
}
function argumentsClassement(v: unknown): v is ArgumentsClassementVarianceM6 {
  return ferme(v, ["selection", "cause", "motif", "classement_attendu", "references_pieces"]) && selection(v.selection) && cause(v.cause) && motifClassementValide(v.motif) &&
    (v.classement_attendu === null || reference(v.classement_attendu, "classements_variance")) && pieces(v.references_pieces);
}
/** Copie validée de la saisie avant toute attente ; aucun accesseur n’est exécuté. */
export function figerArgumentsClassementVariance(v: unknown): ArgumentsClassementVarianceM6 | null {
  const c = copierJsonLecture(v);
  return c !== JSON_LECTURE_INVALIDE && argumentsClassement(c) ? c : null;
}
function trierClesJson(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(trierClesJson);
  if (objet(v)) return Object.fromEntries(Object.keys(v).sort().map(k => [k, trierClesJson(v[k])]));
  return v;
}
/** Args fermés : clés ASCII, entiers bornés, texte Unicode verbatim; même encodeur canonique que Python. */
export function empreinteArgumentsClassementVariance(v: unknown): string | null {
  const args = figerArgumentsClassementVariance(v);
  return args ? bytesToHex(sha256(utf8ToBytes(JSON.stringify(trierClesJson(args))))) : null;
}
const CLE_DESTINATION = "_classement_local";
export interface DestinationClassementVariance { readonly appareilId: string; readonly urlBase: string }
function destination(v: unknown): v is { readonly appareil_id: string; readonly url_base: string } {
  if (!ferme(v, ["appareil_id", "url_base"]) || !id(v.appareil_id) || typeof v.url_base !== "string") return false;
  try {
    const url = new URL(v.url_base);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash;
  } catch { return false; }
}
export function creerMutationClassementVariance(args: ArgumentsClassementVarianceM6, genererId: () => string, horloge: HorlogeAppareil, cible: DestinationClassementVariance): MutationOutbox {
  const c = figerArgumentsClassementVariance(args);
  const locale = cible && { appareil_id: cible.appareilId, url_base: cible.urlBase };
  if (!c || !destination(locale) || !Number.isFinite(horloge.maintenant.getTime()) || !Number.isInteger(horloge.decalageMinutesUTC) || Math.abs(horloge.decalageMinutesUTC) >= 1440) throw new Error("Classement invalide : aucune intention créée.");
  const m = creerMutation({ type: "variance_cause_classification", chantierId: `variance:${c.selection.wct_id}`,
    payload: { ...c, [CLE_DESTINATION]: locale } }, genererId, horloge);
  if (!id(m.id) || !date(m.createdAtLocal)) throw new Error("Identifiant ou heure d’intention invalide.");
  return soumettreMutation(m);
}
function lireCharge(m: MutationOutbox): { readonly args: ArgumentsClassementVarianceM6; readonly destination: { readonly appareil_id: string; readonly url_base: string } } | null {
  const c = copierJsonLecture(m);
  if (c === JSON_LECTURE_INVALIDE || !objet(c) || c.type !== "variance_cause_classification" || !id(c.id) || !objet(c.payload) || !date(c.createdAtLocal)) return null;
  const { [CLE_DESTINATION]: locale, ...args } = c.payload;
  if (!destination(locale) || !argumentsClassement(args) || c.chantierId !== `variance:${args.selection.wct_id}`) return null;
  return { args, destination: locale };
}
/** La destination locale n'est jamais envoyée en argument ou utilisée comme autorité serveur. */
export function argumentsRpcClassementVariance(m: MutationOutbox): Readonly<Record<string, unknown>> | null {
  const c = lireCharge(m); return c ? { ...c.args } : null;
}
export function verifierDestinationClassementVariance(m: MutationOutbox, session: Pick<SessionEnvoi, "appareilId" | "urlBase">): boolean {
  const c = lireCharge(m);
  return c !== null && c.destination.appareil_id === session.appareilId && c.destination.url_base === session.urlBase;
}
const inconnu: InterpretationClassementVariance = { accepte: false, verdict: { code: "accuse_invalide", detail: "Confirmation inconnue : même intention de classement conservée." } };
const SUFFIXES_REFUS_CERTAINS = ["LIGNE-HORS-PERIMETRE", "ARGUMENTS-INVALIDES", "PIECES-INVALIDES", "LIAISON-INCOHERENTE", "REVISION-PERIMEE", "SORTIE-TROP-VOLUMINEUSE"];
const DETAIL_REFUS_CERTAIN = "le classement ne satisfait pas son contrat ; aucun détail partiel n’est transmis";
/** Aucun Date.parse : le décalage civil est exact, les fractions ne perdent aucune microseconde. */
function microsecondes(v: unknown): bigint | null {
  if (!date(v)) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(v);
  if (!m) return null;
  const d = new Date(0); d.setUTCFullYear(Number(m[1]), Number(m[2]) - 1, Number(m[3])); d.setUTCHours(Number(m[4]), Number(m[5]), Number(m[6]), 0);
  const offset = m[8] === "Z" ? 0 : (Number(m[10]) * 60 + Number(m[11])) * (m[9] === "-" ? -1 : 1);
  return BigInt(d.getTime() - offset * 60000) * 1000n + BigInt((m[7] ?? "").padEnd(6, "0"));
}
function memeInstant(v: unknown, original: string): boolean {
  const instant = microsecondes(v); return instant !== null && instant === microsecondes(original);
}
function intentionPropre(v: unknown, args: ArgumentsClassementVarianceM6, m: MutationOutbox, appareilId: string): boolean {
  return intention(v) && v.appareil_id === appareilId && v.intention_uuid === m.id && v.empreinte_arguments === empreinteArgumentsClassementVariance(args);
}
export function interpreterClassementVariance(brut: unknown, mutation?: MutationOutbox): InterpretationClassementVariance {
  if (!mutation) return inconnu;
  const charge = lireCharge(mutation), args = charge?.args;
  const c = copierJsonLecture(brut);
  if (!args || !objet(c) || c.ok !== true || !ferme(c, ["ok", "resultat", ...(Object.hasOwn(c, "rejoue") ? ["rejoue"] : [])]) ||
    (Object.hasOwn(c, "rejoue") && typeof c.rejoue !== "boolean") || !objet(c.resultat)) return inconnu;
  const r = c.resultat;
  if (r.accepte === false) {
    // Un négatif v1, même frais, ne prouve pas qu'un ancien effet n'a jamais existé.
    if (!ferme(r, ["accepte", "version_schema", "verdict", "intention", "preuve_refus", "auteur", "horodatage_appareil_declare"]) || r.version_schema !== 2 ||
      !ferme(r.verdict, ["code", "detail"])) return inconnu;
    const verdict = r.verdict, code = verdict.code;
    if (typeof code !== "string" || !SUFFIXES_REFUS_CERTAINS.some(s => code === `REJ-M6-CLASSEMENT-${s}`) || verdict.detail !== DETAIL_REFUS_CERTAIN ||
      !intentionPropre(r.intention, args, mutation, charge!.destination.appareil_id) || !reference(r.preuve_refus, "refus_classement_variance") ||
      !auteur(r.auteur) || r.auteur.personne !== mutation.proprietaire || !memeInstant(r.horodatage_appareil_declare, mutation.createdAtLocal)) return inconnu;
    return { accepte: false, verdict: { code, detail: verdict.detail } };
  }
  const v2 = Object.hasOwn(r, "version_schema");
  if (!ferme(r, ["accepte", "resultat", "registre", ...(v2 ? ["version_schema"] : [])]) || r.accepte !== true || !classement(r.resultat, args.selection) ||
    (v2 ? r.version_schema !== 2 || !("version_schema" in r.resultat) || !intentionPropre(r.resultat.intention, args, mutation, charge!.destination.appareil_id)
      : "version_schema" in r.resultat) || !ferme(r.registre, ["taille", "hash_tete"]) ||
    r.registre.taille !== r.resultat.reference.index + 1 || r.registre.hash_tete !== r.resultat.reference.hash_maillon ||
    r.resultat.cause !== args.cause || r.resultat.motif !== args.motif || !egal(r.resultat.reference_precedente, args.classement_attendu) || !egal(r.resultat.references_pieces, args.references_pieces) ||
    r.resultat.auteur.personne !== mutation.proprietaire || r.resultat.appareil_id !== charge!.destination.appareil_id || !memeInstant(r.resultat.horodatage_appareil_declare, mutation.createdAtLocal)) return inconnu;
  return { accepte: true, resume: { ...(r.resultat as ClassementVarianceM6), registre_confirmation: { taille: r.registre.taille as number, hash_tete: r.registre.hash_tete as string } } };
}
export function validerRecuClassementVariance(m: MutationOutbox): boolean {
  const mutation = copierJsonLecture(m);
  if (!objet(mutation) || mutation.statut !== "envoyee" || !objet(mutation.resumeAccepte)) return false;
  const c = mutation.resumeAccepte, v2 = Object.hasOwn(c, "version_schema");
  if (!ferme(c, [...CLES_CLASSEMENT, "registre_confirmation", ...(v2 ? ["version_schema", "intention"] : [])])) return false;
  const { registre_confirmation, ...resultat } = c;
  return interpreterClassementVariance({ ok: true, resultat: { accepte: true, ...(v2 ? { version_schema: 2 } : {}), resultat, registre: registre_confirmation } }, mutation as unknown as MutationOutbox).accepte;
}
export const interpreterClassementGenerique = (r: unknown, m?: MutationOutbox): InterpretationResultatMetier => interpreterClassementVariance(r, m);
