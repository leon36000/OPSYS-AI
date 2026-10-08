import { appelerLecture } from "../admin/appel";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import { capturerSessionMateriauxLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { OUTIL_CONTEXTE_MATERIAUX, construireArgumentsContexteMateriaux, lireContexteMateriaux } from "../m6/contexteMateriaux";
import type { ContexteMateriauxM6 } from "../m6/contexteMateriaux";

export type ResultatContexteMateriaux =
  | { readonly source: "serveur"; readonly valeur: ContexteMateriauxM6 }
  | { readonly source: "refus"; readonly verdict: { readonly code: string; readonly detail: string } }
  | { readonly source: "aucune"; readonly raison: { readonly code: string; readonly detail: string } };
interface DependancesContexteMateriaux {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => { readonly enLigne: boolean; readonly courante: () => boolean };
  readonly appelerOutil: (p: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
}
const aucune = (code: string): ResultatContexteMateriaux => ({ source: "aucune", raison: { code, detail: "" } });

/** Lecture actuelle de la seule cible choisie ; aucun cache, dépôt ou effet. */
export function creerChargeurContexteMateriaux(d: DependancesContexteMateriaux) {
  return { charger: async (interventionId: string, wctId: string, decalage: number, limite = 8): Promise<ResultatContexteMateriaux> => {
    let args;
    try { args = construireArgumentsContexteMateriaux(interventionId, wctId, decalage, limite); }
    catch { return aucune("arguments_invalides"); }
    const capture = d.capturerSession(), session = capture.session;
    if (!session || !capture.courante()) return aucune("session_absente");
    const reseau = d.capturerReseau();
    if (!reseau.enLigne) return aucune("hors_ligne");
    const courante = () => capture.courante() && reseau.courante();
    if (!courante()) return aucune("lecture_remplacee");
    try {
      const r = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl,
        urlBase: session.urlBase, jeton: session.jeton }, OUTIL_CONTEXTE_MATERIAUX, { ...args });
      if (!courante()) return aucune("lecture_remplacee");
      if (r.genre !== "reponse") return r.genre === "refuse"
        ? { source: "refus", verdict: r.verdict } : { source: "aucune", raison: r.verdict };
      const lu = lireContexteMateriaux(r.resultat, args);
      if (!courante()) return aucune("lecture_remplacee");
      if (lu.ok) return { source: "serveur", valeur: lu.value };
      const verdict = { code: lu.code, detail: lu.detail };
      return ["reponse_illisible", "reponse_tronquee", ...ERREURS_PASSAGERES].includes(lu.code)
        ? { source: "aucune", raison: verdict } : { source: "refus", verdict };
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  } };
}

let enLigne = false, generationReseau = 0;
export function actualiserConnectiviteContexteMateriaux(valeur: boolean): void {
  if (enLigne !== valeur) generationReseau++;
  enLigne = valeur;
}
const chargeur = creerChargeurContexteMateriaux({ capturerSession: capturerSessionMateriauxLecture,
  capturerReseau: () => { const epoch = generationReseau; return { enLigne, courante: () => enLigne && epoch === generationReseau }; },
  appelerOutil: invoquerOutil, fetchImpl: fetch });
export const chargerContexteMateriaux = chargeur.charger;
