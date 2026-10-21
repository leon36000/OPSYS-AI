import { lireClient360, lireClientDeLead, lireSuggestion } from "../m2/client360";
import type { Client360, SuggestionAction } from "../m2/client360";
import { estObjet, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import type { VerdictServeur } from "../outbox/vidangeur";

/**
 * La fiche d'un lead (`(seller)/lead/[id].tsx`, PLAN T4.8) : la prochaine action suggérée et le Client 360, tels que
 * le serveur les a rendus en UNE lecture. Logique PURE, testée (`fiche.test.ts`).
 *
 * Ce que le cache garde, ce sont les MOTS DU SERVEUR (`FicheBrute` : la valeur acceptée telle qu'elle est venue, ou
 * le verdict de refus), jamais un modèle de l'app : la fiche est composée à chaque lecture, en ligne ou hors ligne,
 * par les mêmes lecteurs (`composerFiche`). Un cache d'une forme que ce code ne sait plus lire donne un verdict
 * `reponse_illisible`, jamais une fiche à moitié devinée.
 */

/** Une réponse d'outil telle que le serveur l'a donnée : sa donnée, ou son refus. */
export type LectureBrute =
  | { readonly genre: "accepte"; readonly valeur: unknown }
  | { readonly genre: "refuse"; readonly verdict: VerdictServeur };

/** Les trois lectures d'une fiche : la suggestion, le client du lead, puis le Client 360 (absent si le client du
 * lead n'a pas pu être trouvé : on ne demande pas une vue sans client). */
export interface FicheBrute {
  readonly suggestion: LectureBrute;
  readonly clientDuLead: LectureBrute;
  readonly vue: LectureBrute | null;
  /** ISO 8601 UTC de la lecture : la date que dit un cache hors ligne. */
  readonly misAJourLe: string;
}

export type PartieFiche<T> =
  | { readonly genre: "lue"; readonly valeur: T }
  /** Le serveur a répondu non (lead d'un autre, lead clos...) ou sa réponse est illisible : son verdict, tel quel. */
  | { readonly genre: "verdict"; readonly verdict: VerdictServeur };

export interface FicheLead {
  readonly leadId: string;
  readonly suggestion: PartieFiche<SuggestionAction>;
  readonly client: PartieFiche<Client360>;
  readonly misAJourLe: string;
}

function illisible(): { readonly genre: "verdict"; readonly verdict: VerdictServeur } {
  return { genre: "verdict", verdict: VERDICT_REPONSE_ILLISIBLE };
}

function partie<T>(lecture: LectureBrute, lire: (valeur: unknown) => T | null): PartieFiche<T> {
  if (lecture.genre === "refuse") {
    return { genre: "verdict", verdict: lecture.verdict };
  }
  const valeur = lire(lecture.valeur);
  return valeur === null ? illisible() : { genre: "lue", valeur };
}

/**
 * Compose la fiche d'un lead depuis les mots du serveur. La suggestion doit parler du même lead ; le Client 360 doit
 * être celui du client que le serveur a donné pour ce lead : une réponse qui parlerait d'un autre lead ou d'un autre
 * client n'est pas montrée (un mélange de fiches ferait lire au vendeur le dossier d'un autre).
 */
export function composerFiche(leadId: string, brute: FicheBrute): FicheLead {
  const suggestion = partie(brute.suggestion, lireSuggestion);
  const suggestionDuBonLead: PartieFiche<SuggestionAction> =
    suggestion.genre === "lue" && suggestion.valeur.leadId !== leadId ? illisible() : suggestion;

  const clientDuLead = partie(brute.clientDuLead, lireClientDeLead);
  let client: PartieFiche<Client360>;
  if (clientDuLead.genre === "verdict") {
    client = clientDuLead;
  } else if (clientDuLead.valeur.leadId !== leadId || brute.vue === null) {
    client = illisible();
  } else {
    const vue = partie(brute.vue, lireClient360);
    client = vue.genre === "lue" && vue.valeur.clientId !== clientDuLead.valeur.clientId ? illisible() : vue;
  }
  return { leadId, suggestion: suggestionDuBonLead, client, misAJourLe: brute.misAJourLe };
}

function estVerdict(valeur: unknown): valeur is VerdictServeur {
  return estObjet(valeur) && typeof valeur.code === "string" && typeof valeur.detail === "string";
}

function estLectureBrute(valeur: unknown): valeur is LectureBrute {
  if (!estObjet(valeur)) {
    return false;
  }
  if (valeur.genre === "accepte") {
    return valeur.valeur !== undefined && valeur.valeur !== null;
  }
  return valeur.genre === "refuse" && estVerdict(valeur.verdict);
}

/** Une fiche brute relue du cache : le conteneur doit avoir la forme que ce module écrit, sinon `false` (cache absent). */
export function estFicheBruteValide(valeur: unknown): valeur is FicheBrute {
  return (
    estObjet(valeur) &&
    estLectureBrute(valeur.suggestion) &&
    estLectureBrute(valeur.clientDuLead) &&
    (valeur.vue === null || estLectureBrute(valeur.vue)) &&
    typeof valeur.misAJourLe === "string" &&
    !Number.isNaN(new Date(valeur.misAJourLe).getTime())
  );
}

/** Les interactions du Client 360 qui sont celles de CE lead, la plus récente d'abord ; celles des autres
 * opportunités du client sont comptées, pas montrées dans l'historique de ce lead. */
export interface HistoriqueDuLead {
  readonly interactions: readonly {
    readonly auteur: string;
    readonly resume: string;
    readonly horodatage: string;
    readonly systeme: boolean;
  }[];
  readonly autresOpportunites: number;
}

export function historiqueDuLead(client: Client360, leadId: string): HistoriqueDuLead {
  const siennes = client.interactionsRecentes.filter((i) => i.leadId === leadId);
  const interactions = siennes
    .map((i) => ({ auteur: i.auteur, resume: i.resume, horodatage: i.horodatage, systeme: i.auteur.startsWith("system:") }))
    .sort((a, b) => Date.parse(b.horodatage) - Date.parse(a.horodatage));
  return { interactions, autresOpportunites: client.interactionsRecentes.length - siennes.length };
}
