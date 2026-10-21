import { DepotOutboxMemoire } from "./depot";
import type { DepotOutbox } from "./depot";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerMutation, soumettreMutation } from "./mutation";
import { creerVidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
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

const PERSONNE = "jdupont";
const URL_BASE = "https://grs.exemple.ca";
const SESSION_DE_TEST: SessionEnvoi = { urlBase: URL_BASE, jeton: "jeton-test", appareilId: "APPAREIL-1", personne: PERSONNE };

/** Insère une mutation `en_attente`, créée sous `proprietaire` (par défaut la personne de la session de test). */
async function inserer(
  depot: DepotOutboxMemoire,
  params: Parameters<typeof creerMutation>[0],
  proprietaire: string | null = PERSONNE,
): Promise<MutationOutbox> {
  const mutation = soumettreMutation(creerMutation(params, idDeterministe, HORLOGE));
  return depot.inserer({ ...mutation, proprietaire, destination: URL_BASE });
}

function creerConfig(
  depot: DepotOutboxMemoire,
  fetchImpl: typeof fetch,
  maintenant: () => Date,
  session: () => SessionEnvoi | null = () => SESSION_DE_TEST,
) {
  return {
    depot,
    descripteurs: DESCRIPTEURS_MUTATION,
    appelerOutil: invoquerOutil,
    fetchImpl,
    session,
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
    expect((await depot.obtenir(mutation.id))?.resumeAccepte).toEqual({ statut: "sur_site" });
  });

  test("reprise au démarrage (statut envoi retrouvé en base) : renvoyée avec la MÊME id, jamais recréée", async () => {
    const depot = new DepotOutboxMemoire();
    const brouillon = creerMutation({ type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } }, idDeterministe, HORLOGE);
    const persistee = await depot.inserer({ ...brouillon, proprietaire: PERSONNE, destination: URL_BASE });
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
    expect((await depot.obtenir(mutation.id))?.resumeAccepte).toEqual({ statut: "sur_site", intervention_id: "interv-1" });
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
  test("corps HTTP interrompu conserve la mutation en attente avec le même identifiant", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } });
    let maintenant = new Date(HORLOGE.maintenant);
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => { throw new TypeError("terminated"); } } as unknown as Response)
      .mockResolvedValueOnce(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => maintenant));
    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.remisesEnAttente).toEqual([mutation.id]);
    const remise = await depot.obtenir(mutation.id);
    expect(remise).toMatchObject({ statut: "en_attente", tentatives: 1, id: mutation.id });
    maintenant = new Date(new Date(remise!.prochaineTentativeA!).getTime() + 1);
    const second = await vidangeur.vidangerFileSortante();
    expect(second.envoyees).toEqual([mutation.id]);
    expect(corpsEnvoye(fetchImpl).idempotencyKey).toBe(mutation.id);
    expect(corpsEnvoye(fetchImpl, 1).idempotencyKey).toBe(mutation.id);
    expect((await depot.obtenir(mutation.id))?.statut).toBe("envoyee");
  });

  test("accusé métier de fichier inconnu reste en attente avec recul (issue serveur incertaine)", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, {
      type: "fichier_bloc", chantierId: "interv-1",
      payload: { empreinte_sha256: "sha", taille_octets: 3, type_mime: "image/jpeg", index_bloc: 0, nombre_blocs: 1, bloc_base64: "YWJj" },
    });
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp(200, { ok: true, result: { ok: true, resultat: {} } }));
    const rapport = await creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant)).vidangerFileSortante();
    expect(rapport.remisesEnAttente).toEqual([mutation.id]);
    expect(rapport.echecsPermanents).toEqual([]);
    expect(await depot.obtenir(mutation.id)).toMatchObject({ statut: "en_attente", tentatives: 1, id: mutation.id });
    expect(corpsEnvoye(fetchImpl).idempotencyKey).toBe(mutation.id);
  });

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

/** L'en-tête `authorization` de l'appel numéro `i` : le jeton réellement envoyé. */
function autorisationEnvoyee(fetchImpl: jest.Mock, appelIndex = 0): string {
  const init = fetchImpl.mock.calls[appelIndex][1] as RequestInit;
  return (init.headers as Record<string, string>).authorization;
}

