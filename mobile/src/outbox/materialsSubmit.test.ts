import { DepotOutboxMemoire } from "./depot";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerMutation, soumettreMutation } from "./mutation";
import { creerVidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";

// Tout est fictif en RAM ; ACK selon contrats_sortie.py (pas une capture HTTP inventée).
const FICTIF = true;
const HORLOGE = { maintenant: new Date("2026-10-08T12:00:00Z"), decalageMinutesUTC: -240 };
function payload(intervention = "INTERVENTION-FICTIVE") {
  return { wct_id: `WCT-${intervention}`, formulaire: { wct_id: `WCT-${intervention}`, intervention_id: intervention,
    chantier_id: "CHANTIER-FICTIF", lignes_materiaux: [{ type_ligne: "perte", materiau_id: "MAT-FICTIF", quantite: 2, unite: "m" }] } };
}
function nominal(intervention = "INTERVENTION-FICTIVE") {
  const p = payload(intervention);
  return { ok: true, resultat: { accepte: true, resultat: { intervention_id: intervention,
    chantier_id: p.formulaire.chantier_id, lignes_declarees: p.formulaire.lignes_materiaux },
    registre: { taille: 3, hash_tete: "a".repeat(64) } } };
}
async function inserer(depot: DepotOutboxMemoire, id: string, intervention = "INTERVENTION-FICTIVE", dependsOn: string | null = null) {
  return depot.inserer({ ...soumettreMutation(creerMutation({ type: "materials_submit", chantierId: intervention, payload: payload(intervention), dependsOn }, () => id, HORLOGE)), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE" });
}
function config(depot: DepotOutboxMemoire, body: unknown) {
  const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ ok: true, result: body }), { status: 200 }));
  return { fetchImpl, vidangeur: creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
    session: () => ({ urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF", personne: "PERSONNE-FICTIVE" }),
    maintenant: () => HORLOGE.maintenant }) };
}
const inconnus: Array<readonly [string, () => unknown]> = [
  // Forme Cap réelle de _appeler_idempotent, source : ce n'est pas une confirmation M6.
  ["approbation en attente", () => ({ ok: true, statut: "en_attente_approbation", demande_id: "DEMANDE-FICTIVE", details: "Demande fictive en attente", rejoue: false })],
  ["approbation en attente rejouée", () => ({ ok: true, statut: "en_attente_approbation", demande_id: "DEMANDE-FICTIVE", details: "Demande fictive en attente", rejoue: true })],
  ["objet vide", () => ({})], ["null", () => null], ["DIRECT vide", () => ({ ok: true, resultat: {} })],
  ["résultat null", () => ({ ok: true, resultat: { accepte: true, resultat: null } })],
  ["partiel", () => ({ ok: true, resultat: { accepte: true, resultat: { intervention_id: "INTERVENTION-FICTIVE" } } })],
  ["sans registre", () => { const n = nominal(); Reflect.deleteProperty(n.resultat, "registre"); return n; }],
  ["hash invalide", () => { const n = nominal(); n.resultat.registre.hash_tete = "incorrect"; return n; }],
  ["mauvaise intervention", () => nominal("AUTRE-INTERVENTION")],
  ["mauvais chantier", () => { const n = nominal(); n.resultat.resultat.chantier_id = "AUTRE-CHANTIER"; return n; }],
  ["mauvaise quantité", () => { const n = nominal(); n.resultat.resultat.lignes_declarees[0].quantite = 3; return n; }],
  ["mauvais type", () => { const n = nominal(); n.resultat.resultat.lignes_declarees[0].type_ligne = "bris"; return n; }],
  ["WCT étranger ajouté", () => { const n = nominal(); Reflect.set(n.resultat.resultat, "wct_id", "WCT-AUTRE"); return n; }],
  ["champ monétaire", () => { const n = nominal(); Reflect.set(n.resultat.resultat.lignes_declarees[0], "cout_unitaire", 9); return n; }],
  ["artefact", () => ({ ok: true, resultat: "artefact://FICTIF" })],
  ["contradiction flags", () => { const n = nominal(); Reflect.set(n, "tronque", true); return n; }],
  ["refus sans code", () => ({ ok: true, resultat: { accepte: false, verdict: {} } })],
  ["refus code non texte", () => ({ ok: true, resultat: { accepte: false, verdict: { code: 12 } } })],
  ["code inconnu", () => ({ ok: true, resultat: { accepte: false, verdict: { code: "code-inventé-fictif" } } })],
];
describe("M6 ACK — intention persistée, transport rejoué fictif", () => {
  test.each(inconnus)("%s conserve UUID/payload et bloque dépendant", async (_nom, body) => {
    expect(FICTIF).toBe(true); const depot = new DepotOutboxMemoire(); const m = await inserer(depot, "UUID-FICTIF-1");
    const suite = await inserer(depot, "UUID-FICTIF-2", "SUITE-FICTIVE", m.id); const c = config(depot, body());
    const rapport = await c.vidangeur.vidangerFileSortante();
    expect(c.fetchImpl).toHaveBeenCalledTimes(1); expect(rapport.resultatsAcceptes).toEqual([]); expect(rapport.echecsPermanents).toEqual([]);
    expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, statut: "en_attente", payload: m.payload, tentatives: 1 });
    expect((await depot.obtenir(suite.id))?.statut).toBe("en_attente");
    const init = c.fetchImpl.mock.calls[0][1]; const args = JSON.parse(String(init?.body));
    expect(args.idempotencyKey).toBe(m.id); expect(args.args.wct_id).toBe(m.payload.wct_id);
  });
  test("nominal source lié termine avec confirmation persistée", async () => {
    const depot = new DepotOutboxMemoire(), m = await inserer(depot, "UUID-NOMINAL-FICTIF"), c = config(depot, nominal());
    const rapport = await c.vidangeur.vidangerFileSortante(); expect(rapport.envoyees).toEqual([m.id]);
    expect(await depot.obtenir(m.id)).toMatchObject({ statut: "envoyee", resumeAccepte: nominal().resultat.resultat });
  });
  test("seconde intention même objet ne part pas derrière issue inconnue", async () => {
    const depot = new DepotOutboxMemoire(), m = await inserer(depot, "UUID-INCERTAIN-FICTIF");
    const autre = await inserer(depot, "UUID-SECONDE-FICTIVE"), c = config(depot, { ok: true, resultat: {} });
    await c.vidangeur.vidangerFileSortante(); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    expect((await depot.obtenir(m.id))?.statut).toBe("en_attente"); expect((await depot.obtenir(autre.id))?.statut).toBe("en_attente");
  });
});


