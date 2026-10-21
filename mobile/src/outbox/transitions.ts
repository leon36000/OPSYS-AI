import type { StatutMutation } from "./types";

export type ResultatTransition =
  | { readonly ok: true }
  | { readonly ok: false; readonly motif: "transition_interdite"; readonly de: StatutMutation; readonly vers: StatutMutation };

/**
 * Graphe FERMÉ des transitions permises (R12 §4 : `brouillon` → `en_attente` → `envoi` →
 * `envoyee` | `echec_permanent`, plus le retour `envoi` → `en_attente` pour un échec
 * réessayable). Toute paire absente de cette table est refusée — fail-closed (P2) : aucune
 * transition n'est tolérée par défaut, seules celles listées ici le sont.
 */
const TRANSITIONS_PERMISES: ReadonlyMap<StatutMutation, ReadonlySet<StatutMutation>> = new Map<
  StatutMutation,
  ReadonlySet<StatutMutation>
>([
  ["brouillon", new Set<StatutMutation>(["en_attente"])],
  ["en_attente", new Set<StatutMutation>(["envoi"])],
  ["envoi", new Set<StatutMutation>(["envoyee", "en_attente", "echec_permanent"])],
  ["envoyee", new Set<StatutMutation>()],
  ["echec_permanent", new Set<StatutMutation>()],
]);

export function transitionEstPermise(de: StatutMutation, vers: StatutMutation): boolean {
  return TRANSITIONS_PERMISES.get(de)?.has(vers) ?? false;
}

/** Version « verdict » de `transitionEstPermise`, utilisée par src/outbox/mutation.ts pour
 * produire un message d'erreur précis quand une transition est refusée. */
export function verifierTransition(de: StatutMutation, vers: StatutMutation): ResultatTransition {
  if (!transitionEstPermise(de, vers)) {
    return { ok: false, motif: "transition_interdite", de, vers };
  }
  return { ok: true };
}
