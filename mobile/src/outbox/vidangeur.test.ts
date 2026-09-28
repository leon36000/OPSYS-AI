import { DepotOutboxMemoire } from "./depot";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerMutation, soumettreMutation } from "./mutation";
import { creerVidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { MutationOutbox } from "./types";

const HORLOGE = { maintenant: new Date("2026-09-28T18:32:00.000Z"), decalageMinutesUTC: -240 }; // 14 h 32 EDT
let compteur = 0;
const idDeterministe = () => `mut-${++compteur}`;

beforeEach(() => {
  compteur = 0;
});

/** Fausse réponse `fetch`, même patron que src/protocole/client.test.ts. */
function reponseHttp(status: number, corps: unknown, ok = status >= 200 && status < 300): Response {
  return { ok, status, json: async () => corps } as unknown as Response;
}

function reponseAcceptee(resultatMetier: Record<string, unknown> = { statut: "sur_site" }): Response {
  return reponseHttp(200, { ok: true, result: { ok: true, resultat: { accepte: true, resultat: resultatMetier }, rejoue: false } });
}

function reponseRejetee(code: string, detail = "détail"): Response {
  return reponseHttp(200, { ok: true, result: { ok: true, resultat: { accepte: false, verdict: { code, statut: "", detail } }, rejoue: false } });
}

async function inserer(depot: DepotOutboxMemoire, params: Parameters<typeof creerMutation>[0]): Promise<MutationOutbox> {
  const mutation = soumettreMutation(creerMutation(params, idDeterministe, HORLOGE));
  return depot.inserer(mutation);
}

function creerConfig(depot: DepotOutboxMemoire, fetchImpl: typeof fetch, maintenant: () => Date) {
  return {
    depot,
    descripteurs: DESCRIPTEURS_MUTATION,
    appelerOutil: invoquerOutil,
    fetchImpl,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-test",
    appareilId: "APPAREIL-1",
    maintenant,
  };
}

function corpsEnvoye(fetchImpl: jest.Mock, appelIndex = 0): Record<string, unknown> {
  const init = fetchImpl.mock.calls[appelIndex][1] as RequestInit;
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

/** Laisse la chaîne de promesses déjà résolues (depot.lister/mettreAJour, etc.) s'écouler
 * jusqu'à l'appel fetch lui-même, sans dépendre d'un compte exact de `await` internes au
 * vidangeur — fragile à recompter à chaque modification interne. */
async function laisserAvancerJusquauFetch(fetchImpl: jest.Mock): Promise<void> {
  for (let tour = 0; tour < 20 && fetchImpl.mock.calls.length === 0; tour += 1) {
    await Promise.resolve();
  }
}

describe("vidangeur — cycle complet hors ligne -> en ligne (faux transport)", () => {
  test("échec réseau puis succès : en_attente avec recul, puis envoyee au déclencheur suivant", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });

    let maintenant = new Date(HORLOGE.maintenant);
    const fetchImpl = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce(reponseAcceptee());

    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => maintenant));

    const premierRapport = await vidangeur.vidangerFileSortante();
    expect(premierRapport.remisesEnAttente).toEqual([mutation.id]);
    const apresEchec = await depot.obtenir(mutation.id);
    expect(apresEchec?.statut).toBe("en_attente");
    expect(apresEchec?.tentatives).toBe(1);
    expect(apresEchec?.prochaineTentativeA).not.toBeNull();

    // Pas encore dû : un deuxième appel immédiat ne renvoie rien (recul respecté).
    const rapportTropTot = await vidangeur.vidangerFileSortante();
    expect(rapportTropTot.envoyees).toEqual([]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    // « Retour du réseau » : le temps avance au-delà de prochaineTentativeA.
    maintenant = new Date(new Date(apresEchec!.prochaineTentativeA!).getTime() + 1);
    const deuxiemeRapport = await vidangeur.vidangerFileSortante();
    expect(deuxiemeRapport.envoyees).toEqual([mutation.id]);
    const apresSucces = await depot.obtenir(mutation.id);
    expect(apresSucces?.statut).toBe("envoyee");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  test("réponse perdue -> renvoi avec EXACTEMENT la même idempotencyKey (mutation.id)", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_out", chantierId: "interv-1", payload: { action: "depart" } });

    let maintenant = new Date(HORLOGE.maintenant);
    const fetchImpl = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => maintenant));

    await vidangeur.vidangerFileSortante();
    const apresEchec = await depot.obtenir(mutation.id);
    maintenant = new Date(new Date(apresEchec!.prochaineTentativeA!).getTime() + 1);
    await vidangeur.vidangerFileSortante();

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const premiereRequete = corpsEnvoye(fetchImpl);
    const deuxiemeRequete = corpsEnvoye(fetchImpl, 1);
    expect(premiereRequete.idempotencyKey).toBe(mutation.id);
    expect(deuxiemeRequete.idempotencyKey).toBe(mutation.id);
    expect(deuxiemeRequete.idempotencyKey).toBe(premiereRequete.idempotencyKey);
  });
});

