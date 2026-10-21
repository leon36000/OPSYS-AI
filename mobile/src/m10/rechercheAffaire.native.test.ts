import { createHash } from "node:crypto";
import capturesNative from "./fixturesRechercheAffaireNative.json";
import {
  construireArgumentsRechercheAffaire, lireRechercheAffaire,
  type ArgumentsRechercheAffaireM10,
} from "./rechercheAffaire";
import { estObjet } from "../admin/lecteurs";
import { invoquerOutil } from "../protocole/client";
import { classerEchec, verdictDepuisEchec } from "../protocole/echec";

// Captures réelles publiques ; seuls le transport fetch et son jeton sont simulés ici.
// Aucun accès au serveur, aux registres, au dépôt mobile ou au téléphone.
const captures = capturesNative.captures;
type Capture = (typeof captures)[number];
const horsContrat = new Set([
  "agent_arg_forge", "auteur_arg_forge", "role_arg_forge", "budget_arg_forge",
  "limite9", "offsetnegatif", "offset10001", "query201", "affaireinvalide",
]);
const refusMetier = new Map([
  ["admin_retire_avant_2registres", "REJ-IDENTITE-APPAREIL-INVALIDE"],
  ["corruption_snapshot_refus_catalogue_distinct", "REJ-RECHERCHE-AFFAIRE-REGISTRE-INVALIDE"],
]);
function capture(phase: string): Capture {
  const c = captures.find(v => v.capture.phase === phase);
  if (!c) throw new Error(`Capture native absente : ${phase}`);
  return c;
}
function enveloppe(c: Capture): Record<string, unknown> {
  const outer: unknown = c.capture.response;
  if (!estObjet(outer) || outer.ok !== true || !estObjet(outer.result)) {
    throw new Error("Cette capture n'est pas une enveloppe DIRECTE HTTP 200.");
  }
  return outer.result;
}
function argumentsNatifs(c: Capture): ArgumentsRechercheAffaireM10 {
  const a: Record<string, unknown> = c.capture.request.args;
  if (horsContrat.has(c.capture.phase) || c.capture.request.tool !== "m10_rechercher_affaire_appareil" ||
    Object.keys(a).sort().join(",") !== "affaire_id,decalage,limite,requete" ||
    typeof a.affaire_id !== "string" || typeof a.requete !== "string" ||
    typeof a.decalage !== "number" || typeof a.limite !== "number") {
    throw new Error("Capture classée hors contrat avant construction : aucune réparation.");
  }
  const args = construireArgumentsRechercheAffaire(a.affaire_id, a.requete, a.decalage, a.limite);
  expect(args).toEqual(a);
  return args;
}
function lire(phase: string) {
  const c = capture(phase);
  const lu = lireRechercheAffaire(enveloppe(c), argumentsNatifs(c));
  if (!lu.ok) throw new Error(`Succès natif illisible : ${phase}/${lu.code}`);
  return lu.value;
}

