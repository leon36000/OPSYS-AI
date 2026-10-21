import { DepotOutboxMemoire } from "./depot";
import { avecProprietaire } from "./proprietaire";
import { creerMutation, soumettreMutation } from "./mutation";
import { creerVidangeur } from "./vidangeur";
import type { DescripteurTypeMutation } from "./vidangeur";
import type { TypeMutation, MutationOutbox } from "./types";
import type { ParametresAppelOutil } from "../protocole/client";
import { invoquerOutil } from "../protocole/client";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerMutationDecisionMarketing, decisionsMarketingEnFile } from "../m7/decisionOutbox";
import type { LigneContenuM7 } from "../m7/contrat";

const FICTIF = true;
const horloge = { maintenant: new Date("2026-10-07T12:00:00Z"), decalageMinutesUTC: -240 };
const session = { urlBase: "https://gateway.fictif.test", jeton: "jeton-fictif", appareilId: "device-fictif", personne: "owner.fictif" };
let compteur = 0;
const id = () => `00000000-0000-4000-8000-${String(++compteur).padStart(12, "0")}`;
beforeEach(() => { compteur = 0; });

async function intention(depot: DepotOutboxMemoire, contenu = "contenu-fictif") {
  return avecProprietaire(depot, () => session.personne, () => session.urlBase).inserer(soumettreMutation(creerMutation({
    type: "marketing_decision", chantierId: `marketing:${contenu}`,
    payload: { contenu_id: contenu, decision: "approuver", _marketing_local: { plateforme: "instagram" } },
  }, id, horloge)));
}

test("le hook reçoit la mutation persistée et retire les métadonnées locales du RPC", async () => {
  expect(FICTIF).toBe(true);
  const depot = new DepotOutboxMemoire(), mutation = await intention(depot);
  const contextes: Array<MutationOutbox | undefined> = [];
  const construireArguments = jest.fn((m: MutationOutbox) => ({ contenu_id: m.payload.contenu_id, decision: m.payload.decision }));
  const descripteur: DescripteurTypeMutation = {
    tool: "m7_decider_contenu", construireArguments,
    interpreterResultat: (_brut, contexte) => {
      contextes.push(contexte);
      return { accepte: true, resume: { contenu_id: "contenu-fictif" } };
    },
  };
  const appeler = jest.fn(async (_params: ParametresAppelOutil) => ({ ok: true as const, result: {} }));
  const vidangeur = creerVidangeur({ depot, descripteurs: new Map<TypeMutation, DescripteurTypeMutation>([["marketing_decision", descripteur]]),
    appelerOutil: appeler, fetchImpl: jest.fn(), session: () => session, maintenant: () => horloge.maintenant });
  await vidangeur.vidangerFileSortante();
  expect(construireArguments).toHaveBeenCalled();
  expect(appeler.mock.calls[0][0].requete.args).toEqual({ contenu_id: "contenu-fictif", decision: "approuver" });
  expect(contextes[0]).toMatchObject({ id: mutation.id, proprietaire: session.personne, sequence: mutation.sequence });
});

test("la première intention en recul bloque une seconde du même objet, pas un autre objet", async () => {
  const depot = new DepotOutboxMemoire(), premiere = await intention(depot);
  await depot.mettreAJour({ ...premiere, prochaineTentativeA: "2026-10-07T12:01:00Z" });
  const seconde = await intention(depot), autre = await intention(depot, "autre-contenu-fictif");
  const appeler = jest.fn(async (_params: ParametresAppelOutil) => ({ ok: true as const, result: {} }));
  const descripteur: DescripteurTypeMutation = { tool: "m7_decider_contenu", serialiserParChantier: true,
    interpreterResultat: () => ({ accepte: true, resume: {} }) };
  const vidangeur = creerVidangeur({ depot, descripteurs: new Map<TypeMutation, DescripteurTypeMutation>([["marketing_decision", descripteur]]),
    appelerOutil: appeler, fetchImpl: jest.fn(), session: () => session, maintenant: () => horloge.maintenant });
  const rapport = await vidangeur.vidangerFileSortante();
  expect(appeler.mock.calls.map(([p]) => p.requete.idempotencyKey)).toEqual([autre.id]);
  expect((await depot.obtenir(seconde.id))?.statut).toBe("en_attente");
  expect(rapport.bloquees).toContain(seconde.id);
});

