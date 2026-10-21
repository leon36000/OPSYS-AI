import { creerControleMemoire } from "./controle";
import { lireDossierRevisionM10 } from "./dossier";
import { lireReferencesM10, lireSignauxM10 } from "./contrat";
import { FIXTURES_M10 } from "./fixtures";
import { FIXTURES_DOSSIER_M10 } from "./fixturesDossier";
import { creerMutationArbitrageMemoire } from "./arbitrageOutbox";
import { DepotOutboxMemoire, type DepotOutbox } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
import { creerVidangeur } from "../outbox/vidangeur";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { invoquerOutil } from "../protocole/client";
import type { ResultatSection } from "../admin/lecture";
import type { SessionEnvoi } from "../protocole/configuration";
import type { DossierRevisionM10 } from "./dossier";
import type { ChoixArbitrageMemoire } from "./arbitrageOutbox";
import type { MutationOutbox } from "../outbox/types";
const f = FIXTURES_M10.reponses, fd = FIXTURES_DOSSIER_M10.reponses.dossier_complet;
const revisionId = fd.args.revision_ligne_id;
const session: SessionEnvoi = { urlBase: "https://fictif.local", jeton: "jeton-fictif", appareilId: "device-fictif", personne: "gestionnaire.fictif" };
const horloge = () => ({ maintenant: new Date("2026-09-16T15:10:00Z"), decalageMinutesUTC: -240 });
// Calculé par encodage.py canonique (vecteur-ack-dossier-01.json), sans crypto miroir dans le test.
const ack = { ...f.arbitrage_accepte.enveloppe.resultat.resultat, revision_ligne_id: revisionId,
  ligne_id: "b9b04a4382a7b29ffb92637d650781589d1db50435a84093bc8e92b24d975639" };
const serveur = <T>(valeur: T): ResultatSection<T> => ({ source: "serveur", valeur, misAJourLe: "2026-09-16T15:10:00Z" });
function dossier(statut: ChoixArbitrageMemoire = "en_attente"): DossierRevisionM10 {
  const b = fd.enveloppe.resultat.resultat;
  const revision = statut === "en_attente" ? b.revision : { ...b.revision, statut,
    statut_le: ack.horodatage, reference_statut: { registre: "affaires", ligne_id: ack.ligne_id, hash_tete: ack.ligne_id } };
  const r = lireDossierRevisionM10({ ok: true, resultat: { accepte: true, resultat: { revision, faits: b.faits } } }, revisionId);
  if (!r.ok) throw new Error(r.detail);
  return r.value;
}
function valeur<T>(r: { ok: true; value: T } | { ok: false; detail: string }): T {
  if (!r.ok) throw new Error(r.detail); return r.value;
}
function harness(options: { depot?: DepotOutbox; cache?: boolean; fetch?: typeof fetch;
  obtenirDepot?: () => Promise<DepotOutbox>; dossier?: () => Promise<ResultatSection<DossierRevisionM10> | null> } = {}) {
  let courante: SessionEnvoi | null = session, epoch = 0, status: ChoixArbitrageMemoire = "en_attente", index = 0;
  const base = options.depot ?? new DepotOutboxMemoire(), depot = avecProprietaire(base, () => courante?.personne ?? null, () => courante?.urlBase ?? null);
  const captures = () => { const e = epoch, s = courante; return { session: s, courante: () => s !== null && courante !== null && e === epoch }; };
  const calls: string[] = [];
  const fetchImpl = options.fetch ?? jest.fn(async () => { status = "distincts_confirmes"; return new Response(JSON.stringify({ ok: true, result: f.arbitrage_accepte.enveloppe.ok ? { ok: true, resultat: { accepte: true, resultat: ack } } : null })); });
  const v = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, maintenant: () => horloge().maintenant, session: () => courante,
    capturerGardeSession: () => captures().courante });
  const informer = <T>(valeur: T): ResultatSection<T> => options.cache
    ? { source: "cache", valeur, misAJourLe: "2026-09-15T15:10:00Z", raisonHorsLigne: { code: "hors_ligne", detail: "" } } : serveur(valeur);
  const deps = {
    capturerSession: captures, enLigne: () => true, horloge, genererId: jest.fn(() => `uuid-${++index}`),
    obtenirDepot: options.obtenirDepot ?? (async () => depot), vidanger: (g: () => boolean) => v.vidangerFileSortante(g),
    chargerSignaux: async () => { calls.push("signaux"); return informer(valeur(lireSignauxM10(f.signaux_ouverts.enveloppe))); },
    chargerReferences: async (offset = 0) => { calls.push(`catalogue:${offset}`); return informer(valeur(lireReferencesM10(offset === 0 ? f.catalogue_page_1.enveloppe : f.catalogue_page_2.enveloppe))); },
    chargerDossier: options.dossier ?? (async () => { calls.push("dossier"); return serveur(dossier(status)); }),
    chargerStatutRevision: async () => { calls.push("statutRevision"); return serveur({ statut: status }); },
    chargerStatutDecision: async () => { calls.push("statutDecision"); return serveur({ statut: null }); },
  };
  const control = creerControleMemoire(deps); control.actualiserConnectivite(true);
  return { control, deps, calls, depot, fetchImpl, captures, fixerStatut: (s: ChoixArbitrageMemoire) => { status = s; },
    retirerScopes: () => { epoch++; }, changerPersonne: () => { epoch++; courante = { ...session, personne: "autre.fictif" }; } };
}

