import type { AccuseDecision, AttenteDepartement, AttentesDepartements, DemandeApprobation } from "../approbations/contrat";
import { creerChargeurApprobations } from "../approbations/chargeur";
import type { ParametresAppelOutil } from "../protocole/client";
import { interpreterResultatListerDemandes } from "../approbations/contrat";
import { DepotOutboxMemoire } from "../outbox/depot";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import { creerVidangeur } from "../outbox/vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { MutationOutbox } from "../outbox/types";
import {
  accuseDepuisResume,
  chargerSuiteAttentes,
  CHANTIER_ID_APPROBATIONS,
  cleAttente,
  creerMutationDecision,
  decisionsEnFile,
  evaluerOffre,
  formaterArguments,
  formaterDepuis,
  fusionnerPageAttentes,
  issueAffichee,
  vueAttentes,
} from "./approvals";

const HORLOGE = { maintenant: new Date("2026-09-28T18:32:00.000Z"), decalageMinutesUTC: -240 };
let compteur = 0;
const idDeterministe = () => `decision-${++compteur}`;
beforeEach(() => {
  compteur = 0;
});

function demande(surcharge: Partial<DemandeApprobation> = {}): DemandeApprobation {
  return {
    id: "d1",
    departement: "m04-field-ops",
    departementNom: "Field Operations",
    outil: "m4_resoudre_revue_completion",
    descriptionOutil: null,
    niveau: "N4",
    depuis: "2026-09-28T14:00:00+00:00",
    motifDemande: null,
    arguments: { intervention_id: "I1" },
    decidable: true,
    lectureSeule: null,
    ...surcharge,
  };
}

describe("evaluerOffre — ce que l'écran offre", () => {
  test("N3 et N4, propriétaire, arguments affichés, serveur d'accord -> décidable", () => {
    expect(evaluerOffre(demande({ niveau: "N3" }), true)).toEqual({ decidable: true });
    expect(evaluerOffre(demande({ niveau: "N4" }), true)).toEqual({ decidable: true });
  });

  test("le verdict de lecture seule du serveur passe en premier, tel quel", () => {
    const verdict = { code: "n5_a_la_console", detail: "Niveau N5 : à décider à la console." };
    expect(evaluerOffre(demande({ niveau: "N5", decidable: false, lectureSeule: verdict }), true)).toEqual({
      decidable: false,
      raison: { genre: "serveur", verdict },
    });
  });

  test("N5 sans verdict (le serveur se contredit) : console, jamais un bouton", () => {
    expect(evaluerOffre(demande({ niveau: "N5", decidable: true }), true)).toEqual({ decidable: false, raison: { genre: "console" } });
  });

  test("niveau absent ou inconnu : console", () => {
    expect(evaluerOffre(demande({ niveau: null }), true)).toEqual({ decidable: false, raison: { genre: "console" } });
    expect(evaluerOffre(demande({ niveau: "N2" }), true)).toEqual({ decidable: false, raison: { genre: "console" } });
    expect(evaluerOffre(demande({ niveau: "n3" }), true)).toEqual({ decidable: false, raison: { genre: "console" } });
  });

  test("pas le propriétaire : lecture seule, même si la demande est décidable en soi", () => {
    expect(evaluerOffre(demande(), false)).toEqual({ decidable: false, raison: { genre: "non_proprietaire" } });
  });

  test("arguments absents : on ne décide pas ce qu'on ne peut pas lire", () => {
    expect(evaluerOffre(demande({ arguments: null }), true)).toEqual({ decidable: false, raison: { genre: "arguments_absents" } });
  });

  test("le serveur ne dit pas décidable : lecture seule, même sans raison donnée", () => {
    expect(evaluerOffre(demande({ decidable: false }), true)).toEqual({ decidable: false, raison: { genre: "incoherente" } });
  });
});

function mutationDecision(id: string, statut: MutationOutbox["statut"], payload: Record<string, unknown>, type: MutationOutbox["type"] = "approval_decision"): MutationOutbox {
  return { id, sequence: 1, type, chantierId: CHANTIER_ID_APPROBATIONS, payload, dependsOn: null, statut, tentatives: 0, createdAtLocal: "2026-09-28T14:32:00-04:00", prochaineTentativeA: null, proprietaire: "proprio.fictif" };
}