const contenu = (contenu_id = "contenu-fictif"): LigneContenuM7 => ({
  contenu_id, wct_id: `wct-${contenu_id}`, plateforme: "instagram", revision: 1,
  approval_status: "PROPOSE", exporte: false, marque_source: null, fraicheur_marque: "preuve_absente",
  texte: "Texte fictif", origine_texte: "gabarit", mots_clics: [], lien_utm: null, avertissements: [], decision: null,
  consentement: { recueilli_par: "owner.fictif", recueilli_le: "2026-10-07T12:00:00Z", version_texte: "v1-fictif" },
});
async function decisionPersistee(depot: DepotOutboxMemoire, contenu_id = "contenu-fictif", personne = session.personne) {
  return avecProprietaire(depot, () => personne, () => session.urlBase).inserer(creerMutationDecisionMarketing(contenu(contenu_id), "approuver", "", id, horloge));
}
function ack(contenu_id = "contenu-fictif", par = session.personne) {
  return { contenu_id, plateforme: "instagram", approval_status: "APPROVED", par, source: "appareil",
    horodatage: "2026-10-07T12:00:00Z", empreinte_texte: "a".repeat(64), prochaine_etape: "suite fictive" };
}
const couple = (value: unknown) => ({ ok: true, resultat: { accepte: true, resultat: value } });
const http = (result: unknown, status = 200) => new Response(JSON.stringify({ ok: true, result }), { status });
function vidangeM7(depot: DepotOutboxMemoire, fetchImpl: typeof fetch, maintenant: () => Date = () => horloge.maintenant,
  obtenirSession = () => session) {
  return creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, maintenant, session: obtenirSession });
}
function requetes(fetchImpl: jest.Mock): Array<{ tool: string; args: Record<string, unknown>; idempotencyKey: string;
  deviceId: string; deviceTimestamp: string }> {
  return fetchImpl.mock.calls.map(([_url, init]) => JSON.parse(init.body));
}

test("descripteur réel : payload durable avant fetch, propriétaire lié et aucun champ local envoyé", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
  const fetchImpl = jest.fn(async () => {
    expect(await depot.obtenir(m.id)).toMatchObject({ statut: "envoi", proprietaire: session.personne, payload: m.payload });
    return http(couple(ack()));
  });
  const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.envoyees).toEqual([m.id]);
  expect(requetes(fetchImpl)).toEqual([{ tool: "m7_decider_contenu", args: {
    contenu_id: "contenu-fictif", decision: "approuver", horodatage: m.createdAtLocal,
  }, idempotencyKey: m.id, deviceId: session.appareilId, deviceTimestamp: m.createdAtLocal }]);
  expect((await depot.obtenir(m.id))?.resumeAccepte).toEqual(ack());
});

test("ACK mal lié puis redémarrage mémoire : même UUID/payload/owner, recul et nouvel effet même objet bloqué", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot), autreIntention = await decisionPersistee(depot);
  const fetchImpl = jest.fn(async () => http(couple(ack("contenu-fictif", "personne-incorrecte-fictive"))));
  const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.remisesEnAttente).toEqual([m.id]);
  expect(rapport.bloquees).toContain(autreIntention.id);
  expect(fetchImpl).toHaveBeenCalledTimes(1);
  const conservée = await depot.obtenir(m.id);
  expect(conservée).toMatchObject({ id: m.id, payload: m.payload, proprietaire: session.personne,
    statut: "en_attente", tentatives: 1 });
  expect(conservée?.prochaineTentativeA).not.toBeNull();
  const redemarre = new DepotOutboxMemoire();
  const lignes: MutationOutbox[] = JSON.parse(JSON.stringify(await depot.lister()));
  for (const ligne of lignes) await redemarre.inserer(ligne);
  const repriseFetch = jest.fn(async () => http({ ...couple(ack()), rejoue: true }));
  const tropTot = await vidangeM7(redemarre, repriseFetch).vidangerFileSortante();
  expect(tropTot.envoyees).toEqual([]);
  expect(tropTot.bloquees).toContain(autreIntention.id);
  expect(repriseFetch).not.toHaveBeenCalled();
  const reprise = await vidangeM7(redemarre, repriseFetch, () => new Date("2026-10-07T12:00:02Z")).vidangerFileSortante();
  expect(reprise.envoyees).toEqual([m.id]);
  expect(repriseFetch).toHaveBeenCalledTimes(1);
  expect(requetes(repriseFetch)[0]).toEqual(requetes(fetchImpl)[0]);
  expect(decisionsMarketingEnFile(await redemarre.lister()).find(d => d.id === m.id))
    .toMatchObject({ personne: session.personne, statut: "envoyee" });
});

