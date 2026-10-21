/** Fictive RAM/SDK transport vectors. No SQL/Cap/backend execution is represented here. */
import { DepotOutboxMemoire } from "./depot";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerVidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { MutationOutbox, TypeMutation } from "./types";
const api = () => require("../m5/obligationsPreparees") as Record<string, (...args: any[]) => any>;
const type = "obligation_preparee" as TypeMutation;
const args = { categorie: "paies", operation: "declarer", declaration: { montant: null, source: null, au: null, echeance: null, calendrier: null }, revision_attendue: null, motif: "FICTIF" };
const session = { personne: "ADMIN-FICTIF", appareilId: "DEVICE-FICTIF", urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF" };
const ID1 = "4e1b7c25-918d-4b70-bcc5-885a2c6a7ab9", ID2 = "f6106514-51d2-4c1a-964f-f7a080a290f1";
const h = { maintenant: new Date("2026-10-09T12:00:00.123Z"), decalageMinutesUTC: -240 };
beforeEach(() => {
  for (const name of ["creerMutationObligationPreparee", "argumentsRpcObligationPreparee", "verifierDestinationObligationPreparee", "interpreterObligationPreparee", "validerRecuObligationPreparee"]) expect(typeof api()[name]).toBe("function");
});
function m(id = ID1, a = args): MutationOutbox { return api().creerMutationObligationPreparee(a, () => id, h, session); }
function positive(mutation: MutationOutbox) {
  const a = api().argumentsRpcObligationPreparee(mutation);
  const value = { categorie: a.categorie, etat_declaration: a.operation === "declarer" ? "DECLAREE" : "RETIREE", declaration: a.declaration,
    reference: { registre: "obligations_preparees", index: 0, ligne_id: "a".repeat(64), precedent_ligne_id: null }, revision_precedente: a.revision_attendue,
    auteur: { personne: session.personne, role: "admin", source: "appareil" }, intention: { appareil_id: session.appareilId, intention_uuid: mutation.id,
      empreinte_arguments: api().empreinteArgumentsObligation(a) }, enregistree_le: "2026-10-09T12:00:01.123456+00:00", horodatage_appareil_declare: mutation.createdAtLocal };
  return { ok: true, rejoue: true, resultat: { accepte: true, version_schema: 1, resultat: value, registre: "obligations_preparees" } };
}
test("descriptor serializes only this category, retains uncertain HTTP and validates local own receipt", () => {
  const d = DESCRIPTEURS_MUTATION.get(type);
  expect(d).toMatchObject({ tool: "m5_enregistrer_obligation_preparee_appareil", groupeSerie: "obligation-m5", serialiserParChantier: true,
    conserverRefusHttpIncertains: true, verifierAvantEnvoi: true });
  const mutation = m(); expect(mutation.chantierId).toBe("obligation-m5:paies"); expect(mutation.proprietaire).toBe(session.personne);
  expect(d?.construireArguments?.(mutation)).toEqual(args);
  expect(JSON.stringify(mutation.payload)).not.toContain(session.jeton); expect(Object.keys(d!.construireArguments!(mutation)!).sort()).toEqual(Object.keys(args).sort());
});
test.each(["personne", "appareilId", "urlBase"])("original %s stays fixed and a changed destination is quarantined", key => {
  const mutation = m(); const changed = { ...session, [key]: "FOREIGN-FICTIF" };
  expect(api().verifierDestinationObligationPreparee(mutation, session)).toBe(true);
  expect(api().verifierDestinationObligationPreparee(mutation, changed)).toBe(false);
  expect(api().argumentsRpcObligationPreparee(mutation)).toEqual(args);
});
test("getters are refused before mutation construction or UUID generation", () => {
  const id = jest.fn(() => ID1), getter = jest.fn(() => session.personne), s = { ...session };
  Object.defineProperty(s, "personne", { get: getter, enumerable: true });
  expect(() => api().creerMutationObligationPreparee(args, id, h, s)).toThrow(); expect(getter).not.toHaveBeenCalled(); expect(id).not.toHaveBeenCalled();
});
test.each([
  { ok: false, erreur: "REJ-M5-OBLIGATIONS-IDENTITE-INVALIDE", details: "FICTIF" },
  { ok: true, resultat: { accepte: false, verdict: { code: "REJ-M5-OBLIGATIONS-REVISION-PERIMEE", detail: "FICTIF" } } },
  { ok: false, erreur: "budget_epuise", details: "FICTIF" }, {}, { ok: true, resultat: { accepte: true, resultat: {} } },
])("no unproved refusal or malformed ACK releases the intention", response => {
  expect(api().interpreterObligationPreparee(response, m())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("the persisted positive receipt is checked before series release", () => {
  const mutation = m(), good = positive(mutation).resultat.resultat;
  expect(api().validerRecuObligationPreparee({ ...mutation, statut: "envoyee", resumeAccepte: good })).toBe(true);
  expect(api().validerRecuObligationPreparee({ ...mutation, statut: "envoyee", resumeAccepte: { ...good, intention: { ...good.intention, intention_uuid: ID2 } } })).toBe(false);
});
test("lost confirmation then unproved refusal blocks next; original UUID/body survives drainer restart", async () => {
  const depot = new DepotOutboxMemoire(); let now = h.maintenant;
  const first = await depot.inserer(m()), next = await depot.inserer(m(ID2));
  const fetchImpl = jest.fn().mockRejectedValueOnce(new Error("FICTIF confirmation lost, no backend effect claim"))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: { accepte: false, verdict: { code: "REJ-M5-OBLIGATIONS-REVISION-PERIMEE", detail: "FICTIF" } } } })))
    .mockImplementation(async () => new Response(JSON.stringify({ ok: true, result: positive(first) })));
  const create = () => creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
    session: () => session, maintenant: () => now, verifierAvantEnvoi: async (mutation, s) => api().verifierDestinationObligationPreparee(mutation, s) });
  expect((await create().vidangerFileSortante()).remisesEnAttente).toEqual([first.id]); now = new Date(now.getTime() + 60000);
  expect((await create().vidangerFileSortante()).remisesEnAttente).toEqual([first.id]);
  expect(fetchImpl).toHaveBeenCalledTimes(2); expect((await depot.obtenir(next.id))?.statut).toBe("en_attente");
  expect((await depot.obtenir(first.id))?.payload).toEqual(first.payload); now = new Date(now.getTime() + 60000);
  expect((await create().vidangerFileSortante()).envoyees).toContain(first.id);
  const bodies = fetchImpl.mock.calls.slice(0, 3).map(call => JSON.parse(String(call[1].body)));
  expect(bodies[0]).toEqual(bodies[1]); expect(bodies[1]).toEqual(bodies[2]);
  expect(bodies[0]).toMatchObject({ args, idempotencyKey: first.id, deviceId: session.appareilId, deviceTimestamp: first.createdAtLocal });
  expect((await depot.obtenir(first.id))?.statut).toBe("envoyee");
});
test.each([400, 401, 403, 404, 500])("HTTP %s after dispatch is not proof of no prior effect", async status => {
  const depot = new DepotOutboxMemoire(), first = await depot.inserer(m()), next = await depot.inserer(m(ID2));
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ error: "FICTIF" }), { status }));
  const v = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl, session: () => session,
    maintenant: () => h.maintenant, verifierAvantEnvoi: async (mutation, s) => api().verifierDestinationObligationPreparee(mutation, s) });
  const rapport = await v.vidangerFileSortante();
  if (status === 401) expect(rapport.arret).toMatchObject({ genre: "appareil_refuse", mutationId: first.id, status: 401 });
  else expect(rapport.remisesEnAttente).toEqual([first.id]);
  expect(fetchImpl).toHaveBeenCalledTimes(1);
  expect((await depot.obtenir(first.id))?.statut).toBe("en_attente");
  expect((await depot.obtenir(first.id))?.payload).toEqual(first.payload);
  expect((await depot.obtenir(first.id))?.id).toBe(first.id);
  expect((await depot.obtenir(next.id))?.statut).toBe("en_attente");
});

