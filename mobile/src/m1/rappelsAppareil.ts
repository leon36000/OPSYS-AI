import { ouvrirEnveloppe } from "../admin/enveloppe";
import { identifiantTransfertM1Valide, instantM1Valide, lireSuiviRappelM1 } from "./contrat";
import type { SuiviRappelM1 } from "./contrat";
import type { Reponse } from "../m7/contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { InterpretationResultatMetier } from "../outbox/vidangeur";
import type { SessionEnvoi } from "../protocole/configuration";

export const OUTIL_LISTE_RAPPELS_M1 = "m1_lister_rappels_appareil";
export const OUTIL_PRISE_RAPPEL_M1 = "m1_prendre_en_charge_rappel_appareil";
export interface ArgumentsRappelsM1 { readonly apres_transfert_id: string | null; readonly taille_page: number }
export interface ArgumentsPriseRappelM1 { readonly transfert_id: string; readonly snapshot_attendu: string }
export interface RappelAppareilM1 {
  readonly transfert_id: string; readonly conversation_id: string; readonly lead_id: string | null;
  readonly canal: "telephone"; readonly ouvert_le: string; readonly nombre_sources: number;
  readonly derniere_source: { readonly ligne_id: string; readonly statut: "manque" | "voicemail"; readonly recu_le: string };
  readonly suivi_rappel: SuiviRappelM1;
}
export interface PageRappelsM1 {
  readonly rappels: readonly RappelAppareilM1[];
  readonly page: { readonly apres_transfert_id: string | null; readonly taille_page: number; readonly total: number;
    readonly retournes: number; readonly reste: number; readonly apres_suivant: string | null };
}
export interface AckPriseRappelM1 {
  readonly version: 1; readonly transfert_id: string; readonly action: "prise_en_charge"; readonly ligne_id: string;
  readonly precedent_ligne_id: string | null; readonly index: number; readonly snapshot_attendu: string;
  readonly par: string; readonly role: "admin"; readonly voie: "appareil"; readonly appareil: string;
  readonly intention_uuid: string; readonly recu_le_serveur: string; readonly horodatage_appareil: string;
  readonly suivi_rappel: SuiviRappelM1;
}
export interface MetaLocalePriseRappelM1 {
  readonly intention_uuid: string; readonly par: string; readonly appareil: string; readonly horodatage_appareil: string;
}
export type DestinationPriseRappelM1 = Pick<SessionEnvoi, "personne" | "appareilId" | "urlBase">;
const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const ferme = (v: unknown, keys: readonly string[]): v is Record<string, unknown> => objet(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const texte = (v: unknown): v is string => typeof v === "string" && [...v].length <= 256 && /[^\p{White_Space}]/u.test(v) && !/[\p{Cc}\p{Cs}]/u.test(v);
const entier = (v: unknown, max = 10000): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(v);
const argsListe = (v: unknown): v is ArgumentsRappelsM1 => ferme(v, ["apres_transfert_id", "taille_page"]) &&
  (v.apres_transfert_id === null || identifiantTransfertM1Valide(v.apres_transfert_id)) && entier(v.taille_page, 8) && v.taille_page > 0;
const argsPrise = (v: unknown): v is ArgumentsPriseRappelM1 => ferme(v, ["transfert_id", "snapshot_attendu"]) && identifiantTransfertM1Valide(v.transfert_id) && hash(v.snapshot_attendu);
export function construireArgumentsRappelsM1(apresTransfertId: string | null = null, taillePage = 8): ArgumentsRappelsM1 {
  const v = { apres_transfert_id: apresTransfertId, taille_page: taillePage };
  if (!argsListe(v)) throw new Error("Page de rappels invalide."); return v;
}
export function construireArgumentsPriseRappelM1(transfertId: string, snapshotAttendu: string): ArgumentsPriseRappelM1 {
  const v = { transfert_id: transfertId, snapshot_attendu: snapshotAttendu };
  if (!argsPrise(v)) throw new Error("Prise en charge invalide."); return v;
}
export function figerArgumentsPriseRappelM1(brut: unknown): ArgumentsPriseRappelM1 | null {
  const c = copierJsonLecture(brut); return c !== JSON_LECTURE_INVALIDE && argsPrise(c) ? c : null;
}
const illisible = <T>(): Reponse<T> => ({ ok: false, code: "reponse_illisible", detail: "Rappels illisibles : aucun état partiel affiché." });
function ouvrir<T>(brut: unknown, parser: (v: unknown) => T | null): Reponse<T> {
  const c = copierJsonLecture(brut); if (c === JSON_LECTURE_INVALIDE) return illisible();
  const o = ouvrirEnveloppe(c, "couple"); if (!o.ok) return { ok: false, code: o.verdict.code, detail: o.verdict.detail };
  if (!ferme(c, ["ok", "resultat", ...(objet(c) && Object.hasOwn(c, "rejoue") ? ["rejoue"] : [])]) ||
    (Object.hasOwn(c, "rejoue") && typeof c.rejoue !== "boolean") || !ferme(c.resultat, ["accepte", "resultat"])) return illisible();
  const v = parser(o.valeur); return v ? { ok: true, value: v } : illisible();
}
export function lireRappelsM1(brut: unknown, args: unknown): Reponse<PageRappelsM1> {
  const a = copierJsonLecture(args); if (!argsListe(a)) return illisible();
  return ouvrir(brut, v => {
    if (!ferme(v, ["rappels", "page"]) || !Array.isArray(v.rappels) || v.rappels.length > a.taille_page ||
      !ferme(v.page, ["apres_transfert_id", "taille_page", "total", "retournes", "reste", "apres_suivant"]) ||
      v.page.apres_transfert_id !== a.apres_transfert_id || v.page.taille_page !== a.taille_page || !entier(v.page.total) ||
      v.page.retournes !== v.rappels.length || !entier(v.page.reste) || v.page.total < v.rappels.length + v.page.reste ||
      (a.apres_transfert_id === null && v.page.total !== v.rappels.length + v.page.reste) ||
      (v.page.reste > 0 && v.rappels.length !== a.taille_page)) return null;
    let precedent = a.apres_transfert_id;
    for (const r of v.rappels) {
      if (!ferme(r, ["transfert_id", "conversation_id", "lead_id", "canal", "ouvert_le", "nombre_sources", "derniere_source", "suivi_rappel"]) ||
        !identifiantTransfertM1Valide(r.transfert_id) || (precedent !== null && r.transfert_id <= precedent) ||
        typeof r.conversation_id !== "string" || !/^sms-[0-9a-f]{24}$/.test(r.conversation_id) || !(r.lead_id === null || texte(r.lead_id)) ||
        r.canal !== "telephone" || !instantM1Valide(r.ouvert_le) || !entier(r.nombre_sources) || r.nombre_sources === 0 ||
        !ferme(r.derniere_source, ["ligne_id", "statut", "recu_le"]) || !hash(r.derniere_source.ligne_id) ||
        !["manque", "voicemail"].includes(r.derniere_source.statut as string) || !instantM1Valide(r.derniere_source.recu_le) || !lireSuiviRappelM1(r.suivi_rappel)) return null;
      precedent = r.transfert_id;
    }
    if (v.page.apres_suivant !== (v.page.reste ? precedent : null)) return null;
    return v as unknown as PageRappelsM1;
  });
}
/** Instant strict converti à la microseconde : les fractions restent exactes, aucun Date.parse. */
function microsecondes(v: string): bigint | null {
  if (!instantM1Valide(v)) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(v)!;
  const d = new Date(0); d.setUTCFullYear(Number(m[1]), Number(m[2]) - 1, Number(m[3])); d.setUTCHours(Number(m[4]), Number(m[5]), Number(m[6]), 0);
  const offset = m[8] === "Z" ? 0 : (Number(m[10]) * 60 + Number(m[11])) * (m[9] === "-" ? -1 : 1);
  return BigInt(d.getTime() - offset * 60000) * 1000n + BigInt((m[7] ?? "").padEnd(6, "0"));
}
function ack(v: unknown, a: ArgumentsPriseRappelM1, m: MetaLocalePriseRappelM1): v is AckPriseRappelM1 {
  if (!ferme(v, ["version", "transfert_id", "action", "ligne_id", "precedent_ligne_id", "index", "snapshot_attendu", "par", "role", "voie", "appareil", "intention_uuid", "recu_le_serveur", "horodatage_appareil", "suivi_rappel"]) ||
    v.version !== 1 || v.transfert_id !== a.transfert_id || v.action !== "prise_en_charge" || !hash(v.ligne_id) || !entier(v.index, 9999) ||
    (v.index === 0 ? v.precedent_ligne_id !== null : !hash(v.precedent_ligne_id)) || v.snapshot_attendu !== a.snapshot_attendu ||
    v.par !== m.par || v.role !== "admin" || v.voie !== "appareil" || v.appareil !== m.appareil || v.intention_uuid !== m.intention_uuid ||
    !instantM1Valide(v.recu_le_serveur) || !instantM1Valide(v.horodatage_appareil) || microsecondes(v.horodatage_appareil) !== microsecondes(m.horodatage_appareil)) return false;
  const suivi = lireSuiviRappelM1(v.suivi_rappel);
  return !!suivi && suivi.responsable === m.par && suivi.role === "admin" && suivi.pris_en_charge_le === v.recu_le_serveur &&
    suivi.tentatives_sans_contact === 0 && suivi.derniere_tentative_le === null && suivi.prochaine_tentative_le === null;
}
export function lirePriseRappelM1(brut: unknown, args: unknown, metaLocale: unknown): Reponse<AckPriseRappelM1> {
  const a = copierJsonLecture(args), m = copierJsonLecture(metaLocale);
  if (!argsPrise(a) || !ferme(m, ["intention_uuid", "par", "appareil", "horodatage_appareil"]) || !uuid(m.intention_uuid) ||
    !texte(m.par) || !texte(m.appareil) || !instantM1Valide(m.horodatage_appareil)) return illisible();
  return ouvrir(brut, v => ack(v, a, m as unknown as MetaLocalePriseRappelM1) ? v : null);
}
const LOCAL = "_rappel_local";
interface Locale { readonly personne: string; readonly appareil_id: string; readonly url_base: string }
function destination(v: unknown): v is Locale {
  if (!ferme(v, ["personne", "appareil_id", "url_base"]) || !texte(v.personne) || !texte(v.appareil_id) || typeof v.url_base !== "string") return false;
  try { const u = new URL(v.url_base); return ["http:", "https:"].includes(u.protocol) && !u.username && !u.password && !u.search && !u.hash; } catch { return false; }
}
export function creerMutationPriseRappelM1(args: ArgumentsPriseRappelM1, genererId: () => string, horloge: HorlogeAppareil, cible: DestinationPriseRappelM1): MutationOutbox {
  const a = figerArgumentsPriseRappelM1(args), c = copierJsonLecture(cible);
  const local = objet(c) ? { personne: c.personne, appareil_id: c.appareilId, url_base: c.urlBase } : null;
  if (!a || !destination(local) || !Number.isFinite(horloge.maintenant.getTime()) || !Number.isInteger(horloge.decalageMinutesUTC) || Math.abs(horloge.decalageMinutesUTC) >= 1440) throw new Error("Intention de rappel invalide.");
  const m = creerMutation({ type: "prise_en_charge_rappel", chantierId: `rappel:${a.transfert_id}`, payload: { ...a, [LOCAL]: local } }, genererId, horloge);
  if (!uuid(m.id) || !instantM1Valide(m.createdAtLocal)) throw new Error("Identifiant ou heure d'intention invalide."); return soumettreMutation(m);
}
function charge(m: MutationOutbox): { args: ArgumentsPriseRappelM1; locale: Locale; meta: MetaLocalePriseRappelM1 } | null {
  const c = copierJsonLecture(m);
  if (!objet(c) || c.type !== "prise_en_charge_rappel" || !objet(c.payload) || !uuid(c.id) || !instantM1Valide(c.createdAtLocal)) return null;
  const { [LOCAL]: locale, ...args } = c.payload;
  if (!destination(locale) || !argsPrise(args) || c.chantierId !== `rappel:${args.transfert_id}` || c.proprietaire !== locale.personne) return null;
  return { args, locale, meta: { intention_uuid: c.id, par: locale.personne, appareil: locale.appareil_id, horodatage_appareil: c.createdAtLocal } };
}
export function argumentsRpcPriseRappelM1(m: MutationOutbox): Readonly<Record<string, unknown>> | null { const c = charge(m); return c ? { ...c.args } : null; }
export function verifierDestinationPriseRappelM1(m: MutationOutbox, session: DestinationPriseRappelM1): boolean {
  const c = charge(m), s = copierJsonLecture(session);
  return !!c && objet(s) && c.locale.personne === s.personne && c.locale.appareil_id === s.appareilId && c.locale.url_base === s.urlBase;
}
const inconnu: InterpretationResultatMetier = { accepte: false, verdict: { code: "accuse_invalide", detail: "Confirmation inconnue : même intention de prise en charge conservée." } };
export function interpreterPriseRappelM1(brut: unknown, mutation?: MutationOutbox): InterpretationResultatMetier {
  const c = mutation && charge(mutation), r = copierJsonLecture(brut); if (!c || !objet(r) || r.ok !== true) return inconnu;
  if (ferme(r, ["ok", "resultat", ...(Object.hasOwn(r, "rejoue") ? ["rejoue"] : [])]) && (!Object.hasOwn(r, "rejoue") || typeof r.rejoue === "boolean") &&
    ferme(r.resultat, ["accepte", "verdict"]) && r.resultat.accepte === false && ferme(r.resultat.verdict, ["code", "detail"])) {
    const v = r.resultat.verdict;
    if (typeof v.code === "string" && /^REJ-M1-RAPPEL-[A-Z0-9]+(?:-[A-Z0-9]+)*$/.test(v.code) && v.code !== "REJ-M1-RAPPEL-IDENTITE-INVALIDE" && typeof v.detail === "string")
      return { accepte: false, verdict: { code: v.code, detail: v.detail } };
    return inconnu;
  }
  const lu = lirePriseRappelM1(r, c.args, c.meta); return lu.ok ? { accepte: true, resume: lu.value } : inconnu;
}
export function validerRecuPriseRappelM1(m: MutationOutbox): boolean {
  return m.statut === "envoyee" && interpreterPriseRappelM1({ ok: true, resultat: { accepte: true, resultat: m.resumeAccepte } }, m).accepte;
}