const SESSION_JETON_1: SessionEnvoi = { urlBase: URL_BASE, jeton: "jeton-1", appareilId: "APPAREIL-1", personne: "jdupont" };
const SESSION_JETON_2: SessionEnvoi = { ...SESSION_JETON_1, jeton: "jeton-2" };
const SESSION_AUTRE_PERSONNE: SessionEnvoi = { ...SESSION_JETON_2, personne: "mtremblay" };

const PUNCH = { type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } } as const;
const PUNCH_OUT = { type: "punch_out", chantierId: "interv-1", payload: { action: "depart" } } as const;

describe("vidangeur — la file suit le jeton courant (PLAN T1.4-l)", () => {
  test("le jeton est relu avant CHAQUE envoi : un changement en cours de vidange est suivi dès la mutation suivante", async () => {
    const depot = new DepotOutboxMemoire();
    const m1 = await inserer(depot, PUNCH);
    const m2 = await inserer(depot, PUNCH_OUT);

    let session = SESSION_JETON_1;
    // Le nouvel appairage a lieu pendant que la première mutation est en vol.
    const fetchImpl = jest
      .fn()
      .mockImplementationOnce(async () => {
        session = SESSION_JETON_2;
        return reponseAcceptee();
      })
      .mockResolvedValueOnce(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => session));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(rapport.envoyees).toEqual([m1.id, m2.id]);
    expect(autorisationEnvoyee(fetchImpl, 0)).toBe("Bearer jeton-1");
    expect(autorisationEnvoyee(fetchImpl, 1)).toBe("Bearer jeton-2");
    expect(rapport.arret).toBeNull();
  });

  test("le vidangeur ne garde aucun jeton d'une passe à l'autre : jamais l'ancien après un nouvel appairage", async () => {
    const depot = new DepotOutboxMemoire();
    await inserer(depot, PUNCH);
    await inserer(depot, PUNCH_OUT);

    let session = SESSION_JETON_1;
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => session));

    await vidangeur.vidangerFileSortante(); // les deux partent avec jeton-1
    await inserer(depot, PUNCH);
    session = SESSION_JETON_2; // nouvel appairage, même vidangeur
    await vidangeur.vidangerFileSortante();

    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect([0, 1, 2].map((i) => autorisationEnvoyee(fetchImpl, i))).toEqual(["Bearer jeton-1", "Bearer jeton-1", "Bearer jeton-2"]);
  });

  test("réappairage de la MÊME personne : la mutation restée en file part avec le nouveau jeton, même id, même clé d'idempotence", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, PUNCH);
    let session = SESSION_JETON_1;
    let maintenant = new Date(HORLOGE.maintenant);
    const fetchImpl = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => maintenant, () => session));

    await vidangeur.vidangerFileSortante(); // hors ligne : reste en file avec l'ancien jeton
    const apresEchec = await depot.obtenir(mutation.id);
    expect(apresEchec?.statut).toBe("en_attente");

    session = SESSION_JETON_2; // même personne, nouveau jeton
    maintenant = new Date(new Date(apresEchec!.prochaineTentativeA!).getTime() + 1);
    const rapport = await vidangeur.vidangerFileSortante();

    expect(rapport.envoyees).toEqual([mutation.id]);
    expect(rapport.quarantaine).toEqual([]);
    expect(autorisationEnvoyee(fetchImpl, 0)).toBe("Bearer jeton-1");
    expect(autorisationEnvoyee(fetchImpl, 1)).toBe("Bearer jeton-2");
    expect(corpsEnvoye(fetchImpl, 1).idempotencyKey).toBe(mutation.id);
    expect(corpsEnvoye(fetchImpl, 1).idempotencyKey).toBe(corpsEnvoye(fetchImpl, 0).idempotencyKey);
    expect((await depot.obtenir(mutation.id))?.statut).toBe("envoyee");
  });

  test("réappairage d'une AUTRE personne : ses mutations ne partent jamais, restent intactes, en quarantaine visible", async () => {
    const depot = new DepotOutboxMemoire();
    const deA1 = await inserer(depot, PUNCH, "jdupont");
    const deA2 = await inserer(depot, PUNCH_OUT, "jdupont");
    const avant = await depot.lister();
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => SESSION_AUTRE_PERSONNE),
    );

    const rapport = await vidangeur.vidangerFileSortante();

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(rapport.envoyees).toEqual([]);
    expect(rapport.remisesEnAttente).toEqual([]);
    expect(rapport.echecsPermanents).toEqual([]);
    expect(rapport.quarantaine).toEqual([deA1.id, deA2.id]);
    expect(rapport.arret).toBeNull();
    // Rien n'est supprimé, rien ne change : la file est identique octet pour octet.
    expect(await depot.lister()).toEqual(avant);
  });

  test("autre personne : SES mutations partent, celles de l'ancienne restent, dans la même passe", async () => {
    const depot = new DepotOutboxMemoire();
    const deA = await inserer(depot, PUNCH, "jdupont");
    const deB = await inserer(depot, PUNCH_OUT, "mtremblay");
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => SESSION_AUTRE_PERSONNE),
    );

    const rapport = await vidangeur.vidangerFileSortante();

    expect(rapport.envoyees).toEqual([deB.id]);
    expect(rapport.quarantaine).toEqual([deA.id]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(corpsEnvoye(fetchImpl).idempotencyKey).toBe(deB.id);
    expect((await depot.obtenir(deA.id))?.statut).toBe("en_attente");
  });

  test("l'ancienne personne revient : sa quarantaine repart, avec la même id", async () => {
    const depot = new DepotOutboxMemoire();
    const deA = await inserer(depot, PUNCH, "jdupont");
    let session: SessionEnvoi = SESSION_AUTRE_PERSONNE;
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => session));

    await vidangeur.vidangerFileSortante();
    expect(fetchImpl).not.toHaveBeenCalled();

    session = SESSION_JETON_2; // l'appareil est de nouveau appairé pour jdupont
    const rapport = await vidangeur.vidangerFileSortante();
    expect(rapport.envoyees).toEqual([deA.id]);
    expect(corpsEnvoye(fetchImpl).idempotencyKey).toBe(deA.id);
    expect(rapport.quarantaine).toEqual([]);
  });

  test("propriétaire inconnu (ligne d'avant T1.4-l) : quarantaine, jamais envoyée sous une identité devinée", async () => {
    const depot = new DepotOutboxMemoire();
    const orpheline = await inserer(depot, PUNCH, null);
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(rapport.quarantaine).toEqual([orpheline.id]);
    expect((await depot.obtenir(orpheline.id))?.statut).toBe("en_attente");
  });

  test("une reprise (`envoi` après un crash) d'une autre personne n'est pas reprise sous la nouvelle identité", async () => {
    const depot = new DepotOutboxMemoire();
    const deA = await inserer(depot, PUNCH, "jdupont");
    await depot.mettreAJour({ ...deA, statut: "envoi" });
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => SESSION_AUTRE_PERSONNE),
    );

    const rapport = await vidangeur.vidangerFileSortante();

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(rapport.quarantaine).toEqual([deA.id]);
    expect((await depot.obtenir(deA.id))?.statut).toBe("envoi");
  });

  test("sans session (pas apparié, ou personne pas encore confirmée pour ce jeton) : rien ne part, rien ne bouge", async () => {
    const depot = new DepotOutboxMemoire();
    await inserer(depot, PUNCH);
    const avant = await depot.lister();
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => null));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(rapport.arret).toEqual({ genre: "sans_session" });
    expect(rapport.envoyees).toEqual([]);
    expect(await depot.lister()).toEqual(avant);
  });

  test("la personne de la session change EN COURS de vidange : la mutation suivante ne part pas, elle redevient en_attente intacte", async () => {
    const depot = new DepotOutboxMemoire();
    const m1 = await inserer(depot, PUNCH, "jdupont");
    const m2 = await inserer(depot, PUNCH_OUT, "jdupont");
    let session: SessionEnvoi = SESSION_JETON_1;
    const fetchImpl = jest.fn().mockImplementationOnce(async () => {
      session = SESSION_AUTRE_PERSONNE; // un autre appairage se termine pendant le premier envoi
      return reponseAcceptee();
    });
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => session));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(rapport.envoyees).toEqual([m1.id]);
    expect(rapport.arret).toEqual({ genre: "session_changee" });
    const restee = await depot.obtenir(m2.id);
    expect(restee?.statut).toBe("en_attente");
    expect(restee?.tentatives).toBe(0);
    expect(restee?.prochaineTentativeA).toBeNull();
    expect(rapport.quarantaine).toEqual([m2.id]); // désormais celle d'une autre personne
  });
});

