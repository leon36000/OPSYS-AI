import { copierJsonDispatch, objetDispatch, clesDispatch, hashDispatch, entierDispatch, lireInterventions, InterventionsLues, STATUTS_DU_DISPATCH } from "./dispatch";
export { OUTIL_LISTER_INTERVENTIONS } from "./dispatch";
export interface ArgumentsPageDispatch { readonly statut: string; readonly curseur: string | null; readonly taille_page: number | null }
export interface MetadonneesPageDispatch {
 readonly ordre: "intervention_id croissant"; readonly curseur: string | null; readonly taille_demandee: number | null;
 readonly taille: number; readonly total: number; readonly reste: number; readonly curseur_suivant: string | null; readonly borne_atteinte: boolean;
}
export interface PageDispatch extends InterventionsLues { readonly page: MetadonneesPageDispatch }
export function construireArgumentsPageDispatch(statut: string, curseur: string | null = null, taillePage: number | null = null): ArgumentsPageDispatch {
 return {statut,curseur,taille_page:taillePage};
}
/** DTO DIRECT après interprétation commune. Page courante seulement ; aucune garantie de snapshot entre lectures. */
export function lirePageDispatch(brut: unknown, argumentsDemandes: ArgumentsPageDispatch): PageDispatch | null {
 const v=copierJsonDispatch(brut), a=copierJsonDispatch(argumentsDemandes);
 if (!objetDispatch(a) || !clesDispatch(a,["statut","curseur","taille_page"]) || typeof a.statut!=="string" || !STATUTS_DU_DISPATCH.includes(a.statut) ||
     !(a.curseur===null || hashDispatch(a.curseur)) || !(a.taille_page===null || entierDispatch(a.taille_page)&&a.taille_page>=1&&a.taille_page<=50) ||
     !objetDispatch(v) || !clesDispatch(v,["interventions","page"]) || !Array.isArray(v.interventions) || !objetDispatch(v.page)) return null;
 const p=v.page;
 if (!clesDispatch(p,["ordre","curseur","taille_demandee","taille","total","reste","curseur_suivant","borne_atteinte"]) ||
     p.ordre!=="intervention_id croissant" || p.curseur!==a.curseur || p.taille_demandee!==a.taille_page ||
     !entierDispatch(p.taille) || !entierDispatch(p.total) || !entierDispatch(p.reste) || typeof p.borne_atteinte!=="boolean" ||
     !(p.curseur_suivant===null || hashDispatch(p.curseur_suivant)) || p.taille!==v.interventions.length || 
     (a.taille_page!==null && p.taille>a.taille_page) || p.total<p.taille+p.reste ||
     (a.curseur===null && p.total!==p.taille+p.reste)) return null;
 let precedent=a.curseur;
 for (const r of v.interventions) {
  if (!objetDispatch(r) || !clesDispatch(r,["intervention_id","statut","lead_id","devis_id","technicien_assigne","fenetre_planifiee"],["service","type_travaux"]) ||
      Object.hasOwn(r,"service")===Object.hasOwn(r,"type_travaux") || !hashDispatch(r.intervention_id) ||
      (precedent!==null && r.intervention_id<=precedent)) return null;
  precedent=r.intervention_id;
 }
 if ((p.reste>0 && (p.taille===0 || p.curseur_suivant!==precedent)) || (p.reste===0 && p.curseur_suivant!==null) ||
     p.borne_atteinte!==(p.taille<Math.min(a.taille_page??(p.taille+p.reste),p.taille+p.reste))) return null;
 const lues=lireInterventions(v.interventions,a.statut); if (!lues || lues.illisibles!==0) return null;
 return {...lues,page:p as unknown as MetadonneesPageDispatch};
}
