import { creerChargeurApprobations, OUTIL_LISTER_DEMANDES } from "./chargeur";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";

const RESULTAT_LISTE = {
  ok: true,
  resultat: {
    accepte: true,
    resultat: { demandes: [], total_en_attente: 0, affichees: 0, reste: 0, proprietaire: true },
  },
};

function creer(appel: (p: ParametresAppelOutil) => Promise<ResultatAppelOutil>) {
  const appelerOutil = jest.fn(appel);
  const chargeur = creerChargeurApprobations({
    appelerOutil,
    fetchImpl: jest.fn() as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-test",
  });
  return { chargeur, appelerOutil };
}

describe("chargeur des demandes d'approbation", () => {
  test("appelle m9_lister_demandes_approbation sans argument, sans clé d'idempotence (lecture seule)", async () => {
    const { chargeur, appelerOutil } = creer(async () => ({ ok: true, result: RESULTAT_LISTE }));

    const resultat = await chargeur.chargerDemandes();

    expect(resultat).toMatchObject({ source: "serveur", liste: { totalEnAttente: 0, proprietaire: true } });
    expect(appelerOutil).toHaveBeenCalledTimes(1);
    const params = appelerOutil.mock.calls[0][0];
    expect(params.urlBase).toBe("https://grs.exemple.ca");
    expect(params.jeton).toBe("jeton-test");
    expect(params.requete).toEqual({ tool: OUTIL_LISTER_DEMANDES, args: {} });
    expect(OUTIL_LISTER_DEMANDES).toBe("m9_lister_demandes_approbation");
    expect(params.requete.idempotencyKey).toBeUndefined();
  });

  test("hors ligne : aucune liste (pas de cache, fail-closed), le verdict dit pourquoi", async () => {
    const { chargeur } = creer(async () => ({
      ok: false,
      echec: { origine: "reseau", reessayable: true, message: "Network request failed" },
    }));

    expect(await chargeur.chargerDemandes()).toEqual({
      source: "aucune",
      raison: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });

  test("refus HTTP du core (rôle hors portée) : le type et le message du core sont repris", async () => {
    const { chargeur } = creer(async () => ({
      ok: false,
      echec: {
        origine: "http",
        reessayable: false,
        message: "refus",
        status: 403,
        erreur: { type: "tool_call_blocked", message: "OPSYS device is not authorized (tool_out_of_scope)." },
      },
    }));

    expect(await chargeur.chargerDemandes()).toEqual({
      source: "aucune",
      raison: { code: "tool_call_blocked", detail: "OPSYS device is not authorized (tool_out_of_scope)." },
    });
  });

  test("verdict du serveur (personne inactive) : repris tel quel, jamais une liste vide", async () => {
    const { chargeur } = creer(async () => ({
      ok: true,
      result: { ok: true, resultat: { accepte: false, verdict: { code: "identite_invalide", detail: "Personne inactive." } } },
    }));

    expect(await chargeur.chargerDemandes()).toEqual({
      source: "aucune",
      raison: { code: "identite_invalide", detail: "Personne inactive." },
    });
  });

  test("réponse illisible : reponse_illisible, jamais « aucune demande »", async () => {
    const { chargeur } = creer(async () => ({ ok: true, result: { ok: true, resultat: "?" } }));

    const resultat = await chargeur.chargerDemandes();

    expect(resultat).toMatchObject({ source: "aucune", raison: { code: "reponse_illisible" } });
  });
});
