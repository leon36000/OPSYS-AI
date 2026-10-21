import capturesSQL from "../fichiers/fixturesDepotFichierSQL.json";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerMutation, soumettreMutation } from "./mutation";
import { DepotOutboxMemoire } from "./depot";
import { creerVidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";

test.each(["completion_review_proposal", "completion_review_decision"] as const)("%s conserve sa série et les HTTP incertains", type => {
  const d = DESCRIPTEURS_MUTATION.get(type);
  expect(d).toBeDefined();
  expect(d).toMatchObject({ serialiserParChantier: true, groupeSerie: "approval_decision",
    conserverRefusHttpIncertains: true, verifierAvantEnvoi: true });
  expect(typeof d?.validerRecuEnvoye).toBe("function");
});

// FILE_ACK_BOUND : collaborateurs réels, transport/octets explicitement fictifs.
describe("fichier_bloc ACK lié au dépôt et au SDK", () => {
  const horloge = { maintenant: new Date("2026-10-08T12:00:00Z"), decalageMinutesUTC: -240 };
  async function preparer(brut: unknown) {
    const depot = new DepotOutboxMemoire();
    const m = await depot.inserer({ ...soumettreMutation(creerMutation({ type: "fichier_bloc", chantierId: "INTERV-FICTIVE",
      payload: { empreinte_sha256: "a".repeat(64), taille_octets: 262147, type_mime: "image/jpeg",
        index_bloc: 1, nombre_blocs: 2, bloc_base64: "QUJD" } }, () => "UUID-BLOC-FICTIF", horloge)), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE" });
    const suite = await depot.inserer({ ...soumettreMutation(creerMutation({ type: "job_completion", chantierId: "INTERV-FICTIVE",
      payload: { intervention_id: "INTERV-FICTIVE" }, dependsOn: m.id }, () => "UUID-SUITE-FICTIVE", horloge)), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE" });
    let maintenant = horloge.maintenant;
    let reponse = brut;
    const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ ok: true, result: reponse }), { status: 200 }));
    const v = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
      session: () => ({ urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF", personne: "PERSONNE-FICTIVE" }),
      maintenant: () => maintenant });
    return { depot, m, suite, fetchImpl, v, reprendre: (date: Date, body: unknown) => { maintenant = date; reponse = body; } };
  }
  test("ACK sans bloc demandé conserve UUID/recul/dépendance", async () => {
    const c = await preparer({ ok: true, resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [0] } } });
    const r = await c.v.vidangerFileSortante();
    expect(r.envoyees).toEqual([]); expect(r.echecsPermanents).toEqual([]); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    expect(await c.depot.obtenir(c.m.id)).toMatchObject({ id: c.m.id, payload: c.m.payload, statut: "en_attente", tentatives: 1 });
    expect((await c.depot.obtenir(c.m.id))?.prochaineTentativeA).not.toBeNull();
    expect((await c.depot.obtenir(c.suite.id))?.statut).toBe("en_attente");
    await c.v.vidangerFileSortante(); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
  });
  test.each([
    ["partiel sans indice", { ok: true, resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [] } } }],
    ["autre référence", { ok: true, resultat: { accepte: true, resultat: { reference: `fichier:sha256:${"b".repeat(64)}`, complet: true, blocs_recus: [0, 1] } } }],
    ["contradiction", { ok: true, resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [0, 1] } } }],
    ["artefact", { ok: true, resultat: "artefact://FICTIF" }],
    ["identité refusée", { ok: false, erreur: "REJ-IDENTITE-APPAREIL-INVALIDE", details: "Identité fictive retirée." }],
    ["identité refusée couple", { ok: true, resultat: { accepte: false, verdict: { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "Retirée", statut: "" } } }],
    ["attente approbation", { ok: true, statut: "en_attente_approbation", demande_id: "DEMANDE-FICTIVE", details: "Attente fictive", rejoue: false }],
    ["approbation rejouée", { ok: true, statut: "en_attente_approbation", demande_id: "DEMANDE-FICTIVE", details: "Attente fictive", rejoue: true }],
    ["code inventé", { ok: true, resultat: { accepte: false, verdict: { code: "REFUS-FICTIF-INCONNU", detail: "" } } }],
  ])("%s ne perd pas l'intention", async (_nom, brut) => {
    const c = await preparer(brut), r = await c.v.vidangerFileSortante();
    expect(r.resultatsAcceptes).toEqual([]); expect(r.echecsPermanents).toEqual([]);
    expect(await c.depot.obtenir(c.m.id)).toMatchObject({ id: c.m.id, payload: c.m.payload, statut: "en_attente" });
    expect((await c.depot.obtenir(c.suite.id))?.statut).toBe("en_attente");
    const request = JSON.parse(String(c.fetchImpl.mock.calls[0][1]?.body));
    expect(request.idempotencyKey).toBe(c.m.id); expect(request.args).toEqual(c.m.payload);
  });
  test.each([false, true])("nominal complet=%s termine uniquement ce bloc", async complet => {
    const brut = { ok: true, resultat: { accepte: true, resultat: { reference: complet ? `fichier:sha256:${"a".repeat(64)}` : null,
      complet, blocs_recus: complet ? [0, 1] : [1] } }, rejoue: true };
    const c = await preparer(brut), r = await c.v.vidangerFileSortante();
    expect(r.envoyees).toEqual([c.m.id]); expect(r.echecsPermanents).toEqual([]);
    const m = await c.depot.obtenir(c.m.id); expect(m?.statut).toBe("envoyee");
    if (!m) throw new Error("Mutation fictive disparue.");
    expect(DESCRIPTEURS_MUTATION.get("fichier_bloc")?.validerRecuEnvoye?.(m)).toBe(true);
    expect(m.resumeAccepte).toEqual({ reference: brut.resultat.resultat.reference, complet, blocsRecus: brut.resultat.resultat.blocs_recus });
  });
  test("réponse inconnue puis reprise conserve exactement clé et payload", async () => {
    const c = await preparer({}); await c.v.vidangerFileSortante();
    const m = await c.depot.obtenir(c.m.id); if (!m?.prochaineTentativeA) throw new Error("Recul absent.");
    c.reprendre(new Date(new Date(m.prochaineTentativeA).getTime() + 1), { ok: true,
      resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [1] } } });
    const r = await c.v.vidangerFileSortante(); expect(r.envoyees).toEqual([c.m.id]); expect(c.fetchImpl).toHaveBeenCalledTimes(2);
    for (const [, init] of c.fetchImpl.mock.calls) {
      const requete = JSON.parse(String(init?.body)); expect(requete.idempotencyKey).toBe(c.m.id); expect(requete.args).toEqual(c.m.payload);
    }
  });
  test("nouveau dépôt mémoire et nouveau vidangeur reprennent le même bloc après recul", async () => {
    const c = await preparer({}); await c.v.vidangerFileSortante();
    const depot = new DepotOutboxMemoire(); for (const ligne of await c.depot.lister()) await depot.inserer(ligne);
    const m = await depot.obtenir(c.m.id); if (!m?.prochaineTentativeA) throw new Error("Recul absent.");
    let date = horloge.maintenant;
    const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ ok: true,
      result: { ok: true, resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [1] } } } }), { status: 200 }));
    const reprise = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
      session: () => ({ urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF", personne: "PERSONNE-FICTIVE" }), maintenant: () => date });
    await reprise.vidangerFileSortante(); expect(fetchImpl).not.toHaveBeenCalled();
    date = new Date(new Date(m.prochaineTentativeA).getTime() + 1);
    expect((await reprise.vidangerFileSortante()).envoyees).toEqual([m.id]);
    const requete = JSON.parse(String(fetchImpl.mock.calls[0][1]?.body));
    expect(requete.idempotencyKey).toBe(m.id); expect(requete.args).toEqual(m.payload);
    expect((await depot.obtenir(c.suite.id))?.statut).toBe("en_attente");
  });
  test("refus fichier canonique est définitif, le dépendant reste fermé", async () => {
    const c = await preparer({ ok: true, resultat: { accepte: false,
      verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", statut: "", detail: "SHA fictif discordant" } } });
    const r = await c.v.vidangerFileSortante(); expect(r.echecsPermanents).toHaveLength(1); expect(r.envoyees).toEqual([]);
    expect((await c.depot.obtenir(c.m.id))?.statut).toBe("echec_permanent"); expect((await c.depot.obtenir(c.suite.id))?.statut).toBe("en_attente");
  });
  test("hook legacy mal lié reste false ; aucune promesse de barrière avant lotB", async () => {
    const c = await preparer({});
    const legacy = { ...c.m, statut: "envoyee" as const, resumeAccepte: { reference: null, complet: false, blocsRecus: [0] } };
    expect(DESCRIPTEURS_MUTATION.get("fichier_bloc")?.validerRecuEnvoye?.(legacy)).toBe(false);
    expect(DESCRIPTEURS_MUTATION.get("fichier_bloc")?.serialiserParChantier).toBeUndefined();
    expect(legacy.id).toBe(c.m.id); expect(c.fetchImpl).not.toHaveBeenCalled();
  });
});

const fichierFictif = { ...soumettreMutation(creerMutation({ type: "fichier_bloc", chantierId: "INTERV-FICTIVE",
  payload: { empreinte_sha256: "a".repeat(64), taille_octets: 262147, type_mime: "image/jpeg",
    index_bloc: 1, nombre_blocs: 2, bloc_base64: "QUJD" } }, () => "UUID-FICTIF",
  { maintenant: new Date("2026-10-08T12:00:00Z"), decalageMinutesUTC: -240 })), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE" };
describe("DESCRIPTEURS_MUTATION", () => {
  test("punch_in/punch_out -> m4_pointer", () => {
    expect(DESCRIPTEURS_MUTATION.get("punch_in")?.tool).toBe("m4_pointer");
    expect(DESCRIPTEURS_MUTATION.get("punch_out")?.tool).toBe("m4_pointer");
  });

  test("job_status_change -> m4_demarrer_route (PLAN T1.4-e)", () => {
    expect(DESCRIPTEURS_MUTATION.get("job_status_change")?.tool).toBe("m4_demarrer_route");
  });

  test("fichier_bloc -> m4_deposer_fichier (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("fichier_bloc")?.tool).toBe("m4_deposer_fichier");
  });

  test("job_completion -> m4_completer_intervention (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("job_completion")?.tool).toBe("m4_completer_intervention");
  });

  test("materials_submit -> m6_declarer_materiaux_utilises (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("materials_submit")?.tool).toBe("m6_declarer_materiaux_utilises");
  });

  test("approval_decision -> m9_decider_demande_approbation (PLAN T1.4-f étape 6)", () => {
    expect(DESCRIPTEURS_MUTATION.get("approval_decision")?.tool).toBe("m9_decider_demande_approbation");
  });

  test("lead_note -> m2_enregistrer_interaction (PLAN T4.8)", () => {
    expect(DESCRIPTEURS_MUTATION.get("lead_note")?.tool).toBe("m2_enregistrer_interaction");
  });

  test("photo_upload/signature_capture : AUCUN descripteur — le transport passe par fichier_bloc (PLAN T1.4-f)", () => {
    expect(DESCRIPTEURS_MUTATION.get("photo_upload")).toBeUndefined();
    expect(DESCRIPTEURS_MUTATION.get("signature_capture")).toBeUndefined();
  });

  describe("interprète fichier_bloc (m4_deposer_fichier)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("fichier_bloc")!.interpreterResultat;

    test("bloc accepté -> accepte:true avec le résumé (reference/complet/blocsRecus)", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [1] } },
      }, fichierFictif);
      expect(resultat).toEqual({ accepte: true, resume: { reference: null, complet: false, blocsRecus: [1] } });
    });

    test("rejet (ex. empreinte discordante) -> accepte:false avec le verdict", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage différent" } },
      }, fichierFictif);
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage différent" } });
    });
  });

  describe("interprète lead_note (m2_enregistrer_interaction)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("lead_note")!.interpreterResultat;

    test("note enregistrée -> accepte:true, l'accusé typé en résumé", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: true, resultat: { lead_id: "L1", ligne_id: "abc", tete_chaine: "def", horodatage: "2026-09-29T14:03:22-04:00" } },
      });
      expect(resultat).toEqual({
        accepte: true,
        resume: { leadId: "L1", ligneId: "abc", horodatage: "2026-09-29T14:03:22-04:00" },
      });
    });

    test("lead d'un autre ou clos -> accepte:false avec le verdict du serveur, tel quel", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead inconnu" } },
      });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead inconnu" } });
    });

    test("accusé illisible -> accepte:false : jamais un succès silencieux", () => {
      expect(interpreter({ ok: true, resultat: { accepte: true, resultat: {} } })).toMatchObject({
        accepte: false,
        verdict: { code: "reponse_illisible" },
      });
    });
  });

  describe("interprète approval_decision (m9_decider_demande_approbation)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("approval_decision")!.interpreterResultat;

    test("décision enregistrée -> accepte:true, l'accusé typé en résumé", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: true, resultat: { demande_id: "d1", decision: "refuser", statut: "refusee", decide_par: "proprio.fictif", role: "nathan_owner" } },
      });
      expect(resultat).toMatchObject({ accepte: true, resume: { demandeId: "d1", decision: "refuser", statut: "refusee" } });
    });

    test("N5 ou déjà décidée -> accepte:false avec le verdict du serveur, tel quel", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "n5_a_la_console", detail: "à décider à la console" } },
      });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "n5_a_la_console", detail: "à décider à la console" } });
    });

    test("accusé illisible -> accepte:false : jamais un succès silencieux", () => {
      const resultat = interpreter({ ok: true, resultat: { accepte: true, resultat: {} } });
      expect(resultat).toMatchObject({
        accepte: false,
        verdict: { code: "accuse_invalide" },
      });
      if (!resultat.accepte) expect(resultat.verdict.detail).not.toContain("ne la renverra pas");
    });
  });

  describe("interprète job_completion (m4_completer_intervention)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("job_completion")!.interpreterResultat;

    test("accepté -> accepte:true, statut porté tel quel (jamais maquillé)", () => {
      const accuse = {
        wct_id: "W1",
        intervention_id: "I1",
        ligne_id: "L1",
        statut: "completed_pending_review",
        hash_maillon: "h",
        duree_reelle_minutes: 90,
        ecart_signale: true,
        tete_chaine: "t",
      };
      const mutation = { ...soumettreMutation(creerMutation({ type: "job_completion", chantierId: "I1",
        payload: { intervention_id: "I1" } }, () => "UUID-COMPLETION-FICTIF",
        { maintenant: new Date("2026-10-08T12:00:00Z"), decalageMinutesUTC: -240 })), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE" };
      const resultat = interpreter({ ok: true, resultat: { accepte: true, resultat: accuse } }, mutation);
      expect(resultat).toEqual({ accepte: true, resume: accuse });
    });

    test("ACK sans intention en attente -> accuse_invalide, issue inconnue", () => {
      const accuse = { wct_id: "W1", intervention_id: "I1", ligne_id: "L1", statut: "completed_pending_review",
        hash_maillon: "h", duree_reelle_minutes: 90, ecart_signale: true, tete_chaine: "t" };
      expect(interpreter({ ok: true, resultat: { accepte: true, resultat: accuse } })).toMatchObject({
        accepte: false, verdict: { code: "accuse_invalide" },
      });
    });

    test("preuves incomplètes -> accepte:false, jamais un succès silencieux", () => {
      const resultat = interpreter({
        ok: true,
        resultat: { accepte: false, verdict: { code: "REJ-CHAMP-VIDE", detail: "photos_apres vide" } },
      });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-CHAMP-VIDE", detail: "photos_apres vide" } });
    });
  });

  describe("interprète materials_submit (m6_declarer_materiaux_utilises)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("materials_submit")!.interpreterResultat;

    test("confirmation canonique liée -> accepte:true (fixture RAM fictive)", () => {
      const lignes = [{ type_ligne: "perte", materiau_id: "MAT-FICTIF", quantite: 2, unite: "m" }];
      const formulaire = { wct_id: "WCT-FICTIF", intervention_id: "INTERVENTION-FICTIVE", chantier_id: "CHANTIER-FICTIF", lignes_materiaux: lignes };
      const mutation = { ...soumettreMutation(creerMutation({ type: "materials_submit", chantierId: formulaire.intervention_id,
        payload: { wct_id: formulaire.wct_id, formulaire } }, () => "UUID-FICTIF",
        { maintenant: new Date("2026-10-08T12:00:00Z"), decalageMinutesUTC: -240 })), destination: "https://fictif.invalid", proprietaire: "PERSONNE-FICTIVE", sequence: 1 };
      // Trois champs exacts de contrats_sortie.py ; aucun écho WCT/personne/UUID inventé.
      const confirmation = { intervention_id: formulaire.intervention_id, chantier_id: formulaire.chantier_id, lignes_declarees: lignes };
      const resultat = interpreter({ ok: true, resultat: { accepte: true, resultat: confirmation,
        registre: { taille: 3, hash_tete: "a".repeat(64) } } }, mutation);
      expect(resultat).toEqual({ accepte: true, resume: confirmation });
    });

    test("rejet sans detail (forme réelle du contrat M6) -> verdict avec detail vide", () => {
      const resultat = interpreter({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-DECLARATION-DEJA-SOUMISE" } } });
      expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-DECLARATION-DEJA-SOUMISE", detail: "" } });
    });
  });

  describe("interprète job_status_change (m4_demarrer_route)", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("job_status_change")!.interpreterResultat;

    test("accepté -> accepte:true avec le résumé", () => {
      const accuse = {
        intervention_id: "I1",
        ligne_id: "L1",
        statut: "en_route",
        statut_precedent: "planifiee",
        empreinte_maillon: "abc",
        tete_chaine: "def",
        horodatage: "2026-09-28T08:00:00-04:00",
      };
      const resultat = interpreter({ ok: true, resultat: { accepte: true, resultat: accuse } });
      expect(resultat).toEqual({ accepte: true, resume: accuse });
    });

    test("rejet métier -> accepte:false avec le verdict, jamais un succès silencieux", () => {
      const resultat = interpreter({
        ok: true,
        resultat: {
          accepte: false,
          verdict: { code: "REJ-TRANSITION-ILLEGALE", statut: "en_route", detail: "transition non autorisée" },
        },
      });
      expect(resultat).toEqual({
        accepte: false,
        verdict: { code: "REJ-TRANSITION-ILLEGALE", detail: "transition non autorisée" },
      });
    });
  });
});

