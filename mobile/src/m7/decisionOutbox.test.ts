import { creerMutationDecisionMarketing, construireArgumentsDecisionMarketing,
  decisionsMarketingEnFile, interpreterDecisionMarketing } from "./decisionOutbox";
import type { LigneContenuM7 } from "./contrat";
import type { MutationOutbox } from "../outbox/types";

const FICTIF = true;
const horloge = { maintenant: new Date("2026-09-15T15:10:00Z"), decalageMinutesUTC: -240 };
const item: LigneContenuM7 = {
  contenu_id: "9fbe357b-71d3-58ba-aa7b-0d8b40ce20bd",
  wct_id: "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
  plateforme: "demande_temoignage", revision: 1, approval_status: "PROPOSE", exporte: false,
  marque_source: null, fraicheur_marque: "preuve_absente", texte: "Texte fictif", origine_texte: "gabarit",
  mots_clics: [], lien_utm: null, avertissements: [], decision: null,
  consentement: { recueilli_par: "etienne", recueilli_le: "2026-09-15T15:05:00+00:00", version_texte: "v1-fictif" },
};
const genererId = () => "00000000-0000-4000-8000-000000000001";
function mutation(decision: "approuver" | "rejeter" = "approuver"): MutationOutbox {
  return { ...creerMutationDecisionMarketing(item, decision, "Motif fictif explicite", genererId, horloge),
    sequence: 1, proprietaire: "nathan" };
}

// ACK natif exact : qualification/m7-decision-contract-fixtures-r1.json, captures.premiere.resultat.resultat.
const PROVENANCE = { fictif: true, capture_sha256: "87155ea4695028d260103b47e2b47790f93e4ca2e6ad72fd83e9c3a04f33b58f" };
const ack = {
  contenu_id: "9fbe357b-71d3-58ba-aa7b-0d8b40ce20bd", plateforme: "demande_temoignage", approval_status: "APPROVED",
  par: "nathan", source: "appareil", horodatage: "2026-09-15T15:10:00+00:00",
  empreinte_texte: "ad76d593095a578e35132de572333eb58d3e80a1ca5c5f7b3004161c755f2800",
  prochaine_etape: "m7_exporter_paquet_manuel : le paquet à publier toi-même",
} as const;
const couple = (v: unknown) => ({ ok: true, resultat: { accepte: true, resultat: v } });

test("création soumise avant réseau, UUID unique, preuve locale et arguments stricts", () => {
  expect(FICTIF && PROVENANCE.fictif).toBe(true);
  const id = jest.fn(genererId);
  const m = creerMutationDecisionMarketing(item, "approuver", "ignoré pour approbation", id, horloge);
  expect(id).toHaveBeenCalledTimes(1);
  expect(m).toMatchObject({ type: "marketing_decision", chantierId: `marketing:${item.contenu_id}`,
    id: genererId(), statut: "en_attente", sequence: null, proprietaire: null,
    createdAtLocal: "2026-09-15T11:10:00-04:00", payload: {
      contenu_id: item.contenu_id, decision: "approuver", horodatage: "2026-09-15T11:10:00-04:00",
      _marketing_local: { plateforme: item.plateforme, revision: 1, wct_id: item.wct_id },
    } });
  expect(construireArgumentsDecisionMarketing(m)).toEqual({ contenu_id: item.contenu_id,
    decision: "approuver", horodatage: m.createdAtLocal });
  const rejet = creerMutationDecisionMarketing(item, "rejeter", "  Motif fictif explicite  ", genererId, horloge);
  expect(construireArgumentsDecisionMarketing(rejet)).toEqual({ contenu_id: item.contenu_id,
    decision: "rejeter", motif: "Motif fictif explicite", horodatage: rejet.createdAtLocal });
});

test.each(["", "  ", "non", "x".repeat(501)])("rejet motif invalide %p avant création UUID", motif => {
  const id = jest.fn(genererId);
  expect(() => creerMutationDecisionMarketing(item, "rejeter", motif, id, horloge)).toThrow();
  expect(id).not.toHaveBeenCalled();
});

test("preuve locale/horloge invalides ne créent aucune intention", () => {
  for (const invalide of [{ ...item, contenu_id: "" }, { ...item, wct_id: "" },
    { ...item, plateforme: "" }, { ...item, revision: 0 }, { ...item, revision: 2 ** 53 }]) {
    expect(() => creerMutationDecisionMarketing(invalide, "approuver", "", genererId, horloge)).toThrow();
  }
  expect(() => creerMutationDecisionMarketing(item, "approuver", "", genererId,
    { ...horloge, maintenant: new Date(NaN) })).toThrow();
});