describe("decisionsEnFile", () => {
  test("les décisions en attente ou en envoi, par demande ; pas les envoyées ni les échecs permanents", () => {
    const enFile = decisionsEnFile([
      mutationDecision("m1", "en_attente", { demande_id: "d1", decision: "approuver" }),
      mutationDecision("m2", "envoi", { demande_id: "d2", decision: "refuser" }),
      mutationDecision("m3", "envoyee", { demande_id: "d3", decision: "approuver" }),
      mutationDecision("m4", "echec_permanent", { demande_id: "d4", decision: "approuver" }),
      mutationDecision("m5", "brouillon", { demande_id: "d5", decision: "approuver" }),
    ]);
    expect([...enFile.keys()].sort()).toEqual(["d1", "d2"]);
    expect(enFile.get("d1")).toEqual({ mutationId: "m1", decision: "approuver", statut: "en_attente" });
    expect(enFile.get("d2")).toEqual({ mutationId: "m2", decision: "refuser", statut: "envoi" });
  });

  test("ignore les autres types de mutation et les payloads mal formés", () => {
    const enFile = decisionsEnFile([
      mutationDecision("m1", "en_attente", { demande_id: "d1", decision: "approuver" }, "punch_in"),
      mutationDecision("m2", "en_attente", { demande_id: 5, decision: "approuver" }),
      mutationDecision("m3", "en_attente", { demande_id: "d3", decision: "annuler" }),
      mutationDecision("m4", "en_attente", {}),
    ]);
    expect(enFile.size).toBe(0);
  });

  test("deux décisions pour la même demande : la première (la plus ancienne) fait foi", () => {
    const enFile = decisionsEnFile([
      mutationDecision("m1", "en_attente", { demande_id: "d1", decision: "refuser" }),
      mutationDecision("m2", "en_attente", { demande_id: "d1", decision: "approuver" }),
    ]);
    expect(enFile.get("d1")?.mutationId).toBe("m1");
  });
});

describe("creerMutationDecision", () => {
  test("une mutation approval_decision en_attente, dans son propre groupe, avec les args exacts de l'outil", () => {
    const mutation = creerMutationDecision("d1", "approuver", "", idDeterministe, HORLOGE);

    expect(mutation).toMatchObject({
      id: "decision-1",
      type: "approval_decision",
      chantierId: CHANTIER_ID_APPROBATIONS,
      statut: "en_attente",
      dependsOn: null,
      tentatives: 0,
      createdAtLocal: "2026-09-28T14:32:00-04:00",
    });
    expect(mutation.payload).toEqual({ demande_id: "d1", decision: "approuver" });
  });

  test("la note du propriétaire voyage, épurée ; jamais de personne, de rôle ni d'appareil dans le payload", () => {
    const mutation = creerMutationDecision("d1", "refuser", "  Pas maintenant.  ", idDeterministe, HORLOGE);

    expect(mutation.payload).toEqual({ demande_id: "d1", decision: "refuser", motif: "Pas maintenant." });
    expect(Object.keys(mutation.payload).sort()).toEqual(["decision", "demande_id", "motif"]);
  });

  test("identifiant de demande vide : erreur, aucune mutation", () => {
    expect(() => creerMutationDecision("  ", "approuver", "", idDeterministe, HORLOGE)).toThrow("identifiant de demande vide");
    expect(compteur).toBe(0);
  });

  test("deux décisions = deux ids (deux clés d'idempotence distinctes)", () => {
    const a = creerMutationDecision("d1", "approuver", "", idDeterministe, HORLOGE);
    const b = creerMutationDecision("d1", "approuver", "", idDeterministe, HORLOGE);
    expect(a.id).not.toBe(b.id);
  });
});

