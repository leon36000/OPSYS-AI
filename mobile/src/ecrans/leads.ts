import { CODE_SEGMENT_NON_CALCULABLE } from "../m2/listeLeads";
import type { FiltreLeads, LeadListe, SegmentNonCalculable } from "../m2/listeLeads";
import type { VerdictServeur } from "../outbox/vidangeur";
import type { ResultatLeads } from "../vendeur/chargeurLeads";
import type { LeadsLus } from "../vendeur/lectureLeads";

/**
 * Logique PURE de `(seller)/leads.tsx` (PLAN T4.8) : ce que l'écran montre d'une lecture, et comment il change de
 * filtre. Le fichier `.tsx` ne fait que le câblage React ; tout ce qui décide est ici, testé (`leads.test.ts`).
 *
 * **Le serveur décide, l'écran ne recalcule rien.** Aucun segment n'est calculé ici, aucune priorité, aucune portée :
 * l'écran lit ce que M2 rend (`segments` avec leur règle citée, `segments_non_calculables` avec leur « manque X »).
 * Un segment que M2 ne peut pas calculer est montré COMME TEL, avec ce qui manque : jamais une liste vide, qui se
 * lirait « aucun lead ».
 */

/** Un filtre change de valeur en touchant la même deux fois (retour à « tous »). Le statut et le segment se
 * combinent (M2 sait filtrer par les deux) ; changer l'un ne touche pas à l'autre. */
export function basculerStatut(filtre: FiltreLeads, statut: string): FiltreLeads {
  return { ...filtre, statut: filtre.statut === statut ? null : statut };
}

export function basculerSegment(filtre: FiltreLeads, segment: string): FiltreLeads {
  return { ...filtre, segment: filtre.segment === segment ? null : segment };
}

export type EtatSegment =
  | { readonly calculable: true }
  /** M2 dit qu'il ne peut pas calculer ce segment pour AUCUN lead : « non calculable, manque X ». */
  | { readonly calculable: false; readonly manque: string };

/**
 * Ce que l'on sait d'un segment d'après la dernière lecture : `calculable` tant que M2 ne dit pas le contraire. Sans
 * lecture encore (`null`), tout est présumé calculable : le serveur refusera ce qu'il ne peut pas calculer
 * (`REJ-SEGMENT-NON-CALCULABLE`), et ce refus est montré comme un segment non calculable (`vueLeads`).
 */
export function etatSegment(segment: string, nonCalculables: readonly SegmentNonCalculable[] | null): EtatSegment {
  const trouve = nonCalculables?.find((n) => n.segment === segment);
  return trouve === undefined ? { calculable: true } : { calculable: false, manque: trouve.manque };
}

export interface LigneDonnee {
  readonly cle: string;
  readonly valeur: string;
}

/** La donnée qui a déclenché une règle, une ligne par clé : un texte tel quel, tout le reste en JSON. Rien n'est
 * abrégé, résumé ni reformulé. */
export function lignesDeDonnee(donnee: Readonly<Record<string, unknown>>): readonly LigneDonnee[] {
  return Object.entries(donnee).map(([cle, valeur]) => ({
    cle,
    valeur: typeof valeur === "string" ? valeur : JSON.stringify(valeur),
  }));
}

export interface SegmentPresente {
  readonly segment: string;
  readonly regle: string;
  /** L'énoncé de la règle tel que M2 le donne (`regles`) ; `null` : le serveur ne l'a pas donné, jamais inventé. */
  readonly enonce: string | null;
  readonly donnee: readonly LigneDonnee[];
}

export interface CarteLead {
  readonly leadId: string;
  readonly statut: string | null;
  readonly travaux: string | null;
  readonly ville: string | null;
  /** `true` seulement si l'urgence a été déclarée à l'ingestion : `null` (absente) n'est pas « non urgent ». */
  readonly urgent: boolean;
  readonly derniereActivite: string | null;
  readonly prochaineAction: { readonly description: string; readonly echeance: string | null } | null;
  readonly segments: readonly SegmentPresente[];
  /** Ce que M2 n'a pas pu calculer POUR CE LEAD (« non calculable, manque X »). */
  readonly nonCalculables: readonly SegmentNonCalculable[];
}

export function presenterLead(lead: LeadListe, regles: Readonly<Record<string, string>>): CarteLead {
  return {
    leadId: lead.leadId,
    statut: lead.statut,
    travaux: lead.travaux,
    ville: lead.ville,
    urgent: lead.urgenceDeclaree === true,
    derniereActivite: lead.derniereActivite,
    prochaineAction: lead.prochaineAction,
    segments: lead.segments.map((s) => ({
      segment: s.segment,
      regle: s.regle,
      enonce: regles[s.regle] ?? null,
      donnee: lignesDeDonnee(s.donnee),
    })),
    nonCalculables: lead.nonCalculables,
  };
}

/** Ce que l'écran affiche de la dernière lecture. */
export type VueLeads =
  | { readonly genre: "sans_appairage" }
  /** M2 ne peut pas calculer ce segment : dit comme tel, avec ce qui manque — pas une erreur, pas une liste vide. */
  | { readonly genre: "segment_non_calculable"; readonly verdict: VerdictServeur }
  /** Le serveur a répondu non (identité invalide...) : son verdict, tel quel. */
  | { readonly genre: "refus"; readonly verdict: VerdictServeur }
  | { readonly genre: "aucune"; readonly raison: VerdictServeur }
  | {
      readonly genre: "liste";
      readonly lus: LeadsLus;
      /** Non nul quand la liste vient du cache : la date du cache et pourquoi le serveur n'a pas été lu. */
      readonly cache: { readonly misAJourLe: string; readonly raison: VerdictServeur } | null;
    };

export function vueLeads(resultat: ResultatLeads | null): VueLeads {
  if (resultat === null) {
    return { genre: "sans_appairage" };
  }
  switch (resultat.source) {
    case "serveur":
      return { genre: "liste", lus: resultat.lus, cache: null };
    case "cache":
      return {
        genre: "liste",
        lus: resultat.lus,
        cache: { misAJourLe: resultat.lus.misAJourLe, raison: resultat.raisonHorsLigne },
      };
    case "refus":
      return resultat.verdict.code === CODE_SEGMENT_NON_CALCULABLE
        ? { genre: "segment_non_calculable", verdict: resultat.verdict }
        : { genre: "refus", verdict: resultat.verdict };
    case "aucune":
      return { genre: "aucune", raison: resultat.raison };
  }
}

/**
 * La liste est-elle vraiment vide ? Seulement quand le serveur (ou le cache) dit `total` 0 ET que rien n'était
 * illisible ni indéterminé : sinon « aucun lead » serait un mensonge.
 */
export function listeVide(lus: LeadsLus): boolean {
  return lus.total === 0 && lus.leads.length === 0 && lus.illisibles === 0 && lus.indetermines === 0;
}
