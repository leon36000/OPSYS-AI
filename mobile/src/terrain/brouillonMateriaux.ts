import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { LigneEnSaisie } from "../ecrans/materials";
import { TYPES_LIGNE_MATERIAUX } from "../m6/materiaux";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";

export interface CibleBrouillonMateriaux {
  readonly urlBase: string; readonly appareilId: string; readonly personne: string; readonly interventionId: string;
}
export interface BrouillonMateriaux {
  readonly wctId: string | null; readonly chantierId: string | null;
  /** Provenance des lignes importées, jamais autorisation ni cache de réponse serveur. */
  readonly sourcePrevu: string | null; readonly positionsImportees: readonly number[];
  readonly intentionId: string | null; readonly lignes: readonly LigneEnSaisie[];
}
export type LectureBrouillonMateriaux = { readonly genre: "absent" } | { readonly genre: "illisible" }
  | { readonly genre: "present"; readonly valeur: BrouillonMateriaux };
const PREFIXE = "brouillon.m6.v1:";
const estObjet = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const ferme = (v: unknown, cles: readonly string[]): v is Record<string, unknown> => estObjet(v) && Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
const texte = (v: unknown): v is string => typeof v === "string" && v.length <= 4096;
const nullable = (v: unknown): v is string | null => v === null || (texte(v) && v.length > 0);
function cle(c: CibleBrouillonMateriaux): string {
  if (![c.urlBase, c.appareilId, c.personne, c.interventionId].every(v => texte(v) && v.length > 0)) throw new Error("Cible de brouillon invalide.");
  return PREFIXE + [c.urlBase, c.appareilId, c.personne, c.interventionId].map(encodeURIComponent).join(":");
}
function ligne(v: unknown): v is LigneEnSaisie {
  return ferme(v, ["id", "typeLigne", "materiauId", "quantiteTexte", "unite", "quantiteEstimeeTexte", "photoFournie", "recuFourni"])
    && texte(v.id) && v.id.length > 0 && TYPES_LIGNE_MATERIAUX.some(t => t === v.typeLigne)
    && [v.materiauId, v.quantiteTexte, v.unite, v.quantiteEstimeeTexte].every(texte)
    && typeof v.photoFournie === "boolean" && typeof v.recuFourni === "boolean";
}
function valider(v: unknown): v is BrouillonMateriaux {
  return ferme(v, ["wctId", "chantierId", "sourcePrevu", "positionsImportees", "intentionId", "lignes"])
    && nullable(v.wctId) && nullable(v.chantierId) && nullable(v.intentionId)
    && (v.sourcePrevu === null || (typeof v.sourcePrevu === "string" && /^[0-9a-f]{64}$/.test(v.sourcePrevu)))
    && Array.isArray(v.positionsImportees) && v.positionsImportees.length <= 128
    && v.positionsImportees.every(x => typeof x === "number" && Number.isSafeInteger(x) && x >= 0 && x < 10000)
    && new Set(v.positionsImportees).size === v.positionsImportees.length
    && (v.sourcePrevu !== null || v.positionsImportees.length === 0)
    && Array.isArray(v.lignes) && v.lignes.length <= 128 && v.lignes.every(ligne)
    && new Set(v.lignes.map(l => l.id)).size === v.lignes.length;
}

/** Saisie brute inachevée conservée ; un contenu illisible n'est ni effacé ni remplacé. */
export async function lireBrouillonMateriaux(d: DepotCleValeur, cible: CibleBrouillonMateriaux): Promise<LectureBrouillonMateriaux> {
  try {
    const raw = await d.lire(cle(cible));
    if (raw === null) return { genre: "absent" };
    if (raw.length > 600000) return { genre: "illisible" };
    const v = copierJsonLecture(JSON.parse(raw));
    if (v === JSON_LECTURE_INVALIDE || !ferme(v, ["version", "cible", "brouillon"]) || v.version !== 1
      || !ferme(v.cible, ["urlBase", "appareilId", "personne", "interventionId"])) return { genre: "illisible" };
    const cibleSauvee = v.cible;
    if (Object.keys(cibleSauvee).some(k => cibleSauvee[k] !== Reflect.get(cible, k)) || !valider(v.brouillon)) return { genre: "illisible" };
    return { genre: "present", valeur: v.brouillon };
  } catch { return { genre: "illisible" }; }
}
const files = new WeakMap<DepotCleValeur, Map<string, Promise<void>>>();
/** Chaque clé possède sa file locale ; aucun jeton, DTO serveur ou envoi réseau. */
export async function sauverBrouillonMateriaux(d: DepotCleValeur, cible: CibleBrouillonMateriaux, brouillon: BrouillonMateriaux): Promise<void> {
  const b = copierJsonLecture(brouillon), c = copierJsonLecture(cible);
  if (b === JSON_LECTURE_INVALIDE || c === JSON_LECTURE_INVALIDE || !valider(b)
    || !ferme(c, ["urlBase", "appareilId", "personne", "interventionId"])) throw new Error("Brouillon de matériaux invalide.");
  const key = cle(c as unknown as CibleBrouillonMateriaux);
  const raw = JSON.stringify({ version: 1, cible: c, brouillon: b });
  if (raw.length > 600000) throw new Error("Brouillon de matériaux trop volumineux.");
  let queue = files.get(d); if (!queue) { queue = new Map(); files.set(d, queue); }
  const precedent = queue.get(key) ?? Promise.resolve();
  const ecriture = precedent.catch(() => undefined).then(() => d.ecrire(key, raw));
  queue.set(key, ecriture);
  try { await ecriture; } finally { if (queue.get(key) === ecriture) queue.delete(key); }
}