describe("la décision passe par la file sortante, avec sa clé d'idempotence", () => {
  const ACCUSE = {
    demande_id: "d1",
    decision: "approuver",
    statut: "executee",
    outil: "m4_resoudre_revue_completion",
    departement: "m04-field-ops",
    niveau: "N4",
    decide_par: "proprio.fictif",
    role: "nathan_owner",
    decide_le: "2026-09-28T18:33:00+00:00",
    issue: { ok: true, accepte: true },
  };
  const reponseHttp = (corps: unknown): Response => ({ ok: true, status: 200, json: async () => corps }) as unknown as Response;
  const accepte = () => reponseHttp({ ok: true, result: { ok: true, resultat: { accepte: true, resultat: ACCUSE }, rejoue: false } });

  /** Les décisions sont créées sous la personne confirmée de l'appareil (PLAN T1.4-l) : la file ne les envoie que pour elle. */
  const deposer = (depot: DepotOutboxMemoire, mutation: MutationOutbox) => depot.inserer({ ...mutation, proprietaire: "proprio.fictif" });

  function vidangeurDe(depot: DepotOutboxMemoire, fetchImpl: jest.Mock, maintenant: () => Date = () => HORLOGE.maintenant) {
    return creerVidangeur({
      depot,
      descripteurs: DESCRIPTEURS_MUTATION,
      appelerOutil: invoquerOutil,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      session: () => ({
        urlBase: "https://grs.exemple.ca",
        jeton: "jeton-test",
        appareilId: "APPAREIL-PROPRIO",
        personne: "proprio.fictif",
      }),
      maintenant,
    });
  }

  const corps = (fetchImpl: jest.Mock, i = 0) => JSON.parse((fetchImpl.mock.calls[i][1] as RequestInit).body as string) as Record<string, unknown>;

  test("envoi : outil m9_decider_demande_approbation, idempotencyKey = id de la mutation, args exacts, accusé lu", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationDecision("d1", "approuver", "Vu.", idDeterministe, HORLOGE));
    const fetchImpl = jest.fn().mockResolvedValue(accepte());

    const rapport = await vidangeurDe(depot, fetchImpl).vidangerFileSortante();

    expect(rapport.envoyees).toEqual([persistee.id]);
    expect(corps(fetchImpl)).toEqual({
      tool: "m9_decider_demande_approbation",
      args: { demande_id: "d1", decision: "approuver", motif: "Vu." },
      idempotencyKey: persistee.id,
      deviceId: "APPAREIL-PROPRIO",
      deviceTimestamp: "2026-09-28T14:32:00-04:00",
    });
    const accuse = accuseDepuisResume(rapport.resultatsAcceptes[0].resume);
    expect(accuse).toMatchObject({ demandeId: "d1", statut: "executee", decidePar: "proprio.fictif", role: "nathan_owner" });
    expect((await depot.obtenir(persistee.id))?.statut).toBe("envoyee");
  });

  test("réponse perdue : le renvoi porte LA MÊME clé (le serveur ne l'applique qu'une fois)", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationDecision("d1", "approuver", "", idDeterministe, HORLOGE));
    let maintenant = new Date(HORLOGE.maintenant);
    const fetchImpl = jest.fn().mockRejectedValueOnce(new TypeError("Network request failed")).mockResolvedValueOnce(accepte());
    const vidangeur = vidangeurDe(depot, fetchImpl, () => maintenant);

    const premier = await vidangeur.vidangerFileSortante();
    expect(premier.remisesEnAttente).toEqual([persistee.id]);
    maintenant = new Date(new Date((await depot.obtenir(persistee.id))!.prochaineTentativeA!).getTime() + 1);
    const second = await vidangeur.vidangerFileSortante();

    expect(second.envoyees).toEqual([persistee.id]);
    expect(corps(fetchImpl, 0).idempotencyKey).toBe(persistee.id);
    expect(corps(fetchImpl, 1).idempotencyKey).toBe(persistee.id);
    expect(corps(fetchImpl, 1).args).toEqual(corps(fetchImpl, 0).args);
  });

  test("le serveur refuse (déjà décidée) : échec permanent avec SON verdict, jamais un succès", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationDecision("d1", "approuver", "", idDeterministe, HORLOGE));
    const verdict = { code: "deja_decidee", detail: "La demande d1 est déjà traitée (executee) : rien n'a été refait.", statut: "executee" };
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp({ ok: true, result: { ok: true, resultat: { accepte: false, verdict }, rejoue: false } }));

    const rapport = await vidangeurDe(depot, fetchImpl).vidangerFileSortante();

    expect(rapport.echecsPermanents).toEqual([{ id: persistee.id, verdict: { code: "deja_decidee", detail: verdict.detail } }]);
    expect(rapport.resultatsAcceptes).toEqual([]);
    expect((await depot.obtenir(persistee.id))?.statut).toBe("echec_permanent");
  });

  test("accusé illisible : échec permanent qui dit de revérifier la liste, jamais un succès", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationDecision("d1", "approuver", "", idDeterministe, HORLOGE));
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp({ ok: true, result: { ok: true, resultat: { accepte: true, resultat: { statut: "?" } } } }));

    const rapport = await vidangeurDe(depot, fetchImpl).vidangerFileSortante();

    expect(rapport.resultatsAcceptes).toEqual([]);
    expect(rapport.echecsPermanents[0].id).toBe(persistee.id);
    expect(rapport.echecsPermanents[0].verdict.code).toBe("reponse_illisible");
  });

  test("une décision en file empêche d'en proposer une seconde pour la même demande", async () => {
    const depot = new DepotOutboxMemoire();
    await deposer(depot, creerMutationDecision("d1", "refuser", "", idDeterministe, HORLOGE));

    const enFile = decisionsEnFile(await depot.lister());

    expect(enFile.get("d1")).toMatchObject({ decision: "refuser", statut: "en_attente" });
  });
});

