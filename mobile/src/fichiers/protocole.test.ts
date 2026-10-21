import { createHash } from "node:crypto";
import capturesSQL from "./fixturesDepotFichierSQL.json";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import {
  construireArgumentsDeposerFichier,
  construireArgumentsEtatFichier,
  construireReferenceFichier,
  interpreterResultatDeposerFichier,
  interpreterResultatEtatFichier,
  validerRecuDeposerFichier,
} from "./protocole";

const SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

// Fixtures fictives en RAM. Bloc final de 3 octets, fichier de deux blocs ; pas une photo réelle.
const mutationFictive = { id: "UUID-FICHIER-FICTIF", sequence: 1, type: "fichier_bloc" as const,
  chantierId: "INTERVENTION-FICTIVE", payload: { empreinte_sha256: SHA, taille_octets: 262147,
    type_mime: "image/jpeg", index_bloc: 1, nombre_blocs: 2, bloc_base64: "QUJD" },
  dependsOn: null, statut: "envoi" as const, tentatives: 0, createdAtLocal: "2026-10-08T12:00:00-04:00",
  prochaineTentativeA: null, proprietaire: "PERSONNE-FICTIVE" };
function avecContexte(brut: unknown, mutation: MutationOutbox = mutationFictive) {
  return interpreterResultatDeposerFichier(brut, mutation);
}
function accuseFictif(complet = false, blocs_recus = [1], reference: string | null = null) {
  return { ok: true, resultat: { accepte: true, resultat: { complet, blocs_recus, reference } } };
}

describe("FILE_ACK_BOUND — bloc demandé et JSON entier", () => {
  test.each([
    ["bloc demandé absent", accuseFictif(false, [0])],
    ["autre SHA", accuseFictif(true, [0, 1], `fichier:sha256:${"a".repeat(64)}`)],
    ["index hors count", accuseFictif(false, [1, 2])],
    ["indices dupliqués", accuseFictif(false, [1, 1])],
    ["complet non exhaustif", accuseFictif(true, [1], construireReferenceFichier(SHA))],
    ["incomplet exhaustif", accuseFictif(false, [0, 1])],
    ["incomplet avec référence", accuseFictif(false, [1], construireReferenceFichier(SHA))],
    ["champ supplémentaire", { ...accuseFictif(), artefact: "artefact://fictif" }],
  ])("%s reste inconnu", (_nom, brut) => {
    expect(avecContexte(brut)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  });
  test("aucun getter exécuté", () => {
    let executions = 0; const brut = accuseFictif();
    Object.defineProperty(brut.resultat.resultat, "complet", { enumerable: true, get: () => { executions++; return false; } });
    expect(avecContexte(brut).accepte).toBe(false); expect(executions).toBe(0);
  });
  test("sans contexte persistant même un bon ACK demeure inconnu", () => {
    expect(interpreterResultatDeposerFichier(accuseFictif())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  });
});

describe("construireArgumentsDeposerFichier / construireArgumentsEtatFichier", () => {
  test("args exacts du contrat, rien de plus", () => {
    expect(construireArgumentsDeposerFichier(SHA, 300, "image/jpeg", 0, 2, "QUJD")).toEqual({
      empreinte_sha256: SHA,
      taille_octets: 300,
      type_mime: "image/jpeg",
      index_bloc: 0,
      nombre_blocs: 2,
      bloc_base64: "QUJD",
    });
  });

  test("args exacts de m4_etat_fichier", () => {
    expect(construireArgumentsEtatFichier(SHA)).toEqual({ empreinte_sha256: SHA });
  });
});

describe("construireReferenceFichier", () => {
  test("forme exacte du contrat", () => {
    expect(construireReferenceFichier(SHA)).toBe(`fichier:sha256:${SHA}`);
  });
});

describe("interpreterResultatDeposerFichier", () => {
  test("bloc accepté, fichier pas encore complet -> reference null", () => {
    const resultat = avecContexte({
      ok: true,
      resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [1] } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { reference: null, complet: false, blocsRecus: [1] } });
  });

  test("dernier bloc accepté -> complet true, référence déterministe", () => {
    const reference = construireReferenceFichier(SHA);
    const resultat = avecContexte({
      ok: true,
      resultat: { accepte: true, resultat: { reference, complet: true, blocs_recus: [0, 1] } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { reference, complet: true, blocsRecus: [0, 1] } });
  });

  test("rejet métier -> accepte:false avec le verdict, jamais un succès silencieux", () => {
    const resultat = avecContexte({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage recalculé différent" } },
    });
    expect(resultat).toEqual({
      accepte: false,
      verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage recalculé différent" },
    });
  });

  test("erreur technique (ok:false) -> accepte:false", () => {
    const resultat = avecContexte({ ok: false, erreur: "invalid_request", details: "type_mime invalide" });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "invalid_request", detail: "type_mime invalide" } });
  });

  test("forme non reconnue ou accusé incomplet -> rejet récupérable, jamais envoyé", () => {
    const attendu = { accepte: false, verdict: { code: "accuse_invalide", detail: "Réponse métier de dépôt de fichier inconnue." } };
    expect(avecContexte(null)).toEqual(attendu);
    expect(avecContexte(undefined)).toEqual(attendu);
    expect(avecContexte({ ok: true, resultat: { accepte: true, resultat: {} } }).accepte).toBe(false);
  });

  test("un accusé valide d'un bloc non final demeure accepté", () => {
    expect(avecContexte({ ok: true, resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [1] } } }))
      .toEqual({ accepte: true, resultat: { reference: null, complet: false, blocsRecus: [1] } });
  });
});