test.each([undefined, {}, { ok: true, resultat: ack() }, couple({ ...ack(), contenu_id: "autre" })])(
  "réponse inconnue %p conservée avec recul, pas transformée en refus permanent", async result => {
    const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
    const fetchImpl = jest.fn(async () => http(result));
    const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
    expect(rapport.remisesEnAttente).toEqual([m.id]);
    expect(rapport.echecsPermanents).toEqual([]);
    expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente", tentatives: 1 });
  },
);

test("refus métier explicite terminal : aucune reprise automatique, autres objets peuvent partir", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot, "a-contenu-fictif");
  const autre = await decisionPersistee(depot, "z-contenu-fictif");
  const fetchImpl = jest.fn()
    .mockResolvedValueOnce(http({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-CONTENU-PERIME", detail: "fictif" } } }))
    .mockResolvedValueOnce(http(couple(ack("z-contenu-fictif"))));
  const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.echecsPermanents).toEqual([{ id: m.id, verdict: { code: "REJ-CONTENU-PERIME", detail: "fictif" } }]);
  expect(rapport.envoyees).toEqual([autre.id]);
  expect((await depot.obtenir(m.id))?.statut).toBe("echec_permanent");
  await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(fetchImpl).toHaveBeenCalledTimes(2);
});

test("quarantaine du premier owner bloque l'intention suivante du même objet ; objet distinct indépendant", async () => {
  const depot = new DepotOutboxMemoire(), ancienne = await decisionPersistee(depot, "a-contenu-fictif", "ancienne.fictive");
  const suivante = await decisionPersistee(depot, "a-contenu-fictif"), autre = await decisionPersistee(depot, "z-contenu-fictif");
  const fetchImpl = jest.fn(async () => http(couple(ack("z-contenu-fictif"))));
  const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.quarantaine).toContain(ancienne.id);
  expect(rapport.bloquees).toContain(suivante.id);
  expect(rapport.envoyees).toEqual([autre.id]);
  expect(decisionsMarketingEnFile(await depot.lister()).find(d => d.id === ancienne.id)?.personne).toBe("ancienne.fictive");
  expect(fetchImpl).toHaveBeenCalledTimes(1);
});

test("révocation HTTP conserve l'intention sans faute ni nouvel effet", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot), suivante = await decisionPersistee(depot);
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ ok: false,
    error: { type: "tool_call_blocked", message: "device_unknown fictif" } }), { status: 401 }));
  const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.arret).toMatchObject({ genre: "appareil_refuse", mutationId: m.id });
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente", tentatives: 0 });
  expect((await depot.obtenir(suivante.id))?.statut).toBe("en_attente");
  expect(fetchImpl).toHaveBeenCalledTimes(1);
});

test("payload local mal formé retenu sans aucun RPC, même UUID et payload", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
  const payload = { ...m.payload, _marketing_local: null };
  await depot.mettreAJour({ ...m, payload });
  const fetchImpl = jest.fn(async () => http(couple(ack())));
  const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(rapport.remisesEnAttente).toEqual([m.id]);
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload, statut: "en_attente", tentatives: 1 });
});

test("un reçu terminal concurrent observé avant dispatch n'est jamais rouvert ni écrasé", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
  const mettre = depot.mettreAJour.bind(depot);
  const comparer = depot.mettreAJourSiInchangee.bind(depot);
  jest.spyOn(depot, "mettreAJourSiInchangee").mockImplementationOnce(async (attendue, envoi) => {
    // Un autre worker a reçu l'ACK pendant cette transition locale ; le dépôt expose désormais ce reçu.
    await mettre({ ...envoi, statut: "envoyee", resumeAccepte: ack() });
    return comparer(attendue, envoi);
  });
  const fetchImpl = jest.fn(async () => http(couple(ack())));
  await vidangeM7(depot, fetchImpl).vidangerFileSortante();
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "envoyee", resumeAccepte: ack() });
});

