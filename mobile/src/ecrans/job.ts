import type { ActionPointageM4 } from "../m4/pointage";
import type { StatutInterventionM4 } from "../m4/interventions";

/**
 * Logique PURE de `app/(employee)/job/[id]/index.tsx` (M4.7, R12 §5 étape 3 — PLAN T1.4-e),
 * même discipline que `src/ecrans/punch.ts` : `job/[id]/index.tsx` importe ce module et ne fait
 * lui-même que le câblage React (pas de `@testing-library/react-native` dans la pile installée).
 *
 * DEFINITION-PRODUIT.md §9.3 nomme quatre transitions ici : « en route, arrivé, démarrer, pause ».
 * `etats.py` (lu, jamais exécuté) n'en connaît que DEUX au niveau de la machine à états de
 * l'intervention (`planifiee -> en_route` via `m4_demarrer_route` ; `en_route -> sur_site` via
 * `m4_pointer(action="arrivee")`, `pointage.py` étape 13) — sa propre note de migration dit
 * explicitement que `sur_site` « regroupe arrived+started du produit, qu'un seul état M4 porte
 * encore » (`etats.py`, en-tête). Il N'EXISTE DONC PAS de transition serveur distincte pour
 * « démarrer » : ce module ne lui associe volontairement AUCUNE action — l'écran affiche
 * « Arrivé » comme couvrant les deux (voir MOBILE.md pour la décision documentée), plutôt que
 * d'inventer un bouton qui n'aurait rien à appeler. « Pause » réutilise TEL QUEL le mécanisme de
 * `m4_pointer` déjà câblé par `punch.tsx` (T1.4-d, `pointage.ACTIONS`) — mais bornée à CE
 * chantier (`intervention_id` fixé par la route), pas à l'employé en général.
 */

/** Phase locale de l'écran. `en_pause` n'existe QUE localement : `pointage.py` documente qu'une
 * pause est SANS EFFET sur `etats.py` (le statut serveur reste `sur_site` pendant une pause) —
 * elle est donc structurellement absente de `StatutInterventionM4` et ne peut jamais être
 * dérivée d'une lecture serveur, voir `phaseDepuisStatutServeur` ci-dessous. */
export type PhaseJob = "planifiee" | "en_route" | "sur_place" | "en_pause";

export type ActionJob = "enRoute" | "arrive" | "pause";

export type ResultatActionJob =
  | { readonly phaseSuivante: PhaseJob; readonly typeMutation: "job_status_change" }
  | {
      readonly phaseSuivante: PhaseJob;
      readonly typeMutation: "punch_in" | "punch_out";
      readonly action: ActionPointageM4;
    };

/** Graphe fermé (fail-closed, même esprit que `src/outbox/transitions.ts` et
 * `src/ecrans/punch.ts`). Une paire absente est refusée par `resoudreActionJob`, jamais devinée. */
const TRANSITIONS: Readonly<Record<PhaseJob, Partial<Readonly<Record<ActionJob, ResultatActionJob>>>>> = {
  planifiee: {
    enRoute: { phaseSuivante: "en_route", typeMutation: "job_status_change" },
  },
  en_route: {
    arrive: { phaseSuivante: "sur_place", typeMutation: "punch_in", action: "arrivee" },
  },
  sur_place: {
    pause: { phaseSuivante: "en_pause", typeMutation: "punch_out", action: "pause_debut" },
  },
  en_pause: {
    pause: { phaseSuivante: "sur_place", typeMutation: "punch_in", action: "pause_fin" },
  },
};

export function resoudreActionJob(phase: PhaseJob, action: ActionJob): ResultatActionJob | null {
  return TRANSITIONS[phase][action] ?? null;
}

/** Boutons à proposer pour la phase courante, ordre stable. */
export function actionsDisponiblesJob(phase: PhaseJob): readonly ActionJob[] {
  const ordre: readonly ActionJob[] = ["enRoute", "arrive", "pause"];
  return ordre.filter((action) => TRANSITIONS[phase][action] !== undefined);
}

/**
 * Dérive la phase locale de départ depuis le dernier statut serveur connu
 * (`src/today/statut.ts`). `null` pour tout statut hors du flux linéaire couvert par cette
 * tranche (`en_revue`, `reportee`, un statut terminal, ou une intervention encore inconnue) :
 * l'écran affiche alors le statut mais ne propose aucun bouton de transition plutôt que d'en
 * deviner un — checklist/photos/signature restent accessibles indépendamment (routes séparées).
 * `sur_site` redevient TOUJOURS `sur_place` (jamais `en_pause`, voir la docstring de `PhaseJob`
 * ci-dessus) : un rechargement du statut serveur ne peut jamais, par lui-même, remettre l'écran
 * en pause.
 */
export function phaseDepuisStatutServeur(statut: StatutInterventionM4 | null): PhaseJob | null {
  switch (statut) {
    case "planifiee":
      return "planifiee";
    case "en_route":
      return "en_route";
    case "sur_site":
      return "sur_place";
    default:
      return null;
  }
}
