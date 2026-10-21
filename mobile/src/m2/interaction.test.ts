import {
  OUTIL_ENREGISTRER_INTERACTION,
  RESUME_LONGUEUR_MAX,
  chantierIdNotes,
  construireArgumentsEnregistrerInteraction,
  creerMutationNote,
  interpreterResultatEnregistrerInteraction,
  notesEnFile,
  validerNote,
} from "./interaction";
import { DepotOutboxMemoire } from "../outbox/depot";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { creerVidangeur } from "../outbox/vidangeur";
import type { MutationOutbox } from "../outbox/types";
import { invoquerOutil } from "../protocole/client";
import { ACCUSE_NOTE_BRUT, enveloppeAcceptee, enveloppeRefusee } from "../vendeur/donneesDeTest";

const HORLOGE = { maintenant: new Date("2026-09-29T18:03:22.000Z"), decalageMinutesUTC: -240 };
let compteur = 0;
const idDeterministe = () => `note-${++compteur}`;
beforeEach(() => {
  compteur = 0;
});

function reponseHttp(corps: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => corps } as unknown as Response;
}

describe("validerNote", () => {
  test("un résumé épuré, non vide, d'au plus 300 caractères", () => {
    expect(validerNote("  Le client veut voir le devis  ")).toEqual({ ok: true, resume: "Le client veut voir le devis" });
    expect(validerNote("a".repeat(RESUME_LONGUEUR_MAX))).toMatchObject({ ok: true });
  });

  test.each([[""], ["   "], ["\n\t"]])("vide (%j) : refusé, jamais mis en file", (texte) => {
    expect(validerNote(texte)).toEqual({ ok: false, raison: "vide" });
  });

  test("au-delà de la borne : refusé (le Client 360 rend dix interactions sous 6 000 caractères)", () => {
    expect(RESUME_LONGUEUR_MAX * 10).toBeLessThan(6000);
    expect(validerNote("a".repeat(RESUME_LONGUEUR_MAX + 1))).toEqual({ ok: false, raison: "trop_longue" });
  });
});

describe("arguments et mutation de la note", () => {
  test("args EXACTS du schéma : lead_id, resume, horodatage — ni auteur, ni personne, ni rôle", () => {
    const args = construireArgumentsEnregistrerInteraction("lead-a-01", " Rappel fait ", "2026-09-29T14:03:22-04:00");
    expect(args).toEqual({ lead_id: "lead-a-01", resume: "Rappel fait", horodatage: "2026-09-29T14:03:22-04:00" });
    for (const interdit of ["auteur", "personne", "role", "appareil", "owner"]) {
      expect(args).not.toHaveProperty(interdit);
    }
  });

  test("la mutation est soumise (en_attente), typée lead_note, groupée par lead, payload = args de l'outil", () => {
    const mutation = creerMutationNote("lead-a-01", "Rappel fait", idDeterministe, HORLOGE);
    expect(mutation).toMatchObject({
      id: "note-1",
      type: "lead_note",
      chantierId: "lead:lead-a-01",
      statut: "en_attente",
      dependsOn: null,
      payload: { lead_id: "lead-a-01", resume: "Rappel fait", horodatage: "2026-09-29T14:03:22-04:00" },
      createdAtLocal: "2026-09-29T14:03:22-04:00",
    });
    expect(Object.keys(mutation.payload).sort()).toEqual(["horodatage", "lead_id", "resume"]);
    expect(chantierIdNotes("x")).toBe("lead:x");
  });

  test("une note vide, trop longue ou sans lead ne crée aucune mutation", () => {
    expect(() => creerMutationNote("lead-a-01", "  ", idDeterministe, HORLOGE)).toThrow(/vide/);
    expect(() => creerMutationNote("lead-a-01", "a".repeat(RESUME_LONGUEUR_MAX + 1), idDeterministe, HORLOGE)).toThrow(/trop_longue/);
    expect(() => creerMutationNote(" ", "note", idDeterministe, HORLOGE)).toThrow(/lead vide/);
    expect(compteur).toBe(0);
  });
});

