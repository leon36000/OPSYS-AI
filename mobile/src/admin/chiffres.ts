import { capturerGardeLecture, VERDICT_LECTURE_REMPLACEE } from "../stockage/lecturesEnVol";
import { fusionnerPagePrevision } from "../m5/pagesPrevision";
import type { RaisonRelecturePrevision } from "../m5/pagesPrevision";
import {
  construireArgumentsEcheances,
  construireArgumentsEtatTresorerie,
  construireArgumentsPrevision,
  lireEcheancesFiscales,
  lireEtatTresorerie,
  lirePrevisionTresorerie,
  OUTIL_ECHEANCES_FISCALES,
  OUTIL_ETAT_TRESORERIE,
  OUTIL_PREVOIR_TRESORERIE,
} from "../m5/tresorerie";
import type { EcheancesFiscales, EtatTresorerie, PrevisionLue, PrevisionTresorerie } from "../m5/tresorerie";
import { construireArgumentsVueExecutive, lireVueExecutive, OUTIL_VUE_EXECUTIVE } from "../m8/vueExecutive";
import type { VueExecutive } from "../m8/vueExecutive";
import type { VerdictServeur } from "../outbox/vidangeur";
import { appelerLecture } from "./appel";
import type { ConfigurationChargeurAdmin } from "./appel";
import { interpreter } from "./enveloppe";
import { jourLocal } from "./horloge";
import { lireSection } from "./lecture";
import type { DefinitionSection, ResultatSection } from "./lecture";

/**
 * Les quatre lectures de l'écran « Chiffres » (`(admin)/chiffres.tsx`, PLAN T4.20, §9.5 M5 et M8) : la vue exécutive
 * de M8, l'état de trésorerie et le cash libre, la prévision et les échéances fiscales de M5. Chaque section se lit
 * SÉPARÉMENT (`lireSection`) : une section qui échoue, qui est refusée ou que M5 dit « à configurer » ne cache pas les
 * trois autres. Lecture d'abord, cache marqué (date, raison), une clé par personne ; un refus du serveur n'est jamais
 * remplacé par le cache.
 *
 * Le jour de référence de M5 (`aujourd_hui`) est celui de l'appareil (`jourLocal`) : M5 n'a pas d'horloge. Aucun montant,
 * horizon, seuil ni délai n'est envoyé : ils sont au propriétaire (`department.yaml`, GATE NATHAN), et absents, M5
 * refuse en disant quoi déclarer — refus que l'écran montre tel quel.
 */
export const SECTION_VUE_EXECUTIVE: DefinitionSection<VueExecutive> = {
  outil: OUTIL_VUE_EXECUTIVE,
  args: construireArgumentsVueExecutive(),
  cache: "vue_executive",
  interpreter: (brut) => interpreter(brut, "directe", lireVueExecutive),
};

export const SECTION_TRESORERIE: DefinitionSection<EtatTresorerie> = {
  outil: OUTIL_ETAT_TRESORERIE,
  args: construireArgumentsEtatTresorerie(),
  cache: "tresorerie",
  interpreter: (brut) => interpreter(brut, "directe", lireEtatTresorerie),
};

/** La première page de la prévision : celle que le cache garde. */
export function sectionPrevision(aujourdHui: string): DefinitionSection<PrevisionLue> {
  return {
    outil: OUTIL_PREVOIR_TRESORERIE,
    args: construireArgumentsPrevision(aujourdHui),
    cache: "prevision",
    interpreter: (brut) => interpreter(brut, "couple", lirePrevisionTresorerie),
  };
}

export function sectionEcheances(aujourdHui: string): DefinitionSection<EcheancesFiscales> {
  return {
    outil: OUTIL_ECHEANCES_FISCALES,
    args: construireArgumentsEcheances(aujourdHui),
    cache: "echeances",
    interpreter: (brut) => interpreter(brut, "couple", lireEcheancesFiscales),
  };
}

/** Ce que devient la prévision après « Voir plus » (les semaines qui suivent, lues en ligne). */
export type SuitePrevision =
  | { readonly genre: "fusionnee"; readonly prevision: PrevisionTresorerie }
  /** La prévision a changé, ou la page ne s'accorde pas : ce qui est affiché reste, l'écran relit depuis le début et le dit. */
  | { readonly genre: "a_relire"; readonly raison: RaisonRelecturePrevision }
  /** Le serveur a refusé : son verdict, dit ; les semaines déjà lues restent affichées. */
  | { readonly genre: "refus"; readonly verdict: VerdictServeur }
  /** Le serveur n'a pas pu répondre (ou la réponse est illisible) : la suite n'est pas inventée, le bouton reste offert. */
  | { readonly genre: "echec"; readonly verdict: VerdictServeur }
  /** Rien à demander : rien ne suit. */
  | { readonly genre: "sans_suite" };

export interface ChargeurChiffres {
  /** Aucune ne lève pour une raison réseau ou HTTP. */
  chargerVueExecutive(): Promise<ResultatSection<VueExecutive>>;
  chargerTresorerie(): Promise<ResultatSection<EtatTresorerie>>;
  chargerPrevision(): Promise<ResultatSection<PrevisionLue>>;
  chargerEcheances(): Promise<ResultatSection<EcheancesFiscales>>;
  /**
   * « Voir plus » : les semaines qui suivent celles qui sont lues, sans cache (hors ligne, la suite n'est pas inventée).
   * Le recollement suit `fusionnerPagePrevision`.
   */
  chargerSuitePrevision(lue: PrevisionTresorerie): Promise<SuitePrevision>;
}

export function creerChargeurChiffres(config: ConfigurationChargeurAdmin): ChargeurChiffres {
  const aujourdHui = () => jourLocal(config.horloge());
  return {
    chargerVueExecutive: () => lireSection(config, SECTION_VUE_EXECUTIVE),
    chargerTresorerie: () => lireSection(config, SECTION_TRESORERIE),
    chargerPrevision: () => lireSection(config, sectionPrevision(aujourdHui())),
    chargerEcheances: () => lireSection(config, sectionEcheances(aujourdHui())),

    async chargerSuitePrevision(lue: PrevisionTresorerie): Promise<SuitePrevision> {
      const garde = capturerGardeLecture(config.depot);
      if (!garde.courante()) return { genre: "echec", verdict: VERDICT_LECTURE_REMPLACEE };
      if (lue.prochainDepart === null) {
        return { genre: "sans_suite" };
      }
      // Le jour de la suite est celui de la première page : une prévision qui traverse minuit n'est pas recollée à une
      // autre (son empreinte changerait ; `aujourd_hui` de la première page est ce que M5 a dit).
      const appel = await appelerLecture(config, OUTIL_PREVOIR_TRESORERIE, construireArgumentsPrevision(lue.aujourdHui, lue.prochainDepart));
      if (!garde.courante()) return { genre: "echec", verdict: VERDICT_LECTURE_REMPLACEE };
      if (appel.genre === "refuse") {
        return { genre: "refus", verdict: appel.verdict };
      }
      if (appel.genre === "injoignable") {
        return { genre: "echec", verdict: appel.verdict };
      }
      const page = interpreter(appel.resultat, "couple", lirePrevisionTresorerie);
      if (!page.ok) {
        return page.genre === "refus" ? { genre: "refus", verdict: page.verdict } : { genre: "echec", verdict: page.verdict };
      }
      return fusionnerPagePrevision(lue, page.valeur);
    },
  };
}
