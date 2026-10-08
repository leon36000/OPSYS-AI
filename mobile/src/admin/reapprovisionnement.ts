import { appelerLecture } from "./appel";
import type { ResultatSection } from "./lecture";
import { invoquerOutil } from "../protocole/client";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import { OUTIL_REAPPROVISIONNEMENT, construireArgumentsReapprovisionnement, lireReapprovisionnement } from "../m6/reapprovisionnement";
import type { ReapprovisionnementM6 } from "../m6/reapprovisionnement";

export interface DependancesReapprovisionnementM6 {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => { readonly enLigne: boolean; readonly courante: () => boolean };
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly horloge: () => Date;
}
const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });

/** Lecture courante liée à sa session et au cycle réseau, sans cache ni effet. */
export function creerChargeurReapprovisionnementM6(d: DependancesReapprovisionnementM6) {
  return {
    chargerReapprovisionnement: async (decalage = 0): Promise<ResultatSection<ReapprovisionnementM6> | null> => {
      let args;
      try { args = construireArgumentsReapprovisionnement(decalage); } catch { return aucune("lecture_indisponible"); }
      const capture = d.capturerSession(), session = capture.session;
      if (!session) return null;
      if (!capture.courante()) return aucune("lecture_remplacee");
      const reseau = d.capturerReseau();
      if (!reseau.enLigne) return aucune("hors_ligne");
      const courante = () => capture.courante() && reseau.courante();
      if (!courante()) return aucune("lecture_remplacee");
      try {
        const appel = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl,
          urlBase: session.urlBase, jeton: session.jeton }, OUTIL_REAPPROVISIONNEMENT, { ...args });
        if (!courante()) return aucune("lecture_remplacee");
        if (appel.genre !== "reponse") return appel.genre === "refuse"
          ? { source: "refus", verdict: appel.verdict } : { source: "aucune", raison: appel.verdict };
        const lu = lireReapprovisionnement(appel.resultat, args);
        if (!courante()) return aucune("lecture_remplacee");
        if (!lu.ok) {
          const verdict = { code: lu.code, detail: lu.detail };
          return lu.code === "reponse_illisible" || lu.code === "reponse_tronquee" || ERREURS_PASSAGERES.includes(lu.code)
            ? { source: "aucune", raison: verdict } : { source: "refus", verdict };
        }
        const date = d.horloge().toISOString();
        return courante() ? { source: "serveur", valeur: lu.value, misAJourLe: date } : aucune("lecture_remplacee");
      } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
    },
  };
}

let connectee = false, generationReseau = 0;
export function actualiserConnectiviteReapprovisionnementM6(valeur: boolean): void {
  if (valeur !== connectee) generationReseau++;
  connectee = valeur;
}
const lectures = creerChargeurReapprovisionnementM6({
  capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => {
    const epoch = generationReseau;
    return { enLigne: connectee, courante: () => connectee && epoch === generationReseau };
  },
  appelerOutil: invoquerOutil, fetchImpl: fetch, horloge: () => new Date(),
});
export const chargerReapprovisionnementM6 = lectures.chargerReapprovisionnement;