test("rôle retiré avec même tuple pendant stockage : pas de HTTP, même intention sans faute ; regrant reprend", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
  let generation = 1;
  const lister = depot.lister.bind(depot);
  jest.spyOn(depot, "lister").mockImplementationOnce(async () => { generation++; return lister(); });
  const fetchImpl = jest.fn(async () => http(couple(ack())));
  const vidangeur = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, session: () => session, maintenant: () => horloge.maintenant,
    capturerGardeSession: () => { const capture = generation; return () => capture === generation; } });
  const retrait = await vidangeur.vidangerFileSortante();
  expect(retrait.arret).toEqual({ genre: "session_changee" });
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente", tentatives: 0 });
  const regrant = await vidangeur.vidangerFileSortante();
  expect(regrant.envoyees).toEqual([m.id]);
});

test("guard d'appel périmé avant bootstrap garde le dépôt et le réseau fermés", async () => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
  const lister = jest.spyOn(depot, "lister"), fetchImpl = jest.fn(async () => http(couple(ack())));
  const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante(() => false);
  expect(rapport.arret).toEqual({ genre: "session_changee" });
  expect(lister).not.toHaveBeenCalled();
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload, statut: "en_attente", tentatives: 0 });
});

test.each([false, true])("retrait pendant mise à jour locale, reçu concurrent=%p : jamais de dispatch ni reçu écrasé", async terminal => {
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
  let generation = 1;
  const mettre = depot.mettreAJour.bind(depot);
  const comparer = depot.mettreAJourSiInchangee.bind(depot);
  jest.spyOn(depot, "mettreAJourSiInchangee").mockImplementationOnce(async (attendue, envoi) => {
    generation++;
    if (terminal) await mettre({ ...envoi, statut: "envoyee", resumeAccepte: ack() });
    return comparer(attendue, envoi);
  });
  const fetchImpl = jest.fn(async () => http(couple(ack())));
  const vidangeur = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, session: () => session, maintenant: () => horloge.maintenant,
    capturerGardeSession: () => { const capture = generation; return () => capture === generation; } });
  await vidangeur.vidangerFileSortante();
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload,
    statut: terminal ? "envoyee" : "en_attente", tentatives: 0, resumeAccepte: terminal ? ack() : null });
});

test("service natif simulé : garde avant SQLite, rôle changé au bootstrap, singleton/verrou conservés", async () => {
  // Assemblage natif réel, seuls SQLite et fetch sont simulés ; aucun téléphone dans cette preuve.
  const depot = new DepotOutboxMemoire(), m = await decisionPersistee(depot);
  let ouvrir!: (base: object) => void;
  const ouverture = new Promise<object>(resolve => { ouvrir = resolve; });
  const openDatabaseAsync = jest.fn(() => ouverture);
  let repondre!: (reponse: Response) => void;
  const reponse = new Promise<Response>(resolve => { repondre = resolve; });
  let signalerDispatch!: () => void;
  const dispatch = new Promise<void>(resolve => { signalerDispatch = resolve; });
  const fetchImpl = jest.spyOn(globalThis, "fetch").mockImplementation(() => { signalerDispatch(); return reponse; });
  jest.doMock("expo-sqlite", () => ({ openDatabaseAsync }));
  jest.doMock("./depot.sqlite", () => ({ initialiserSchemaOutbox: jest.fn(async () => undefined),
    creerDepotOutboxSqlite: () => depot }));
  try {
    await jest.isolateModulesAsync(async () => {
      const configuration: typeof import("../protocole/configuration") = require("../protocole/configuration");
      const service: typeof import("./service") = require("./service");
      configuration.definirConfigurationAppel(session);
      configuration.definirPersonneConfirmee({ ...session, role: "admin" });
      expect(await service.declencherVidange(() => false)).toBeNull();
      expect(openDatabaseAsync).not.toHaveBeenCalled();
      const bootstrap = service.declencherVidange();
      expect(openDatabaseAsync).toHaveBeenCalledTimes(1);
      configuration.definirPersonneConfirmee({ ...session, role: "vendeur" });
      ouvrir({});
      expect((await bootstrap)?.arret).toEqual({ genre: "session_changee" });
      expect(fetchImpl).not.toHaveBeenCalled();
      expect(await depot.obtenir(m.id)).toMatchObject({ id: m.id, statut: "en_attente", tentatives: 0, payload: m.payload });
      configuration.definirPersonneConfirmee({ ...session, role: "admin" });
      const reprise = service.declencherVidange();
      await dispatch;
      expect(fetchImpl).toHaveBeenCalledTimes(1);
      expect((await service.declencherVidange())?.ignoreeVerrouActif).toBe(true);
      repondre(http(couple(ack())));
      expect((await reprise)?.envoyees).toEqual([m.id]);
      expect(openDatabaseAsync).toHaveBeenCalledTimes(1);
    });
  } finally {
    fetchImpl.mockRestore();
    jest.dontMock("expo-sqlite");
    jest.dontMock("./depot.sqlite");
  }
});

