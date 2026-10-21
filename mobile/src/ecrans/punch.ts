import type { ActionPointageM4 } from "../m4/pointage";
import type { TypeMutation } from "../outbox/types";

/**
 * Logique PURE de `app/(employee)/punch.tsx` (M4.4), extraite dans ce module parce que
 * `@testing-library/react-native` n'est pas dans la pile installée (`mobile/package.json` — ni
 * en dépendance, ni résolu dans `package-lock.json` : seule une mention en pair optionnel
 * d'`expo-router` y apparaît) : la mission demande alors de tester la logique d'écran extraite
 * en fonctions pures plutôt que le composant rendu. `punch.tsx` importe ce module et ne fait
 * lui-même que du câblage React (état, effets, JSX).
 */

/** État LOCAL de l'écran — PAS le statut serveur de l'intervention (`etats.py` côté M4, que ce
 * squelette ne connaît pas encore, faute de session/`today.tsx`) : seulement assez pour savoir
 * quel(s) bouton(s) proposer ensuite, sur l'appareil, hors ligne. */
export type PhasePointage = "avant_arrivee" | "sur_place" | "en_pause";

export type ActionEmploye = "entree" | "sortie" | "pause";

export interface ResultatActionEmploye {
  readonly phaseSuivante: PhasePointage;
  /** Seuls ces deux types sont créés par cet écran (mission item 2) — le `payload.action` réel
   * (pointage.ACTIONS) porte la nuance arrivée/départ/pause, voir `action` ci-dessous. */
  readonly typeMutation: Extract<TypeMutation, "punch_in" | "punch_out">;
  readonly action: ActionPointageM4;
}

/**
 * Graphe fermé des transitions locales (fail-closed, même esprit que
 * `src/outbox/transitions.ts`) : `entree`/`sortie`/`pause` sont CE QUE `m4_pointer` accepte
 * réellement (`pointage.ACTIONS`), jamais une action inventée. Une pause bascule entre
 * `pause_debut`/`pause_fin` selon la phase courante.
 *
 * Choix de mapping type-de-mutation (documenté aussi dans MOBILE.md, car ni R12 ni le
 * catalogue `TypeMutation` de T1.4-a n'anticipaient la pause) : `punch_in` = l'employé DEVIENT
 * présent/actif (arrivée OU fin de pause), `punch_out` = l'employé DEVIENT absent (départ OU
 * début de pause). La mission demande explicitement de ne créer QUE des mutations
 * `punch_in`/`punch_out` ; l'action `m4_pointer` exacte (les 4 valeurs réelles) voyage dans
 * `payload.action`, jamais dans le type de mutation lui-même.
 */
const TRANSITIONS: Readonly<Record<PhasePointage, Partial<Readonly<Record<ActionEmploye, ResultatActionEmploye>>>>> = {
  avant_arrivee: {
    entree: { phaseSuivante: "sur_place", typeMutation: "punch_in", action: "arrivee" },
  },
  sur_place: {
    sortie: { phaseSuivante: "avant_arrivee", typeMutation: "punch_out", action: "depart" },
    pause: { phaseSuivante: "en_pause", typeMutation: "punch_out", action: "pause_debut" },
  },
  en_pause: {
    pause: { phaseSuivante: "sur_place", typeMutation: "punch_in", action: "pause_fin" },
  },
};

/** Fail-closed : une action hors du graphe (ex. « sortie » pendant `avant_arrivee`) renvoie
 * `null` plutôt qu'un état inventé — l'écran ne doit jamais pouvoir l'appeler (voir
 * `actionsDisponibles`, qui pilote quels boutons sont proposés), mais la fonction reste sûre si
 * un appelant futur se trompe. */
export function resoudreActionEmploye(phase: PhasePointage, action: ActionEmploye): ResultatActionEmploye | null {
  return TRANSITIONS[phase][action] ?? null;
}

/** Les actions à proposer (boutons actifs) pour la phase courante, dans un ordre stable. */
export function actionsDisponibles(phase: PhasePointage): readonly ActionEmploye[] {
  const ordre: readonly ActionEmploye[] = ["entree", "sortie", "pause"];
  return ordre.filter((action) => TRANSITIONS[phase][action] !== undefined);
}

/**
 * Extrait `{heures, minutes}` d'un horodatage local ISO 8601 AVEC décalage
 * (`MutationOutbox.createdAtLocal`, `src/outbox/mutation.ts` `formaterHorodatageLocal` —
 * JAMAIS `Z`/UTC). Découpage TEXTUEL plutôt que `new Date(...).getHours()` : un ISO avec
 * décalage réinterprété par `Date` suit le fuseau du RUNTIME qui l'affiche, pas celui déjà
 * capturé dans la chaîne — ce module doit rester correct même exécuté (tests Jest, CI) depuis
 * un fuseau différent de celui de l'appareil qui a créé la mutation.
 */
export function extraireHeureMinuteLocale(createdAtLocal: string): { heures: string; minutes: string } | null {
  const correspondance = /T(\d{2}):(\d{2})/.exec(createdAtLocal);
  if (!correspondance) {
    return null;
  }
  const [, heures, minutes] = correspondance;
  return { heures, minutes };
}

/** État de synchro à afficher pour une mutation de pointage donnée — dérivé du statut PERSISTÉ
 * de la mutation (`MutationOutbox.statut`, toujours disponible, y compris après redémarrage) et,
 * quand disponible, du verdict de la dernière vidange REÇUE PAR CETTE SESSION (`RapportVidange`,
 * `src/outbox/vidangeur.ts` — le verdict business n'est pas persisté dans la ligne `outbox`
 * elle-même ; voir MOBILE.md pour cette limite assumée). */
export type EtatSynchroAffiche =
  | { readonly genre: "en_attente" }
  | { readonly genre: "envoi" }
  | { readonly genre: "envoyee" }
  | { readonly genre: "echec_permanent"; readonly verdict: { readonly code: string; readonly detail: string } | null };

export function deriverEtatSynchroAffiche(
  statut: "brouillon" | "en_attente" | "envoi" | "envoyee" | "echec_permanent",
  dernierVerdictConnu: { readonly code: string; readonly detail: string } | null,
): EtatSynchroAffiche {
  switch (statut) {
    case "envoyee":
      return { genre: "envoyee" };
    case "envoi":
      return { genre: "envoi" };
    case "echec_permanent":
      return { genre: "echec_permanent", verdict: dernierVerdictConnu };
    default:
      return { genre: "en_attente" };
  }
}
