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

/**
 * Association type de mutation -> outil réel (`/tools/invoke`, `tool`) + interprète de sa
 * réponse business. Seuls `punch_in`/`punch_out` sont câblés dans cette tranche (T1.4-d, R12 §5
 * étape 2) — voir `app/(employee)/punch.tsx` pour le choix punch_in = arrivée/fin de pause,
 * punch_out = départ/début de pause (`src/ecrans/punch.ts`). Les tranches suivantes
 * enregistrent ici leur propre descripteur pour leurs types (ex. `materials_submit` ->
 * `m6_soumettre_materiaux_utilises`), sans toucher à `vidangeur.ts`.
 */
export const DESCRIPTEURS_MUTATION: ReadonlyMap<TypeMutation, DescripteurTypeMutation> = new Map([
  ["punch_in", { tool: "m4_pointer", interpreterResultat: versInterpretationGenerique }],
  ["punch_out", { tool: "m4_pointer", interpreterResultat: versInterpretationGenerique }],
]);
