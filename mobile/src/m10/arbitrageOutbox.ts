import { sha256 } from "@noble/hashes/sha2.js";
import { utf8ToBytes } from "@noble/hashes/utils.js";
import { encoderHex } from "../appairage/base64url";
import { creerMutation, formaterHorodatageLocal, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox, StatutMutation } from "../outbox/types";
import type { VerdictServeur } from "../outbox/vidangeur";
import type { StatutRevisionM10 } from "./contrat";

export type ChoixArbitrageMemoire = Exclude<StatutRevisionM10, null>;
export interface AccuseArbitrageMemoire {
  readonly type_entree: "revision_signalee"; readonly horodatage: string;
  readonly ligne_id_a: null; readonly ligne_id_b: null; readonly statut: ChoixArbitrageMemoire;
  readonly revision_ligne_id: string; readonly par: string; readonly role: "admin";
  readonly source_decision: "appareil"; readonly ligne_id: string; readonly precedent_ligne_id: string;
}
export type InterpretationArbitrageMemoire =
  | { readonly accepte: true; readonly resume: AccuseArbitrageMemoire }
  | { readonly accepte: false; readonly verdict: VerdictServeur };
export interface ArbitrageMemoireEnFile {
  readonly id: string; readonly revisionId: string | null; readonly statut: StatutMutation;
  readonly personne: string | null; readonly choix: ChoixArbitrageMemoire | null;
}
const HASH = /^[0-9a-f]{64}$/;
const hash = (v: unknown): v is string => typeof v === "string" && HASH.test(v);
const personne = (v: unknown): v is string => typeof v === "string" && /^[a-z][a-z0-9_.-]{1,63}$/.test(v);
const choix = (v: unknown): v is ChoixArbitrageMemoire => v === "en_attente" || v === "distincts_confirmes" || v === "obsolete_marquee" || v === "indetermine";
const ferme = (v: Record<string, unknown>, cles: readonly string[]) => Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
function objet(v: unknown): Record<string, unknown> | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  try {
    const proto = Object.getPrototypeOf(v);
    if (proto !== Object.prototype && proto !== null) {
      // Response.json natif peut appartenir à un autre realm ; seul Object terminal est admis.
      if (Object.getPrototypeOf(proto) !== null) return null;
      const c = Object.getOwnPropertyDescriptor(proto, "constructor");
      if (!c || !("value" in c) || typeof c.value !== "function" || Object.getOwnPropertyDescriptor(c.value, "name")?.value !== "Object") return null;
    }
    if (Reflect.ownKeys(v).some(k => typeof k !== "string")) return null;
    const r: Record<string, unknown> = Object.create(null);
    for (const [k, d] of Object.entries(Object.getOwnPropertyDescriptors(v))) {
      if (!("value" in d)) return null;
      r[k] = d.value;
    }
    return r;
  } catch { return null; }
}
function instant(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-](\d{2}):(\d{2}))$/.exec(v);
  if (!m) return false;
  const an = Number(m[1]), mois = Number(m[2]), jour = Number(m[3]);
  const jours = [31, an % 4 === 0 && (an % 100 !== 0 || an % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return an > 0 && mois >= 1 && mois <= 12 && jour >= 1 && jour <= jours[mois - 1] && Number(m[4]) < 24 && Number(m[5]) < 60 && Number(m[6]) < 60 &&
    (m[8] === undefined || (Number(m[8]) < 24 && Number(m[9]) < 60));
}
export function creerMutationArbitrageMemoire(revisionId: string, statut: ChoixArbitrageMemoire, genererId: () => string, horloge: HorlogeAppareil): MutationOutbox {
  if (!hash(revisionId) || !choix(statut) || !Number.isFinite(horloge.maintenant.getTime()) ||
    !Number.isInteger(horloge.decalageMinutesUTC) || Math.abs(horloge.decalageMinutesUTC) >= 1440) throw new Error("Révision, statut ou horloge invalide : aucune intention créée.");
  const horodatage = formaterHorodatageLocal(horloge);
  if (!instant(horodatage)) throw new Error("Horodatage local invalide : aucune intention créée.");
  const m = creerMutation({ type: "memory_revision_arbitration", chantierId: `memoire_revision:${revisionId}`,
    payload: { revision_ligne_id: revisionId, statut, horodatage } }, genererId, horloge);
  if (typeof m.id !== "string" || m.id.trim() === "") throw new Error("Identifiant d’intention vide.");
  return soumettreMutation(m);
}
export function construireArgumentsArbitrageMemoire(m: MutationOutbox): Record<string, unknown> | null {
  const p = objet(m.payload);
  if (m.type !== "memory_revision_arbitration" || !p || !ferme(p, ["revision_ligne_id", "statut", "horodatage"]) ||
    !hash(p.revision_ligne_id) || !choix(p.statut) || !instant(p.horodatage) || p.horodatage !== m.createdAtLocal ||
    m.chantierId !== `memoire_revision:${p.revision_ligne_id}`) return null;
  return { revision_ligne_id: p.revision_ligne_id, statut: p.statut, horodatage: p.horodatage };
}
export function arbitragesMemoireEnFile(rows: readonly MutationOutbox[]): readonly ArbitrageMemoireEnFile[] {
  return rows.filter(m => m.type === "memory_revision_arbitration").map(m => {
    const p = objet(m.payload), suffixe = typeof m.chantierId === "string" && m.chantierId.startsWith("memoire_revision:") ? m.chantierId.slice("memoire_revision:".length) : null;
    return { id: m.id, revisionId: hash(suffixe) ? suffixe : null, statut: m.statut,
      personne: typeof m.proprietaire === "string" && m.proprietaire !== "" ? m.proprietaire : null,
      choix: p && choix(p.statut) ? p.statut : null };
  });
}
const INVALIDE: InterpretationArbitrageMemoire = { accepte: false, verdict: {
  code: "accuse_invalide", detail: "Arbitrage non confirmé : conserver la même intention et sa clé." } };
const REFUS = new Set(["REJ-REVISION-LIGNES-IDENTIQUES", "REJ-REVISION-LIGNE-INTROUVABLE", "REJ-REVISION-STATUT-INCONNU", "REJ-REVISION-SIGNALEMENT-INTROUVABLE",
  "REJ-HUMAIN-REQUIS", "REJ-HUMAIN-IDENTITE-INVALIDE", "REJ-HUMAIN-ROLE-INSUFFISANT", "REJ-HUMAIN-ACTEUR-INVALIDE", "REJ-HUMAIN-MOTIF-INVALIDE", "REJ-HUMAIN-HORODATAGE-INVALIDE", "REJ-IDENTITE-APPAREIL-INVALIDE"]);
const TECHNIQUES = new Set(["arguments_invalides", "mutation_conflit", "refus_metier", "hors_portee_role"]);
function detailsNatifs(v: unknown): string | null {
  if (v === undefined) return "";
  if (typeof v === "string") return v;
  if (!Array.isArray(v)) return null;
  try {
    const ds = Object.getOwnPropertyDescriptors(v), taille: unknown = Object.getOwnPropertyDescriptor(v, "length")?.value;
    if (typeof taille !== "number" || !Number.isSafeInteger(taille) || taille < 0 ||
      Reflect.ownKeys(v).length !== taille + 1) return null;
    const morceaux: string[] = [];
    for (let i = 0; i < taille; i++) {
      const d = Object.hasOwn(ds, String(i)) ? ds[String(i)] : null;
      if (!d || !("value" in d) || typeof d.value !== "string") return null;
      morceaux.push(d.value);
    }
    return morceaux.join(" ; ");
  } catch { return null; }
}
/** Port borné d’encodage.py : neuf clés/valeurs ASCII (ou null), jamais un encodeur Python général. */
function empreinteRecu(v: AccuseArbitrageMemoire): string {
  const corps = { type_entree: v.type_entree, horodatage: v.horodatage,
    ligne_id_a: v.ligne_id_a, ligne_id_b: v.ligne_id_b, statut: v.statut,
    revision_ligne_id: v.revision_ligne_id, par: v.par, role: v.role, source_decision: v.source_decision };
  const normalise = ["__dict__", Object.keys(corps).sort().map(k => [k, Object.getOwnPropertyDescriptor(corps, k)?.value])];
  const texte = JSON.stringify(normalise), precedent = JSON.stringify(v.precedent_ligne_id);
  // Tous les champs validés sont ASCII : longueur JS == longueur Python ensure_ascii=True.
  return encoderHex(sha256(utf8ToBytes(`${texte.length}:${texte}${precedent.length}:${precedent}`)));
}
export function interpreterArbitrageMemoire(brut: unknown, m?: MutationOutbox): InterpretationArbitrageMemoire {
  const args = m && construireArgumentsArbitrageMemoire(m);
  if (!m || !args || !personne(m.proprietaire)) return INVALIDE;
  const r = objet(brut); if (!r || r.tronque === true) return INVALIDE;
  if (r.ok === false) {
    const detail = detailsNatifs(r.details);
    return typeof r.erreur === "string" && TECHNIQUES.has(r.erreur) && detail !== null
      ? { accepte: false, verdict: { code: r.erreur, detail } } : INVALIDE;
  }
  if (r.ok !== true) return INVALIDE;
  const metier = objet(r.resultat); if (!metier) return INVALIDE;
  if (metier.accepte === false) {
    if (typeof metier.verdict === "string" && REFUS.has(metier.verdict)) return { accepte: false, verdict: { code: metier.verdict, detail: "" } };
    const v = objet(metier.verdict);
    return v && ferme(v, ["code", "detail"]) && typeof v.code === "string" && REFUS.has(v.code) && typeof v.detail === "string"
      ? { accepte: false, verdict: { code: v.code, detail: v.detail } } : INVALIDE;
  }
  const v = objet(metier.resultat);
  if (metier.accepte !== true || !v || !ferme(v, ["type_entree", "horodatage", "ligne_id_a", "ligne_id_b", "statut", "revision_ligne_id", "par", "role", "source_decision", "ligne_id", "precedent_ligne_id"]) ||
    v.type_entree !== "revision_signalee" || !instant(v.horodatage) || v.ligne_id_a !== null || v.ligne_id_b !== null ||
    !choix(v.statut) || v.statut !== args.statut || !hash(v.revision_ligne_id) || v.revision_ligne_id !== args.revision_ligne_id ||
    v.par !== m.proprietaire || v.role !== "admin" || v.source_decision !== "appareil" || !hash(v.ligne_id) || !hash(v.precedent_ligne_id)) return INVALIDE;
  const resume: AccuseArbitrageMemoire = { type_entree: "revision_signalee", horodatage: v.horodatage, ligne_id_a: null, ligne_id_b: null,
    statut: v.statut, revision_ligne_id: v.revision_ligne_id, par: m.proprietaire, role: "admin", source_decision: "appareil",
    ligne_id: v.ligne_id, precedent_ligne_id: v.precedent_ligne_id };
  return empreinteRecu(resume) === resume.ligne_id ? { accepte: true, resume } : INVALIDE;
}
