import { message, montantOuTexte, formaterDateOuInstant } from "./adminCommun";
import type { Message } from "./adminCommun";
import type { LangueMontant } from "./quotes";
import { texteSansChemin } from "./texteSur";
import { TRANCHES } from "../m5/comptes";
import type { Creances, Masquee, PageAP, AttentesFacturation } from "../m5/comptes";

const sur = (v: string | null) => v === null ? null : texteSansChemin(v);
const ligne = (libelle: string, valeur: string | null): Message =>
  valeur === null ? message(`admin.comptes.champs.${libelle}Inconnu`) : message(`admin.comptes.champs.${libelle}`, { valeur });
const somme = (v: string | null, langue: LangueMontant) => v === null ? null : montantOuTexte(v, langue);
const ref = (v: string | null) => sur(v);
const STATUTS = ["partially_received","received","sent_to_supplier","SAISIE","CORRIGEE","ANNULEE","en_attente_devis_accepte","en_attente_travaux_termines","en_attente_chantier_id","wct_sans_devis_id"];
const statut = (v: string): Message => STATUTS.includes(v)
  ? message(`admin.comptes.statuts.${v}`) : message("admin.commun.inconnu", { valeur: sur(v) ?? "" });
export interface GroupeComptes { readonly titre: string; readonly lignes: readonly Message[]; }
export interface VueComptes { readonly vide: boolean; readonly lignes: readonly Message[]; readonly groupes: readonly GroupeComptes[]; }
export function presenterCreances(v: Creances | Masquee, langue: LangueMontant, decalage: number): VueComptes {
  if (v.genre === "masquee") return { vide: false, lignes: [message("admin.comptes.masque", { nombre: v.nombre })], groupes: [] };
  const lignes: Message[] = [
    message(v.total_complet ? "admin.comptes.totalRecevoir" : "admin.comptes.recevoirPartiel",
      { montant: montantOuTexte(v.total_a_recevoir, langue), nombre: v.nombre }),
    message("admin.comptes.ageDepuisEnvoi", { jour: v.age.aujourd_hui }),
  ];
  for (const cle of TRANCHES) lignes.push(message("admin.comptes.tranche", {
    tranche: cle, montant: montantOuTexte(v.age.total_par_tranche[cle], langue), nombre: v.age.tranches[cle].length,
  }));
  for (const a of v.illisibles) lignes.push(message("admin.comptes.anomalie", { reference: ref(a.facture_id) ?? "", code: sur(a.code) ?? "" }));
  for (const a of v.age.exclues) lignes.push(message("admin.comptes.ageExclu", { reference: ref(a.facture_id) ?? "", code: sur(a.code) ?? "" }));
  return { vide: v.factures.length === 0 && v.illisibles.length === 0, lignes, groupes: v.factures.map(f => ({
    titre: ref(f.facture_id) ?? "",
    lignes: [
      ligne("client", ref(f.client_id)), ligne("chantier", ref(f.chantier_id)), ligne("devis", ref(f.devis_id)),
      ligne("CAD", somme(f.montant_apres_taxes, langue)),
      ligne("date_envoi", f.date_envoi === null ? null : sur(formaterDateOuInstant(f.date_envoi, decalage))),
    ],
  })) };
}
export function presenterAP(v: PageAP | Masquee, langue: LangueMontant, decalage: number): VueComptes {
  if (v.genre === "masquee") return { vide: false, lignes: [message("admin.comptes.masque", { nombre: v.nombre })], groupes: [] };
  const lignes: Message[] = [
    message("admin.comptes.mention", { texte: sur(v.mention) ?? "" }),
    message(v.complet ? "admin.comptes.totalPayer" : "admin.comptes.payerPartiel", {
      montant: montantOuTexte(v.complet ? v.total_apres_taxes! : v.connu_apres_taxes, langue),
    }),
    message("admin.comptes.page", { depart: v.depart, affichees: v.affichees, reste: v.reste, total: v.total }),
    message(v.sans_po ? "admin.comptes.totalSansPO" : "admin.comptes.totalAvecSansPO"),
    ...v.hypotheses.map(texte => message("admin.comptes.mention", { texte: sur(texte) ?? "" })),
    ...Object.entries(v.taxes_versions).map(([nom, version]) => message("admin.comptes.versionFiscale", {
      taxe: sur(nom) ?? "", version: sur(version) ?? "",
    })),
  ];
  return { vide: v.comptes.length === 0 && v.factures.length === 0, lignes, groupes: v.sans_po ? v.factures.map(f => ({
    titre: ref(f.numero_facture) ?? "",
    lignes: [
      ligne("facture", ref(f.facture_fournisseur_id)), ligne("fournisseur", ref(f.fournisseur_id)),
      ligne("categorie", sur(f.categorie_depense)), statut(f.statut),
      ligne("date_facture", sur(f.date_facture)), ligne("CAD", somme(f.apres_taxes, langue)),
      ...f.avertissements.map(texte => message("admin.comptes.mention", { texte: sur(texte) ?? "" })),
    ],
  })) : v.comptes.map(p => ({
    titre: ref(p.po_id) ?? "",
    lignes: [
      ligne("fournisseur", ref(p.fournisseur_id)), ligne("chantier", ref(p.chantier_id)), statut(p.statut_po),
      ligne("derniere_reception", sur(formaterDateOuInstant(p.derniere_reception, decalage))),
      p.attendu_apres_taxes === null ? message("admin.comptes.attenduInconnu") : message("admin.comptes.attendu", { montant: montantOuTexte(p.attendu_apres_taxes, langue) }),
      message("admin.comptes.facture", { montant: montantOuTexte(p.facture_apres_taxes, langue) }),
      p.a_payer_apres_taxes === null ? message("admin.comptes.payerInconnu") :
        message("admin.comptes.aPayer", { montant: montantOuTexte(p.a_payer_apres_taxes, langue) }),
      message("admin.comptes.rapprochement", { verdict: sur(p.verdict) ?? "" }),
      ...p.manque.map(texte => message("admin.comptes.mention", { texte: sur(texte) ?? "" })),
    ],
  })) };
}
export function presenterAttentes(v: AttentesFacturation): VueComptes {
  return { vide: v.devis.length === 0 && v.wct.length === 0, lignes: [message("admin.comptes.attentesLecture")],
    groupes: [
      ...v.devis.map(d => ({ titre: ref(d.devis_id) ?? "", lignes: [statut(d.statut)] })),
      ...v.wct.map(w => ({ titre: ref(w.wct_id) ?? "", lignes: [
        ligne("intervention", ref(w.intervention_id)), statut(w.statut),
      ] })),
    ] };
}
