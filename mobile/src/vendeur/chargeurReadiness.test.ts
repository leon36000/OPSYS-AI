import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { ConfigurationChargeurVendeur } from "./appel";
import { OUTIL_EVALUER_READINESS } from "../m2/readiness";
import { chargerReadiness, memeSessionReadiness, resultatSiMemeSession } from "./chargeurReadiness";
import {
  echecHttp,
  enveloppeAcceptee,
  enveloppeRefusee,
  fauxTransport,
  transportHorsLigne,
} from "./donneesDeTest";

const LEAD = "lead-a-01";
const HORLOGE = { maintenant: new Date("2026-10-05T18:03:22.000Z"), decalageMinutesUTC: -240 };
const MARQUEUR = {
  readiness_ok: true,
  lead_id: LEAD,
  hash_tete_registre: "a".repeat(64),
  empreinte: "b".repeat(64),
  horodatage: "2026-10-05T14:03:22-04:00",
};

function config(appelerOutil: jest.Mock, depot = new DepotCleValeurMemoire()): ConfigurationChargeurVendeur {
  return {
    depot,
    appelerOutil,
    fetchImpl: jest.fn() as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-vendeur",
    personne: "vendeur.a",
    horloge: () => HORLOGE,
  };
}

describe("chargeur readiness — lecture M2 sans cache", () => {
  test("appelle l'outil vendeur avec l'heure locale et aucun champ de mutation", async () => {
    const transport = fauxTransport({ [OUTIL_EVALUER_READINESS]: () => enveloppeAcceptee(MARQUEUR) });
    const depot = new DepotCleValeurMemoire();
    const lire = jest.spyOn(depot, "lire");
    const ecrire = jest.spyOn(depot, "ecrire");

    const resultat = await chargerReadiness(config(transport, depot), LEAD);

    expect(resultat.genre).toBe("pret");
    expect(transport.mock.calls[0][0].requete).toEqual({
      tool: "m2_evaluer_readiness",
      args: { lead_id: LEAD, horodatage: "2026-10-05T14:03:22-04:00" },
    });
    expect(transport.mock.calls[0][0].requete.idempotencyKey).toBeUndefined();
    expect(lire).not.toHaveBeenCalled();
    expect(ecrire).not.toHaveBeenCalled();
  });

  test("préserve le refus métier et les refus HTTP/auth comme refus, sans cache", async () => {
    const refusMetier = await chargerReadiness(
      config(fauxTransport({ [OUTIL_EVALUER_READINESS]: () => enveloppeRefusee("REJ-TRANSITION-ILLEGALE", "ville manquante") })),
      LEAD,
    );
    expect(refusMetier).toEqual({ genre: "refus", verdict: { code: "REJ-TRANSITION-ILLEGALE", detail: "ville manquante" } });

    for (const [status, code] of [[401, "unauthorized"], [403, "tool_call_blocked"]] as const) {
      const refusAuth = await chargerReadiness(config(jest.fn(async () => echecHttp(status, code, "appareil refusé"))), LEAD);
      expect(refusAuth).toMatchObject({ genre: "refus", verdict: { code } });
    }
  });

  test("panne réseau, outil hors portée ou réponse illisible: non vérifiée, aucun ancien marqueur servi", async () => {
    const depot = new DepotCleValeurMemoire();
    const ecrire = jest.spyOn(depot, "ecrire");
    const horsLigne = await chargerReadiness(config(transportHorsLigne(), depot), LEAD);
    expect(horsLigne).toMatchObject({ genre: "non_verifie", verdict: { code: "erreur_reseau" } });

    const horsPortee = await chargerReadiness(config(jest.fn(async () => echecHttp(403, "tool_call_blocked")), depot), LEAD);
    expect(horsPortee).toMatchObject({ genre: "refus", verdict: { code: "tool_call_blocked" } });

    const illisible = await chargerReadiness(config(fauxTransport({ [OUTIL_EVALUER_READINESS]: () => enveloppeAcceptee({ ...MARQUEUR, empreinte: "bad" }) }), depot), LEAD);
    expect(illisible).toMatchObject({ genre: "non_verifie", verdict: { code: "reponse_illisible" } });
    expect(ecrire).not.toHaveBeenCalled();
    expect(depot.cles()).toEqual([]);
  });
});

describe("cohérence de session pour la readiness", () => {
  const session = { urlBase: "https://grs.exemple.ca", jeton: "jeton-vendeur", appareilId: "appareil-a", personne: "vendeur.a" };
  const configAppel = { urlBase: session.urlBase, jeton: session.jeton, personne: session.personne };

  test("autorise seulement la même URL, le même jeton et la même personne après la lecture", () => {
    expect(memeSessionReadiness(configAppel, session)).toBe(true);
    expect(memeSessionReadiness(configAppel, { ...session, jeton: "nouveau-jeton" })).toBe(false);
    expect(memeSessionReadiness(configAppel, { ...session, urlBase: "https://autre.exemple.ca" })).toBe(false);
    expect(memeSessionReadiness(configAppel, { ...session, personne: "vendeur.b" })).toBe(false);
    expect(memeSessionReadiness(configAppel, null)).toBe(false);
  });

  test.each<[string, Partial<typeof session>]>([
    ["jeton remplacé", { jeton: "nouveau-jeton" }],
    ["personne remplacée", { personne: "vendeur.b" }],
  ])("rejette une réponse différée après %s", async (_nom, changement) => {
    let sessionCourante: typeof session | null = session;
    let terminer!: (valeur: { readonly personne: string }) => void;
    const attente = new Promise<{ readonly personne: string }>((resolve) => {
      terminer = resolve;
    });
    const gardee = attente.then((valeur) =>
      resultatSiMemeSession(configAppel, sessionCourante, valeur),
    );

    sessionCourante = { ...session, ...changement };
    terminer({ personne: "vendeur.a" });

    expect(await gardee).toBeNull();
  });
});