// Transport fictif ; SDK, descripteur, dépôt mémoire et vidangeur actuels. Aucun effet backend simulé.
describe("approval_decision conserve une confirmation inconnue", () => {
  const horloge = { maintenant: new Date("2026-10-09T07:40:00Z"), decalageMinutesUTC: -240 };
  const session = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "DEVICE-FICTIF", personne: "OWNER-FICTIF" };
  const ack = (statut: "executee" | "refusee" | "echec" = "executee") => ({ ok: true, resultat: { accepte: true,
    resultat: { demande_id: "DEMANDE-FICTIVE", decision: "approuver", statut, decide_par: session.personne,
      role: "nathan_owner", issue: { ok: statut !== "echec", accepte: statut === "executee" } } } });
  async function preparer(reponse: Response) {
    const depot = new DepotOutboxMemoire();
    const creer = (id: string) => ({ ...soumettreMutation(creerMutation({ type: "approval_decision", chantierId: "approbations",
      payload: { demande_id: "DEMANDE-FICTIVE", decision: "approuver", motif: "Vu, fictif." } }, () => id, horloge)), destination: session.urlBase, proprietaire: session.personne });
    const premiere = await depot.inserer(creer("UUID-D-FICTIF-1")), suite = await depot.inserer(creer("UUID-D-FICTIF-2"));
    let maintenant = horloge.maintenant;
    const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => reponse);
    const vidangeur = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
      fetchImpl, session: () => session, maintenant: () => maintenant });
    return { depot, premiere, suite, fetchImpl, vidangeur, reprendre: (date: Date, body: unknown) => {
      maintenant = date; reponse = new Response(JSON.stringify({ ok: true, result: body }), { status: 200 });
    } };
  }
  const illisibles: readonly [string, unknown][] = [
    ["ACK malformé", { ok: true, resultat: { accepte: true, resultat: { statut: "INCONNU-FICTIF" } } }],
    ["sortie tronquée", { ok: true, tronque: true, apercu: "{" }],
    ...ERREURS_PASSAGERES.map(code => [code, { ok: false, erreur: code, details: "État fictif passager." }] as [string, unknown]),
  ];
  test.each(illisibles)("%s conserve UUID/corps et bloque la suivante dans la même passe", async (_nom, body) => {
    const c = await preparer(new Response(JSON.stringify({ ok: true, result: body }), { status: 200 }));
    const r = await c.vidangeur.vidangerFileSortante();
    expect(r.echecsPermanents).toEqual([]); expect(r.resultatsAcceptes).toEqual([]);
    expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    expect(await c.depot.obtenir(c.premiere.id)).toMatchObject({ id: c.premiere.id, payload: c.premiere.payload,
      destination: session.urlBase, proprietaire: session.personne, createdAtLocal: c.premiere.createdAtLocal, statut: "en_attente" });
    expect((await c.depot.obtenir(c.suite.id))?.statut).toBe("en_attente");
  });
  test.each([401, 403, 400, 404])("HTTP%s après dispatch reste inconnu et bloque la suite", async status => {
    const c = await preparer(new Response(JSON.stringify({ ok: false, error: { type: "refus_fictif", message: "Refus fictif." } }), { status }));
    const r = await c.vidangeur.vidangerFileSortante();
    expect(r.echecsPermanents).toEqual([]); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
    expect(await c.depot.obtenir(c.premiere.id)).toMatchObject({ id: c.premiere.id, payload: c.premiere.payload, statut: "en_attente" });
    expect((await c.depot.obtenir(c.suite.id))?.statut).toBe("en_attente");
  });
  test("reprise après ACK illisible conserve exactement UUID, heure, arguments et destination", async () => {
    const c = await preparer(new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 }));
    await c.vidangeur.vidangerFileSortante();
    const m = await c.depot.obtenir(c.premiere.id); expect(m?.prochaineTentativeA).not.toBeNull();
    c.reprendre(new Date(new Date(m!.prochaineTentativeA!).getTime() + 1), ack());
    expect((await c.vidangeur.vidangerFileSortante()).envoyees).toContain(m!.id);
    const requetes = c.fetchImpl.mock.calls.slice(0, 2).map(([url, init]) => ({ url, body: JSON.parse(String(init?.body)) }));
    expect(requetes[1]).toEqual(requetes[0]);
    expect(requetes[0].body.idempotencyKey).toBe(c.premiere.id); expect(requetes[0].body.args).toEqual(c.premiere.payload);
  });
  test.each(["executee", "refusee", "echec"] as const)("ACK valide %s reste une décision enregistrée", statut => {
    expect(DESCRIPTEURS_MUTATION.get("approval_decision")!.interpreterResultat(ack(statut))).toMatchObject({
      accepte: true, resume: { demandeId: "DEMANDE-FICTIVE", statut } });
  });
  test("refus métier certain demeure terminal", async () => {
    const c = await preparer(new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: { accepte: false,
      verdict: { code: "deja_decidee", detail: "Demande fictive déjà décidée." } } } }), { status: 200 }));
    const r = await c.vidangeur.vidangerFileSortante();
    expect(r.echecsPermanents[0].verdict.code).toBe("deja_decidee");
    expect((await c.depot.obtenir(c.premiere.id))?.statut).toBe("echec_permanent");
  });
});

