import type { FiltreLeads, LeadListe, PageLeads, SegmentNonCalculable } from "../m2/listeLeads";

/**
 * La liste des leads lue page par page (`(seller)/leads.tsx`, PLAN T4.8) : ce que l'écran a lu jusqu'ici pour UN
 * filtre, et comment une page de plus s'y recolle. Logique PURE, testée (`lectureLeads.test.ts`).
 *
 * Le serveur pagine par RANG dans un ordre stable (`liste_leads.py` : le plus ancien lead ingéré d'abord). Un
 * lead qui change de statut ou de segment entre deux pages (il entre dans un filtre ou en sort) fait glisser les
 * rangs : un lead pourrait manquer ou se répéter, et `total` change. Le serveur le dit (« l'appelant relit depuis
 * 0 ») ; l'écran ne recolle donc une page que si tout s'accorde, et relit sinon depuis le début — jamais une liste
 * qui aurait l'air complète sans l'être. Même règle que `fusionnerPageAttentes` (approbations, PLAN T1.5-e).
 */

export interface LeadsLus {
  readonly filtre: FiltreLeads;
  readonly leads: readonly LeadListe[];
  /** Les leads visibles qui passent le filtre, toutes pages confondues (au moment de la première page). */
  readonly total: number;
  /** Rang à demander pour la page suivante ; `null` : rien ne suit. */
  readonly suivant: number | null;
  /** Leads qui viennent APRÈS ceux-ci : pas encore lus. */
  readonly reste: number;
  /** Énoncé des règles citées par les leads lus (identifiant -> texte). */
  readonly regles: Readonly<Record<string, string>>;
  /** Ce qui manque pour calculer un segment, pour TOUS les leads. */
  readonly segmentsNonCalculables: readonly SegmentNonCalculable[];
  readonly indetermines: number;
  /** Leads de la réponse que ce client n'a pas su lire. */
  readonly illisibles: number;
  /** Les pages telles que le serveur les a rendues : c'est CE que le cache garde, relu par les mêmes lecteurs. */
  readonly pagesBrutes: readonly unknown[];
  /** ISO 8601 UTC de la lecture de la PREMIÈRE page : la date que dit un cache hors ligne. */
  readonly misAJourLe: string;
}

export type RaisonRelecture = "liste_changee" | "incoherente";

export type FusionLeads =
  | { readonly genre: "fusionnee"; readonly lus: LeadsLus }
  | { readonly genre: "a_relire"; readonly raison: RaisonRelecture };

export function memeFiltre(a: FiltreLeads, b: FiltreLeads): boolean {
  return a.statut === b.statut && a.segment === b.segment;
}

/** Clé d'un filtre pour le cache : un filtre = une lecture. */
export function cleFiltre(filtre: FiltreLeads): string {
  return `${filtre.statut ?? "*"}|${filtre.segment ?? "*"}`;
}

/**
 * La première page d'un filtre. `null` si la page n'est pas la première (`decalage` ≠ 0) ou si le serveur n'a pas
 * répondu pour le filtre demandé : ce ne serait pas la liste demandée, elle n'est pas montrée.
 */
export function demarrerLecture(
  filtre: FiltreLeads,
  page: PageLeads,
  brute: unknown,
  misAJourLe: string,
): LeadsLus | null {
  if (page.decalage !== 0 || !memeFiltre(page.filtre, filtre)) {
    return null;
  }
  return {
    filtre,
    leads: page.leads,
    total: page.total,
    suivant: page.suivant,
    reste: page.reste,
    regles: page.regles,
    segmentsNonCalculables: page.segmentsNonCalculables,
    indetermines: page.indetermines,
    illisibles: page.illisibles,
    pagesBrutes: [brute],
    misAJourLe,
  };
}

/**
 * Prolonge les leads lus par la page que le serveur vient de rendre. Elle ne se recolle que si :
 *  - la page est celle qu'on a demandée (`decalage` = `suivant` des leads lus) et pour le même filtre ;
 *  - la page fait progresser la lecture (`suivant` = `decalage` + `affichees`, ou nul) : un serveur qui répondrait
 *    toujours la même page ne fait pas tourner « Voir plus » en rond ;
 *  - le total n'a pas changé ;
 *  - aucun lead de la page n'est déjà affiché.
 */
export function fusionnerPage(lues: LeadsLus, page: PageLeads, brute: unknown): FusionLeads {
  if (lues.suivant === null || page.decalage !== lues.suivant || !memeFiltre(page.filtre, lues.filtre)) {
    return { genre: "a_relire", raison: "incoherente" };
  }
  if (page.suivant !== null && page.suivant !== page.decalage + page.affichees) {
    return { genre: "a_relire", raison: "incoherente" };
  }
  if (page.total !== lues.total) {
    return { genre: "a_relire", raison: "liste_changee" };
  }
  const deja = new Set(lues.leads.map((lead) => lead.leadId));
  if (page.leads.some((lead) => deja.has(lead.leadId))) {
    return { genre: "a_relire", raison: "liste_changee" };
  }
  return {
    genre: "fusionnee",
    lus: {
      ...lues,
      leads: [...lues.leads, ...page.leads],
      suivant: page.suivant,
      reste: page.reste,
      regles: { ...lues.regles, ...page.regles },
      segmentsNonCalculables: page.segmentsNonCalculables,
      indetermines: page.indetermines,
      illisibles: lues.illisibles + page.illisibles,
      pagesBrutes: [...lues.pagesBrutes, brute],
    },
  };
}