describe("accusé de la note", () => {
  test("accusé lu : lead, ligne écrite, heure", () => {
    expect(interpreterResultatEnregistrerInteraction(enveloppeAcceptee(ACCUSE_NOTE_BRUT))).toEqual({
      accepte: true,
      resultat: { leadId: "lead-a-01", ligneId: ACCUSE_NOTE_BRUT.ligne_id, horodatage: "2026-09-29T14:03:22-04:00" },
    });
  });

  test("refus du serveur (lead d'un autre, lead clos, note vide) : verdict tel quel", () => {
    expect(interpreterResultatEnregistrerInteraction(enveloppeRefusee("REJ-LEAD-NON-ASSIGNE", "lead inconnu"))).toEqual({
      accepte: false,
      verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead inconnu" },
    });
    expect(interpreterResultatEnregistrerInteraction(enveloppeRefusee("REJ-CONVERSATION-CLOSE", "lead clos")).accepte).toBe(false);
  });

  test("refus technique : verdict avec code et détails", () => {
    expect(
      interpreterResultatEnregistrerInteraction({ ok: false, erreur: "mutation_conflit", details: "clé déjà utilisée" }),
    ).toEqual({ accepte: false, verdict: { code: "mutation_conflit", detail: "clé déjà utilisée" } });
  });

  test.each(["lead_id", "ligne_id", "horodatage"])("accusé sans %s : jamais un succès, dit de vérifier l'historique", (cle) => {
    const lecture = interpreterResultatEnregistrerInteraction(enveloppeAcceptee({ ...ACCUSE_NOTE_BRUT, [cle]: undefined }));
    expect(lecture).toMatchObject({ accepte: false, verdict: { code: "reponse_illisible" } });
    expect(lecture.accepte === false && lecture.verdict.detail).toContain("ne la renverra pas");
  });
});

describe("la note par la file sortante, avec sa clé d'idempotence", () => {
  const session = () => ({
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-vendeur",
    appareilId: "APPAREIL-VENDEUR",
    personne: "vendeur.fictif",
  });
  const deposer = (depot: DepotOutboxMemoire, mutation: MutationOutbox) =>
    depot.inserer({ ...mutation, destination: session().urlBase, proprietaire: "vendeur.fictif" });
  const vidangeurDe = (depot: DepotOutboxMemoire, fetchImpl: jest.Mock, maintenant: () => Date = () => HORLOGE.maintenant) =>
    creerVidangeur({
      depot,
      descripteurs: DESCRIPTEURS_MUTATION,
      appelerOutil: invoquerOutil,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      session,
      maintenant,
    });
  const corps = (fetchImpl: jest.Mock, i = 0) =>
    JSON.parse((fetchImpl.mock.calls[i][1] as RequestInit).body as string) as Record<string, unknown>;

  test("envoi : m2_enregistrer_interaction, idempotencyKey = id de la mutation, args exacts, accusé lu", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationNote("lead-a-01", "Rappel fait", idDeterministe, HORLOGE));
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp({ ok: true, result: enveloppeAcceptee(ACCUSE_NOTE_BRUT) }));

    const rapport = await vidangeurDe(depot, fetchImpl).vidangerFileSortante();

    expect(rapport.envoyees).toEqual([persistee.id]);
    expect(corps(fetchImpl)).toEqual({
      tool: OUTIL_ENREGISTRER_INTERACTION,
      args: { lead_id: "lead-a-01", resume: "Rappel fait", horodatage: "2026-09-29T14:03:22-04:00" },
      idempotencyKey: persistee.id,
      deviceId: "APPAREIL-VENDEUR",
      deviceTimestamp: "2026-09-29T14:03:22-04:00",
    });
    expect(rapport.resultatsAcceptes[0].resume).toMatchObject({ leadId: "lead-a-01", ligneId: ACCUSE_NOTE_BRUT.ligne_id });
    expect((await depot.obtenir(persistee.id))?.statut).toBe("envoyee");
  });

  test("réponse perdue : le renvoi porte LA MÊME clé et le MÊME payload (le serveur n'écrit la note qu'une fois)", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationNote("lead-a-01", "Rappel fait", idDeterministe, HORLOGE));
    let maintenant = new Date(HORLOGE.maintenant);
    const fetchImpl = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce(reponseHttp({ ok: true, result: { ...enveloppeAcceptee(ACCUSE_NOTE_BRUT), rejoue: true } }));
    const vidangeur = vidangeurDe(depot, fetchImpl, () => maintenant);

    const premier = await vidangeur.vidangerFileSortante();
    expect(premier.remisesEnAttente).toEqual([persistee.id]);
    maintenant = new Date(new Date((await depot.obtenir(persistee.id))!.prochaineTentativeA!).getTime() + 1);
    const second = await vidangeur.vidangerFileSortante();

    expect(second.envoyees).toEqual([persistee.id]);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(corps(fetchImpl, 1).idempotencyKey).toBe(corps(fetchImpl, 0).idempotencyKey);
    expect(corps(fetchImpl, 1).args).toEqual(corps(fetchImpl, 0).args);
    expect(corps(fetchImpl, 1).deviceTimestamp).toBe(corps(fetchImpl, 0).deviceTimestamp);
  });

  test("refus du serveur : échec permanent avec son verdict, jamais renvoyé", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationNote("lead-b-01", "Note", idDeterministe, HORLOGE));
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(reponseHttp({ ok: true, result: enveloppeRefusee("REJ-LEAD-NON-ASSIGNE", "lead lead-b-01 non assigné") }));

    const rapport = await vidangeurDe(depot, fetchImpl).vidangerFileSortante();

    expect(rapport.echecsPermanents).toEqual([
      { id: persistee.id, verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead lead-b-01 non assigné" } },
    ]);
    expect((await depot.obtenir(persistee.id))?.statut).toBe("echec_permanent");
    await vidangeurDe(depot, fetchImpl).vidangerFileSortante();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  test("hors ligne : la note reste en file, intacte, et la file la montre", async () => {
    const depot = new DepotOutboxMemoire();
    const persistee = await deposer(depot, creerMutationNote("lead-a-01", "Note hors ligne", idDeterministe, HORLOGE));
    const fetchImpl = jest.fn().mockRejectedValue(new TypeError("Network request failed"));

    await vidangeurDe(depot, fetchImpl).vidangerFileSortante();

    const restante = await depot.obtenir(persistee.id);
    expect(restante).toMatchObject({ statut: "en_attente", tentatives: 1, payload: persistee.payload });
    expect(notesEnFile(await depot.lister(), "lead-a-01").map((n) => [n.resume, n.statut])).toEqual([
      ["Note hors ligne", "en_attente"],
    ]);
  });
});