test("garde optionnelle sur type historique : reçu terminal pendant stockage conservé", async () => {
  const depot = new DepotOutboxMemoire();
  const m = await avecProprietaire(depot, () => session.personne, () => session.urlBase).inserer(soumettreMutation(creerMutation({
    type: "punch_in", chantierId: "chantier-fictif", payload: {},
  }, id, horloge)));
  let generation = 1;
  const mettre = depot.mettreAJour.bind(depot);
  const comparer = depot.mettreAJourSiInchangee.bind(depot);
  jest.spyOn(depot, "mettreAJourSiInchangee").mockImplementationOnce(async (attendue, envoi) => {
    await mettre({ ...envoi, statut: "envoyee", resumeAccepte: { preuve: "terminale-fictive" } });
    generation++;
    return comparer(attendue, envoi);
  });
  const appeler = jest.fn(async () => ({ ok: true as const, result: {} }));
  const vidangeur = creerVidangeur({ depot,
    descripteurs: new Map<TypeMutation, DescripteurTypeMutation>([["punch_in", {
      tool: "m4_pointer", interpreterResultat: () => ({ accepte: true, resume: {} }),
    }]]), appelerOutil: appeler, fetchImpl: jest.fn(), session: () => session, maintenant: () => horloge.maintenant,
    capturerGardeSession: () => { const capture = generation; return () => capture === generation; } });
  expect((await vidangeur.vidangerFileSortante()).arret).toEqual({ genre: "session_changee" });
  expect(appeler).not.toHaveBeenCalled();
  expect(await depot.obtenir(m.id)).toMatchObject({ statut: "envoyee", resumeAccepte: { preuve: "terminale-fictive" } });
});

test.each([null, ack("a-contenu-fictif", "personne-erronee-fictive"), ack("autre-contenu-fictif")])(
  "envoyee avec reçu non lié %p : seconde intention bloquée, autre contenu libre, reçu conservé", async resumeAccepte => {
    const depot = new DepotOutboxMemoire(), premiere = await decisionPersistee(depot, "a-contenu-fictif");
    await depot.mettreAJour({ ...premiere, statut: "envoyee", resumeAccepte });
    const suivante = await decisionPersistee(depot, "a-contenu-fictif"), autre = await decisionPersistee(depot, "z-contenu-fictif");
    const fetchImpl = jest.fn(async (_url, init) => {
      const requete = JSON.parse(init.body);
      return http(couple(ack(requete.args.contenu_id)));
    });
    const rapport = await vidangeM7(depot, fetchImpl).vidangerFileSortante();
    expect(requetes(fetchImpl).map(r => r.idempotencyKey)).toEqual([autre.id]);
    expect(rapport.bloquees).toContain(suivante.id);
    expect(await depot.obtenir(premiere.id)).toEqual({ ...premiere, statut: "envoyee", resumeAccepte });
    expect(await depot.obtenir(suivante.id)).toMatchObject({ id: suivante.id, payload: suivante.payload,
      statut: "en_attente", tentatives: 0 });
    // Une réparation du reçu est explicite ; seules les données désormais liées libèrent la série.
    await depot.mettreAJour({ ...premiere, statut: "envoyee", resumeAccepte: ack("a-contenu-fictif") });
    expect((await vidangeM7(depot, fetchImpl).vidangerFileSortante()).envoyees).toEqual([suivante.id]);
    expect(requetes(fetchImpl).map(r => r.idempotencyKey)).toEqual([autre.id, suivante.id]);
  },
);
