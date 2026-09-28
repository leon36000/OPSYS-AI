import { DepotOutboxMemoire } from "./depot";
import { creerMutation, marquerEnvoi, soumettreMutation } from "./mutation";

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

  test("inserer assigne une sequence (la mutation en mémoire l'a à null avant)", async () => {
    const depot = new DepotOutboxMemoire();
    const brouillon = creerMutation({ type: "punch_in", chantierId: "c1", payload: {} }, idDeterministe, HORLOGE);
    expect(brouillon.sequence).toBeNull();
    const persistee = await depot.inserer(brouillon);
    expect(persistee.sequence).toBe(1);
    expect(persistee).toEqual({ ...brouillon, sequence: 1 });
  });

  test("la sequence croît strictement à chaque insertion (compteur du dépôt)", async () => {
    const depot = new DepotOutboxMemoire();
    const sequences: (number | null)[] = [];
    for (let i = 0; i < 4; i += 1) {
      const mutation = creerMutation({ type: "checklist_step", chantierId: "c1", payload: { i } }, idDeterministe, HORLOGE);
      const persistee = await depot.inserer(mutation);
      sequences.push(persistee.sequence);
    }
    expect(sequences).toEqual([1, 2, 3, 4]);
  });

  test("inserer puis obtenir retrouve la mutation persistée (avec sa sequence)", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = creerMutation({ type: "punch_in", chantierId: "c1", payload: {} }, idDeterministe, HORLOGE);
    const persistee = await depot.inserer(mutation);
    await expect(depot.obtenir(mutation.id)).resolves.toEqual(persistee);
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

  test("mettreAJour reflète la transition de statut et conserve la sequence assignée", async () => {
    const depot = new DepotOutboxMemoire();
    let mutation = await depot.inserer(
      creerMutation({ type: "punch_in", chantierId: "c1", payload: {} }, idDeterministe, HORLOGE),
    );
    const sequenceAssignee = mutation.sequence;

    mutation = soumettreMutation(mutation);
    await depot.mettreAJour(mutation);
    mutation = marquerEnvoi(mutation);
    await depot.mettreAJour(mutation);

    const relu = await depot.obtenir(mutation.id);
    expect(relu?.statut).toBe("envoi");
    expect(relu?.sequence).toBe(sequenceAssignee);
  });

  test("lister() reflète toutes les insertions, triées par sequence croissante", async () => {
    const depot = new DepotOutboxMemoire();
    const ids: string[] = [];
    for (let i = 0; i < 3; i += 1) {
      const mutation = creerMutation({ type: "checklist_step", chantierId: "c1", payload: { i } }, idDeterministe, HORLOGE);
      const persistee = await depot.inserer(mutation);
      ids.push(persistee.id);
    }
    const lues = await depot.lister();
    expect(lues.map((x) => x.id)).toEqual(ids);
    expect(lues.map((x) => x.sequence)).toEqual([1, 2, 3]);
  });
});
