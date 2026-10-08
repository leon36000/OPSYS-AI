import { DepotOutboxMemoire } from "./depot";
import { creerMutation, soumettreMutation } from "./mutation";
import { creerVidangeur } from "./vidangeur";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { invoquerOutil } from "../protocole/client";
import { construireArgumentsMateriauxAvecPreuves } from "../m6/materiauxAvecPreuves";
const h={maintenant:new Date("2026-10-08T12:00:00Z"),decalageMinutesUTC:-240};
const form={wct_id:"W-FICTIF",intervention_id:"I-FICTIF",chantier_id:"C-FICTIF",lignes_materiaux:[{type_ligne:"perte" as const,materiau_id:"SKU-FICTIF",quantite:1,unite:"pi"}]};
const preuves=[{position_ligne:0,note:"Fictif",photos:[]}];
function ack(){return {ok:true,resultat:{accepte:true,resultat:{wct_id:form.wct_id,intervention_id:form.intervention_id,chantier_id:form.chantier_id,lignes_declarees:form.lignes_materiaux,preuves:[{position_ligne:0,reference_mouvement:{registre:"principal",index:0,hash_maillon:"a".repeat(64)},reference_preuve:{registre:"preuves_pertes_bris",index:0,hash_maillon:"b".repeat(64)},nombre_photos:0}]},registre:{taille:1,hash_tete:"a".repeat(64)}}};}
async function insere(d:DepotOutboxMemoire,id:string,type:"materials_submit"|"materials_submit_with_proofs"="materials_submit_with_proofs"){
 const payload=type==="materials_submit"?{wct_id:form.wct_id,formulaire:form}:{...construireArgumentsMateriauxAvecPreuves(form,preuves),_fichiers_locaux:[]};
 return d.inserer({...soumettreMutation(creerMutation({type,chantierId:form.intervention_id,payload},()=>id,h)),proprietaire:"P-FICTIF"});
}
function config(d:DepotOutboxMemoire,ready:boolean){const fetchImpl=jest.fn(async(_url:RequestInfo|URL,_init?:RequestInit)=>new Response(JSON.stringify({ok:true,result:ack()}),{status:200}));const verifierAvantEnvoi=jest.fn(async()=>ready);return {fetchImpl,verifierAvantEnvoi,v:creerVidangeur({depot:d,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl,session:()=>({urlBase:"https://fictif.invalid",jeton:"FICTIF",appareilId:"D-FICTIF",personne:"P-FICTIF"}),maintenant:()=>h.maintenant,verifierAvantEnvoi})};}
test("barrière false zéro RPC déclaration, mêmeUUID et payload retained",async()=>{const d=new DepotOutboxMemoire(),m=await insere(d,"NEW-FICTIF"),c=config(d,false);const r=await c.v.vidangerFileSortante();expect(c.fetchImpl).not.toHaveBeenCalled();expect(c.verifierAvantEnvoi).toHaveBeenCalledTimes(1);expect(r.envoyees).toEqual([]);expect(await d.obtenir(m.id)).toMatchObject({id:m.id,payload:m.payload,statut:"en_attente"});});
test("ancienM6enrecul bloque nouveau groupe, même sansdependsOn",async()=>{const d=new DepotOutboxMemoire(),old=await insere(d,"OLD-FICTIF","materials_submit");await d.mettreAJour({...old,prochaineTentativeA:"2099-01-01T00:00:00Z"});const m=await insere(d,"NEW-FICTIF"),c=config(d,true);await c.v.vidangerFileSortante();expect(c.fetchImpl).not.toHaveBeenCalled();expect((await d.obtenir(m.id))?.statut).toBe("en_attente");});
test("UNKNOWN bloque l'intention suivante et survive à une nouvelle passe",async()=>{
 const d=new DepotOutboxMemoire(),premiere=await insere(d,"PREMIERE-FICTIVE"),seconde=await insere(d,"SECONDE-FICTIVE"),c=config(d,true);
 c.fetchImpl.mockImplementation(async()=>new Response(JSON.stringify({ok:true,result:{ok:true,statut:"en_attente_approbation",demande_id:"D-FICTIVE"}}),{status:200}));
 await c.v.vidangerFileSortante();expect(c.fetchImpl).toHaveBeenCalledTimes(1);
 expect(await d.obtenir(premiere.id)).toMatchObject({id:premiere.id,payload:premiere.payload,statut:"en_attente"});expect((await d.obtenir(seconde.id))?.tentatives).toBe(0);
 await config(d,true).v.vidangerFileSortante();expect((await d.obtenir(seconde.id))?.tentatives).toBe(0);
});
test("rôle retiré pendant la barrière ne déclenche aucune déclaration",async()=>{
 const d=new DepotOutboxMemoire(),m=await insere(d,"ROLE-FICTIF");let actuelle=true;
 const c=config(d,true);const v=creerVidangeur({depot:d,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:c.fetchImpl,session:()=>({urlBase:"https://fictif.invalid",jeton:"FICTIF",appareilId:"D-FICTIF",personne:"P-FICTIF"}),maintenant:()=>h.maintenant,capturerGardeSession:()=>()=>actuelle,verifierAvantEnvoi:async()=>{actuelle=false;return true;}});
 await v.vidangerFileSortante();expect(c.fetchImpl).not.toHaveBeenCalled();expect(await d.obtenir(m.id)).toMatchObject({id:m.id,payload:m.payload,statut:"en_attente"});
});
test("un reçu ancien mal lié n'ouvre pas le groupe commun",async()=>{
 const d=new DepotOutboxMemoire(),old=await insere(d,"LEGACY-FICTIF","materials_submit");await d.mettreAJour({...old,statut:"envoyee",resumeAccepte:{intervention_id:"AUTRE",chantier_id:form.chantier_id,lignes_declarees:form.lignes_materiaux}});
 await insere(d,"NOUVELLE-FICTIVE");const c=config(d,true);await c.v.vidangerFileSortante();expect(c.fetchImpl).not.toHaveBeenCalled();expect((await d.obtenir(old.id))?.statut).toBe("envoyee");
});
test("payload modifié durant une barrière ne remplace pas la nouvelle donnée par l'ancienne",async()=>{
 const d=new DepotOutboxMemoire(),m=await insere(d,"IMMUTABLE-FICTIF"),c=config(d,true);const change={...m.payload,preuves_lignes:[{position_ligne:0,note:"CHANGÉ FICTIF",photos:[]}]};
 const v=creerVidangeur({depot:d,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:c.fetchImpl,session:()=>({urlBase:"https://fictif.invalid",jeton:"FICTIF",appareilId:"D-FICTIF",personne:"P-FICTIF"}),maintenant:()=>h.maintenant,verifierAvantEnvoi:async()=>{const r=await d.obtenir(m.id);if(!r)throw new Error();await d.mettreAJour({...r,payload:change});return true;}});
 await v.vidangerFileSortante();expect(c.fetchImpl).not.toHaveBeenCalled();expect((await d.obtenir(m.id))?.payload).toEqual(change);
});

