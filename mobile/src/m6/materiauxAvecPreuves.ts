import type { MutationOutbox } from "../outbox/types";
import type { FormulaireMateriauxUtilisesM6, LigneDeclareeChantierM6, TypeLigneMateriaux } from "./materiaux";
import { TYPES_LIGNE_MATERIAUX } from "./materiaux";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
export const OUTIL_MATERIAUX_AVEC_PREUVES="m6_declarer_materiaux_avec_preuves_appareil";
export interface PreuveLigneMateriaux {readonly position_ligne:number;readonly note:string;readonly photos:readonly string[];}
export interface ArgumentsMateriauxAvecPreuves {readonly wct_id:string;readonly formulaire:FormulaireMateriauxUtilisesM6;readonly preuves_lignes:readonly PreuveLigneMateriaux[];}
export interface FichierPreuveLocal {readonly capture_id:string;readonly empreinte_sha256:string;readonly taille_octets:number;readonly type_mime:"image/jpeg"|"image/png";}
export interface ReferencePreuveM6 {readonly registre:"principal"|"preuves_pertes_bris";readonly index:number;readonly hash_maillon:string;}
export interface ConfirmationMateriauxAvecPreuves {readonly wct_id:string;readonly intervention_id:string;readonly chantier_id:string;readonly lignes_declarees:readonly LigneDeclareeChantierM6[];readonly preuves:readonly {readonly position_ligne:number;readonly reference_mouvement:ReferencePreuveM6;readonly reference_preuve:ReferencePreuveM6;readonly nombre_photos:number;}[];}
/** Copie locale de métadonnées réellement reçues : ni argument RPC, ni permission/signature. */
export interface RegistreConfirmationMateriaux {readonly taille:number;readonly hash_tete:string;}
export interface RecuMateriauxAvecPreuves extends ConfirmationMateriauxAvecPreuves {readonly registre_confirmation:RegistreConfirmationMateriaux;}
export type InterpretationMateriauxAvecPreuves={readonly accepte:true;readonly resultat:RecuMateriauxAvecPreuves}|{readonly accepte:false;readonly verdict:{readonly code:string;readonly detail:string}};
const inconnu:InterpretationMateriauxAvecPreuves={accepte:false,verdict:{code:"accuse_invalide",detail:"Confirmation des preuves inconnue ou non liée : même intention conservée."}};
const obj=(v:unknown):v is Record<string,unknown>=>typeof v==="object"&&v!==null&&!Array.isArray(v);
const ferme=(v:unknown,keys:readonly string[]):v is Record<string,unknown>=>obj(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const id=(v:unknown):v is string=>typeof v==="string"&&[...v].length<=256&&v.replace(/\p{White_Space}/gu,"").length>0&&!/[\p{Cc}\p{Cs}]/u.test(v);
const hash=(v:unknown):v is string=>typeof v==="string"&&/^[0-9a-f]{64}$/.test(v);
const entier=(v:unknown,max=Number.MAX_SAFE_INTEGER):v is number=>typeof v==="number"&&Number.isSafeInteger(v)&&v>=0&&v<=max;
const quantite=(v:unknown):v is number=>typeof v==="number"&&Number.isFinite(v)&&v>0&&(!Number.isInteger(v)||Number.isSafeInteger(v));
export function notePreuveValide(v:unknown):v is string {return typeof v==="string"&&[...v].length>=1&&[...v].length<=500&&v.replace(/\p{White_Space}/gu,"").length>0&&!/[^\P{Cc}\t\r\n]|\p{Cs}/u.test(v);}
function ligne(v:unknown):v is LigneDeclareeChantierM6 {
  if(!obj(v)||!TYPES_LIGNE_MATERIAUX.some(t=>t===v.type_ligne)||v.type_ligne==="achat_terrain")return false;
  const keys=["type_ligne","materiau_id","quantite","unite",...(v.type_ligne==="prevu"?["quantite_estimee"]:[])];
  return ferme(v,keys)&&id(v.materiau_id)&&id(v.unite)&&quantite(v.quantite)&&(v.type_ligne!=="prevu"||quantite(v.quantite_estimee));
}
function argumentsValides(v:unknown):ArgumentsMateriauxAvecPreuves|null {
  if(!ferme(v,["wct_id","formulaire","preuves_lignes"])||!id(v.wct_id)||!ferme(v.formulaire,["wct_id","intervention_id","chantier_id","lignes_materiaux"]))return null;
  const f=v.formulaire;
  if(f.wct_id!==v.wct_id||!id(f.intervention_id)||!id(f.chantier_id)||!Array.isArray(f.lignes_materiaux)||f.lignes_materiaux.length<1||f.lignes_materiaux.length>24||!f.lignes_materiaux.every(ligne)||!Array.isArray(v.preuves_lignes)||v.preuves_lignes.length>8)return null;
  const attendues=f.lignes_materiaux.flatMap((l,i)=>(l.type_ligne==="perte"||l.type_ligne==="bris")?[i]:[]),vues=new Set<number>(),preuves:PreuveLigneMateriaux[]=[];
  for(const p of v.preuves_lignes){
    if(!ferme(p,["position_ligne","note","photos"])||!entier(p.position_ligne,23)||!attendues.includes(p.position_ligne)||vues.has(p.position_ligne)||!notePreuveValide(p.note)||!Array.isArray(p.photos)||p.photos.length>3||!p.photos.every((r):r is string=>typeof r==="string"&&/^fichier:sha256:[0-9a-f]{64}$/.test(r))||new Set(p.photos).size!==p.photos.length)return null;
    vues.add(p.position_ligne);preuves.push({position_ligne:p.position_ligne,note:p.note,photos:p.photos});
  }
  if(vues.size!==attendues.length)return null;
  return {wct_id:v.wct_id,formulaire:{wct_id:v.wct_id,intervention_id:f.intervention_id,chantier_id:f.chantier_id,lignes_materiaux:f.lignes_materiaux},preuves_lignes:preuves};
}
export function construireArgumentsMateriauxAvecPreuves(formulaire:FormulaireMateriauxUtilisesM6,preuves:readonly PreuveLigneMateriaux[]):ArgumentsMateriauxAvecPreuves {
  const s=copierJsonLecture([formulaire,preuves]);
  const a=s===JSON_LECTURE_INVALIDE||!Array.isArray(s)||!obj(s[0])?null:argumentsValides({wct_id:s[0].wct_id,formulaire:s[0],preuves_lignes:s[1]});if(!a)throw new Error("Plan de preuves invalide.");return a;
}
export function lireChargeMateriauxAvecPreuves(mutation:unknown):{readonly args:ArgumentsMateriauxAvecPreuves;readonly fichiers:readonly FichierPreuveLocal[]}|null {
  const s=copierJsonLecture(mutation);
  if(s===JSON_LECTURE_INVALIDE||!obj(s)||s.type!=="materials_submit_with_proofs"||!id(s.id)||!id(s.proprietaire)||!ferme(s.payload,["wct_id","formulaire","preuves_lignes","_fichiers_locaux"]))return null;
  const p=s.payload,a=argumentsValides({wct_id:p.wct_id,formulaire:p.formulaire,preuves_lignes:p.preuves_lignes});
  if(!a||s.chantierId!==a.formulaire.intervention_id||!Array.isArray(p._fichiers_locaux)||p._fichiers_locaux.length>24)return null;
  const fichiers:FichierPreuveLocal[]=[],refs=new Set(a.preuves_lignes.flatMap(p=>p.photos));
  for(const f of p._fichiers_locaux){
    if(!ferme(f,["capture_id","empreinte_sha256","taille_octets","type_mime"])||!id(f.capture_id)||!hash(f.empreinte_sha256)||!entier(f.taille_octets,10485760)||f.taille_octets===0||(f.type_mime!=="image/jpeg"&&f.type_mime!=="image/png")||!refs.has(`fichier:sha256:${f.empreinte_sha256}`))return null;
    fichiers.push({capture_id:f.capture_id,empreinte_sha256:f.empreinte_sha256,taille_octets:f.taille_octets,type_mime:f.type_mime});
  }
  if(new Set(fichiers.map(f=>f.capture_id)).size!==fichiers.length||new Set(fichiers.map(f=>f.empreinte_sha256)).size!==fichiers.length||fichiers.length!==refs.size)return null;
  return {args:a,fichiers};
}
export function argumentsRpcMateriauxAvecPreuves(m:MutationOutbox):Readonly<Record<string,unknown>>|null {const c=lireChargeMateriauxAvecPreuves(m);return c?{...c.args}:null;}
function ref(v:unknown,registre:ReferencePreuveM6["registre"]):v is ReferencePreuveM6{return ferme(v,["registre","index","hash_maillon"])&&v.registre===registre&&entier(v.index)&&hash(v.hash_maillon);}
function confirmation(v:unknown,a:ArgumentsMateriauxAvecPreuves,taille:number,locale=false):ConfirmationMateriauxAvecPreuves|null {
  if(taille<a.formulaire.lignes_materiaux.length||!ferme(v,["wct_id","intervention_id","chantier_id","lignes_declarees","preuves",...(locale?["registre_confirmation"]:[])])||v.wct_id!==a.wct_id||v.intervention_id!==a.formulaire.intervention_id||v.chantier_id!==a.formulaire.chantier_id||!Array.isArray(v.lignes_declarees)||!v.lignes_declarees.every(ligne)||v.lignes_declarees.length!==a.formulaire.lignes_materiaux.length||!Array.isArray(v.preuves)||v.preuves.length!==a.preuves_lignes.length)return null;
  for(let i=0;i<v.lignes_declarees.length;i++){const l=v.lignes_declarees[i],e=a.formulaire.lignes_materiaux[i];if(Object.keys(l).some(k=>Reflect.get(l,k)!==Reflect.get(e,k)))return null;}
  const preuves:ConfirmationMateriauxAvecPreuves["preuves"][number][]=[],mouvements=new Set<number>(),liens=new Set<number>();
  for(let i=0;i<v.preuves.length;i++){const p=v.preuves[i],e=a.preuves_lignes[i];
    if(!ferme(p,["position_ligne","reference_mouvement","reference_preuve","nombre_photos"])||p.position_ligne!==e.position_ligne||p.nombre_photos!==e.photos.length||!ref(p.reference_mouvement,"principal")||!ref(p.reference_preuve,"preuves_pertes_bris")||p.reference_mouvement.index!==taille-a.formulaire.lignes_materiaux.length+e.position_ligne||p.reference_preuve.index>=taille||mouvements.has(p.reference_mouvement.index)||liens.has(p.reference_preuve.index))return null;
    mouvements.add(p.reference_mouvement.index);liens.add(p.reference_preuve.index);preuves.push({position_ligne:e.position_ligne,reference_mouvement:p.reference_mouvement,reference_preuve:p.reference_preuve,nombre_photos:e.photos.length});
  }
  return {wct_id:a.wct_id,intervention_id:a.formulaire.intervention_id,chantier_id:a.formulaire.chantier_id,lignes_declarees:v.lignes_declarees,preuves};
}
export function interpreterMateriauxAvecPreuves(brut:unknown,mutation?:MutationOutbox):InterpretationMateriauxAvecPreuves {
  const s=copierJsonLecture(brut),charge=lireChargeMateriauxAvecPreuves(mutation);
  if(s===JSON_LECTURE_INVALIDE||!obj(s)||!charge)return inconnu;
  const keys=Object.hasOwn(s,"rejoue")?["ok","resultat","rejoue"]:["ok","resultat"];
  if(Object.hasOwn(s,"rejoue")&&typeof s.rejoue!=="boolean")return inconnu;
  if(s.ok===false){
    if(!ferme(s,["ok","erreur","details",...(Object.hasOwn(s,"rejoue")?["rejoue"]:[])])||typeof s.erreur!=="string"||typeof s.details!=="string"||!/^REJ-[A-Z0-9]+(?:-[A-Z0-9]+)*$/.test(s.erreur)||s.erreur==="REJ-IDENTITE-APPAREIL-INVALIDE")return inconnu;
    return {accepte:false,verdict:{code:s.erreur,detail:s.details}};
  }
  if(!ferme(s,keys)||s.ok!==true||!obj(s.resultat))return inconnu;const m=s.resultat;
  if(m.accepte===false){const v=m.verdict;if(!ferme(m,["accepte","verdict"])||!obj(v)||typeof v.code!=="string"||!/^REJ-[A-Z0-9]+(?:-[A-Z0-9]+)*$/.test(v.code)||v.code==="REJ-IDENTITE-APPAREIL-INVALIDE"||typeof v.detail!=="string"||!ferme(v,["code","detail",...(Object.hasOwn(v,"statut")?["statut"]:[])]))return inconnu;return {accepte:false,verdict:{code:v.code,detail:v.detail}};}
  if(!ferme(m,["accepte","resultat","registre"])||m.accepte!==true||!ferme(m.registre,["taille","hash_tete"])||!entier(m.registre.taille)||!hash(m.registre.hash_tete))return inconnu;
  const taille=m.registre.taille;const c=confirmation(m.resultat,charge.args,taille);if(!c)return inconnu;
  return {accepte:true,resultat:{...c,registre_confirmation:{taille,hash_tete:m.registre.hash_tete}}};
}
export function validerRecuMateriauxAvecPreuves(m:MutationOutbox):boolean {
  const s=copierJsonLecture(m),c=lireChargeMateriauxAvecPreuves(m);
  if(s===JSON_LECTURE_INVALIDE||!obj(s)||s.statut!=="envoyee"||!c||!obj(s.resumeAccepte))return false;
  const r=s.resumeAccepte.registre_confirmation;
  return ferme(r,["taille","hash_tete"])&&entier(r.taille)&&hash(r.hash_tete)&&confirmation(s.resumeAccepte,c.args,r.taille,true)!==null;
}
