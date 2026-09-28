import { identifierMutationsAReprendre, selectionnerProchainesEnvoyables } from "./planification";
import type { MutationOutbox } from "./types";

function m(partiel: Partial<MutationOutbox> & Pick<MutationOutbox, "id">): MutationOutbox {
  return {
    type: "punch_in",
    chantierId: "chantier-1",
    payload: {},
    dependsOn: null,
    statut: "en_attente",
    tentatives: 0,
    createdAtLocal: "2026-01-15T08:00:00-05:00",
    ...partiel,
  };
}

describe("selectionnerProchainesEnvoyables", () => {
  test("ignore brouillon, envoyee et echec_permanent", () => {
    const mutations = [
      m({ id: "a", statut: "brouillon" }),
      m({ id: "b", statut: "envoyee" }),
      m({ id: "c", statut: "echec_permanent" }),
    ];
    expect(selectionnerProchainesEnvoyables(mutations)).toEqual([]);
  });

  test("inclut en_attente et envoi (reprise)", () => {
    const mutations = [m({ id: "a", statut: "en_attente" }), m({ id: "b", statut: "envoi" })];
    const resultat = selectionnerProchainesEnvoyables(mutations);
    expect(resultat.map((x) => x.id).sort()).toEqual(["a", "b"]);
  });

  test("une mutation avec dependsOn attend que la parente soit envoyee", () => {
    const parenteEnAttente = m({ id: "parent", statut: "en_attente" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(selectionnerProchainesEnvoyables([parenteEnAttente, enfant]).map((x) => x.id)).toEqual(["parent"]);
  });

  test("l'enfant devient envoyable une fois la parente envoyee", () => {
    const parenteEnvoyee = m({ id: "parent", statut: "envoyee" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(selectionnerProchainesEnvoyables([parenteEnvoyee, enfant]).map((x) => x.id)).toEqual(["enfant"]);
  });

  test("dependsOn vers une parente en echec_permanent reste bloqué (jamais envoyé avant la parente)", () => {
    const parenteBloquee = m({ id: "parent", statut: "echec_permanent" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(selectionnerProchainesEnvoyables([parenteBloquee, enfant])).toEqual([]);
  });

  test("trie par chantier puis par heure de création (FIFO par chantier)", () => {
    const mutations = [
      m({ id: "b2", chantierId: "B", createdAtLocal: "2026-01-15T09:00:00-05:00" }),
      m({ id: "a1", chantierId: "A", createdAtLocal: "2026-01-15T08:00:00-05:00" }),
      m({ id: "b1", chantierId: "B", createdAtLocal: "2026-01-15T08:00:00-05:00" }),
      m({ id: "a2", chantierId: "A", createdAtLocal: "2026-01-15T09:00:00-05:00" }),
    ];
    expect(selectionnerProchainesEnvoyables(mutations).map((x) => x.id)).toEqual(["a1", "a2", "b1", "b2"]);
  });

  test("ne modifie pas le tableau reçu", () => {
    const mutations = [m({ id: "a" }), m({ id: "b" })];
    const copie = [...mutations];
    selectionnerProchainesEnvoyables(mutations);
    expect(mutations).toEqual(copie);
  });

  test("liste vide -> liste vide", () => {
    expect(selectionnerProchainesEnvoyables([])).toEqual([]);
  });
});

describe("identifierMutationsAReprendre", () => {
  test("isole uniquement les mutations en statut envoi", () => {
    const mutations = [
      m({ id: "a", statut: "en_attente" }),
      m({ id: "b", statut: "envoi" }),
      m({ id: "c", statut: "envoyee" }),
    ];
    expect(identifierMutationsAReprendre(mutations).map((x) => x.id)).toEqual(["b"]);
  });

  test("une mutation reprise garde le même id (jamais recréée)", () => {
    const original = m({ id: "meme-id", statut: "envoi" });
    const [reprise] = identifierMutationsAReprendre([original]);
    expect(reprise.id).toBe("meme-id");
    expect(reprise).toBe(original); // même référence : aucune recréation, même partielle
  });

  test("aucune reprise -> liste vide", () => {
    expect(identifierMutationsAReprendre([m({ id: "a", statut: "en_attente" })])).toEqual([]);
  });
});
