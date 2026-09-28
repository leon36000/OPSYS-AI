import {
  ErreurTransitionInterdite,
  creerMutation,
  formaterHorodatageLocal,
  marquerEchecPermanent,
  marquerEchecReessayable,
  marquerEnvoi,
  marquerEnvoyee,
  soumettreMutation,
} from "./mutation";
import type { MutationOutbox } from "./types";

const HORLOGE_MONTREAL_EN_HIVER = { maintenant: new Date("2026-01-15T16:32:00.000Z"), decalageMinutesUTC: -300 };
let compteurId = 0;
const idDeterministe = () => `mutation-test-${++compteurId}`;

beforeEach(() => {
  compteurId = 0;
});

describe("formaterHorodatageLocal", () => {
  test("applique le décalage négatif (EST, UTC-5) et n'émet jamais 'Z'", () => {
    expect(formaterHorodatageLocal(HORLOGE_MONTREAL_EN_HIVER)).toBe("2026-01-15T11:32:00-05:00");
  });

  test("applique un décalage positif", () => {
    expect(
      formaterHorodatageLocal({ maintenant: new Date("2026-01-15T16:32:00.000Z"), decalageMinutesUTC: 60 }),
    ).toBe("2026-01-15T17:32:00+01:00");
  });

  test("décalage nul -> signe '+' et heure inchangée", () => {
    expect(
      formaterHorodatageLocal({ maintenant: new Date("2026-01-15T16:32:00.000Z"), decalageMinutesUTC: 0 }),
    ).toBe("2026-01-15T16:32:00+00:00");
  });
});

describe("creerMutation", () => {
  test("statut brouillon, 0 tentative, id fourni par l'appelant", () => {
    const mutation = creerMutation(
      { type: "punch_in", chantierId: "chantier-1", payload: { note: "arrivée" } },
      idDeterministe,
      HORLOGE_MONTREAL_EN_HIVER,
    );
    expect(mutation).toEqual<MutationOutbox>({
      id: "mutation-test-1",
      type: "punch_in",
      chantierId: "chantier-1",
      payload: { note: "arrivée" },
      dependsOn: null,
      statut: "brouillon",
      tentatives: 0,
      createdAtLocal: "2026-01-15T11:32:00-05:00",
    });
  });

  test("dependsOn omis -> null (jamais undefined, pour matcher la colonne SQLite nullable)", () => {
    const mutation = creerMutation(
      { type: "checklist_step", chantierId: "c1", payload: {} },
      idDeterministe,
      HORLOGE_MONTREAL_EN_HIVER,
    );
    expect(mutation.dependsOn).toBeNull();
  });

  test("dependsOn explicite conservé", () => {
    const mutation = creerMutation(
      { type: "materials_submit", chantierId: "c1", payload: {}, dependsOn: "mutation-parente" },
      idDeterministe,
      HORLOGE_MONTREAL_EN_HIVER,
    );
    expect(mutation.dependsOn).toBe("mutation-parente");
  });
});

function mutationDansStatut(statut: MutationOutbox["statut"], tentatives = 0): MutationOutbox {
  return {
    id: "m1",
    type: "punch_in",
    chantierId: "c1",
    payload: {},
    dependsOn: null,
    statut,
    tentatives,
    createdAtLocal: "2026-01-15T11:32:00-05:00",
  };
}

describe("cycle de vie normal", () => {
  test("brouillon -> en_attente -> envoi -> envoyee", () => {
    let m = mutationDansStatut("brouillon");
    m = soumettreMutation(m);
    expect(m.statut).toBe("en_attente");
    m = marquerEnvoi(m);
    expect(m.statut).toBe("envoi");
    m = marquerEnvoyee(m);
    expect(m.statut).toBe("envoyee");
  });

  test("envoi -> en_attente (échec réessayable) incrémente les tentatives", () => {
    const m = marquerEchecReessayable(mutationDansStatut("envoi", 2));
    expect(m.statut).toBe("en_attente");
    expect(m.tentatives).toBe(3);
  });

  test("envoi -> echec_permanent", () => {
    const m = marquerEchecPermanent(mutationDansStatut("envoi", 5));
    expect(m.statut).toBe("echec_permanent");
    expect(m.tentatives).toBe(5); // inchangé : ce n'est pas un réessai
  });
});

describe("transitions interdites -> ErreurTransitionInterdite", () => {
  test("soumettreMutation sur une mutation déjà envoyée", () => {
    expect(() => soumettreMutation(mutationDansStatut("envoyee"))).toThrow(ErreurTransitionInterdite);
  });

  test("marquerEnvoi sur un brouillon (doit passer par en_attente)", () => {
    expect(() => marquerEnvoi(mutationDansStatut("brouillon"))).toThrow(ErreurTransitionInterdite);
  });

  test("marquerEnvoyee sur une mutation en_attente (pas encore en envoi)", () => {
    expect(() => marquerEnvoyee(mutationDansStatut("en_attente"))).toThrow(ErreurTransitionInterdite);
  });

  test("marquerEchecPermanent sur un statut déjà terminal", () => {
    expect(() => marquerEchecPermanent(mutationDansStatut("echec_permanent"))).toThrow(ErreurTransitionInterdite);
  });

  test("le message nomme le de/vers refusés", () => {
    try {
      soumettreMutation(mutationDansStatut("envoyee"));
      throw new Error("aurait dû lever");
    } catch (erreur) {
      expect(erreur).toBeInstanceOf(ErreurTransitionInterdite);
      expect((erreur as ErreurTransitionInterdite).de).toBe("envoyee");
      expect((erreur as ErreurTransitionInterdite).vers).toBe("en_attente");
    }
  });
});

test("les fonctions de transition ne modifient pas la mutation reçue (immuabilité)", () => {
  const original = mutationDansStatut("brouillon");
  const copie = { ...original };
  soumettreMutation(original);
  expect(original).toEqual(copie);
});
