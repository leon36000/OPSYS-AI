import fs from "node:fs";
import path from "node:path";

import { creerDeclencheurVidange } from "./declenchement";
import { DepotOutboxMemoire } from "./depot";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerMutation, soumettreMutation } from "./mutation";
import { avecProprietaire, ErreurSansPersonneConfirmee } from "./proprietaire";
import { ecouterRefusAppareil } from "./refusAppareil";
import { creerVidangeur } from "./vidangeur";
import { synchroniserPersonneConfirmee } from "../identite/sessionEnvoi";
import { invoquerOutil } from "../protocole/client";
import { definirConfigurationAppel, definirPersonneConfirmee, obtenirSessionEnvoi } from "../protocole/configuration";
import type { ConfigurationAppel } from "../protocole/configuration";
import type { MutationOutbox } from "./types";

/**
 * Le câblage réel de PLAN T1.4-l, moins le natif : la configuration et la personne confirmée
 * (`configuration.ts`, `sessionEnvoi.ts`), le dépôt qui pose le propriétaire, le vidangeur qui relit la
 * session à chaque envoi, le déclencheur qui signale un refus d'appareil. Seuls le réseau (`fetch`) et
 * SQLite sont remplacés. Chaque test suit UN appareil à travers ses appairages successifs.
 */

const HORLOGE = { maintenant: new Date("2026-09-29T12:00:00.000Z"), decalageMinutesUTC: -240 };
let compteur = 0;
const idDeterministe = () => `mut-${++compteur}`;

const URL_BASE = "https://grs.exemple.ca";
const APPAREIL = "APPAREIL-1";

function reponseHttp(status: number, corps: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => corps } as unknown as Response;
}
const acceptee = () =>
  reponseHttp(200, { ok: true, result: { ok: true, resultat: { accepte: true, resultat: { statut: "sur_site" } }, rejoue: false } });
const refuse401 = () => reponseHttp(401, { error: { message: "Unauthorized", type: "unauthorized" } });

function autorisation(fetchImpl: jest.Mock, i: number): string {
  return ((fetchImpl.mock.calls[i][1] as RequestInit).headers as Record<string, string>).authorization;
}

/** Ce que fait l'écran d'appairage : la nouvelle configuration est posée, l'identité est en lecture. */
function apparier(jeton: string): ConfigurationAppel {
  const configuration = { urlBase: URL_BASE, jeton, appareilId: APPAREIL };
  definirConfigurationAppel(configuration);
  synchroniserPersonneConfirmee({ genre: "en_lecture" }, configuration);
  return configuration;
}

/** Ce que fait le cycle d'identité quand le serveur a répondu 200 pour ce jeton. */
function confirmerIdentite(configuration: ConfigurationAppel, personne: string): void {
  synchroniserPersonneConfirmee(
    { genre: "confirmee", identite: { appareilId: APPAREIL, personne, role: "employee" } },
    configuration,
  );
}

function creerBanc() {
  let maintenant = HORLOGE.maintenant;
  const base = new DepotOutboxMemoire();
  const depot = avecProprietaire(base, () => obtenirSessionEnvoi()?.personne ?? null, () => obtenirSessionEnvoi()?.urlBase ?? null);
  const fetchImpl = jest.fn();
  const vidangeur = creerVidangeur({
    depot,
    descripteurs: DESCRIPTEURS_MUTATION,
    appelerOutil: invoquerOutil,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    session: obtenirSessionEnvoi,
    maintenant: () => maintenant,
  });
  const declencher = creerDeclencheurVidange({
    sessionDisponible: () => obtenirSessionEnvoi() !== null,
    obtenirVidangeur: async () => vidangeur,
  });
  /** Une mutation créée par un écran, soumise, puis mise en file — comme `punch.tsx`. */
  async function mettreEnFile(action: string): Promise<MutationOutbox> {
    const brouillon = creerMutation(
      { type: "punch_in", chantierId: "interv-1", payload: { action } },
      idDeterministe,
      HORLOGE,
    );
    return depot.inserer(soumettreMutation(brouillon));
  }
  /** Laisse passer le recul exponentiel d'un échec réseau (« le réseau est revenu »). */
  function avancerHorloge(ms: number): void {
    maintenant = new Date(maintenant.getTime() + ms);
  }
  return { base, depot, fetchImpl, declencher, mettreEnFile, avancerHorloge };
}

beforeEach(() => {
  compteur = 0;
  definirConfigurationAppel(null);
  definirPersonneConfirmee(null);
});

afterEach(() => {
  definirConfigurationAppel(null);
  definirPersonneConfirmee(null);
});

