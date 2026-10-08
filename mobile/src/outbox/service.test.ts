import { DepotOutboxMemoire } from "./depot";
import { obtenirDepot, declencherVidange } from "./service";
import { definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { creerMutation,soumettreMutation } from "./mutation";
let mockDepot:DepotOutboxMemoire;
jest.mock("expo-sqlite",()=>({openDatabaseAsync:async()=>({})}));
jest.mock("./depot.sqlite",()=>({initialiserSchemaOutbox:async()=>undefined,creerDepotOutboxSqlite:()=>mockDepot}));
const form={wct_id:"W-FICTIF",intervention_id:"I-FICTIF",chantier_id:"C-FICTIF",lignes_materiaux:[{type_ligne:"perte" as const,materiau_id:"SKU-FICTIF",quantite:1,unite:"pi"}]};
function session(role:string){definirConfigurationAppel({urlBase:"https://core-fictif.invalid",appareilId:"D-FICTIF",jeton:"J-FICTIF"});definirPersonneConfirmee({appareilId:"D-FICTIF",jeton:"J-FICTIF",personne:"P-FICTIF",role});}
test("singleton production : note seule n'exempte pas le rôle, nouvelle passe employee même UUID",async()=>{
 mockDepot=new DepotOutboxMemoire();session("seller");const d=await obtenirDepot();
 const m=await d.inserer(soumettreMutation(creerMutation({type:"materials_submit_with_proofs",chantierId:form.intervention_id,payload:{wct_id:form.wct_id,formulaire:form,preuves_lignes:[{position_ligne:0,note:"FICTIF note seule",photos:[]}],_fichiers_locaux:[]}},()=>"UUID-NOTE-FICTIF",{maintenant:new Date("2026-10-08T12:00:00Z"),decalageMinutesUTC:-240})));
 const precedent=global.fetch;const fetchMock=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit)=>{
  const r=JSON.parse(String(init?.body));expect(r.idempotencyKey).toBe(m.id);expect(Object.keys(r.args).sort()).toEqual(["formulaire","preuves_lignes","wct_id"]);
  return new Response(JSON.stringify({ok:true,result:{ok:true,resultat:{accepte:true,resultat:{wct_id:form.wct_id,intervention_id:form.intervention_id,chantier_id:form.chantier_id,lignes_declarees:form.lignes_materiaux,preuves:[{position_ligne:0,reference_mouvement:{registre:"principal",index:0,hash_maillon:"a".repeat(64)},reference_preuve:{registre:"preuves_pertes_bris",index:0,hash_maillon:"b".repeat(64)},nombre_photos:0}]},registre:{taille:1,hash_tete:"a".repeat(64)}}}}),{status:200});
 });global.fetch=fetchMock;
 try {
  await declencherVidange();expect(fetchMock).not.toHaveBeenCalled();expect(await d.obtenir(m.id)).toMatchObject({id:m.id,payload:m.payload,statut:"en_attente"});
  session("employee");const r=await d.obtenir(m.id);if(!r)throw new Error("Intention perdue");await d.mettreAJour({...r,prochaineTentativeA:null});
  expect((await declencherVidange())?.envoyees).toEqual([m.id]);expect(fetchMock).toHaveBeenCalledTimes(1);
 } finally {global.fetch=precedent;definirConfigurationAppel(null);definirPersonneConfirmee(null);}
});
