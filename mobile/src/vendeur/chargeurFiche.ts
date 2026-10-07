import { capturerGardeLecture, depotSousGardeLecture, VERDICT_LECTURE_REMPLACEE } from "../stockage/lecturesEnVol";
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
import { estRefusDeRequete, lireEnveloppeMetier } from "../protocole/enveloppeOutil";
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
 * QUATRE issues :
 *  - `serveur` : le serveur a répondu aux trois lectures (par des données ou par des VERDICTS métier, qui sont des
 *    réponses : un lead clos n'a pas de suggestion, un lead d'un autre n'a rien). La fiche est composée. Le cache n'est
 *    écrit que si le Client 360 a été lu : une fiche faite de refus n'a rien à garder (PLAN T1.4-n) ;
 *  - `cache` : l'une des lectures n'a pas pu aboutir (réseau, délai, 5xx, sortie tronquée, réponse illisible) et une
 *    fiche de CE lead pour CETTE personne est gardée : elle est rendue avec sa date et la raison. Jamais un mélange de
 *    lectures fraîches et gardées ;
 *  - `refus` : le serveur a refusé la REQUÊTE (401 ou 403 de la porte d'appareil, autre 4xx du core, ou un refus
 *    technique : identité que la base ne confirme plus, rôle retiré, arguments refusés) : jeton révoqué, personne
 *    désactivée, rôle retiré. Aucune fiche, aucun cache lu, rien d'écrit : un cache ne dit pas ce que le serveur refuse
 *    aujourd'hui (règle de l'admin, PLAN T1.4-n) ;
 *  - `aucune` : ni serveur ni cache.
 *
 * Aucun argument ne désigne une personne : le serveur ne montre à un vendeur que SES leads, et un lead d'un autre donne
 * le même refus qu'un lead inconnu.
 */
export type ResultatFiche =
  | { readonly source: "serveur"; readonly fiche: FicheLead }
  | { readonly source: "cache"; readonly fiche: FicheLead; readonly raisonHorsLigne: VerdictServeur }
  | { readonly source: "refus"; readonly verdict: VerdictServeur }
  | { readonly source: "aucune"; readonly raison: VerdictServeur };

export interface ChargeurFiche {
  /** Ne lève jamais pour une raison réseau ou HTTP. */
  chargerFiche(leadId: string): Promise<ResultatFiche>;
}

type Lecture =
  | { readonly genre: "lue"; readonly lecture: LectureBrute }
  /** Le serveur refuse la REQUÊTE (l'appareil, son rôle, son identité, ses arguments), pas seulement ce lead. */
  | { readonly genre: "refusee"; readonly verdict: VerdictServeur }
  | { readonly genre: "indisponible"; readonly verdict: VerdictServeur };

function creerChargeurFicheInterne(config: ConfigurationChargeurVendeur): ChargeurFiche {
  /**
   * Une lecture : les mots du serveur (donnée ou verdict métier), le refus de la requête, ou l'impossibilité de les
   * avoir (cache possible). Un verdict métier (`accepte: false`) fait partie de la fiche ; un refus de la requête n'en
   * fait pas partie : il refuse toute la fiche.
   */
  async function lire(tool: string, args: Record<string, unknown>): Promise<Lecture> {
    const appel = await appelerLecture(config, tool, args);
    if (appel.genre === "refuse") {
      return { genre: "refusee", verdict: appel.verdict };
    }
    if (appel.genre === "injoignable") {
      return { genre: "indisponible", verdict: appel.verdict };
    }
    const enveloppe = lireEnveloppeMetier(appel.resultat);
    if (enveloppe.ok) {
      return { genre: "lue", lecture: { genre: "accepte", valeur: enveloppe.valeur } };
    }
    if (enveloppe.genre === "refus") {
      return estRefusDeRequete(appel.resultat)
        ? { genre: "refusee", verdict: enveloppe.verdict }
        : { genre: "lue", lecture: { genre: "refuse", verdict: enveloppe.verdict } };
    }
    return { genre: "indisponible", verdict: enveloppe.verdict };
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
      if (suggestion.genre === "refusee") {
        return { source: "refus", verdict: suggestion.verdict };
      }
      if (suggestion.genre === "indisponible") {
        return depuisCache(leadId, suggestion.verdict);
      }
      const clientDuLead = await lire(OUTIL_TROUVER_CLIENT_DE_LEAD, { ...construireArgumentsTrouverClient(leadId) });
      if (clientDuLead.genre === "refusee") {
        return { source: "refus", verdict: clientDuLead.verdict };
      }
      if (clientDuLead.genre === "indisponible") {
        return depuisCache(leadId, clientDuLead.verdict);
      }

      let vue: LectureBrute | null = null;
      if (clientDuLead.lecture.genre === "accepte") {
        // On ne demande la vue que d'un client que le serveur a nommé pour ce lead, jamais d'un identifiant deviné.
        const clientId = lireClientDeLead(clientDuLead.lecture.valeur)?.clientId ?? null;
        if (clientId !== null) {
          const lueVue = await lire(OUTIL_OBTENIR_CLIENT_360, { ...construireArgumentsClient360(clientId) });
          if (lueVue.genre === "refusee") {
            return { source: "refus", verdict: lueVue.verdict };
          }
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
      // Une fiche dont le Client 360 n'a pas été lu (le lead d'un autre, un client illisible) n'est faite que de
      // verdicts : elle est montrée, mais il n'y a rien à garder, et un cache ne doit pas redire un refus demain.
      if (vue?.genre === "accepte") {
        await ecrireSansEchouer(() => ecrireCacheFiche(config.depot, config.personne, leadId, brute));
      }
      return { source: "serveur", fiche: composerFiche(leadId, brute) };
    },
  };
}

export function creerChargeurFiche(config: ConfigurationChargeurVendeur): ChargeurFiche {
  const garde = capturerGardeLecture(config.depot);
  const chargeur = creerChargeurFicheInterne({ ...config, depot: depotSousGardeLecture(config.depot, garde.courante) });
  return {
    async chargerFiche(leadId) {
      if (!garde.courante()) return { source: "aucune", raison: VERDICT_LECTURE_REMPLACEE };
      const result = await chargeur.chargerFiche(leadId);
      return garde.courante() ? result : { source: "aucune", raison: VERDICT_LECTURE_REMPLACEE };
    },
  };
}