// Originaux Cap/DEVICE injecté/SQLite : aucun HTTP natif capturé. Le wrapper Gateway
// et le fetch ci-dessous sont un transport de rejeu fictif, pas une preuve de pairing.
interface CaptureSDKSQL {
  readonly phase: string; readonly request: { readonly toolName: string; readonly args: Record<string, unknown>;
    readonly mutation: null | { readonly idempotencyKey: string; readonly appareil: string; readonly horodatage_appareil: string } };
  readonly caller: { readonly personne: string }; readonly response: unknown;
}
describe("FILE_ACK_BOUND —17 dépôts SQL via vrai SDK/descripteur/vidangeur", () => {
  test.each(capturesSQL.captures.filter(r => r.disposition_mobile !== "etat_separe_non_durci").map(row => [row.phase, row] as const))("%s", async (_phase, row) => {
    const c: CaptureSDKSQL = JSON.parse(row.capture_utf8), meta = c.request.mutation;
    // Cette capsule contient le corps Python original ; seul le wrapper Gateway est fictif.
    const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(`{"ok":true,"result":${row.response_utf8}}`, { status: 200 }));
    if (!meta) {
      const r = await invoquerOutil({ fetchImpl, urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF",
        requete: { tool: c.request.toolName, args: c.request.args } });
      expect(r.ok).toBe(true); if (!r.ok) throw new Error("Transport fictif refusé.");
      expect(DESCRIPTEURS_MUTATION.get("fichier_bloc")!.interpreterResultat(r.result))
        .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } }); return;
    }
    const depot = new DepotOutboxMemoire();
    const m = await depot.inserer({ ...soumettreMutation(creerMutation({ type: "fichier_bloc",
      chantierId: "INTERVENTION-LOCALE-FICTIVE-NON-ECHO", payload: c.request.args }, () => meta.idempotencyKey,
      { maintenant: new Date(meta.horodatage_appareil), decalageMinutesUTC: -240 })), destination: "https://fictif.invalid", proprietaire: c.caller.personne });
    expect(m.id).toBe(meta.idempotencyKey); expect(m.createdAtLocal).toBe(meta.horodatage_appareil);
    const v = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil, fetchImpl,
      session: () => ({ urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: meta.appareil, personne: c.caller.personne }),
      maintenant: () => new Date(meta.horodatage_appareil) });
    const rapport = await v.vidangerFileSortante(), etat = await depot.obtenir(m.id);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const requete = JSON.parse(String(fetchImpl.mock.calls[0][1]?.body));
    expect(requete).toEqual({ tool: c.request.toolName, args: c.request.args, idempotencyKey: meta.idempotencyKey,
      deviceId: meta.appareil, deviceTimestamp: meta.horodatage_appareil });
    if (row.disposition_mobile === "accepte") {
      expect(rapport.envoyees).toEqual([m.id]); expect(etat?.statut).toBe("envoyee");
      if (!etat) throw new Error("Intention manquante.");
      expect(DESCRIPTEURS_MUTATION.get("fichier_bloc")?.validerRecuEnvoye?.(etat)).toBe(true);
    } else if (row.disposition_mobile === "refus_permanent") {
      expect(rapport.echecsPermanents).toHaveLength(1); expect(etat?.statut).toBe("echec_permanent");
    } else {
      expect(rapport.resultatsAcceptes).toEqual([]); expect(rapport.echecsPermanents).toEqual([]);
      expect(etat).toMatchObject({ id: m.id, payload: c.request.args, statut: "en_attente", tentatives: 1 });
      expect(etat?.prochaineTentativeA).not.toBeNull();
    }
  });
});
