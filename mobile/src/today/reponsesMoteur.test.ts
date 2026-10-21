import fs from "node:fs";
import path from "node:path";

import { estInterventionM4, interpreterResultatListerInterventions, interpreterResultatStatutIntervention } from "../m4/interventions";
import type { InterventionM4, StatutInterventionM4 } from "../m4/interventions";
import { invoquerOutil } from "../protocole/client";
import { VERDICT_REPONSE_TRONQUEE } from "../protocole/enveloppeOutil";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { ecrireCacheChantiers, lireCacheChantiers } from "./cache";
import { creerChargeurChantiers } from "./orchestrateur";
import { ETATS_ACTIFS_AUJOURDHUI } from "./selection";
import { obtenirStatutChantier } from "./statut";

/**
 * Les vraies réponses du moteur (`m4_lister_interventions` et `m4_statut_intervention` par la porte d'appareil `employee`,
 * capturées par `tests/e2e/test_liste_employe_appareil.py` : `today/fixtures/reponses-moteur.json`) passent par les
 * lecteurs et l'orchestrateur de l'app (PLAN T1.4-n, constats 1 et 2). La liste de 26 chantiers planifiés est COUPÉE par le
 * socle : l'app ne la lit ni comme vide ni comme complète, et ne remplace jamais son cache par elle. Un employé
 * désactivé reçoit un REFUS : le cache ne le remplace jamais.
 */

interface Fixture {
  readonly fictif: boolean;
  readonly appels: Record<string, { readonly outil: string; readonly args: Record<string, string> }>;
  readonly reponses: Record<string, any>;
}

const FIXTURE: Fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "reponses-moteur.json"), "utf8"));

const PERSONNE = "etienne";
const MAINTENANT = () => new Date("2026-09-28T12:00:00.000Z");

function reponseHttp(corps: unknown): Response {
  return { ok: true, status: 200, json: async () => corps } as unknown as Response;
}

/** Un serveur qui rejoue les réponses ENREGISTRÉES : pour chaque statut demandé, la réponse dont le nom est donné. */
function serveurRejoue(nomParStatut: Partial<Record<StatutInterventionM4, string>>) {
  return jest.fn(async (_url: string, init: RequestInit) => {
    const { tool, args } = JSON.parse(init.body as string) as { tool: string; args: { statut: StatutInterventionM4 } };
    expect(tool).toBe("m4_lister_interventions");
    const nom = nomParStatut[args.statut];
    if (nom === undefined) {
      throw new Error(`aucune réponse enregistrée pour le statut ${args.statut}`);
    }
    return reponseHttp({ ok: true, result: FIXTURE.reponses[nom] });
  });
}

function chargeur(depot: DepotCleValeurMemoire, fetchImpl: jest.Mock) {
  return creerChargeurChantiers({
    depot,
    appelerOutil: invoquerOutil,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-test",
    personne: PERSONNE,
    maintenant: MAINTENANT,
  });
}

const CHANTIERS_DE_LA_JOURNEE: Partial<Record<StatutInterventionM4, string>> = {
  en_route: "interventions_en_route",
  sur_site: "interventions_sur_site",
  en_revue: "interventions_en_revue",
  planifiee: "interventions_planifiee_tronquee",
};

const REFUS_DU_SERVEUR: Partial<Record<StatutInterventionM4, string>> = {
  en_route: "refus_identite_interventions",
  sur_site: "refus_identite_interventions",
  en_revue: "refus_identite_interventions",
  planifiee: "refus_identite_interventions",
};

function chantierEnRoute(): InterventionM4 {
  const [intervention] = FIXTURE.reponses.interventions_en_route.resultat;
  return intervention as InterventionM4;
}

async function depotAvecCache(interventions: readonly InterventionM4[]): Promise<DepotCleValeurMemoire> {
  const depot = new DepotCleValeurMemoire();
  await ecrireCacheChantiers(depot, PERSONNE, { interventions, misAJourLe: "2026-09-28T08:00:00.000Z" });
  return depot;
}

