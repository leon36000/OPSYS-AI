import { createHash } from "node:crypto";
import capturesNative from "./fixturesReapprovisionnementNative.json";
import { construireArgumentsReapprovisionnement, lireReapprovisionnement, OUTIL_REAPPROVISIONNEMENT } from "./reapprovisionnement";
import { estObjet } from "../admin/lecteurs";
import { ouvrirEnveloppe } from "../admin/enveloppe";
import { invoquerOutil } from "../protocole/client";
import { classerEchec } from "../protocole/echec";
import type { RequeteOutilsInvoke } from "../protocole/types";

// Les captures proviennent de Native r3 ; seul le transport fetch est rejoué ici.
// Aucun octet HTTP n'est prétendu reproduit par JSON.stringify, aucun serveur relancé.
interface Capture {
  readonly phase: string; readonly status: number;
  readonly request: RequeteOutilsInvoke & Record<string, unknown>;
  readonly response: unknown; readonly brut: Record<string, unknown>;
}
function estRequete(v: unknown): v is RequeteOutilsInvoke & Record<string, unknown> {
  return estObjet(v) && typeof v.tool === "string" && estObjet(v.args) &&
    ["action", "sessionKey", "agentId", "idempotencyKey", "deviceId", "deviceTimestamp"].every(k => v[k] === undefined || typeof v[k] === "string");
}
function charger(c: (typeof capturesNative.captures)[number]): Capture {
  const v: unknown = JSON.parse(c.capture_json_utf8);
  if (!estObjet(v) || v.phase !== c.phase || typeof v.phase !== "string" || typeof v.status !== "number" ||
    !estRequete(v.request) || !Object.hasOwn(v, "response")) throw new Error("Capture Native publique mal formée.");
  return { phase: v.phase, status: v.status, request: v.request, response: v.response, brut: v };
}
const captures = capturesNative.captures.map(charger);
const invalides = new Set(["limite9", "offset10001", "offsetnegatif", "auteur_arg_forge", "agent_arg_forge", "query_arg_forge"]);
function capture(phase: string): Capture {
  const c = captures.find(v => v.phase === phase);
  if (!c) throw new Error(`Capture Native absente : ${phase}`);
  return c;
}
function directe(c: Capture): Record<string, unknown> {
  if (!estObjet(c.response) || c.response.ok !== true || !estObjet(c.response.result)) throw new Error("DIRECTE Gateway200 attendue.");
  return c.response.result;
}
function args(c: Capture) {
  const a = c.request.args;
  if (invalides.has(c.phase) || c.request.tool !== OUTIL_REAPPROVISIONNEMENT || !a ||
    Object.keys(a).sort().join(",") !== "decalage,limite" || typeof a.decalage !== "number" || typeof a.limite !== "number") {
    throw new Error("Arguments classés hors contrat avant constructeur : aucun remplacement.");
  }
  const lu = construireArgumentsReapprovisionnement(a.decalage, a.limite);
  expect(lu).toEqual(a);
  return lu;
}
function donnees(phase: string) {
  const c = capture(phase), lu = lireReapprovisionnement(directe(c), args(c));
  if (!lu.ok) throw new Error(`Succès Native illisible : ${phase}/${lu.code}`);
  return lu.value;
}

