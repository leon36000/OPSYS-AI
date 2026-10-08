import { ouvrirEnveloppe } from "../admin/enveloppe";
import type { Reponse } from "../m7/contrat";
import { horodatageM10Valide, lireProjectionRevisionM10, lireReferenceM10 } from "./contrat";
import { prototypeJsonValide } from "./json";
import type { LigneRevisionM10, ReferenceM10 } from "./contrat";

export type JsonMetier = null | boolean | number | string | readonly JsonMetier[] | { readonly [cle: string]: JsonMetier };
export interface FaitRevisionM10 {
  readonly reference: ReferenceM10;
  readonly type_entree: "decision_enregistree" | "evenement_memorise" | "fait_consolide" | "fait_candidat" | "provenance_documentaire";
  readonly horodatage: string;
  readonly champs: { readonly [cle: string]: JsonMetier };
}
export interface DossierRevisionM10 {
  readonly revision: LigneRevisionM10;
  readonly faits: readonly [FaitRevisionM10, FaitRevisionM10];
}
const INVALIDE = Symbol("dossier_invalide");
const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const ferme = (v: Record<string, unknown>, ks: readonly string[]) => Object.keys(v).length === ks.length && ks.every(k => Object.hasOwn(v, k));
const illisible = (): Reponse<DossierRevisionM10> => ({ ok: false, code: "reponse_illisible", detail: "Dossier de comparaison illisible." });

/** Les objets JSON sont copiés avant toute lecture ; leurs données ne deviennent jamais du code. */
function copier(v: unknown, profondeur: number, vus = new Set<object>()): JsonMetier | typeof INVALIDE {
  if (profondeur < 0) return INVALIDE;
  if (v === null || typeof v === "string" || typeof v === "boolean") return v;
  if (typeof v === "number") return Number.isFinite(v) && (!Number.isInteger(v) || Number.isSafeInteger(v)) ? v : INVALIDE;
  if (typeof v !== "object" || vus.has(v)) return INVALIDE;
  try {
    vus.add(v);
    if (!prototypeJsonValide(v)) return INVALIDE;
    if (Reflect.ownKeys(v).some(k => typeof k !== "string")) return INVALIDE;
    const ds = Object.getOwnPropertyDescriptors(v);
    if (Array.isArray(v)) {
      const n: unknown = ds.length?.value;
      if (typeof n !== "number" || !Number.isSafeInteger(n) || n < 0 || Object.keys(ds).length !== n + 1) return INVALIDE;
      const r: JsonMetier[] = [];
      for (let i = 0; i < n; i++) {
        const d = Object.hasOwn(ds, String(i)) ? ds[String(i)] : null;
        if (!d || !("value" in d)) return INVALIDE;
        const c = copier(d.value, profondeur - 1, vus); if (c === INVALIDE) return INVALIDE; r.push(c);
      }
      return r;
    }
    const r: Record<string, JsonMetier> = Object.create(null);
    for (const [k, d] of Object.entries(ds)) {
      if (!("value" in d)) return INVALIDE;
      const c = copier(d.value, profondeur - 1, vus); if (c === INVALIDE) return INVALIDE; r[k] = c;
    }
    return r;
  } catch { return INVALIDE; } finally { vus.delete(v); }
}
function fait(v: unknown): FaitRevisionM10 | undefined {
  if (!objet(v) || !ferme(v, ["reference", "type_entree", "horodatage", "champs"]) || !horodatageM10Valide(v.horodatage) || !objet(v.champs)) return undefined;
  const r = lireReferenceM10(v.reference);
  const type = v.type_entree;
  if (!r || (type !== "decision_enregistree" && type !== "evenement_memorise" && type !== "fait_consolide" && type !== "fait_candidat" && type !== "provenance_documentaire")) return undefined;
  const champBrut = v.champs;
  if (["ligne_id", "precedent_ligne_id", "confidentialite", "type_entree", "horodatage"].some(k => Object.hasOwn(champBrut, k))) return undefined;
  const champs = copier(champBrut, 8);
  return champs !== INVALIDE && objet(champs) ? { reference: r, type_entree: type, horodatage: v.horodatage, champs } : undefined;
}
export function lireDossierRevisionM10(brut: unknown, revisionId?: string): Reponse<DossierRevisionM10> {
  const copie = copier(brut, 16);
  if (copie === INVALIDE) return illisible();
  const ouverte = ouvrirEnveloppe(copie, "couple");
  if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  const v = ouverte.valeur;
  if (!objet(v) || !ferme(v, ["revision", "faits"]) || !Array.isArray(v.faits) || v.faits.length !== 2) return illisible();
  const revision = lireProjectionRevisionM10(v.revision), a = fait(v.faits[0]), b = fait(v.faits[1]);
  if (!revision || !a || !b || (revisionId !== undefined && revision.revision_ligne_id !== revisionId) ||
    a.reference.ligne_id !== revision.reference_a.ligne_id || b.reference.ligne_id !== revision.reference_b.ligne_id) return illisible();
  return { ok: true, value: { revision, faits: [a, b] } };
}
