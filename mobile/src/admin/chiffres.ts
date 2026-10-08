import { epurerVueExecutive } from "./cacheVueExecutive";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { estJourCashLibre } from "../m8/cashLibre";
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

/** Un slot personnel versionné ; l'âge de la copie reste lié à son jour d'origine. */
export function sectionVueExecutive(aujourdHui: string): DefinitionSection<VueExecutive> {
  function propre(v: unknown, cle: string): unknown {
    if (typeof v !== "object" || v === null) return undefined;
    try { const d = Object.getOwnPropertyDescriptor(v, cle); return d && "value" in d ? d.value : undefined; }
    catch { return undefined; }
  }
  function lire(brut: unknown, jour: string) {
    const copie = copierJsonLecture(brut);
    const refusMetier = propre(propre(brut, "resultat"), "accepte") === false;
    if (copie === JSON_LECTURE_INVALIDE) return { ok: false as const, genre: refusMetier || propre(brut, "ok") === false ? "refus" as const : "illisible" as const,
      verdict: { code: "reponse_illisible", detail: "" } };
    if (refusMetier) return interpreter({ ok: true, resultat: propre(copie, "resultat") }, "directe", lireVueExecutive);
    return interpreter(copie, "directe", valeur => {
      const vue = lireVueExecutive(valeur);
      return vue !== null && (vue.cashLibre.genre !== "lu" || vue.cashLibre.age.aujourdHui === jour) ? vue : null;
    });
  }
  const args = construireArgumentsVueExecutive(aujourdHui);
  return {
    outil: OUTIL_VUE_EXECUTIVE, args, cache: "vue_executive_constat", invaliderCacheSurRefus: true,
    interpreter: v => lire(v, aujourdHui),
    interpreterCache: v => {
      const copie = copierJsonLecture(v);
      if (copie === JSON_LECTURE_INVALIDE || typeof copie !== "object" || copie === null || Array.isArray(copie) ||
          Object.keys(copie).length !== 2 || !Object.hasOwn(copie, "aujourd_hui") || !Object.hasOwn(copie, "enveloppe") ||
          !estJourCashLibre(copie.aujourd_hui)) return { ok: false, genre: "illisible", verdict: { code: "reponse_illisible", detail: "" } };
      return lire(copie.enveloppe, copie.aujourd_hui);
    },
    epurerPourLeCache: v => ({ aujourd_hui: aujourdHui, enveloppe: epurerVueExecutive(v) }),
  };
}

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
    chargerVueExecutive: () => lireSection(config, sectionVueExecutive(aujourdHui())),
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