test("pages courantes indépendantes, suite remplace, statuts inconnus ne deviennent pas décisions", async () => {
  const h = harness(); await h.control.charger();
  expect(h.control.etat().catalogue?.source).toBe("serveur");
  await h.control.chargerSuite();
  const c = h.control.etat().catalogue;
  if (c?.source !== "serveur") throw new Error("catalogue serveur attendu");
  expect(c.valeur.decalage).toBe(8); expect(c.valeur.affichees).toBe(8);
  expect(h.calls).toContain("catalogue:8");
  await h.control.lireDecision("Décision inconnue 😀");
  expect(h.control.etat().statutDecision).toMatchObject({ source: "serveur", valeur: { statut: null } });
  expect(h.control.peutArbitrer()).toBe(false);
});

test("arbitrage : dossier2faits serveur, persistance avant HTTP et relecture des statuts", async () => {
  const base = new DepotOutboxMemoire();
  const h = harness({ depot: base });
  await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect(h.control.peutArbitrer()).toBe(true);
  expect(await h.control.arbitrer("distincts_confirmes")).toEqual({ ok: true, code: "relue" });
  const rows = await base.lister();
  expect(rows).toHaveLength(1);
  expect(rows[0]).toMatchObject({ statut: "envoyee", proprietaire: session.personne, resumeAccepte: ack });
  expect(h.calls.filter(x => x === "statutRevision")).toHaveLength(2);
  expect(h.control.etat().statutRevision).toMatchObject({ source: "serveur", valeur: { statut: "distincts_confirmes" } });
});

test("cache de catalogue ou dossier ne peut autoriser une action", async () => {
  const h = harness({ cache: true, dossier: async () => ({ source: "cache", valeur: dossier(),
    misAJourLe: "2026-09-15T15:10:00Z", raisonHorsLigne: { code: "hors_ligne", detail: "" } }) });
  await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect(h.control.peutArbitrer()).toBe(false);
  expect((await h.control.arbitrer("distincts_confirmes")).ok).toBe(false);
  expect(h.fetchImpl).not.toHaveBeenCalled();
});

test("la persistance précède HTTP, aucune RPC directe depuis un port lecture", async () => {
  const base = new DepotOutboxMemoire();
  const fetchImpl = jest.fn(async (_input: Parameters<typeof fetch>[0], _init?: Parameters<typeof fetch>[1]) => {
    expect(await base.obtenir("uuid-1")).toMatchObject({ statut: "envoi", proprietaire: session.personne,
      payload: { revision_ligne_id: revisionId, statut: "distincts_confirmes", horodatage: "2026-09-16T11:10:00-04:00" } });
    h.fixerStatut("distincts_confirmes");
    return new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: { accepte: true, resultat: ack } } }));
  });
  const h = harness({ depot: base, fetch: fetchImpl });
  await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect((await h.control.arbitrer("distincts_confirmes")).ok).toBe(true);
  const init = fetchImpl.mock.calls[0]?.[1];
  expect(typeof init?.body).toBe("string");
  if (typeof init?.body !== "string") throw new Error("corps JSON attendu");
  const wire = JSON.parse(init.body);
  expect(wire.tool).toBe("m10_arbitrer_revision"); expect(wire.idempotencyKey).toBe("uuid-1");
  expect(wire.args).not.toHaveProperty("role"); expect(wire.args).not.toHaveProperty("par");
});