describe("interpreterResultatEtatFichier", () => {
  test("fichier connu, incomplet -> blocs déjà reçus portés", () => {
    const resultat = etatAvecContexte({
      ok: true,
      resultat: { accepte: true, resultat: { existe: true, complet: false, blocs_recus: [0], reference: null } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { existe: true, complet: false, blocsRecus: [0], reference: null } });
  });

  test("fichier inconnu du serveur -> existe:false, jamais une erreur", () => {
    const resultat = etatAvecContexte({
      ok: true,
      resultat: { accepte: true, resultat: { existe: false, complet: false, blocs_recus: [], reference: null } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { existe: false, complet: false, blocsRecus: [], reference: null } });
  });

  test("fichier complet -> reference portée", () => {
    const reference = construireReferenceFichier(SHA);
    const resultat = etatAvecContexte({
      ok: true,
      resultat: { accepte: true, resultat: { existe: true, complet: true, blocs_recus: [0, 1], reference } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { existe: true, complet: true, blocsRecus: [0, 1], reference } });
  });

  test("rejet métier (ex. empreinte hors forme attendue) -> accepte:false", () => {
    const resultat = etatAvecContexte({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-FICHIER-PARAMETRES-INVALIDES", detail: "empreinte_sha256 invalide" } },
    });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-FICHIER-PARAMETRES-INVALIDES", detail: "empreinte_sha256 invalide" } });
  });

  test("réponse inconnue ou état incomplet ne se transforme pas en fichier absent", () => {
    expect(etatAvecContexte({})).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
    expect(etatAvecContexte({ ok: true, resultat: { accepte: true, resultat: {} } })).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  });
});

// Le payload est évalué tel que persisté, sans réparer les anciennes formes.
describe("FILE_ACK_BOUND — contexte et reçu durable", () => {
  const payloads: Array<readonly [string, Record<string, unknown>]> = [
    ["autre hash non hex", { empreinte_sha256: "sha" }], ["SHA majuscule", { empreinte_sha256: "A".repeat(64) }],
    ["SHA newline", { empreinte_sha256: `${SHA}\n` }],
    ["taille nulle", { taille_octets: 0 }], ["taille trop grande", { taille_octets: 10485761 }],
    ["taille fractionnaire", { taille_octets: 2.5 }], ["nombre incohérent", { nombre_blocs: 3 }],
    ["count unsafe", { nombre_blocs: 2 ** 53 }], ["index hors borne", { index_bloc: 2 }],
    ["index négatif", { index_bloc: -1 }], ["MIME inconnu", { type_mime: "text/plain" }],
    ["base64 invalide", { bloc_base64: "???=" }], ["base64 espaces", { bloc_base64: "Q UJD" }],
    ["base64 newline de longueur plausible", { bloc_base64: "QUJ\n" }],
    ["mauvaise longueur réelle", { bloc_base64: "QQ==" }], ["champ ajouté", { prix: 10 }],
    ["valeur NaN", { taille_octets: NaN }],
  ];
  test.each(payloads)("%s conserve issue inconnue", (_nom, patch) => {
    expect(avecContexte(accuseFictif(), { ...mutationFictive, payload: { ...mutationFictive.payload, ...patch } }))
      .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  });
  test.each([null, ""])("propriétaire %j n'est pas promu", proprietaire => {
    expect(avecContexte(accuseFictif(), { ...mutationFictive, proprietaire }).accepte).toBe(false);
  });
  test("contexte getter : zéro exécution", () => {
    let appels = 0; const c = { ...mutationFictive };
    Object.defineProperty(c, "payload", { enumerable: true, get: () => { appels++; return mutationFictive.payload; } });
    expect(avecContexte(accuseFictif(), c).accepte).toBe(false); expect(appels).toBe(0);
  });
  test.each([Object.assign(Object.create({ autre: true }), accuseFictif()), (() => { const b = accuseFictif(); Reflect.set(b, "cycle", b); return b; })(),
    Object.assign(accuseFictif(), { [Symbol("fictif")]: true })])("JSON hostile refusé entier", brut => {
    expect(avecContexte(brut).accepte).toBe(false);
  });
  test("nominals partiel et complet : valeurs sources, pas de tri des indices", () => {
    expect(avecContexte(accuseFictif())).toEqual({ accepte: true, resultat: { reference: null, complet: false, blocsRecus: [1] } });
    expect(avecContexte(accuseFictif(true, [1, 0], construireReferenceFichier(SHA))))
      .toEqual({ accepte: true, resultat: { reference: construireReferenceFichier(SHA), complet: true, blocsRecus: [1, 0] } });
  });
  test.each([{}, null, { complet: false, reference: null, blocsRecus: [0] },
    { complet: true, reference: `fichier:sha256:${"a".repeat(64)}`, blocsRecus: [0, 1] }])("ancien envoyé %j non probant", resumeAccepte => {
    expect(validerRecuDeposerFichier({ ...mutationFictive, statut: "envoyee", resumeAccepte })).toBe(false);
  });
  test("reçu durable lié, partiel ou complet, ne réexpédie ni ne crée de clé", () => {
    for (const resumeAccepte of [{ complet: false, reference: null, blocsRecus: [1] },
      { complet: true, reference: construireReferenceFichier(SHA), blocsRecus: [0, 1] }]) {
      const m: MutationOutbox = { ...mutationFictive, statut: "envoyee", resumeAccepte };
      expect(validerRecuDeposerFichier(m)).toBe(true); expect(m.id).toBe(mutationFictive.id);
      expect(validerRecuDeposerFichier({ ...m, statut: "en_attente" })).toBe(false);
    }
  });
});

interface CaptureDepotSQL {
  readonly phase: string; readonly fictif: boolean;
  readonly request: { readonly toolName: string; readonly args: Record<string, unknown>; readonly mutation: null | {
    readonly idempotencyKey: string; readonly appareil: string; readonly horodatage_appareil: string; } };
  readonly caller: { readonly personne: string }; readonly response: unknown;
  readonly response_UTF8_bytes: number; readonly response_UTF8_sha256: string;
}
function contexteSQL(c: CaptureDepotSQL): MutationOutbox | undefined {
  const m = c.request.mutation; if (!m) return undefined;
  return { ...soumettreMutation(creerMutation({ type: "fichier_bloc", chantierId: "INTERVENTION-LOCALE-FICTIVE-NON-ECHO",
    payload: c.request.args }, () => m.idempotencyKey, { maintenant: new Date(m.horodatage_appareil), decalageMinutesUTC: -240 })),
    proprietaire: c.caller.personne };
}
describe("FILE_ACK_BOUND —22 originaux SQL scellés (17 dépôts +5 états distincts)", () => {
  test.each(capturesSQL.captures.map(row => [row.phase, row] as const))("%s original UTF8/SHA et disposition", (_phase, row) => {
    expect(capturesSQL.fictif).toBe(true);
    const c: CaptureDepotSQL = JSON.parse(row.capture_utf8); expect(c.fictif).toBe(true);
    expect(createHash("sha256").update(row.capture_utf8, "utf8").digest("hex")).toBe(row.capture_sha256);
    expect(createHash("sha256").update(row.response_utf8, "utf8").digest("hex")).toBe(row.response_sha256);
    expect(Buffer.byteLength(row.response_utf8, "utf8")).toBe(c.response_UTF8_bytes);
    expect(row.response_sha256).toBe(c.response_UTF8_sha256); expect(JSON.parse(row.response_utf8)).toEqual(c.response);
    if (c.request.toolName === "m4_etat_fichier") {
      // Caractérisation du lecteur existant seulement ; aucune garde/contexte nouveau pour état.
      expect(row.disposition_mobile).toBe("etat_separe_non_durci");
      if(typeof c.request.args.empreinte_sha256 !== "string") throw new Error("Query SHA manquante");
      const lecture = interpreterResultatEtatFichier(c.response,{empreinte_sha256:c.request.args.empreinte_sha256,
        taille_octets:capturesSQL.image_provenance.bytes,type_mime:"image/png",nombre_blocs:capturesSQL.image_provenance.blocks});
      expect(lecture.accepte).toBe(row.phase !== "role-removed-state"); return;
    }
    const lecture = interpreterResultatDeposerFichier(c.response, contexteSQL(c));
    if (row.disposition_mobile === "accepte") {
      expect(lecture.accepte).toBe(true);
    } else {
      expect(lecture.accepte).toBe(false);
      if (lecture.accepte) throw new Error("Reçu de refus fictif accepté.");
      if (row.disposition_mobile === "accuse_invalide") expect(lecture.verdict.code).toBe("accuse_invalide");
      else expect(lecture.verdict.code).toMatch(/^REJ-FICHIER-/);
    }
  });
  test("restart source exact, aucune copie de CAS ni photo de dommage inférée", () => {
    expect(capturesSQL.captures).toHaveLength(22);
    expect(capturesSQL.captures.filter(r => r.disposition_mobile === "etat_separe_non_durci")).toHaveLength(5);
    expect(createHash("sha256").update(capturesSQL.restart_utf8, "utf8").digest("hex")).toBe(capturesSQL.restart_sha256);
    const restart = JSON.parse(capturesSQL.restart_utf8);
    const trouve = (phase: string) => { const c = capturesSQL.captures.find(r => r.phase === phase); if (!c) throw new Error(phase); return JSON.parse(c.response_utf8); };
    expect(restart.response).toEqual(trouve("complete-UUID-replay")); expect(restart.state).toEqual(trouve("complete-state"));
    expect(capturesSQL.image_provenance.generation).toBe("deterministic random pixels, not a photo of a chantier");
    // Le vrai serveur accepte le bloc partiel sous un mauvais SHA puis purge au complet :
    // l'ACK partiel ne constitue donc PAS une preuve d'intégrité du fichier assemblé.
    const partiel = capturesSQL.captures.find(r => r.phase === "wrong-SHA-0"); if (!partiel) throw new Error("Capture manquante");
    const c: CaptureDepotSQL = JSON.parse(partiel.capture_utf8);
    expect(c.request.args.empreinte_sha256).not.toBe(capturesSQL.image_provenance.image_sha256);
    expect(interpreterResultatDeposerFichier(c.response, contexteSQL(c)).accepte).toBe(true);
    expect(trouve("wrong-SHA-1").resultat.verdict.code).toBe("REJ-FICHIER-EMPREINTE-DISCORDANTE");
  });
});

// Nouveau contexte léger de l'état : observé localement après vérification des octets.
const contexteEtatFictif = { empreinte_sha256: SHA, taille_octets: 262147, type_mime: "image/jpeg" as const, nombre_blocs: 2 };
function etatAvecContexte(brut: unknown) { return interpreterResultatEtatFichier(brut, contexteEtatFictif); }
describe("B1 état lié JSON fermé", () => {
  test.each([
    { existe:true,complet:true,blocs_recus:[0,1],reference:`fichier:sha256:${"a".repeat(64)}` },
    { existe:true,complet:true,blocs_recus:[0,1,2],reference:construireReferenceFichier(SHA) },
    { existe:false,complet:true,blocs_recus:[0,1],reference:construireReferenceFichier(SHA) },
    { existe:true,complet:false,blocs_recus:[0,0],reference:null },
  ])("état discordant n'est jamais prêt %j", resultat => {
    expect(etatAvecContexte({ok:true,resultat:{accepte:true,resultat}})).toMatchObject({accepte:false,verdict:{code:"accuse_invalide"}});
  });
  test("getter état zéro exécution", () => {
    let n=0; const resultat={existe:true,complet:false,blocs_recus:[0],reference:null};
    Object.defineProperty(resultat,"complet",{enumerable:true,get:()=>{n++;return false;}});
    expect(etatAvecContexte({ok:true,resultat:{accepte:true,resultat}}).accepte).toBe(false);expect(n).toBe(0);
  });
});
