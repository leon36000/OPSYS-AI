import type { ResultatSection } from "../admin/lecture";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import { capturerSessionLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import type { Reponse } from "./contrat";
import { lireFileApprobationM7, lireDemandesAvisM7 } from "./lecturesAdmin";

export interface DependancesLecturesMarketing {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly appeler: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly maintenant: () => string;
}

const remplacee = () => ({ source: "aucune" as const, raison: { code: "lecture_remplacee", detail: "La session de lecture a changé." } });

/** Informative reads only. No cache, idempotency key, role argument or mutation is supplied. */
export function creerChargeurLecturesMarketing(d: DependancesLecturesMarketing) {
  async function lire<T>(outil: string, args: Record<string, unknown>, lecteur: (v: unknown) => Reponse<T>): Promise<ResultatSection<T> | null> {
    const capture = d.capturerSession(), session = capture.session;
    if (!session) return null;
    if (!capture.courante()) return remplacee();
    try {
      const resultat = await d.appeler({ fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton, requete: { tool: outil, args } });
      if (!capture.courante()) return remplacee();
      if (!resultat.ok) {
        const verdict = { code: resultat.echec.erreur?.type ?? "lecture_indisponible", detail: resultat.echec.erreur?.message ?? resultat.echec.message };
        return resultat.echec.reessayable ? { source: "aucune", raison: verdict } : { source: "refus", verdict };
      }
      const lu = lecteur(resultat.result);
      if (!capture.courante()) return remplacee();
      if (!lu.ok) {
        const verdict = { code: lu.code, detail: lu.detail };
        return lu.code === "reponse_illisible" || lu.code === "reponse_tronquee" || ERREURS_PASSAGERES.includes(lu.code)
          ? { source: "aucune", raison: verdict } : { source: "refus", verdict };
      }
      return { source: "serveur", valeur: lu.value, misAJourLe: d.maintenant() };
    } catch {
      return capture.courante()
        ? { source: "aucune", raison: { code: "lecture_indisponible", detail: "Lecture momentanément indisponible." } }
        : remplacee();
    }
  }
  return {
    chargerFile: () => lire("m7_lister_file_approbation", {}, lireFileApprobationM7),
    chargerDemandesAvis: () => lire("m7_lister_demandes_avis", { limite: 8 }, lireDemandesAvisM7),
  };
}

function chargeur() {
  return creerChargeurLecturesMarketing({ capturerSession: capturerSessionLecture, appeler: invoquerOutil, fetchImpl: fetch, maintenant: () => new Date().toISOString() });
}
export const chargerFileMarketing = () => chargeur().chargerFile();
export const chargerDemandesAvisMarketing = () => chargeur().chargerDemandesAvis();