test("réponse perdue puis refresh/restart ne crée pas une seconde intention et conserve le recul", async () => {
  const depot = new DepotOutboxMemoire(), fetchImpl = jest.fn(async () => { throw new Error("réponse perdue"); });
  const h = harness({ depot, fetch: fetchImpl });
  await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect((await h.control.arbitrer("distincts_confirmes")).code).toBe("decision_incertaine");
  const mutation = await depot.obtenir("uuid-1");
  expect(mutation).toMatchObject({ statut: "en_attente", tentatives: 1, proprietaire: session.personne });
  expect(mutation?.prochaineTentativeA).not.toBeNull();
  await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect(h.control.peutArbitrer()).toBe(false);
  const restart = harness({ depot }); await restart.control.charger(); await restart.control.ouvrirRevision(revisionId);
  expect(restart.control.peutArbitrer()).toBe(false);
  await restart.control.arbitrer("distincts_confirmes");
  expect(restart.deps.genererId).not.toHaveBeenCalled();
  expect(await depot.lister()).toHaveLength(1);
  expect(fetchImpl).toHaveBeenCalledTimes(1);
});

test("refus connu terminal libère une action future ; le détail serveur reste brut", async () => {
  const fetchImpl = jest.fn(async () => new Response(JSON.stringify({ ok: true, result: { ok: true,
    resultat: { accepte: false, verdict: { code: "REJ-REVISION-SIGNALEMENT-INTROUVABLE", detail: "Détail serveur fictif exact" } } } })));
  const h = harness({ fetch: fetchImpl }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect(await h.control.arbitrer("distincts_confirmes")).toEqual({ ok: false, code: "refus_serveur_relue" });
  expect(h.control.etat().message).toBe("Détail serveur fictif exact");
  expect(h.control.peutArbitrer()).toBe(true);
  expect((await h.depot.obtenir("uuid-1"))?.statut).toBe("echec_permanent");
});

test("réponse inconnue demeure persistée, sans refus permanent inventé", async () => {
  const h = harness({ fetch: jest.fn(async () => new Response(JSON.stringify({ ok: true, result: {} }))) });
  await h.control.charger(); await h.control.ouvrirRevision(revisionId); await h.control.arbitrer("distincts_confirmes");
  expect(h.control.etat().intentions).toMatchObject([{ id: "uuid-1", revisionId, statut: "en_attente", personne: session.personne }]);
  expect(h.control.peutArbitrer()).toBe(false);
});

test("stockage échoue avant insertion : aucune RPC, UUID non abandonné en réseau", async () => {
  class DepotDefaillant extends DepotOutboxMemoire {
    async inserer(_m: MutationOutbox): Promise<MutationOutbox> { throw new Error("pas d’écriture"); }
  }
  const h = harness({ depot: new DepotDefaillant() }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect((await h.control.arbitrer("distincts_confirmes")).code).toBe("stockage_impossible");
  expect(h.fetchImpl).not.toHaveBeenCalled(); expect(await h.depot.lister()).toEqual([]);
});

test("quarantaine, identifiant inconnu et mauvais reçu terminal bloquent sans inventer la personne", async () => {
  for (const patch of [{ proprietaire: "autre.fictif" }, { chantierId: "memoire_revision:", payload: {}, proprietaire: null },
    { statut: "envoyee" as const, resumeAccepte: { ...ack, ligne_id: "a".repeat(64) } }]) {
    const depot = new DepotOutboxMemoire();
    await depot.inserer({ ...creerMutationArbitrageMemoire(revisionId, "distincts_confirmes", () => "ancienne", horloge()),
      proprietaire: session.personne, ...patch });
    const h = harness({ depot }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
    expect(h.control.peutArbitrer()).toBe(false);
    expect(h.control.etat().intentions[0].personne).toBe(patch.proprietaire === undefined ? session.personne : patch.proprietaire);
    if ("chantierId" in patch) expect(h.control.etat().intentions[0].revisionId).toBeNull();
    await h.control.arbitrer("distincts_confirmes"); expect(h.fetchImpl).not.toHaveBeenCalled();
  }
});

test("rôle retiré à tuple identique masque la comparaison et interdit l’arbitrage", async () => {
  const h = harness(); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  h.retirerScopes(); expect(h.control.etat().dossier).toBeNull(); expect(h.control.peutArbitrer()).toBe(false);
  await h.control.arbitrer("distincts_confirmes"); expect(h.fetchImpl).not.toHaveBeenCalled();
});

test("ACK tardif durable après changement personne reste reçu mais ancienne UI cachée", async () => {
  let release!: (r: Response) => void, appele!: () => void;
  const requete = new Promise<void>(resolve => { appele = resolve; });
  const fetchImpl = jest.fn(() => { appele(); return new Promise<Response>(resolve => { release = resolve; }); });
  const h = harness({ fetch: fetchImpl }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  const p = h.control.arbitrer("distincts_confirmes"); await requete; h.changerPersonne();
  release(new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: { accepte: true, resultat: ack } } })));
  expect((await p).code).toBe("identite_changee");
  expect(await h.depot.obtenir("uuid-1")).toMatchObject({ statut: "envoyee", resumeAccepte: ack });
  expect(h.control.etat().dossier).toBeNull(); expect(h.control.etat().intentions).toEqual([]);
});

