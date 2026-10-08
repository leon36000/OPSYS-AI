import { copierJsonDispatch, objetDispatch, clesDispatch, texteDispatch, hashDispatch, entierDispatch, horodatageDispatch } from "./dispatch";
export const OUTIL_LIRE_RETARDS_INCIDENTS="m4_lire_retards_incidents";
export interface HeureRetard { readonly intervention_id:string; readonly depuis:string; readonly origine_heure:"serveur"|"appelant"; readonly heures_ecoulees:number|null }
export interface ReportCourant extends HeureRetard { readonly motif:"client_absent"|"meteo"|"decision_admin" }
export interface IncidentCourant extends HeureRetard { readonly demande_id:string; readonly type_demande:"ecart_metier"|"anomalie_pointage"; readonly bloquee:boolean }
export interface ListeRetards<T> { readonly total:number; readonly affiches:number; readonly reste:number; readonly suite:string|null; readonly liste:readonly T[] }
export interface RetardsIncidents {
 readonly type:"RETARDS_INCIDENTS"; readonly reference:string; readonly seuil_blocage_heures:number;
 readonly reports:ListeRetards<ReportCourant>&{readonly par_motif:Readonly<Record<ReportCourant["motif"],number>>};
 readonly incidents:ListeRetards<IncidentCourant>&{readonly par_type:Readonly<Record<IncidentCourant["type_demande"],number>>; readonly bloques:number};
 readonly retard_sur_cedule:{readonly statut:"non_mesurable";readonly manque:string};
}
export function construireArgumentsRetardsIncidents(reference:string):{readonly horodatage_reference:string}{return {horodatage_reference:reference};}
const MOTIFS=["client_absent","meteo","decision_admin"],TYPES=["ecart_metier","anomalie_pointage"];
function liste(v:unknown,incident:boolean,seuil:number):boolean {
 const compteur=incident?"par_type":"par_motif",enumere=incident?TYPES:MOTIFS;
 if(!objetDispatch(v)||!clesDispatch(v,["total",compteur,"affiches","reste","suite","liste",...(incident?["bloques"]:[])])||
    !entierDispatch(v.total)||!entierDispatch(v.affiches)||!entierDispatch(v.reste)||v.total!==v.affiches+v.reste||
    !Array.isArray(v.liste)||v.liste.length!==v.affiches||v.affiches>8||!objetDispatch(v[compteur]))return false;
 const repartition=v[compteur] as Record<string,unknown>;
 if(!clesDispatch(repartition,enumere)||!Object.values(repartition).every(entierDispatch)||Object.values(repartition).reduce<number>((s,n)=>s+(n as number),0)!==v.total)return false;
 const suite=v.reste===0?null:`${v.reste} de plus, du moins ancien au plus récent : ${incident?"m4_lister_pending_review":"m4_lister_interventions (statut reportee)"} les rend tous`;
 if(v.suite!==suite||incident&&!entierDispatch(v.bloques))return false;
 const ids=new Set<string>(),visibles:Record<string,number>={};let bloques=0,precedent:{heure:number,microsecondes:number,id:string}|null=null;
 for(const r of v.liste){
  if(!objetDispatch(r)||!clesDispatch(r,["intervention_id","depuis","origine_heure","heures_ecoulees",...(incident?["demande_id","type_demande","bloquee"]:["motif"])])||
     !hashDispatch(r.intervention_id)||!horodatageDispatch(r.depuis)||!["serveur","appelant"].includes(r.origine_heure as string)||
     !(r.heures_ecoulees===null||entierDispatch(r.heures_ecoulees)))return false;
  const id=incident?r.demande_id:r.intervention_id,t=incident?r.type_demande:r.motif;
  if(!hashDispatch(id)||typeof t!=="string"||!enumere.includes(t)||ids.has(id))return false;
  if(incident&&(typeof r.bloquee!=="boolean"||r.bloquee!==(r.heures_ecoulees!==null&&(r.heures_ecoulees as number)>=seuil)))return false;
  // Ordre du serveur vérifié, pas d'âge recalculé à l'heure courante du téléphone.
  const fraction=/[.,](\d+)(?=Z|[+-]\d{2}:\d{2}$)/.exec(r.depuis);
  const heure=Date.parse(r.depuis.replace(/[.,]\d+(?=Z|[+-]\d{2}:\d{2}$)/,"" ).replace(" ","T"));
  // datetime Python tronque à six décimales ; Date.parse seul perd les microsecondes.
  const microsecondes=Number((fraction?.[1]??"").padEnd(6,"0").slice(0,6));
  if(!Number.isFinite(heure)||precedent&&(heure<precedent.heure||heure===precedent.heure&&(microsecondes<precedent.microsecondes||microsecondes===precedent.microsecondes&&id<=precedent.id)))return false;
  precedent={heure,microsecondes,id};ids.add(id);visibles[t]=(visibles[t]??0)+1;if(r.bloquee)bloques++;
 }
 if(enumere.some(k=>(visibles[k]??0)>(repartition[k] as number)))return false;
 return !incident || (v.bloques as number)>=bloques&&(v.bloques as number)<=bloques+v.reste;
}
/** DTO après COUPLE interprété. La référence est liée à la demande ; aucune actualisation d'un âge ancien. */
export function lireRetardsIncidents(brut:unknown,reference:string):RetardsIncidents|null {
 const v=copierJsonDispatch(brut);
 if(!horodatageDispatch(reference)||!objetDispatch(v)||!clesDispatch(v,["type","reference","seuil_blocage_heures","reports","incidents","retard_sur_cedule"])||
    v.type!=="RETARDS_INCIDENTS"||v.reference!==reference||v.seuil_blocage_heures!==24||!liste(v.reports,false,24)||!liste(v.incidents,true,24)||
    !objetDispatch(v.retard_sur_cedule)||!clesDispatch(v.retard_sur_cedule,["statut","manque"])||v.retard_sur_cedule.statut!=="non_mesurable"||!texteDispatch(v.retard_sur_cedule.manque))return null;
 return v as unknown as RetardsIncidents;
}
