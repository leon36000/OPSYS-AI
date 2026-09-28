import { ajouterItem, basculerItem, checklistTerminee, retirerItem } from "./logique";
import type { ItemChecklist } from "./types";

describe("ajouterItem", () => {
  test("ajoute un item non fait, avec l'id fourni et le texte nettoyé", () => {
    expect(ajouterItem([], "id-1", "  Vérifier l'alignement  ")).toEqual([
      { id: "id-1", texte: "Vérifier l'alignement", fait: false },
    ]);
  });

  test("texte vide ou blanc -> rien n'est ajouté (fail-closed)", () => {
    expect(ajouterItem([], "id-1", "")).toEqual([]);
    expect(ajouterItem([], "id-1", "   ")).toEqual([]);
  });

  test("ne mute jamais la liste reçue", () => {
    const items: ItemChecklist[] = [{ id: "a", texte: "A", fait: false }];
    ajouterItem(items, "b", "B");
    expect(items).toEqual([{ id: "a", texte: "A", fait: false }]);
  });
});

describe("basculerItem", () => {
  test("inverse fait pour l'id ciblé, laisse les autres intacts", () => {
    const items: ItemChecklist[] = [
      { id: "a", texte: "A", fait: false },
      { id: "b", texte: "B", fait: false },
    ];
    expect(basculerItem(items, "a")).toEqual([
      { id: "a", texte: "A", fait: true },
      { id: "b", texte: "B", fait: false },
    ]);
  });

  test("id inconnu -> liste inchangée, jamais une erreur", () => {
    const items: ItemChecklist[] = [{ id: "a", texte: "A", fait: false }];
    expect(basculerItem(items, "inconnu")).toEqual(items);
  });

  test("bascule deux fois = retour à l'état initial", () => {
    const items: ItemChecklist[] = [{ id: "a", texte: "A", fait: false }];
    expect(basculerItem(basculerItem(items, "a"), "a")).toEqual(items);
  });
});

describe("retirerItem", () => {
  test("retire l'item ciblé", () => {
    const items: ItemChecklist[] = [
      { id: "a", texte: "A", fait: false },
      { id: "b", texte: "B", fait: true },
    ];
    expect(retirerItem(items, "a")).toEqual([{ id: "b", texte: "B", fait: true }]);
  });

  test("id inconnu -> liste inchangée", () => {
    const items: ItemChecklist[] = [{ id: "a", texte: "A", fait: false }];
    expect(retirerItem(items, "inconnu")).toEqual(items);
  });
});

describe("checklistTerminee", () => {
  test("liste vide -> jamais terminée", () => {
    expect(checklistTerminee([])).toBe(false);
  });

  test("au moins un item non fait -> pas terminée", () => {
    expect(
      checklistTerminee([
        { id: "a", texte: "A", fait: true },
        { id: "b", texte: "B", fait: false },
      ]),
    ).toBe(false);
  });

  test("tous les items faits et liste non vide -> terminée", () => {
    expect(
      checklistTerminee([
        { id: "a", texte: "A", fait: true },
        { id: "b", texte: "B", fait: true },
      ]),
    ).toBe(true);
  });
});