describe("les réponses réelles du moteur : les chantiers de l'employé", () => {
  test("la fixture est fictive, lue sous le nom nu des deux outils de l'écran", () => {
    expect(FIXTURE.fictif).toBe(true);
    expect(new Set(Object.values(FIXTURE.appels).map((appel) => appel.outil))).toEqual(
      new Set(["m4_lister_interventions", "m4_statut_intervention"]),
    );
  });

  test("les quatre statuts demandés par l'écran sont ceux de la fixture, dans l'ordre de l'app", () => {
    expect([...ETATS_ACTIFS_AUJOURDHUI]).toEqual(["en_route", "sur_site", "en_revue", "planifiee"]);
    expect(Object.keys(CHANTIERS_DE_LA_JOURNEE)).toEqual([...ETATS_ACTIFS_AUJOURDHUI]);
    for (const [statut, nom] of Object.entries(CHANTIERS_DE_LA_JOURNEE)) {
      expect(FIXTURE.appels[nom as string].args).toEqual({ statut });
    }
  });

  describe("la liste coupée par le socle", () => {
    test.each(["interventions_planifiee_tronquee", "interventions_sans_filtre_tronquee"])(
      "%s : n'est ni une liste vide ni une liste complète, et dit qu'elle est coupée",
      (nom) => {
        const brut = FIXTURE.reponses[nom];
        // Ce que le socle rend : exactement ces trois clés, jamais `resultat`.
        expect(Object.keys(brut).sort()).toEqual(["apercu", "ok", "tronque"]);
        expect(interpreterResultatListerInterventions(brut)).toEqual({ ok: false, genre: "tronquee", verdict: VERDICT_REPONSE_TRONQUEE });
      },
    );

    test("la vraie forme n'a pas de `resultat` : elle n'est jamais lue comme « aucune intervention »", () => {
      const brut = FIXTURE.reponses.interventions_planifiee_tronquee;
      expect(brut.resultat).toBeUndefined();
      expect(interpreterResultatListerInterventions(brut).ok).toBe(false);
    });

    test("les groupes qui tiennent sous la borne sont lus en entier : le chantier en route, et deux groupes vides", () => {
      const enRoute = interpreterResultatListerInterventions(FIXTURE.reponses.interventions_en_route);
      expect(enRoute).toMatchObject({ ok: true });
      expect(enRoute.ok && enRoute.interventions).toHaveLength(1);
      expect(estInterventionM4(chantierEnRoute())).toBe(true);
      for (const nom of ["interventions_sur_site", "interventions_en_revue"]) {
        expect(interpreterResultatListerInterventions(FIXTURE.reponses[nom])).toEqual({ ok: true, interventions: [] });
      }
    });
  });

  describe("l'orchestrateur rejoue ces réponses, un appel par statut", () => {
    test("le groupe coupé : « incomplète », les autres groupes en entier, et RIEN n'est écrit au cache", async () => {
      const depot = new DepotCleValeurMemoire();
      const fetchImpl = serveurRejoue(CHANTIERS_DE_LA_JOURNEE);

      const resultat = await chargeur(depot, fetchImpl).chargerChantiersAujourdhui();

      expect(fetchImpl).toHaveBeenCalledTimes(4);
      expect(resultat).toEqual({
        source: "incomplet",
        items: [chantierEnRoute()],
        groupesIncomplets: ["planifiee"],
        misAJourLe: "2026-09-28T12:00:00.000Z",
      });
      expect(await lireCacheChantiers(depot, PERSONNE)).toBeNull();
    });

    test("le cache d'avant n'est ni servi à la place ni écrasé par la lecture coupée", async () => {
      const avant = [chantierEnRoute()];
      const depot = await depotAvecCache(avant);

      const resultat = await chargeur(depot, serveurRejoue(CHANTIERS_DE_LA_JOURNEE)).chargerChantiersAujourdhui();

      expect(resultat.source).toBe("incomplet");
      expect(await lireCacheChantiers(depot, PERSONNE)).toEqual({ interventions: avant, misAJourLe: "2026-09-28T08:00:00.000Z" });
    });

    test("un employé désactivé : un REFUS avec le verdict d'identité du serveur, jamais le cache, rien d'écrit", async () => {
      const avant = [chantierEnRoute()];
      const depot = await depotAvecCache(avant);

      const resultat = await chargeur(depot, serveurRejoue(REFUS_DU_SERVEUR)).chargerChantiersAujourdhui();

      expect(resultat.source).toBe("refus");
      expect(resultat.source === "refus" && resultat.verdict.detail).toContain("REJ-IDENTITE-APPAREIL-INVALIDE");
      expect(await lireCacheChantiers(depot, PERSONNE)).toEqual({ interventions: avant, misAJourLe: "2026-09-28T08:00:00.000Z" });
    });

    test("un refus dans UN groupe suffit : il l'emporte sur un groupe coupé", async () => {
      const resultat = await chargeur(
        new DepotCleValeurMemoire(),
        serveurRejoue({ ...CHANTIERS_DE_LA_JOURNEE, sur_site: "refus_identite_interventions" }),
      ).chargerChantiersAujourdhui();
      expect(resultat.source).toBe("refus");
    });
  });

  describe("le statut d'un chantier", () => {
    function fetchStatut(nom: string) {
      return jest.fn(async () => reponseHttp({ ok: true, result: FIXTURE.reponses[nom] })) as unknown as typeof fetch;
    }
    const config = (depot: DepotCleValeurMemoire, fetchImpl: typeof fetch) => ({
      depot,
      appelerOutil: invoquerOutil,
      fetchImpl,
      urlBase: "https://grs.exemple.ca",
      jeton: "jeton-test",
      personne: PERSONNE,
    });

    test("le statut lu par le serveur est celui de M4", async () => {
      const id = chantierEnRoute().intervention_id;
      expect(interpreterResultatStatutIntervention(FIXTURE.reponses.statut_intervention)).toEqual({
        ok: true,
        intervention_id: id,
        statut: "en_route",
      });
      expect(await obtenirStatutChantier(config(new DepotCleValeurMemoire(), fetchStatut("statut_intervention")), id)).toEqual({
        source: "serveur",
        statut: "en_route",
      });
    });

    test("un employé désactivé : un refus, jamais le statut de la copie gardée", async () => {
      const chantier = chantierEnRoute();
      const depot = await depotAvecCache([chantier]);
      const resultat = await obtenirStatutChantier(config(depot, fetchStatut("refus_identite_statut")), chantier.intervention_id);
      expect(resultat.source).toBe("refus");
      expect(resultat.source === "refus" && resultat.verdict.detail).toContain("REJ-IDENTITE-APPAREIL-INVALIDE");
    });
  });
});
