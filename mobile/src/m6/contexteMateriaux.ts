import { ouvrirEnveloppe } from "../admin/enveloppe";
import { estObjet } from "../admin/lecteurs";
import { horodatageM10Valide } from "../m10/contrat";
import type { Reponse } from "../m7/contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
export type { Reponse } from "../m7/contrat";
export const OUTIL_CONTEXTE_MATERIAUX = "m6_lire_contexte_materiaux_appareil";
export interface ArgumentsContexteMateriauxM6 { readonly intervention_id: string; readonly wct_id: string; readonly decalage: number; readonly limite: number }
export interface WctContexteMateriauxM6 {
  readonly wct_id: string; readonly intervention_id: string; readonly devis_id: string | null;
  readonly horodatage_completion: string; readonly hash_maillon: string;
  readonly reference_bus: { readonly type: "m4.travaux_termines"; readonly evenement_id: string };
}
export interface SourcePrevuMateriauxM6 {
  readonly registre: "besoins_prevus"; readonly rang: number; readonly empreinte_snapshot: string;
  readonly estimation_id: string | null; readonly rang_m3: number | null; readonly bareme_version: string | null;
  readonly horodatage: string | null;
  readonly reference_m3: { readonly type: "m3.besoins_materiaux" | "m3.devis_accepte"; readonly evenement_id: string } | null;
}
export interface LignePrevueMateriauxM6 {
  readonly position_source: number; readonly materiau_id: string; readonly unite: string;
  readonly quantite_estimee: string; readonly origine_quantite: "texte_m3_verifie" | "nombre_m6_persiste";
}
export type ManqueContexteMateriauxM6 = "devis_absent" | "prevu_absent" | "chantier_source_absent" | "horodatage_prevu_absent" | "provenance_m3_absente";
export interface ContexteMateriauxM6 {
  readonly wct: WctContexteMateriauxM6;
  readonly chantier: { readonly chantier_id: string | null; readonly origine: "prevu_m6" | "intervention_employee" | "absent_admin" };
  readonly prevu: { readonly statut: "absent" | "definitif" | "provisoire_estimation_m3"; readonly source: SourcePrevuMateriauxM6 | null };
  readonly lignes: readonly LignePrevueMateriauxM6[];
  readonly pagination: { readonly decalage: number; readonly limite: number; readonly affichees: number; readonly total: number; readonly suivant: number | null; readonly reste: number; readonly courante: true };
  readonly manques: readonly ManqueContexteMateriauxM6[];
  readonly couverture: { readonly objet: "contexte_et_prevu_du_wct"; readonly quantite_reelle: "non_renseignee"; readonly pages: "courantes"; readonly plafond_lignes: 10000 };
  readonly borne_caracteres: 5400; readonly taille_caracteres: number;
}
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const sansControle = (v: string) => !/[\p{Cc}\p{Cs}]/u.test(v);
const id = (v: unknown): v is string => typeof v === "string" && v.length > 0 && !/^\p{White_Space}+$/u.test(v) && Array.from(v).length <= 256 && sansControle(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v) && v.length === 64;
const date = (v: unknown): v is string => typeof v === "string" && v.length <= 64 && sansControle(v) && horodatageM10Valide(v);
function ferme(v: unknown, cles: readonly string[]): v is Record<string, unknown> {
  return estObjet(v) && Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
}
function argsValides(v: unknown): v is ArgumentsContexteMateriauxM6 {
  return ferme(v, ["intervention_id", "wct_id", "decalage", "limite"]) && id(v.intervention_id) && id(v.wct_id) &&
    entier(v.decalage) && v.decalage <= 10000 && entier(v.limite) && v.limite >= 1 && v.limite <= 8;
}
export function construireArgumentsContexteMateriaux(interventionId: string, wctId: string, decalage: number, limite: number): ArgumentsContexteMateriauxM6 {
  const a = { intervention_id: interventionId, wct_id: wctId, decalage, limite };
  if (!argsValides(a)) throw new Error("Arguments de contexte matériaux M6 invalides.");
  return a;
}
function decimalPositif(v: unknown): v is string {
  return typeof v === "string" && v.length <= 5400 && sansControle(v) && /^[0-9]+(?:\.[0-9]+)?$/.test(v) && /[1-9]/.test(v);
}
/** Clé de comparaison décimale seulement ; les exposants viennent du sérialiseur JSON.
 * Les chiffres de la quantité ne sont jamais additionnés ou multipliés. */
function cleValeur(texte: string): { chiffres: string; exposant: number } {
  const [mantisse, e = "0"] = texte.toLowerCase().split("e"), [entiers, fraction = ""] = mantisse.split(".");
  const bruts = (entiers + fraction).replace(/^0+/, ""), chiffres = bruts.replace(/0+$/, "");
  return { chiffres, exposant: Number(e) - fraction.length + bruts.length - chiffres.length };
}
/** Writer actuel number : import uniquement si la valeur JSON roundtrip est exacte et
 * admise par jsonLecture/ACK. Le texte affiché reste inchangé ; réel non renseigné. */
