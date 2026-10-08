import { construireArgumentsMateriauxAvecPreuves, interpreterMateriauxAvecPreuves } from "./materiauxAvecPreuves";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
const FICTIF=true;
const form={wct_id:"WCT-FICTIF",intervention_id:"INT-FICTIF",chantier_id:"CHANTIER-FICTIF",lignes_materiaux:[{type_ligne:"perte" as const,materiau_id:"SKU-FICTIF",quantite:2,unite:"pi"}]};
const preuves=[{position_ligne:0,note:"Bris fictif observé\n sans attribution",photos:[]}];
function mutation(){return {...soumettreMutation(creerMutation({type:"materials_submit_with_proofs",chantierId:form.intervention_id,payload:{...construireArgumentsMateriauxAvecPreuves(form,preuves),_fichiers_locaux:[]}},()=>"UUID-FICTIF",{maintenant:new Date("2026-10-08T12:00:00Z"),decalageMinutesUTC:-240})),proprietaire:"EMPLOYEE-FICTIF"};}
// Conception C, fictive RAM ; aucune capture SQL inventée.
function ack(){return {ok:true,resultat:{accepte:true,resultat:{wct_id:form.wct_id,intervention_id:form.intervention_id,chantier_id:form.chantier_id,lignes_declarees:form.lignes_materiaux,preuves:[{position_ligne:0,reference_mouvement:{registre:"principal",index:2,hash_maillon:"a".repeat(64)},reference_preuve:{registre:"preuves_pertes_bris",index:0,hash_maillon:"b".repeat(64)},nombre_photos:0}]},registre:{taille:3,hash_tete:"a".repeat(64)}}};}
test("args3 natifs, note/order verbatim, fictifRAM seulement",()=>{expect(FICTIF).toBe(true);expect(construireArgumentsMateriauxAvecPreuves(form,preuves)).toEqual({wct_id:form.wct_id,formulaire:form,preuves_lignes:preuves});});
test("ACK canonical lié au contexte",()=>{expect(interpreterMateriauxAvecPreuves(ack(),mutation()).accepte).toBe(true);expect(interpreterMateriauxAvecPreuves(ack()).accepte).toBe(false);});
test.each(["wct","position","photoCount","hash","extra"])("%s corrompu conserve intention",cas=>{const r=ack();if(cas==="wct")r.resultat.resultat.wct_id="AUTRE";if(cas==="position")r.resultat.resultat.preuves[0].position_ligne=1;if(cas==="photoCount")r.resultat.resultat.preuves[0].nombre_photos=1;if(cas==="hash")r.resultat.resultat.preuves[0].reference_preuve.hash_maillon="invalide";if(cas==="extra")Reflect.set(r.resultat.resultat,"uri","file:///fictif");expect(interpreterMateriauxAvecPreuves(r,mutation())).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});});
test("transportconfirmation inconnue et getter0",()=>{expect(interpreterMateriauxAvecPreuves({ok:false,erreur:"confirmation_transport_indisponible",issue:"inconnue",details:"Transport fictif"},mutation())).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});let n=0;const r=ack();Object.defineProperty(r.resultat,"accepte",{enumerable:true,get:()=>{n++;return true;}});expect(interpreterMateriauxAvecPreuves(r,mutation()).accepte).toBe(false);expect(n).toBe(0);});

import sql from "./fixturesMateriauxAvecPreuvesSQL.json";
import { createHash } from "node:crypto";
test.each(sql.captures)("confirmation SQL originale $phase liée au contexte persistant",r=>{
 expect(createHash("sha256").update(r.capture_utf8).digest("hex")).toBe(r.capture_sha256);
 expect(createHash("sha256").update(r.response_utf8).digest("hex")).toBe(r.response_sha256);
 const c=JSON.parse(r.capture_utf8),args=construireArgumentsMateriauxAvecPreuves(c.request.args.formulaire,c.request.args.preuves_lignes);
 expect(args).toEqual(c.request.args);expect(JSON.parse(r.response_utf8)).toEqual(c.response);
 const m={...mutation(),id:c.request.mutation.idempotencyKey,proprietaire:c.authority.personne,chantierId:args.formulaire.intervention_id,payload:{...args,_fichiers_locaux:[{capture_id:"CAPTURE-SQL-FICTIVE",empreinte_sha256:args.preuves_lignes[0].photos[0].slice(15),taille_octets:307899,type_mime:"image/png"}]}};
 expect(interpreterMateriauxAvecPreuves(c.response,m).accepte).toBe(true);
});

