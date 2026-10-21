import fixtures from "./fixturesClassementCapSQL.json";
import intentions from "./fixturesClassementIntentionCapSQL.json";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
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
  return { ...creerMutationClassementVariance(c.request.arguments as unknown as ArgumentsClassementVarianceM6, () => c.request.meta_cap!.cle, horloge, session), destination: session.urlBase, proprietaire: session.personne };
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

test("un négatif legacy substitué après confirmation perdue ne libère pas la mutation suivante", async () => {
  const depot = new DepotOutboxMemoire(), initiale = cap("classement_v1_succes_reponse_perdue");
  const m = await depot.inserer(mutation(initiale));
  const suivante = await depot.inserer({ ...m, id: "93b549e0-d8bb-48ce-98b9-797a64f45da8", sequence: null,
    payload: { ...m.payload, cause: "breakage" } });
  let maintenant = new Date(horloge.maintenant), perdre = true;
  const requests: Record<string, unknown>[] = [];
  // Réponse négative réellement capturée, volontairement substituée au succès perdu.
  // Le faux transport modélise un cache incohérent; il ne qualifie pas un effet serveur.
  const negative = cap("attendu_v1_frais_refus_revision").response;
  const fetchImpl = async (_input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(JSON.parse(String(init?.body)));
    if (perdre) throw new TypeError("FICTIF : confirmation perdue");
    return new Response(JSON.stringify({ ok: true, result: negative }), { status: 200 });
  };
  const reprendre = () => creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, verifierAvantEnvoi: async (m, s, courante) => courante() && verifierDestinationClassementVariance(m, s),
    session: () => session, maintenant: () => maintenant });
  await reprendre().vidangerFileSortante();
  maintenant = new Date(Date.parse((await depot.obtenir(m.id))!.prochaineTentativeA!) + 1);
  perdre = false;
  const lu = await reprendre().vidangerFileSortante();
  expect(lu.echecsPermanents).toEqual([]);
  expect(lu.envoyees).toEqual([]);
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente" });
  expect((await depot.obtenir(suivante.id))?.statut).toBe("en_attente");
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
});

