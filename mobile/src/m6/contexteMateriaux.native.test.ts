import { createHash } from "node:crypto";
import fixture from "./fixturesContexteMateriauxNative.json";
import { OUTIL_CONTEXTE_MATERIAUX, construireArgumentsContexteMateriaux, lireContexteMateriaux, estimationEnNombreExact } from "./contexteMateriaux";
import { estObjet } from "../admin/lecteurs";
import { ouvrirEnveloppe } from "../admin/enveloppe";
import { invoquerOutil } from "../protocole/client";
import { classerEchec } from "../protocole/echec";
import type { RequeteOutilsInvoke } from "../protocole/types";
// Native r5 finale scellée : seuls les corps HTTP originaux sont rejoués sur fetch fictif.
// Aucun nouvel HTTP, CAS, provider, téléphone ou rôle confirmé par ce rejeu.
interface Capture { phase:string; status:number; request:RequeteOutilsInvoke & Record<string,unknown>; response:unknown; brut:Record<string,unknown>; rawBody:string }
function estRequete(v:unknown):v is RequeteOutilsInvoke & Record<string,unknown> {
  return estObjet(v)&&typeof v.tool==="string"&&estObjet(v.args)&&["action","sessionKey","agentId","idempotencyKey","deviceId","deviceTimestamp"].every(k=>v[k]===undefined||typeof v[k]==="string");
}
function charger(c:(typeof fixture.captures)[number]):Capture {
  const v:unknown=JSON.parse(c.capture_json_utf8);
  if(!estObjet(v)||v.phase!==c.phase||typeof v.phase!=="string"||typeof v.status!=="number"||!estRequete(v.request)||!Object.hasOwn(v,"response"))throw new Error("Capture publique hors shape SDK : disposition requise sans projection silencieuse");
  return {phase:v.phase,status:v.status,request:v.request,response:v.response,brut:v,rawBody:c.http_body_utf8};
}
const captures=fixture.captures.map(charger);
function formeArguments(c:Capture){
  const a=c.request.args;
  return a && Object.keys(a).sort().join(",")==="decalage,intervention_id,limite,wct_id" ? a : null;
}
function construire(c:Capture){
  const a=formeArguments(c);if(!a)throw new Error("Arguments hors quatre champs, aucun repair");
  if(typeof a.intervention_id!=="string"||typeof a.wct_id!=="string"||typeof a.decalage!=="number"||typeof a.limite!=="number")throw new Error("Types des quatre arguments invalides, aucun repair");
  return construireArgumentsContexteMateriaux(a.intervention_id,a.wct_id,a.decalage,a.limite);
}
function admissibles(c:Capture):boolean {try{construire(c);return true;}catch{return false;}}
function directe(c:Capture){if(!estObjet(c.response)||c.response.ok!==true||!estObjet(c.response.result))throw new Error("HTTP200 Gateway DIRECT attendu");return c.response.result;}

