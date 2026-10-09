import captures from "../m6/fixturesClassementVariancesSQL.json";
import { creerMutation, soumettreMutation } from "./mutation";
import { DepotOutboxMemoire } from "./depot";
import { creerVidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { DescripteurTypeMutation } from "./vidangeur";
import type { TypeMutation } from "./types";
const TYPE = "variance_cause_classification" as TypeMutation;
const cap = (phase: string) => captures.captures.find(v => v.phase === phase)!;
const horloge = { maintenant: new Date("2026-10-08T17:00:00Z"), decalageMinutesUTC: -240 };
const session = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APP-CLASSEMENT-FICTIF", personne: "admin.contexte.fictif" };
// Fictif : dépôt/SDK/vidangeur réels, réponses HTTP fournies ; aucun Gateway ou effet serveur déduit.
test("un refus HTTP de portée après effet possible conserve l'intention opt-in et bloque la suivante", async () => {
  const depot = new DepotOutboxMemoire();
  const m = await depot.inserer({ ...soumettreMutation(creerMutation({ type: TYPE, chantierId: "variance:WCT-FICTIF",
    payload: cap("classement_v1").request.arguments }, () => "20f884dc-80ef-4f13-aab1-b2a7bd73d64d", horloge)), proprietaire: session.personne });
  const next = await depot.inserer({ ...m, id: "a180c7ad-75a5-484d-bd47-332b4d271d40", sequence: null });
  const interpreter = jest.fn(() => { throw new Error("aucune réponse métier dans ce refus HTTP"); });
  const descripteur = { tool: "m6_classer_cause_variance_appareil", serialiserParChantier: true,
    conserverRefusHttpIncertains: true, interpreterResultat: interpreter } as DescripteurTypeMutation;
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ ok: false, error: { type: "tool_call_blocked",
    message: 'OPSYS device is not authorized to call "m6_classer_cause_variance_appareil" (tool_out_of_scope).' } }), { status: 403 }));
  const vidangeur = creerVidangeur({ depot, descripteurs: new Map([[TYPE, descripteur]]), appelerOutil: invoquerOutil,
    fetchImpl, session: () => session, maintenant: () => horloge.maintenant });
  const r = await vidangeur.vidangerFileSortante();
  expect(r.echecsPermanents).toEqual([]); expect(r.remisesEnAttente).toEqual([m.id]);
  expect((await depot.obtenir(m.id))?.statut).toBe("en_attente");
  expect((await depot.obtenir(next.id))?.statut).toBe("en_attente");
  expect(fetchImpl).toHaveBeenCalledTimes(1); expect(interpreter).not.toHaveBeenCalled();
});
test("les types sans opt-in gardent leur refus HTTP permanent existant", async () => {
  const depot = new DepotOutboxMemoire();
  const m = await depot.inserer({ ...soumettreMutation(creerMutation({ type: "lead_note", chantierId: "lead:FICTIF",
    payload: {} }, () => "3cce6c84-7648-4f0e-b9b1-aaf394b80a8e", horloge)), proprietaire: session.personne });
  const fetchImpl = jest.fn(async () => new Response('{}', { status: 404 }));
  const v = creerVidangeur({ depot, descripteurs: new Map([["lead_note", { tool: "m2_enregistrer_interaction",
    interpreterResultat: () => ({ accepte: false, verdict: { code: "FICTIF", detail: "" } }) }]]), appelerOutil: invoquerOutil,
    fetchImpl, session: () => session, maintenant: () => horloge.maintenant });
  expect((await v.vidangerFileSortante()).echecsPermanents).toHaveLength(1);
  expect((await depot.obtenir(m.id))?.statut).toBe("echec_permanent");
});