interface CaptureIntention {
  readonly label: string; readonly arguments: Readonly<Record<string, unknown>>;
  readonly meta: { readonly cle: string; readonly appareil: string; readonly horodatage_appareil: string } | null;
  readonly response: unknown;
}
const capturesIntention = intentions.captures as unknown as readonly CaptureIntention[];
const intentionCap = (label: string) => capturesIntention.find(c => c.label === label)!;
function mutationIntention(c: CaptureIntention) {
  const meta = c.meta!;
  return { ...creerMutationClassementVariance(c.arguments as unknown as ArgumentsClassementVarianceM6, () => meta.cle,
    { maintenant: new Date(meta.horodatage_appareil), decalageMinutesUTC: 0 }, { ...session, appareilId: meta.appareil }),
    createdAtLocal: meta.horodatage_appareil, destination: session.urlBase, proprietaire: session.personne };
}
test("la nouvelle fixture est la copie byte-exact des 20 captures Cap/SQLite ROOT, sans HTTP revendiqué", () => {
  const octets = readFileSync(join(__dirname, "fixturesClassementIntentionCapSQL.json"));
  expect(createHash("sha256").update(octets).digest("hex")).toBe("37d8c3a671b4c33149079a22b65b12a75782d6631650522b61a921ca22d2ae6f");
  expect(capturesIntention).toHaveLength(20);
});
test.each(capturesIntention.map(c => [c.label, c] as const))("le reçu réel v2 %s est consommé sans réparer son DTO", (_label, c) => {
  if (c.label.startsWith("m6_lister")) {
    const lu = lireVariancesClassables(c.response, c.arguments);
    expect(lu.ok).toBe(true); if (lu.ok) expect(lu.value).toEqual((c.response as any).resultat.resultat);
  } else if (c.label.startsWith("m6_lire_historique")) {
    const lu = lireHistoriqueClassements(c.response, c.arguments);
    expect(lu.ok).toBe(true); if (lu.ok) expect(lu.value).toEqual((c.response as any).resultat.resultat);
  } else {
    const lu = interpreterClassementVariance(c.response, mutationIntention(c)), response = c.response as any;
    if (response.ok === false) expect(lu).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
    else if (response.resultat.accepte === false) expect(lu).toMatchObject({ accepte: false, verdict: response.resultat.verdict });
    else {
      expect(lu.accepte).toBe(true);
      if (lu.accepte) expect(lu.resume).toEqual({ ...response.resultat.resultat, registre_confirmation: response.resultat.registre });
    }
  }
});
test("deux UUID de même corps et heure ne partagent pas leur preuve négative", () => {
  const succes = intentionCap("succes_v2"), refus = intentionCap("refus_v2_autre_uuid_meme_corps_heure");
  expect(refus.arguments).toEqual(succes.arguments);
  expect(refus.meta!.horodatage_appareil).toBe(succes.meta!.horodatage_appareil);
  expect(refus.meta!.cle).not.toBe(succes.meta!.cle);
  expect(interpreterClassementVariance(refus.response, mutationIntention(succes)))
    .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  expect(interpreterClassementVariance(refus.response, mutationIntention(refus)))
    .toMatchObject({ accepte: false, verdict: (refus.response as any).resultat.verdict });
});
test("SDK/dépôt/vidangeur conservent l’intention perdue à travers les substitutions réelles puis son ACK propre après correction", async () => {
  const initiale = intentionCap("succes_v2"), depot = new DepotOutboxMemoire();
  const m = await depot.inserer(mutationIntention(initiale));
  const suivante = await depot.inserer({ ...m, id: "22cf2c1c-fb67-4d23-ad74-1fb5b6d16b4b", sequence: null,
    payload: { ...m.payload, cause: "breakage" } });
  let perdre = true, brut: unknown, maintenant = new Date(initiale.meta!.horodatage_appareil);
  const requests: Record<string, unknown>[] = [];
  const fetchImpl = async (_input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(JSON.parse(String(init?.body)));
    if (perdre) throw new TypeError("FICTIF : confirmation perdue, aucun réseau");
    return new Response(JSON.stringify({ ok: true, result: brut }), { status: 200 });
  };
  const reprendre = () => creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, verifierAvantEnvoi: async (m, s, courante) => courante() && verifierDestinationClassementVariance(m, s),
    session: () => session, maintenant: () => maintenant });
  const inconnus = [null, ...capturesIntention.filter(c => c.label.startsWith("cache_succes_")).map(c => c.label), "role_retire_avant_cache"];
  for (const label of inconnus) {
    if (label) { perdre = false; brut = intentionCap(label).response; }
    const r = await reprendre().vidangerFileSortante();
    expect(r.envoyees).toEqual([]); expect(r.echecsPermanents).toEqual([]);
    const courant = await depot.obtenir(m.id);
    expect(courant).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente" });
    expect((await depot.obtenir(suivante.id))?.statut).toBe("en_attente");
    maintenant = new Date(Date.parse(courant!.prochaineTentativeA!) + 1);
  }
  expect(requests).toHaveLength(inconnus.length);
  expect(requests.every(r => JSON.stringify(r) === JSON.stringify(requests[0]))).toBe(true);
  const rangPropre = requests.length;
  brut = intentionCap("premier_succes_apres_revision").response;
  expect((await reprendre().vidangerFileSortante()).envoyees).toContain(m.id);
  expect(requests[rangPropre]).toEqual(requests[0]);
  const recu = (await depot.obtenir(m.id))!.resumeAccepte as any;
  expect(recu.version_schema).toBe(2); expect(recu.reference.index).toBe(0); expect(recu.intention.intention_uuid).toBe(m.id);
  // Une éventuelle tentative suivante a son propre UUID; aucun effet serveur n'est simulé pour elle.
  expect((await depot.obtenir(suivante.id))?.statut).toBe("en_attente");
});
test("un vrai refus certain r2 perdu devient définitif seulement avec son reçu propre rejoué", async () => {
  const frais = intentionCap("refus_v2_autre_uuid_meme_corps_heure"), cache = intentionCap("refus_v2_restart"), depot = new DepotOutboxMemoire();
  const m = await depot.inserer(mutationIntention(frais));
  let perdre = true, maintenant = new Date(frais.meta!.horodatage_appareil);
  const requests: Record<string, unknown>[] = [];
  const fetchImpl = async (_input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(JSON.parse(String(init?.body)));
    if (perdre) throw new TypeError("FICTIF : reçu perdu");
    return new Response(JSON.stringify({ ok: true, result: cache.response }), { status: 200 });
  };
  const reprendre = () => creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, verifierAvantEnvoi: async (m, s, courante) => courante() && verifierDestinationClassementVariance(m, s),
    session: () => session, maintenant: () => maintenant });
  expect((await reprendre().vidangerFileSortante()).echecsPermanents).toEqual([]);
  maintenant = new Date(Date.parse((await depot.obtenir(m.id))!.prochaineTentativeA!) + 1); perdre = false;
  expect((await reprendre().vidangerFileSortante()).echecsPermanents).toEqual([{ id: m.id, verdict: (cache.response as any).resultat.verdict }]);
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "echec_permanent" });
  expect(requests).toHaveLength(2); expect(requests[1]).toEqual(requests[0]);
});
