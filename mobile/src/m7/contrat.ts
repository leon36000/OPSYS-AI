import { lireEnveloppeMetier, estObjet } from "../protocole/enveloppeOutil";
import { interpreterResultatListerDemandes } from "../approbations/contrat";

export interface SessionM7 { readonly urlBase: string; readonly jeton: string; readonly appareilId: string; readonly personne: string }
export interface PreuveMarqueM7 { readonly source: "brand_profiles" | "yaml_legacy"; readonly revision: number | null; readonly sha256: string }
export interface LigneContenuM7 {
  readonly contenu_id: string; readonly wct_id: string; readonly plateforme: string; readonly revision: number;
  readonly approval_status: "PROPOSE" | "APPROVED" | "REJECTED" | "CONSENTEMENT_RETIRE";
  readonly exporte: boolean; readonly marque_source: PreuveMarqueM7 | null;
  readonly fraicheur_marque: "courante" | "perimee" | "preuve_absente";
  readonly texte: string; readonly origine_texte: string; readonly mots_clics: readonly string[];
  readonly lien_utm: string | null; readonly avertissements: readonly string[]; readonly decision: unknown;
  readonly consentement: { readonly recueilli_par: string; readonly recueilli_le: string; readonly version_texte: string };
}
export interface ListeM7 {
  readonly items: readonly LigneContenuM7[]; readonly total: number; readonly decalage: number;
  readonly suivant: number | null; readonly reste: number; readonly marqueCourante: PreuveMarqueM7 | null;
}
export type Reponse<T> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly code: string; readonly detail: string };
export type AppelM7 = (tool: string, args?: Record<string, unknown>, mutation?: { idempotencyKey: string; deviceId: string; deviceTimestamp: string }) => Promise<unknown>;

const str = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
function preuve(v: unknown): PreuveMarqueM7 | null {
  if (v === null) return null;
  if (!estObjet(v) || (v.source !== "brand_profiles" && v.source !== "yaml_legacy") || typeof v.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(v.sha256)) return null;
  if (v.source === "brand_profiles" && (!Number.isSafeInteger(v.revision) || (v.revision as number) < 1)) return null;
  if (v.source === "yaml_legacy" && v.revision !== null) return null;
  return { source: v.source, revision: v.revision as number | null, sha256: v.sha256 };
}
function ligne(v: unknown): LigneContenuM7 | null {
  if (!estObjet(v)) return null;
  const p = v.marque_source === null ? null : preuve(v.marque_source);
  const c = v.consentement;
  const d = v.decision;
  const decisionValide = d === null || (estObjet(d) && typeof d.decision === "string" && ["APPROVED", "REJECTED"].includes(d.decision) &&
    str(d.par) && str(d.role) && str(d.source) && (d.motif === null || typeof d.motif === "string") && str(d.horodatage));
  if (!str(v.contenu_id) || !str(v.wct_id) || !str(v.plateforme) || !Number.isSafeInteger(v.revision) || (v.revision as number) < 1 ||
      typeof v.approval_status !== "string" || !["PROPOSE", "APPROVED", "REJECTED", "CONSENTEMENT_RETIRE"].includes(v.approval_status) || typeof v.exporte !== "boolean" ||
      (v.marque_source !== null && p === null) || typeof v.fraicheur_marque !== "string" || !["courante", "perimee", "preuve_absente"].includes(v.fraicheur_marque) ||
      typeof v.texte !== "string" || v.texte.trim() === "" || v.texte.length > 6000 || !str(v.origine_texte) || !Array.isArray(v.mots_clics) || !v.mots_clics.every(str) ||
      !(v.lien_utm === null || typeof v.lien_utm === "string") || !Array.isArray(v.avertissements) || !v.avertissements.every(str) || !decisionValide ||
      !estObjet(c) || !str(c.recueilli_par) || !str(c.recueilli_le) || !str(c.version_texte)) return null;
  return { contenu_id: v.contenu_id, wct_id: v.wct_id, plateforme: v.plateforme, revision: v.revision as number,
    approval_status: v.approval_status as LigneContenuM7["approval_status"], exporte: v.exporte, marque_source: p,
    fraicheur_marque: v.fraicheur_marque as LigneContenuM7["fraicheur_marque"], texte: v.texte, origine_texte: v.origine_texte,
    mots_clics: v.mots_clics as string[], lien_utm: v.lien_utm as string | null, avertissements: v.avertissements as string[], decision: v.decision,
    consentement: { recueilli_par: c.recueilli_par, recueilli_le: c.recueilli_le, version_texte: c.version_texte } };
}
export function lireListeM7(brut: unknown): Reponse<ListeM7> {
  const enveloppe = lireEnveloppeMetier(brut);
  if (!enveloppe.ok) return { ok: false, code: enveloppe.verdict.code, detail: enveloppe.verdict.detail };
  const v = enveloppe.valeur;
  if (!estObjet(v) || !Array.isArray(v.contenus) || !Number.isSafeInteger(v.total) || (v.total as number) < 0 ||
      !Number.isSafeInteger(v.decalage) || (v.decalage as number) < 0 || !(v.suivant === null || (Number.isSafeInteger(v.suivant) && (v.suivant as number) >= 0)) ||
      !Number.isSafeInteger(v.reste) || (v.reste as number) < 0 || v.contenus.length > 8) return { ok: false, code: "reponse_illisible", detail: "Liste marketing invalide." };
  const items = v.contenus.map(ligne);
  if (items.some((x) => x === null) || new Set((items as LigneContenuM7[]).map((x) => x.contenu_id)).size !== items.length) return { ok: false, code: "reponse_illisible", detail: "Une ligne marketing est invalide." };
  const brand = preuve(v.marque_courante);
  if (v.marque_courante !== null && brand === null) return { ok: false, code: "reponse_illisible", detail: "Preuve de marque invalide." };
  const apres = (v.decalage as number) + items.length;
  if (apres > (v.total as number) || v.reste !== (v.total as number) - apres || (v.suivant !== null && v.suivant !== apres) ||
      (v.suivant === null && v.reste !== 0) || (v.suivant !== null && items.length === 0)) return { ok: false, code: "reponse_illisible", detail: "Pagination marketing incohérente." };
  return { ok: true, value: { items: items as LigneContenuM7[], total: v.total as number, decalage: v.decalage as number,
    suivant: v.suivant as number | null, reste: v.reste as number, marqueCourante: brand } };
}
export function lireOwnerM9(brut: unknown): Reponse<boolean> {
  const interpretation = interpreterResultatListerDemandes(brut);
  return interpretation.ok
    ? { ok: true, value: interpretation.liste.proprietaire }
    : { ok: false, code: interpretation.verdict.code, detail: interpretation.verdict.detail };
}
