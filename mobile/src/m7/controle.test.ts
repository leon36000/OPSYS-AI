import { creerControleMarketing } from "./controle";
import type { AppelM7, LigneContenuM7, SessionM7 } from "./contrat";
import { DepotOutboxMemoire, type DepotOutbox } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
import { creerVidangeur } from "../outbox/vidangeur";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { creerMutationDecisionMarketing } from "./decisionOutbox";
import type { ParametresAppelOutil } from "../protocole/client";
import type { MutationOutbox } from "../outbox/types";

const session: SessionM7 = { urlBase: "https://local", jeton: "jeton-a", appareilId: "app-a", personne: "nathan" };
const ligne = (overrides: Partial<LigneContenuM7> = {}): LigneContenuM7 => ({
  contenu_id: "contenu-1", wct_id: "wct-1", plateforme: "instagram", revision: 1,
  approval_status: "PROPOSE", exporte: false,
  marque_source: { source: "brand_profiles", revision: 1, sha256: "a".repeat(64) },
  fraicheur_marque: "courante", texte: "Texte intégral", origine_texte: "chantier",
  mots_clics: [], lien_utm: "https://example.test", avertissements: [], decision: null,
  consentement: { recueilli_par: "nathan", recueilli_le: "2026-01-01T00:00:00Z", version_texte: "v1" }, ...overrides,
});
const liste = (items = [ligne()]) => ({ total: items.length, marque_courante: { source: "brand_profiles", revision: 1, sha256: "a".repeat(64) }, contenus: items, decalage: 0, suivant: null, reste: 0 });
const directe = (value: unknown) => ({ ok: true as const, resultat: value });
const acc = (value: unknown) => ({ ok: true as const, resultat: { accepte: true, resultat: value } });
const ownerResult = (proprietaire: boolean) => ({ demandes: [], proprietaire, total_en_attente: 0, affichees: 0, reste: 0 });
const decisionResult = (contenuId: string, status: "APPROVED" | "REJECTED") => ({
  contenu_id: contenuId,
  plateforme: "instagram",
  approval_status: status,
  par: "nathan",
  source: "appareil",
  horodatage: "2026-10-04T12:00:00.000Z",
  empreinte_texte: "b".repeat(64),
  prochaine_etape: "suite",
});

function harness(options: { owner?: boolean; list?: () => Promise<unknown>; decide?: () => Promise<unknown>; online?: boolean; session?: () => SessionM7 | null; depot?: DepotOutbox; obtenirDepot?: () => Promise<DepotOutbox>; genererId?: () => string } = {}) {
  let current = options.session ?? (() => session);
  let autorite = 0;
  const calls: string[] = [];
  const directWrites: string[] = [];
  const details: Array<{ tool: string; args?: Record<string, unknown>; mutation?: { idempotencyKey: string; deviceId: string; deviceTimestamp: string } }> = [];
  const attentes: Array<{ tool: string; nombre: number; resolve: () => void }> = [];
  function enregistrer(tool: string, args?: Record<string, unknown>, mutation?: { idempotencyKey: string; deviceId: string; deviceTimestamp: string }) {
    calls.push(tool); details.push({ tool, args, mutation });
    for (const attente of attentes) if (calls.filter(x => x === attente.tool).length >= attente.nombre) attente.resolve();
  }
  function attendreAppel(tool: string, nombre = 1): Promise<void> {
    if (calls.filter(x => x === tool).length >= nombre) return Promise.resolve();
    return new Promise(resolve => attentes.push({ tool, nombre, resolve }));
  }
  const horloge = () => ({ maintenant: new Date("2026-10-04T12:00:00.000Z"), decalageMinutesUTC: 0 });
  const base = options.depot ?? new DepotOutboxMemoire();
  const depot = avecProprietaire(base, () => current()?.personne ?? null);
  const appeler: AppelM7 = async (tool, args, mutation) => {
    enregistrer(tool, args, mutation);
    if (tool === "m9_lister_demandes_approbation") return acc(ownerResult(options.owner ?? true));
    if (tool === "m7_lister_contenus_chantier") return options.list ? options.list() : directe(liste());
    directWrites.push(tool);
    throw new Error("une décision ne passe jamais par le port de lecture");
  };
  const vidangeur = creerVidangeur({
    depot, descripteurs: DESCRIPTEURS_MUTATION, fetchImpl: jest.fn(), session: () => current(), maintenant: () => horloge().maintenant,
    appelerOutil: async ({ requete }: ParametresAppelOutil) => {
      enregistrer(requete.tool, requete.args, { idempotencyKey: requete.idempotencyKey!, deviceId: requete.deviceId!, deviceTimestamp: requete.deviceTimestamp! });
      if (options.decide) return { ok: true, result: await options.decide() };
      return { ok: true, result: acc(decisionResult("contenu-1", "APPROVED")) };
    },
  });
  function capturerSession() {
    const s = current(), generation = autorite;
    return { session: s, courante: () => s !== null && generation === autorite && current() !== null };
  }
  const dependencies = {
    obtenirSession: () => current(), capturerSession, enLigne: () => options.online ?? true, appeler,
    horloge,
    genererId: options.genererId ?? (() => "idem-1"),
    obtenirDepot: options.obtenirDepot ?? (async () => depot),
    vidanger: async (courante: () => boolean) => courante() ? vidangeur.vidangerFileSortante(courante) : null,
  };
  const control = creerControleMarketing(dependencies);
  control.actualiserConnectivite(options.online ?? true);
  return { control, calls, details, directWrites, depot, dependencies, attendreAppel,
    changerScopes: () => { autorite++; },
    changeSession: (s: SessionM7 | null) => { autorite++; current = () => s; } };
}

