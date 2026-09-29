import {
  construireArgumentsClient360,
  construireArgumentsSuggerer,
  construireArgumentsTrouverClient,
  lireClientDeLead,
  OUTIL_OBTENIR_CLIENT_360,
  OUTIL_SUGGERER_PROCHAINE_ACTION,
  OUTIL_TROUVER_CLIENT_DE_LEAD,
} from "../m2/client360";
import { formaterHorodatageLocal } from "../outbox/mutation";
import type { VerdictServeur } from "../outbox/vidangeur";
import { lireEnveloppeMetier } from "../protocole/enveloppeOutil";
import { appelerLecture, ecrireSansEchouer } from "./appel";
import type { ConfigurationChargeurVendeur } from "./appel";
import { ecrireCacheFiche, lireCacheFiche } from "./cache";
import { composerFiche } from "./fiche";
import type { FicheBrute, FicheLead, LectureBrute } from "./fiche";

/**
 * Chargeur de la fiche d'un lead (`(seller)/lead/[id].tsx`, PLAN T4.8) : la prochaine action suggérée
 * (`m2_suggerer_prochaine_action`), puis le client du lead (`m2_trouver_client_de_lead`) et son Client 360
 * (`m2_obtenir_client_360`). Lecture d'abord, cache hors ligne marqué comme tel. Orchestration PURE, testée avec un
 * faux transport et un dépôt mémoire (`chargeurFiche.test.ts`).
 *
 * TROIS issues :
 *  - `serveur` : le serveur a répondu aux trois lectures (par des données ou par des REFUS, qui sont des réponses :
 *    un lead clos n'a pas de suggestion, un lead d'un autre n'a rien). La fiche est composée, le cache écrit ;
 *  - `cache` : l'une des lectures n'a pas pu aboutir (réseau, délai, sortie tronquée, réponse illisible) et une
 *    fiche de CE lead pour CETTE personne est gardée : elle est rendue avec sa date et la raison. Jamais un mélange de
 *    lectures fraîches et gardées ;
 *  - `aucune` : ni serveur ni cache.
 *
 * Aucun argument ne désigne une personne : le serveur ne montre à un vendeur que SES leads, et un lead d'un autre donne
 * le même refus qu'un lead inconnu.
 */
export type ResultatFiche =
  | { readonly source: "serveur"; readonly fiche: FicheLead }
  | { readonly source: "cache"; readonly fiche: FicheLead; readonly raisonHorsLigne: VerdictServeur }
  | { readonly source: "aucune"; readonly raison: VerdictServeur };

export interface ChargeurFiche {
  /** Ne lève jamais pour une raison réseau ou HTTP. */
  chargerFiche(leadId: string): Promise<ResultatFiche>;
}

type Lecture =
  | { readonly genre: "lue"; readonly lecture: LectureBrute }
  | { readonly genre: "indisponible"; readonly verdict: VerdictServeur };

export function creerChargeurFiche(config: ConfigurationChargeurVendeur): ChargeurFiche {
  /** Une lecture : les mots du serveur (donnée ou refus), ou l'impossibilité de les avoir (cache possible). */
  async function lire(tool: string, args: Record<string, unknown>): Promise<Lecture> {
    const appel = await appelerLecture(config, tool, args);
    if (appel.genre === "injoignable") {
      return { genre: "indisponible", verdict: appel.verdict };
    }
    const enveloppe = lireEnveloppeMetier(appel.resultat);
    if (enveloppe.ok) {
      return { genre: "lue", lecture: { genre: "accepte", valeur: enveloppe.valeur } };
    }
    return enveloppe.genre === "refus"
      ? { genre: "lue", lecture: { genre: "refuse", verdict: enveloppe.verdict } }
      : { genre: "indisponible", verdict: enveloppe.verdict };
  }

  async function depuisCache(leadId: string, raisonHorsLigne: VerdictServeur): Promise<ResultatFiche> {
    const brute = await lireCacheFiche(config.depot, config.personne, leadId);
    return brute === null
      ? { source: "aucune", raison: raisonHorsLigne }
      : { source: "cache", fiche: composerFiche(leadId, brute), raisonHorsLigne };
  }

  return {
    async chargerFiche(leadId: string): Promise<ResultatFiche> {
      const horloge = config.horloge();
      const suggestion = await lire(
        OUTIL_SUGGERER_PROCHAINE_ACTION,
        { ...construireArgumentsSuggerer(leadId, formaterHorodatageLocal(horloge)) },
      );
      if (suggestion.genre === "indisponible") {
        return depuisCache(leadId, suggestion.verdict);
      }
      const clientDuLead = await lire(OUTIL_TROUVER_CLIENT_DE_LEAD, { ...construireArgumentsTrouverClient(leadId) });
      if (clientDuLead.genre === "indisponible") {
        return depuisCache(leadId, clientDuLead.verdict);
      }

      let vue: LectureBrute | null = null;
      if (clientDuLead.lecture.genre === "accepte") {
        // On ne demande la vue que d'un client que le serveur a nommé pour ce lead, jamais d'un identifiant deviné.
        const clientId = lireClientDeLead(clientDuLead.lecture.valeur)?.clientId ?? null;
        if (clientId !== null) {
          const lueVue = await lire(OUTIL_OBTENIR_CLIENT_360, { ...construireArgumentsClient360(clientId) });
          if (lueVue.genre === "indisponible") {
            return depuisCache(leadId, lueVue.verdict);
          }
          vue = lueVue.lecture;
        }
      }

      const brute: FicheBrute = {
        suggestion: suggestion.lecture,
        clientDuLead: clientDuLead.lecture,
        vue,
        misAJourLe: horloge.maintenant.toISOString(),
      };
      await ecrireSansEchouer(() => ecrireCacheFiche(config.depot, config.personne, leadId, brute));
      return { source: "serveur", fiche: composerFiche(leadId, brute) };
    },
  };
}
