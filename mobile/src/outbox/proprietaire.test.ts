import { DepotOutboxMemoire } from "./depot";
import { creerMutation, marquerEnvoi, soumettreMutation } from "./mutation";
import {
  avecProprietaire,
  ErreurSansPersonneConfirmee,
  identifierEnQuarantaine,
  resumerQuarantaine,
} from "./proprietaire";
import type { MutationOutbox, StatutMutation } from "./types";

const HORLOGE = { maintenant: new Date("2026-09-29T12:00:00.000Z"), decalageMinutesUTC: -240 };
let compteur = 0;
const idDeterministe = () => `id-${++compteur}`;

beforeEach(() => {
  compteur = 0;
});

function brouillon(): MutationOutbox {
  return creerMutation({ type: "punch_in", chantierId: "c1", payload: { action: "arrivee" } }, idDeterministe, HORLOGE);
}

function mutation(id: string, statut: StatutMutation, proprietaire: string | null): MutationOutbox {
  return { ...brouillon(), id, statut, sequence: 1, proprietaire };
}

describe("avecProprietaire : chaque mutation insérée porte sa personne", () => {
  test("une mutation sans propriétaire reçoit la personne confirmée à l'instant de l'insertion", async () => {
    const base = new DepotOutboxMemoire();
    let personne: string | null = "jdupont";
    const depot = avecProprietaire(base, () => personne);

    const premiere = await depot.inserer(brouillon());
    personne = "mtremblay"; // l'appareil change de personne
    const seconde = await depot.inserer(brouillon());

    expect(premiere.proprietaire).toBe("jdupont");
    expect(seconde.proprietaire).toBe("mtremblay");
    expect((await base.obtenir(premiere.id))?.proprietaire).toBe("jdupont");
    expect(premiere.sequence).toBe(1);
  });

  test("sans personne confirmée : l'insertion échoue, rien n'est écrit (jamais une mutation orpheline)", async () => {
    const base = new DepotOutboxMemoire();
    const depot = avecProprietaire(base, () => null);

    await expect(depot.inserer(brouillon())).rejects.toBeInstanceOf(ErreurSansPersonneConfirmee);
    expect(await base.lister()).toEqual([]);
  });

  test("une personne vide n'est pas une personne", async () => {
    const depot = avecProprietaire(new DepotOutboxMemoire(), () => "  ");
    await expect(depot.inserer(brouillon())).rejects.toBeInstanceOf(ErreurSansPersonneConfirmee);
  });

  test("un propriétaire déjà posé est gardé, jamais écrasé par la personne courante", async () => {
    const depot = avecProprietaire(new DepotOutboxMemoire(), () => "mtremblay");
    const persistee = await depot.inserer({ ...brouillon(), proprietaire: "jdupont" });
    expect(persistee.proprietaire).toBe("jdupont");
  });

  test("une destination héritée explicitement inconnue n'est jamais liée à la passerelle courante", async () => {
    const depot = avecProprietaire(new DepotOutboxMemoire(), () => "jdupont", () => "https://a.fictif.invalid");
    const legacy = await depot.inserer({ ...brouillon(), proprietaire: "jdupont", destination: null });
    expect(legacy.destination).toBeNull();
    const nouvelle = await depot.inserer(brouillon());
    expect(nouvelle.destination).toBe("https://a.fictif.invalid");
  });

  test("changer de statut ne change pas le propriétaire", async () => {
    const depot = avecProprietaire(new DepotOutboxMemoire(), () => "jdupont");
    const persistee = await depot.inserer(brouillon());
    const enEnvoi = marquerEnvoi(soumettreMutation(persistee));
    await depot.mettreAJour(enEnvoi);
    const relue = await depot.obtenir(persistee.id);
    expect(relue?.statut).toBe("envoi");
    expect(relue?.proprietaire).toBe("jdupont");
  });
});

describe("identifierEnQuarantaine / resumerQuarantaine", () => {
  const file: MutationOutbox[] = [
    mutation("a1", "en_attente", "jdupont"),
    mutation("a2", "envoi", "jdupont"),
    mutation("a3", "brouillon", "jdupont"),
    mutation("a4", "envoyee", "jdupont"),
    mutation("a5", "echec_permanent", "jdupont"),
    mutation("b1", "en_attente", "mtremblay"),
    mutation("o1", "en_attente", null),
    mutation("o2", "envoi", null),
    mutation("o3", "envoyee", null),
  ];

  test("ce qui attend un envoi et n'est pas à la personne : autre personne ou propriétaire inconnu", () => {
    expect(identifierEnQuarantaine(file, "mtremblay").map((m) => m.id)).toEqual(["a1", "a2", "o1", "o2"]);
    expect(identifierEnQuarantaine(file, "jdupont").map((m) => m.id)).toEqual(["b1", "o1", "o2"]);
  });

  test("brouillons, envoyées et échecs permanents n'attendent aucun envoi : jamais en quarantaine", () => {
    const ids = identifierEnQuarantaine(file, "quelquun").map((m) => m.id);
    expect(ids).not.toContain("a3");
    expect(ids).not.toContain("a4");
    expect(ids).not.toContain("a5");
    expect(ids).not.toContain("o3");
  });

  test("aucune quarantaine quand tout appartient à la personne", () => {
    expect(identifierEnQuarantaine([mutation("a1", "en_attente", "jdupont")], "jdupont")).toEqual([]);
    expect(resumerQuarantaine([], "jdupont")).toEqual({ nombre: 0, proprietaires: [], proprietaireInconnu: 0 });
  });

  test("le résumé compte, nomme les propriétaires sans doublon (triés) et isole les inconnus", () => {
    expect(resumerQuarantaine(file, "mtremblay")).toEqual({ nombre: 4, proprietaires: ["jdupont"], proprietaireInconnu: 2 });
    expect(resumerQuarantaine(file, "autre")).toEqual({
      nombre: 5,
      proprietaires: ["jdupont", "mtremblay"],
      proprietaireInconnu: 2,
    });
  });
});