test("originals UTF8 + corps HTTP exacts et SHA individuels",()=>{
  expect(fixture.fictif).toBe(true);expect(new Set(captures.map(c=>c.phase)).size).toBe(captures.length);
  expect(captures).toHaveLength(41);
  expect(fixture.provenance.native_manifest_sha256).toBe("9368837077eeca5136fcc4124f5d04a131ef992cc8ba75ca3d89adec116f1477");
  expect(fixture.provenance.native_proof_sha256).toBe("a285a47ef18ee4059eeeee113f6a00c54cf6de16d023513ca5c3f9d943f9174f");
  expect(fixture.provenance.closure_sha256).toBe("10c62f6cf276a371729ede530945a428301e3bb59c5bf070bb9dd804287ca574");
  expect(fixture.provenance.root_validation_sha256).toBe("cb879f48c24b66552a376eca7eb49857fc6cdb44eee174704027c619ad11298d");
  expect(fixture.captures.every(c=>c.source.kind==="dto_file_byte_copy")).toBe(true);
  expect(captures.filter(c=>c.status===200)).toHaveLength(37);expect(captures.filter(c=>c.status===403)).toHaveLength(3);expect(captures.filter(c=>c.status===401)).toHaveLength(1);
  for(const c of fixture.captures){
    expect(createHash("sha256").update(c.capture_json_utf8,"utf8").digest("hex")).toBe(c.utf8_sha256);
    expect(createHash("sha256").update(c.http_body_utf8,"utf8").digest("hex")).toBe(c.http_body_source.sha256);
    const v=charger(c);expect(JSON.parse(v.rawBody)).toEqual(v.response);expect(v.brut.all_entire_tables_unchanged).toBe(true);
    expect(Buffer.byteLength(v.rawBody,"utf8")).toBe(v.brut.Gateway_HTTP_response_body_bytes);
    expect(c.http_body_source.sha256).toBe(v.brut.Gateway_HTTP_response_body_sha256);
    expect(v.request.tool).toBe(OUTIL_CONTEXTE_MATERIAUX);
  }
});
test.each(captures.map(c=>[c.phase,c] as const))("%s : vraie API client/lecteur, responsebody conservée",async(_phase,c)=>{
  const fetchImpl=jest.fn(async(_url:RequestInfo|URL,_init?:RequestInit)=>new Response(c.rawBody,{status:c.status}));
  if(!admissibles(c)){
    // Application constructor refuses BEFORE fetch. Native deliberately invalid wire remains an independent server observation.
    expect(()=>construire(c)).toThrow();expect(fetchImpl).not.toHaveBeenCalled();
    if(c.status===200){const env=directe(c);expect(ouvrirEnveloppe(env,"directe")).toMatchObject({ok:false});
      expect(Reflect.apply(lireContexteMateriaux,undefined,[env,c.request.args])).toMatchObject({ok:false,code:"reponse_illisible"});}
    // Rejeu DISTINCT de la requête volontairement invalide observée par Native ;
    // l'app n'atteint pas ce fetch, son constructeur a refusé juste au-dessus.
    const fetchHistorique=jest.fn(async(_url:RequestInfo|URL,_init?:RequestInit)=>new Response(c.rawBody,{status:c.status}));
    const historique=await invoquerOutil({fetchImpl:fetchHistorique,urlBase:"https://rejeu-fictif.invalid",jeton:"JETON-REJEU-FICTIF-NON-NATIVE",requete:c.request});
    expect(fetchHistorique).toHaveBeenCalledTimes(1);expect(JSON.parse(String(fetchHistorique.mock.calls[0][1]?.body))).toEqual(c.request);
    expect(historique).toEqual({ok:true,result:directe(c)});return;
  }
  const args=construire(c);expect(args).toEqual(c.request.args);
  const appel=await invoquerOutil({fetchImpl,urlBase:"https://rejeu-fictif.invalid",jeton:"JETON-REJEU-FICTIF-NON-NATIVE",requete:c.request});
  expect(fetchImpl).toHaveBeenCalledTimes(1);
  const body=fetchImpl.mock.calls[0][1]?.body;if(typeof body!=="string")throw new Error("Body SDK absent");
  // La capture JSON structurée garde les extras hostiles. Le SDK courant les sérialise
  // à l’identique ; ceci ne leur donne aucune autorité et ne recrée aucune authentication Native.
  expect(JSON.parse(body)).toEqual(c.request);
  if(c.status!==200){
    expect(appel.ok).toBe(false);if(appel.ok)throw new Error("Refus HTTP ne donne aucun DTO");
    expect(appel.echec).toMatchObject({origine:"http",status:c.status,reessayable:false});expect(classerEchec(appel.echec)).toBe("refuse");expect(appel).not.toHaveProperty("result");
    if(c.status===401){expect(c.response).not.toHaveProperty("ok");expect(appel.echec.erreur).toBeUndefined();}return;
  }
  expect(appel).toEqual({ok:true,result:directe(c)});if(!appel.ok)throw new Error("Result Gateway exact requis");
  const lu=lireContexteMateriaux(appel.result,args),env=directe(c),r=env.resultat;
  if(estObjet(r)&&r.accepte===false&&estObjet(r.verdict))expect(lu).toEqual({ok:false,code:r.verdict.code,detail:r.verdict.detail});
  else if(env.ok===false)expect(lu).toEqual({ok:false,code:env.erreur,detail:env.details});
  else expect(lu).toEqual({ok:true,value:r});
  if(lu.ok)for(const ligne of lu.value.lignes){
    expect(ligne).not.toHaveProperty("quantite_reelle");expect(ligne).not.toHaveProperty("prix");
    const n=estimationEnNombreExact(ligne.quantite_estimee);if(n!==null)expect(Number.isFinite(n)).toBe(true);
  }
});
test("getters/prototypes fermés autour d'un original success sans lecture du getter",()=>{
  const c=captures.find(c=>admissibles(c)&&c.status===200&&lireContexteMateriaux(directe(c),construire(c)).ok);
  if(!c)throw new Error("Succès final capturé requis");const original=directe(c);let lus=0;
  const getter={};Object.defineProperty(getter,"ok",{enumerable:true,get:()=>{lus++;return true;}});
  const proto=Object.assign(Object.create({fictif:true}),original);
  for(const v of [getter,proto])expect(lireContexteMateriaux(v,construire(c))).toMatchObject({ok:false,code:"reponse_illisible"});expect(lus).toBe(0);
});

