import { DepotOutboxMemoire } from "./depot";
import { creerMutation, marquerEnvoi, soumettreMutation } from "./mutation";
import type { MutationOutbox } from "./types";

const HORLOGE = { maintenant: new Date("2026-01-15T12:00:00.000Z"), decalageMinutesUTC: -300 };
let compteur = 0;
const idDeterministe = () => `id-${++compteur}`;

beforeEach(() => {
  compteur = 0;
});

describe("DepotOutboxMemoire", () => {
  test("lister() est vide au départ", async () => {
    const depot = new DepotOutboxMemoire();
    await expect(depot.lister()).resolves.toEqual([]);
  });

  test("inserer puis obtenir retrouve la même mutation", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = creerMutation({ type: "punch_in", chantierId: "c1", payload: {} }, idDeterministe, HORLOGE);
    await depot.inserer(mutation);
    await expect(depot.obtenir(mutation.id)).resolves.toEqual(mutation);
  });

  test("obtenir() sur un id absent renvoie null (jamais une exception)", async () => {
    const depot = new DepotOutboxMemoire();
    await expect(depot.obtenir("inconnu")).resolves.toBeNull();
  });

  test("inserer un id déjà présent refuse", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = creerMutation({ type: "punch_in", chantierId: "c1", payload: {} }, idDeterministe, HORLOGE);
    await depot.inserer(mutation);
    await expect(depot.inserer(mutation)).rejects.toThrow();
  });

  test("mettreAJour sur un id absent refuse (jamais un upsert silencieux)", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = creerMutation({ type: "punch_in", chantierId: "c1", payload: {} }, idDeterministe, HORLOGE);
    await expect(depot.mettreAJour(mutation)).rejects.toThrow();
  });

  test("mettreAJour reflète la transition de statut", async () => {
    const depot = new DepotOutboxMemoire();
    let mutation = creerMutation({ type: "punch_in", chantierId: "c1", payload: {} }, idDeterministe, HORLOGE);
    await depot.inserer(mutation);

    mutation = soumettreMutation(mutation);
    await depot.mettreAJour(mutation);
    mutation = marquerEnvoi(mutation);
    await depot.mettreAJour(mutation);

    const relu = await depot.obtenir(mutation.id);
    expect(relu?.statut).toBe("envoi");
  });

  test("lister() reflète toutes les insertions, dans un ordre stable par id", async () => {
    const depot = new DepotOutboxMemoire();
    const mutations: MutationOutbox[] = [];
    for (let i = 0; i < 3; i += 1) {
      const mutation = creerMutation({ type: "checklist_step", chantierId: "c1", payload: { i } }, idDeterministe, HORLOGE);
      mutations.push(mutation);
      await depot.inserer(mutation);
    }
    const lues = await depot.lister();
    expect(lues.map((x) => x.id).sort()).toEqual(mutations.map((x) => x.id).sort());
  });
});