test("refresh et seconde intention restent bloqués pendant réseau et relecture", async () => {
  let release!: (r: Response) => void, appele!: () => void;
  const requete = new Promise<void>(resolve => { appele = resolve; });
  const fetchImpl = jest.fn(() => { appele(); return new Promise<Response>(resolve => { release = resolve; }); });
  const h = harness({ fetch: fetchImpl }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  const p = h.control.arbitrer("distincts_confirmes"); await requete;
  const avant = [...h.calls]; await h.control.charger(); await h.control.chargerSuite();
  expect(h.calls).toEqual(avant); expect((await h.control.arbitrer("en_attente")).ok).toBe(false);
  h.fixerStatut("distincts_confirmes");
  release(new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: { accepte: true, resultat: ack } } })));
  await p; expect(fetchImpl).toHaveBeenCalledTimes(1);
});

test("hors ligne : intentions réelles conservées, aucune autorité de dossier/cache", async () => {
  const depot = new DepotOutboxMemoire();
  await depot.inserer({ ...creerMutationArbitrageMemoire(revisionId, "en_attente", () => "persistée", horloge()), proprietaire: session.personne });
  const h = harness({ depot, cache: true }); h.control.actualiserConnectivite(false);
  await h.control.charger();
  expect(h.control.etat().intentions).toEqual([{ id: "persistée", revisionId, statut: "en_attente", personne: session.personne, choix: "en_attente" }]);
  expect(h.control.etat().catalogue?.source).toBe("cache");
  expect(h.control.peutArbitrer()).toBe(false);
});

test("ACK tardif hors ligne : projection locale relue réelle, comparaison toujours masquée", async () => {
  let release!: (r: Response) => void, appele!: () => void;
  const requete = new Promise<void>(resolve => { appele = resolve; });
  const fetchImpl = jest.fn(() => { appele(); return new Promise<Response>(resolve => { release = resolve; }); });
  const h = harness({ fetch: fetchImpl }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  const p = h.control.arbitrer("distincts_confirmes"); await requete;
  h.control.actualiserConnectivite(false);
  release(new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: { accepte: true, resultat: ack } } })));
  await p;
  expect(await h.depot.obtenir("uuid-1")).toMatchObject({ statut: "envoyee" });
  expect(h.control.etat().intentions[0].statut).toBe("envoyee");
  expect(h.control.etat().dossier).toBeNull(); expect(h.control.peutArbitrer()).toBe(false);
});

test.each(["deconnexion", "invalidation"])("relecture suspendue après ACK : %s conserve le reçu sans restaurer l’ancienne UI", async perturbation => {
  let release!: (r: ResultatSection<DossierRevisionM10>) => void, appele!: () => void, lectures = 0;
  const relecture = new Promise<void>(resolve => { appele = resolve; });
  const h = harness({ dossier: async () => {
    if (++lectures === 1) return serveur(dossier());
    appele();
    return new Promise<ResultatSection<DossierRevisionM10>>(resolve => { release = resolve; });
  } });
  await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  const p = h.control.arbitrer("distincts_confirmes"); await relecture;
  const recu = await h.depot.obtenir("uuid-1");
  expect(recu).toMatchObject({ statut: "envoyee", resumeAccepte: ack });
  // L’ACK a été persisté, mais le verrou couvre encore la vraie relecture suspendue.
  const avant = [...h.calls]; await h.control.charger(); await h.control.chargerSuite();
  expect(h.calls).toEqual(avant);
  expect((await h.control.arbitrer("en_attente")).ok).toBe(false);
  if (perturbation === "deconnexion") h.control.actualiserConnectivite(false);
  else h.control.invalider();
  release(serveur(dossier("distincts_confirmes")));
  expect((await p).code).toBe("identite_changee");
  expect(await h.depot.obtenir("uuid-1")).toEqual(recu);
  expect(h.fetchImpl).toHaveBeenCalledTimes(1); expect(h.deps.genererId).toHaveBeenCalledTimes(1);
  expect(h.control.peutArbitrer()).toBe(false); expect(h.control.etat().dossier).toBeNull();
  if (perturbation === "deconnexion") {
    expect(h.control.etat()).toMatchObject({ statut: "hors_ligne", messageCode: "connexion" });
    expect(h.control.etat().intentions[0]).toMatchObject({ id: "uuid-1", statut: "envoyee" });
  } else {
    expect(h.control.etat()).toMatchObject({ statut: "inactif", revisionId: null, messageCode: null, intentions: [] });
  }
});

