import { createHash } from "node:crypto";
import capturesNative from "./fixturesPertesAlertesNative.json";
import {
  construireArgumentsListeWct, construireArgumentsPertesWct, lireListeWctPertes, lirePertesAlertesWct,
  OUTIL_LISTE_WCT_PERTES, OUTIL_PERTES_ALERTES_WCT,
} from "./pertesAlertes";
import { estObjet } from "../admin/lecteurs";
import { ouvrirEnveloppe } from "../admin/enveloppe";
import { invoquerOutil } from "../protocole/client";
import { classerEchec } from "../protocole/echec";
import type { RequeteOutilsInvoke } from "../protocole/types";

// Source Native r4 réelle, mais transport de ces tests exclusivement rejoué localement.
// Les textes DTO restent byte-identiques ; aucune normalisation de response ou request.
interface Capture {
  readonly phase: string; readonly status: number; readonly request: RequeteOutilsInvoke & Record<string, unknown>;
  readonly response: unknown; readonly brut: Record<string, unknown>;
}
function estRequete(v: unknown): v is RequeteOutilsInvoke & Record<string, unknown> {
  return estObjet(v) && typeof v.tool === "string" && estObjet(v.args) &&
    ["action", "sessionKey", "agentId", "idempotencyKey", "deviceId", "deviceTimestamp"].every(k => v[k] === undefined || typeof v[k] === "string");
}
function charger(c: (typeof capturesNative.captures)[number]): Capture {
  const v: unknown = JSON.parse(c.capture_json_utf8);
  if (!estObjet(v) || v.phase !== c.phase || typeof v.phase !== "string" ||
    typeof v.status !== "number" || !estRequete(v.request) || !Object.hasOwn(v, "response")) {
    throw new Error("Capture Native publique mal formée.");
  }
  return { phase: v.phase, status: v.status, request: v.request, response: v.response, brut: v };
}
const captures = capturesNative.captures.map(charger);
const invalides = new Set(["limite9", "offset10001", "offsetnegatif", "auteur_arg_forge", "agent_arg_forge", "wct_absent", "wct_null"]);
function capture(phase: string): Capture {
  const c = captures.find(v => v.phase === phase);
  if (!c) throw new Error(`Capture Native absente : ${phase}`);
  return c;
}
function directe(c: Capture): Record<string, unknown> {
  if (!estObjet(c.response) || c.response.ok !== true || !estObjet(c.response.result)) {
    throw new Error("Cette capture ne contient pas une DIRECTE Gateway200.");
  }
  return c.response.result;
}
function argsListe(c: Capture) {
  const a = c.request.args;
  if (!a || c.request.tool !== OUTIL_LISTE_WCT_PERTES || Object.keys(a).sort().join(",") !== "decalage,limite" ||
    typeof a.decalage !== "number" || typeof a.limite !== "number") throw new Error("Arguments liste hors contrat.");
  const args = construireArgumentsListeWct(a.decalage, a.limite);
  expect(args).toEqual(a);
  return args;
}
function argsDetail(c: Capture) {
  const a = c.request.args;
  if (invalides.has(c.phase) || !a || c.request.tool !== OUTIL_PERTES_ALERTES_WCT ||
    Object.keys(a).sort().join(",") !== "decalage,limite,wct_id" || typeof a.wct_id !== "string" ||
    typeof a.decalage !== "number" || typeof a.limite !== "number") {
    throw new Error("Arguments détail classés hors contrat avant constructeur : aucun remplacement.");
  }
  const args = construireArgumentsPertesWct(a.wct_id, a.decalage, a.limite);
  expect(args).toEqual(a);
  return args;
}
function detail(phase: string) {
  const c = capture(phase), lu = lirePertesAlertesWct(directe(c), argsDetail(c));
  if (!lu.ok) throw new Error(`Succès Native détail illisible : ${phase}/${lu.code}`);
  return lu.value;
}
function liste(phase: string) {
  const c = capture(phase), lu = lireListeWctPertes(directe(c), argsListe(c));
  if (!lu.ok) throw new Error(`Succès Native liste illisible : ${phase}/${lu.code}`);
  return lu.value;
}

