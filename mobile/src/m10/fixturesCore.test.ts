import { FIXTURES_CORE_M10 } from "./fixturesCore";
import { invoquerOutil } from "../protocole/client";
import { lireReferencesM10, lireSignauxM10, lireStatutDecisionM10, lireStatutRevisionM10 } from "./contrat";
import { lireDossierRevisionM10 } from "./dossier";
import { creerMutationArbitrageMemoire, interpreterArbitrageMemoire } from "./arbitrageOutbox";
const f = FIXTURES_CORE_M10.cases;
type Cas = typeof f[keyof typeof f];
async function recevoir(cas: Cas) {
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify(cas.response), { status: cas.status }));
  const r = await invoquerOutil({ urlBase: "https://core.fictif", jeton: "token-client-fictif", requete: cas.request, fetchImpl });
  expect(fetchImpl).toHaveBeenCalledTimes(1);
  return r;
}
test.each(["signaux", "catalogue", "dossier", "decision", "revision"] as const)("capture Gateway %s : client et contrat mobile", async nom => {
  expect(FIXTURES_CORE_M10.fictif).toBe(true);
    const cas = f[nom], r = await recevoir(cas);
    expect(cas.tables_unchanged).toBe(true);
    if (!r.ok) throw new Error(r.echec.message);
    // Response.json du runtime de test fournit du JSON ordinaire provenant d'un autre realm.
    expect(Object.getPrototypeOf(r.result)).not.toBe(Object.prototype);
    expect(Object.getPrototypeOf(Object.getPrototypeOf(r.result))).toBeNull();
    const lu = nom === "signaux" ? lireSignauxM10(r.result) : nom === "catalogue" ? lireReferencesM10(r.result) :
      nom === "dossier" ? lireDossierRevisionM10(r.result, f.dossier.request.args.revision_ligne_id) :
      nom === "decision" ? lireStatutDecisionM10(r.result) : lireStatutRevisionM10(r.result);
    expect(lu.ok).toBe(true);
});
test.each(["arbitrage", "rejeu", "rejeu_apres_backend_reboot"] as const)("ACK natif %s : hash, choix, cible et personne persistée", async nom => {
  const r = await recevoir(f[nom]); if (!r.ok) throw new Error(r.echec.message);
  const natif = f.arbitrage.response.result.resultat.resultat;
  const request = f.arbitrage.request;
  const m = { ...creerMutationArbitrageMemoire(request.args.revision_ligne_id, request.args.statut,
    () => request.idempotencyKey, { maintenant: new Date(request.args.horodatage), decalageMinutesUTC: 0 }), proprietaire: natif.par };
  const ack = interpreterArbitrageMemoire(r.result, m);
  expect(ack.accepte).toBe(true);
  if (ack.accepte) expect(ack.resume).toEqual(natif);
  expect(interpreterArbitrageMemoire(r.result, { ...m, proprietaire: "autre-fictif" }).accepte).toBe(false);
});
test.each(["role_employee", "role_seller", "body_device_id_usurpe"] as const)("Gateway %s : refus permanent sans mutation", async nom => {
  const cas = f[nom], r = await recevoir(cas);
  expect(cas.tables_unchanged).toBe(true); expect(r.ok).toBe(false);
  if (!r.ok) expect(r.echec.reessayable).toBe(false);
});
test.each(["conflit_uuid", "role_retire_backend"] as const)("Métier %s : aucun accusé accepté", async nom => {
  const cas = f[nom], r = await recevoir(cas);
  expect(cas.tables_unchanged).toBe(true);
  if (r.ok) expect(interpreterArbitrageMemoire(r.result).accepte).toBe(false);
  else expect(r.echec.reessayable).toBe(false);
});