test("a persisted receipt with a getter is rejected without executing that getter",()=> {
 const getter=jest.fn(()=>"envoyee"),mutation=m();const bad=Object.defineProperty({...mutation,resumeAccepte:positive(mutation).resultat.resultat},"statut",{get:getter,enumerable:true});
 expect(api().validerRecuObligationPreparee(bad)).toBe(false);expect(getter).not.toHaveBeenCalled();
});

/** Fictive SDK replay of captured actual Cap envelopes, never an actual HTTP/back-end call. */
const cap = require("../m5/fixturesObligationsPrepareesCapSQL.json");
const phase=(n:string)=>cap.captures.find((c:any)=>c.name===n);
function mutationCap(c:any):MutationOutbox {
 const cible={personne:c.request.identite_injectee.personne,appareilId:c.request.meta.appareil,urlBase:"https://fictif.invalid"};
 const m=api().creerMutationObligationPreparee(c.request.arguments,()=>c.request.meta.cle,{maintenant:new Date("2026-10-09T12:00:00.000Z"),decalageMinutesUTC:-240},cible);
 // Injected persisted transport fixture: preserve actual captured Meta text, not the clock formatter.
 return {...m,createdAtLocal:c.request.meta.horodatage_appareil};
}
test.each(["declaration-positive","rejeu-propre","revision-positive","rejeu-v1-apres-v2","retrait-positif","autre-auteur-das","rejeu-v1-apres-retrait-redemarrage"])("actual Cap own positive %s validates persisted local receipt without current-head inference",name=> {
 const c=phase(name),m=mutationCap(c),r=api().interpreterObligationPreparee(c.enveloppe,m);expect(r.accepte).toBe(true);
 expect(api().validerRecuObligationPreparee({...m,statut:"envoyee",resumeAccepte:r.resume})).toBe(true);
});
test.each(["revision-perimee","rejeu-refus-inconnu","quota-fresh-800","quota-rejeu-550","rejeu-role-revoque"])("actual Cap %s stays unknown without an independent own negative proof",name=> {
 const c=phase(name);expect(api().interpreterObligationPreparee(c.enveloppe,mutationCap(c))).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});
});
test("captured quota/role then own historical replay keep original body and block the next category intent",async()=> {
 const firstCapture=phase("declaration-positive"),sessionCap={personne:firstCapture.request.identite_injectee.personne,appareilId:firstCapture.request.meta.appareil,urlBase:"https://fictif.invalid",jeton:"JETON-FICTIF"};
 const depot=new DepotOutboxMemoire(),first=await depot.inserer(mutationCap(firstCapture)),next=await depot.inserer({...mutationCap(firstCapture),id:ID2});let now=new Date("2026-10-09T12:00:00.000Z");
 const replies=["quota-rejeu-550","rejeu-role-revoque","rejeu-v1-apres-retrait-redemarrage"],fetchImpl=jest.fn().mockRejectedValueOnce(new Error("FICTIF confirmation lost; no SDK backend effect claimed"));
 for(const name of replies)fetchImpl.mockResolvedValueOnce(new Response(JSON.stringify({ok:true,result:phase(name).enveloppe})));
 fetchImpl.mockResolvedValue(new Response(JSON.stringify({ok:true,result:{ok:false,erreur:"FICTIF"}})));
 const create=()=>creerVidangeur({depot,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl,session:()=>sessionCap,maintenant:()=>now,verifierAvantEnvoi:async(m,s)=>api().verifierDestinationObligationPreparee(m,s)});
 for(let i=0;i<3;i++){expect((await create().vidangerFileSortante()).remisesEnAttente).toEqual([first.id]);expect((await depot.obtenir(next.id))?.statut).toBe("en_attente");now=new Date(now.getTime()+60000);}
 expect((await create().vidangerFileSortante()).envoyees).toContain(first.id);
 const bodies=fetchImpl.mock.calls.slice(0,4).map(call=>JSON.parse(String(call[1]?.body)));expect(bodies.every(b=>JSON.stringify(b)===JSON.stringify(bodies[0]))).toBe(true);
 expect(bodies[0]).toMatchObject({args:firstCapture.request.arguments,idempotencyKey:firstCapture.request.meta.cle,deviceTimestamp:firstCapture.request.meta.horodatage_appareil});
 expect((await depot.obtenir(first.id))?.statut).toBe("envoyee");expect((await depot.obtenir(next.id))?.statut).toBe("en_attente");
});