describe("Réapprovisionnement M6 — consommation des 41 captures Native DEVICE", () => {
  test("39 DTO UTF8 exacts et deux projections distinctes conservent toute la campagne", () => {
    expect(capturesNative.fictif).toBe(true);
    expect(captures).toHaveLength(41); expect(new Set(captures.map(c => c.phase)).size).toBe(41);
    expect(capturesNative.provenance.native_manifest_sha256).toBe("d1424ca825738625126f603f16e5ac839dfaae7ad53dfa69ac57b78a98630296");
    expect(capturesNative.provenance.native_proof_sha256).toBe("e0ba1514d35addac374e6ee415932d40475f95cd6f5739e0a5de073c98b79493");
    expect(capturesNative.provenance.closure_sha256).toBe("58d2a078f73396cc282a868ee22b5c66eaef5bfc1ebc33ade5acf46cc72f4733");
    expect(capturesNative.captures.filter(c => c.source.kind === "dto_file_byte_copy")).toHaveLength(39);
    expect(capturesNative.captures.filter(c => c.source.kind === "native_proof_phase_projection").map(c => c.phase))
      .toEqual(["avant_decimal_cancellation", "avant_restart_body_entier"]);
    expect(captures.filter(c => c.status === 200)).toHaveLength(36);
    expect(captures.filter(c => c.status === 403)).toHaveLength(4);
    expect(captures.filter(c => c.status === 401)).toHaveLength(1);
    for (const c of capturesNative.captures) {
      expect(createHash("sha256").update(c.capture_json_utf8, "utf8").digest("hex")).toBe(c.utf8_sha256);
      expect(c.source.sha256).toBe(c.source.kind === "dto_file_byte_copy" ? c.utf8_sha256 : capturesNative.provenance.native_proof_sha256);
      const brut = charger(c).brut;
      expect(brut.all_entire_tables_unchanged).toBe(true);
      expect(brut.Gateway_HTTP_response_body_sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(charger(c).request.tool).toBe(OUTIL_REAPPROVISIONNEMENT);
    }
  });
  test.each(captures.map(c => [c.phase, c] as const))("%s : le vrai client puis le lecteur respectent réponse et arguments capturés", async (_phase, c) => {
    const fetchImpl = jest.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: c.status >= 200 && c.status < 300, status: c.status, json: async () => c.response,
    } as unknown as Response));
    const avant = JSON.stringify(c.response);
    const appel = await invoquerOutil({ fetchImpl, urlBase: "https://rejeu-fictif.invalid", jeton: "jeton-rejeu-fictif-non-native", requete: c.request });
    const init = fetchImpl.mock.calls[0][1];
    if (typeof init?.body !== "string") throw new Error("Corps envoyé absent.");
    expect(JSON.parse(init.body)).toEqual(c.request);
    expect(JSON.stringify(c.response)).toBe(avant);
    if (c.status !== 200) {
      expect(appel.ok).toBe(false);
      if (appel.ok) throw new Error("Un refus HTTP ne donne aucun DTO.");
      expect(appel.echec).toMatchObject({ origine: "http", status: c.status, reessayable: false });
      expect(classerEchec(appel.echec)).toBe("refuse"); expect(appel).not.toHaveProperty("result");
      if (!estObjet(c.response)) throw new Error("Corps HTTP capturé attendu.");
      if (c.status === 401) {
        expect(c.response).toEqual({ error: { message: "Unauthorized", type: "unauthorized" } });
        expect(c.response).not.toHaveProperty("ok"); expect(appel.echec.erreur).toBeUndefined();
        expect(appel.echec.message).toBe("réponse HTTP 401 inattendue");
      } else expect(appel.echec.erreur).toEqual(c.response.error);
      return;
    }
    const enveloppe = directe(c);
    expect(appel).toEqual({ ok: true, result: enveloppe });
    if (!appel.ok) throw new Error("HTTP200 capturé doit livrer le result exact.");
    if (invalides.has(c.phase)) {
      expect(() => args(c)).toThrow("classés hors contrat avant constructeur");
      expect(ouvrirEnveloppe(appel.result, "directe")).toMatchObject({ ok: false, genre: "refus" });
      expect(Reflect.apply(lireReapprovisionnement, undefined, [appel.result, c.request.args]))
        .toMatchObject({ ok: false, code: "reponse_illisible" });
      return;
    }
    const lu = lireReapprovisionnement(appel.result, args(c));
    const metier = enveloppe.resultat;
    if (estObjet(metier) && metier.accepte === false) {
      if (!estObjet(metier.verdict)) throw new Error("Verdict Native attendu.");
      expect(lu).toEqual({ ok: false, code: metier.verdict.code, detail: metier.verdict.detail });
      expect(lu).not.toHaveProperty("value");
    } else if (enveloppe.ok === false) {
      expect(lu).toEqual({ ok: false, code: enveloppe.erreur, detail: enveloppe.details });
      expect(lu).not.toHaveProperty("value");
    } else expect(lu).toEqual({ ok: true, value: metier });
  });
  test.each(["limite9", "offset10001", "offsetnegatif"])("%s : aucune valeur capturée réparée par les defaults", phase => {
    const a = capture(phase).request.args;
    if (!a) throw new Error("Arguments capturés attendus.");
    expect(() => Reflect.apply(construireArgumentsReapprovisionnement, undefined, [a.decalage, a.limite])).toThrow();
  });
  test("page réduite et suite conservent offsets, rangs, reste et remplacement natifs", () => {
    const premiere = donnees("page_courante_bornee5400"), suite = donnees("page_suivante_exacte");
    expect(premiere.pagination).toEqual({ decalage: 0, limite: 8, affichees: 4, total: 10, suivant: 4, reste: 6, courante: true });
    expect(suite.pagination).toEqual({ decalage: 4, limite: 8, affichees: 4, total: 10, suivant: 8, reste: 2, courante: true });
    expect(premiere.taille_caracteres).toBe(4639);
    expect(suite.articles.some(a => premiere.articles.some(b => b.materiau_id === a.materiau_id))).toBe(false);
    expect(donnees("page_remplacement_courante").pagination.total).toBe(11);
    expect(donnees("decalage_hors_total_legal").pagination).toEqual({ decalage: 10000, limite: 8, affichees: 0, total: 11, suivant: null, reste: 0, courante: true });
  });
  test("paramètres exacts, sources inconnues et métadonnées internes ne deviennent pas inventaire physique", () => {
    const grand = donnees("parametres_entiers_grands_textes_exacts").articles[0];
    expect(grand.seuil_reapprovisionnement).toBe("9007199254740992"); expect(grand.quantite_cible).toBe("9007199254740993");
    expect(grand.quantite_a_commander).toBe("9007199254740749");
    expect(donnees("grand_decimal_cancellation_exacte").articles[0].chiffres)
      .toEqual(donnees("avant_decimal_cancellation").articles[0].chiffres);
    const legacy = donnees("emplacements_courants_metadata_legacy").articles[0];
    expect(legacy.chiffres.hors_main).toBe("20"); expect(legacy.chiffres.reserve).toBe("20");
    expect(legacy.unite).toBeNull(); expect(legacy.dernier_constat.horodatage).toBe("2026-10-09T15:04:30+00:00");
    expect(donnees("seuil_absent_distinct").articles[0]).toMatchObject({ statut: "seuil_absent", quantite_a_commander: null });
    expect(donnees("configuration_invalide_lisible").articles[0]).toMatchObject({ statut: "configuration_invalide", quantite_a_commander: null });
  });
  test("reprise entière et contrôle final gardent corps, source et empreinte sans données substituées", () => {
    const avant = capture("avant_restart_body_entier"), apres = capture("apres_restart_body_entier_identique");
    expect(apres.request).toEqual(avant.request); expect(apres.response).toEqual(avant.response);
    expect(apres.brut.Gateway_HTTP_response_body_sha256).toBe(avant.brut.Gateway_HTTP_response_body_sha256);
    expect(capture("agentId_body_forge_identique").response).toEqual(capture("constat_pipeline_reel_stock_bas").response);
    // Le contrôle final relit la page courante après les préparations de catalogue ;
    // le monde initial d'un seul article n'est jamais substitué à cette lecture.
    expect(capture("finale_relecture_ordinaire_identique").response).toEqual(apres.response);
    expect(capture("finale_relecture_ordinaire_identique").brut.Gateway_HTTP_response_body_sha256)
      .toBe(apres.brut.Gateway_HTTP_response_body_sha256);
  });
});
