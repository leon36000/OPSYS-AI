import { ouvrirEnveloppe } from "../admin/enveloppe";
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
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;

/** JSON propre ou projection à prototype nul : aucune propriété héritée ni lecture d'accesseur. */
function objet(v: unknown): Record<string, unknown> | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  try {
    const prototype = Object.getPrototypeOf(v);
    if (prototype !== Object.prototype && prototype !== null) return null;
    const resultat: Record<string, unknown> = Object.create(null);
    for (const [cle, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(v))) {
      if (!("value" in descriptor)) return null;
      resultat[cle] = descriptor.value;
    }
    return resultat;
  } catch {
    return null;
  }
}
function liste<T>(v: unknown, lire: (v: unknown) => T | null, limite = Number.MAX_SAFE_INTEGER): T[] | null {
  if (!Array.isArray(v)) return null;
  try {
    if (Object.getPrototypeOf(v) !== Array.prototype) return null;
    const longueur: unknown = Object.getOwnPropertyDescriptor(v, "length")?.value;
    if (!entier(longueur) || longueur > limite) return null;
    const descriptors = Object.getOwnPropertyDescriptors(v), resultat: T[] = [];
    for (let i = 0; i < longueur; i++) {
      if (!Object.hasOwn(descriptors, String(i))) return null;
      const descriptor = descriptors[String(i)];
      if (!("value" in descriptor)) return null;
      const lu = lire(descriptor.value);
      if (lu === null) return null;
      resultat.push(lu);
    }
    return resultat;
  } catch {
    return null;
  }
}
function preuve(v: unknown): PreuveMarqueM7 | null {
  if (v === null) return null;
  const p = objet(v);
  if (!p || typeof p.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(p.sha256)) return null;
  if (p.source === "brand_profiles" && entier(p.revision) && p.revision >= 1) {
    return { source: p.source, revision: p.revision, sha256: p.sha256 };
  }
  return p.source === "yaml_legacy" && p.revision === null
    ? { source: p.source, revision: null, sha256: p.sha256 } : null;
}
function statut(v: unknown): v is LigneContenuM7["approval_status"] {
  return v === "PROPOSE" || v === "APPROVED" || v === "REJECTED" || v === "CONSENTEMENT_RETIRE";
}
function fraicheur(v: unknown): v is LigneContenuM7["fraicheur_marque"] {
  return v === "courante" || v === "perimee" || v === "preuve_absente";
}
function decision(v: unknown): Record<string, unknown> | null | undefined {
  if (v === null) return null;
  const d = objet(v);
  if (!d || (d.decision !== "APPROVED" && d.decision !== "REJECTED") || !str(d.par) || !str(d.role)
    || !str(d.source) || !(d.motif === null || typeof d.motif === "string") || !str(d.horodatage)) return undefined;
  return { decision: d.decision, par: d.par, role: d.role, source: d.source, motif: d.motif, horodatage: d.horodatage };
}
function ligne(brut: unknown): LigneContenuM7 | null {
  const v = objet(brut);
  if (!v) return null;
  const p = v.marque_source === null ? null : preuve(v.marque_source);
  const c = objet(v.consentement), d = decision(v.decision);
  const mots = liste(v.mots_clics, x => str(x) ? x : null);
  const avertissements = liste(v.avertissements, x => str(x) ? x : null);
  if (!str(v.contenu_id) || !str(v.wct_id) || !str(v.plateforme) || !entier(v.revision) || v.revision < 1 ||
      !statut(v.approval_status) || typeof v.exporte !== "boolean" || (v.marque_source !== null && p === null) ||
      !fraicheur(v.fraicheur_marque) || !str(v.texte) || v.texte.length > 6000 || !str(v.origine_texte) ||
      !mots || !avertissements || !(v.lien_utm === null || typeof v.lien_utm === "string") || d === undefined ||
      !c || !str(c.recueilli_par) || !str(c.recueilli_le) || !str(c.version_texte)) return null;
  return { contenu_id: v.contenu_id, wct_id: v.wct_id, plateforme: v.plateforme, revision: v.revision,
    approval_status: v.approval_status, exporte: v.exporte, marque_source: p,
    fraicheur_marque: v.fraicheur_marque, texte: v.texte, origine_texte: v.origine_texte,
    mots_clics: mots, lien_utm: v.lien_utm, avertissements, decision: d,
    consentement: { recueilli_par: c.recueilli_par, recueilli_le: c.recueilli_le, version_texte: c.version_texte } };
}
/** M7 liste est DIRECTE ; les décisions M7 gardent le lecteur COUPLE de leur contrôleur. */
export function lireListeM7(brut: unknown): Reponse<ListeM7> {
  const racine = objet(brut);
  if (racine && racine.ok === true) {
    const contenu = objet(racine.resultat);
    if (contenu) {
      if (contenu.accepte === false) contenu.verdict = objet(contenu.verdict);
      racine.resultat = contenu;
    } else {
      racine.resultat = null;
    }
  }
  const enveloppe = ouvrirEnveloppe(racine, "directe");
  if (!enveloppe.ok) return { ok: false, code: enveloppe.verdict.code, detail: enveloppe.verdict.detail };
  const v = objet(enveloppe.valeur);
  if (!v || !entier(v.total) || !entier(v.decalage) || !entier(v.reste) ||
    !(v.suivant === null || entier(v.suivant))) return { ok: false, code: "reponse_illisible", detail: "Liste marketing invalide." };
  const items = liste(v.contenus, ligne, 8);
  if (!items || new Set(items.map(x => x.contenu_id)).size !== items.length ||
    new Set(items.map(x => JSON.stringify([x.wct_id, x.plateforme]))).size !== items.length) {
    return { ok: false, code: "reponse_illisible", detail: "Une ligne marketing courante est invalide." };
  }
  const brand = preuve(v.marque_courante);
  if (v.marque_courante !== null && brand === null) return { ok: false, code: "reponse_illisible", detail: "Preuve de marque invalide." };
  const apres = v.decalage + items.length;
  // Le serveur rend une page vide légale quand l'offset est au-delà de la fin. Un vide intérieur ne progresse pas.
  const suivant = items.length > 0 && apres < v.total ? apres : null;
  if (!Number.isSafeInteger(apres) || (items.length > 0 && apres > v.total) ||
    (items.length === 0 && v.decalage < v.total) || v.reste !== Math.max(0, v.total - apres) || v.suivant !== suivant) {
    return { ok: false, code: "reponse_illisible", detail: "Pagination marketing incohérente." };
  }
  return { ok: true, value: { items, total: v.total, decalage: v.decalage,
    suivant: v.suivant, reste: v.reste, marqueCourante: brand } };
}
export function lireOwnerM9(brut: unknown): Reponse<boolean> {
  const interpretation = interpreterResultatListerDemandes(brut);
  return interpretation.ok
    ? { ok: true, value: interpretation.liste.proprietaire }
    : { ok: false, code: interpretation.verdict.code, detail: interpretation.verdict.detail };
}