describe("vidangeur — l'appareil est refusé : révocation (PLAN T1.4-l)", () => {
  const corps401 = { error: { message: "Unauthorized", type: "unauthorized" } };
  const corps403 = (raison: string) => ({
    ok: false,
    error: { type: "tool_call_blocked", message: `OPSYS device is not authorized to call "m4_pointer" (${raison}).` },
  });

  test("401 : la vidange s'ARRÊTE au premier refus, la mutation reste intacte en file, aucun échec permanent fabriqué", async () => {
    const depot = new DepotOutboxMemoire();
    const m1 = await inserer(depot, PUNCH);
    const m2 = await inserer(depot, PUNCH_OUT);
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp(401, corps401));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(fetchImpl).toHaveBeenCalledTimes(1); // pas de boucle, pas de deuxième mutation tentée
    expect(rapport.arret).toEqual({
      genre: "appareil_refuse",
      mutationId: m1.id,
      status: 401,
      message: "réponse HTTP 401 inattendue",
    });
    expect(rapport.echecsPermanents).toEqual([]);
    expect(rapport.remisesEnAttente).toEqual([]);
    expect(rapport.envoyees).toEqual([]);
    for (const id of [m1.id, m2.id]) {
      const restee = await depot.obtenir(id);
      expect(restee?.statut).toBe("en_attente");
      expect(restee?.tentatives).toBe(0); // pas sa faute : aucune tentative comptée
      expect(restee?.prochaineTentativeA).toBeNull(); // pas de recul : elle repartira dès qu'une session valide existera
    }
  });

  test.each(["device_unknown", "role_unknown"])("403 %s (attribution retirée) : même arrêt, mutation intacte", async (raison) => {
    const depot = new DepotOutboxMemoire();
    const m1 = await inserer(depot, PUNCH);
    await inserer(depot, PUNCH_OUT);
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp(403, corps403(raison)));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(rapport.arret?.genre).toBe("appareil_refuse");
    expect(rapport.echecsPermanents).toEqual([]);
    expect((await depot.obtenir(m1.id))?.statut).toBe("en_attente");
  });

  test("403 tool_out_of_scope : c'est la MUTATION qui est refusée, pas l'appareil — échec permanent, et la file continue", async () => {
    const depot = new DepotOutboxMemoire();
    const refusee = await inserer(depot, PUNCH);
    const suivante = await inserer(depot, PUNCH_OUT, PERSONNE);
    const fetchImpl = jest
      .fn()
      .mockResolvedValueOnce(reponseHttp(403, corps403("tool_out_of_scope")))
      .mockResolvedValueOnce(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(rapport.arret).toBeNull();
    expect(rapport.echecsPermanents.map((e) => e.id)).toEqual([refusee.id]);
    expect(rapport.envoyees).toEqual([suivante.id]);
    expect((await depot.obtenir(refusee.id))?.statut).toBe("echec_permanent");
  });

  test("chaque passe fait UN seul essai puis s'arrête : un déclencheur ordinaire ne fait jamais boucler la file", async () => {
    const depot = new DepotOutboxMemoire();
    await inserer(depot, PUNCH);
    const fetchImpl = jest.fn().mockResolvedValue(reponseHttp(401, corps401));
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant));

    await vidangeur.vidangerFileSortante();
    await vidangeur.vidangerFileSortante();
    await vidangeur.vidangerFileSortante();

    expect(fetchImpl).toHaveBeenCalledTimes(3); // un essai par passe, jamais plus
  });

  test("après le refus, un nouvel appairage (même personne) : la MÊME mutation part avec le nouveau jeton", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, PUNCH);
    let session = SESSION_JETON_1;
    const fetchImpl = jest
      .fn()
      .mockResolvedValueOnce(reponseHttp(401, corps401))
      .mockResolvedValueOnce(reponseAcceptee());
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => session));

    const refus = await vidangeur.vidangerFileSortante();
    expect(refus.arret?.genre).toBe("appareil_refuse");

    session = SESSION_JETON_2;
    const rapport = await vidangeur.vidangerFileSortante();

    expect(rapport.envoyees).toEqual([mutation.id]);
    expect(autorisationEnvoyee(fetchImpl, 0)).toBe("Bearer jeton-1");
    expect(autorisationEnvoyee(fetchImpl, 1)).toBe("Bearer jeton-2");
    expect(corpsEnvoye(fetchImpl, 1).idempotencyKey).toBe(mutation.id);
    expect((await depot.obtenir(mutation.id))?.statut).toBe("envoyee");
  });

  test("le refus d'un ANCIEN jeton, arrivé après un nouvel appairage, n'est pas un refus d'appareil", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, PUNCH);
    let session = SESSION_JETON_1;
    const fetchImpl = jest.fn().mockImplementationOnce(async () => {
      session = SESSION_JETON_2; // le nouvel appairage a invalidé l'ancien jeton pendant l'appel
      return reponseHttp(401, corps401);
    });
    const vidangeur = creerVidangeur(creerConfig(depot, fetchImpl as unknown as typeof fetch, () => HORLOGE.maintenant, () => session));

    const rapport = await vidangeur.vidangerFileSortante();

    expect(rapport.arret).toEqual({ genre: "session_changee" });
    const restee = await depot.obtenir(mutation.id);
    expect(restee?.statut).toBe("en_attente");
    expect(restee?.tentatives).toBe(0);
  });
});