describe("vidangeur — idempotence du socle", () => {
  test("rejoue:true du socle est traité comme un succès ordinaire", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const fetchImpl = jest.fn().mockResolvedValue(
      reponseHttp(200, {
        ok: true,
        result: { ok: true, resultat: { accepte: true, resultat: { statut: "sur_site" } }, rejoue: true },
      }),
    );
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.envoyees).toEqual([mutation.id]);
    expect((await depot.obtenir(mutation.id))?.statut).toBe("envoyee");
  });

  test("reprise au démarrage (statut envoi retrouvé en base) : renvoyée avec la MÊME id, jamais recréée", async () => {
    const depot = new DepotOutboxMemoire();
    const brouillon = creerMutation({ type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } }, idDeterministe, HORLOGE);
    const persistee = await depot.inserer(brouillon);
    // Simule une ligne retrouvée `envoi` après un crash en plein envoi (jamais via marquerEnvoi
    // ici : c'est l'état trouvé tel quel dans le dépôt au démarrage, pas une transition qu'on
    // rejoue nous-mêmes).
    await depot.mettreAJour({ ...persistee, statut: "envoi" });

    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.envoyees).toEqual([persistee.id]);
    expect(corpsEnvoye(fetchImpl).idempotencyKey).toBe(persistee.id);
    expect((await depot.obtenir(persistee.id))?.statut).toBe("envoyee");
  });
});

describe("vidangeur — resultatsAcceptes (PLAN T1.4-f)", () => {
  test("une mutation acceptée porte son resume dans resultatsAcceptes, pas seulement son id", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseAcceptee({ statut: "sur_site", intervention_id: "interv-1" }));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.envoyees).toEqual([mutation.id]);
    expect(rapport.resultatsAcceptes).toEqual([{ id: mutation.id, resume: { statut: "sur_site", intervention_id: "interv-1" } }]);
  });

  test("plusieurs mutations acceptées -> un resultatsAcceptes par mutation, dans l'ordre d'envoi", async () => {
    const depot = new DepotOutboxMemoire();
    const m1 = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const m2 = await inserer(depot, { type: "punch_out", chantierId: "interv-1", payload: { action: "depart" } });
    const fetchImpl = jest
      .fn()
      .mockResolvedValueOnce(reponseAcceptee({ statut: "sur_site" }))
      .mockResolvedValueOnce(reponseAcceptee({ statut: "termine" }));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.resultatsAcceptes.map((r) => r.id)).toEqual([m1.id, m2.id]);
    expect(rapport.resultatsAcceptes[0].resume).toEqual({ statut: "sur_site" });
    expect(rapport.resultatsAcceptes[1].resume).toEqual({ statut: "termine" });
  });

  test("un échec (réessayable ou permanent) n'ajoute rien à resultatsAcceptes", async () => {
    const depot = new DepotOutboxMemoire();
    await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseRejetee("REJ-TRANSITION-ILLEGALE"));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.echecsPermanents).toHaveLength(1);
    expect(rapport.resultatsAcceptes).toEqual([]);
  });

  test("verrou actif -> resultatsAcceptes vide (même forme que les autres champs)", async () => {
    const depot = new DepotOutboxMemoire();
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    // Le premier appel démarre et pose le verrou de façon SYNCHRONE (avant son premier `await`,
    // voir vidangeur.ts) ; le second, déclenché pendant que le premier est encore en cours, est
    // donc TOUJOURS celui que le verrou ignore — même discipline que les autres champs du rapport.
    const [, rapportSeconde] = await Promise.all([vidangeur.vidangerFileSortante(), vidangeur.vidangerFileSortante()]);
    expect(rapportSeconde.ignoreeVerrouActif).toBe(true);
    expect(rapportSeconde.resultatsAcceptes).toEqual([]);
  });
});