// Copies négatives explicites de la capture réelle, jamais réécriture de la fixture source.
test.each(["mouvement_position","preuve_index"])("SQL %s incohérent garde UNKNOWN",cas=>{
 const c=JSON.parse(sql.captures[0].capture_utf8),r=JSON.parse(sql.captures[0].response_utf8),args=c.request.args;
 const m={...mutation(),id:c.request.mutation.idempotencyKey,proprietaire:c.authority.personne,chantierId:args.formulaire.intervention_id,payload:{...args,_fichiers_locaux:[{capture_id:"CAPTURE-SQL-FICTIVE",empreinte_sha256:args.preuves_lignes[0].photos[0].slice(15),taille_octets:307899,type_mime:"image/png"}]}};
 if(cas==="mouvement_position")r.resultat.resultat.preuves[0].reference_mouvement.index=0;
 if(cas==="preuve_index")r.resultat.resultat.preuves[0].reference_preuve.index=r.resultat.registre.taille;
 expect(interpreterMateriauxAvecPreuves(r,m)).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});
});

import { validerRecuMateriauxAvecPreuves } from "./materiauxAvecPreuves";
import { DepotOutboxMemoire } from "../outbox/depot";
import { creerVidangeur } from "../outbox/vidangeur";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { invoquerOutil } from "../protocole/client";
function contexteSQL(){
 const c=JSON.parse(sql.captures[0].capture_utf8),args=c.request.args;
 return {...mutation(),id:c.request.mutation.idempotencyKey,proprietaire:c.authority.personne,chantierId:args.formulaire.intervention_id,payload:{...args,_fichiers_locaux:[{capture_id:"CAPTURE-SQL-FICTIVE",empreinte_sha256:args.preuves_lignes[0].photos[0].slice(15),taille_octets:307899,type_mime:"image/png"}]}};
}
test("résumé local conserve le registre reçu ; ancien résultat seul ne prouve pas la géométrie",()=>{
 const m=contexteSQL(),raw=JSON.parse(sql.captures[0].response_utf8),lu=interpreterMateriauxAvecPreuves(raw,m);if(!lu.accepte)throw new Error("Source SQL originale refusée");
 expect(lu.resultat.registre_confirmation).toEqual(raw.resultat.registre);
 expect(validerRecuMateriauxAvecPreuves({...m,statut:"envoyee",resumeAccepte:lu.resultat})).toBe(true);
 expect(validerRecuMateriauxAvecPreuves({...m,statut:"envoyee",resumeAccepte:raw.resultat.resultat})).toBe(false);
 const corrompu=JSON.parse(JSON.stringify(lu.resultat));corrompu.preuves[0].reference_mouvement.index=0;
 expect(validerRecuMateriauxAvecPreuves({...m,statut:"envoyee",resumeAccepte:corrompu})).toBe(false);
});
test.each(["mouvement_position","preuve_index","legacy_envoyee"])("vrai sender %s : intention conservée, suivante bloquée",async cas=>{
 const d=new DepotOutboxMemoire(),original=contexteSQL();const raw=JSON.parse(sql.captures[0].response_utf8);
 if(cas==="mouvement_position")raw.resultat.resultat.preuves[0].reference_mouvement.index=0;
 if(cas==="preuve_index")raw.resultat.resultat.preuves[0].reference_preuve.index=raw.resultat.registre.taille;
 const premiere=await d.inserer(cas==="legacy_envoyee"?{...original,statut:"envoyee",resumeAccepte:raw.resultat.resultat}:original);
 const seconde=await d.inserer({...original,id:"UUID-SUIVANTE-FICTIVE"});
 const fetchImpl=jest.fn(async()=>new Response(JSON.stringify({ok:true,result:raw}),{status:200}));
 const v=creerVidangeur({depot:d,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl,session:()=>({urlBase:"https://fictif.invalid",jeton:"FICTIF",appareilId:"D-FICTIF",personne:original.proprietaire}),maintenant:()=>new Date("2026-10-08T12:00:00Z"),verifierAvantEnvoi:async()=>true});
 expect((await v.vidangerFileSortante()).envoyees).toEqual([]);
 expect(fetchImpl).toHaveBeenCalledTimes(cas==="legacy_envoyee"?0:1);
 expect(await d.obtenir(premiere.id)).toMatchObject({id:premiere.id,payload:premiere.payload,statut:cas==="legacy_envoyee"?"envoyee":"en_attente"});
 expect(await d.obtenir(seconde.id)).toMatchObject({id:seconde.id,payload:seconde.payload,tentatives:0,statut:"en_attente"});
});
