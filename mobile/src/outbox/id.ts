import * as Crypto from "expo-crypto";

/**
 * Génère un `mutation_id` UUID sur l'appareil, avant tout appel réseau (R12 §4, mission item 4 :
 * « brique vérifiée, ex. expo-crypto randomUUID »). Seule fonction impure du module outbox :
 * `creerMutation` (src/outbox/mutation.ts) prend un générateur en paramètre plutôt que
 * d'appeler ceci directement, pour rester pur et testable avec un id déterministe.
 */
export function genererMutationId(): string {
  return Crypto.randomUUID();
}