describe("accuseDepuisResume", () => {
  const base = { demandeId: "d1", decision: "approuver", statut: "executee" };

  test("un accusé bien formé est rendu tel quel", () => {
    expect(accuseDepuisResume(base)).toBe(base as unknown);
  });

  test.each([null, undefined, "texte", 5, {}, { ...base, statut: "en_cours" }, { ...base, decision: "annuler" }, { ...base, demandeId: 1 }])(
    "forme inattendue %p -> null, jamais affiché comme fait",
    (resume) => {
      expect(accuseDepuisResume(resume)).toBeNull();
    },
  );
});

function accuse(surcharge: Partial<AccuseDecision> = {}): AccuseDecision {
  return {
    demandeId: "d1",
    decision: "approuver",
    statut: "executee",
    outil: "m9_etat_consolide",
    departement: "m09-strategic-intelligence",
    niveau: "N3",
    decidePar: "proprio.fictif",
    role: "nathan_owner",
    decideLe: "2026-09-28T14:05:00+00:00",
    issue: { ok: true, accepte: true, verdict: null, erreur: null, details: null },
    ...surcharge,
  };
}

describe("issueAffichee", () => {
  test("refus -> refusee", () => {
    expect(issueAffichee(accuse({ decision: "refuser", statut: "refusee", issue: null }))).toEqual({ genre: "refusee" });
  });

  test("approbation exécutée -> executee", () => {
    expect(issueAffichee(accuse())).toEqual({ genre: "executee" });
  });

  test("approbation dont l'outil a refusé sur le fond : PAS présentée comme faite, verdict conservé", () => {
    const verdict = { code: "REJ-X", detail: "snapshot refusé" };
    expect(issueAffichee(accuse({ issue: { ok: true, accepte: false, verdict, erreur: null, details: null } }))).toEqual({
      genre: "executee_refusee_par_l_outil",
      verdict,
    });
  });

  test("exécution en échec -> echec_execution avec l'erreur et les détails", () => {
    expect(
      issueAffichee(accuse({ statut: "echec", issue: { ok: false, accepte: null, verdict: null, erreur: "refus_metier", details: "valeur négative" } })),
    ).toEqual({ genre: "echec_execution", detail: "refus_metier : valeur négative" });
    expect(issueAffichee(accuse({ statut: "echec", issue: null }))).toEqual({ genre: "echec_execution", detail: "" });
  });
});