describe("notesEnFile", () => {
  function mutation(id: string, statut: MutationOutbox["statut"], leadId: string, sequence: number, type: MutationOutbox["type"] = "lead_note"): MutationOutbox {
    return {
      id,
      sequence,
      type,
      chantierId: chantierIdNotes(leadId),
      payload: { lead_id: leadId, resume: `résumé ${id}`, horodatage: "2026-09-29T14:03:22-04:00" },
      dependsOn: null,
      statut,
      tentatives: 0,
      createdAtLocal: "2026-09-29T14:03:22-04:00",
      prochaineTentativeA: null,
      proprietaire: "vendeur.fictif",
    };
  }

  test("les notes du lead pas encore à l'historique, dans l'ordre d'écriture (la séquence, pas le texte)", () => {
    const file = [
      mutation("c", "en_attente", "L1", 3),
      mutation("a", "echec_permanent", "L1", 1),
      mutation("b", "envoi", "L1", 2),
    ];
    expect(notesEnFile(file, "L1").map((n) => [n.mutationId, n.statut])).toEqual([
      ["a", "echec_permanent"],
      ["b", "envoi"],
      ["c", "en_attente"],
    ]);
  });

  test("ignore une note envoyée (déjà à l'historique), un brouillon, un autre lead et un autre type", () => {
    const file = [
      mutation("envoyee", "envoyee", "L1", 1),
      mutation("brouillon", "brouillon", "L1", 2),
      mutation("autre-lead", "en_attente", "L2", 3),
      mutation("autre-type", "en_attente", "L1", 4, "punch_in"),
      mutation("ok", "en_attente", "L1", 5),
    ];
    expect(notesEnFile(file, "L1").map((n) => n.mutationId)).toEqual(["ok"]);
  });

  test("un payload sans résumé lisible est ignoré, jamais montré vide", () => {
    const abime = { ...mutation("x", "en_attente", "L1", 1), payload: { lead_id: "L1" } };
    expect(notesEnFile([abime], "L1")).toEqual([]);
  });
});