test("deux hashes sans champ métier ne suffisent pas à autoriser l’arbitrage", async () => {
  function sansChamps(): DossierRevisionM10 {
    const d = dossier(); return { ...d, faits: [{ ...d.faits[0], champs: {} }, d.faits[1]] };
  }
  const h = harness({ dossier: async () => serveur(sansChamps()) });
  await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect(h.control.peutArbitrer()).toBe(false);
  await h.control.arbitrer("distincts_confirmes"); expect(h.fetchImpl).not.toHaveBeenCalled();
});

test("une carte en cache peut ouvrir un dossier serveur frais, seule cette lecture autorise", async () => {
  const h = harness({ cache: true }); await h.control.charger();
  expect(h.control.peutArbitrer()).toBe(false);
  await h.control.ouvrirRevision(revisionId);
  expect(h.control.etat().dossier?.source).toBe("serveur");
  expect(h.control.peutArbitrer()).toBe(true);
});

test("même intention rejouée après recul, aucune nouvelle UUID après restart du contrôleur", async () => {
  const fetchImpl = jest.fn<ReturnType<typeof fetch>, Parameters<typeof fetch>>()
    .mockRejectedValueOnce(new Error("réponse perdue après effet fictif"))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, result: { ok: true,
      resultat: { accepte: true, resultat: ack }, rejoue: true } })));
  const h = harness({ fetch: fetchImpl }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  await h.control.arbitrer("distincts_confirmes");
  const reprise = creerVidangeur({ depot: h.depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
    fetchImpl, session: () => session, maintenant: () => new Date("2026-09-16T15:10:02Z") });
  expect((await reprise.vidangerFileSortante()).envoyees).toEqual(["uuid-1"]);
  h.fixerStatut("distincts_confirmes"); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect(h.control.etat().intentions[0].statut).toBe("envoyee");
  expect(h.deps.genererId).toHaveBeenCalledTimes(1);
  const wires = fetchImpl.mock.calls.map(([_url, init]) => typeof init?.body === "string" ? JSON.parse(init.body) : null);
  expect(wires).toHaveLength(2); expect(wires[0]).toEqual(wires[1]);
});

test("scope retiré pendant insertion persistée : pas de HTTP, intention durable jamais perdue", async () => {
  let sauvegardee!: () => void, release!: () => void;
  const courant = new Promise<void>(r => { sauvegardee = r; });
  class DepotSuspendu extends DepotOutboxMemoire {
    async inserer(m: MutationOutbox): Promise<MutationOutbox> {
      const row = await super.inserer(m); sauvegardee(); await new Promise<void>(r => { release = r; }); return row;
    }
  }
  const depot = new DepotSuspendu(), h = harness({ depot }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  const p = h.control.arbitrer("distincts_confirmes"); await courant; h.retirerScopes(); release();
  expect((await p).code).toBe("identite_changee"); expect(h.fetchImpl).not.toHaveBeenCalled();
  expect(await depot.obtenir("uuid-1")).toMatchObject({ statut: "en_attente", proprietaire: session.personne });
  expect(h.control.etat().dossier).toBeNull();
});

test("retour insertion perdu conserve la ligne et bloque un nouveau contrôleur", async () => {
  class DepotRetourPerdu extends DepotOutboxMemoire {
    async inserer(m: MutationOutbox): Promise<MutationOutbox> { await super.inserer(m); throw new Error("retour perdu"); }
  }
  const depot = new DepotRetourPerdu(), h = harness({ depot }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect((await h.control.arbitrer("distincts_confirmes")).code).toBe("stockage_impossible");
  expect(h.fetchImpl).not.toHaveBeenCalled();
  const restart = harness({ depot }); await restart.control.charger(); await restart.control.ouvrirRevision(revisionId);
  expect(restart.control.peutArbitrer()).toBe(false); expect(await depot.lister()).toHaveLength(1);
});

test("dossier autre cible ou statut absent ne permet pas de décision même après lecture serveur", async () => {
  const mauvais: DossierRevisionM10 = { ...dossier(), revision: { ...dossier().revision, revision_ligne_id: "a".repeat(64) } };
  const h = harness({ dossier: async () => serveur(mauvais) }); await h.control.charger(); await h.control.ouvrirRevision(revisionId);
  expect(h.control.etat().messageCode).toBe("dossierInvalide"); expect(h.control.peutArbitrer()).toBe(false);
  expect(h.fetchImpl).not.toHaveBeenCalled();
});
