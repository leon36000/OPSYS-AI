import type { InterventionM4, StatutInterventionM4, VerdictServeurM4 } from "../m4/interventions";
import type { ResultatChargementChantiers } from "../today/orchestrateur";

/**
 * Logique PURE de `(employee)/today.tsx` (PLAN T1.4-n) : ce que l'écran dit d'une lecture des chantiers. Le fichier `.tsx`
 * ne fait que le câblage React ; tout ce qui décide est ici, testé (`today.test.ts`).
 *
 * « Aucun chantier actif » n'est dit que si une lecture le dit : le serveur (liste lue en entier) ou le cache marqué. Jamais
 * quand la lecture a échoué (ni serveur ni cache), qu'elle a été refusée, ou qu'elle est incomplète (le socle a coupé la
 * réponse d'un statut) : une liste vide et une liste qu'on n'a pas pu lire ne se ressemblent jamais.
 */
export type AvisChantiers =
  /** Le serveur n'a pas pu répondre : la liste gardée, avec sa date. */
  | { readonly genre: "cache"; readonly misAJourLe: string }
  /** Le socle a coupé la réponse de ces statuts : la liste montrée n'est ni vide ni complète. */
  | { readonly genre: "incomplet"; readonly statuts: readonly StatutInterventionM4[] }
  /** Le serveur dit non (jeton révoqué, personne désactivée, rôle retiré) : son verdict, jamais une liste gardée. */
  | { readonly genre: "refus"; readonly verdict: VerdictServeurM4 }
  /** Ni serveur ni liste gardée. */
  | { readonly genre: "aucune" };

export interface VueChantiers {
  readonly items: readonly InterventionM4[];
  readonly avis: AvisChantiers | null;
  readonly aucunChantier: boolean;
}

export function vueChantiers(resultat: ResultatChargementChantiers | null, premierChargementFait: boolean): VueChantiers {
  if (resultat === null) {
    return { items: [], avis: null, aucunChantier: false };
  }
  switch (resultat.source) {
    case "serveur":
      return { items: resultat.items, avis: null, aucunChantier: premierChargementFait && resultat.items.length === 0 };
    case "cache":
      return {
        items: resultat.items,
        avis: { genre: "cache", misAJourLe: resultat.misAJourLe },
        aucunChantier: premierChargementFait && resultat.items.length === 0,
      };
    case "incomplet":
      return { items: resultat.items, avis: { genre: "incomplet", statuts: resultat.groupesIncomplets }, aucunChantier: false };
    case "refus":
      return { items: [], avis: { genre: "refus", verdict: resultat.verdict }, aucunChantier: false };
    case "aucune":
      return { items: [], avis: { genre: "aucune" }, aucunChantier: false };
  }
}
