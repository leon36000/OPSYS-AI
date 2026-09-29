import { CODE_SEGMENT_NON_CALCULABLE } from "../m2/listeLeads";
import { construireArgumentsLireDevis, lireDevisVendeur, OUTIL_LIRE_DEVIS } from "../m3/devis";
import type { DevisVendeur } from "../m3/devis";
import type { VerdictServeur } from "../outbox/vidangeur";
import { lireEnveloppeMetier, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import { appelerLecture, ecrireSansEchouer } from "./appel";
import type { ConfigurationChargeurVendeur } from "./appel";
import { ecrireCacheDevis, ecrireDevisConnus, lireCacheDevis, lireDevisConnus } from "./cache";
import { creerChargeurLeads } from "./chargeurLeads";
import type { ChargeurLeads } from "./chargeurLeads";
import {
  SEGMENT_DEVIS_ACCEPTE,
  SEGMENT_DEVIS_SANS_REPONSE,
  devisCitesParLeads,
  fusionnerDevisConnus,
  memesDevisConnus,
} from "./devisConnus";
import type { DevisConnu } from "./devisConnus";

/**
 * Chargeur des devis du vendeur (`(seller)/quotes.tsx`, PLAN T4.8) : `m3_lire_devis` sur chaque devis que le vendeur
 * connaît. Lecture d'abord, cache hors ligne marqué comme tel. Orchestration PURE, testée avec un faux transport et un
 * dépôt mémoire (`chargeurDevis.test.ts`).
 *
 * **Aucun outil ne liste les devis d'un vendeur** (voir `devisConnus.ts`). Les numéros viennent donc de deux sources :
 *  - la DÉCOUVERTE : les leads que M2 range dans `won_pending_schedule` (devis accepté) et `quote_stale` (devis envoyé
 *    resté sans réponse), lus par `m2_lister_leads` filtré par segment ; leur `donnee` cite le numéro du devis ;
 *  - la SAISIE : le numéro d'une soumission que le vendeur a en main (`ouvrirParNumero`).
 * Chaque source dit son état : un segment non calculable (seuil à configurer) est dit tel quel, une lecture
 * partielle ou en échec l'est aussi — jamais une liste qui aurait l'air complète sans l'être.
 *
 * Par devis, quatre états : `serveur` (lu à l'instant, cache écrit), `cache` (le serveur n'a pas pu répondre : devis
 * gardé, avec sa date et la raison), `refus` (le serveur dit non : `REJ-DEVIS-INTROUVABLE`, le même refus pour un devis
 * inconnu et celui d'un autre vendeur, ou un 401 ou 403 de la porte d'appareil ; le cache ne le remplace jamais et rien
 * n'est écrit) et `indisponible` (ni serveur ni cache).
 */

/** Pages de leads lues au plus par segment : la découverte ne tourne pas sans fin sur un très gros pipeline. */
export const MAX_PAGES_DECOUVERTE = 10;

export type EtatDevis =
  | { readonly genre: "serveur"; readonly devis: DevisVendeur; readonly misAJourLe: string }
  | {
      readonly genre: "cache";
      readonly devis: DevisVendeur;
      readonly misAJourLe: string;
      readonly raisonHorsLigne: VerdictServeur;
    }
  | { readonly genre: "refus"; readonly verdict: VerdictServeur }
  | { readonly genre: "indisponible"; readonly raison: VerdictServeur };

export interface EntreeDevis {
  readonly connu: DevisConnu;
  readonly etat: EtatDevis;
}

/** Ce que la découverte a pu lire d'un segment de leads. */
export type EtatSourceDevis =
  /** Les leads du segment ont été lus ; `reste` > 0 : la lecture est PARTIELLE (bornée, ou interrompue). `depuisCache`
   * porte la raison quand ils viennent du cache. */
  | {
      readonly genre: "lue";
      readonly leadsLus: number;
      readonly reste: number;
      readonly depuisCache: VerdictServeur | null;
    }
  /** M2 dit qu'il ne peut pas calculer ce segment (seuil à configurer...) : son « manque X », tel quel. */
  | { readonly genre: "non_calculable"; readonly verdict: VerdictServeur }
  /** Les devis de ce segment n'ont pas été découverts : ni serveur ni cache, ou le serveur a refusé la REQUÊTE (401, 403,
   * identité que la base ne confirme plus : `refuse`). */
  | { readonly genre: "echouee"; readonly verdict: VerdictServeur; readonly refuse: boolean };

export interface SourceDevis {
  readonly segment: string;
  readonly etat: EtatSourceDevis;
}

export interface ResultatDevis {
  readonly entrees: readonly EntreeDevis[];
  readonly sources: readonly SourceDevis[];
}

export interface ChargeurDevis {
  /** Découvre les devis cités par les leads, les réunit aux numéros déjà connus, puis lit chacun. Ne lève jamais pour
   * une raison réseau ou HTTP. */
  chargerDevis(): Promise<ResultatDevis>;
  /** Lit le devis dont le vendeur a le numéro ; `null` si le numéro est vide (rien n'est demandé). Un numéro lu avec
   * succès est gardé avec les numéros connus ; un refus ou un échec ne l'est jamais. */
  ouvrirParNumero(numero: string): Promise<EntreeDevis | null>;
}

const SEGMENTS_DECOUVERTE: readonly string[] = [SEGMENT_DEVIS_ACCEPTE, SEGMENT_DEVIS_SANS_REPONSE];

export function creerChargeurDevis(
  config: ConfigurationChargeurVendeur,
  chargeurLeads: ChargeurLeads = creerChargeurLeads(config),
): ChargeurDevis {
  async function depuisCache(connu: DevisConnu, raisonHorsLigne: VerdictServeur): Promise<EntreeDevis> {
    const gardee = await lireCacheDevis(config.depot, config.personne, connu.devisId);
    return {
      connu,
      etat:
        gardee === null
          ? { genre: "indisponible", raison: raisonHorsLigne }
          : { genre: "cache", devis: gardee.devis, misAJourLe: gardee.misAJourLe, raisonHorsLigne },
    };
  }

  async function lireUnDevis(connu: DevisConnu): Promise<EntreeDevis> {
    const appel = await appelerLecture(config, OUTIL_LIRE_DEVIS, { ...construireArgumentsLireDevis(connu.devisId) });
    if (appel.genre === "refuse") {
      // 401, 403 : l'appareil est refusé. Le devis gardé n'est pas montré, et rien n'est écrit (PLAN T1.4-n).
      return { connu, etat: { genre: "refus", verdict: appel.verdict } };
    }
    if (appel.genre === "injoignable") {
      return depuisCache(connu, appel.verdict);
    }
    const enveloppe = lireEnveloppeMetier(appel.resultat);
    if (!enveloppe.ok) {
      return enveloppe.genre === "refus"
        ? { connu, etat: { genre: "refus", verdict: enveloppe.verdict } }
        : depuisCache(connu, enveloppe.verdict);
    }
    const devis = lireDevisVendeur(enveloppe.valeur);
    if (devis === null || devis.devisId !== connu.devisId) {
      // Illisible, ou le devis d'un autre numéro : ce n'est pas celui qu'on a demandé, il n'est pas montré.
      return depuisCache(connu, VERDICT_REPONSE_ILLISIBLE);
    }
    const misAJourLe = config.horloge().maintenant.toISOString();
    await ecrireSansEchouer(() => ecrireCacheDevis(config.depot, config.personne, devis, misAJourLe));
    return { connu, etat: { genre: "serveur", devis, misAJourLe } };
  }

  /** Les leads d'UN segment, page par page jusqu'à la borne, puis les devis que leurs segments citent. */
  async function decouvrirSegment(
    segment: string,
  ): Promise<{ readonly source: SourceDevis; readonly cites: readonly DevisConnu[] }> {
    const lecture = await chargeurLeads.chargerLeads({ statut: null, segment });
    if (lecture.source === "refus") {
      return {
        source: {
          segment,
          etat:
            lecture.verdict.code === CODE_SEGMENT_NON_CALCULABLE
              ? { genre: "non_calculable", verdict: lecture.verdict }
              : { genre: "echouee", verdict: lecture.verdict, refuse: lecture.requete === true },
        },
        cites: [],
      };
    }
    if (lecture.source === "aucune") {
      return { source: { segment, etat: { genre: "echouee", verdict: lecture.raison, refuse: false } }, cites: [] };
    }
    let lus = lecture.lus;
    if (lecture.source === "serveur") {
      // Le cache ne se prolonge pas : il garde ce qui a été lu, il n'invente pas la suite.
      for (let pages = 1; lus.suivant !== null && pages < MAX_PAGES_DECOUVERTE; pages += 1) {
        const suite = await chargeurLeads.chargerSuite(lus);
        if (suite.genre !== "fusionnee") {
          break;
        }
        lus = suite.lus;
      }
    }
    return {
      source: {
        segment,
        etat: {
          genre: "lue",
          leadsLus: lus.leads.length,
          reste: lus.reste,
          depuisCache: lecture.source === "cache" ? lecture.raisonHorsLigne : null,
        },
      },
      cites: devisCitesParLeads(lus.leads),
    };
  }

  return {
    async chargerDevis(): Promise<ResultatDevis> {
      const sources: SourceDevis[] = [];
      let decouverts: readonly DevisConnu[] = [];
      for (const segment of SEGMENTS_DECOUVERTE) {
        const { source, cites } = await decouvrirSegment(segment);
        sources.push(source);
        decouverts = fusionnerDevisConnus(decouverts, cites);
      }
      // Le serveur refuse la REQUÊTE (jeton révoqué, personne désactivée, rôle retiré) : les numéros gardés sont du cache,
      // qu'un refus ne remplace jamais ; aucun devis n'est demandé ni montré, rien n'est écrit (PLAN T1.4-n).
      if (sources.some((source) => source.etat.genre === "echouee" && source.etat.refuse)) {
        return { entrees: [], sources };
      }
      const gardes = await lireDevisConnus(config.depot, config.personne);
      const connus = fusionnerDevisConnus(gardes, decouverts);
      if (!memesDevisConnus(connus, gardes)) {
        await ecrireSansEchouer(() => ecrireDevisConnus(config.depot, config.personne, connus));
      }
      const entrees: EntreeDevis[] = [];
      for (const connu of connus) {
        entrees.push(await lireUnDevis(connu));
      }
      return { entrees, sources };
    },

    async ouvrirParNumero(numero: string): Promise<EntreeDevis | null> {
      const devisId = numero.trim();
      if (devisId === "") {
        return null;
      }
      const connu: DevisConnu = { devisId, leadId: null, origine: "saisi" };
      const entree = await lireUnDevis(connu);
      if (entree.etat.genre === "serveur") {
        const gardes = await lireDevisConnus(config.depot, config.personne);
        const fusion = fusionnerDevisConnus(gardes, [connu]);
        if (!memesDevisConnus(fusion, gardes)) {
          await ecrireSansEchouer(() => ecrireDevisConnus(config.depot, config.personne, fusion));
        }
      }
      return entree;
    },
  };
}
