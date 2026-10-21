import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { horodatageM10Valide } from "../m10/contrat";
import type { Reponse } from "../m7/contrat";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { InterpretationResultatMetier } from "../outbox/vidangeur";
import type { SessionEnvoi } from "../protocole/configuration";

export const OUTIL_OBLIGATIONS_PREPAREES = "m5_lire_obligations_preparees_appareil";
export const OUTIL_ENREGISTRER_OBLIGATION_PREPAREE = "m5_enregistrer_obligation_preparee_appareil";
export const CATEGORIES_OBLIGATIONS = ["paies", "das", "dettes"] as const;
export type CategorieObligation = typeof CATEGORIES_OBLIGATIONS[number];
export interface ReferenceObligation {
  readonly registre: "obligations_preparees"; readonly index: number; readonly ligne_id: string; readonly precedent_ligne_id: string | null;
}
export interface CalendrierDeclareObligation {
  readonly autorite: string | null; readonly periode_debut: string | null; readonly periode_fin: string | null;
  readonly echeance_source: string | null; readonly source_consultee_le: string | null; readonly source_applicable_du: string | null;
  readonly source_applicable_jusqu_au: string | null; readonly annee: number | null; readonly version: string | null;
}
export interface DeclarationObligation {
  readonly montant: string | null; readonly source: string | null; readonly au: string | null; readonly echeance: string | null;
  readonly calendrier: CalendrierDeclareObligation | null;
}
export interface ArgumentsObligations { readonly aujourd_hui: string; readonly decalage: number; readonly limite: number }
export interface ArgumentsDeclarationObligation {
  readonly categorie: CategorieObligation; readonly operation: "declarer" | "retirer"; readonly declaration: DeclarationObligation | null;
  readonly revision_attendue: ReferenceObligation | null; readonly motif: string;
}
export interface AuteurObligation { readonly personne: string; readonly role: "admin"; readonly source: "appareil" }
export interface IntentionObligation { readonly appareil_id: string; readonly intention_uuid: string; readonly empreinte_arguments: string }
export interface PersistedObligation {
  readonly categorie: CategorieObligation; readonly etat_declaration: "ABSENTE" | "DECLAREE" | "RETIREE";
  readonly declaration: DeclarationObligation | null; readonly reference: ReferenceObligation | null;
  readonly revision_precedente: ReferenceObligation | null; readonly auteur: AuteurObligation | null;
  readonly intention: IntentionObligation | null; readonly enregistree_le: string | null; readonly horodatage_appareil_declare: string | null;
}
export interface CalendrierObligation {
  readonly id: CategorieObligation; readonly nom: string; readonly autorite: string | null;
  readonly periode: { readonly debut: string | null; readonly fin: string | null }; readonly echeance: string | null;
  readonly montant: string | null; readonly devise: "CAD" | null;
  readonly source_montant: { readonly description: string | null; readonly au: string | null };
  readonly source_echeance: { readonly description: string | null; readonly consultee_le: string | null; readonly applicable_du: string | null; readonly applicable_jusqu_au: string | null };
  readonly annee: number | null; readonly version: string | null; readonly montant_utilisable: string | null;
  readonly echeance_statut: "NON_DECLAREE" | "PASSEE_A_VERIFIER" | "A_VENIR";
  readonly statut: "SOURCE_PERIMEE" | "INCOMPLETE" | "ECHEANCE_PASSEE_A_VERIFIER" | "DOCUMENTEE_A_VALIDER";
  readonly manque: readonly { readonly code: string; readonly detail: string }[];
}
export interface LigneObligationPreparee extends PersistedObligation { readonly calendrier_preparatoire: CalendrierObligation }
export interface PageObligationsPreparees {
  readonly type: "DECLARATIONS_PREPARATOIRES_OBLIGATIONS"; readonly version_schema: 1; readonly aujourd_hui: string;
  readonly source_canonique: "REGISTRE_PREPARATOIRE_DURABLE"; readonly registre: "obligations_preparees";
  readonly decalage: number; readonly limite: number; readonly total: 3; readonly decalage_suivant: number | null;
  readonly obligations: readonly LigneObligationPreparee[]; readonly mention: "Analyse préparatoire IA";
  readonly couverture: { readonly categories: "paies_das_dettes_seulement"; readonly montants: "declares_non_attestes";
    readonly source: "registre_preparatoire_sans_activation_YAML_cash_CFO"; readonly echeances: "a_verifier_sans_etat_paiement";
    readonly pages: "courantes_non_figees"; readonly plafond_lignes: 10000 };
}
export interface MetaLocaleObligation {
  readonly personne: string; readonly appareil_id: string; readonly intention_uuid: string; readonly horodatage_appareil_declare: string;
}
export type DestinationObligation = Pick<SessionEnvoi, "personne" | "appareilId" | "urlBase">;
const objet = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const ferme = (v: unknown, keys: readonly string[]): v is Record<string, unknown> => objet(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const entier = (v: unknown, max = 10000): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
const categorie = (v: unknown): v is CategorieObligation => CATEGORIES_OBLIGATIONS.includes(v as CategorieObligation);
const scalaire = (v: unknown): v is string => typeof v === "string" && !/[\p{Cs}]/u.test(v);
const nonVide = (v: unknown): v is string => scalaire(v) && /[^\p{White_Space}\u001c-\u001f]/u.test(v);
const texte = (v: unknown, max: number): v is string => nonVide(v) && [...v].length <= max;
const argent = (v: unknown): v is string => typeof v === "string" && /^[0-9]{1,12}(?:\.[0-9]{1,2})?$/.test(v) && !/\s/.test(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(v);
const option = <T,>(v: unknown, parser: (u: unknown) => u is T): v is T | null => v === null || parser(v);
const PERSISTED_KEYS = ["categorie", "etat_declaration", "declaration", "reference", "revision_precedente", "auteur", "intention", "enregistree_le", "horodatage_appareil_declare"];
const CALENDAR_KEYS = ["autorite", "periode_debut", "periode_fin", "echeance_source", "source_consultee_le", "source_applicable_du", "source_applicable_jusqu_au", "annee", "version"];
/** Civil dates are validated numerically, never interpreted as an instant or repaired. */
export function dateObligationValide(v: unknown): v is string {
  if (typeof v !== "string" || v.length !== 10 || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const [y, m, d] = v.split("-").map(Number), leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  return y > 0 && m > 0 && m <= 12 && d > 0 && d <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
}
function reference(v: unknown): v is ReferenceObligation {
  return ferme(v, ["registre", "index", "ligne_id", "precedent_ligne_id"]) && v.registre === "obligations_preparees" && entier(v.index, 9999) && hash(v.ligne_id) &&
    (v.index === 0 ? v.precedent_ligne_id === null : hash(v.precedent_ligne_id));
}
function calendarRaw(v: unknown): v is CalendrierDeclareObligation {
  if (!ferme(v, CALENDAR_KEYS) || !["autorite", "echeance_source", "version"].every(k => option(v[k], x => texte(x, 240))) ||
    !["periode_debut", "periode_fin", "source_consultee_le", "source_applicable_du", "source_applicable_jusqu_au"].every(k => option(v[k], dateObligationValide)) ||
    !(v.annee === null || (entier(v.annee, 9999) && v.annee > 0))) return false;
  if (typeof v.periode_debut === "string" && typeof v.periode_fin === "string" && v.periode_fin < v.periode_debut) return false;
  if (typeof v.source_applicable_du === "string" && typeof v.source_applicable_jusqu_au === "string" && v.source_applicable_jusqu_au < v.source_applicable_du) return false;
  return true;
}
function declaration(v: unknown): v is DeclarationObligation {
  return ferme(v, ["montant", "source", "au", "echeance", "calendrier"]) && option(v.montant, argent) && option(v.source, x => texte(x, 120)) &&
    option(v.au, dateObligationValide) && option(v.echeance, dateObligationValide) && option(v.calendrier, calendarRaw);
}
function argsRead(v: unknown): v is ArgumentsObligations {
  return ferme(v, ["aujourd_hui", "decalage", "limite"]) && dateObligationValide(v.aujourd_hui) && entier(v.decalage) && entier(v.limite, 8) && v.limite > 0;
}
function argsWrite(v: unknown): v is ArgumentsDeclarationObligation {
  return ferme(v, ["categorie", "operation", "declaration", "revision_attendue", "motif"]) && categorie(v.categorie) &&
    option(v.revision_attendue, reference) && scalaire(v.motif) && [...v.motif].length <= 500 &&
    (v.operation === "declarer" ? declaration(v.declaration) : v.operation === "retirer" && v.declaration === null && nonVide(v.motif));
}
export function construireArgumentsObligations(aujourdHui: string, decalage = 0, limite = 1): ArgumentsObligations {
  const v = { aujourd_hui: aujourdHui, decalage, limite }; if (!argsRead(v)) throw new Error("Lecture d’obligations invalide."); return v;
}
export function figerArgumentsDeclarationObligation(brut: unknown): ArgumentsDeclarationObligation | null {
  const c = copierJsonLecture(brut); return c !== JSON_LECTURE_INVALIDE && argsWrite(c) ? c : null;
}
export function construireArgumentsDeclarationObligation(c: CategorieObligation, operation: "declarer" | "retirer", d: DeclarationObligation | null, revision: ReferenceObligation | null, motif: string): ArgumentsDeclarationObligation {
  const v = figerArgumentsDeclarationObligation({ categorie: c, operation, declaration: d, revision_attendue: revision, motif });
  if (!v) throw new Error("Déclaration préparatoire invalide."); return v;
}
function canonique(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(canonique).join(",") + "]";
  return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canonique((v as Record<string, unknown>)[k])).join(",") + "}";
}
export function empreinteArgumentsObligation(brut: unknown): string {
  const a = figerArgumentsDeclarationObligation(brut); if (!a) throw new Error("Arguments d’intention invalides.");
  return bytesToHex(sha256(utf8ToBytes(canonique(a))));
}
const equal = (a: unknown, b: unknown) => canonique(a) === canonique(b);
function auteur(v: unknown): v is AuteurObligation { return ferme(v, ["personne", "role", "source"]) && nonVide(v.personne) && v.role === "admin" && v.source === "appareil"; }
function intention(v: unknown): v is IntentionObligation { return ferme(v, ["appareil_id", "intention_uuid", "empreinte_arguments"]) && nonVide(v.appareil_id) && nonVide(v.intention_uuid) && hash(v.empreinte_arguments); }
function persisted(v: unknown, avecCalendrier = false): v is PersistedObligation {
  if (!ferme(v, [...PERSISTED_KEYS, ...(avecCalendrier ? ["calendrier_preparatoire"] : [])]) || !categorie(v.categorie)) return false;
  if (v.etat_declaration === "ABSENTE") return PERSISTED_KEYS.filter(k => !["categorie", "etat_declaration"].includes(k)).every(k => v[k] === null);
  if (!(v.etat_declaration === "DECLAREE" ? declaration(v.declaration) : v.etat_declaration === "RETIREE" && v.declaration === null) ||
    !reference(v.reference) || !option(v.revision_precedente, reference) || !auteur(v.auteur) || !intention(v.intention) ||
    !horodatageM10Valide(v.enregistree_le) || !horodatageM10Valide(v.horodatage_appareil_declare)) return false;
  return v.revision_precedente === null || v.revision_precedente.index < v.reference.index;
}
/** Python strip for valid scalar input: FEFF is retained, unlike JavaScript trim. */
const normalize = (v: string | null | undefined) => typeof v === "string" ? v.replace(/^[\p{White_Space}\u001c-\u001f]+|[\p{White_Space}\u001c-\u001f]+$/gu, "") : null;
function calendar(v: unknown, r: PersistedObligation, aujourdHui: string): v is CalendrierObligation {
  if (!ferme(v, ["id", "nom", "autorite", "periode", "echeance", "montant", "devise", "source_montant", "source_echeance", "annee", "version", "montant_utilisable", "echeance_statut", "statut", "manque"]) ||
    v.id !== r.categorie || v.nom !== { paies: "Paies", das: "Déductions à la source (DAS)", dettes: "Dettes déclarées" }[r.categorie] ||
    !ferme(v.periode, ["debut", "fin"]) || !ferme(v.source_montant, ["description", "au"]) ||
    !ferme(v.source_echeance, ["description", "consultee_le", "applicable_du", "applicable_jusqu_au"]) || !Array.isArray(v.manque) ||
    !v.manque.every(x => ferme(x, ["code", "detail"]) && typeof x.code === "string" && x.code.startsWith("REJ-CALENDRIER-") && typeof x.detail === "string")) return false;
  const d = r.declaration, m = d?.calendrier;
  if (v.montant !== (d?.montant ?? null) || v.devise !== (d?.montant == null ? null : "CAD") || v.source_montant.description !== normalize(d?.source) ||
    v.source_montant.au !== (d?.au ?? null) || v.echeance !== (d?.echeance ?? null) || v.autorite !== normalize(m?.autorite) || v.version !== normalize(m?.version) ||
    v.annee !== (m?.annee ?? null) || v.periode.debut !== (m?.periode_debut ?? null) || v.periode.fin !== (m?.periode_fin ?? null) ||
    v.source_echeance.description !== normalize(m?.echeance_source) || v.source_echeance.consultee_le !== (m?.source_consultee_le ?? null) ||
    v.source_echeance.applicable_du !== (m?.source_applicable_du ?? null) || v.source_echeance.applicable_jusqu_au !== (m?.source_applicable_jusqu_au ?? null)) return false;
  const perimee = !!(m?.periode_debut && m.periode_fin && m.source_applicable_du && m.source_applicable_jusqu_au &&
    (m.source_applicable_du > m.periode_debut || m.source_applicable_jusqu_au < m.periode_fin));
  const usable = d?.montant != null && d.source !== null && d.au !== null && !perimee ? d.montant : null;
  if (v.montant_utilisable !== usable || v.echeance_statut !== (d?.echeance == null ? "NON_DECLAREE" : d.echeance < aujourdHui ? "PASSEE_A_VERIFIER" : "A_VENIR")) return false;
  return perimee ? v.statut === "SOURCE_PERIMEE" : v.manque.length ? v.statut === "INCOMPLETE" :
    v.statut === (d?.echeance && d.echeance < aujourdHui ? "ECHEANCE_PASSEE_A_VERIFIER" : "DOCUMENTEE_A_VALIDER");
}
const illisible = <T,>(): Reponse<T> => ({ ok: false, code: "reponse_illisible", detail: "Obligations illisibles : aucun état partiel affiché." });
function refus<T>(v: Record<string, unknown>): Reponse<T> | null {
  if (v.ok === false && typeof v.erreur === "string") return { ok: false, code: v.erreur, detail: typeof v.details === "string" ? v.details : "" };
  if (v.ok === true && ferme(v.resultat, ["accepte", "verdict"]) && v.resultat.accepte === false && ferme(v.resultat.verdict, ["code", "detail"]) &&
    typeof v.resultat.verdict.code === "string" && typeof v.resultat.verdict.detail === "string") return { ok: false, code: v.resultat.verdict.code, detail: v.resultat.verdict.detail };
  return null;
}
export function lireObligationsPreparees(brut: unknown, args: unknown): Reponse<PageObligationsPreparees> {
  const a = copierJsonLecture(args), e = copierJsonLecture(brut); if (!argsRead(a) || !objet(e)) return illisible();
  const failure = refus<PageObligationsPreparees>(e); if (failure) return failure;
  if (!ferme(e, ["ok", "resultat"]) || e.ok !== true || !ferme(e.resultat, ["accepte", "resultat"]) || e.resultat.accepte !== true) return illisible();
  const v = e.resultat.resultat;
  if (!ferme(v, ["type", "version_schema", "aujourd_hui", "source_canonique", "registre", "decalage", "limite", "total", "decalage_suivant", "obligations", "mention", "couverture"]) ||
    v.type !== "DECLARATIONS_PREPARATOIRES_OBLIGATIONS" || v.version_schema !== 1 || v.aujourd_hui !== a.aujourd_hui || v.source_canonique !== "REGISTRE_PREPARATOIRE_DURABLE" ||
    v.decalage !== a.decalage || v.limite !== a.limite || v.total !== 3 || v.mention !== "Analyse préparatoire IA" ||
    v.registre !== "obligations_preparees" ||
    !Array.isArray(v.obligations) || v.obligations.length !== Math.max(0, Math.min(a.limite, 3 - a.decalage)) ||
    v.decalage_suivant !== (a.decalage + v.obligations.length < 3 ? a.decalage + v.obligations.length : null) ||
    !equal(v.couverture, { categories: "paies_das_dettes_seulement", montants: "declares_non_attestes", source: "registre_preparatoire_sans_activation_YAML_cash_CFO",
      echeances: "a_verifier_sans_etat_paiement", pages: "courantes_non_figees", plafond_lignes: 10000 })) return illisible();
  for (let i = 0; i < v.obligations.length; ++i) {
    const r = v.obligations[i];
    if (!persisted(r, true) || r.categorie !== CATEGORIES_OBLIGATIONS[a.decalage + i] ||
      !calendar((r as unknown as LigneObligationPreparee).calendrier_preparatoire, r, a.aujourd_hui)) return illisible();
  }
  return { ok: true, value: v as unknown as PageObligationsPreparees };
}
export function lireAccuseObligationPreparee(brut: unknown, args: unknown, meta: unknown): Reponse<PersistedObligation> {
  const a = figerArgumentsDeclarationObligation(args), m = copierJsonLecture(meta), e = copierJsonLecture(brut);
  if (!a || !ferme(m, ["personne", "appareil_id", "intention_uuid", "horodatage_appareil_declare"]) || !nonVide(m.personne) || !nonVide(m.appareil_id) ||
    !nonVide(m.intention_uuid) || !horodatageM10Valide(m.horodatage_appareil_declare) || !objet(e) ||
    !ferme(e, ["ok", "resultat", ...(Object.hasOwn(e, "rejoue") ? ["rejoue"] : [])]) || e.ok !== true ||
    (Object.hasOwn(e, "rejoue") && typeof e.rejoue !== "boolean") || !ferme(e.resultat, ["accepte", "version_schema", "resultat", "registre"]) ||
    e.resultat.accepte !== true || e.resultat.version_schema !== 1 || !persisted(e.resultat.resultat)) return illisible();
  const r = e.resultat.resultat, reg = e.resultat.registre;
  if (!r.reference || !r.auteur || !r.intention || r.categorie !== a.categorie || r.etat_declaration !== (a.operation === "declarer" ? "DECLAREE" : "RETIREE") ||
    !equal(r.declaration, a.declaration) || !equal(r.revision_precedente, a.revision_attendue) || r.auteur.personne !== m.personne ||
    r.intention.appareil_id !== m.appareil_id || r.intention.intention_uuid !== m.intention_uuid || r.intention.empreinte_arguments !== empreinteArgumentsObligation(a) ||
    r.horodatage_appareil_declare !== m.horodatage_appareil_declare || reg !== "obligations_preparees") return illisible();
  return { ok: true, value: r };
}
const LOCAL = "_obligation_locale";
interface Locale { readonly personne: string; readonly appareil_id: string; readonly url_base: string }
function destination(v: unknown): v is Locale {
  if (!ferme(v, ["personne", "appareil_id", "url_base"]) || !nonVide(v.personne) || !nonVide(v.appareil_id) || typeof v.url_base !== "string") return false;
  try { const u = new URL(v.url_base); return ["http:", "https:"].includes(u.protocol) && !u.username && !u.password && !u.search && !u.hash; } catch { return false; }
}
export function creerMutationObligationPreparee(args: ArgumentsDeclarationObligation, genererId: () => string, horloge: HorlogeAppareil, cible: DestinationObligation): MutationOutbox {
  const a = figerArgumentsDeclarationObligation(args), c = copierJsonLecture(cible);
  const local = objet(c) ? { personne: c.personne, appareil_id: c.appareilId, url_base: c.urlBase } : null;
  if (!a || !destination(local) || !Number.isFinite(horloge.maintenant.getTime()) || !Number.isInteger(horloge.decalageMinutesUTC) || Math.abs(horloge.decalageMinutesUTC) >= 1440) throw new Error("Intention d’obligation invalide.");
  const m = creerMutation({ type: "obligation_preparee", chantierId: `obligation-m5:${a.categorie}`, payload: { ...a, [LOCAL]: local } }, genererId, horloge);
  if (!uuid(m.id) || !horodatageM10Valide(m.createdAtLocal)) throw new Error("UUID ou heure d’intention invalide.");
  return { ...soumettreMutation(m), destination: local.url_base, proprietaire: local.personne };
}
function charge(mutation: MutationOutbox): { args: ArgumentsDeclarationObligation; locale: Locale; meta: MetaLocaleObligation } | null {
  const c = copierJsonLecture(mutation); if (!objet(c) || c.type !== "obligation_preparee" || !objet(c.payload) || !uuid(c.id) || !horodatageM10Valide(c.createdAtLocal)) return null;
  const { [LOCAL]: locale, ...args } = c.payload;
  if (!destination(locale) || !argsWrite(args) || c.chantierId !== `obligation-m5:${args.categorie}` || c.proprietaire !== locale.personne) return null;
  return { args, locale, meta: { personne: locale.personne, appareil_id: locale.appareil_id, intention_uuid: c.id, horodatage_appareil_declare: c.createdAtLocal } };
}
export function argumentsRpcObligationPreparee(m: MutationOutbox): Readonly<Record<string, unknown>> | null { const c = charge(m); return c ? { ...c.args } : null; }
export function verifierDestinationObligationPreparee(m: MutationOutbox, session: DestinationObligation): boolean {
  const c = charge(m), s = copierJsonLecture(session);
  return !!c && objet(s) && c.locale.personne === s.personne && c.locale.appareil_id === s.appareilId && c.locale.url_base === s.urlBase;
}
const inconnue: InterpretationResultatMetier = { accepte: false, verdict: { code: "accuse_invalide", detail: "Confirmation inconnue : même intention d’obligation conservée." } };
export function interpreterObligationPreparee(brut: unknown, mutation?: MutationOutbox): InterpretationResultatMetier {
  const c = mutation && charge(mutation); if (!c) return inconnue;
  const r = lireAccuseObligationPreparee(brut, c.args, c.meta); return r.ok ? { accepte: true, resume: r.value } : inconnue;
}
export function validerRecuObligationPreparee(m: MutationOutbox): boolean {
  const copie = copierJsonLecture(m);
  if (!objet(copie) || copie.statut !== "envoyee") return false;
  const c = charge(copie as unknown as MutationOutbox), r = copie.resumeAccepte; if (!c || !persisted(r) || !r.reference) return false;
  // Local validation of a receipt already admitted, not a reconstructed transport capture.
  return lireAccuseObligationPreparee({ ok: true, resultat: { accepte: true, version_schema: 1, resultat: r,
    registre: "obligations_preparees" } }, c.args, c.meta).ok;
}
