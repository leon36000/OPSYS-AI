import { copierJsonDispatch, objetDispatch, clesDispatch, texteDispatch, hashDispatch, entierDispatch, dateCivileDispatch, horodatageDispatch } from "./dispatch";
export const OUTIL_LIRE_METEO_INTERVENTION="m4_lire_meteo_intervention";
export type StatutMeteoIntervention="ok"|"inconnu"|"validation_requise"|"bloquant";
export interface CauseMeteo { readonly code:string; readonly detail:string }
export interface CitationMeteo { readonly source:string; readonly emise_le:string; readonly heure_type:string; readonly saisi_par?:string; readonly reference?:string; readonly licence?:string; readonly forfait?:string; readonly collection?:string; readonly page_meteo?:string }
export interface RegleMeteo { readonly risque:string; readonly statut:StatutMeteoIntervention; readonly detail:string }
export interface CreneauMeteoIntervention {
 readonly intervention_id:string; readonly equipe:string; readonly jour:number; readonly date:string|null; readonly debut_min:number; readonly fin_min:number; readonly service:string|null;
 readonly statut_intervention:string; readonly statut:StatutMeteoIntervention; readonly plan_perime:boolean; readonly regles:readonly RegleMeteo[];
 readonly prevision:CitationMeteo|null; readonly cause?:CauseMeteo; readonly sans_objet?:readonly string[]; readonly a_configurer?:readonly string[];
}
export interface MeteoIntervention {
 readonly intervention_id:string; readonly statut_intervention:string; readonly statut:StatutMeteoIntervention; readonly plan_id:string|null;
 readonly creneaux:readonly CreneauMeteoIntervention[]; readonly cause:CauseMeteo|null; readonly attributions:readonly {readonly source:string;readonly attribution:string}[];
}
export interface ArgumentsMeteoIntervention { readonly intervention_id:string; readonly date:string|null }
export function construireArgumentsMeteoIntervention(interventionId:string,date:string|null=null):ArgumentsMeteoIntervention {return {intervention_id:interventionId,date};}
const RISQUES=["vent","pluie","gel","verglas","chaleur"];
const STATUTS=["ok","inconnu","validation_requise","bloquant"];
function cause(v:unknown):boolean {return objetDispatch(v)&&clesDispatch(v,["code","detail"])&&texteDispatch(v.code)&&texteDispatch(v.detail);}
function textes(v:unknown):v is string[] {return Array.isArray(v)&&v.every(texteDispatch);}
/** DTO après COUPLE interprété. Date explicitement fournie ou null ; aucun défaut de calendrier. */
export function lireMeteoIntervention(brut:unknown,argumentsDemandes:ArgumentsMeteoIntervention):MeteoIntervention|null {
 const v=copierJsonDispatch(brut),a=copierJsonDispatch(argumentsDemandes);
 if(!objetDispatch(a)||!clesDispatch(a,["intervention_id","date"])||!hashDispatch(a.intervention_id)||!(a.date===null||dateCivileDispatch(a.date))||
    !objetDispatch(v)||!clesDispatch(v,["intervention_id","statut_intervention","statut","plan_id","creneaux","cause","attributions"])||
    v.intervention_id!==a.intervention_id||typeof v.statut_intervention!=="string"||!["a_planifier","planifiee","reportee","en_route"].includes(v.statut_intervention)||
    typeof v.statut!=="string"||!STATUTS.includes(v.statut)||!(v.plan_id===null||hashDispatch(v.plan_id))||
    !(v.cause===null||cause(v.cause))||!Array.isArray(v.creneaux)||v.creneaux.length>1||!Array.isArray(v.attributions)||
    !v.attributions.every(r=>objetDispatch(r)&&clesDispatch(r,["source","attribution"])&&texteDispatch(r.source)&&texteDispatch(r.attribution)))return null;
 if(v.creneaux.length===0) return v.plan_id===null&&v.statut==="inconnu"&&v.cause!==null ? v as unknown as MeteoIntervention:null;
 if(v.plan_id===null||v.cause!==null||!["planifiee","en_route"].includes(v.statut_intervention))return null;
 const c=v.creneaux[0];
 if(!objetDispatch(c)||!clesDispatch(c,["intervention_id","equipe","jour","date","debut_min","fin_min","service","statut_intervention","statut","plan_perime","regles","prevision"],["cause","sans_objet","a_configurer"])||
    c.intervention_id!==v.intervention_id||c.statut_intervention!==v.statut_intervention||c.statut!==v.statut||!texteDispatch(c.equipe)||!entierDispatch(c.jour)||
    c.date!==a.date||!entierDispatch(c.debut_min)||!entierDispatch(c.fin_min)||c.debut_min>=c.fin_min||!(c.service===null||texteDispatch(c.service))||
    typeof c.plan_perime!=="boolean"||!Array.isArray(c.regles)||!c.regles.every(r=>objetDispatch(r)&&clesDispatch(r,["risque","statut","detail"])&&typeof r.risque==="string"&&RISQUES.includes(r.risque)&&typeof r.statut==="string"&&STATUTS.includes(r.statut)&&texteDispatch(r.detail))||
    (Object.hasOwn(c,"cause")&&!cause(c.cause))||(Object.hasOwn(c,"sans_objet")&&(!textes(c.sans_objet)||new Set(c.sans_objet).size!==c.sans_objet.length||!c.sans_objet.every(r=>RISQUES.includes(r))))||
    (Object.hasOwn(c,"a_configurer")&&!textes(c.a_configurer)))return null;
 if(c.prevision!==null && (!objetDispatch(c.prevision)||!clesDispatch(c.prevision,["source","emise_le","heure_type"],["saisi_par","reference","licence","forfait","collection","page_meteo"])||
    !Object.values(c.prevision).every(texteDispatch)||!horodatageDispatch(c.prevision.emise_le)))return null;
 const regles=c.regles as unknown as RegleMeteo[], sans=(c.sans_objet??[]) as string[], config=(c.a_configurer??[]) as string[];
 if(regles.some(r=>sans.includes(r.risque)))return null;
 const gravite=regles.some(r=>r.statut==="bloquant")?"bloquant":regles.some(r=>r.statut==="validation_requise")?"validation_requise":
    regles.some(r=>r.statut==="inconnu")||Object.hasOwn(c,"cause")||config.length>0?"inconnu":"ok";
 if(c.statut!==gravite || ((a.date===null||c.service===null)&&c.statut!=="inconnu") ||
    (c.prevision===null&&(c.statut==="bloquant"||c.statut==="validation_requise")))return null;
 if(c.statut==="ok" && (c.date===null||c.service===null||Object.hasOwn(c,"cause")||config.length>0||
    !RISQUES.every(r=>sans.includes(r)||regles.some(x=>x.risque===r))||c.prevision===null&&!RISQUES.every(r=>sans.includes(r))))return null;
 return v as unknown as MeteoIntervention;
}
