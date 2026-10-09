import fixtures from "./fixturesClassementCapSQL.json";
import { creerMutationClassementVariance, interpreterClassementVariance, lireVariancesClassables, lireHistoriqueClassements, verifierDestinationClassementVariance } from "./classementVariance";
import type { ArgumentsClassementVarianceM6 } from "./classementVariance";
import { DepotOutboxMemoire } from "../outbox/depot";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { creerVidangeur } from "../outbox/vidangeur";
import { invoquerOutil } from "../protocole/client";
interface Capture {
  readonly phase: string; readonly request: { readonly nom: string; readonly arguments: Readonly<Record<string, unknown>>;
    readonly meta_cap: { readonly cle: string; readonly appareil: string; readonly horodatage_appareil: string } | null };
  readonly response: unknown; readonly response_utf8: string;
}
const captures = fixtures.captures as unknown as readonly Capture[];
const cap = (phase: string) => captures.find(c => c.phase === phase)!;
const horloge = { maintenant: new Date("2026-10-08T17:00:00Z"), decalageMinutesUTC: 0 };
const session = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APP-CLASSEMENT-FICTIF", personne: "admin.contexte.fictif" };
function mutation(c: Capture) {
  return { ...creerMutationClassementVariance(c.request.arguments as unknown as ArgumentsClassementVarianceM6, () => c.request.meta_cap!.cle, horloge, session), proprietaire: session.personne };
}
// Producteur Cap/SQLite et captures réels fictifs ; ici fetch, dépôt mémoire et pertes de réponses sont fictifs.
test.each(captures.map(c => [c.phase, c] as const))("les octets Cap %s sont consommés sans DTO inventé", (_phase, c) => {
  expect(JSON.parse(c.response_utf8)).toEqual(c.response);
  if (c.request.nom.includes("lister_variances")) expect(lireVariancesClassables(c.response, c.request.arguments).ok).toBe(true);
  else if (c.request.nom.includes("lire_historique")) expect(lireHistoriqueClassements(c.response, c.request.arguments).ok).toBe(true);
  else {
    const lu = interpreterClassementVariance(c.response, mutation(c));
    if (c.phase.includes("inconnu")) expect(lu).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
    else if (c.phase.includes("refus")) expect(lu.accepte).toBe(false);
    else expect(lu.accepte).toBe(true);
  }
});
test("SDK/dépôt/vidangeur conservent corps et UUID à travers perte, quota, rôle et source avant confirmation v1 après v2", async () => {
  const initiale = cap("classement_v1_succes_reponse_perdue"), depot = new DepotOutboxMemoire();
  const m = await depot.inserer(mutation(initiale));
  const next = await depot.inserer({ ...m, id: "e57ea356-0a21-4924-b343-68d18e317397", sequence: null,
    payload: { ...m.payload, cause: "breakage" } });
  const requests: Record<string, unknown>[] = []; let brut: unknown = null, perdre = true;
  let maintenant = new Date(horloge.maintenant);
  const fetchImpl = jest.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(JSON.parse(String(init?.body)));
    if (perdre) throw new TypeError("FICTIF : réponse perdue, aucun vrai réseau");
    return new Response(JSON.stringify({ ok: true, result: brut }), { status: 200 });
  });
  const reprendre = () => creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, verifierAvantEnvoi: async (m, s, courante) => courante() && verifierDestinationClassementVariance(m, s), session: () => session, maintenant: () => maintenant });
  const inconnus = [null, "rejeu_quota800_inconnu", "rejeu_role_retire_inconnu", "rejeu_source_volatile_inconnu"];
  for (const phase of inconnus) {
    if (phase) { perdre = false; brut = cap(phase).response; }
    const r = await reprendre().vidangerFileSortante();
    expect(r.envoyees).toEqual([]); expect(r.echecsPermanents).toEqual([]);
    const courant = await depot.obtenir(m.id); expect(courant?.statut).toBe("en_attente"); expect(courant?.payload).toEqual(m.payload);
    expect((await depot.obtenir(next.id))?.statut).toBe("en_attente");
    maintenant = new Date(Date.parse(courant!.prochaineTentativeA!) + 1);
  }
  expect(requests).toHaveLength(4);
  expect(requests.every(r => r.idempotencyKey === m.id)).toBe(true);
  expect(requests.every(r => JSON.stringify(r) === JSON.stringify(requests[0]))).toBe(true);
  brut = cap("rejeu_propre_v1_apres_v2").response;
  const r = await reprendre().vidangerFileSortante(); expect(r.envoyees).toContain(m.id);
  const envoye = await depot.obtenir(m.id); expect(envoye?.statut).toBe("envoyee");
  expect((envoye?.resumeAccepte as { reference: { index: number } }).reference.index).toBe(0);
  expect(requests[4]).toEqual(requests[0]);
});
test.each(["appareil", "destination"])("un changement de %s conserve la même intention sans RPC sous le nouveau contexte", async genre => {
  const depot = new DepotOutboxMemoire(), c = cap("classement_v1_succes_reponse_perdue");
  const m = await depot.inserer(mutation(c));
  const autre = { ...session, ...(genre === "appareil" ? { appareilId: "AUTRE-APP-FICTIF" } : { urlBase: "https://autre-fictif.invalid" }) };
  const fetchImpl = jest.fn(async () => new Response('{}', { status: 200 }));
  const v = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
    verifierAvantEnvoi: async (m, s, courante) => courante() && verifierDestinationClassementVariance(m, s),
    session: () => autre, maintenant: () => horloge.maintenant });
  await v.vidangerFileSortante(); expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente" });
});
