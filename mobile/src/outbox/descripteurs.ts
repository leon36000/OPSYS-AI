import { interpreterResultatDemarrerRoute } from "../m4/interventions";
import { interpreterResultatPointage } from "../m4/pointage";
import type { DescripteurTypeMutation, InterpretationResultatMetier } from "./vidangeur";
import type { TypeMutation } from "./types";

/**
 * Adapte `interpreterResultatPointage` (src/m4/pointage.ts, vocabulaire M4 — `accuse`) à la
 * forme générique qu'attend `DescripteurTypeMutation.interpreterResultat` (src/outbox/vidangeur.ts,
 * vocabulaire neutre — `resume`) : `vidangeur.ts` ne connaît rien de M4, et `pointage.ts` ne
 * connaît rien de la file sortante — cette fonction est le SEUL endroit qui relie les deux
 * vocabulaires, pour qu'aucun des deux modules n'ait à emprunter le mot de l'autre.
 */
function versInterpretationGenerique(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatPointage(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.accuse };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle que `versInterpretationGenerique` ci-dessus, pour `m4_demarrer_route`
 * (`src/m4/interventions.ts`, PLAN T1.4-e) — `job/[id]/index.tsx`, bouton « En route ». */
function versInterpretationGeneriqueDemarrerRoute(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatDemarrerRoute(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.resultat };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/**
 * Association type de mutation -> outil réel (`/tools/invoke`, `tool`) + interprète de sa
 * réponse business. `punch_in`/`punch_out` : T1.4-d, R12 §5 étape 2 — voir
 * `app/(employee)/punch.tsx` pour le choix punch_in = arrivée/fin de pause, punch_out =
 * départ/début de pause (`src/ecrans/punch.ts`), réutilisé TEL QUEL par `job/[id]/index.tsx`
 * (T1.4-e, `src/ecrans/job.ts`) pour « Arrivé »/« Pause », bornés à CE chantier. `job_status_change`
 * : T1.4-e, `job/[id]/index.tsx`, bouton « En route » (`m4_demarrer_route`) — SEULE direction de
 * ce type aujourd'hui (voir `src/ecrans/job.ts`, en-tête) ; une tranche future qui ajouterait
 * d'autres transitions de statut (report, annulation) devra soit ajouter un type de mutation
 * dédié par transition, soit faire porter l'outil par le PAYLOAD plutôt que par le descripteur —
 * non fait ici, hors périmètre.
 *
 * `photo_upload`/`signature_capture` (T1.4-e, `src/photos/`, `src/signature/`) : DÉLIBÉRÉMENT
 * SANS DESCRIPTEUR — ces mutations restent `brouillon` pour toujours (jamais
 * `soumettreMutation`, voir `src/photos/mutation.ts`/`src/signature/mutation.ts`), tant qu'aucune
 * route serveur n'existe pour envoyer le binaire (R12 §4, gap documenté dans MOBILE.md). Un
 * descripteur enregistré ici SANS outil réel derrière ferait échouer le vidangeur (`Error`,
 * `vidangeur.ts`) le jour où l'une de ces mutations serait, par erreur, soumise — l'ABSENCE de
 * descripteur est le filet de sécurité, pas un oubli.
 */
export const DESCRIPTEURS_MUTATION: ReadonlyMap<TypeMutation, DescripteurTypeMutation> = new Map([
  ["punch_in", { tool: "m4_pointer", interpreterResultat: versInterpretationGenerique }],
  ["punch_out", { tool: "m4_pointer", interpreterResultat: versInterpretationGenerique }],
  ["job_status_change", { tool: "m4_demarrer_route", interpreterResultat: versInterpretationGeneriqueDemarrerRoute }],
]);
