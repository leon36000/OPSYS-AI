/** RAM/SDK fixtures only: no SQL, DEVICE, Cap or Native proof. */
import { creerMutationDocumentM10 } from "../m10/documentsAffaireOutbox";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { DepotOutboxMemoire } from "./depot";
import { creerVidangeur, type DescripteurTypeMutation } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { MutationOutbox, TypeMutation } from "./types";
const session={personne:"admin.fictif",appareilId:"APP-FICTIF",urlBase:"https://core-fictif.invalid",jeton:"TOKEN-FICTIF"};
const clock={maintenant:new Date("2026-10-09T12:00:00Z"),decalageMinutesUTC:-240};
const ref={registre:"documents_affaire" as const,index:0,ligne_id:"b".repeat(64)};
const args={affaire_id:"LEAD-FICTIF",document_ref:null,version_precedente:null,titre:"Pièce é😀",corps:" A\t\r\né😀\u0001\u2028 ",confidentialite:"INTERNAL"};
const ID1="00000000-0000-4000-8000-000000000001",ID2="00000000-0000-4000-8000-000000000002",ID3="00000000-0000-4000-8000-000000000003";
function m(id=ID1,affaire="LEAD-FICTIF"){return creerMutationDocumentM10("deposer",{...args,affaire_id:affaire},()=>id,clock,session);}
function positive(mutation:MutationOutbox){return {ok:true,rejoue:true,resultat:{accepte:true,resultat:{version_schema:1,operation:"deposer",document_ref:ref,reference:ref,version_source:ref,source_sha256:"23cf543bfea53eec58f44f63f94ed8a5e8f97bd239d37c065181dec048ef57ae",auteur:{personne:session.personne,role:"admin",source:"appareil"},intention:{appareil:session.appareilId,cle:mutation.id,outil:"m10_deposer_version_document_appareil",empreinte_arguments:"577ec7b105db8e4683edf560fd6811cccf7b43b816a35ab916a4c20cd5390514"},horodatage_appareil_declare:mutation.createdAtLocal,horodatage:"2026-10-09T12:00:01+00:00"}}};}
function driver(depot:DepotOutboxMemoire,fetchImpl:jest.Mock,descripteurs=DESCRIPTEURS_MUTATION){return creerVidangeur({depot,descripteurs,appelerOutil:invoquerOutil,fetchImpl,session:()=>session,maintenant:()=>clock.maintenant,verifierAvantEnvoi:async()=>true});}
test.each(["document_m10_depot","document_m10_activation","document_m10_retrait"] as TypeMutation[])("descriptor %s opt-in complet et groupe commun",type=>{
 expect(DESCRIPTEURS_MUTATION.get(type)).toMatchObject({groupeSerie:"documents-m10",serialiserParChantier:true,conserverRefusHttpIncertains:true,verifierAvantEnvoi:true,echecPermanentBloqueSerie:true});
});
test.each([400,401,403,404,408,429,500,503])("HTTP %s conserve UUID/body original et bloque autre opération",async status=>{
 const depot=new DepotOutboxMemoire(),a=await depot.inserer(m()),b=await depot.inserer(creerMutationDocumentM10("activer",{affaire_id:args.affaire_id,document_ref:ref,version_source:ref,activation_attendue:null},()=>ID2,clock,session));
 const f=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit)=>{const r=JSON.parse(String(init?.body));expect(r.idempotencyKey).toBe(a.id);expect(r.args).toEqual(args);expect(r.deviceTimestamp).toBe(a.createdAtLocal);return new Response("{}",{status});});
 await driver(depot,f).vidangerFileSortante();expect(f).toHaveBeenCalledTimes(1);expect(await depot.obtenir(a.id)).toMatchObject({id:a.id,payload:a.payload,statut:"en_attente"});expect(await depot.obtenir(b.id)).toMatchObject({statut:"en_attente",tentatives:0});
});
test("perte réseau puis nouveau vidangeur : même UUID, ACK durable lié, pas nouvel effet derrière pendant passe",async()=>{
 const depot=new DepotOutboxMemoire(),a=await depot.inserer(m()),b=await depot.inserer(m(ID2));
 const lost=jest.fn(async()=>{throw Error("FICTIF response lost");});await driver(depot,lost).vidangerFileSortante();
 const held=await depot.obtenir(a.id);if(!held)throw Error("lost");await depot.mettreAJour({...held,statut:"envoi",prochaineTentativeA:null});
 const f=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit)=>{const r=JSON.parse(String(init?.body));expect(r.idempotencyKey).toBe(a.id);expect(r.args).toEqual(args);return new Response(JSON.stringify({ok:true,result:positive(a)}));});
 const report=await driver(depot,f).vidangerFileSortante();expect(report.envoyees).toEqual([a.id]);expect(f).toHaveBeenCalledTimes(1);expect(await depot.obtenir(b.id)).toMatchObject({statut:"en_attente"});
 const sent=await depot.obtenir(a.id);expect(DESCRIPTEURS_MUTATION.get(a.type)?.validerRecuEnvoye?.(sent!)).toBe(true);
 // A fresh drainer over reconstructed durable rows releases the next intention; no native SQLite claimed.
 const reopened=new DepotOutboxMemoire();for(const row of await depot.lister())await reopened.inserer(JSON.parse(JSON.stringify(row)));
 const next=jest.fn(async()=>new Response(JSON.stringify({ok:true,result:{ok:false,erreur:"FICTIF"}})));await driver(reopened,next).vidangerFileSortante();expect(next).toHaveBeenCalledTimes(1);
});
test.each(["echec_permanent","envoyee"] as const)("état %s sans reçu ne libère aucune des trois opérations",async statut=>{
 const depot=new DepotOutboxMemoire();const a=await depot.inserer({...m(),statut,resumeAccepte:null});
 await depot.inserer(creerMutationDocumentM10("retirer",{affaire_id:args.affaire_id,document_ref:ref,activation_attendue:null,code_motif:"RETRAIT_ACCES"},()=>ID2,clock,session));
 const f=jest.fn(async()=>new Response("{}"));await driver(depot,f).vidangerFileSortante();expect(f).not.toHaveBeenCalled();expect(await depot.obtenir(a.id)).toMatchObject({id:a.id,statut});
});
test("permanent opt-in ne modifie pas terminalité historique",async()=>{
 const depot=new DepotOutboxMemoire();await depot.inserer({...m(),type:"lead_note",statut:"echec_permanent"});await depot.inserer({...m(ID2),type:"lead_note"});
 const descriptors=new Map<TypeMutation,DescripteurTypeMutation>([["lead_note",{tool:"FICTIF",serialiserParChantier:true,interpreterResultat:()=>({accepte:true,resume:{fictif:true}})}]]);
 const f=jest.fn(async()=>new Response(JSON.stringify({ok:true,result:{}})));await driver(depot,f,descriptors).vidangerFileSortante();expect(f).toHaveBeenCalledTimes(1);
});
test("quarantaine autre personne première bloque ; affaire différente garde sa voie",async()=>{
 const depot=new DepotOutboxMemoire();await depot.inserer({...m(),proprietaire:"autre.fictif"});await depot.inserer(m(ID2));await depot.inserer(m(ID3,"AUTRE-FICTIF"));
 const f=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit)=>{expect(JSON.parse(String(init?.body)).idempotencyKey).toBe(ID3);return new Response(JSON.stringify({ok:true,result:{ok:false,erreur:"FICTIF"}}));});
 await driver(depot,f).vidangerFileSortante();expect(f).toHaveBeenCalledTimes(1);
});
test.each(["order","payload","A-B-A"])("changement %s après await interdit nouveau RPC",async cause=>{
 const depot=new DepotOutboxMemoire(),a=await depot.inserer(m());let current=true;
 const f=jest.fn(async()=>new Response("{}"));const v=creerVidangeur({depot,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:f,session:()=>session,maintenant:()=>clock.maintenant,capturerGardeSession:()=>()=>current,verifierAvantEnvoi:async()=>{
 if(cause==="A-B-A")current=false;else{const now=await depot.obtenir(a.id);if(now)await depot.mettreAJour(cause==="order"?{...now,sequence:null}:{...now,payload:{...now.payload,commande:{...args,corps:"CHANGÉ"}}});}return true;}});
 await v.vidangerFileSortante();expect(f).not.toHaveBeenCalled();expect((await depot.obtenir(a.id))?.id).toBe(a.id);
});

