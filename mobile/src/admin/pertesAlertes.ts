import { construireArgumentsPreuves, lirePreuvesPertesWct, OUTIL_PREUVES_PERTES_M6 } from '../m6/preuvesLecture';
import type { PagePreuvesM6 } from '../m6/preuvesLecture';
import { appelerLecture } from "./appel";
import type { ResultatSection } from "./lecture";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import type { Reponse } from "../m7/contrat";
import {
  construireArgumentsListeWct, construireArgumentsPertesWct,
  lireListeWctPertes, lirePertesAlertesWct,
  OUTIL_LISTE_WCT_PERTES, OUTIL_PERTES_ALERTES_WCT,
} from "../m6/pertesAlertes";
import type { ListeWctPertesM6, PertesAlertesWctM6 } from "../m6/pertesAlertes";

export interface DependancesPertesAlertesM6 {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => { readonly enLigne: boolean; readonly courante: () => boolean };
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly horloge: () => Date;
}
const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });

/** Lectures sans dépôt/cache/outbox : toute réponse appartient à sa session et à son cycle réseau. */
export function creerChargeurPertesAlertesM6(d: DependancesPertesAlertesM6) {
  async function lire<T>(outil: string, args: Readonly<Record<string, unknown>>, lecteur: (v: unknown) => Reponse<T>): Promise<ResultatSection<T> | null> {
    const capture = d.capturerSession(), session = capture.session;
    if (!session) return null;
    if (!capture.courante()) return aucune("lecture_remplacee");
    const reseau = d.capturerReseau();
    if (!reseau.enLigne) return aucune("hors_ligne");
    const courante = () => capture.courante() && reseau.courante();
    if (!courante()) return aucune("lecture_remplacee");
    try {
      const appel = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl,
        urlBase: session.urlBase, jeton: session.jeton }, outil, args);
      if (!courante()) return aucune("lecture_remplacee");
      if (appel.genre !== "reponse") return appel.genre === "refuse" ?
        { source: "refus", verdict: appel.verdict } : { source: "aucune", raison: appel.verdict };
      const lu = lecteur(appel.resultat);
      if (!courante()) return aucune("lecture_remplacee");
      if (!lu.ok) {
        const verdict = { code: lu.code, detail: lu.detail };
        return lu.code === "reponse_illisible" || lu.code === "reponse_tronquee" || ERREURS_PASSAGERES.includes(lu.code) ?
          { source: "aucune", raison: verdict } : { source: "refus", verdict };
      }
      const date = d.horloge().toISOString();
      return courante() ? { source: "serveur", valeur: lu.value, misAJourLe: date } : aucune("lecture_remplacee");
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  return {
    chargerPreuves: async (wctId: string, decalage = 0): Promise<ResultatSection<PagePreuvesM6> | null> => {
      let args;
      try { args = construireArgumentsPreuves(wctId, decalage); } catch { return aucune("lecture_indisponible"); }
      return lire(OUTIL_PREUVES_PERTES_M6, { ...args }, v => lirePreuvesPertesWct(v, args));
    },
    chargerWcts: async (decalage = 0): Promise<ResultatSection<ListeWctPertesM6> | null> => {
      let args;
      try { args = construireArgumentsListeWct(decalage); } catch { return aucune("lecture_indisponible"); }
      return lire(OUTIL_LISTE_WCT_PERTES, { ...args }, v => lireListeWctPertes(v, args));
    },
    chargerPertes: async (wctId: string, decalage = 0): Promise<ResultatSection<PertesAlertesWctM6> | null> => {
      let args;
      try { args = construireArgumentsPertesWct(wctId, decalage); } catch { return aucune("lecture_indisponible"); }
      return lire(OUTIL_PERTES_ALERTES_WCT, { ...args }, v => lirePertesAlertesWct(v, args));
    },
  };
}

let connectee = false, generationReseau = 0;
/** Toute transition, y compris A→B→A, invalide les lectures déjà parties. */
export function actualiserConnectivitePertesM6(valeur: boolean): void {
  if (valeur !== connectee) generationReseau++;
  connectee = valeur;
}
const lectures = creerChargeurPertesAlertesM6({
  capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => {
    const epoch = generationReseau;
    return { enLigne: connectee, courante: () => connectee && epoch === generationReseau };
  },
  appelerOutil: invoquerOutil,
  fetchImpl: fetch,
  horloge: () => new Date(),
});
export const chargerWctsPertesM6 = lectures.chargerWcts;
export const chargerPertesAlertesWctM6 = lectures.chargerPertes;

export const chargerPreuvesPertesWctM6 = (wctId: string, decalage = 0) => lectures.chargerPreuves(wctId, decalage);
