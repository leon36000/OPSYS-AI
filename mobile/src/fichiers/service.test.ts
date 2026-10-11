import type { NetInfoState } from "@react-native-community/netinfo";
import NetInfo, { NetInfoStateType } from "@react-native-community/netinfo";
import { File } from "expo-file-system";
import * as Crypto from "expo-crypto";
import { obtenirDepot } from "../outbox/service";
import { createHash } from "node:crypto";
import { DepotOutboxMemoire } from "../outbox/depot";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import { creerVidangeur } from "../outbox/vidangeur";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionMateriauxLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import capturesSQL from "./fixturesDepotFichierSQL.json";
import { calculerEtatEnvoiFichier } from "./etatEnvoi";

jest.mock("expo-file-system", () => ({File:class { async bytes(){return new Uint8Array();} },Paths:{document:{uri:"file:///document/"}}}));
jest.mock("expo-crypto", () => ({CryptoDigestAlgorithm:{SHA256:"SHA256"},digest:jest.fn()}));
jest.mock("@react-native-community/netinfo", () => ({__esModule:true,NetInfoStateType:{unknown:"unknown",other:"other",none:"none"},default:{fetch:jest.fn(),addEventListener:jest.fn()}}));
jest.mock("../outbox/id", () => ({genererMutationId:()=>"UUID-BLOC-FICTIF"}));
jest.mock("../outbox/service", () => ({obtenirDepot:jest.fn()}));
import { creerServiceEnvoiFichiers, uriFichierGere, envoyerFichiersDuChantier } from "./service";
import type { DepotOutbox } from "../outbox/depot";
const PERSONNE="file.ack.employee.fictif", APPAREIL="FILE-ACK-APPAREIL-FICTIF", JETON="JETON-FICTIF";
const URI="file:///document/opsys-photos/INTERV-FICTIVE/apres/00000000-0000-4000-8000-000000000010.png";
const HORLOGE={maintenant:new Date("2026-10-08T00:00:00-04:00"),decalageMinutesUTC:-240};
interface CaptureSQL {request:{args:Record<string,unknown>};response:unknown;}
function capture(phase:string) { const r=capturesSQL.captures.find(c=>c.phase===phase);if(!r)throw new Error(phase);const data:CaptureSQL=JSON.parse(r.capture_utf8);return {row:r,data}; }
const premiers=capture("first-partial"),derniers=capture("second-complete");
function octetsPNG():Uint8Array<ArrayBuffer> {
  const a=premiers.data.request.args.bloc_base64,b=derniers.data.request.args.bloc_base64;
  if(typeof a!=="string"||typeof b!=="string")throw new Error("Blocs source manquants");
  return Uint8Array.from(Buffer.concat([Buffer.from(a,"base64"),Buffer.from(b,"base64")]));
}
function session() {
  definirConfigurationAppel({urlBase:"https://fictif.invalid",jeton:JETON,appareilId:APPAREIL});
  definirPersonneConfirmee({jeton:JETON,appareilId:APPAREIL,personne:PERSONNE,role:"employee"});
}
function digest(octets:Uint8Array<ArrayBuffer>):Promise<ArrayBuffer> {return Promise.resolve(Uint8Array.from(createHash("sha256").update(Buffer.from(octets)).digest()).buffer);}
afterEach(()=>{definirConfigurationAppel(null);definirPersonneConfirmee(null);});
async function preparer(phase="complete-state") {
  session();const depot=new DepotOutboxMemoire();
  const photo=await depot.inserer({...creerMutation({type:"photo_upload",chantierId:"INTERV-FICTIVE",payload:{nature:"apres",uri:URI,
    sha256:capturesSQL.image_provenance.image_sha256,taille_octets:capturesSQL.image_provenance.bytes}},()=>"CAPTURE-FICTIVE",HORLOGE),proprietaire:PERSONNE});
  let ligne=true,epoch=0;const fermer=jest.fn();
  const corps=capture(phase).row.response_utf8;
  const fetchImpl=jest.fn(async (_input:RequestInfo|URL,_init?:RequestInit)=>new Response(`{"ok":true,"result":${corps}}`,{status:200}));
  const lireOctets=jest.fn(async(_uri:string)=>octetsPNG());const hacher=jest.fn(digest);
  const d={capturerSession:capturerSessionMateriauxLecture,capturerReseau:async()=>{const version=epoch;return {enLigne:ligne,courante:()=>ligne&&version===epoch,fermer};},
    obtenirDepot:async():Promise<DepotOutbox>=>depot,lireOctets,digest:hacher,genererId:()=>"UUID-BLOC-FICTIF",horloge:()=>HORLOGE,
    documentUri:()=>"file:///document/",appelerOutil:invoquerOutil,fetchImpl};
  return {depot,photo,d,fetchImpl,lireOctets,hacher,fermer,reseau:(v:boolean)=>{if(v!==ligne)epoch++;ligne=v;}};
}
describe("B1 fichiers readiness — composants réels, transport/FS/natifs fictifs",()=>{
  test("PNG307899 réel scellé +état complet : pret live, aucune clé/réconciliation nouvelle",async()=>{
    const c=await preparer();const r=await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE");
    expect(r[0].resultat).toEqual({ok:true,pret:true,blocsEnfiles:0});expect(c.lireOctets).toHaveBeenCalledTimes(1);expect(c.hacher).toHaveBeenCalledTimes(1);
    expect(c.fetchImpl).toHaveBeenCalledTimes(1);expect(await c.depot.lister()).toHaveLength(1);expect(c.fermer).toHaveBeenCalledTimes(1);
    const args=JSON.parse(String(c.fetchImpl.mock.calls[0][1]?.body));expect(args.args).toEqual({empreinte_sha256:capturesSQL.image_provenance.image_sha256});
    expect(args.tool).toBe("m4_etat_fichier");expect(args.deviceId).toBe(APPAREIL);expect(args.idempotencyKey).toBeUndefined();
  });
  test("état partiel puis vrai sender ACK complet, puis live complet après reprise",async()=>{
    const c=await preparer("partial-state-requested-hash");const r=await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE");
    expect(r[0].resultat).toEqual({ok:true,pret:false,blocsEnfiles:1});
    const bloc=(await c.depot.lister()).find(m=>m.type==="fichier_bloc");if(!bloc)throw new Error("Bloc absent");
    expect(bloc.payload).toEqual(derniers.data.request.args);
    const fetchImpl=jest.fn(async()=>new Response(`{"ok":true,"result":${derniers.row.response_utf8}}`,{status:200}));
    const sender=creerVidangeur({depot:c.depot,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl,
      session:()=>({urlBase:"https://fictif.invalid",jeton:JETON,appareilId:APPAREIL,personne:PERSONNE}),maintenant:()=>HORLOGE.maintenant});
    expect((await sender.vidangerFileSortante()).envoyees).toEqual([bloc.id]);
    const reprise=new DepotOutboxMemoire();for(const row of await c.depot.lister())await reprise.inserer(row);
    const complet=capture("complete-state").row.response_utf8;
    const d={...c.d,obtenirDepot:async()=>reprise,fetchImpl:jest.fn(async()=>new Response(`{"ok":true,"result":${complet}}`,{status:200}))};
    expect((await creerServiceEnvoiFichiers(d).envoyer("INTERV-FICTIVE"))[0].resultat).toMatchObject({ok:true,pret:true,blocsEnfiles:0});
    expect((await reprise.lister()).find(m=>m.type==="fichier_bloc")?.id).toBe(bloc.id);
    expect((await reprise.obtenir(bloc.id))?.resumeAccepte).toMatchObject({genre:"etat_fichier"});
    // Un seul bloc local n'atteste pas tous les indices, mais l'observation live peut être complète.
    expect(calculerEtatEnvoiFichier(await reprise.lister(),"INTERV-FICTIVE",capturesSQL.image_provenance.image_sha256).statut).toBe("en_cours");
  });
  test.each(["role-removed-state","unknown-state"])("%s ne produit ni prêt ni nouvelle clé legacy",async phase=>{
    const c=await preparer(phase);
    const legacy=await c.depot.inserer({...soumettreMutation(creerMutation({type:"fichier_bloc",chantierId:"INTERV-FICTIVE",payload:derniers.data.request.args},()=>"UUID-LEGACY-FICTIF",HORLOGE)),proprietaire:PERSONNE});
    await c.depot.mettreAJour({...legacy,statut:"envoyee",resumeAccepte:null});
    const r=await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE");expect(r[0].resultat.pret).toBe(false);
    expect((await c.depot.lister()).map(m=>m.id)).toEqual([c.photo.id,legacy.id]);expect((await c.depot.obtenir(legacy.id))?.resumeAccepte).toBeNull();
  });
  test.each(["role","token","personne","URL","réseau","focus","capture"])("%s change pendant lecture locale : zéro query état",async genre=>{
    const c=await preparer();let focus=true;
    c.lireOctets.mockImplementation(async()=>{
      if(genre==="role")definirPersonneConfirmee({jeton:JETON,appareilId:APPAREIL,personne:PERSONNE,role:"seller"});
      if(genre==="token")definirConfigurationAppel({urlBase:"https://fictif.invalid",jeton:"AUTRE-FICTIF",appareilId:APPAREIL});
      if(genre==="personne")definirPersonneConfirmee({jeton:JETON,appareilId:APPAREIL,personne:"AUTRE-FICTIF",role:"employee"});
      if(genre==="URL")definirConfigurationAppel({urlBase:"https://autre-fictif.invalid",jeton:JETON,appareilId:APPAREIL});
      if(genre==="réseau"){c.reseau(false);c.reseau(true);}
      if(genre==="focus")focus=false;
      if(genre==="capture")await c.depot.mettreAJour({...c.photo,payload:{...c.photo.payload,uri:URI.replace(".png",".jpg")}});
      return octetsPNG();
    });
    const r=await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE",()=>focus);
    expect(r[0].resultat).toMatchObject({pret:false,raison:"contexte_change"});expect(c.fetchImpl).not.toHaveBeenCalled();expect(c.fermer).toHaveBeenCalledTimes(1);
  });
  test("changement pendant query état ne réconcilie pas sous nouvelle autorité",async()=>{
    const c=await preparer();c.fetchImpl.mockImplementation(async()=>{
      definirPersonneConfirmee({jeton:JETON,appareilId:APPAREIL,personne:PERSONNE,role:"seller"});
      return new Response(`{"ok":true,"result":${capture("complete-state").row.response_utf8}}`,{status:200});
    });
    expect((await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE"))[0].resultat).toMatchObject({pret:false,raison:"contexte_change"});
    expect(await c.depot.lister()).toHaveLength(1);
  });
  test("capture d'un autre owner ou owner inconnu reste en quarantaine",async()=>{
    const c=await preparer();await c.depot.mettreAJour({...c.photo,proprietaire:null});
    expect(await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE")).toEqual([]);expect(c.lireOctets).not.toHaveBeenCalled();
    expect((await c.depot.obtenir(c.photo.id))?.proprietaire).toBeNull();
  });
});
describe("URI fichier géré (aucun FS réel)",()=>{
  test("photo et signature admises, UUID fichier distinct capture",()=>{
    expect(uriFichierGere(URI,"INTERV-FICTIVE","image/png","file:///document/")).toBe(true);
    expect(uriFichierGere(URI.replace("opsys-photos/INTERV-FICTIVE/apres","opsys-signatures/INTERV-FICTIVE"),"INTERV-FICTIVE","image/png","file:///document/")).toBe(true);
  });
  test.each([URI.replace("/apres/","/../"),URI.replace("/apres/","/%2e%2e/"),URI.replace("INTERV-FICTIVE","AUTRE"),
    URI.replace("file:","https:"),URI+"?auth=fictif",URI+"#fictif",URI.replace("/apres/","/avant/"),URI.replace("/document/","/document-autre/")])("URI hors scope %s",uri=>{
    expect(uriFichierGere(uri,"INTERV-FICTIVE","image/png","file:///document/")).toBe(false);
  });
});

// Façade de production réellement utilisée, seuls les adaptateurs natifs sont remplacés.
describe("façade native — capture avant bootstrap",()=>{
  const online:NetInfoState={type:NetInfoStateType.other,isConnected:true,isInternetReachable:true,details:{isConnectionExpensive:false}};
  test("câblage FS/Crypto/SDK et écoute NetInfo, suppression du listener après observation",async()=>{
    const c=await preparer(),stop=jest.fn(),ancien=global.fetch;
    jest.mocked(obtenirDepot).mockResolvedValue(c.depot);
    jest.spyOn(File.prototype,"bytes").mockResolvedValue(octetsPNG());
    jest.mocked(Crypto.digest).mockImplementation(async(_algorithm,bytes)=>{if(!(bytes instanceof Uint8Array))throw new Error("Octets attendus");return digest(new Uint8Array(bytes));});
    jest.mocked(NetInfo.fetch).mockResolvedValue(online);jest.mocked(NetInfo.addEventListener).mockImplementation(listener=>{listener(online);return stop;});
    global.fetch=c.fetchImpl;
    try {expect((await envoyerFichiersDuChantier("INTERV-FICTIVE"))[0].resultat.pret).toBe(true);expect(stop).toHaveBeenCalledTimes(1);}
    finally {global.fetch=ancien;}
  });
  test("role retiré pendant fetch réseau : dépôt/FS/HTTP non lus",async()=>{
    await preparer();jest.mocked(obtenirDepot).mockClear();
    jest.mocked(NetInfo.addEventListener).mockReturnValue(()=>undefined);
    jest.mocked(NetInfo.fetch).mockImplementation(async()=>{definirPersonneConfirmee({jeton:JETON,appareilId:APPAREIL,personne:PERSONNE,role:"seller"});return online;});
    expect(await envoyerFichiersDuChantier("INTERV-FICTIVE")).toEqual([]);expect(obtenirDepot).not.toHaveBeenCalled();
  });
});

describe("B1 dernières frontières await, erreurs explicites",()=>{
  test("A→B→A rôle même tuple pendant bootstrap ferme la première capture",async()=>{
    const c=await preparer();const d={...c.d,obtenirDepot:async()=>{
      definirPersonneConfirmee({jeton:JETON,appareilId:APPAREIL,personne:PERSONNE,role:"seller"});
      definirPersonneConfirmee({jeton:JETON,appareilId:APPAREIL,personne:PERSONNE,role:"employee"});return c.depot;
    }};
    expect(await creerServiceEnvoiFichiers(d).envoyer("INTERV-FICTIVE")).toEqual([]);expect(c.lireOctets).not.toHaveBeenCalled();
  });
  test("file getter entier ferme avant tout accès/FS",async()=>{
    const c=await preparer();let appels=0;const hostile={...c.photo};
    Object.defineProperty(hostile,"payload",{enumerable:true,get:()=>{appels++;return c.photo.payload;}});
    const d={...c.d,obtenirDepot:async()=>({lister:async()=>[hostile],obtenir:(id:string)=>c.depot.obtenir(id),inserer:c.depot.inserer.bind(c.depot),mettreAJour:c.depot.mettreAJour.bind(c.depot),mettreAJourSiInchangee:c.depot.mettreAJourSiInchangee.bind(c.depot)})};
    await expect(creerServiceEnvoiFichiers(d).envoyer("INTERV-FICTIVE")).rejects.toThrow("illisibles");
    expect(appels).toBe(0);expect(c.lireOctets).not.toHaveBeenCalled();expect(c.fermer).toHaveBeenCalledTimes(1);
  });
  test("source état refus identité code/detail verbatim, aucune permission locale supprimée/inventée",async()=>{
    const c=await preparer("role-removed-state");
    const r=(await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE"))[0].resultat;
    expect(r).toMatchObject({ok:false,pret:false,raison:"etat_refuse",verdict:{code:"REJ-IDENTITE-APPAREIL-INVALIDE"}});
    expect(await c.depot.lister()).toHaveLength(1);
  });
  test("octets manquants ou taille discordante conservés, jamais query/prêt",async()=>{
    const c=await preparer();c.lireOctets.mockRejectedValue(new Error("Fichier fictif absent"));
    expect((await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE"))[0].resultat).toMatchObject({pret:false,raison:"echec_lecture"});
    c.lireOctets.mockResolvedValue(new Uint8Array(1));
    expect((await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE"))[0].resultat).toMatchObject({pret:false,raison:"taille_discordante"});
    expect(c.fetchImpl).not.toHaveBeenCalled();expect(await c.depot.lister()).toHaveLength(1);
  });
  test("écoute native ferme sur réseau aller-retour pendant hash",async()=>{
    const c=await preparer(),ancien=global.fetch;let signal: ((s:NetInfoState)=>void)|undefined;
    const online:NetInfoState={type:NetInfoStateType.other,isConnected:true,isInternetReachable:true,details:{isConnectionExpensive:false}};
    jest.mocked(NetInfo.fetch).mockResolvedValue(online);jest.mocked(NetInfo.addEventListener).mockImplementation(l=>{signal=l;l(online);return ()=>undefined;});
    jest.mocked(obtenirDepot).mockResolvedValue(c.depot);jest.spyOn(File.prototype,"bytes").mockResolvedValue(octetsPNG());
    jest.mocked(Crypto.digest).mockImplementation(async(_a,bytes)=>{
      signal?.({type:NetInfoStateType.none,isConnected:false,isInternetReachable:false,details:null});signal?.(online);
      if(!(bytes instanceof Uint8Array))throw new Error("Octets attendus");return digest(new Uint8Array(bytes));
    });global.fetch=c.fetchImpl;
    try {expect((await envoyerFichiersDuChantier("INTERV-FICTIVE"))[0].resultat).toMatchObject({pret:false,raison:"contexte_change"});expect(c.fetchImpl).not.toHaveBeenCalled();}
    finally {global.fetch=ancien;}
  });
});

test("PNG sous URI JPEG/même SHA : pas de prêt sans cohérence MIME des octets locaux",async()=>{
  const c=await preparer();await c.depot.mettreAJour({...c.photo,payload:{...c.photo.payload,uri:URI.replace(".png",".jpg")}});
  const r=await creerServiceEnvoiFichiers(c.d).envoyer("INTERV-FICTIVE");
  expect(r[0].resultat).toMatchObject({pret:false,raison:"type_non_permis"});expect(c.fetchImpl).not.toHaveBeenCalled();
});

// B2 barrière multi-fichiers : vrais lecteur/SDK/orchestrateur/sender, états RAM explicitement fictifs.
test("deux CAS : un état inconnu empêche la déclaration puis reprise même UUID une fois tous prêts",async()=>{
 const c=await preparer(),hashA=String(c.photo.payload.sha256),bytesB=octetsPNG();bytesB[bytesB.length-1]^=1;
 const hashB=createHash("sha256").update(bytesB).digest("hex"),uriB=URI.replace("000000000010","000000000011");
 const photoB=await c.depot.inserer({...c.photo,id:"CAPTURE-B-FICTIVE",sequence:null,payload:{...c.photo.payload,uri:uriB,sha256:hashB,nature:"avant"}});
 // L'URI et la nature doivent rester cohérentes ; choisir pendant/avant ne sélectionne pas automatiquement.
 await c.depot.mettreAJour({...photoB,payload:{...photoB.payload,uri:uriB.replace("/apres/","/avant/")}});
 c.lireOctets.mockImplementation(async uri=>uri.includes("000000000011")?bytesB:octetsPNG());
 let secondPret=false,declares=0;
 c.fetchImpl.mockImplementation(async(_u,init)=>{
  const req=JSON.parse(String(init?.body));if(req.tool!=="m4_etat_fichier"){declares++;return new Response(JSON.stringify({ok:true,result:{}}),{status:200});}
  const sha=req.args.empreinte_sha256;if(sha===hashB&&!secondPret)return new Response(JSON.stringify({ok:true,result:{}}),{status:200});
  return new Response(JSON.stringify({ok:true,result:{ok:true,resultat:{accepte:true,resultat:{existe:true,complet:true,blocs_recus:[0,1],reference:`fichier:sha256:${sha}`}}}}),{status:200});
 });
 const fichiers=[{capture_id:c.photo.id,empreinte_sha256:hashA,taille_octets:307899,type_mime:"image/png" as const},{capture_id:photoB.id,empreinte_sha256:hashB,taille_octets:307899,type_mime:"image/png" as const}];
 const form={wct_id:"W-MULTI-FICTIF",intervention_id:"INTERV-FICTIVE",chantier_id:"C-FICTIF",lignes_materiaux:[{type_ligne:"perte" as const,materiau_id:"SKU-FICTIF",quantite:1,unite:"pi"}]};
 const m=await c.depot.inserer({...soumettreMutation(creerMutation({type:"materials_submit_with_proofs",chantierId:"INTERV-FICTIVE",payload:{wct_id:form.wct_id,formulaire:form,preuves_lignes:[{position_ligne:0,note:"FICTIF",photos:fichiers.map(f=>`fichier:sha256:${f.empreinte_sha256}`)}],_fichiers_locaux:fichiers}},()=>"M-MULTI-FICTIF",HORLOGE)),proprietaire:PERSONNE});
 const service=creerServiceEnvoiFichiers(c.d);
 const sender=creerVidangeur({depot:c.depot,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:c.fetchImpl,session:()=>({urlBase:"https://fictif.invalid",jeton:JETON,appareilId:APPAREIL,personne:PERSONNE}),maintenant:()=>new Date("2099-01-01T00:00:00Z"),verifierAvantEnvoi:async(_m,_s,garde)=>{
   const r=await service.envoyerSelection("INTERV-FICTIVE",fichiers,garde);return r.length===2&&r.every(f=>f.resultat.pret);
 }});
 await sender.vidangerFileSortante();expect(declares).toBe(0);expect(await c.depot.obtenir(m.id)).toMatchObject({id:m.id,payload:m.payload,statut:"en_attente"});
 secondPret=true; // Reprise distincte, pas une permission gardée depuis la première observation.
 const reprise=await c.depot.obtenir(m.id);if(!reprise)throw new Error("Intention perdue");await c.depot.mettreAJour({...reprise,prochaineTentativeA:null});
 await sender.vidangerFileSortante();expect(declares).toBe(1);expect((await c.depot.obtenir(m.id))?.payload).toEqual(m.payload);
});
