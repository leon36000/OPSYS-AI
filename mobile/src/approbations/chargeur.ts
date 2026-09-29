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

export interface OptionsChargementApprobations {
  /**
   * Rang de la première attente demandée (`decalage_attentes`, PLAN T1.5-e) : la valeur de `attentes.suivant` de la
   * page précédente. Absent ou 0 : la première page, sans argument, comme avant. Ce n'est qu'un rang : aucune
   * personne, aucun rôle (le serveur les tient du jeton d'appareil).
   */
  readonly decalageAttentes?: number;
}

export interface ChargeurApprobations {
  /** Ne lève jamais pour une raison réseau ou HTTP : elle devient `{source: "aucune", raison}`. */
  chargerDemandes(options?: OptionsChargementApprobations): Promise<ResultatChargementApprobations>;
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

/** Les args EXACTS de `m9_lister_demandes_approbation` : `{}` pour la première page, sinon le seul rang. */
export function construireArgumentsListerDemandes(decalageAttentes: number | undefined): Record<string, number> {
  return decalageAttentes === undefined || decalageAttentes === 0 ? {} : { decalage_attentes: decalageAttentes };
}

export function creerChargeurApprobations(config: ConfigurationChargeurApprobations): ChargeurApprobations {
  return {
    async chargerDemandes(options?: OptionsChargementApprobations): Promise<ResultatChargementApprobations> {
      const decalage = options?.decalageAttentes;
      if (decalage !== undefined && (!Number.isInteger(decalage) || decalage < 0)) {
        // Un rang qui n'est pas un entier ≥ 0 ne part jamais : le serveur le refuserait, l'app ne l'envoie pas.
        return {
          source: "aucune",
          raison: { code: "decalage_invalide", detail: "decalage_attentes : un entier supérieur ou égal à 0 est attendu." },
        };
      }
      const resultatAppel = await config.appelerOutil({
        fetchImpl: config.fetchImpl,
        urlBase: config.urlBase,
        jeton: config.jeton,
        requete: { tool: OUTIL_LISTER_DEMANDES, args: construireArgumentsListerDemandes(decalage) },
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