describe("M10 recherche — jonction des 31 captures DEVICE natives", () => {
  test("provenance et projection publique scellées, distinctes d'une nouvelle exécution HTTP", () => {
    expect(capturesNative.fictif).toBe(true);
    expect(capturesNative.provenance.closure_sha256).toBe("75d35e31f3abbf06df5c9e129e35d7a99568150e8741985d15a2e9e4dbde94c5");
    expect(capturesNative.provenance.public_manifest_sha256).toBe("8c543ba65dba01f9c63645f71a60c0a1939953e6ca0b4d6927fa9934e9912d5e");
    expect(capturesNative.provenance.producer_sha256).toBe("38d09cc2a5c899d56b35a75b30b0fff85f5e805f768b9521eb7b2bc6c05a0117");
    expect(capturesNative.provenance.all_source_manifest_sha256).toBe("31e9456fbcdc27d64d4ee92031dd2a1257fc14ba53f680690bc45c4cfac96b7a");
    expect(captures).toHaveLength(31);
    expect(new Set(captures.map(c => c.capture.phase)).size).toBe(31);
    expect(captures.filter(c => c.source.path.endsWith("native-proof.json")).map(c => c.capture.phase)).toEqual(["avant_restart_exact"]);
    for (const c of captures) {
      expect(c.source.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(c.capture.Gateway_HTTP_response_body_sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(c.capture.all_entire_tables_unchanged).toBe(true);
      expect(createHash("sha256").update(JSON.stringify(c.capture), "utf8").digest("hex")).toBe(c.source.projection_sha256);
    }
  });

  test.each(captures.map(c => [c.capture.phase, c] as const))("%s : vrai client, corps et statut capturés", async (_phase, c) => {
    // Response minimal conforme au seam déjà employé dans client.test.ts : json() restitue
    // exactement le corps parsé. Pas de revendication sur sa sérialisation/les octets réseau.
    const fetchImpl = jest.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: c.capture.status >= 200 && c.capture.status < 300,
      status: c.capture.status,
      json: async () => c.capture.response,
    } as unknown as Response));
    const appel = await invoquerOutil({
      fetchImpl, urlBase: "https://gateway.fictif.invalid", jeton: "jeton-de-rejeu-fictif",
      requete: c.capture.request,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const init = fetchImpl.mock.calls[0][1];
    expect(init?.method).toBe("POST");
    if (typeof init?.body !== "string") throw new Error("Corps de requête absent.");
    expect(JSON.parse(init.body)).toEqual(c.capture.request);
    if (c.capture.status !== 200) {
      expect(appel.ok).toBe(false);
      if (appel.ok) throw new Error("Un refus HTTP ne doit pas livrer un DTO.");
      expect(appel.echec.status).toBe(c.capture.status);
      expect(appel.echec.origine).toBe("http");
      expect(appel.echec.reessayable).toBe(false);
      expect(classerEchec(appel.echec)).toBe("refuse");
      const response: unknown = c.capture.response;
      if (!estObjet(response) || !estObjet(response.error)) throw new Error("Refus Gateway structuré absent.");
      expect(verdictDepuisEchec(appel.echec)).toEqual({ code: response.error.type, detail: response.error.message });
      expect(appel).not.toHaveProperty("result");
      return;
    }
    expect(appel).toEqual({ ok: true, result: enveloppe(c) });
    if (!appel.ok) throw new Error("HTTP 200 natif perdu par le client.");
    if (horsContrat.has(c.capture.phase)) {
      expect(() => argumentsNatifs(c)).toThrow("classée hors contrat avant construction");
      // Les valeurs hors contrat restent intactes ; le lecteur ne les transforme pas en
      // arguments valides, même si l'enveloppe porte un refus métier lisible.
      expect(Reflect.apply(lireRechercheAffaire, undefined, [appel.result, c.capture.request.args])).toMatchObject({ ok: false, code: "reponse_illisible" });
      return;
    }
    const lu = lireRechercheAffaire(appel.result, argumentsNatifs(c));
    const code = refusMetier.get(c.capture.phase);
    if (code) {
      const e = enveloppe(c);
      if (!estObjet(e.resultat) || !estObjet(e.resultat.verdict)) throw new Error("Verdict métier natif absent.");
      expect(e.resultat.accepte).toBe(false);
      expect(lu).toEqual({ ok: false, code, detail: e.resultat.verdict.detail });
      expect(lu).not.toHaveProperty("value");
    } else {
      expect(lu).toEqual({ ok: true, value: enveloppe(c).resultat });
    }
  });

  test.each(["limite9", "offsetnegatif", "offset10001", "query201", "affaireinvalide"])("%s : constructeur refuse les valeurs capturées, sans correction", phase => {
    const a: Record<string, unknown> = capture(phase).capture.request.args;
    expect(() => Reflect.apply(construireArgumentsRechercheAffaire, undefined, [a.affaire_id, a.requete, a.decalage, a.limite])).toThrow("Arguments de recherche d'affaire invalides.");
  });

  test("pages courantes et page réduite : compteurs et tailles natifs conservés", () => {
    const p = lire("page_courante_premiere"), s = lire("page_courante_suivante");
    expect(p.pagination).toEqual({ decalage: 0, limite: 2, affichees: 2, total: 14, suivant: 2, reste: 12, courante: true });
    expect(s.pagination).toEqual({ decalage: 2, limite: 2, affichees: 2, total: 14, suivant: 4, reste: 10, courante: true });
    expect(s.resultats).toHaveLength(2);
    expect(s.resultats.some(l => p.resultats.some(a => a.reference.ligne_id === l.reference.ligne_id))).toBe(false);
    const borne = lire("projection_volume_page_reduite_catalogue_distinct");
    expect(borne.pagination).toEqual({ decalage: 0, limite: 8, affichees: 6, total: 8, suivant: 6, reste: 2, courante: true });
    expect(borne.taille_caracteres).toBe(5016);
    expect(borne.borne_caracteres).toBe(5400);
    expect(lire("offset_hors_total_legal").pagination).toEqual({ decalage: 10000, limite: 8, affichees: 0, total: 14, suivant: null, reste: 0, courante: true });
  });

  test("inconnue, zéro résultat et origine absente restent des situations distinctes", () => {
    expect(lire("affaire_inconnue").affaire).toEqual({ connue: false, origine_recue: false, origine: null, verdict: "AMONT-AFFAIRE-INCONNUE" });
    for (const phase of ["zero_hit_8", "zero_hit_9", "zero_hit_10"]) {
      expect(lire(phase).resultats).toEqual([]);
      expect(lire(phase).pagination).toEqual({ decalage: 0, limite: 8, affichees: 0, total: 0, suivant: null, reste: 0, courante: true });
    }
    expect(lire("origine_absente_connue").affaire).toEqual({ connue: true, origine_recue: false, origine: null, verdict: "AMONT-ORIGINE-NON-RECUE" });
  });

  test("ancien fait et consolidation gardent leurs références natives et confidentialité", () => {
    const ancien = lire("match_ancien_hors_cinq_faits");
    expect(ancien.resultats).toHaveLength(1);
    expect(ancien.resultats[0].reference.registre).toBe("evenements");
    const consolidation = lire("consolidation_source_reelle_visible");
    expect(consolidation.resultats).toHaveLength(1);
    const fait = consolidation.resultats[0];
    expect(fait.genre).toBe("fait_consolide");
    expect(fait.source).toBe("m10:consolidation");
    expect(fait.reference.registre).toBe("affaires");
    expect(fait.identifiant).toBe(fait.reference.ligne_id);
    expect(fait.reference.hash_tete).toBe(fait.reference.ligne_id);
    expect(consolidation.confidentialite).toEqual({ agent: null, regle: "v1", niveaux: ["PUBLIC_INTERNAL", "INTERNAL"] });
  });

  test("redémarrage réel : requête et réponse identiques ; agent forgé dans le corps sans effet", () => {
    const avant = capture("avant_restart_exact").capture;
    const apres = capture("relecture_exacte_apres_restart").capture;
    expect(apres.request).toEqual(avant.request);
    expect(apres.response).toEqual(avant.response);
    expect(apres.Gateway_HTTP_response_body_sha256).toBe(avant.Gateway_HTTP_response_body_sha256);
    expect(capture("agent_body_forge_vue_identique").capture.response).toEqual(capture("affaire_canonique_pipeline_durable").capture.response);
  });
});
