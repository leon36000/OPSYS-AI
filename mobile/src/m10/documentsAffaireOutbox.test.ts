import { creerMutationDocumentM10, argumentsRpcDocumentM10, interpreterDocumentM10, validerRecuDocumentM10, verifierDestinationDocumentM10 } from "./documentsAffaireOutbox";
import type { MutationOutbox } from "../outbox/types";
const origin={personne:"admin.fictif",appareilId:"APP-FICTIF",urlBase:"https://core-fictif.invalid"};
const clock={maintenant:new Date("2026-10-09T12:00:00Z"),decalageMinutesUTC:-240};
const id="00000000-0000-4000-8000-000000000001";
const ref={registre:"documents_affaire",index:0,ligne_id:"b".repeat(64)};
const args={affaire_id:"LEAD-FICTIF",document_ref:null,version_precedente:null,titre:"Pièce é😀",corps:" A\t\r\né😀\u0001\u2028 ",confidentialite:"INTERNAL"};
// RAM vector from real Python idempotence.empreinte_arguments, not a SQL/HTTP DTO capture.
const vectorHash="577ec7b105db8e4683edf560fd6811cccf7b43b816a35ab916a4c20cd5390514";
function mutation(){return creerMutationDocumentM10("deposer",args,()=>id,clock,origin);}
function ack(m:MutationOutbox){return {version_schema:1,operation:"deposer",document_ref:ref,reference:ref,version_source:ref,source_sha256:"23cf543bfea53eec58f44f63f94ed8a5e8f97bd239d37c065181dec048ef57ae",auteur:{personne:origin.personne,role:"admin",source:"appareil"},intention:{appareil:origin.appareilId,cle:m.id,outil:"m10_deposer_version_document_appareil",empreinte_arguments:vectorHash},horodatage_appareil_declare:m.createdAtLocal,horodatage:"2026-10-09T12:00:01+00:00"};}
function frame(m:MutationOutbox){return {ok:true,resultat:{accepte:true,resultat:ack(m)},rejoue:false};}
test("constructeur fige args et destination, heure originale sans .000, clés RPC exactes",()=>{
 const a={...args},o={...origin};const m=creerMutationDocumentM10("deposer",a,()=>id,clock,o);a.corps="ALTÉRÉ";o.personne="autre";
 expect(argumentsRpcDocumentM10(m)).toEqual(args);expect(Object.keys(argumentsRpcDocumentM10(m)!).sort()).toEqual(Object.keys(args).sort());
 expect(m).toMatchObject({id,createdAtLocal:"2026-10-09T08:00:00-04:00",proprietaire:origin.personne,chantierId:"document-m10:LEAD-FICTIF",type:"document_m10_depot"});
 expect(verifierDestinationDocumentM10(m,origin)).toBe(true);expect(verifierDestinationDocumentM10(m,{...origin,urlBase:"https://autre-fictif.invalid"})).toBe(false);
});
test("golden Python Unicode/control/null → own ACK10 admis, UTF8 corps exact",()=>{const m=mutation();expect(interpreterDocumentM10(frame(m),m)).toEqual({accepte:true,resume:ack(m)});});
test.each(["personne","appareil","cle","outil","empreinte","heure","document","source","extra","flag","wrapper"])("ACK étranger/malformé %s reste inconnu",cause=>{
 const m=mutation(),r:any=frame(m);const a=r.resultat.resultat;
 if(cause==="personne")a.auteur.personne="autre";if(cause==="appareil")a.intention.appareil="AUTRE";if(cause==="cle")a.intention.cle="00000000-0000-4000-8000-000000000002";
 if(cause==="outil")a.intention.outil="m10_retirer_document_appareil";if(cause==="empreinte")a.intention.empreinte_arguments="a".repeat(64);if(cause==="heure")a.horodatage_appareil_declare="2026-10-09T12:00:00Z";
 if(cause==="document")a.document_ref={...ref,index:1};if(cause==="source")a.source_sha256="a".repeat(64);if(cause==="extra")a.approbation_id="FAKE";if(cause==="flag")delete r.rejoue;if(cause==="wrapper")r.resultat={accepte:true,resultat:{accepte:true,resultat:a}};
 expect(interpreterDocumentM10(r,m)).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});
});
test.each([{},null,[],{ok:false,erreur:"REFUS"},{ok:true,resultat:{accepte:false,verdict:{code:"REJ"}},rejoue:true}])("toute négation est inconnue sans nouveau UUID",r=>{const m=mutation();expect(interpreterDocumentM10(r,m).accepte).toBe(false);expect(m.id).toBe(id);});
test("getters, prototype, cycles, surrogates, keys supplémentaires ferment sans accès",()=>{
 let calls=0;const hostile={...args};Object.defineProperty(hostile,"corps",{enumerable:true,get(){calls++;throw Error("getter");}});
 for(const a of [hostile,{...args,corps:"\ud800"},{...args,personne:"FAKE"},Object.create(args),{...args,document_ref:{...ref,index:true}}])expect(()=>creerMutationDocumentM10("deposer",a,()=>id,clock,origin)).toThrow();
 expect(calls).toBe(0);const m=mutation();const cycle:any={...m.payload};cycle.commande=cycle;expect(argumentsRpcDocumentM10({...m,payload:cycle})).toBeNull();
});
test("body espaces seul valide, titre Python strip, bornes points et UTF8",()=>{
 expect(()=>creerMutationDocumentM10("deposer",{...args,corps:"  "},()=>id,clock,origin)).not.toThrow();
 expect(()=>creerMutationDocumentM10("deposer",{...args,corps:"😀".repeat(2000),titre:"é".repeat(120)},()=>id,clock,origin)).not.toThrow();
 for(const a of [{...args,corps:"😀".repeat(2001)},{...args,titre:" \u001c "},{...args,titre:"a".repeat(121)},{...args,affaire_id:"LEAD-FICTIF\n"}])expect(()=>creerMutationDocumentM10("deposer",a,()=>id,clock,origin)).toThrow();
});
test("reçu durable admis reste propre après état suivant, sans reconstituer un transport",()=>{
 const m=mutation(),sent={...m,statut:"envoyee" as const,resumeAccepte:ack(m)};expect(validerRecuDocumentM10(sent)).toBe(true);
 expect(validerRecuDocumentM10({...sent,resumeAccepte:null})).toBe(false);expect(validerRecuDocumentM10({...sent,payload:{...m.payload,_document_m10_local:{personne:"autre",appareil_id:origin.appareilId,url_base:origin.urlBase}}})).toBe(false);
});