describe("M6 pertes/alertes — jonction des 46 captures HTTP Native DEVICE", () => {
  test("44 DTO byte-identiques et deux projections de preuve, sans confondre manifeste/archive", () => {
    expect(capturesNative.fictif).toBe(true);
    expect(capturesNative.provenance.native_manifest_sha256).toBe("d15bd3c96cd83f962150eef0cf3ca6ed76b1053b79b9c42b28d05f292ae085e0");
    expect(capturesNative.provenance.closure_sha256).toBe("891362aa6b05042203e836f334b40714c9156a130676d6f64501c2986f0853fa");
    expect(capturesNative.provenance.contract_sha256).toBe("46d4f420b698ce1ec11176c850b8487736fabcf3c53f764c7cb5beb7200be40b");
    expect(capturesNative.provenance.producer_sha256).toBe("91542acd18213c08eefaa3a815b3d8475c08672872a3f0c0c7b07f9e3cb939e4");
    expect(captures).toHaveLength(46);
    expect(new Set(captures.map(c => c.phase)).size).toBe(46);
    expect(capturesNative.captures.filter(c => c.source.kind === "dto_file_byte_copy")).toHaveLength(44);
    expect(capturesNative.captures.filter(c => c.source.kind === "native_proof_phase_projection").map(c => c.phase)).toEqual(["avant_restart_detail", "avant_restart_liste"]);
    expect(captures.filter(c => c.status === 200)).toHaveLength(39);
    expect(captures.filter(c => c.status === 403)).toHaveLength(6);
    expect(captures.filter(c => c.status === 401)).toHaveLength(1);
    for (const c of capturesNative.captures) {
      expect(createHash("sha256").update(c.capture_json_utf8, "utf8").digest("hex")).toBe(c.utf8_sha256);
      if (c.source.kind === "dto_file_byte_copy") expect(c.utf8_sha256).toBe(c.source.sha256);
      else expect(c.source.sha256).toBe(capturesNative.provenance.native_proof_sha256);
      const brut = charger(c).brut;
      expect(brut.all_entire_tables_unchanged).toBe(true);
      expect(brut.Gateway_HTTP_response_body_sha256).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  test.each(captures.map(c => [c.phase, c] as const))("%s : vrai client et lecteur, réponse source intacte", async (_phase, c) => {
    // Même seam Response minimale que les tests du client : json() fournit le corps parsé
    // exact. On ne prétend pas reproduire les octets HTTP par re-sérialisation.
    const fetchImpl = jest.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: c.status >= 200 && c.status < 300, status: c.status, json: async () => c.response,
    } as unknown as Response));
    const avant = JSON.stringify(c.response);
    const appel = await invoquerOutil({ fetchImpl, urlBase: "https://rejeu-fictif.invalid", jeton: "jeton-rejeu-fictif-non-native", requete: c.request });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const init = fetchImpl.mock.calls[0][1];
    if (typeof init?.body !== "string") throw new Error("Corps HTTP absent.");
    expect(JSON.parse(init.body)).toEqual(c.request);
    expect(JSON.stringify(c.response)).toBe(avant);
    if (c.status !== 200) {
      expect(appel.ok).toBe(false);
      if (appel.ok) throw new Error("Un refus HTTP ne livre aucun DTO.");
      expect(appel.echec).toMatchObject({ origine: "http", status: c.status, reessayable: false });
      expect(classerEchec(appel.echec)).toBe("refuse");
      expect(appel).not.toHaveProperty("result");
      if (!estObjet(c.response)) throw new Error("Corps HTTP capturé attendu.");
      if (c.status === 401) {
        expect(c.response).toEqual({ error: { message: "Unauthorized", type: "unauthorized" } });
        expect(c.response).not.toHaveProperty("ok");
        // Le vrai client exige ok:false pour reconnaître une erreur structurée.
        // Le statut401 suffit au refus ; aucun ok/code natif n'est inventé.
        expect(appel.echec.erreur).toBeUndefined();
        expect(appel.echec.message).toBe("réponse HTTP 401 inattendue");
      } else {
        expect(appel.echec.erreur).toEqual(c.response.error);
      }
      return;
    }
    const enveloppe = directe(c);
    expect(appel).toEqual({ ok: true, result: enveloppe });
    if (!appel.ok) throw new Error("HTTP 200 capturé doit livrer son result exact.");
    if (invalides.has(c.phase)) {
      expect(() => argsDetail(c)).toThrow("classés hors contrat avant constructeur");
      expect(Reflect.apply(lirePertesAlertesWct, undefined, [appel.result, c.request.args])).toMatchObject({ ok: false, code: "reponse_illisible" });
      return;
    }
    if (c.request.tool === "m6_evaluer_variance_chantier") {
      // Contrôle du legacy hors interface des deux nouveaux lecteurs : aucune fabrication
      // de contexte WCT. Son refus réel est ouvert par le helper DIRECT commun.
      const refuse = ouvrirEnveloppe(appel.result, "directe");
      expect(refuse).toMatchObject({ ok: false, genre: "refus", verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE" } });
      expect(refuse).not.toHaveProperty("valeur");
      if (!estObjet(enveloppe.resultat)) throw new Error("Refus legacy attendu.");
      expect(refuse.ok ? null : refuse.verdict).toEqual(enveloppe.resultat.verdict);
      return;
    }
    const lu = c.request.tool === OUTIL_LISTE_WCT_PERTES
      ? lireListeWctPertes(appel.result, argsListe(c))
      : lirePertesAlertesWct(appel.result, argsDetail(c));
    const resultat = enveloppe.resultat;
    if (estObjet(resultat) && resultat.accepte === false) {
      if (!estObjet(resultat.verdict)) throw new Error("Verdict natif attendu.");
      expect(lu).toEqual({ ok: false, code: resultat.verdict.code, detail: resultat.verdict.detail });
      expect(lu).not.toHaveProperty("value");
    } else if (enveloppe.ok === false) {
      expect(lu).toEqual({ ok: false, code: enveloppe.erreur, detail: enveloppe.details });
      expect(lu).not.toHaveProperty("value");
    } else {
      expect(lu).toEqual({ ok: true, value: resultat });
    }
  });

  test.each(["limite9", "offset10001", "offsetnegatif", "wct_absent", "wct_null"])("%s : constructeur refuse la valeur capturée sans réparation", phase => {
    const a = capture(phase).request.args;
    if (!a) throw new Error("Arguments capturés attendus.");
    expect(() => Reflect.apply(construireArgumentsPertesWct, undefined, [a.wct_id, a.decalage, a.limite])).toThrow();
  });
  test("pages de pertes remplacées, index source et quantités signées conservés", () => {
    const p = detail("page_perte_premiere"), s = detail("page_bris_suivante");
    expect(p.pagination).toEqual({ decalage: 0, limite: 1, affichees: 1, total: 2, suivant: 1, reste: 1, courante: true });
    expect(s.pagination).toEqual({ decalage: 1, limite: 1, affichees: 1, total: 2, suivant: null, reste: 0, courante: true });
    expect(p.pertes_bris).toHaveLength(1); expect(s.pertes_bris).toHaveLength(1);
    expect(p.pertes_bris[0].type_mouvement).toBe("PERTE"); expect(s.pertes_bris[0].type_mouvement).toBe("BRIS");
    expect(s.pertes_bris[0].reference.index).toBeGreaterThan(p.pertes_bris[0].reference.index);
    for (const m of [...p.pertes_bris, ...s.pertes_bris]) {
      expect(m.quantite_signee.startsWith("-")).toBe(true); expect(m.unite).toBeNull(); expect(m.horodatage).toBeNull();
    }
  });
  test("page budget réduite et son curseur natif ; offset hors total vide légal", () => {
    const p = detail("volume_page_reduite_catalogue_distinct"), s = detail("volume_suivante_curseur_exact");
    expect(p.pagination).toEqual({ decalage: 0, limite: 8, affichees: 7, total: 8, suivant: 7, reste: 1, courante: true });
    expect(p.taille_caracteres).toBe(5043); expect(p.borne_caracteres).toBe(5400);
    expect(s.pagination).toEqual({ decalage: 7, limite: 8, affichees: 1, total: 8, suivant: null, reste: 0, courante: true });
    expect(s.taille_caracteres).toBe(1828);
    expect(detail("offset_hors_total_legal").pagination).toEqual({ decalage: 10000, limite: 8, affichees: 0, total: 2, suivant: null, reste: 0, courante: true });
  });
  test("liste courante remplacée après préparation : total15 natif sans snapshot inventé", () => {
    const p = liste("liste_page_courante_premiere"), s = liste("liste_page_courante_suivante"), nouvelle = liste("liste_remplacement_page_courante_apres_preparation");
    expect(p.pagination.total).toBe(14); expect(s.pagination.decalage).toBe(1);
    expect(nouvelle.pagination).toEqual({ decalage: 0, limite: 1, affichees: 1, total: 15, suivant: 1, reste: 14, courante: true });
    expect(nouvelle.wcts).toHaveLength(1);
    expect(nouvelle.wcts[0].reference_recu.rang).toBeGreaterThan(p.wcts[0].reference_recu.rang);
  });
  test("absence, historique fixe, WCT long et FEFF : aucun contexte corrigé", () => {
    const absent = detail("declaration_absente_pipeline");
    expect(absent.declaration_presente).toBe(false); expect(absent.pertes_bris).toEqual([]);
    const historique = detail("historique_quatre_slots_catalogue_distinct");
    expect(historique.historique_variance.map(s => s.statut)).toEqual(["seuil_absent", "prevu_absent", "declaration_absente", "evaluee"]);
    expect(historique.historique_variance.every(s => s.presente)).toBe(true);
    expect(historique.evaluee_terminal).toBe(true);
    const long = detail("wct256_reference300_catalogue_distinct");
    expect(Array.from(long.wct.wct_id)).toHaveLength(256);
    const evaluee = long.historique_variance[3];
    expect(evaluee.presente).toBe(true);
    if (!evaluee.presente) throw new Error("Évaluation Native longue attendue.");
    expect(evaluee.publication.reference_bus.evenement_id).toBe(`m6-variance-${long.wct.wct_id}-evaluee`);
    expect(Array.from(evaluee.publication.reference_bus.evenement_id).length).toBeGreaterThan(256);
    expect(detail("id_FEFF_verbatim_catalogue_distinct").wct.wct_id).toBe("\ufeff");
  });
  test("reprise et dernier contrôle exacts ; corps forgé agent/rôle/auteur sans effet", () => {
    for (const [avant, apres] of [["avant_restart_detail", "relecture_detail_exacte_apres_restart"], ["avant_restart_liste", "relecture_liste_exacte_apres_restart"]]) {
      expect(capture(apres).request).toEqual(capture(avant).request);
      expect(capture(apres).response).toEqual(capture(avant).response);
      expect(capture(apres).brut.Gateway_HTTP_response_body_sha256).toBe(capture(avant).brut.Gateway_HTTP_response_body_sha256);
    }
    expect(capture("agentId_body_forge_identique").response).toEqual(capture("declaration_absente_pipeline").response);
    expect(capture("derniere_relecture_ordinaire_identique").response).toEqual(capture("perte_bris_pipeline_writer_reel").response);
  });
});
