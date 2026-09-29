import type { PrevisionLue, PrevisionTresorerie } from "./tresorerie";

/**
 * La prévision lue page par page (`(admin)/chiffres.tsx`, PLAN T4.20) : comment une page de semaines s'ajoute à ce que
 * l'écran a déjà lu. Logique PURE, testée (`pagesPrevision.test.ts`).
 *
 * Le serveur pagine par RANG (`depart`, `prochain_depart`) et donne à TOUTE la prévision une empreinte
 * (`prevision_id`) : deux pages d'un même horizon la partagent, une page d'une prévision refaite entre-temps (un
 * paiement saisi, une facture envoyée) en a une autre. L'écran ne recolle donc une page que si tout s'accorde, et relit
 * depuis le début sinon — jamais une série qui aurait l'air complète en mélangeant deux prévisions. Même règle que
 * `fusionnerPageAttentes` (approbations, PLAN T1.5-e) et `fusionnerPage` (leads, PLAN T4.8).
 */
export type RaisonRelecturePrevision = "prevision_changee" | "incoherente";

export type FusionPrevision =
  | { readonly genre: "fusionnee"; readonly prevision: PrevisionTresorerie }
  | { readonly genre: "a_relire"; readonly raison: RaisonRelecturePrevision };

/**
 * Recolle `page` à `lue`. L'en-tête (la lecture de M5, l'alerte, le manque, le solde de départ) est celui de `lue` :
 * il est le même pour toutes les pages d'une même prévision. Il faut, pour recoller :
 *  - qu'il reste des semaines à lire (`lue.prochainDepart` n'est pas nul) et que la page soit une prévision ;
 *  - que ce soit la page demandée (`depart` = `prochainDepart` de ce qui est lu) ;
 *  - que la prévision n'ait pas changé (même `prevision_id`, même total) ;
 *  - que la page fasse progresser la lecture (au moins une semaine, et un rang suivant qui avance) ;
 *  - qu'aucune de ses semaines ne soit déjà affichée.
 */
export function fusionnerPagePrevision(lue: PrevisionTresorerie, page: PrevisionLue | null): FusionPrevision {
  if (page === null || page.genre !== "prevision" || lue.prochainDepart === null || page.depart !== lue.prochainDepart) {
    return { genre: "a_relire", raison: "incoherente" };
  }
  if (page.previsionId !== lue.previsionId || page.total !== lue.total) {
    return { genre: "a_relire", raison: "prevision_changee" };
  }
  if (page.affichees === 0 || (page.prochainDepart !== null && page.prochainDepart <= page.depart)) {
    return { genre: "a_relire", raison: "incoherente" };
  }
  const dejaLues = new Set(lue.semaines.map((semaine) => semaine.semaine));
  if (page.semaines.some((semaine) => dejaLues.has(semaine.semaine))) {
    return { genre: "a_relire", raison: "incoherente" };
  }
  return {
    genre: "fusionnee",
    prevision: {
      ...lue,
      semaines: [...lue.semaines, ...page.semaines],
      semainesIllisibles: lue.semainesIllisibles + page.semainesIllisibles,
      affichees: lue.affichees + page.affichees,
      reste: page.reste,
      prochainDepart: page.prochainDepart,
    },
  };
}