export function estimationEnNombreExact(texte: string): number | null {
  if (!decimalPositif(texte)) return null;
  const n = Number(texte);
  if (!Number.isFinite(n) || n <= 0 || (Number.isInteger(n) && !Number.isSafeInteger(n))) return null;
  const representation = JSON.stringify(n), source = cleValeur(texte), destination = cleValeur(representation);
  return source.chiffres === destination.chiffres && source.exposant === destination.exposant ? n : null;
}
function lireWct(v: unknown, a: ArgumentsContexteMateriauxM6): WctContexteMateriauxM6 | null {
  if (!ferme(v, ["wct_id", "intervention_id", "devis_id", "horodatage_completion", "hash_maillon", "reference_bus"]) ||
    v.wct_id !== a.wct_id || v.intervention_id !== a.intervention_id || !(v.devis_id === null || id(v.devis_id)) ||
    !date(v.horodatage_completion) || !hash(v.hash_maillon) || !ferme(v.reference_bus, ["type", "evenement_id"]) ||
    v.reference_bus.type !== "m4.travaux_termines" || v.reference_bus.evenement_id !== a.wct_id) return null;
  return { wct_id: a.wct_id, intervention_id: a.intervention_id, devis_id: v.devis_id, horodatage_completion: v.horodatage_completion,
    hash_maillon: v.hash_maillon, reference_bus: { type: "m4.travaux_termines", evenement_id: a.wct_id } };
}
function lireSource(v: unknown, statut: "definitif" | "provisoire_estimation_m3"): SourcePrevuMateriauxM6 | null {
  if (!ferme(v, ["registre", "rang", "empreinte_snapshot", "estimation_id", "rang_m3", "bareme_version", "horodatage", "reference_m3"]) ||
    v.registre !== "besoins_prevus" || !entier(v.rang) || !hash(v.empreinte_snapshot) || !(v.estimation_id === null || hash(v.estimation_id)) ||
    !(v.rang_m3 === null || entier(v.rang_m3)) || !(v.bareme_version === null || id(v.bareme_version)) || !(v.horodatage === null || date(v.horodatage))) return null;
  if (statut === "provisoire_estimation_m3" ? (v.estimation_id === null || v.rang_m3 === null || v.bareme_version === null) :
    (v.estimation_id !== null || v.rang_m3 !== null || v.bareme_version !== null)) return null;
  let reference_m3: SourcePrevuMateriauxM6["reference_m3"] = null;
  if (v.reference_m3 !== null) {
    if (!ferme(v.reference_m3, ["type", "evenement_id"]) || !id(v.reference_m3.evenement_id) ||
      v.reference_m3.type !== (statut === "provisoire_estimation_m3" ? "m3.besoins_materiaux" : "m3.devis_accepte")) return null;
    const type = statut === "provisoire_estimation_m3" ? "m3.besoins_materiaux" : "m3.devis_accepte";
    reference_m3 = { type, evenement_id: v.reference_m3.evenement_id };
  }
  if ((reference_m3?.type === "m3.devis_accepte") !== (v.horodatage !== null)) return null;
  return { registre: "besoins_prevus", rang: v.rang, empreinte_snapshot: v.empreinte_snapshot, estimation_id: v.estimation_id,
    rang_m3: v.rang_m3, bareme_version: v.bareme_version, horodatage: v.horodatage, reference_m3 };
}
function lireLigne(v: unknown, position: number, source: SourcePrevuMateriauxM6 | null): LignePrevueMateriauxM6 | null {
  if (!ferme(v, ["position_source", "materiau_id", "unite", "quantite_estimee", "origine_quantite"]) || v.position_source !== position ||
    !id(v.materiau_id) || !id(v.unite) || !decimalPositif(v.quantite_estimee) ||
    (v.origine_quantite !== "texte_m3_verifie" && v.origine_quantite !== "nombre_m6_persiste") ||
    (v.origine_quantite === "texte_m3_verifie" && source?.reference_m3 == null)) return null;
  return { position_source: position, materiau_id: v.materiau_id, unite: v.unite, quantite_estimee: v.quantite_estimee, origine_quantite: v.origine_quantite };
}
const MANQUES = ["devis_absent", "prevu_absent", "chantier_source_absent", "horodatage_prevu_absent", "provenance_m3_absente"] as const;
const manque = (v: unknown): v is ManqueContexteMateriauxM6 => MANQUES.some(m => m === v);
const illisible = (): Reponse<ContexteMateriauxM6> => ({ ok: false, code: "reponse_illisible", detail: "Contexte matériaux illisible : aucun prévu partiel appliqué." });
export function lireContexteMateriaux(brut: unknown, args: ArgumentsContexteMateriauxM6): Reponse<ContexteMateriauxM6> {
  const a = copierJsonLecture(args);
  if (a === JSON_LECTURE_INVALIDE || !argsValides(a)) return illisible();
  const c = copierJsonLecture(brut);
  if (c === JSON_LECTURE_INVALIDE || !estObjet(c)) return illisible();
  if (estObjet(c.resultat) && c.resultat.accepte === false) {
    const v = c.resultat.verdict;
    if (!ferme(v, ["code", "detail"]) || !id(v.code) || typeof v.detail !== "string") return illisible();
    return { ok: false, code: v.code, detail: v.detail };
  }
  if (c.ok === false && (!id(c.erreur) || !(typeof c.details === "string" || (Array.isArray(c.details) && c.details.every(t => typeof t === "string"))))) return illisible();
  const ouvert = ouvrirEnveloppe(c, "directe");
  if (!ouvert.ok) return { ok: false, code: ouvert.verdict.code, detail: ouvert.verdict.detail };
  if (!ferme(c, ["ok", "resultat"])) return illisible();
  const v = ouvert.valeur;
  if (!ferme(v, ["wct", "chantier", "prevu", "lignes", "pagination", "manques", "couverture", "borne_caracteres", "taille_caracteres"]) ||
    !ferme(v.chantier, ["chantier_id", "origine"]) || !(v.chantier.chantier_id === null || id(v.chantier.chantier_id)) ||
    (v.chantier.origine !== "prevu_m6" && v.chantier.origine !== "intervention_employee" && v.chantier.origine !== "absent_admin") ||
    !ferme(v.prevu, ["statut", "source"]) || (v.prevu.statut !== "absent" && v.prevu.statut !== "definitif" && v.prevu.statut !== "provisoire_estimation_m3") ||
    !Array.isArray(v.lignes) || v.lignes.length > a.limite || !Array.isArray(v.manques) || !v.manques.every(manque) || new Set(v.manques).size !== v.manques.length ||
    !ferme(v.couverture, ["objet", "quantite_reelle", "pages", "plafond_lignes"]) || v.couverture.objet !== "contexte_et_prevu_du_wct" || v.couverture.quantite_reelle !== "non_renseignee" || v.couverture.pages !== "courantes" || v.couverture.plafond_lignes !== 10000 ||
    v.borne_caracteres !== 5400 || !entier(v.taille_caracteres) || v.taille_caracteres < 1 || v.taille_caracteres > 5400) return illisible();
  const manques = v.manques;
  const wct = lireWct(v.wct, a);
  const statut = v.prevu.statut, source = statut === "absent" ? null : lireSource(v.prevu.source, statut);
  if (!wct || (statut === "absent" ? v.prevu.source !== null : source === null) || (wct.devis_id === null && statut !== "absent") ||
    (v.chantier.origine === "absent_admin" ? v.chantier.chantier_id !== null : v.chantier.chantier_id === null) ||
    (v.chantier.origine === "intervention_employee" && v.chantier.chantier_id !== a.intervention_id) || (v.chantier.origine === "prevu_m6" && statut === "absent")) return illisible();
  const requis: ManqueContexteMateriauxM6[] = [];
  if (wct.devis_id === null) requis.push("devis_absent"); if (statut === "absent") requis.push("prevu_absent");
  if (v.chantier.chantier_id === null) requis.push("chantier_source_absent");
  if (source?.horodatage === null) requis.push("horodatage_prevu_absent"); if (source?.reference_m3 === null) requis.push("provenance_m3_absente");
  if (manques.length !== requis.length || !requis.every(m => manques.includes(m))) return illisible();
  const p = v.pagination;
  if (!ferme(p, ["decalage", "limite", "affichees", "total", "suivant", "reste", "courante"]) || p.decalage !== a.decalage || p.limite !== a.limite || p.affichees !== v.lignes.length || p.courante !== true ||
    !entier(p.total) || p.total > 10000 || !entier(p.reste) || !(p.suivant === null || entier(p.suivant)) || v.lignes.length > Math.max(0, p.total - a.decalage) ||
    (a.decalage < p.total && v.lignes.length === 0) || (statut === "absent" && (p.total !== 0 || v.lignes.length !== 0))) return illisible();
  const reste = Math.max(0, p.total - a.decalage - v.lignes.length);
  if (p.reste !== reste || p.suivant !== (reste ? a.decalage + v.lignes.length : null)) return illisible();
  const lignes: LignePrevueMateriauxM6[] = [], ids = new Set<string>();
  for (let i = 0; i < v.lignes.length; i++) {
    const l = lireLigne(v.lignes[i], a.decalage + i, source); if (!l || ids.has(l.materiau_id)) return illisible(); ids.add(l.materiau_id); lignes.push(l);
  }
  return { ok: true, value: { wct, chantier: { chantier_id: v.chantier.chantier_id, origine: v.chantier.origine }, prevu: { statut, source }, lignes,
    pagination: { decalage: a.decalage, limite: a.limite, affichees: lignes.length, total: p.total, suivant: p.suivant, reste: p.reste, courante: true }, manques,
    couverture: { objet: "contexte_et_prevu_du_wct", quantite_reelle: "non_renseignee", pages: "courantes", plafond_lignes: 10000 }, borne_caracteres: 5400, taille_caracteres: v.taille_caracteres } };
}
