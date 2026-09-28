import { interpreterResultatListerDemandes } from "./contrat";
import type { ListeApprobations, VerdictServeurApprobation } from "./contrat";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";

/**
 * Chargeur des demandes d'approbation (`(admin)/approvals.tsx`, PLAN T1.4-f étape 6). Même discipline
 * que `src/today/orchestrateur.ts` — orchestration PURE, tout est injecté, testée avec un faux transport
 * (`chargeur.test.ts`) — MAIS sans cache : une liste d'approbations gardée en mémoire dirait à un
 * propriétaire hors ligne de décider une demande peut-être déjà décidée à la console. Hors ligne, la
 * liste n'est pas montrée (fail-closed), et le verdict dit pourquoi. Décider, lui, reste possible hors
 * ligne : la décision part par la file sortante (`approval_decision`), le serveur revérifie tout à
 * l'arrivée et répond par un verdict (`deja_decidee`...).
 *
 * Lecture seule : aucune clé d'idempotence (rien n'est écrit) ; l'identité du propriétaire est celle du
 * jeton d'appareil, transmise par le core, jamais un argument.
 */
export interface ConfigurationChargeurApprobations {
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
}

export type ResultatChargementApprobations =
  | { readonly source: "serveur"; readonly liste: ListeApprobations }
  | { readonly source: "aucune"; readonly raison: VerdictServeurApprobation };

export interface ChargeurApprobations {
  /** Ne lève jamais pour une raison réseau ou HTTP : elle devient `{source: "aucune", raison}`. */
  chargerDemandes(): Promise<ResultatChargementApprobations>;
}

export const OUTIL_LISTER_DEMANDES = "m9_lister_demandes_approbation";

function verdictDepuisEchecAppel(echec: {
  readonly message: string;
  readonly erreur?: { readonly type: string; readonly message: string };
}): VerdictServeurApprobation {
  if (echec.erreur) {
    return { code: echec.erreur.type, detail: echec.erreur.message };
  }
  return { code: "erreur_reseau", detail: echec.message };
}

export function creerChargeurApprobations(config: ConfigurationChargeurApprobations): ChargeurApprobations {
  return {
    async chargerDemandes(): Promise<ResultatChargementApprobations> {
      const resultatAppel = await config.appelerOutil({
        fetchImpl: config.fetchImpl,
        urlBase: config.urlBase,
        jeton: config.jeton,
        requete: { tool: OUTIL_LISTER_DEMANDES, args: {} },
      });
      if (!resultatAppel.ok) {
        return { source: "aucune", raison: verdictDepuisEchecAppel(resultatAppel.echec) };
      }
      const interpretation = interpreterResultatListerDemandes(resultatAppel.result);
      if (!interpretation.ok) {
        return { source: "aucune", raison: interpretation.verdict };
      }
      return { source: "serveur", liste: interpretation.liste };
    },
  };
}