describe("formaterArguments", () => {
  test("un texte tel quel, tout le reste en JSON, l'ordre du serveur, rien d'abrégé", () => {
    const long = "x".repeat(1400);
    expect(formaterArguments({ decision: "verifiee", horodatage: long, n: 3, actif: true, vide: null, snapshot: { a: ["1"] } })).toEqual([
      { cle: "decision", valeur: "verifiee" },
      { cle: "horodatage", valeur: long },
      { cle: "n", valeur: "3" },
      { cle: "actif", valeur: "true" },
      { cle: "vide", valeur: "null" },
      { cle: "snapshot", valeur: '{"a":["1"]}' },
    ]);
  });

  test("aucun argument -> aucune ligne", () => {
    expect(formaterArguments({})).toEqual([]);
  });
});

describe("formaterDepuis", () => {
  test("heure locale de l'appareil (décalage injecté), AAAA-MM-JJ HH:MM", () => {
    expect(formaterDepuis("2026-09-28T18:32:00+00:00", -240)).toBe("2026-09-28 14:32");
    expect(formaterDepuis("2026-09-28T02:05:59Z", -240)).toBe("2026-09-27 22:05");
    expect(formaterDepuis("2026-09-28T14:32:00-04:00", 0)).toBe("2026-09-28 18:32");
  });

  test("horodatage illisible : rendu tel quel, jamais une date inventée", () => {
    expect(formaterDepuis("hier soir", -240)).toBe("hier soir");
    expect(formaterDepuis("", -240)).toBe("");
  });
});

describe("cohérence de l'écran avec l'outbox", () => {
  test("approval_decision a son descripteur, et son chantier n'est pas un chantier", () => {
    expect(DESCRIPTEURS_MUTATION.get("approval_decision")?.tool).toBe("m9_decider_demande_approbation");
    expect(CHANTIER_ID_APPROBATIONS).toBe("approbations");
  });

  test("une mutation de décision soumise est bien envoyable (pas un brouillon)", () => {
    const brouillon = creerMutation({ type: "approval_decision", chantierId: CHANTIER_ID_APPROBATIONS, payload: {} }, idDeterministe, HORLOGE);
    expect(soumettreMutation(brouillon).statut).toBe("en_attente");
  });
});

describe("vueAttentes", () => {
  const attente: AttenteDepartement = {
    type: "completion_en_revue",
    id: "int-1",
    departement: "m04-field-ops",
    departementNom: "Field Ops",
    resume: "Complétion en revue (int-1) — écart matériaux CRITIQUE signalé par M6 (seuil 0.3)",
    niveau: "N4",
    depuis: "2026-09-16T11:00:00-04:00",
    actionProposee: "m4_resoudre_revue_completion : verifiee ou correction",
  };
  const vide: AttentesDepartements = {
    items: [],
    total: 0,
    reste: 0,
    decalage: 0,
    suivant: null,
    illisibles: 0,
    departementsIllisibles: [],
  };

  test("le moteur n'en donne pas : inconnues (l'écran ne dit rien, il ne sait pas)", () => {
    expect(vueAttentes(null)).toEqual({ genre: "inconnues" });
  });

  test("le serveur dit aucune et tous les départements ont répondu : aucune", () => {
    expect(vueAttentes(vide)).toEqual({ genre: "aucune" });
  });

  test("des attentes : présentes, telles quelles, sans reclassement", () => {
    const vue = vueAttentes({ ...vide, items: [attente], total: 1 });
    expect(vue).toEqual({
      genre: "presentes",
      items: [attente],
      reste: 0,
      suivant: null,
      illisibles: 0,
      departementsIllisibles: [],
    });
  });

  test("la page suivante à demander est celle du serveur, jamais calculée ici", () => {
    const vue = vueAttentes({ ...vide, items: [attente], total: 4, reste: 3, suivant: 1 });
    expect(vue).toMatchObject({ genre: "presentes", reste: 3, suivant: 1 });
  });

  test.each([
    ["des attentes non affichées", { reste: 2, total: 2 }],
    ["des éléments illisibles", { illisibles: 1, total: 1 }],
    ["un département dont les attentes sont illisibles", { departementsIllisibles: ["m05-financecore"] }],
  ])("jamais « aucune » avec %s", (_nom, surcharge) => {
    const vue = vueAttentes({ ...vide, ...surcharge });
    expect(vue.genre).toBe("presentes");
  });
});

