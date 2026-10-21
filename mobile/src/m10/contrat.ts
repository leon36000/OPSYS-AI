import { ouvrirEnveloppe, type FormeReponse } from "../admin/enveloppe";
import type { Reponse } from "../m7/contrat";
import { prototypeJsonValide } from "./json";

export type StatutDecisionM10 = "proposee" | "validee" | "remplacee" | "annulee" | "indetermine" | null;
export type StatutRevisionM10 = "en_attente" | "distincts_confirmes" | "obsolete_marquee" | "indetermine" | null;
export interface SignalM10 {
  readonly signal_id: string; readonly affaire_id: string | null; readonly horodatage: string;
  readonly etat: "ouvert" | "pris_en_compte" | "clos";
  readonly traite_par: string | null; readonly traite_le: string | null; readonly motif: string | null;
}
export interface VueSignauxM10 {
  readonly signaux: readonly SignalM10[]; readonly nb_total: number; readonly nb_omis: number;
  readonly nb_ouverts: number; readonly nb_pris_en_compte: number; readonly nb_clos: number;
}
export interface ReferenceM10 { readonly registre: "affaires"; readonly ligne_id: string; readonly hash_tete: string }
export interface LigneDecisionM10 {
  readonly genre: "decision"; readonly decision_id: string; readonly statut: Exclude<StatutDecisionM10, null>;
  readonly horodatage: string; readonly reference: ReferenceM10;
}
export interface LigneRevisionM10 {
  readonly genre: "revision"; readonly revision_ligne_id: string; readonly statut: Exclude<StatutRevisionM10, null>;
  readonly signalee_le: string; readonly statut_le: string; readonly reference: ReferenceM10;
  readonly reference_statut: ReferenceM10; readonly reference_a: ReferenceM10; readonly reference_b: ReferenceM10;
}
export interface CatalogueM10 {
  readonly decisions: readonly LigneDecisionM10[]; readonly revisions: readonly LigneRevisionM10[];
  readonly decalage: number; readonly suivant: number | null; readonly reste: number; readonly total: number;
  readonly affichees: number; readonly limite: number; readonly borne_caracteres: 5400; readonly taille_caracteres: number;
  readonly confidentialite: { readonly regle: "v1"; readonly nb_retenus: number };
}
const INVALIDE = Symbol("json_invalide");
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const id = (v: unknown): v is string => typeof v === "string" && v.trim() !== "" &&
  Array.from(v).length <= 256 && !/[\p{Cc}\p{Cs}]/u.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const ferme = (v: Record<string, unknown>, cles: readonly string[]) => Object.keys(v).length === cles.length &&
  cles.every(c => Object.hasOwn(v, c));

