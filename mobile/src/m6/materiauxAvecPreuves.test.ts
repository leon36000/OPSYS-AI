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

import refusSQL from "./fixturesRefusPreuvesSQL.json";
function captureRefus(phase:string){
 const stored=refusSQL.captures.find(c=>c.phase===phase);if(!stored)throw new Error("Capture SQL absente");
 expect(createHash("sha256").update(stored.capture_utf8).digest("hex")).toBe(stored.capture_sha256);
 expect(createHash("sha256").update(stored.response_utf8).digest("hex")).toBe(stored.response_sha256);
 const capture=JSON.parse(stored.capture_utf8);expect(capture.response).toEqual(JSON.parse(stored.response_utf8));return capture;
}
function mutationRefusSQL(){
 const c=captureRefus("succes_initial_reponse_perdue");
 return {...mutation(),id:c.request.mutation.idempotencyKey,createdAtLocal:c.request.mutation.deviceTimestamp,
  proprietaire:c.authority.personne,chantierId:c.request.args.formulaire.intervention_id,
  payload:{...c.request.args,_fichiers_locaux:[]}};
}
test.each(["role_retire_preclaim","source_10001_preclaim"])("Cap SQLite %s préclaim conserve UNKNOWN",phase=>{
 const c=captureRefus(phase);expect(c.response.ok).toBe(false);
 expect(c.tables_pair.count).toBe(49);expect(c.tables_pair.changed).toEqual([]);expect(c.artefacts_after).toBe(0);
 expect(interpreterMateriauxAvecPreuves(c.response,mutationRefusSQL())).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});
});
test.each(["REJ-IDENTITE-APPAREIL-INVALIDE","REJ-M6-PREUVES-IDENTITE-INVALIDE"])("identité %s reste incertaine dans les deux enveloppes",code=>{
 const m=mutationRefusSQL();
 for(const r of [{ok:false,erreur:code,details:"FICTIF"},{ok:true,resultat:{accepte:false,verdict:{code,detail:"FICTIF"}}}]){
  expect(interpreterMateriauxAvecPreuves(r,m)).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});
 }
});
test("refus interne frais Cap reste métier certain ; pas de reclassification générique",()=>{
 const c=captureRefus("refus_interne_frais_quota800");expect(c.response.ok).toBe(true);expect(c.response.resultat.accepte).toBe(false);
 expect(c.tables_pair.changed).toEqual(["mutations_appliquees"]);expect(c.artefacts_after).toBe(0);
 expect(interpreterMateriauxAvecPreuves(c.response,mutationRefusSQL())).toEqual({accepte:false,verdict:c.response.resultat.verdict});
 expect(interpreterMateriauxAvecPreuves({ok:false,erreur:"REJ-FICTIF-CERTAIN",details:"FICTIF"},mutationRefusSQL())).toEqual({accepte:false,verdict:{code:"REJ-FICTIF-CERTAIN",detail:"FICTIF"}});
});
test.each([["role_retire_preclaim","role_retabli_cachedsuccess"],["source_10001_preclaim","source_retablie_cachedsuccess"]])(
 "succès Cap perdu puis %s : SDK/dépôt/vidangeur rejouent même intention avant suivante",async(phase,reprise)=>{
 const original=mutationRefusSQL(),source=captureRefus("succes_initial_reponse_perdue"),refuse=captureRefus(phase),replay=captureRefus(reprise);
 expect(replay.response.rejoue).toBe(true);expect(replay.response.resultat).toEqual(source.response.resultat);expect(replay.tables_pair.changed).toEqual([]);
 const d=new DepotOutboxMemoire(),premiere=await d.inserer(original);
 const seconde=await d.inserer({...original,id:"7dd03819-38d9-448a-adab-2452b75d3e95"});
 const ids:string[]=[],bodies:unknown[]=[],stages=[refuse.response,replay.response];let now=new Date("2026-10-08T12:00:00Z");
 const fetchImpl=jest.fn(async(_url:unknown,init?:RequestInit)=>{
  const body=JSON.parse(String(init?.body));bodies.push(body);ids.push(body.idempotencyKey);
  if(ids.length===1||body.idempotencyKey!==original.id)throw new TypeError("FICTIF réponse initiale perdue / aucune capture pour suivante");
  return new Response(JSON.stringify({ok:true,result:stages.shift()}),{status:200});
 });
 const v=creerVidangeur({depot:d,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl,
  session:()=>({urlBase:"https://fictif.invalid",jeton:"FICTIF",appareilId:source.request.mutation.deviceId,personne:original.proprietaire}),
  maintenant:()=>now,verifierAvantEnvoi:async()=>true});
 await v.vidangerFileSortante();now=new Date(now.getTime()+300000);const refus=await v.vidangerFileSortante();
 const apresRefus=await d.obtenir(premiere.id);now=new Date(now.getTime()+300000);await v.vidangerFileSortante();
 expect(ids).toEqual([original.id,original.id,original.id]);expect(bodies[0]).toEqual(bodies[1]);expect(bodies[1]).toEqual(bodies[2]);
 expect(refus.echecsPermanents).toEqual([]);expect(apresRefus).toMatchObject({id:original.id,payload:original.payload,statut:"en_attente"});
 expect(await d.obtenir(premiere.id)).toMatchObject({id:original.id,payload:original.payload,statut:"envoyee",resumeAccepte:{preuves:replay.response.resultat.resultat.preuves}});
 expect(await d.obtenir(seconde.id)).toMatchObject({id:seconde.id,payload:seconde.payload,statut:"en_attente",tentatives:0});
});