describe("M6 ACK — reprise, séries et reçu durable", () => {
  test("reprise mémoire : recul empêche renvoi, puis même UUID/payload termine, seconde passe seulement", async () => {
    const depot = new DepotOutboxMemoire(), m = await inserer(depot, "UUID-REPRISE-FICTIF");
    const seconde = await inserer(depot, "UUID-SECONDE-REPRISE-FICTIF"), premier = config(depot, { ok: true, resultat: {} });
    await premier.vidangeur.vidangerFileSortante(); const etat = await depot.obtenir(m.id); expect(etat?.prochaineTentativeA).not.toBeNull();
    const reprise = new DepotOutboxMemoire(); for (const row of await depot.lister()) await reprise.inserer(row);
    const c = config(reprise, nominal()); await c.vidangeur.vidangerFileSortante(); expect(c.fetchImpl).not.toHaveBeenCalled();
    if (!etat?.prochaineTentativeA) throw new Error("Recul manquant.");
    const heure = new Date(new Date(etat.prochaineTentativeA).getTime() + 1);
    const v = creerVidangeur({ depot: reprise, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl: c.fetchImpl,
      session: () => ({ urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF", personne: "PERSONNE-FICTIVE" }), maintenant: () => heure });
    await v.vidangerFileSortante(); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    const corps = JSON.parse(String(c.fetchImpl.mock.calls[0][1]?.body)); expect(corps.idempotencyKey).toBe(m.id); expect(corps.args).toEqual(m.payload);
    expect(await reprise.obtenir(m.id)).toMatchObject({ statut: "envoyee", payload: m.payload });
    expect((await reprise.obtenir(seconde.id))?.statut).toBe("en_attente");
    await v.vidangerFileSortante(); expect(c.fetchImpl).toHaveBeenCalledTimes(2);
  });
  test.each([null, { statut: "ok" }, { intervention_id: "AUTRE", chantier_id: "CHANTIER-FICTIF", lignes_declarees: payload().formulaire.lignes_materiaux }])("ancien envoyé reçu %j ne libère jamais nouvelle intention ; objet distinct reste libre", async resumeAccepte => {
    const depot = new DepotOutboxMemoire(), ancien = await inserer(depot, "UUID-LEGACY-FICTIF");
    await depot.mettreAJour({ ...ancien, statut: "envoyee", resumeAccepte });
    const seconde = await inserer(depot, "UUID-APRES-LEGACY-FICTIF"), independante = await inserer(depot, "UUID-INDEPENDANT-FICTIF", "AUTRE-FICTIVE");
    const c = config(depot, nominal("AUTRE-FICTIVE")); const rapport = await c.vidangeur.vidangerFileSortante();
    expect(c.fetchImpl).toHaveBeenCalledTimes(1); expect(rapport.envoyees).toEqual([independante.id]);
    expect(await depot.obtenir(ancien.id)).toMatchObject({ statut: "envoyee", resumeAccepte, id: ancien.id });
    expect((await depot.obtenir(seconde.id))?.statut).toBe("en_attente");
  });
  test("reçu envoyé canonique lié libère seconde intention sans renvoyer legacy UUID", async () => {
    const depot = new DepotOutboxMemoire(), ancien = await inserer(depot, "UUID-CANONIQUE-LEGACY-FICTIF");
    await depot.mettreAJour({ ...ancien, statut: "envoyee", resumeAccepte: nominal().resultat.resultat });
    const seconde = await inserer(depot, "UUID-APRES-CANONIQUE-FICTIF"), c = config(depot, nominal());
    const rapport = await c.vidangeur.vidangerFileSortante(); expect(rapport.envoyees).toEqual([seconde.id]); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(c.fetchImpl.mock.calls[0][1]?.body)).idempotencyKey).toBe(seconde.id);
  });
  test("objet distinct progresse malgré première issue inconnue ; même objet reste fermé", async () => {
    const depot = new DepotOutboxMemoire(), premier = await inserer(depot, "UUID-INCONNU-OBJET-FICTIF");
    const seconde = await inserer(depot, "UUID-MEME-OBJET-FICTIF"), autre = await inserer(depot, "UUID-AUTRE-OBJET-FICTIF", "AUTRE-FICTIVE");
    const c = config(depot, nominal("AUTRE-FICTIVE"));
    c.fetchImpl.mockImplementation(async (_input, init) => {
      const requete = JSON.parse(String(init?.body));
      const result = requete.args.formulaire.intervention_id === "INTERVENTION-FICTIVE" ? { ok: true, resultat: {} } : nominal("AUTRE-FICTIVE");
      return new Response(JSON.stringify({ ok: true, result }), { status: 200 });
    });
    const rapport = await c.vidangeur.vidangerFileSortante(); expect(c.fetchImpl).toHaveBeenCalledTimes(2); expect(rapport.envoyees).toEqual([autre.id]);
    expect((await depot.obtenir(premier.id))?.statut).toBe("en_attente"); expect((await depot.obtenir(seconde.id))?.statut).toBe("en_attente");
  });
  test("refus métier connu terminal, suivant seulement à nouvelle passe", async () => {
    const depot = new DepotOutboxMemoire(), premier = await inserer(depot, "UUID-REFUS-FICTIF"), seconde = await inserer(depot, "UUID-APRES-REFUS-FICTIF");
    const c = config(depot, { ok: true, resultat: { accepte: false, verdict: { code: "REJ-WCT-INCONNU" } } });
    await c.vidangeur.vidangerFileSortante(); expect((await depot.obtenir(premier.id))?.statut).toBe("echec_permanent");
    expect((await depot.obtenir(seconde.id))?.statut).toBe("en_attente"); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    await c.vidangeur.vidangerFileSortante(); expect(c.fetchImpl).toHaveBeenCalledTimes(2);
  });
  test("quarantaine propriétaire inconnu même objet bloque ; autre objet courant reste indépendant", async () => {
    const depot = new DepotOutboxMemoire(), premier = await inserer(depot, "UUID-QUARANTAINE-FICTIF");
    await depot.mettreAJour({ ...premier, proprietaire: null });
    const seconde = await inserer(depot, "UUID-APRES-QUARANTAINE-FICTIF"), autre = await inserer(depot, "UUID-LIBRE-FICTIF", "AUTRE-FICTIVE");
    const c = config(depot, nominal("AUTRE-FICTIVE")); const rapport = await c.vidangeur.vidangerFileSortante();
    expect(c.fetchImpl).toHaveBeenCalledTimes(1); expect(rapport.envoyees).toEqual([autre.id]); expect(rapport.quarantaine).toContain(premier.id);
    expect((await depot.obtenir(seconde.id))?.statut).toBe("en_attente");
  });
});


test("identité refusée en HTTP200 conserve intention et bloque même objet, sans autorisation supposée", async () => {
  const depot = new DepotOutboxMemoire(), m = await inserer(depot, "UUID-AUTH-FICTIF"), suivante = await inserer(depot, "UUID-AUTH-SUITE-FICTIF");
  const refus = { ok: true, resultat: { accepte: false, verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "personne fictive inactive ou rôle retiré" } } };
  const c = config(depot, refus), rapport = await c.vidangeur.vidangerFileSortante();
  expect(rapport.echecsPermanents).toEqual([]); expect(rapport.envoyees).toEqual([]); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "en_attente", id: m.id, payload: m.payload });
  expect((await depot.obtenir(suivante.id))?.statut).toBe("en_attente");
  expect(JSON.parse(String(c.fetchImpl.mock.calls[0][1]?.body)).idempotencyKey).toBe(m.id);
});