describe("CF037 — transitions de départ et de garde en concurrence", () => {
  test("CF037 ownership — le départ perdu de B ne réinitialise pas l'envoi acquis par A", async () => {
    const depot = new DepotOutboxMemoire();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-CF037", payload: { action: "arrivee" } });
    let entrerB!: () => void, libererB!: () => void, entrerA!: () => void, libererA!: (response: Response) => void;
    const entreeB = new Promise<void>(resolve => { entrerB = resolve; });
    const attenteB = new Promise<void>(resolve => { libererB = resolve; });
    const entreeA = new Promise<void>(resolve => { entrerA = resolve; });
    const attenteA = new Promise<Response>(resolve => { libererA = resolve; });
    let resetsB = 0;
    const depotB: DepotOutbox = {
      lister: () => depot.lister(), obtenir: id => depot.obtenir(id),
      inserer: ligne => depot.inserer(ligne), mettreAJour: ligne => depot.mettreAJour(ligne),
      mettreAJourSiInchangee: async (attendue, suivante) => {
        if (suivante.statut === "envoi") { entrerB(); await attenteB; }
        if (suivante.statut === "en_attente") resetsB += 1;
        return depot.mettreAJourSiInchangee(attendue, suivante);
      },
    };
    const fetchA = jest.fn(async () => { entrerA(); return attenteA; });
    const fetchB = jest.fn();
    const generationA = 0;
    let generationB = 0;
    const configuration = { descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
      maintenant: () => HORLOGE.maintenant, session: () => SESSION_DE_TEST };
    const a = creerVidangeur({ ...configuration, depot, fetchImpl: fetchA,
      capturerGardeSession: () => { const capture = generationA; return () => capture === generationA; } });
    const b = creerVidangeur({ ...configuration, depot: depotB, fetchImpl: fetchB,
      capturerGardeSession: () => { const capture = generationB; return () => capture === generationB; } });
    const passeB = b.vidangerFileSortante();
    await entreeB;
    const passeA = a.vidangerFileSortante();
    await entreeA;
    const envoiA = await depot.obtenir(mutation.id);
    generationB += 1;
    libererB();
    const rapportB = await passeB;
    const pendantRpcA = await depot.obtenir(mutation.id);
    libererA(reponseAcceptee());
    const rapportA = await passeA;
    expect(fetchB).not.toHaveBeenCalled();
    expect(resetsB).toBe(0);
    expect(rapportB.arret).toEqual({ genre: "session_changee" });
    expect(envoiA?.statut).toBe("envoi");
    expect(pendantRpcA).toEqual(envoiA);
    expect(fetchA).toHaveBeenCalledTimes(1);
    expect(rapportA.envoyees).toEqual([mutation.id]);
    expect(await depot.obtenir(mutation.id)).toMatchObject({ id: mutation.id, payload: mutation.payload,
      proprietaire: PERSONNE, statut: "envoyee", resumeAccepte: { statut: "sur_site" } });
  });

  test.each(["depart", "garde"])("%s ne remplace jamais une confirmation intercalée avant le CAS", async frontiere => {
    class DepotIntercale extends DepotOutboxMemoire {
      intercaler = false;
      async mettreAJourSiInchangee(...args: Parameters<DepotOutboxMemoire["mettreAJourSiInchangee"]>): Promise<boolean> {
        const [attendue, suivante] = args;
        if (this.intercaler && suivante.statut === (frontiere === "depart" ? "envoi" : "en_attente")) {
          this.intercaler = false;
          const actuelle = await this.obtenir(attendue.id);
          if (!actuelle) throw new Error("FIXTURE-CF037-ABSENTE");
          await this.mettreAJour({ ...actuelle, statut: "envoyee", resumeAccepte: { statut: "sur_site", preuve: "CONFIRMATION-FICTIVE" } });
        }
        return super.mettreAJourSiInchangee(...args);
      }
    }
    const depot = new DepotIntercale();
    const mutation = await inserer(depot, { type: "punch_in", chantierId: "interv-CF037", payload: { action: "arrivee" } });
    depot.intercaler = true;
    let sessions = 0;
    const appelerOutil = jest.fn();
    const vidangeur = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil, fetchImpl: jest.fn(),
      maintenant: () => HORLOGE.maintenant,
      session: () => ++sessions > 1 && frontiere === "garde" ? null : SESSION_DE_TEST });
    const rapport = await vidangeur.vidangerFileSortante();
    expect(appelerOutil).not.toHaveBeenCalled();
    const actuelle = await depot.obtenir(mutation.id);
    expect(actuelle).toMatchObject({ id: mutation.id, payload: mutation.payload, proprietaire: PERSONNE,
      statut: "envoyee", resumeAccepte: { statut: "sur_site", preuve: "CONFIRMATION-FICTIVE" } });
    expect(rapport.envoyees).toEqual([mutation.id]);
    expect(rapport.remisesEnAttente).toEqual([]);
    expect(rapport.echecsPermanents).toEqual([]);
    expect(rapport.resultatsAcceptes).toEqual([{ id: mutation.id, resume: actuelle?.resumeAccepte }]);
    expect(rapport.arret?.genre ?? null).toBe(frontiere === "garde" ? "session_changee" : null);
  });
});

