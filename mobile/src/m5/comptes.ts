import { estDecimal, estObjet, listeDeTextes, texteOuNull } from "../admin/lecteurs";

export const OUTIL_CREANCES = "m5_lire_comptes_a_recevoir";
export const OUTIL_A_PAYER = "m5_lister_comptes_a_payer";
export const OUTIL_ATTENTES = "m5_lister_attentes_facturation";
type Objet = Record<string, unknown>;
export type Montant = string | null;
export interface Masquee { readonly genre: "masquee"; readonly nombre: number; readonly role: string; }
export interface Creance {
  readonly facture_id: string; readonly chantier_id: string | null;
  readonly devis_id: string | null; readonly client_id: string | null;
  readonly montant_apres_taxes: string; readonly date_envoi: string | null;
}
export interface AgeCreances {
  readonly aujourd_hui: string;
  readonly tranches: Readonly<Record<string, readonly { facture_id: string; age_jours: number; montant_apres_taxes: string }[]>>;
  readonly total_par_tranche: Readonly<Record<string, string>>;
  readonly exclues: readonly { facture_id: string; code: string }[];
}
export interface Creances {
  readonly genre: "creances"; readonly nombre: number; readonly factures: readonly Creance[];
  readonly total_a_recevoir: string; readonly total_complet: boolean;
  readonly illisibles: readonly { facture_id: string; code: string }[];
  readonly age: AgeCreances; readonly role: string;
}
export interface ComptePO {
  readonly po_id: string; readonly fournisseur_id: string; readonly chantier_id: string;
  readonly statut_po: string; readonly derniere_reception: string;
  readonly attendu_apres_taxes: Montant; readonly facture_apres_taxes: string;
  readonly a_payer_apres_taxes: Montant; readonly verdict: string; readonly manque: readonly string[];
}
export interface FactureSansPO {
  readonly facture_fournisseur_id: string; readonly numero_facture: string; readonly fournisseur_id: string;
  readonly categorie_depense: string; readonly date_facture: string; readonly statut: string;
  readonly apres_taxes: string; readonly avertissements: readonly string[];
}
export interface PageAP {
  readonly genre: "page"; readonly role: string; readonly sans_po: boolean; readonly mention: string;
  readonly hypotheses: readonly string[]; readonly taxes_versions: Readonly<Record<string, string>>;
  readonly total: number; readonly depart: number; readonly affichees: number;
  readonly reste: number; readonly prochain_depart: number | null;
  readonly total_apres_taxes: Montant; readonly connu_apres_taxes: string; readonly complet: boolean;
  readonly comptes: readonly ComptePO[]; readonly factures: readonly FactureSansPO[];
}
export interface AttentesFacturation {
  readonly devis: readonly { devis_id: string; statut: string }[];
  readonly wct: readonly { wct_id: string; intervention_id: string; statut: string }[];
}
export const TRANCHES = ["0-30", "31-60", "61-90", "90+"] as const;
const entier = (x: unknown): x is number => typeof x === "number" && Number.isSafeInteger(x) && x >= 0;
const nullableTexte = (x: unknown): x is string | null => x === null || texteOuNull(x) !== null;
const montant = (x: unknown): x is Montant => x === null || estDecimal(x);
function liste<T>(x: unknown, lire: (v: unknown) => T | null): readonly T[] | null {
  if (!Array.isArray(x)) return null;
  const lus = x.map(lire);
  return lus.some(v => v === null) ? null : lus as T[];
}
function anomalie(v: unknown) {
  if (!estObjet(v) || !texteOuNull(v.facture_id) || !estObjet(v.verdict) || !texteOuNull(v.verdict.code)) return null;
  return { facture_id: v.facture_id as string, code: v.verdict.code as string };
}
export function lireCreances(v: unknown, jour: string): Creances | Masquee | null {
  if (!estObjet(v) || !texteOuNull(v.role) || !entier(v.nombre)) return null;
  if (v.montants_masques === true) return { genre: "masquee", nombre: v.nombre, role: v.role as string };
  if (!estDecimal(v.total_a_recevoir) || typeof v.total_complet !== "boolean" || !estObjet(v.age) ||
      v.age.aujourd_hui !== jour || !estObjet(v.age.tranches) || !estObjet(v.age.total_par_tranche)) return null;
  const factures = liste(v.factures, (f): Creance | null => {
    if (!estObjet(f) || !texteOuNull(f.facture_id) || !estDecimal(f.montant_apres_taxes) ||
        !nullableTexte(f.chantier_id) || !nullableTexte(f.devis_id) || !nullableTexte(f.client_id) || !nullableTexte(f.date_envoi)) return null;
    return { facture_id: f.facture_id as string, chantier_id: f.chantier_id, devis_id: f.devis_id,
      client_id: f.client_id, montant_apres_taxes: f.montant_apres_taxes, date_envoi: f.date_envoi };
  });
  const illisibles = liste(v.illisibles, anomalie), exclues = liste(v.age.exclues, anomalie);
  if (!factures || !illisibles || !exclues || v.nombre !== factures.length || v.total_complet !== (illisibles.length === 0)) return null;
  const tranches: Record<string, { facture_id: string; age_jours: number; montant_apres_taxes: string }[]> = Object.create(null);
  const totaux: Record<string, string> = Object.create(null);
  for (const cle of TRANCHES) {
    if (!Object.hasOwn(v.age.tranches, cle) || !Object.hasOwn(v.age.total_par_tranche, cle)) return null;
    const rows = liste(v.age.tranches[cle], r => {
      if (!estObjet(r) || !texteOuNull(r.facture_id) || !entier(r.age_jours) || !estDecimal(r.montant_apres_taxes)) return null;
      return { facture_id: r.facture_id as string, age_jours: r.age_jours, montant_apres_taxes: r.montant_apres_taxes };
    });
    const total = v.age.total_par_tranche[cle];
    if (!rows || !estDecimal(total)) return null;
    tranches[cle] = [...rows]; totaux[cle] = total;
  }
  return { genre: "creances", role: v.role as string, nombre: v.nombre, factures, total_a_recevoir: v.total_a_recevoir,
    total_complet: v.total_complet, illisibles, age: { aujourd_hui: jour, tranches, total_par_tranche: totaux, exclues } };
}
function lirePO(v: unknown): ComptePO | null {
  if (!estObjet(v) || !texteOuNull(v.po_id) || !texteOuNull(v.fournisseur_id) || !texteOuNull(v.chantier_id) ||
      !texteOuNull(v.statut_po) || !texteOuNull(v.derniere_reception) || !estObjet(v.attendu) || !montant(v.attendu.apres_taxes) ||
      !estObjet(v.factures) || !estDecimal(v.factures.apres_taxes) || !montant(v.a_payer_apres_taxes) ||
      !estObjet(v.rapprochement) || v.rapprochement.statut !== "PROPOSE" || !texteOuNull(v.rapprochement.verdict)) return null;
  const manque = v.manque === undefined ? [] : listeDeTextes(v.manque);
  if (!manque) return null;
  return { po_id: v.po_id as string, fournisseur_id: v.fournisseur_id as string, chantier_id: v.chantier_id as string,
    statut_po: v.statut_po as string, derniere_reception: v.derniere_reception as string,
    attendu_apres_taxes: v.attendu.apres_taxes, facture_apres_taxes: v.factures.apres_taxes,
    a_payer_apres_taxes: v.a_payer_apres_taxes, verdict: v.rapprochement.verdict as string, manque };
}
function lireSansPO(v: unknown): FactureSansPO | null {
  if (!estObjet(v) || !texteOuNull(v.facture_fournisseur_id) || !texteOuNull(v.numero_facture) ||
      !texteOuNull(v.fournisseur_id) || !texteOuNull(v.categorie_depense) || !texteOuNull(v.date_facture) ||
      !texteOuNull(v.statut) || !estDecimal(v.apres_taxes)) return null;
  const avertissements = listeDeTextes(v.avertissements);
  if (!avertissements) return null;
  return { facture_fournisseur_id: v.facture_fournisseur_id as string, numero_facture: v.numero_facture as string,
    fournisseur_id: v.fournisseur_id as string, categorie_depense: v.categorie_depense as string,
    date_facture: v.date_facture as string, statut: v.statut as string, apres_taxes: v.apres_taxes, avertissements };
}
export function lireAP(v: unknown, sansPO: boolean, depart: number): PageAP | Masquee | null {
  if (!estObjet(v) || !texteOuNull(v.role)) return null;
  if (v.montants_masques === true) {
    const nombre = sansPO ? v.nombre_factures_sans_po : v.nombre_po;
    return entier(nombre) ? { genre: "masquee", nombre, role: v.role as string } : null;
  }
  if (v.type !== (sansPO ? "COMPTES_A_PAYER_SANS_PO" : "COMPTES_A_PAYER") ||
      !texteOuNull(v.mention) || !estObjet(v.totaux) || !entier(v.total) || !entier(v.depart) || v.depart !== depart ||
      !entier(v.affichees) || !entier(v.reste) || !(v.prochain_depart === null || entier(v.prochain_depart))) return null;
  if (v.depart + v.affichees + v.reste !== v.total || !Number.isSafeInteger(v.depart + v.affichees + v.reste) ||
      v.prochain_depart !== (v.reste > 0 ? v.depart + v.affichees : null) || (v.reste > 0 && v.affichees === 0)) return null;
  const hypotheses = listeDeTextes(v.hypotheses);
  const comptes = sansPO ? [] : liste(v.comptes, lirePO);
  const factures = sansPO ? liste(v.factures, lireSansPO) : [];
  if (!hypotheses || !comptes || !factures || (sansPO ? factures.length : comptes.length) !== v.affichees) return null;
  const taxes: Record<string, string> = Object.create(null);
  if (!sansPO) {
    if (!estObjet(v.taxes_versions)) return null;
    for (const [k, t] of Object.entries(v.taxes_versions)) {
      if (!texteOuNull(t)) return null; taxes[k] = t as string;
    }
  }
  const total = sansPO ? v.totaux.apres_taxes : v.totaux.a_payer_apres_taxes;
  const connu = sansPO ? v.totaux.apres_taxes : v.totaux.a_payer_connu_apres_taxes;
  const complet = sansPO ? true : v.totaux.complet;
  if (!montant(total) || !estDecimal(connu) || typeof complet !== "boolean" || complet !== (total !== null)) return null;
  return { genre: "page", role: v.role as string, sans_po: sansPO, mention: v.mention as string, hypotheses, taxes_versions: taxes,
    total: v.total, depart: v.depart, affichees: v.affichees, reste: v.reste, prochain_depart: v.prochain_depart,
    total_apres_taxes: total, connu_apres_taxes: connu, complet, comptes, factures };
}
export function lireAttentes(v: unknown): AttentesFacturation | null {
  if (!estObjet(v)) return null;
  const devis = liste(v.attentes_devis, d => estObjet(d) && texteOuNull(d.devis_id) && texteOuNull(d.statut)
    ? { devis_id: d.devis_id as string, statut: d.statut as string } : null);
  const wct = liste(v.attentes_wct_sans_devis_id, d => estObjet(d) && texteOuNull(d.wct_id) &&
    texteOuNull(d.intervention_id) && texteOuNull(d.statut)
    ? { wct_id: d.wct_id as string, intervention_id: d.intervention_id as string, statut: d.statut as string } : null);
  return devis && wct ? { devis, wct } : null;
}
