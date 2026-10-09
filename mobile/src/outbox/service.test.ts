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

test.each(["employee", "seller", "url", "appareil", "personne"])("D typed %s ferme la garde du service réel avant SDK", async cause => {
  jest.resetModules();
  const config = require("../protocole/configuration") as typeof import("../protocole/configuration");
  const service = require("./service") as typeof import("./service");
  const adapter = require("../m4/revueCompletionOutbox") as typeof import("../m4/revueCompletionOutbox");
  const cap = require("../m4/fixturesRevueCompletionCapSQL.json") as typeof import("../m4/fixturesRevueCompletionCapSQL.json");
  mockDepot = new DepotOutboxMemoire();
  const origin = { personne: cap.decision.auteur_sql, appareilId: cap.decision.meta.appareil_id, urlBase: "https://fictif.invalid" };
  const definir = (role: string, value = origin) => {
    config.definirConfigurationAppel({ urlBase: value.urlBase, appareilId: value.appareilId, jeton: "JETON-FICTIF" });
    config.definirPersonneConfirmee({ appareilId: value.appareilId, jeton: "JETON-FICTIF", personne: value.personne, role });
  };
  definir("admin"); const depot = await service.obtenirDepot();
  const m = await depot.inserer({ ...adapter.creerMutationDecisionRevueCompletion(cap.decision.arguments, cap.lectures[1].reponse,
    cap.lectures[1].arguments, () => cap.decision.meta.intention_uuid, { maintenant: new Date("2026-10-09T12:00:00Z"), decalageMinutesUTC: 0 }, origin), proprietaire: origin.personne });
  if (cause === "employee" || cause === "seller") definir(cause);
  else definir("admin", { ...origin, ...(cause === "url" ? { urlBase: "https://autre-fictif.invalid" } :
    cause === "appareil" ? { appareilId: "AUTRE-APP-FICTIF" } : { personne: "AUTRE-FICTIF" }) });
  const old = global.fetch, f = jest.fn(async () => new Response("{}", { status: 200 })); global.fetch = f;
  try { await service.declencherVidange(); expect(f).not.toHaveBeenCalled();
    expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente", proprietaire: origin.personne });
  } finally { global.fetch = old; config.definirConfigurationAppel(null); config.definirPersonneConfirmee(null); }
});