describe("contrôleur M7 mobile", () => {
  test("persistée avant réseau : UUID, payload, personne et reprise viennent du dépôt", async () => {
    const base = new DepotOutboxMemoire();
    const h = harness({ depot: base, decide: async () => {
      const rows = await base.lister();
      expect(rows).toHaveLength(1);
      expect(rows[0]).toMatchObject({ id: "idem-1", statut: "envoi", proprietaire: "nathan", type: "marketing_decision" });
      expect(rows[0].payload).toHaveProperty("_marketing_local", { plateforme: "instagram", revision: 1, wct_id: "wct-1" });
      return acc(decisionResult("contenu-1", "APPROVED"));
    } });
    await h.control.charger();
    await h.control.decider("contenu-1", "approuver");
    expect(h.directWrites).toEqual([]);
    expect(await base.obtenir("idem-1")).toMatchObject({ statut: "envoyee", resumeAccepte: decisionResult("contenu-1", "APPROVED") });
  });

  test("après refresh et redémarrage une réponse inconnue conserve la même intention", async () => {
    const depot = new DepotOutboxMemoire(), id = jest.fn(() => "durable-1");
    const h = harness({ depot, genererId: id, decide: async () => ({ ok: false, erreur: "code_inconnu" }) });
    await h.control.charger();
    expect(await h.control.decider("contenu-1", "approuver")).toEqual({ ok: false, code: "decision_incertaine" });
    await h.control.charger();
    expect(h.control.etat().intentions).toEqual([{ id: "durable-1", contenuId: "contenu-1", statut: "en_attente", personne: "nathan", decision: "approuver" }]);
    expect(h.control.peutDecider(ligne())).toBe(false);
    const restart = harness({ depot, genererId: id });
    await restart.control.charger();
    expect(restart.control.peutDecider(ligne())).toBe(false);
    await restart.control.decider("contenu-1", "approuver");
    expect(id).toHaveBeenCalledTimes(1);
    expect(restart.calls).not.toContain("m7_decider_contenu");
    expect(await depot.lister()).toHaveLength(1);
  });

  test.each(["brouillon", "en_attente", "envoi"] as const)("une intention %s en file interdit une seconde décision", async statut => {
    const depot = new DepotOutboxMemoire();
    const m = creerMutationDecisionMarketing(ligne(), "approuver", "", () => "ancienne", { maintenant: new Date("2026-10-04T12:00:00Z"), decalageMinutesUTC: 0 });
    await depot.inserer({ ...m, statut, proprietaire: "nathan" });
    const h = harness({ depot });
    await h.control.charger();
    expect(h.control.peutDecider(ligne())).toBe(false);
    expect(h.control.etat().intentions[0].statut).toBe(statut);
  });

  test("quarantaine et données corrompues bloquent sans inventer un objet ou une personne", async () => {
    for (const patch of [{ proprietaire: "autre" }, { payload: {} }, { chantierId: "marketing:", proprietaire: null }] as const) {
      const depot = new DepotOutboxMemoire();
      const m = creerMutationDecisionMarketing(ligne(), "approuver", "", () => "ancienne", { maintenant: new Date("2026-10-04T12:00:00Z"), decalageMinutesUTC: 0 });
      await depot.inserer({ ...m, proprietaire: "nathan", ...patch });
      const h = harness({ depot });
      await h.control.charger();
      expect(h.control.peutDecider(ligne())).toBe(false);
      const projection = h.control.etat().intentions[0];
      expect(projection.personne).toBe(patch.proprietaire === undefined ? "nathan" : patch.proprietaire);
      if ("chantierId" in patch) expect(projection.contenuId).toBeNull();
      await h.control.decider("contenu-1", "approuver");
      expect(h.calls).not.toContain("m7_decider_contenu");
    }
  });

  test("une panne de stockage avant insertion ne déclenche aucun réseau de décision", async () => {
    class DepotDefaillant extends DepotOutboxMemoire {
      async inserer(_m: MutationOutbox): Promise<MutationOutbox> { throw new Error("stockage indisponible"); }
    }
    const depot = new DepotDefaillant(), h = harness({ depot });
    await h.control.charger();
    expect(await h.control.decider("contenu-1", "approuver")).toEqual({ ok: false, code: "stockage_impossible" });
    expect(h.calls).not.toContain("m7_decider_contenu");
    expect(await depot.lister()).toEqual([]);
    expect(h.control.peutDecider(ligne())).toBe(false);
  });

  test("une insertion réussie dont le retour échoue reste bloquante après redémarrage", async () => {
    class DepotRetourDefaillant extends DepotOutboxMemoire {
      async inserer(m: MutationOutbox): Promise<MutationOutbox> { await super.inserer(m); throw new Error("retour perdu"); }
    }
    const depot = new DepotRetourDefaillant(), h = harness({ depot });
    await h.control.charger();
    expect((await h.control.decider("contenu-1", "approuver")).code).toBe("stockage_impossible");
    expect(h.calls).not.toContain("m7_decider_contenu");
    const restart = harness({ depot });
    await restart.control.charger();
    expect(restart.control.peutDecider(ligne())).toBe(false);
    expect(await depot.obtenir("idem-1")).toMatchObject({ statut: "en_attente", proprietaire: "nathan" });
  });

  test("une panne de persistance du reçu ne recrée pas l’intention après effet serveur", async () => {
    class DepotRecuDefaillant extends DepotOutboxMemoire {
      async mettreAJourSiInchangee(...args: Parameters<DepotOutboxMemoire["mettreAJourSiInchangee"]>): Promise<boolean> {
        if (args[1].statut === "envoyee") throw new Error("réception non persistée");
        return await super.mettreAJourSiInchangee(...args);
      }
    }
    const depot = new DepotRecuDefaillant(), h = harness({ depot });
    await h.control.charger();
    expect((await h.control.decider("contenu-1", "approuver")).code).toBe("decision_incertaine");
    await h.control.charger();
    expect(h.control.peutDecider(ligne())).toBe(false);
    expect(await depot.obtenir("idem-1")).toMatchObject({ statut: "envoi" });
    expect(h.calls.filter(x => x === "m7_decider_contenu")).toHaveLength(1);
  });

  test("le retrait des scopes à tuple identique masque immédiatement la page", async () => {
    const h = harness();
    await h.control.charger();
    h.changerScopes();
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.peutDecider(ligne())).toBe(false);
    await h.control.decider("contenu-1", "approuver");
    expect(h.calls).not.toContain("m7_decider_contenu");
  });

  test("les scopes retirés pendant l’ouverture du dépôt empêchent toute insertion", async () => {
    let release!: (d: DepotOutbox) => void, ouvertes = 0;
    const h = harness({ obtenirDepot: () => ++ouvertes === 1 ? Promise.resolve(h.depot) : new Promise(resolve => { release = resolve; }) });
    await h.control.charger();
    const pending = h.control.decider("contenu-1", "approuver");
    h.changerScopes();
    release(h.depot);
    expect(await pending).toEqual({ ok: false, code: "identite_changee" });
    expect(await h.depot.lister()).toEqual([]);
    expect(h.calls).not.toContain("m7_decider_contenu");
  });

  test("les scopes retirés après insertion conservent l’intention sans la transmettre", async () => {
    let release!: () => void;
    class DepotInsertionSuspendue extends DepotOutboxMemoire {
      async inserer(m: MutationOutbox): Promise<MutationOutbox> {
        const row = await super.inserer(m);
        await new Promise<void>(resolve => { release = resolve; });
        return row;
      }
    }
    const depot = new DepotInsertionSuspendue(), h = harness({ depot });
    await h.control.charger();
    const pending = h.control.decider("contenu-1", "approuver");
    while ((await depot.lister()).length === 0 || !release) await Promise.resolve();
    h.changerScopes(); release();
    expect(await pending).toEqual({ ok: false, code: "identite_changee" });
    expect(await depot.obtenir("idem-1")).toMatchObject({ statut: "en_attente", proprietaire: "nathan" });
    expect(h.calls).not.toContain("m7_decider_contenu");
  });

  test("une garde retirée pendant la sélection réelle du vidangeur interdit le HTTP", async () => {
    let selection!: () => void, release!: () => void, lectures = 0;
    const attente = new Promise<void>(resolve => { selection = resolve; });
    class DepotSelectionSuspendue extends DepotOutboxMemoire {
      async lister(): Promise<MutationOutbox[]> {
        if (++lectures === 3) { selection(); await new Promise<void>(resolve => { release = resolve; }); }
        return super.lister();
      }
    }
    const depot = new DepotSelectionSuspendue(), h = harness({ depot });
    await h.control.charger();
    const pending = h.control.decider("contenu-1", "approuver");
    await attente;
    h.changerScopes(); release();
    expect(await pending).toEqual({ ok: false, code: "identite_changee" });
    expect(h.calls).not.toContain("m7_decider_contenu");
    expect(await depot.obtenir("idem-1")).toMatchObject({ statut: "en_attente", tentatives: 0 });
  });

  test("un ACK valide tardif demeure persisté sans réafficher la session retirée", async () => {
    let release!: (value: unknown) => void;
    const h = harness({ decide: () => new Promise(resolve => { release = resolve; }) });
    await h.control.charger();
    const pending = h.control.decider("contenu-1", "approuver");
    await h.attendreAppel("m7_decider_contenu");
    h.changerScopes();
    release(acc(decisionResult("contenu-1", "APPROVED")));
    expect(await pending).toEqual({ ok: false, code: "identite_changee" });
    expect(await h.depot.obtenir("idem-1")).toMatchObject({ statut: "envoyee", resumeAccepte: decisionResult("contenu-1", "APPROVED") });
    expect(h.control.etat().items).toEqual([]);
    expect(h.calls.filter(t => t === "m7_lister_contenus_chantier")).toHaveLength(1);
  });

  test("un reçu terminal mal lié ne libère pas le contenu pour une nouvelle décision", async () => {
    const depot = new DepotOutboxMemoire();
    const m = creerMutationDecisionMarketing(ligne(), "approuver", "", () => "ancienne", { maintenant: new Date("2026-10-04T12:00:00Z"), decalageMinutesUTC: 0 });
    await depot.inserer({ ...m, proprietaire: "nathan", statut: "envoyee", resumeAccepte: { ...decisionResult("contenu-1", "APPROVED"), par: "autre" } });
    const h = harness({ depot }); await h.control.charger();
    expect(h.control.peutDecider(ligne())).toBe(false);
    expect(h.control.etat().sourceDate).toBe("2026-10-04T12:00:00.000Z");
  });

  test("un refus terminal connu permet une nouvelle intention lors d’une passe ultérieure", async () => {
    const depot = new DepotOutboxMemoire();
    const m = creerMutationDecisionMarketing(ligne(), "approuver", "", () => "ancienne", { maintenant: new Date("2026-10-04T12:00:00Z"), decalageMinutesUTC: 0 });
    await depot.inserer({ ...m, proprietaire: "nathan", statut: "echec_permanent" });
    const h = harness({ depot }); await h.control.charger();
    expect(h.control.peutDecider(ligne())).toBe(true);
    await h.control.decider("contenu-1", "approuver");
    expect(await depot.lister()).toHaveLength(2);
    expect(h.calls.filter(t => t === "m7_decider_contenu")).toHaveLength(1);
  });

  test("hors ligne la file est masquée, l’intention durable reste intacte et le code local suit le message", async () => {
    const h = harness({ decide: async () => ({ ok: false, erreur: "code_inconnu" }) });
    await h.control.charger();
    await h.control.decider("contenu-1", "approuver");
    expect(h.control.etat().intentions).toHaveLength(1);
    h.control.actualiserConnectivite(false);
    expect(h.control.etat()).toMatchObject({ statut: "hors_ligne", items: [], intentions: [],
      message: "Connexion indisponible.", codeMessage: "connexion" });
    expect(await h.depot.obtenir("idem-1")).toMatchObject({ statut: "en_attente", proprietaire: "nathan" });
    h.control.actualiserConnectivite(true);
    await h.control.charger();
    expect(h.control.etat().intentions).toHaveLength(1);
    expect(h.control.etat().message).toBeNull();
    expect(h.control.etat().codeMessage).toBeNull();
    expect(h.control.peutDecider(ligne())).toBe(false);
  });

  test("une suite courante remplace la page visible sans promettre un snapshot", async () => {
    let reads = 0;
    const h = harness({ list: async () => {
      reads++;
      return directe({ ...liste(), total: 2, contenus: [ligne({ contenu_id: reads === 1 ? "contenu-1" : "contenu-2", wct_id: reads === 1 ? "wct-1" : "wct-2" })],
        decalage: reads === 1 ? 0 : 1, suivant: reads === 1 ? 1 : null, reste: reads === 1 ? 1 : 0 });
    } });
    await h.control.charger();
    expect(h.control.etat().items.map(item => item.contenu_id)).toEqual(["contenu-1"]);
    await h.control.chargerSuite();
    expect(h.control.etat().items.map(item => item.contenu_id)).toEqual(["contenu-2"]);
  });
  test("une page courante peut revoir un identifiant dont la révision a changé", async () => {
    let reads = 0;
    const h = harness({ list: async () => {
      reads++;
      return directe({ ...liste(), total: 2, contenus: [ligne({ revision: reads })],
        decalage: reads === 1 ? 0 : 1, suivant: reads === 1 ? 1 : null, reste: reads === 1 ? 1 : 0 });
    } });
    await h.control.charger();
    await h.control.chargerSuite();
    expect(h.control.etat().statut).toBe("pret");
    expect(h.control.etat().items).toHaveLength(1);
    expect(h.control.etat().items[0].revision).toBe(2);
  });
  test("lire la liste DIRECTE n'autorise pas une décision transportée hors du COUPLE natif", async () => {
    const h = harness({ decide: async () => directe(decisionResult("contenu-1", "APPROVED")) });
    await h.control.charger();
    expect(h.control.etat().statut).toBe("pret");
    expect(await h.control.decider("contenu-1", "approuver")).toEqual({ ok: false, code: "decision_incertaine" });
    expect(h.control.peutDecider(ligne())).toBe(false);
    expect(h.calls.filter(tool => tool === "m7_decider_contenu")).toHaveLength(1);
  });
  test("affiche texte complet et n'autorise qu'un PROPOSE de marque courante du propriétaire", async () => {
    const { control } = harness();
    await control.charger();
    expect(control.etat().items[0].texte).toBe("Texte intégral");
    expect(control.peutDecider(control.etat().items[0])).toBe(true);
    expect(control.peutDecider(ligne({ fraicheur_marque: "perimee" }))).toBe(false);
    expect(control.peutDecider(ligne({ marque_source: { source: "brand_profiles", revision: 2, sha256: "b".repeat(64) } }))).toBe(false);
    expect(control.peutDecider(ligne({ approval_status: "APPROVED" }))).toBe(false);
  });
  test("refuse les enveloppes mal formées ou refusées et masque les décisions si le serveur nie owner", async () => {
    const malformed = harness({ list: async () => directe({ items: [{ texte: "partiel" }] }) });
    await malformed.control.charger();
    expect(malformed.control.etat().items).toEqual([]);
    const refusal = harness({ list: async () => ({ ok: true, resultat: { accepte: false, verdict: { code: "refuse", detail: "non" } } }) });
    await refusal.control.charger();
    expect(refusal.control.etat().owner).toBe(false);
    const nonOwner = harness({ owner: false });
    await nonOwner.control.charger();
    expect(nonOwner.control.etat().items).toHaveLength(1);
    expect(nonOwner.control.peutDecider(nonOwner.control.etat().items[0] ?? ligne())).toBe(false);
    // Remplace uniquement la réponse M9 par une enveloppe invalide et conserve la lecture M7.
    const helper = harness();
    const custom = creerControleMarketing({ ...helper.dependencies, appeler: async (tool) => tool === "m9_lister_demandes_approbation" ? acc({}) : directe(liste()) });
    custom.actualiserConnectivite(true); await custom.charger();
    expect(custom.etat().owner).toBe(false);
    expect(custom.etat().items).toHaveLength(1);
    const malformedEnum = harness({ list: async () => directe({ ...liste(), contenus: [ligne({ approval_status: ["PROPOSE"] as unknown as LigneContenuM7["approval_status"] })] }) });
    await malformedEnum.control.charger();
    expect(malformedEnum.control.etat().items).toEqual([]);
    const badPage = harness({ list: async () => directe({ ...liste(), suivant: 9 }) });
    await badPage.control.charger();
    expect(badPage.control.etat().items).toEqual([]);
  });
  test("offline n'envoie aucun appel et une mutation en vol ne peut pas être répétée", async () => {
    const offline = harness({ online: false });
    await offline.control.charger();
    expect(offline.calls).toEqual([]);
    let release!: (x: unknown) => void;
    const pending = harness({ decide: () => new Promise((resolve) => { release = resolve; }) });
    await pending.control.charger();
    const a = pending.control.decider("contenu-1", "approuver");
    await pending.attendreAppel("m7_decider_contenu");
    const b = await pending.control.decider("contenu-1", "approuver");
    expect(b.ok).toBe(false);
    release(acc({ contenu_id: "contenu-1", approval_status: "APPROVED" }));
    await a;
    expect(pending.calls.filter((x) => x === "m7_decider_contenu")).toHaveLength(1);
  });
  test("rejette les motifs invalides et exige une relecture après transport incertain, sans replay", async () => {
    const h = harness({ decide: async () => { throw new Error("timeout"); } });
    await h.control.charger();
    expect((await h.control.decider("contenu-1", "rejeter", "no")).ok).toBe(false);
    expect(h.calls.filter((x) => x === "m7_decider_contenu")).toHaveLength(0);
    await h.control.decider("contenu-1", "rejeter", "Motif suffisamment clair");
    expect(h.calls.filter((x) => x === "m7_decider_contenu")).toHaveLength(1);
    expect(h.calls.filter((x) => x === "m7_lister_contenus_chantier")).toHaveLength(2);
    expect(h.control.etat().statut).toBe("decision_incertaine");
    const request = h.details.find((x) => x.tool === "m7_decider_contenu")!;
    expect(request.args).toEqual({ contenu_id: "contenu-1", decision: "rejeter", horodatage: "2026-10-04T12:00:00+00:00", motif: "Motif suffisamment clair" });
    expect(request.mutation).toEqual({ idempotencyKey: "idem-1", deviceId: "app-a", deviceTimestamp: "2026-10-04T12:00:00+00:00" });
    expect(request.args).not.toHaveProperty("csrf");
  });
  test("une erreur de relecture après mutation incertaine verrouille toute nouvelle décision", async () => {
    let reads = 0;
    const h = harness({ decide: async () => { throw new Error("timeout"); }, list: async () => { reads++; if (reads > 1) throw new Error("offline"); return directe(liste()); } });
    await h.control.charger();
    await h.control.decider("contenu-1", "approuver");
    expect(h.control.etat().statut).toBe("relecture_impossible");
    expect(h.control.peutDecider(ligne())).toBe(false);
    expect(h.calls.filter((x) => x === "m7_decider_contenu")).toHaveLength(1);
  });
  test("un refus métier explicite reste distinct d'une réponse incertaine après relecture", async () => {
    const h = harness({ decide: async () => ({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-CONTENU-PERIME", detail: "détail serveur" } } }) });
    await h.control.charger();
    const result = await h.control.decider("contenu-1", "approuver");
    expect(result).toEqual({ ok: false, code: "refus_serveur_relue" });
    expect(h.control.etat().statut).toBe("pret");
    expect(h.control.etat().message).toBe("Décision refusée par le serveur; la liste a été relue.");
  });
  test("reset sur changement identité, blur et ignore les réponses périmées", async () => {
    let resolve!: (x: unknown) => void;
    const h = harness({ list: () => new Promise((r) => { resolve = r; }) });
    const loading = h.control.charger();
    await h.attendreAppel("m7_lister_contenus_chantier");
    h.changeSession({ ...session, jeton: "jeton-b", appareilId: "app-b", personne: "autre" });
    h.control.invalider();
    resolve(directe(liste()));
    await loading;
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.etat().statut).toBe("inactif");
    const badOwner = harness({ owner: false });
    await badOwner.control.charger();
    expect(badOwner.control.etat().owner).toBe(false);
  });
  test("un changement d’identité pendant la relecture ne réaffiche pas les données de l’ancienne session", async () => {
    let reads = 0;
    let resolveReadback!: (value: unknown) => void;
    const h = harness({
      decide: async () => { throw new Error("timeout"); },
      list: async () => {
        reads++;
        return reads === 1 ? directe(liste()) : new Promise((resolve) => { resolveReadback = resolve; });
      },
    });
    await h.control.charger();
    const decision = h.control.decider("contenu-1", "approuver");
    await h.attendreAppel("m7_lister_contenus_chantier", 2);
    h.changeSession({ ...session, jeton: "jeton-c", appareilId: "app-c", personne: "autre" });
    h.control.invalider();
    resolveReadback(directe(liste()));
    await decision;
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.etat().statut).toBe("inactif");
    expect(h.calls.filter((x) => x === "m7_decider_contenu")).toHaveLength(1);
  });
  test("changement de passerelle pendant une lecture invalide la réponse de l’ancienne URL", async () => {
    let resolve!: (value: unknown) => void;
    const h = harness({ list: () => new Promise((r) => { resolve = r; }) });
    const pending = h.control.charger();
    await h.attendreAppel("m7_lister_contenus_chantier");
    h.changeSession({ ...session, urlBase: "https://gateway-b" });
    resolve(directe(liste()));
    await pending;
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.etat().statut).toBe("inactif");
  });
  test("le changement de passerelle masque immédiatement l’ancien contenu et ses boutons", async () => {
    const h = harness();
    await h.control.charger();
    h.changeSession({ ...session, urlBase: "https://gateway-b" });
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.etat().statut).toBe("inactif");
    expect(h.control.peutDecider(ligne())).toBe(false);
  });
  test("la déconnexion pendant une lecture invalide la réponse en vol", async () => {
    let resolve!: (value: unknown) => void;
    const h = harness({ list: () => new Promise((r) => { resolve = r; }) });
    const pending = h.control.charger();
    await h.attendreAppel("m7_lister_contenus_chantier");
    h.control.actualiserConnectivite(false);
    resolve(directe(liste()));
    await pending;
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.etat().statut).toBe("hors_ligne");
  });
  test("succès approuvé et rejeté : la liste relue fait foi", async () => {
    for (const [decision, expected] of [["approuver", "APPROVED"], ["rejeter", "REJECTED"]] as const) {
      let currentStatus: LigneContenuM7["approval_status"] = "PROPOSE";
      const h = harness({
        list: async () => directe(liste([ligne({ approval_status: currentStatus })])),
        decide: async () => {
          currentStatus = expected;
          return acc(decisionResult("contenu-1", expected));
        },
      });
      await h.control.charger();
    const result = await h.control.decider("contenu-1", decision, "Motif suffisamment clair");
      expect(result.ok).toBe(true);
      expect(h.control.etat().items[0].approval_status).toBe(expected);
      expect(h.control.peutDecider(h.control.etat().items[0])).toBe(false);
      expect(h.calls.filter((tool) => tool === "m7_decider_contenu")).toHaveLength(1);
    }
  });
  test("le retrait du consentement visible à la relecture bloque le contenu", async () => {
    let currentStatus: LigneContenuM7["approval_status"] = "PROPOSE";
    const h = harness({
      list: async () => directe(liste([ligne({ approval_status: currentStatus })])),
      decide: async () => {
        currentStatus = "CONSENTEMENT_RETIRE";
        return acc(decisionResult("contenu-1", "APPROVED"));
      },
    });
    await h.control.charger();
    await h.control.decider("contenu-1", "approuver");
    expect(h.control.etat().items[0].approval_status).toBe("CONSENTEMENT_RETIRE");
    expect(h.control.peutDecider(h.control.etat().items[0])).toBe(false);
  });
  test("un motif invalide donne un retour explicite sans envoyer la mutation", async () => {
    const h = harness();
    await h.control.charger();
    expect(await h.control.decider("contenu-1", "rejeter", "  non ")).toEqual({ ok: false, code: "motif_invalide" });
    expect(h.control.etat().message).toBe("Le motif doit contenir entre 5 et 500 caractères.");
    expect(h.control.etat().codeMessage).toBe("motifInvalide");
    await h.control.charger();
    expect(h.control.etat().message).toBeNull();
    expect(h.control.etat().codeMessage).toBeNull();
    expect(h.calls.filter((tool) => tool === "m7_decider_contenu")).toHaveLength(0);
  });
  test("rechargement manuel reste bloqué pendant la mutation et sa relecture", async () => {
    let resolveDecision!: (value: unknown) => void;
    let resolveList!: (value: unknown) => void;
    let listCount = 0;
    const h = harness({
      list: async () => {
        listCount++;
        return listCount === 1 ? directe(liste()) : new Promise((resolve) => { resolveList = resolve; });
      },
      decide: () => new Promise((resolve) => { resolveDecision = resolve; }),
    });
    await h.control.charger();
    const first = h.control.decider("contenu-1", "approuver");
    await h.attendreAppel("m7_decider_contenu");
    const listCalls = h.calls.filter((tool) => tool === "m7_lister_contenus_chantier").length;
    await h.control.charger();
    await h.control.chargerSuite();
    expect(h.calls.filter((tool) => tool === "m7_lister_contenus_chantier")).toHaveLength(listCalls);
    expect(h.calls.filter((tool) => tool === "m7_decider_contenu")).toHaveLength(1);
    resolveDecision(acc(decisionResult("contenu-1", "APPROVED")));
    await h.attendreAppel("m7_lister_contenus_chantier", 2);
    expect(resolveList).toBeDefined();
    const secondDecision = await h.control.decider("contenu-1", "approuver");
    expect(secondDecision.ok).toBe(false);
    expect(h.calls.filter((tool) => tool === "m7_decider_contenu")).toHaveLength(1);
    resolveList(directe(liste([ligne({ approval_status: "APPROVED" })])));
    await first;
    expect(h.control.etat().items[0].approval_status).toBe("APPROVED");
  });
  test("pagination demande la page suivante exacte et remplace la page courante", async () => {
    let page = 0;
    const h = harness({ list: async () => {
      page++;
      const items = page === 1 ? Array.from({ length: 8 }, (_, i) => ligne({ contenu_id: `c-${i}`, wct_id: `wct-${i}` })) : [ligne({ contenu_id: "c-8", wct_id: "wct-8" })];
      const x = liste(items); return directe({ ...x, total: 9, decalage: page === 1 ? 0 : 8, suivant: page === 1 ? 8 : null, reste: page === 1 ? 1 : 0 });
    } });
    await h.control.charger();
    expect(h.control.etat().items).toHaveLength(8);
    await h.control.chargerSuite();
    expect(h.control.etat().items.map(item => item.contenu_id)).toEqual(["c-8"]);
    expect(h.details.filter((x) => x.tool === "m7_lister_contenus_chantier").map((x) => x.args)).toEqual([{ limite: 8, decalage: 0 }, { limite: 8, decalage: 8 }]);
  });
});