test("refus identité rejoué reste retenu avec clé inchangée, aucune restauration déduite", async () => {
  const depot = new DepotOutboxMemoire(), m = await inserer(depot, "UUID-AUTH-REJOUE-FICTIF");
  const refus = { ok: true, resultat: { accepte: false, verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "personne fictive inactive" } }, rejoue: true };
  const c = config(depot, refus); await c.vidangeur.vidangerFileSortante(); const etat = await depot.obtenir(m.id);
  if (!etat?.prochaineTentativeA) throw new Error("Recul manquant.");
  const heure = new Date(new Date(etat.prochaineTentativeA).getTime() + 1);
  const v = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl: c.fetchImpl,
    session: () => ({ urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF", personne: "PERSONNE-FICTIVE" }), maintenant: () => heure });
  const rapport = await v.vidangerFileSortante(); expect(rapport.envoyees).toEqual([]); expect(rapport.echecsPermanents).toEqual([]);
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, statut: "en_attente", payload: m.payload, tentatives: 2 });
  for (const appel of c.fetchImpl.mock.calls) expect(JSON.parse(String(appel[1]?.body)).idempotencyKey).toBe(m.id);
});


import capturesSql from "../m6/fixturesMateriauxAckSQL.json";
describe("M6 ACK — cinq réponses SQL réelles ROOT, transport rejoué en mémoire", () => {
  test("provenance source séparée : quatre Cap DEVICE et un outil direct, aucun HTTP/photo physique", () => {
    expect(capturesSql.fictif).toBe(true); expect(capturesSql.sources_unchanged).toBe(true); expect(capturesSql.captures).toHaveLength(5);
    expect(capturesSql.captures.filter(c => "idempotencyKey" in c)).toHaveLength(4);
  });
  test.each(capturesSql.captures)("réponse entière $phase, payload exact", async capture => {
    // Session/horloge/propriétaire sont des fixtures RAM de transport ; aucun écho absent inventé.
    const id = capture.idempotencyKey ?? "UUID-FICTIF-OUTIL-DIRECT-SANS-CAP";
    const depot = new DepotOutboxMemoire();
    const m = await depot.inserer({ ...soumettreMutation(creerMutation({ type: "materials_submit",
      chantierId: capture.request.formulaire.intervention_id, payload: { ...capture.request } }, () => id, HORLOGE)), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE" });
    const suivante = await depot.inserer({ ...soumettreMutation(creerMutation({ type: "materials_submit", chantierId: m.chantierId,
      payload: { ...capture.request } }, () => `${id}-SUIVANTE-FICTIVE`, HORLOGE)), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE" });
    const c = config(depot, capture.response), rapport = await c.vidangeur.vidangerFileSortante();
    expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    const requete = JSON.parse(String(c.fetchImpl.mock.calls[0][1]?.body)); expect(requete.args).toEqual(capture.request); expect(requete.idempotencyKey).toBe(id);
    if (capture.phase === "six_types_confirmation_reelle" || capture.phase === "meme_UUID_rejoue") {
      const metier = capture.response.resultat;
      if (!metier || metier.accepte !== true || !metier.resultat) throw new Error("Capture nominale absente.");
      expect(rapport.envoyees).toEqual([id]); expect(await depot.obtenir(id)).toMatchObject({ statut: "envoyee", resumeAccepte: metier.resultat, payload: capture.request });
    } else {
      expect(rapport.envoyees).toEqual([]); expect(rapport.echecsPermanents).toEqual([]);
      expect(await depot.obtenir(id)).toMatchObject({ statut: "en_attente", id, payload: capture.request });
    }
    expect((await depot.obtenir(suivante.id))?.statut).toBe("en_attente");
  });
});