/** Snapshot JSON propre : aucun accesseur, héritage, trou de tableau ou entier unsafe n'est lu. */
function copier(v: unknown, vus = new Set<object>()): unknown {
  if (v === null || typeof v === "string" || typeof v === "boolean") return v;
  if (typeof v === "number") return Number.isSafeInteger(v) ? v : INVALIDE;
  if (typeof v !== "object" || vus.has(v)) return INVALIDE;
  try {
    vus.add(v);
    const tableau = Array.isArray(v);
    if (!prototypeJsonValide(v)) return INVALIDE;
    if (Reflect.ownKeys(v).some(c => typeof c !== "string")) return INVALIDE;
    const ds = Object.getOwnPropertyDescriptors(v);
    if (tableau) {
      const longueur: unknown = ds.length?.value;
      if (!entier(longueur) || Object.keys(ds).length !== longueur + 1) return INVALIDE;
      const r: unknown[] = [];
      for (let i = 0; i < longueur; i++) {
        const d = Object.hasOwn(ds, String(i)) ? ds[String(i)] : null;
        if (!d || !("value" in d)) return INVALIDE;
        const c = copier(d.value, vus); if (c === INVALIDE) return INVALIDE; r.push(c);
      }
      return r;
    }
    const r: Record<string, unknown> = Object.create(null);
    for (const [k, d] of Object.entries(ds)) {
      if (!("value" in d)) return INVALIDE;
      const c = copier(d.value, vus); if (c === INVALIDE) return INVALIDE; r[k] = c;
    }
    return r;
  } catch { return INVALIDE; } finally { vus.delete(v); }
}
function date(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,]\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(v);
  if (!m) return false;
  const an = Number(m[1]), mois = Number(m[2]), jour = Number(m[3]);
  const jours = [31, an % 4 === 0 && (an % 100 !== 0 || an % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return an > 0 && mois >= 1 && mois <= 12 && jour >= 1 && jour <= jours[mois - 1] &&
    Number(m[4]) < 24 && Number(m[5]) < 60 && Number(m[6]) < 60 &&
    (m[7] === undefined || (Number(m[7]) < 24 && Number(m[8]) < 60));
}
function decision(v: unknown): v is Exclude<StatutDecisionM10, null> {
  return v === "proposee" || v === "validee" || v === "remplacee" || v === "annulee" || v === "indetermine";
}
function revision(v: unknown): v is Exclude<StatutRevisionM10, null> {
  return v === "en_attente" || v === "distincts_confirmes" || v === "obsolete_marquee" || v === "indetermine";
}
function illisible<T>(): Reponse<T> {
  return { ok: false, code: "reponse_illisible", detail: "Réponse mémoire illisible : aucune référence partielle affichée." };
}
function lire<T>(brut: unknown, forme: FormeReponse, parser: (v: unknown) => T | undefined): Reponse<T> {
  const copie = copier(brut); if (copie === INVALIDE) return illisible();
  // Le helper commun sait construire des refus de secours ; ces quatre contrats exigent
  // le verdict natif, sans inventer code ou détail pour une réponse mal formée.
  const metier = objet(copie) && objet(copie.resultat) ? copie.resultat : null;
  if (metier?.accepte === false) {
    const verdict = metier.verdict;
    if (!objet(verdict) || !ferme(verdict, ["code", "detail"]) || !id(verdict.code) ||
      typeof verdict.detail !== "string") return illisible();
  }
  const ouverte = ouvrirEnveloppe(copie, forme);
  if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  const value = parser(ouverte.valeur);
  return value === undefined ? illisible() : { ok: true, value };
}
function signal(v: unknown): SignalM10 | undefined {
  if (!objet(v) || !ferme(v, ["signal_id", "affaire_id", "horodatage", "etat", "traite_par", "traite_le", "motif"]) ||
    !id(v.signal_id) || !(v.affaire_id === null || id(v.affaire_id)) || !date(v.horodatage) ||
    (v.etat !== "ouvert" && v.etat !== "pris_en_compte" && v.etat !== "clos")) return undefined;
  if (v.etat === "ouvert") {
    if (v.traite_par !== null || v.traite_le !== null || v.motif !== null) return undefined;
    return { signal_id: v.signal_id, affaire_id: v.affaire_id, horodatage: v.horodatage,
      etat: v.etat, traite_par: null, traite_le: null, motif: null };
  }
  if (!id(v.traite_par) || !date(v.traite_le) || typeof v.motif !== "string" ||
    Array.from(v.motif.trim()).length < 10 || Array.from(v.motif.trim()).length > 500) return undefined;
  return { signal_id: v.signal_id, affaire_id: v.affaire_id, horodatage: v.horodatage,
    etat: v.etat, traite_par: v.traite_par, traite_le: v.traite_le, motif: v.motif };
}
export function lireSignauxM10(brut: unknown): Reponse<VueSignauxM10> {
  return lire(brut, "directe", v => {
    if (!objet(v) || !ferme(v, ["signaux", "nb_total", "nb_omis", "nb_ouverts", "nb_pris_en_compte", "nb_clos"]) ||
      !Array.isArray(v.signaux) || v.signaux.length > 50 || !entier(v.nb_total) || !entier(v.nb_omis) ||
      !entier(v.nb_ouverts) || !entier(v.nb_pris_en_compte) || !entier(v.nb_clos) ||
      v.nb_ouverts + v.nb_pris_en_compte + v.nb_clos !== v.nb_total || v.nb_total - v.signaux.length !== v.nb_omis) return undefined;
    const signaux: SignalM10[] = [], ids = new Set<string>();
    for (const raw of v.signaux) {
      const lu = signal(raw); if (!lu || ids.has(lu.signal_id)) return undefined;
      ids.add(lu.signal_id); signaux.push(lu);
    }
    if (signaux.filter(s => s.etat === "ouvert").length > v.nb_ouverts ||
      signaux.filter(s => s.etat === "pris_en_compte").length > v.nb_pris_en_compte ||
      signaux.filter(s => s.etat === "clos").length > v.nb_clos) return undefined;
    return { signaux, nb_total: v.nb_total, nb_omis: v.nb_omis, nb_ouverts: v.nb_ouverts,
      nb_pris_en_compte: v.nb_pris_en_compte, nb_clos: v.nb_clos };
  });
}
export function lireStatutDecisionM10(brut: unknown): Reponse<{ readonly statut: StatutDecisionM10 }> {
  return lire(brut, "directe", v => objet(v) && ferme(v, ["statut"]) && (v.statut === null || decision(v.statut))
    ? { statut: v.statut } : undefined);
}
export function lireStatutRevisionM10(brut: unknown): Reponse<{ readonly statut: StatutRevisionM10 }> {
  return lire(brut, "directe", v => objet(v) && ferme(v, ["statut"]) && (v.statut === null || revision(v.statut))
    ? { statut: v.statut } : undefined);
}
function reference(v: unknown): ReferenceM10 | undefined {
  return objet(v) && ferme(v, ["registre", "ligne_id", "hash_tete"]) && v.registre === "affaires" &&
    hash(v.ligne_id) && v.hash_tete === v.ligne_id ? { registre: v.registre, ligne_id: v.ligne_id, hash_tete: v.ligne_id } : undefined;
}
function ligneDecision(v: unknown): LigneDecisionM10 | undefined {
  if (!objet(v) || !ferme(v, ["genre", "decision_id", "statut", "horodatage", "reference"]) ||
    v.genre !== "decision" || !id(v.decision_id) || !decision(v.statut) || !date(v.horodatage)) return undefined;
  const r = reference(v.reference); return r ? { genre: v.genre, decision_id: v.decision_id,
    statut: v.statut, horodatage: v.horodatage, reference: r } : undefined;
}
function ligneRevision(v: unknown): LigneRevisionM10 | undefined {
  if (!objet(v) || !ferme(v, ["genre", "revision_ligne_id", "statut", "signalee_le", "statut_le", "reference", "reference_statut", "reference_a", "reference_b"]) ||
    v.genre !== "revision" || !hash(v.revision_ligne_id) || !revision(v.statut) || !date(v.signalee_le) || !date(v.statut_le)) return undefined;
  const r = reference(v.reference), s = reference(v.reference_statut), a = reference(v.reference_a), b = reference(v.reference_b);
  if (!r || !s || !a || !b || r.ligne_id !== v.revision_ligne_id || a.ligne_id === b.ligne_id ||
    r.ligne_id === a.ligne_id || r.ligne_id === b.ligne_id || s.ligne_id === a.ligne_id || s.ligne_id === b.ligne_id ||
    (s.ligne_id === r.ligne_id && (v.statut !== "en_attente" || v.statut_le !== v.signalee_le))) return undefined;
  return { genre: v.genre, revision_ligne_id: v.revision_ligne_id, statut: v.statut, signalee_le: v.signalee_le,
    statut_le: v.statut_le, reference: r, reference_statut: s, reference_a: a, reference_b: b };
}

/** Réutilisation des projections natives dans le dossier de comparaison, sans fabriquer une page. */
export function lireProjectionRevisionM10(brut: unknown): LigneRevisionM10 | undefined {
  const v = copier(brut); return v === INVALIDE ? undefined : ligneRevision(v);
}
export function lireReferenceM10(brut: unknown): ReferenceM10 | undefined {
  const v = copier(brut); return v === INVALIDE ? undefined : reference(v);
}
export const horodatageM10Valide = date;
export function lireReferencesM10(brut: unknown): Reponse<CatalogueM10> {
  return lire(brut, "couple", v => {
    if (!objet(v) || !ferme(v, ["decisions", "revisions", "decalage", "suivant", "reste", "total", "affichees", "limite", "borne_caracteres", "taille_caracteres", "confidentialite"]) ||
      !Array.isArray(v.decisions) || !Array.isArray(v.revisions) || !entier(v.decalage) || !entier(v.reste) || !entier(v.total) ||
      !entier(v.affichees) || !entier(v.limite) || v.limite < 1 || v.limite > 8 || v.borne_caracteres !== 5400 ||
      !entier(v.taille_caracteres) || v.taille_caracteres < 1 || v.taille_caracteres > 5400 ||
      !objet(v.confidentialite) || !ferme(v.confidentialite, ["regle", "nb_retenus"]) ||
      v.confidentialite.regle !== "v1" || !entier(v.confidentialite.nb_retenus) ||
      v.decisions.length + v.revisions.length !== v.affichees || v.affichees > v.limite ||
      v.affichees > Math.max(0, v.total - v.decalage) || v.reste !== Math.max(0, v.total - v.decalage - v.affichees) ||
      (v.reste === 0 ? v.suivant !== null : !entier(v.suivant) || v.affichees === 0 || v.suivant !== v.decalage + v.affichees)) return undefined;
    const decisions: LigneDecisionM10[] = [], revisions: LigneRevisionM10[] = [], ids = new Set<string>();
    for (const raw of v.decisions) {
      const lu = ligneDecision(raw); if (!lu || ids.has(`decision:${lu.decision_id}`)) return undefined;
      ids.add(`decision:${lu.decision_id}`); decisions.push(lu);
    }
    for (const raw of v.revisions) {
      const lu = ligneRevision(raw); if (!lu || ids.has(`revision:${lu.revision_ligne_id}`)) return undefined;
      ids.add(`revision:${lu.revision_ligne_id}`); revisions.push(lu);
    }
    return { decisions, revisions, decalage: v.decalage, suivant: entier(v.suivant) ? v.suivant : null,
      reste: v.reste, total: v.total, affichees: v.affichees, limite: v.limite, borne_caracteres: 5400,
      taille_caracteres: v.taille_caracteres, confidentialite: { regle: "v1", nb_retenus: v.confidentialite.nb_retenus } };
  });
}