test("ACK natif couple relié à l'intention et au propriétaire persisté", () => {
  expect(interpreterDecisionMarketing(couple(ack), mutation())).toEqual({ accepte: true, resume: ack });
  expect(interpreterDecisionMarketing({ ...couple(ack), rejoue: true }, mutation())).toEqual({ accepte: true, resume: ack });
  expect(interpreterDecisionMarketing(couple({ ...ack, approval_status: "REJECTED" }), mutation("rejeter")))
    .toMatchObject({ accepte: true, resume: { approval_status: "REJECTED" } });
});

test("JSON décodé par Response reste une donnée native lisible, quel que soit son realm", async () => {
  const reponse = new Response(JSON.stringify(couple(ack)));
  const brut: unknown = await reponse.json();
  expect(interpreterDecisionMarketing(brut, mutation())).toEqual({ accepte: true, resume: ack });
});

test.each([
  { contenu_id: "autre-contenu-fictif" }, { par: "autre-personne-fictive" }, { plateforme: "facebook" },
  { approval_status: "REJECTED" }, { source: "console" }, { empreinte_texte: "g".repeat(64) },
  { empreinte_texte: "a".repeat(63) }, { prochaine_etape: "" },
  { horodatage: "2026-09-15T15:10:00" }, { horodatage: "2026-02-30T12:00:00Z" },
  { horodatage: "2026-09-15T25:10:00Z" }, { horodatage: "2026-09-15T15:10:00+24:00" },
])("ACK mal lié/mal formé %p reste incertain", invalide => {
  expect(interpreterDecisionMarketing(couple({ ...ack, ...invalide }), mutation())).toMatchObject({
    accepte: false, verdict: { code: "accuse_invalide" },
  });
});

test("direct, troncature, contexte absent ou propriétaire inconnu ne sont jamais un succès", () => {
  for (const brut of [{ ok: true, resultat: ack }, { ...couple(ack), tronque: true }, {}, null]) {
    expect(interpreterDecisionMarketing(brut, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  }
  expect(interpreterDecisionMarketing(couple(ack))).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  expect(interpreterDecisionMarketing(couple(ack), { ...mutation(), proprietaire: null }))
    .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});

test("payload corrompu, métadonnées héritées ou getter : aucune autorité inférée", () => {
  const m = mutation();
  const get = jest.fn(() => item.plateforme);
  const locale = { plateforme: item.plateforme, revision: 1, wct_id: item.wct_id };
  Object.defineProperty(locale, "plateforme", { get, enumerable: true });
  for (const payload of [{ ...m.payload, _marketing_local: undefined },
    { ...m.payload, _marketing_local: Object.create({ plateforme: item.plateforme, revision: 1, wct_id: item.wct_id }) },
    { ...m.payload, _marketing_local: locale }, { ...m.payload, contenu_id: "autre" },
    { ...m.payload, horodatage: "2026-09-15T12:00:00Z" }]) {
    const invalide = { ...m, payload };
    expect(construireArgumentsDecisionMarketing(invalide)).toBeNull();
    expect(interpreterDecisionMarketing(couple(ack), invalide)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  }
  expect(get).not.toHaveBeenCalled();
});

test("refus explicitement codé permanent, erreur inconnue/illisible garde la même intention", () => {
  expect(interpreterDecisionMarketing({ ok: true, resultat: { accepte: false,
    verdict: { code: "REJ-CONTENU-PERIME", detail: "révision fictive dépassée" } } }, mutation()))
    .toEqual({ accepte: false, verdict: { code: "REJ-CONTENU-PERIME", detail: "révision fictive dépassée" } });
  expect(interpreterDecisionMarketing({ ok: false, erreur: "mutation_conflit", details: "fictif" }, mutation()))
    .toEqual({ accepte: false, verdict: { code: "mutation_conflit", detail: "fictif" } });
  for (const brut of [{ ok: true, resultat: { accepte: false, verdict: {} } }, { ok: false },
    { ok: false, erreur: "outil_inconnu" }]) {
    expect(interpreterDecisionMarketing(brut, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  }
});

test("projections incluent chaque propriétaire persisté, même terminal ou inconnu/corrompu", () => {
  const m = mutation();
  const invalide = { ...m, id: "invalide-fictif", proprietaire: null, payload: {} };
  expect(decisionsMarketingEnFile([m, { ...m, id: "terminale-fictive", statut: "envoyee", proprietaire: "autre.fictive" }, invalide]))
    .toEqual([
      { id: m.id, contenuId: item.contenu_id, statut: "en_attente", personne: "nathan", decision: "approuver" },
      { id: "terminale-fictive", contenuId: item.contenu_id, statut: "envoyee", personne: "autre.fictive", decision: "approuver" },
      { id: "invalide-fictif", contenuId: item.contenu_id, statut: "en_attente", personne: null, decision: null },
    ]);
});