// Additional Python RAM vectors: correction with reference, activation and withdrawal.
const additionalVectors=[{"args": {"affaire_id": "LEAD-FICTIF", "document_ref": {"registre": "documents_affaire", "index": 7, "ligne_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "version_precedente": {"registre": "documents_affaire", "index": 8, "ligne_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "titre": " Version ", "corps": "  ", "confidentialite": "INTERNAL"}, "canonical_utf8": "{\"affaire_id\":\"LEAD-FICTIF\",\"confidentialite\":\"INTERNAL\",\"corps\":\"  \",\"document_ref\":{\"index\":7,\"ligne_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"registre\":\"documents_affaire\"},\"titre\":\" Version \",\"version_precedente\":{\"index\":8,\"ligne_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"registre\":\"documents_affaire\"}}", "sha256": "c2eb971c50cee35220e6d735c24b4da7ff6497b32cd2869128d13c392ee5e9b4"}, {"args": {"affaire_id": "LEAD-FICTIF", "document_ref": {"registre": "documents_affaire", "index": 7, "ligne_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "version_source": {"registre": "documents_affaire", "index": 8, "ligne_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "activation_attendue": null}, "canonical_utf8": "{\"activation_attendue\":null,\"affaire_id\":\"LEAD-FICTIF\",\"document_ref\":{\"index\":7,\"ligne_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"registre\":\"documents_affaire\"},\"version_source\":{\"index\":8,\"ligne_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"registre\":\"documents_affaire\"}}", "sha256": "525ffced8dedb1295c5a7408a70f12014f16893bcd4917f20eb906041abde9a6"}, {"args": {"affaire_id": "LEAD-FICTIF", "document_ref": {"registre": "documents_affaire", "index": 7, "ligne_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "activation_attendue": {"registre": "documents_affaire", "index": 9, "ligne_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "code_motif": "RETRAIT_ACCES"}, "canonical_utf8": "{\"activation_attendue\":{\"index\":9,\"ligne_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"registre\":\"documents_affaire\"},\"affaire_id\":\"LEAD-FICTIF\",\"code_motif\":\"RETRAIT_ACCES\",\"document_ref\":{\"index\":7,\"ligne_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"registre\":\"documents_affaire\"}}", "sha256": "b31fbe67562296f35515e6477bccc13df4768983e0dbbfa46b1d74b352bdabc3"}];
test.each(additionalVectors)("arguments Python non-null/ref ordre exact : $sha256",v=>{
 const op=Object.hasOwn(v.args,"titre")?"deposer":Object.hasOwn(v.args,"version_source")?"activer":"retirer";
 const m=creerMutationDocumentM10(op,v.args,()=>id,clock,origin);const document=v.args.document_ref!;
 const a={...ack(m),operation:op,document_ref:document,reference:{...ref,index:10},version_source:op==="deposer"?{...ref,index:10}:op==="activer"?(v.args as any).version_source:null,source_sha256:op==="retirer"?null:op==="activer"?"c".repeat(64):"6c179f21e6f62b629055d8ab40f454ed02e48b68563913473b857d3638e23b28",intention:{...ack(m).intention,outil:op==="deposer"?"m10_deposer_version_document_appareil":op==="activer"?"m10_activer_version_document_appareil":"m10_retirer_document_appareil",empreinte_arguments:v.sha256}};
 expect(interpreterDocumentM10({ok:true,resultat:{accepte:true,resultat:a},rejoue:true},m)).toEqual({accepte:true,resume:a});
 const original=argumentsRpcDocumentM10(m);expect(original).toEqual(v.args);
 if(op==="activer")expect(interpreterDocumentM10({ok:true,resultat:{accepte:true,resultat:{...a,version_source:{...ref,index:9}}},rejoue:false},m).accepte).toBe(false);
 if(op==="retirer")expect(interpreterDocumentM10({ok:true,resultat:{accepte:true,resultat:{...a,source_sha256:"c".repeat(64)}},rejoue:false},m).accepte).toBe(false);
 const sent={...m,statut:"envoyee" as const,resumeAccepte:a};expect(validerRecuDocumentM10(sent)).toBe(true);
});
