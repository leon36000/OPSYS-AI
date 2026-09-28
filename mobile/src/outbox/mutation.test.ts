import { calculerProchaineTentativeA } from "./recul";
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

  // Correction relecture (point 2) : `createdAtLocal` traverse le passage à l'heure normale
  // (Amérique du Nord, -04:00 EDT -> -05:00 EST, 1er novembre 2026) sans jamais servir à
  // trier — voir planification.test.ts pour la preuve que `sequence` reste correcte pendant ce
  // même passage, là où comparer ces deux chaînes donnerait le mauvais ordre.
  test("passage à l'heure normale : deux instants réels distincts peuvent produire la même heure murale", () => {
    // Juste avant le changement (05:45 UTC, encore -04:00 EDT) : 01:45 locale.
    const avant = formaterHorodatageLocal({
      maintenant: new Date("2026-11-01T05:45:00.000Z"),
      decalageMinutesUTC: -240,
    });
    // Juste après (06:15 UTC, déjà -05:00 EST) : 01:15 locale — antérieure en apparence, mais
    // 30 minutes APRÈS en heure réelle.
    const apres = formaterHorodatageLocal({
      maintenant: new Date("2026-11-01T06:15:00.000Z"),
      decalageMinutesUTC: -300,
    });
    expect(avant).toBe("2026-11-01T01:45:00-04:00");
    expect(apres).toBe("2026-11-01T01:15:00-05:00");
    // La preuve du problème que `sequence` corrige : comparée comme un texte, "apres" (pourtant
    // postérieure en réalité) trie AVANT "avant". `createdAtLocal` ne doit donc jamais servir à
    // ordonner — seulement à afficher (ex. « pointé à 01 h 15 »).
    expect(apres < avant).toBe(true);
  });
});

describe("creerMutation", () => {
  test("statut brouillon, 0 tentative, id fourni par l'appelant, sequence et prochaineTentativeA nulles", () => {
    const mutation = creerMutation(
      { type: "punch_in", chantierId: "chantier-1", payload: { note: "arrivée" } },
      idDeterministe,
      HORLOGE_MONTREAL_EN_HIVER,
    );
    expect(mutation).toEqual<MutationOutbox>({
      id: "mutation-test-1",
      sequence: null,
      type: "punch_in",
      chantierId: "chantier-1",
      payload: { note: "arrivée" },
      dependsOn: null,
      statut: "brouillon",
      tentatives: 0,
      createdAtLocal: "2026-01-15T11:32:00-05:00",
      prochaineTentativeA: null,
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

function mutationDansStatut(
  statut: MutationOutbox["statut"],
  tentatives = 0,
  extra: Partial<Pick<MutationOutbox, "sequence" | "prochaineTentativeA">> = {},
): MutationOutbox {
  return {
    id: "m1",
    sequence: 1,
    type: "punch_in",
    chantierId: "c1",
    payload: {},
    dependsOn: null,
    statut,
    tentatives,
    createdAtLocal: "2026-01-15T11:32:00-05:00",
    prochaineTentativeA: null,
    ...extra,
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
    const maintenant = new Date("2026-01-15T12:00:00.000Z");
    const m = marquerEchecReessayable(mutationDansStatut("envoi", 2), maintenant);
    expect(m.statut).toBe("en_attente");
    expect(m.tentatives).toBe(3);
  });

  // Correction relecture (point 1) : le recul calculé doit atterrir sur la mutation, sinon la
  // sélection (planification.ts) la renvoie tout de suite.
  describe("marquerEchecReessayable pose prochaineTentativeA à partir du recul", () => {
    test("tentatives=0 avant échec -> recul de 1s", () => {
      const maintenant = new Date("2026-01-15T12:00:00.000Z");
      const m = marquerEchecReessayable(mutationDansStatut("envoi", 0), maintenant);
      expect(m.prochaineTentativeA).toBe(calculerProchaineTentativeA(0, maintenant).toISOString());
      expect(m.prochaineTentativeA).toBe("2026-01-15T12:00:01.000Z");
    });

    test("tentatives=4 avant échec -> recul de 16s (pas encore plafonné)", () => {
      const maintenant = new Date("2026-01-15T12:00:00.000Z");
      const m = marquerEchecReessayable(mutationDansStatut("envoi", 4), maintenant);
      expect(m.prochaineTentativeA).toBe("2026-01-15T12:00:16.000Z");
    });

    test("tentatives=9 avant échec -> plafonné à 30s", () => {
      const maintenant = new Date("2026-01-15T12:00:00.000Z");
      const m = marquerEchecReessayable(mutationDansStatut("envoi", 9), maintenant);
      expect(m.prochaineTentativeA).toBe("2026-01-15T12:00:30.000Z");
    });

    test("écrase une prochaineTentativeA précédente (recul recalculé à chaque échec)", () => {
      const premierEchec = marquerEchecReessayable(
        mutationDansStatut("envoi", 0),
        new Date("2026-01-15T12:00:00.000Z"),
      );
      expect(premierEchec.prochaineTentativeA).toBe("2026-01-15T12:00:01.000Z");
      const apresReenvoi = marquerEnvoi(premierEchec);
      const deuxiemeEchec = marquerEchecReessayable(apresReenvoi, new Date("2026-01-15T12:05:00.000Z"));
      expect(deuxiemeEchec.tentatives).toBe(2);
      expect(deuxiemeEchec.prochaineTentativeA).toBe("2026-01-15T12:05:02.000Z");
    });
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