// -- « Voir plus » : la lecture des attentes page par page (PLAN T1.5-e) -------------------------------------------
function uneAttente(numero: number, surcharge: Partial<AttenteDepartement> = {}): AttenteDepartement {
  return {
    type: "besoin_commande",
    id: `besoin_commande:article-${String(numero).padStart(2, "0")}`,
    departement: "m06-material-control",
    departementNom: "Material Control",
    resume: `Stock bas : article-${numero}`,
    niveau: "N2",
    depuis: `2026-09-${String(numero + 1).padStart(2, "0")}T15:00:00+00:00`,
    actionProposee: "Créer un bon de commande (jamais seul)",
    ...surcharge,
  };
}

function pageDAttentes(surcharge: Partial<AttentesDepartements>): AttentesDepartements {
  return {
    items: [],
    total: 0,
    reste: 0,
    decalage: 0,
    suivant: null,
    illisibles: 0,
    departementsIllisibles: [],
    ...surcharge,
  };
}

describe("fusionnerPageAttentes", () => {
  const premiere = pageDAttentes({ items: [uneAttente(0), uneAttente(1)], total: 5, reste: 3, decalage: 0, suivant: 2 });

  test("la page demandée est recollée à la suite, dans l'ordre du serveur", () => {
    const page = pageDAttentes({ items: [uneAttente(2), uneAttente(3)], total: 5, reste: 1, decalage: 2, suivant: 4 });

    const fusion = fusionnerPageAttentes(premiere, page);

    expect(fusion).toEqual({
      genre: "fusionnee",
      attentes: {
        items: [uneAttente(0), uneAttente(1), uneAttente(2), uneAttente(3)],
        total: 5,
        reste: 1,
        decalage: 0,
        suivant: 4,
        illisibles: 0,
        departementsIllisibles: [],
      },
    });
  });

  test("la dernière page ferme la lecture : plus rien à demander", () => {
    const page = pageDAttentes({ items: [uneAttente(2)], total: 3, reste: 0, decalage: 2, suivant: null });

    const fusion = fusionnerPageAttentes({ ...premiere, total: 3, reste: 1 }, page);

    expect(fusion).toMatchObject({ genre: "fusionnee", attentes: { reste: 0, suivant: null } });
    if (fusion.genre === "fusionnee") {
      expect(vueAttentes(fusion.attentes)).toMatchObject({ genre: "presentes", suivant: null, reste: 0 });
    }
  });

  test("les attentes illisibles s'additionnent et les départements muets ne s'oublient pas", () => {
    const lues = { ...premiere, illisibles: 1, departementsIllisibles: ["m05-financecore"] };
    const page = pageDAttentes({
      items: [uneAttente(3)],
      total: 5,
      reste: 0,
      decalage: 2,
      suivant: null,
      illisibles: 2,
      departementsIllisibles: ["m05-financecore", "m04-field-ops"],
    });

    const fusion = fusionnerPageAttentes(lues, page);

    expect(fusion).toMatchObject({
      genre: "fusionnee",
      attentes: { illisibles: 3, departementsIllisibles: ["m05-financecore", "m04-field-ops"] },
    });
  });

  test("le total a changé entre deux pages : les rangs ont glissé, la liste est relue depuis le début", () => {
    const page = pageDAttentes({ items: [uneAttente(2)], total: 4, reste: 1, decalage: 2, suivant: 3 });
    expect(fusionnerPageAttentes(premiere, page)).toEqual({ genre: "a_relire", raison: "liste_changee" });
  });

  test("une attente déjà affichée revient dans la page : relue, jamais montrée deux fois", () => {
    const page = pageDAttentes({ items: [uneAttente(1), uneAttente(3)], total: 5, reste: 1, decalage: 2, suivant: 4 });
    expect(fusionnerPageAttentes(premiere, page)).toEqual({ genre: "a_relire", raison: "liste_changee" });
  });

  test("une attente de même id mais d'un autre département n'est pas la même attente", () => {
    const autre = uneAttente(1, { departement: "m05-financecore", type: "facture_brouillon" });
    const page = pageDAttentes({ items: [autre], total: 5, reste: 2, decalage: 2, suivant: 3 });
    expect(cleAttente(autre)).not.toBe(cleAttente(uneAttente(1)));
    expect(fusionnerPageAttentes(premiere, page)).toMatchObject({ genre: "fusionnee" });
  });

  test.each([
    ["le serveur rend un autre rang que celui demandé", pageDAttentes({ items: [uneAttente(3)], total: 5, reste: 1, decalage: 3, suivant: 4 })],
    ["le serveur répond la même page : la lecture ne progresse pas", pageDAttentes({ items: [uneAttente(2)], total: 5, reste: 2, decalage: 2, suivant: 2 })],
    ["le serveur remonte en arrière", pageDAttentes({ items: [uneAttente(2)], total: 5, reste: 2, decalage: 2, suivant: 1 })],
    ["la réponse n'a plus d'attentes lisibles", null],
  ])("réponse incohérente, relue depuis le début : %s", (_nom, page) => {
    expect(fusionnerPageAttentes(premiere, page)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("sans page suivante à demander, il n'y a rien à recoller", () => {
    const page = pageDAttentes({ items: [uneAttente(2)], total: 5, reste: 2, decalage: 2, suivant: 3 });
    expect(fusionnerPageAttentes({ ...premiere, suivant: null }, page)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });
});

describe("chargerSuiteAttentes", () => {
  /** Un serveur fictif qui pagine comme le moteur : `taillePage` attentes par page, dans l'ordre donné. */
  function serveurFictif(attentes: readonly AttenteDepartement[], taillePage: number) {
    const decalagesDemandes: number[] = [];
    const argsRecus: unknown[] = [];
    const corps = (decalage: number) => {
      const page = attentes.slice(decalage, decalage + taillePage);
      const apres = Math.min(attentes.length, decalage + page.length);
      return {
        ok: true,
        resultat: {
          accepte: true,
          resultat: {
            demandes: [],
            total_en_attente: 0,
            affichees: 0,
            reste: 0,
            proprietaire: true,
            attentes: page.map((a) => ({
              type: a.type,
              id: a.id,
              departement: a.departement,
              departement_nom: a.departementNom,
              resume: a.resume,
              niveau: a.niveau,
              depuis: a.depuis,
              action_proposee: a.actionProposee,
            })),
            total_attentes: attentes.length,
            attentes_affichees: page.length,
            attentes_reste: attentes.length - apres,
            attentes_decalage: decalage,
            attentes_suivant: apres < attentes.length ? apres : null,
            attentes_illisibles: [],
          },
        },
      };
    };
    const chargeur = creerChargeurApprobations({
      appelerOutil: async (params: ParametresAppelOutil) => {
        const args = params.requete.args as { decalage_attentes?: number };
        argsRecus.push(args);
        const decalage = args.decalage_attentes ?? 0;
        decalagesDemandes.push(decalage);
        return { ok: true, result: corps(decalage) };
      },
      fetchImpl: jest.fn() as unknown as typeof fetch,
      urlBase: "https://grs.exemple.ca",
      jeton: "jeton-test",
    });
    const premierePage = async (): Promise<AttentesDepartements> => {
      const resultat = await chargeur.chargerDemandes();
      if (resultat.source !== "serveur" || resultat.liste.attentes === null) {
        throw new Error("première page illisible");
      }
      return resultat.liste.attentes;
    };
    return { chargeur, premierePage, decalagesDemandes, argsRecus };
  }

  const TOUTES = [0, 1, 2, 3, 4, 5, 6, 7].map((n) => uneAttente(n));

  test("toutes les attentes se lisent page après page, chacune une seule fois, dans l'ordre", async () => {
    const serveur = serveurFictif(TOUTES, 3);
    let lues = await serveur.premierePage();
    expect(lues.items).toHaveLength(3);
    expect(lues).toMatchObject({ total: 8, reste: 5, decalage: 0, suivant: 3 });

    let pages = 1;
    while (lues.suivant !== null) {
      const suite = await chargerSuiteAttentes(lues, (options) => serveur.chargeur.chargerDemandes(options));
      expect(suite.genre).toBe("fusionnee");
      if (suite.genre !== "fusionnee") {
        return;
      }
      lues = suite.attentes;
      pages += 1;
      expect(pages).toBeLessThan(10);
    }

    expect(lues.items.map(cleAttente)).toEqual(TOUTES.map(cleAttente));
    expect(new Set(lues.items.map(cleAttente)).size).toBe(8);
    expect(lues).toMatchObject({ total: 8, reste: 0, suivant: null, illisibles: 0 });
    // Le rang demandé est celui que le serveur a donné ; la première page part sans argument.
    expect(serveur.argsRecus).toEqual([{}, { decalage_attentes: 3 }, { decalage_attentes: 6 }]);
  });

  test("rien ne suit : aucun appel, la lecture est finie", async () => {
    const serveur = serveurFictif(TOUTES.slice(0, 2), 3);
    const lues = await serveur.premierePage();
    const appels = jest.fn();

    const suite = await chargerSuiteAttentes(lues, appels);

    expect(lues.suivant).toBeNull();
    expect(suite).toEqual({ genre: "sans_suite" });
    expect(appels).not.toHaveBeenCalled();
  });

  test("hors ligne : l'échec est dit, ce qui est affiché reste, rien n'est inventé", async () => {
    const serveur = serveurFictif(TOUTES, 3);
    const lues = await serveur.premierePage();
    const copie = JSON.stringify(lues);

    const suite = await chargerSuiteAttentes(lues, async () => ({
      source: "aucune",
      raison: { code: "erreur_reseau", detail: "Network request failed" },
    }));

    expect(suite).toEqual({ genre: "echec", verdict: { code: "erreur_reseau", detail: "Network request failed" } });
    expect(JSON.stringify(lues)).toBe(copie);
  });

  test("appareil non apparié : dit comme pour la liste", async () => {
    const serveur = serveurFictif(TOUTES, 3);
    const lues = await serveur.premierePage();

    expect(await chargerSuiteAttentes(lues, async () => null)).toEqual({ genre: "sans_appairage" });
  });

  test("une attente traitée entre deux pages : le total change, la liste est relue depuis le début", async () => {
    const avant = serveurFictif(TOUTES, 3);
    const lues = await avant.premierePage();
    const apres = serveurFictif(TOUTES.slice(1), 3); // la plus ancienne a été traitée entre-temps

    const suite = await chargerSuiteAttentes(lues, (options) => apres.chargeur.chargerDemandes(options));

    expect(suite).toEqual({ genre: "a_relire", raison: "liste_changee" });
  });

  test("le serveur répond une page illisible : verdict du chargeur, jamais une page vide qui dirait « fini »", async () => {
    const serveur = serveurFictif(TOUTES, 3);
    const lues = await serveur.premierePage();
    const chargeur = creerChargeurApprobations({
      appelerOutil: async () => ({ ok: true, result: { ok: true, resultat: "?" } }),
      fetchImpl: jest.fn() as unknown as typeof fetch,
      urlBase: "https://grs.exemple.ca",
      jeton: "jeton-test",
    });

    const suite = await chargerSuiteAttentes(lues, (options) => chargeur.chargerDemandes(options));

    expect(suite).toMatchObject({ genre: "echec", verdict: { code: "reponse_illisible" } });
  });

  test("un moteur plus ancien ne pagine pas : pas de « Voir plus », le reste est seulement compté", () => {
    const brut = {
      ok: true,
      resultat: {
        accepte: true,
        resultat: {
          demandes: [],
          total_en_attente: 0,
          affichees: 0,
          reste: 0,
          proprietaire: true,
          attentes: [],
          total_attentes: 5,
          attentes_affichees: 0,
          attentes_reste: 5,
          attentes_illisibles: [],
        },
      },
    };
    const interpretation = interpreterResultatListerDemandes(brut);
    expect(interpretation.ok).toBe(true);
    if (!interpretation.ok) {
      return;
    }
    expect(interpretation.liste.attentes).toMatchObject({ decalage: 0, suivant: null, reste: 5 });
    expect(vueAttentes(interpretation.liste.attentes)).toMatchObject({ genre: "presentes", suivant: null, reste: 5 });
  });
});
