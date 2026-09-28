import {
  identifierMutationsAReprendre,
  identifierMutationsBloqueesParEchecPermanent,
  selectionnerProchainesEnvoyables,
} from "./planification";
import type { MutationOutbox } from "./types";

const MAINTENANT_REF = new Date("2026-01-15T12:00:00.000Z");

let seqAuto = 0;
beforeEach(() => {
  seqAuto = 0;
});

function m(partiel: Partial<MutationOutbox> & Pick<MutationOutbox, "id">): MutationOutbox {
  seqAuto += 1;
  return {
    sequence: seqAuto,
    type: "punch_in",
    chantierId: "chantier-1",
    payload: {},
    dependsOn: null,
    statut: "en_attente",
    tentatives: 0,
    createdAtLocal: "2026-01-15T08:00:00-05:00",
    prochaineTentativeA: null,
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
    expect(selectionnerProchainesEnvoyables(mutations, MAINTENANT_REF)).toEqual([]);
  });

  test("inclut en_attente et envoi (reprise)", () => {
    const mutations = [m({ id: "a", statut: "en_attente" }), m({ id: "b", statut: "envoi" })];
    const resultat = selectionnerProchainesEnvoyables(mutations, MAINTENANT_REF);
    expect(resultat.map((x) => x.id).sort()).toEqual(["a", "b"]);
  });

  test("une mutation avec dependsOn attend que la parente soit envoyee", () => {
    const parenteEnAttente = m({ id: "parent", statut: "en_attente" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(selectionnerProchainesEnvoyables([parenteEnAttente, enfant], MAINTENANT_REF).map((x) => x.id)).toEqual([
      "parent",
    ]);
  });

  test("l'enfant devient envoyable une fois la parente envoyee", () => {
    const parenteEnvoyee = m({ id: "parent", statut: "envoyee" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(selectionnerProchainesEnvoyables([parenteEnvoyee, enfant], MAINTENANT_REF).map((x) => x.id)).toEqual([
      "enfant",
    ]);
  });

  test("dependsOn vers une parente en echec_permanent reste bloqué (jamais envoyé avant la parente)", () => {
    const parenteBloquee = m({ id: "parent", statut: "echec_permanent" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(selectionnerProchainesEnvoyables([parenteBloquee, enfant], MAINTENANT_REF)).toEqual([]);
  });

  // Correction relecture (point 2) : l'ordre fait foi sur `sequence`, jamais sur
  // `createdAtLocal`. `createdAtLocal` est délibérément incohérent ci-dessous (pas trié dans
  // l'ordre de `sequence`) pour prouver qu'il n'intervient plus dans le tri.
  test("trie par chantier puis par sequence (jamais par createdAtLocal)", () => {
    const mutations = [
      m({ id: "b2", chantierId: "B", sequence: 4, createdAtLocal: "2026-01-15T01:00:00-05:00" }),
      m({ id: "a1", chantierId: "A", sequence: 1, createdAtLocal: "2026-01-15T23:00:00-05:00" }),
      m({ id: "b1", chantierId: "B", sequence: 3, createdAtLocal: "2026-01-15T22:00:00-05:00" }),
      m({ id: "a2", chantierId: "A", sequence: 2, createdAtLocal: "2026-01-15T02:00:00-05:00" }),
    ];
    expect(selectionnerProchainesEnvoyables(mutations, MAINTENANT_REF).map((x) => x.id)).toEqual([
      "a1",
      "a2",
      "b1",
      "b2",
    ]);
  });

  // Correction relecture (point 2), cas concret : passage à l'heure normale (1er novembre
  // 2026, -04:00 EDT -> -05:00 EST). Deux mutations créées dans le bon ordre réel (sequence 1
  // puis 2) produisent des `createdAtLocal` qui, comparés comme du texte, s'inverseraient
  // (voir mutation.test.ts). La sélection doit rester dans le bon ordre malgré ça.
  test("passage à l'heure normale (-04:00 -> -05:00) : l'ordre reste correct via sequence", () => {
    const creeeAvant = m({
      id: "avant",
      sequence: 1,
      createdAtLocal: "2026-11-01T01:45:00-04:00", // 05:45 UTC réel
    });
    const creeeApres = m({
      id: "apres",
      sequence: 2,
      createdAtLocal: "2026-11-01T01:15:00-05:00", // 06:15 UTC réel, VRAIMENT après
    });
    // La preuve du piège : trier sur le texte inverserait l'ordre réel.
    expect(creeeApres.createdAtLocal < creeeAvant.createdAtLocal).toBe(true);
    // La sélection, elle, respecte l'ordre réel de création (sequence).
    expect(selectionnerProchainesEnvoyables([creeeApres, creeeAvant], MAINTENANT_REF).map((x) => x.id)).toEqual([
      "avant",
      "apres",
    ]);
  });

  describe("recul exponentiel appliqué à la sélection (correction relecture, point 1)", () => {
    test("une en_attente dont prochaineTentativeA est future est exclue", () => {
      const pasEncoreDue = m({
        id: "a",
        prochaineTentativeA: new Date(MAINTENANT_REF.getTime() + 5_000).toISOString(),
      });
      expect(selectionnerProchainesEnvoyables([pasEncoreDue], MAINTENANT_REF)).toEqual([]);
    });

    test("une en_attente dont prochaineTentativeA est passée est incluse", () => {
      const due = m({
        id: "a",
        prochaineTentativeA: new Date(MAINTENANT_REF.getTime() - 5_000).toISOString(),
      });
      expect(selectionnerProchainesEnvoyables([due], MAINTENANT_REF).map((x) => x.id)).toEqual(["a"]);
    });

    test("une en_attente dont prochaineTentativeA est exactement maintenant est incluse (bornes incluses)", () => {
      const due = m({ id: "a", prochaineTentativeA: MAINTENANT_REF.toISOString() });
      expect(selectionnerProchainesEnvoyables([due], MAINTENANT_REF).map((x) => x.id)).toEqual(["a"]);
    });

    test("prochaineTentativeA nulle -> toujours due (jamais encore échouée)", () => {
      const jamaisEchouee = m({ id: "a", prochaineTentativeA: null });
      expect(selectionnerProchainesEnvoyables([jamaisEchouee], MAINTENANT_REF).map((x) => x.id)).toEqual(["a"]);
    });

    test("une reprise (statut envoi) est due même si prochaineTentativeA est future", () => {
      const repriseAvecReculFutur = m({
        id: "a",
        statut: "envoi",
        prochaineTentativeA: new Date(MAINTENANT_REF.getTime() + 30_000).toISOString(),
      });
      expect(selectionnerProchainesEnvoyables([repriseAvecReculFutur], MAINTENANT_REF).map((x) => x.id)).toEqual([
        "a",
      ]);
    });
  });

  test("ne modifie pas le tableau reçu", () => {
    const mutations = [m({ id: "a" }), m({ id: "b" })];
    const copie = [...mutations];
    selectionnerProchainesEnvoyables(mutations, MAINTENANT_REF);
    expect(mutations).toEqual(copie);
  });

  test("liste vide -> liste vide", () => {
    expect(selectionnerProchainesEnvoyables([], MAINTENANT_REF)).toEqual([]);
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

// Correction relecture (point 3) : R12 §4, « ne jamais perdre silencieusement un événement mis
// en file ». Un descendant d'une mutation en echec_permanent restait en_attente pour toujours,
// sans que rien ne le signale.
describe("identifierMutationsBloqueesParEchecPermanent", () => {
  test("chaîne à trois niveaux : le petit-enfant est bloqué par le GRAND-parent, pas seulement le parent direct", () => {
    const grandParent = m({ id: "grand-parent", statut: "echec_permanent" });
    // Le parent direct n'est PAS lui-même en échec permanent — juste coincé en_attente.
    const parent = m({ id: "parent", statut: "en_attente", dependsOn: "grand-parent" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });

    const bloquees = identifierMutationsBloqueesParEchecPermanent([grandParent, parent, enfant]);

    expect(bloquees.map((x) => x.id).sort()).toEqual(["enfant", "parent"]);
  });

  test("une mutation sans dependsOn n'est jamais bloquée", () => {
    const autonome = m({ id: "a", statut: "en_attente", dependsOn: null });
    expect(identifierMutationsBloqueesParEchecPermanent([autonome])).toEqual([]);
  });

  test("une mutation dont la parente est envoyee n'est pas bloquée", () => {
    const parenteOk = m({ id: "parent", statut: "envoyee" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(identifierMutationsBloqueesParEchecPermanent([parenteOk, enfant])).toEqual([]);
  });

  test("une mutation dont la parente est en_attente (pas encore envoyee, pas en échec) n'est pas bloquée", () => {
    const parenteEnCours = m({ id: "parent", statut: "en_attente" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "parent" });
    expect(identifierMutationsBloqueesParEchecPermanent([parenteEnCours, enfant])).toEqual([]);
  });

  test("une parente inconnue (pas chargée) n'est pas déclarée bloquante ici", () => {
    const orphelin = m({ id: "enfant", statut: "en_attente", dependsOn: "parent-absente" });
    expect(identifierMutationsBloqueesParEchecPermanent([orphelin])).toEqual([]);
  });

  test("le déclencheur lui-même (echec_permanent) n'apparaît pas dans le résultat", () => {
    const grandParent = m({ id: "grand-parent", statut: "echec_permanent" });
    const enfant = m({ id: "enfant", statut: "en_attente", dependsOn: "grand-parent" });
    const bloquees = identifierMutationsBloqueesParEchecPermanent([grandParent, enfant]);
    expect(bloquees.map((x) => x.id)).toEqual(["enfant"]);
  });

  test("une mutation déjà envoyee ou brouillon n'est pas listée même avec un ancêtre en échec permanent", () => {
    const grandParent = m({ id: "grand-parent", statut: "echec_permanent" });
    const parent = m({ id: "parent", statut: "en_attente", dependsOn: "grand-parent" });
    const enfantDejaEnvoyee = m({ id: "enfant-envoyee", statut: "envoyee", dependsOn: "parent" });
    const enfantBrouillon = m({ id: "enfant-brouillon", statut: "brouillon", dependsOn: "parent" });

    const bloquees = identifierMutationsBloqueesParEchecPermanent([
      grandParent,
      parent,
      enfantDejaEnvoyee,
      enfantBrouillon,
    ]);

    expect(bloquees.map((x) => x.id)).toEqual(["parent"]);
  });

  test("une mutation en statut envoi peut aussi être signalée bloquée (défensif)", () => {
    const grandParent = m({ id: "grand-parent", statut: "echec_permanent" });
    const parent = m({ id: "parent", statut: "envoi", dependsOn: "grand-parent" });
    expect(identifierMutationsBloqueesParEchecPermanent([grandParent, parent]).map((x) => x.id)).toEqual(["parent"]);
  });

  test("liste vide -> liste vide", () => {
    expect(identifierMutationsBloqueesParEchecPermanent([])).toEqual([]);
  });
});