function capture(phase:string):Capture {const c=captures.find(c=>c.phase===phase);if(!c)throw new Error(`Capture r5 absente : ${phase}`);return c;}
function donnees(phase:string){const c=capture(phase),lu=lireContexteMateriaux(directe(c),construire(c));if(!lu.ok)throw new Error(`DTO r5 illisible : ${phase}/${lu.code}`);return lu.value;}

test("les sept requêtes invalides restent invalides, required et quatre champs seulement",()=>{
  expect(captures.filter(c=>!admissibles(c)).map(c=>c.phase)).toEqual(["limite9","offset10001","offsetnegatif","auteur_arg","agent_arg","null_arg","bool_arg"]);
  for(const phase of ["limite9","offset10001","offsetnegatif","null_arg","bool_arg"]){
    const a=capture(phase).request.args;if(!a)throw new Error("Args Native requis");
    expect(()=>Reflect.apply(construireArgumentsContexteMateriaux,undefined,[a.intervention_id,a.wct_id,a.decalage,a.limite])).toThrow();
  }
  expect(()=>Reflect.apply(construireArgumentsContexteMateriaux,undefined,["I-FICTIF","W-FICTIF"])).toThrow();
});
test("même WCT reçu : M3 provisoire rang0 puis définitif rang1, chantier distinct de l'intervention",()=>{
  const p=donnees("provisoire"),d=donnees("pipeline_reel_employee_own"),admin=donnees("pipeline_reel_admin_actif");
  expect(admin).toEqual(d);expect(p.wct).toEqual(d.wct);
  expect(p.prevu).toMatchObject({statut:"provisoire_estimation_m3",source:{rang:0,reference_m3:{type:"m3.besoins_materiaux"},horodatage:null}});
  expect(p.manques).toEqual(["horodatage_prevu_absent"]);
  expect(d.prevu).toMatchObject({statut:"definitif",source:{rang:1,estimation_id:null,rang_m3:null,bareme_version:null,reference_m3:{type:"m3.devis_accepte"}}});
  expect(d.prevu.source?.horodatage).toBe("2026-10-08T13:55:52-04:00");expect(d.wct.horodatage_completion).toBe("2026-10-09T15:04:30+00:00");
  expect(d.chantier.chantier_id).not.toBe(d.wct.intervention_id);expect(d.chantier.origine).toBe("prevu_m6");
  expect(p.chantier).toEqual({chantier_id:p.wct.intervention_id,origine:"intervention_employee"});
  expect(d.lignes[0]).toEqual({position_source:0,materiau_id:"gouttiere-alu-5po-fictif",unite:"pi",quantite_estimee:"40",origine_quantite:"texte_m3_verifie"});
});
test("absent/vide/date inconnue restent des états sources distincts, aucune complétion utilisée comme date prévue",()=>{
  expect(donnees("absent")).toMatchObject({prevu:{statut:"absent",source:null},lignes:[],manques:["prevu_absent"]});
  expect(donnees("absent_admin_chantier_inconnu").chantier).toEqual({chantier_id:null,origine:"absent_admin"});
  expect(donnees("vide")).toMatchObject({prevu:{statut:"definitif",source:{horodatage:null,reference_m3:null}},lignes:[]});
  const d=donnees("date_inconnue");expect(d.prevu.source?.horodatage).toBeNull();expect(d.manques).toEqual(["horodatage_prevu_absent","provenance_m3_absente"]);
  expect(d.lignes).toHaveLength(1);expect(d.wct.horodatage_completion).not.toBeNull();
});
test("FEFF réellement U+FEFF et grand décimal natif ne sont ni normalisés ni arrondis",()=>{
  const f=donnees("feff").lignes[0];expect(f.materiau_id).toBe("\ufeff");expect(f.unite).toBe("\ufeff");
  const g=donnees("grand").lignes[0];expect(g.quantite_estimee).toBe("1267650600228229401496703205376");
  expect(estimationEnNombreExact(g.quantite_estimee)).toBeNull();expect(g).not.toHaveProperty("quantite_reelle");
  expect(estimationEnNombreExact(donnees("pipeline_reel_employee_own").lignes[0].quantite_estimee)).toBe(40);
});
test("pages courantes, suite et source remplacée gardent uniquement leurs lignes natives",()=>{
  const p=donnees("page_premiere"),s=donnees("page_suivante"),nouvelle=donnees("page_remplacee");
  expect(p.pagination).toEqual({decalage:0,limite:2,affichees:2,total:10,suivant:2,reste:8,courante:true});
  expect(s.pagination).toEqual({decalage:2,limite:2,affichees:2,total:10,suivant:4,reste:6,courante:true});
  expect(p.lignes.map(l=>l.position_source)).toEqual([0,1]);expect(s.lignes.map(l=>l.position_source)).toEqual([2,3]);
  expect(s.lignes.some(l=>p.lignes.some(a=>a.materiau_id===l.materiau_id))).toBe(false);
  expect(p.prevu.source?.empreinte_snapshot).toBe(s.prevu.source?.empreinte_snapshot);
  expect(nouvelle.prevu.source?.empreinte_snapshot).not.toBe(p.prevu.source?.empreinte_snapshot);expect(nouvelle.lignes[0].materiau_id).toBe("MAT-NEUF-FICTIF-0");
  expect(donnees("page_hors_total").pagination).toEqual({decalage:10000,limite:8,affichees:0,total:10,suivant:null,reste:0,courante:true});
  expect(donnees("page_legale_reduite5400").pagination).toEqual({decalage:0,limite:8,affichees:6,total:8,suivant:6,reste:2,courante:true});
});
test("reprise du corps entier et body hostile conservent exactement le résultat observé",()=>{
  const avant=capture("avant_restart_entier"),apres=capture("apres_restart_entier_identique"),fin=capture("finale_ordinaire_exacte");
  expect(apres.request).toEqual(avant.request);expect(apres.rawBody).toBe(avant.rawBody);expect(apres.response).toEqual(avant.response);expect(fin.rawBody).toBe(apres.rawBody);
  const hostile=capture("body_role_agent_auteur_forges");expect(hostile.request).toHaveProperty("role");expect(hostile.request).toHaveProperty("auteur");
  expect(hostile.request).toHaveProperty("agentId");expect(hostile.response).toEqual(capture("pipeline_reel_admin_actif").response);
  // La reproduction SDK de son body complet est vérifiée dans le test paramétré.
  // Seule Native qualifie ici l'absence d'autorité conférée par ces champs.
});
test.each(["admin_role_SQL_retire_avant_M4_bus_M6","employee_role_SQL_retire_avant_M4_bus_M6"])("%s : refus identité nommé sans DTO",phase=>{
  const c=capture(phase),lu=lireContexteMateriaux(directe(c),construire(c));
  expect(lu).toMatchObject({ok:false,code:"REJ-M6-CONTEXTE-IDENTITE-INVALIDE"});expect(lu).not.toHaveProperty("value");
});
test("Cap800 nommé et sources/volume refusés ne deviennent jamais des données partielles",()=>{
  const c=capture("Cap800_refus_named"),env=directe(c);
  expect(env).toEqual({ok:false,erreur:"REJ-M6-CONTEXTE-SORTIE-TROP-VOLUMINEUSE",details:"la lecture dépasse la borne de sortie appareil ; aucun détail partiel n'est transmis"});
  for(const phase of ["source_corrompue","date_invalide","copie_exception","quota10001","sortie5400","WCT_bus_hash_corrompu","Cap800_refus_named"]){
    const x=capture(phase);expect(lireContexteMateriaux(directe(x),construire(x))).toMatchObject({ok:false});
  }
});
