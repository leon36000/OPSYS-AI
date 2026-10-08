import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import type { MutationOutbox } from "../outbox/types";
import type { LigneEnSaisie } from "../ecrans/materials";
import { deduireTypeMimeDepuisUri } from "../fichiers/candidats";
import { construireReferenceFichier } from "../fichiers/protocole";
import { construireArgumentsMateriauxAvecPreuves } from "../m6/materiauxAvecPreuves";
import type { FormulaireMateriauxUtilisesM6 } from "../m6/materiaux";
import type { ArgumentsMateriauxAvecPreuves, FichierPreuveLocal } from "../m6/materiauxAvecPreuves";
export interface PreuveEnSaisie {readonly ligneId:string;readonly note:string;readonly captureIds:readonly string[];}
export interface CapturePreuve {readonly capture_id:string;readonly empreinte_sha256:string;readonly taille_octets:number;readonly type_mime:"image/jpeg"|"image/png";readonly nature:"avant"|"pendant"|"apres";}
/** Sélection de métadonnées locales sous owner/intervention, pas permission ni vérité de scène. */
export function listerCapturesPreuves(mutations:readonly MutationOutbox[],personne:string,intervention:string):CapturePreuve[] {
  const s=copierJsonLecture(mutations);if(s===JSON_LECTURE_INVALIDE||!Array.isArray(s))return [];
  const result:CapturePreuve[]=[];
  for(const m of s){
    if(typeof m!=="object"||m===null||Array.isArray(m)||m.type!=="photo_upload"||m.statut!=="brouillon"||m.proprietaire!==personne||m.chantierId!==intervention||typeof m.id!=="string"||typeof m.payload!=="object"||m.payload===null||Array.isArray(m.payload))continue;
    const p=m.payload,mime=typeof p.uri==="string"?deduireTypeMimeDepuisUri(p.uri):null;
    if(!mime||typeof p.sha256!=="string"||!/^[0-9a-f]{64}$/.test(p.sha256)||typeof p.taille_octets!=="number"||!Number.isSafeInteger(p.taille_octets)||p.taille_octets<1||p.taille_octets>10485760||(p.nature!=="avant"&&p.nature!=="pendant"&&p.nature!=="apres"))continue;
    result.push({capture_id:m.id,empreinte_sha256:p.sha256,taille_octets:p.taille_octets,type_mime:mime,nature:p.nature});
  }
  return result;
}
export function figerPreuvesMateriaux(lignes:readonly LigneEnSaisie[],formulaire:FormulaireMateriauxUtilisesM6,
  notes:readonly PreuveEnSaisie[],captures:readonly CapturePreuve[]):{args:ArgumentsMateriauxAvecPreuves;fichiers:readonly FichierPreuveLocal[]} {
  if(copierJsonLecture([lignes,formulaire,notes,captures])===JSON_LECTURE_INVALIDE)throw new Error("preuves_invalides");
  const preuveIds=new Set(notes.map(n=>n.ligneId));if(preuveIds.size!==notes.length)throw new Error("preuves_invalides");
  const fichiers=new Map<string,FichierPreuveLocal>();
  const preuves=lignes.flatMap((l,position)=>{
    if(l.typeLigne!=="perte"&&l.typeLigne!=="bris")return [];
    const p=notes.find(p=>p.ligneId===l.id);if(!p)throw new Error("preuve_manquante");
    const photos=p.captureIds.map(id=>{
      const c=captures.find(c=>c.capture_id===id);if(!c)throw new Error("capture_indisponible");
      if(!fichiers.has(c.empreinte_sha256))fichiers.set(c.empreinte_sha256,{capture_id:c.capture_id,empreinte_sha256:c.empreinte_sha256,taille_octets:c.taille_octets,type_mime:c.type_mime});
      return construireReferenceFichier(c.empreinte_sha256);
    });return [{position_ligne:position,note:p.note,photos}];
  });
  return {args:construireArgumentsMateriauxAvecPreuves(formulaire,preuves),fichiers:[...fichiers.values()]};
}