describe("un appareil à travers ses appairages successifs", () => {
  test("même personne, nouveau jeton : rien ne part avant que le serveur confirme CE jeton, puis tout part avec lui", async () => {
    const { base, fetchImpl, declencher, mettreEnFile, avancerHorloge } = creerBanc();
    const premier = apparier("jeton-1");
    confirmerIdentite(premier, "jdupont");
    const m1 = await mettreEnFile("arrivee");
    const m2 = await mettreEnFile("depart");
    // Hors ligne : les deux restent en file, essayées avec le jeton du moment.
    fetchImpl.mockRejectedValue(new TypeError("Network request failed"));
    await declencher();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(autorisation(fetchImpl, 0)).toBe("Bearer jeton-1");

    // « Appairer de nouveau » : nouveau jeton, identité pas encore relue. Le réseau est revenu.
    const second = apparier("jeton-2");
    avancerHorloge(60_000);
    fetchImpl.mockResolvedValue(acceptee());
    expect(await declencher()).toBeNull();
    expect(fetchImpl).toHaveBeenCalledTimes(2); // aucun envoi, ni avec l'ancien jeton ni avec le nouveau

    // Le serveur confirme la même personne pour le nouveau jeton.
    confirmerIdentite(second, "jdupont");
    const rapport = await declencher();

    expect(rapport?.envoyees).toEqual([m1.id, m2.id]);
    expect(rapport?.quarantaine).toEqual([]);
    expect(autorisation(fetchImpl, 2)).toBe("Bearer jeton-2");
    expect(autorisation(fetchImpl, 3)).toBe("Bearer jeton-2");
    expect((await base.obtenir(m1.id))?.statut).toBe("envoyee");
  });

  test("autre personne : ses mutations restent en quarantaine, celles de la nouvelle partent, l'ancienne les retrouve à son retour", async () => {
    const { base, fetchImpl, declencher, mettreEnFile } = creerBanc();
    const premier = apparier("jeton-1");
    confirmerIdentite(premier, "jdupont");
    const deJdupont = await mettreEnFile("arrivee");

    const second = apparier("jeton-2");
    confirmerIdentite(second, "mtremblay");
    const deMtremblay = await mettreEnFile("arrivee");
    fetchImpl.mockResolvedValue(acceptee());

    const rapport = await declencher();

    expect(rapport?.envoyees).toEqual([deMtremblay.id]);
    expect(rapport?.quarantaine).toEqual([deJdupont.id]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(autorisation(fetchImpl, 0)).toBe("Bearer jeton-2");
    const restee = await base.obtenir(deJdupont.id);
    expect(restee?.statut).toBe("en_attente"); // conservée, jamais supprimée
    expect(restee?.proprietaire).toBe("jdupont");

    // jdupont récupère l'appareil : sa mutation part, avec son propre jeton.
    const troisieme = apparier("jeton-3");
    confirmerIdentite(troisieme, "jdupont");
    const retour = await declencher();
    expect(retour?.envoyees).toEqual([deJdupont.id]);
    expect(autorisation(fetchImpl, 1)).toBe("Bearer jeton-3");
  });

  test("révocation : le refus arrête la passe et est signalé ; l'identité refusée coupe l'envoi ; le nouvel appairage le rouvre", async () => {
    const { base, fetchImpl, declencher, mettreEnFile } = creerBanc();
    const signaux = jest.fn();
    const retirer = ecouterRefusAppareil(signaux);
    const premier = apparier("jeton-1");
    confirmerIdentite(premier, "jdupont");
    const m1 = await mettreEnFile("arrivee");
    const m2 = await mettreEnFile("depart");
    fetchImpl.mockResolvedValue(refuse401());

    const rapport = await declencher();

    expect(rapport?.arret?.genre).toBe("appareil_refuse");
    expect(fetchImpl).toHaveBeenCalledTimes(1); // arrêt au premier refus
    expect(signaux).toHaveBeenCalledTimes(1); // l'app relit son identité
    expect((await base.obtenir(m1.id))?.statut).toBe("en_attente");
    expect((await base.obtenir(m2.id))?.statut).toBe("en_attente");

    // La relecture de l'identité reçoit 401 : l'app passe à l'écran d'identité, plus aucune personne.
    synchroniserPersonneConfirmee({ genre: "erreur", motif: "jeton_refuse" }, premier);
    expect(await declencher()).toBeNull();
    expect(fetchImpl).toHaveBeenCalledTimes(1); // plus aucun essai avec le jeton révoqué
    expect(signaux).toHaveBeenCalledTimes(1); // et plus de signal : pas de boucle

    // Nouvel appairage, même personne : la file repart avec le nouveau jeton, mêmes clés d'idempotence.
    const second = apparier("jeton-2");
    confirmerIdentite(second, "jdupont");
    fetchImpl.mockResolvedValue(acceptee());
    const repartie = await declencher();
    expect(repartie?.envoyees).toEqual([m1.id, m2.id]);
    expect(autorisation(fetchImpl, 1)).toBe("Bearer jeton-2");
    retirer();
  });

  test("sans personne confirmée, aucune mutation ne peut être mise en file (jamais une mutation orpheline)", async () => {
    const { base, mettreEnFile } = creerBanc();
    apparier("jeton-1"); // identité pas encore lue

    await expect(mettreEnFile("arrivee")).rejects.toBeInstanceOf(ErreurSansPersonneConfirmee);
    expect(await base.lister()).toEqual([]);
  });
});

describe("le câblage réel de service.ts, SQLite simulé pour le comportement", () => {
  // Quelques invariants structurels lisent la source, comme `ecransSansSaisie.test.ts`, pour que le
  // défaut corrigé par T1.4-l (un jeton gardé jusqu'au redémarrage) ne puisse pas revenir sans faire échouer un test.
  const source = fs.readFileSync(path.join(__dirname, "service.ts"), "utf8");

  test("le vidangeur lit la session courante à chaque envoi, il ne reçoit aucun jeton figé", () => {
    expect(source).toContain("session: obtenirSessionEnvoi,");
    expect(source).not.toMatch(/\bjeton:/);
    expect(source).not.toContain("urlBase:");
    expect(source).not.toContain("appareilId:");
    expect(source).not.toContain("obtenirConfigurationAppel");
  });

  test("le vidangeur est construit une seule fois (un seul verrou), et n'est pas reconstruit selon le jeton", () => {
    expect(source.match(/creerVidangeur\(/g)).toHaveLength(1);
    expect(source).toContain("vidangeurPromesse");
  });

  test("tout écran qui met une mutation en file passe par un dépôt qui pose la personne", () => {
    expect(source).toContain("avecProprietaire(creerDepotOutboxSqlite(base)");
  });

  test("sans session, aucune vidange n'est tentée ; un refus d'appareil est signalé par le déclencheur", async () => {
    const base = new DepotOutboxMemoire();
    const openDatabaseAsync = jest.fn(async () => ({}));
    const fetchImpl = jest.spyOn(globalThis, "fetch").mockResolvedValue(refuse401());
    jest.doMock("expo-sqlite", () => ({ openDatabaseAsync }));
    jest.doMock("./depot.sqlite", () => ({ initialiserSchemaOutbox: jest.fn(async () => undefined),
      creerDepotOutboxSqlite: () => base }));
    try {
      await jest.isolateModulesAsync(async () => {
        const configuration: typeof import("../protocole/configuration") = require("../protocole/configuration");
        const service: typeof import("./service") = require("./service");
        const refus: typeof import("./refusAppareil") = require("./refusAppareil");
        const signal = jest.fn(), retirer = refus.ecouterRefusAppareil(signal);
        try {
          expect(await service.declencherVidange()).toBeNull();
          configuration.definirConfigurationAppel({ urlBase: URL_BASE, jeton: "jeton-fictif", appareilId: APPAREIL });
          // Un appairage seul ne confirme ni la personne ni l'autorité du jeton.
          expect(await service.declencherVidange()).toBeNull();
          expect(openDatabaseAsync).not.toHaveBeenCalled();
          expect(fetchImpl).not.toHaveBeenCalled();
          expect(signal).not.toHaveBeenCalled();
          configuration.definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: APPAREIL,
            personne: "personne.fictive", role: "employee" });
          const m = await avecProprietaire(base, () => "personne.fictive", () => URL_BASE).inserer(soumettreMutation(creerMutation({
            type: "punch_in", chantierId: "chantier-fictif", payload: { action: "arrivee" },
          }, idDeterministe, HORLOGE)));
          expect((await service.declencherVidange())?.arret).toMatchObject({ genre: "appareil_refuse", mutationId: m.id });
          expect(openDatabaseAsync).toHaveBeenCalledTimes(1);
          expect(fetchImpl).toHaveBeenCalledTimes(1);
          expect(new Headers(fetchImpl.mock.calls[0][1]?.headers).get("authorization")).toBe("Bearer jeton-fictif");
          expect(signal).toHaveBeenCalledTimes(1);
          expect(await base.obtenir(m.id)).toMatchObject({ id: m.id, payload: m.payload,
            proprietaire: "personne.fictive", statut: "en_attente", tentatives: 0 });
        } finally { retirer(); }
      });
    } finally {
      fetchImpl.mockRestore();
      jest.dontMock("expo-sqlite");
      jest.dontMock("./depot.sqlite");
    }
  });
});
