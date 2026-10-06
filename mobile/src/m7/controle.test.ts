import { creerControleMarketing } from "./controle";
import type { AppelM7, LigneContenuM7, SessionM7 } from "./contrat";

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

function harness(options: { owner?: boolean; list?: () => Promise<unknown>; decide?: () => Promise<unknown>; online?: boolean; session?: () => SessionM7 | null } = {}) {
  let current = options.session ?? (() => session);
  const calls: string[] = [];
  const details: Array<{ tool: string; args?: Record<string, unknown>; mutation?: { idempotencyKey: string; deviceId: string; deviceTimestamp: string } }> = [];
  const appeler: AppelM7 = async (tool, args, mutation) => {
    calls.push(tool);
    details.push({ tool, args, mutation });
    if (tool === "m9_lister_demandes_approbation") return acc(ownerResult(options.owner ?? true));
    if (tool === "m7_lister_contenus_chantier") return options.list ? options.list() : acc(liste());
    return options.decide ? options.decide() : acc(decisionResult("contenu-1", "APPROVED"));
  };
  const control = creerControleMarketing({
    obtenirSession: () => current(), enLigne: () => options.online ?? true, appeler,
    maintenant: () => "2026-10-04T12:00:00.000Z", genererId: () => "idem-1",
  });
  control.actualiserConnectivite(options.online ?? true);
  return { control, calls, details, changeSession: (s: SessionM7 | null) => { current = () => s; } };
}

