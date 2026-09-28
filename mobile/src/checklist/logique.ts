import type { ItemChecklist } from "./types";

/** Reducer PUR de `checklist.tsx` — voir `types.ts` pour pourquoi cette liste est composée par
 * l'employé plutôt que puisée dans un catalogue serveur inexistant. `id` est fourni par
 * l'appelant (même discipline que `src/outbox/mutation.ts::creerMutation` : généré par
 * `expo-crypto` en production, déterministe dans les tests). */
export function ajouterItem(items: readonly ItemChecklist[], id: string, texte: string): ItemChecklist[] {
  const propre = texte.trim();
  if (propre === "") {
    return [...items]; // fail-closed : jamais un item vide ajouté silencieusement
  }
  return [...items, { id, texte: propre, fait: false }];
}

export function basculerItem(items: readonly ItemChecklist[], id: string): ItemChecklist[] {
  return items.map((item) => (item.id === id ? { ...item, fait: !item.fait } : item));
}

export function retirerItem(items: readonly ItemChecklist[], id: string): ItemChecklist[] {
  return items.filter((item) => item.id !== id);
}

/** `checklist_complete` (`preuves.py`) : une checklist VIDE n'est jamais terminée — même lecture
 * que `photos_apres` côté serveur (« une checklist "en cours" ne clôt rien », `preuves.py`,
 * docstring). */
export function checklistTerminee(items: readonly ItemChecklist[]): boolean {
  return items.length > 0 && items.every((item) => item.fait);
}
