import type { MutationOutbox, StatutMutation } from "./types";

/**
 * Statuts éligibles à un envoi immédiat. `envoi` y figure exprès : une ligne retrouvée dans cet
 * état au démarrage n'est pas un échec, c'est une reprise après crash/redémarrage en plein
 * envoi (R12 §4) — elle doit être renvoyée avec le MÊME id (= idempotencyKey), jamais recréée.
 * `identifierMutationsAReprendre` ci-dessous isole ce sous-cas pour que l'appelant puisse le
 * tracer séparément (P3, traçabilité), mais la sélection normale l'inclut aussi.
 */
const STATUTS_ENVOYABLES = new Set<StatutMutation>(["en_attente", "envoi"]);

function parentEstEnvoyee(mutation: MutationOutbox, parId: ReadonlyMap<string, MutationOutbox>): boolean {
  if (mutation.dependsOn === null) {
    return true;
  }
  return parId.get(mutation.dependsOn)?.statut === "envoyee";
}

/**
 * Sélectionne, DANS L'ORDRE où elles doivent être envoyées, les mutations actuellement
 * envoyables (R12 §4) :
 *   1. statut `en_attente` ou `envoi` (reprise) ;
 *   2. si `dependsOn` est renseigné, la mutation parente doit être `envoyee` — « une mutation
 *      n'est jamais envoyée avant sa parente ‹ envoyée › » ;
 *   3. triées par chantier puis par heure de création locale (FIFO par chantier).
 * Fonction pure : ne lit ni n'écrit aucun stockage, prend et retourne des données.
 */
export function selectionnerProchainesEnvoyables(mutations: readonly MutationOutbox[]): MutationOutbox[] {
  const parId = new Map(mutations.map((m) => [m.id, m] as const));
  return mutations
    .filter((m) => STATUTS_ENVOYABLES.has(m.statut))
    .filter((m) => parentEstEnvoyee(m, parId))
    .slice()
    .sort((a, b) => {
      if (a.chantierId !== b.chantierId) {
        return a.chantierId < b.chantierId ? -1 : 1;
      }
      if (a.createdAtLocal !== b.createdAtLocal) {
        return a.createdAtLocal < b.createdAtLocal ? -1 : 1;
      }
      return 0;
    });
}

/**
 * Sous-ensemble « reprise au démarrage » (statut `envoi` trouvé en base) — isolé pour que
 * l'appelant puisse journaliser cette reprise distinctement (P3) avant de la fondre dans la
 * sélection générale ci-dessus.
 */
export function identifierMutationsAReprendre(mutations: readonly MutationOutbox[]): MutationOutbox[] {
  return mutations.filter((m) => m.statut === "envoi");
}
