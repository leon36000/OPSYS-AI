import { creerChargeurChiffres } from "../admin/chiffres";
import { interpreter } from "../admin/enveloppe";
import { config, reponse } from "../admin/donneesDeTest";
import { lirePrevisionTresorerie } from "../m5/tresorerie";
import type { ResultatAppelOutil } from "../protocole/client";
import {
  capturerSessionLecture,
  definirConfigurationAppel,
  definirPersonneConfirmee,
} from "../protocole/configuration";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { depotSousGardeLecture } from "../stockage/lecturesEnVol";
import { chargerReadiness } from "../vendeur/chargeurReadiness";
import { synchroniserCaches } from "./caches";

function differer<T>() {
  let resoudre!: (value: T) => void;
  const promesse = new Promise<T>((resolve) => {
    resoudre = resolve;
  });
  return { promesse, resoudre };
}
const SESSION = {
  urlBase: "https://passerelle.fictif.test",
  jeton: "jeton-fictif",
  appareilId: "appareil-fictif",
};
const PERSONNE = {
  jeton: SESSION.jeton,
  appareilId: SESSION.appareilId,
  personne: "personne-fictive-a",
};
afterEach(() => {
  definirPersonneConfirmee(null);
  definirConfigurationAppel(null);
});

for (const lecture of ["prevision", "readiness"] as const) {
  for (const changement of ["role", "purge"] as const) {
    test.each(["avant", "pendant"])(
      `${lecture} écarte un changement ${changement} %s l'appel sans cache`,
      async (moment) => {
        definirConfigurationAppel(SESSION);
        definirPersonneConfirmee({
          ...PERSONNE,
          role: lecture === "prevision" ? "admin" : "seller",
        });
        const capture = capturerSessionLecture();
        const depot = new DepotCleValeurMemoire();
        const vue = depotSousGardeLecture(depot, capture.courante);
        const started = differer<void>();
        const reply = differer<ResultatAppelOutil>();
        const transport = jest.fn(async () => {
          started.resoudre();
          return reply.promesse;
        });
        const configuration = config(transport, { depot: vue });
        const invalider = async () => {
          if (changement === "role") definirPersonneConfirmee({ ...PERSONNE, role: "employee" });
          else await synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
        };
        const premiere = interpreter(
          reponse("prevision_longue_page_1"),
          "couple",
          lirePrevisionTresorerie,
        );
        if (!premiere.ok || premiere.valeur.genre !== "prevision")
          throw Error("fixture fictive invalide");
        const prevision = premiere.valeur;
      const charger = () =>
          lecture === "prevision"
            ? creerChargeurChiffres(configuration).chargerSuitePrevision(prevision)
            : chargerReadiness(configuration, "lead-fictif-a");
        if (moment === "avant") await invalider();
        const pending = charger();
        if (moment === "pendant") {
          await started.promesse;
          await invalider();
        }
        reply.resoudre({
          ok: true,
          result:
            lecture === "prevision"
              ? reponse("prevision_longue_page_2")
              : {
                  ok: true,
                  resultat: {
                    accepte: true,
                    resultat: {
                      readiness_ok: true,
                      lead_id: "lead-fictif-a",
                      hash_tete_registre: "a".repeat(64),
                      empreinte: "b".repeat(64),
                      horodatage: "2026-10-06T18:00:00Z",
                    },
                  },
                },
        });
        expect(await pending).toMatchObject({
          genre: lecture === "prevision" ? "echec" : "non_verifie",
          verdict: { code: "lecture_remplacee" },
        });
        expect(transport).toHaveBeenCalledTimes(moment === "avant" ? 0 : 1);
        expect(depot.cles()).toEqual([]);
      },
    );
  }
}