test("SQL réel node:sqlite : reçu propre et charge restent durables après fermeture/réouverture connexion",async()=>{
 const {DatabaseSync}=require("node:sqlite") as typeof import("node:sqlite");
 const fs=require("node:fs") as typeof import("node:fs"),os=require("node:os") as typeof import("node:os"),path=require("node:path") as typeof import("node:path");
 const {initialiserSchemaOutbox,creerDepotOutboxSqlite}=require("./depot.sqlite") as typeof import("./depot.sqlite");
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),"m10-outbox-fictif-"));const file=path.join(directory,"outbox.sqlite");let raw:import("node:sqlite").DatabaseSync|undefined;
 const open=()=>{raw=new DatabaseSync(file);const current=raw;return {execAsync:async(sql:string)=>{current.exec(sql);},getAllAsync:async(sql:string,p:any[]=[])=>current.prepare(sql).all(...p),getFirstAsync:async(sql:string,p:any[]=[])=>current.prepare(sql).get(...p)??null,runAsync:async(sql:string,p:any[]=[])=>{current.prepare(sql).run(...p);}} as unknown as import("expo-sqlite").SQLiteDatabase;};
 try{const base=open();await initialiserSchemaOutbox(base);let depot=creerDepotOutboxSqlite(base);const a=await depot.inserer(m());await depot.inserer(m(ID2));const f=jest.fn(async()=>new Response(JSON.stringify({ok:true,result:positive(a)})));
 const v=creerVidangeur({depot,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:f,session:()=>session,maintenant:()=>clock.maintenant,verifierAvantEnvoi:async()=>true});await v.vidangerFileSortante();expect(f).toHaveBeenCalledTimes(1);raw!.close();raw=undefined;
 depot=creerDepotOutboxSqlite(open());const sent=await depot.obtenir(a.id);expect(sent).toMatchObject({id:a.id,payload:a.payload,statut:"envoyee"});expect(DESCRIPTEURS_MUTATION.get(a.type)!.validerRecuEnvoye!(sent!)).toBe(true);
 const next=jest.fn(async()=>new Response(JSON.stringify({ok:true,result:{ok:false,erreur:"FICTIF"}})));const reprise=creerVidangeur({depot,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:next,session:()=>session,maintenant:()=>clock.maintenant,verifierAvantEnvoi:async()=>true});await reprise.vidangerFileSortante();expect(next).toHaveBeenCalledTimes(1);
 const held=await depot.obtenir(ID2);expect(held?.id).toBe(ID2);expect(held?.statut).toBe("en_attente");
 }finally{raw?.close();fs.rmSync(directory,{recursive:true,force:true});}
 // Real SQL/connection reopen only; no new process, ExpoSQLite bridge or physical phone is asserted.
});
