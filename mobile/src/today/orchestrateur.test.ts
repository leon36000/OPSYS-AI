import { creerChargeurChantiers } from "./orchestrateur";
import { lireCacheChantiers } from "./cache";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { invoquerOutil } from "../protocole/client";
import type { InterventionM4 } from "../m4/interventions";

/** Même patron que src/outbox/vidangeur.test.ts. */
function reponseHttp(status: number, corps: unknown, ok = status >= 200 && status < 300): Response {
  return { ok, status, json: async () => corps } as unknown as Response;
}

function reponseListe(interventions: InterventionM4[]): Response {
  return reponseHttp(200, { ok: true, result: { ok: true, resultat: interventions } });
}

const INTERVENTIONS: InterventionM4[] = [
  { intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "gouttieres", devis_id: null },
  { intervention_id: "I2", statut: "completed_verified", lead_id: "L2", type_travaux: "revetement", devis_id: "D2" },
  { intervention_id: "I3", statut: "en_route", lead_id: "L3", type_travaux: "soffite_fascia", devis_id: null },
];

function creerConfig(depot: DepotCleValeurMemoire, fetchImpl: typeof fetch, maintenant: () => Date) {
  return {
    depot,
    appelerOutil: invoquerOutil,
    fetchImpl,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-test",
    maintenant,
  };
}

describe("chargerChantiersAujourdhui — en ligne", () => {
  test("succès : source serveur, cache écrit, filtré aux statuts actifs", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseListe(INTERVENTIONS));
    const maintenant = () => new Date("2026-09-28T12:00:00.000Z");
    const chargeur = creerChargeurChantiers(creerConfig(depot, fetchImpl as unknown as typeof fetch, maintenant));

    const resultat = await chargeur.chargerChantiersAujourdhui();

    expect(resultat.source).toBe("serveur");
    if (resultat.source === "serveur") {
      expect(resultat.items.map((i) => i.intervention_id)).toEqual(["I3", "I1"]); // en_route avant planifiee
      expect(resultat.misAJourLe).toBe("2026-09-28T12:00:00.000Z");
    }

    // Le cache écrit contient TOUTES les interventions reçues, pas seulement les actives — le
    // filtrage reste une décision de lecture, jamais d'écriture (voir types.ts).
    const cache = await lireCacheChantiers(depot);
    expect(cache?.interventions).toHaveLength(3);
  });

  test("appel HTTP porte bien le bon outil, aucun argument inventé", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseListe([]));
    const chargeur = creerChargeurChantiers(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => new Date("2026-09-28T12:00:00.000Z")),
    );
    await chargeur.chargerChantiersAujourdhui();
    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    const corps = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(corps.tool).toBe("m4_lister_interventions");
    expect(corps.args).toEqual({});
  });
});

describe("chargerChantiersAujourdhui — hors ligne / échec, retombée sur le cache", () => {
  test("échec réseau avec un cache déjà présent : source cache, items filtrés, raison portée", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(
      "today_chantiers_v1",
      JSON.stringify({ interventions: INTERVENTIONS, misAJourLe: "2026-09-28T08:00:00.000Z" }),
    );
    const fetchImpl = jest.fn().mockRejectedValueOnce(new TypeError("Network request failed"));
    const chargeur = creerChargeurChantiers(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => new Date("2026-09-28T12:00:00.000Z")),
    );

    const resultat = await chargeur.chargerChantiersAujourdhui();

    expect(resultat.source).toBe("cache");
    if (resultat.source === "cache") {
      expect(resultat.items.map((i) => i.intervention_id)).toEqual(["I3", "I1"]);
      expect(resultat.misAJourLe).toBe("2026-09-28T08:00:00.000Z");
      expect(resultat.raisonHorsLigne.code).toBe("erreur_reseau");
    }
  });

  test("échec réseau SANS cache : source aucune, jamais une liste inventée", async () => {
    const depot = new DepotCleValeurMemoire();
    const fetchImpl = jest.fn().mockRejectedValueOnce(new TypeError("Network request failed"));
    const chargeur = creerChargeurChantiers(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => new Date("2026-09-28T12:00:00.000Z")),
    );

    const resultat = await chargeur.chargerChantiersAujourdhui();
    expect(resultat).toEqual({
      source: "aucune",
      raisonHorsLigne: { code: "erreur_reseau", detail: "Network request failed" },
    });
  });

  test("échec technique de l'outil (ok:false) : retombe aussi sur le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(
      "today_chantiers_v1",
      JSON.stringify({ interventions: [INTERVENTIONS[0]], misAJourLe: "2026-09-28T08:00:00.000Z" }),
    );
    const fetchImpl = jest
      .fn()
      .mockResolvedValueOnce(reponseHttp(200, { ok: true, result: { ok: false, erreur: "refus_metier", details: "statut invalide" } }));
    const chargeur = creerChargeurChantiers(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => new Date("2026-09-28T12:00:00.000Z")),
    );

    const resultat = await chargeur.chargerChantiersAujourdhui();
    expect(resultat.source).toBe("cache");
    if (resultat.source === "cache") {
      expect(resultat.raisonHorsLigne).toEqual({ code: "refus_metier", detail: "statut invalide" });
    }
  });

  test("une nouvelle réussite après un échec remplace le cache, pas une fusion", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire(
      "today_chantiers_v1",
      JSON.stringify({ interventions: INTERVENTIONS, misAJourLe: "2026-09-28T08:00:00.000Z" }),
    );
    const fetchImpl = jest.fn().mockResolvedValueOnce(reponseListe([INTERVENTIONS[0]]));
    const chargeur = creerChargeurChantiers(
      creerConfig(depot, fetchImpl as unknown as typeof fetch, () => new Date("2026-09-28T13:00:00.000Z")),
    );

    const resultat = await chargeur.chargerChantiersAujourdhui();
    expect(resultat.source).toBe("serveur");
    const cache = await lireCacheChantiers(depot);
    expect(cache?.interventions).toEqual([INTERVENTIONS[0]]);
  });
});