// Target-bound completion ACKs: SDK transport fixtures, no backend/phone execution.
describe("completion ACK target and uncertain series", () => {
  const payload = (id = "I-COMPLETE") => ({ intervention_id: id, horodatage: "2026-10-13T12:00:00+00:00",
    preuves_completion: { checklist_complete: true, photos_apres: ["fichier:sha256:" + "a".repeat(64)], notes: "FICTIF", signature: null }, signature_requise: false });
  const ack = (id: unknown = "I-COMPLETE") => ({ wct_id: "W-FICTIF", intervention_id: id,
    ligne_id: "a".repeat(64), statut: "completed_pending_review", hash_maillon: "b".repeat(64),
    duree_reelle_minutes: 60, ecart_signale: true, tete_chaine: "c".repeat(64) });
  const completion = (depot: DepotOutboxMemoire, id = "I-COMPLETE") => inserer(depot,
    { type: "job_completion", chantierId: id, payload: payload(id) });

  test("matching target stores only the original intention and eight-field ACK", async () => {
    const depot = new DepotOutboxMemoire(), first = await completion(depot);
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee(ack()));
    const driver = creerVidangeur(creerConfig(depot, fetchImpl, () => HORLOGE.maintenant));
    expect((await driver.vidangerFileSortante()).envoyees).toEqual([first.id]);
    expect(await depot.obtenir(first.id)).toMatchObject({ id: first.id, proprietaire: PERSONNE, payload: first.payload,
      statut: "envoyee", resumeAccepte: ack() });
    expect(Object.keys(ack()).sort()).toEqual(["wct_id", "intervention_id", "ligne_id", "statut", "hash_maillon",
      "duree_reelle_minutes", "ecart_signale", "tete_chaine"].sort());
  });

  test.each(["I-FOREIGN", null, undefined, ""])("ACK target %j retains UUID/body without an accepted result", async target => {
    const depot = new DepotOutboxMemoire(), first = await completion(depot);
    const fetchImpl = jest.fn().mockResolvedValue(reponseAcceptee({ ...ack(), intervention_id: target }));
    const driver = creerVidangeur(creerConfig(depot, fetchImpl, () => HORLOGE.maintenant));
    const report = await driver.vidangerFileSortante();
    expect(report.envoyees).toEqual([]); expect(report.resultatsAcceptes).toEqual([]);
    expect(await depot.obtenir(first.id)).toMatchObject({ id: first.id, proprietaire: PERSONNE, payload: first.payload,
      statut: "en_attente", resumeAccepte: null });
  });

  test("unknown original blocks next same job, independent job proceeds, correct retry keeps UUID/body", async () => {
    const depot = new DepotOutboxMemoire(), first = await completion(depot), second = await completion(depot);
    const other = await completion(depot, "I-OTHER"); let now = new Date(HORLOGE.maintenant);
    let unknown = true;
    const fetchImpl = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body));
      return request.idempotencyKey === first.id && unknown ? reponseHttp(200, { ok: true, result: {} }) :
        reponseAcceptee(ack(request.args.intervention_id));
    });
    const driver = creerVidangeur(creerConfig(depot, fetchImpl, () => now));
    const initial = await driver.vidangerFileSortante();
    expect(initial.envoyees).toEqual([other.id]); expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(await depot.obtenir(first.id)).toMatchObject({ id: first.id, payload: first.payload, statut: "en_attente" });
    expect(await depot.obtenir(second.id)).toMatchObject({ statut: "en_attente", tentatives: 0 });
    unknown = false; now = new Date(now.getTime() + 60000);
    const retry = await driver.vidangerFileSortante(); expect(retry.envoyees).toEqual([first.id]);
    expect(await depot.obtenir(second.id)).toMatchObject({ statut: "en_attente", tentatives: 0 });
    const requests = fetchImpl.mock.calls.map(call => JSON.parse(String(call[1]?.body))).filter(r => r.idempotencyKey === first.id);
    expect(requests).toHaveLength(2); expect(requests[0]).toEqual(requests[1]);
    expect(await depot.obtenir(first.id)).toMatchObject({ id: first.id, payload: first.payload, proprietaire: PERSONNE });
    expect((await driver.vidangerFileSortante()).envoyees).toEqual([second.id]);
    expect(await depot.obtenir(second.id)).toMatchObject({ id: second.id, payload: second.payload, statut: "envoyee" });
  });

  test("restored sent receipt for foreign target blocks same job but preserves another job", async () => {
    const depot = new DepotOutboxMemoire(), original = await completion(depot);
    await depot.mettreAJour({ ...original, statut: "envoyee", resumeAccepte: ack("I-FOREIGN") });
    const next = await completion(depot), other = await completion(depot, "I-OTHER");
    const fetchImpl = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) => reponseAcceptee(ack(JSON.parse(String(init?.body)).args.intervention_id)));
    const report = await creerVidangeur(creerConfig(depot, fetchImpl, () => HORLOGE.maintenant)).vidangerFileSortante();
    expect(report.envoyees).toEqual([other.id]); expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(await depot.obtenir(next.id)).toMatchObject({ statut: "en_attente", tentatives: 0 });
    expect(await depot.obtenir(original.id)).toMatchObject({ statut: "envoyee", resumeAccepte: ack("I-FOREIGN") });
  });
});