describe("vidangeur — classification des échecs", () => {
  test("erreur réessayable (HTTP 500) : recul respecté, pas de renvoi avant l'heure", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp(500, { ok: false, error: { type: "tool_error", message: "panne" } }));
    let maintenant = new Date(HORLOGE.maintenant);
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.remisesEnAttente).toEqual([mutation.id]);
    const apres = await depot.obtenir(mutation.id);
    expect(apres?.statut).toBe("en_attente");
    // 1er échec (tentatives=0 avant) -> recul de 1000 ms (recul.ts, calculerDelaiReculMs(0)).
    expect(new Date(apres!.prochaineTentativeA!).getTime()).toBe(maintenant.getTime() + 1_000);

    await vidangeur.vidangerFileSortante();
    expect(fetchImpl).toHaveBeenCalledTimes(1); // toujours pas dû

    maintenant = new Date(maintenant.getTime() + 1_001);
    await vidangeur.vidangerFileSortante();
    expect(fetchImpl).toHaveBeenCalledTimes(2); // dû désormais
  });

  test("erreur permanente HTTP (400) : echec_permanent, descendant signalé bloqué", async () => {
    const depot = new DepotOutboxMemoire();
    const parent = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const enfant = await inserer(depot, {
      type: "punch_out",
      chantierId: "interv-1",
      payload: { action: "depart" },
      dependsOn: parent.id,
    });
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp(400, { ok: false, error: { type: "invalid_request", message: "mal formé" } }));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.echecsPermanents).toEqual([
      { id: parent.id, verdict: { code: "invalid_request", detail: "mal formé" } },
    ]);
    expect((await depot.obtenir(parent.id))?.statut).toBe("echec_permanent");
    // L'enfant n'a jamais été envoyé (sa parente n'est pas `envoyee`) : toujours en_attente...
    expect((await depot.obtenir(enfant.id))?.statut).toBe("en_attente");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    // ...mais signalé, pas oublié silencieusement (R12 §4).
    expect(rapport.bloquees).toEqual([enfant.id]);
  });

  test("rejet métier (accepte:false, HTTP 200) : echec_permanent AVEC le verdict du serveur", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const fetchImpl = jest.fn().mockResolvedValue(reponseRejetee("REJ-PUNCH-HORS-HEURES", "hors fenêtre"));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.echecsPermanents).toEqual([
      { id: mutation.id, verdict: { code: "REJ-PUNCH-HORS-HEURES", detail: "hors fenêtre" } },
    ]);
    expect((await depot.obtenir(mutation.id))?.statut).toBe("echec_permanent");
    // Un seul essai : un rejet métier ne se réessaie jamais avec le même payload.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

describe("vidangeur — verrou simple", () => {
  test("jamais deux vidanges concurrentes : le deuxième appel est absorbé, pas empilé", async () => {
    const depot = new DepotOutboxMemoire();
    await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });

    let resoudre: (reponse: Response) => void = () => undefined;
    const promesseControlee = new Promise<Response>((resolve) => {
      resoudre = resolve;
    });
    const fetchImpl = jest.fn().mockReturnValue(promesseControlee);
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const premierAppel = vidangeur.vidangerFileSortante(); // ne pas attendre : fetch encore en vol
    await laisserAvancerJusquauFetch(fetchImpl);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const deuxiemeAppel = await vidangeur.vidangerFileSortante();
    expect(deuxiemeAppel.ignoreeVerrouActif).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1); // pas de deuxième vidange démarrée

    resoudre(reponseAcceptee());
    const rapportPremierAppel = await premierAppel;
    expect(rapportPremierAppel.ignoreeVerrouActif).toBe(false);
    expect(rapportPremierAppel.envoyees).toHaveLength(1);
  });

  test("une fois la vidange précédente terminée, une nouvelle vidange redémarre normalement", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    await vidangeur.vidangerFileSortante();
    const rapportSuivant = await vidangeur.vidangerFileSortante();
    expect(rapportSuivant.ignoreeVerrouActif).toBe(false);
    expect(rapportSuivant.envoyees).toEqual([]); // plus rien à envoyer, mais la passe a bien eu lieu
    expect((await depot.obtenir(mutation.id))?.statut).toBe("envoyee");
  });
});
