import { ecrireChecklist, lireChecklist } from "./cache";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { ItemChecklist } from "./types";

const ITEMS: ItemChecklist[] = [
  { id: "a", texte: "Vérifier l'alignement", fait: true },
  { id: "b", texte: "Sceller les joints", fait: false },
];

describe("lireChecklist / ecrireChecklist", () => {
  test("aller-retour pour un chantier", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireChecklist(depot, "I1", ITEMS);
    expect(await lireChecklist(depot, "I1")).toEqual(ITEMS);
  });

  test("rien encore écrit -> liste vide", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await lireChecklist(depot, "I1")).toEqual([]);
  });

  test("chaque chantier a sa propre clé, jamais de mélange", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireChecklist(depot, "I1", ITEMS);
    await ecrireChecklist(depot, "I2", []);
    expect(await lireChecklist(depot, "I1")).toEqual(ITEMS);
    expect(await lireChecklist(depot, "I2")).toEqual([]);
  });

  test("valeur corrompue -> liste vide, fail-closed", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("checklist_I1_v1", "pas du JSON");
    expect(await lireChecklist(depot, "I1")).toEqual([]);
  });

  test("forme reconnaissable mais item invalide -> liste vide", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("checklist_I1_v1", JSON.stringify([{ id: "a", texte: "A" }]));
    expect(await lireChecklist(depot, "I1")).toEqual([]);
  });
});