describe("contrôleur M7 mobile", () => {
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
    const malformed = harness({ list: async () => acc({ items: [{ texte: "partiel" }] }) });
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
    const custom = creerControleMarketing({ obtenirSession: () => session, enLigne: () => true, maintenant: () => "t", genererId: () => "id", appeler: async (tool) => tool === "m9_lister_demandes_approbation" ? acc({}) : acc(liste()) });
    custom.actualiserConnectivite(true); await custom.charger();
    expect(custom.etat().owner).toBe(false);
    expect(custom.etat().items).toHaveLength(1);
    const malformedEnum = harness({ list: async () => acc({ ...liste(), contenus: [ligne({ approval_status: ["PROPOSE"] as unknown as LigneContenuM7["approval_status"] })] }) });
    await malformedEnum.control.charger();
    expect(malformedEnum.control.etat().items).toEqual([]);
    const badPage = harness({ list: async () => acc({ ...liste(), suivant: 9 }) });
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
    await Promise.resolve(); await Promise.resolve();
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
    expect(request.args).toEqual({ contenu_id: "contenu-1", decision: "rejeter", horodatage: "2026-10-04T12:00:00.000Z", motif: "Motif suffisamment clair" });
    expect(request.mutation).toEqual({ idempotencyKey: "idem-1", deviceId: "app-a", deviceTimestamp: "2026-10-04T12:00:00.000Z" });
    expect(request.args).not.toHaveProperty("csrf");
  });
  test("une erreur de relecture après mutation incertaine verrouille toute nouvelle décision", async () => {
    let reads = 0;
    const h = harness({ decide: async () => { throw new Error("timeout"); }, list: async () => { reads++; if (reads > 1) throw new Error("offline"); return acc(liste()); } });
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
    await Promise.resolve(); await Promise.resolve();
    h.changeSession({ ...session, jeton: "jeton-b", appareilId: "app-b", personne: "autre" });
    h.control.invalider();
    resolve(acc(liste()));
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
        return reads === 1 ? acc(liste()) : new Promise((resolve) => { resolveReadback = resolve; });
      },
    });
    await h.control.charger();
    const decision = h.control.decider("contenu-1", "approuver");
    for (let i = 0; i < 5; i++) await Promise.resolve();
    h.changeSession({ ...session, jeton: "jeton-c", appareilId: "app-c", personne: "autre" });
    h.control.invalider();
    resolveReadback(acc(liste()));
    await decision;
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.etat().statut).toBe("inactif");
    expect(h.calls.filter((x) => x === "m7_decider_contenu")).toHaveLength(1);
  });
  test("changement de passerelle pendant une lecture invalide la réponse de l’ancienne URL", async () => {
    let resolve!: (value: unknown) => void;
    const h = harness({ list: () => new Promise((r) => { resolve = r; }) });
    const pending = h.control.charger();
    for (let i = 0; i < 3; i++) await Promise.resolve();
    h.changeSession({ ...session, urlBase: "https://gateway-b" });
    resolve(acc(liste()));
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
    for (let i = 0; i < 3; i++) await Promise.resolve();
    h.control.actualiserConnectivite(false);
    resolve(acc(liste()));
    await pending;
    expect(h.control.etat().items).toEqual([]);
    expect(h.control.etat().statut).toBe("hors_ligne");
  });
  test("succès approuvé et rejeté : la liste relue fait foi", async () => {
    for (const [decision, expected] of [["approuver", "APPROVED"], ["rejeter", "REJECTED"]] as const) {
      let currentStatus: LigneContenuM7["approval_status"] = "PROPOSE";
      const h = harness({
        list: async () => acc(liste([ligne({ approval_status: currentStatus })])),
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
      list: async () => acc(liste([ligne({ approval_status: currentStatus })])),
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
    expect(h.control.etat().message).toContain("5 et 500");
    expect(h.calls.filter((tool) => tool === "m7_decider_contenu")).toHaveLength(0);
  });
  test("rechargement manuel reste bloqué pendant la mutation et sa relecture", async () => {
    let resolveDecision!: (value: unknown) => void;
    let resolveList!: (value: unknown) => void;
    let listCount = 0;
    const h = harness({
      list: async () => {
        listCount++;
        return listCount === 1 ? acc(liste()) : new Promise((resolve) => { resolveList = resolve; });
      },
      decide: () => new Promise((resolve) => { resolveDecision = resolve; }),
    });
    await h.control.charger();
    const first = h.control.decider("contenu-1", "approuver");
    for (let i = 0; i < 3; i++) await Promise.resolve();
    const listCalls = h.calls.filter((tool) => tool === "m7_lister_contenus_chantier").length;
    await h.control.charger();
    await h.control.chargerSuite();
    expect(h.calls.filter((tool) => tool === "m7_lister_contenus_chantier")).toHaveLength(listCalls);
    expect(h.calls.filter((tool) => tool === "m7_decider_contenu")).toHaveLength(1);
    resolveDecision(acc(decisionResult("contenu-1", "APPROVED")));
    for (let i = 0; i < 20 && !resolveList; i++) await Promise.resolve();
    expect(resolveList).toBeDefined();
    const secondDecision = await h.control.decider("contenu-1", "approuver");
    expect(secondDecision.ok).toBe(false);
    expect(h.calls.filter((tool) => tool === "m7_decider_contenu")).toHaveLength(1);
    resolveList(acc(liste([ligne({ approval_status: "APPROVED" })])));
    await first;
    expect(h.control.etat().items[0].approval_status).toBe("APPROVED");
  });
  test("pagination demande la page suivante exacte et cumule au plus huit lignes par lecture", async () => {
    let page = 0;
    const h = harness({ list: async () => {
      page++;
      const items = page === 1 ? Array.from({ length: 8 }, (_, i) => ligne({ contenu_id: `c-${i}` })) : [ligne({ contenu_id: "c-8" })];
      const x = liste(items); return acc({ ...x, total: 9, decalage: page === 1 ? 0 : 8, suivant: page === 1 ? 8 : null, reste: page === 1 ? 1 : 0 });
    } });
    await h.control.charger();
    expect(h.control.etat().items).toHaveLength(8);
    await h.control.chargerSuite();
    expect(h.control.etat().items).toHaveLength(9);
    expect(h.details.filter((x) => x.tool === "m7_lister_contenus_chantier").map((x) => x.args)).toEqual([{ limite: 8, decalage: 0 }, { limite: 8, decalage: 8 }]);
  });
});