import capturesSQL from "../m6/fixturesMateriauxAvecPreuvesSQL.json";
test.each(capturesSQL.captures)("$phase SQL : vrai SDK/descripteur/drainer, arguments natifs seulement",async r=>{
 const capture=JSON.parse(r.capture_utf8),d=new DepotOutboxMemoire();
 const m=await d.inserer({...soumettreMutation(creerMutation({type:"materials_submit_with_proofs",chantierId:capture.request.args.formulaire.intervention_id,payload:{...capture.request.args,_fichiers_locaux:[{capture_id:"CAPTURE-SQL-FICTIVE",empreinte_sha256:capture.request.args.preuves_lignes[0].photos[0].slice(15),taille_octets:307899,type_mime:"image/png"}]}},()=>capture.request.mutation.idempotencyKey,h)),proprietaire:capture.authority.personne});
 const fetchImpl=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit)=>{const body=JSON.parse(String(init?.body));expect(body.args).toEqual(capture.request.args);expect(body.idempotencyKey).toBe(m.id);return new Response(`{"ok":true,"result":${r.response_utf8}}`,{status:200});});
 const v=creerVidangeur({depot:d,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl,session:()=>({urlBase:"https://core-fictif.invalid",jeton:"FICTIF",appareilId:capture.request.mutation.appareil,personne:capture.authority.personne}),maintenant:()=>h.maintenant,verifierAvantEnvoi:async()=>true}); // Readiness testée séparément avec les octets scellés et état serveur.
 expect((await v.vidangerFileSortante()).envoyees).toEqual([m.id]);expect(fetchImpl).toHaveBeenCalledTimes(1);expect((await d.obtenir(m.id))?.payload).toEqual(m.payload);
});
test("lecture de dépôt hostile après la barrière : getter zéro, aucun RPC ni effacement",async()=>{
 const d=new DepotOutboxMemoire(),m=await insere(d,"GETTER-FICTIF"),c=config(d,true);let hostile=false,n=0;
 const depot={lister:()=>d.lister(),inserer:d.inserer.bind(d),mettreAJour:d.mettreAJour.bind(d),obtenir:async(id:string)=>{
  const r=await d.obtenir(id);if(!r||!hostile)return r;const copie={...r};Object.defineProperty(copie,"payload",{enumerable:true,get:()=>{n++;return r.payload;}});return copie;
 }};
 const v=creerVidangeur({depot,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:c.fetchImpl,session:()=>({urlBase:"https://fictif.invalid",jeton:"FICTIF",appareilId:"D-FICTIF",personne:"P-FICTIF"}),maintenant:()=>h.maintenant,verifierAvantEnvoi:async()=>{hostile=true;return true;}});
 await v.vidangerFileSortante();expect(c.fetchImpl).not.toHaveBeenCalled();expect(n).toBe(0);expect(await d.obtenir(m.id)).toMatchObject({id:m.id,payload:m.payload});
});
