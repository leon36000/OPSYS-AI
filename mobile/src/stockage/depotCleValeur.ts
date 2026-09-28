/**
 * Frontière de stockage clé/valeur PARTAGÉE (texte JSON) — brique interne commune à `src/today`
 * (cache de lecture de `m4_lister_interventions`) et `src/checklist` (liste d'items par
 * chantier), pour éviter de dupliquer deux adaptateurs `expo-sqlite` quasi identiques (AGENTS.md :
 * réutiliser plutôt que réécrire). Même patron que `src/outbox/depot.ts` : interface pure,
 * implémentation mémoire ici (utilisée par les tests), adaptateur `expo-sqlite` réel dans
 * `depotCleValeur.sqlite.ts` (non exercé par Jest, même limite que `src/outbox/depot.sqlite.ts` —
 * pas de SQLite natif sous Jest).
 *
 * PAS pour des secrets : `expo-secure-store` reste la seule destination des jetons/clés
 * d'appareil (R12 §6) — ce dépôt est pour de la donnée métier NON sensible, déjà lisible par un
 * appel serveur ou déjà saisie localement par l'employé.
 */
export interface DepotCleValeur {
  lire(cle: string): Promise<string | null>;
  ecrire(cle: string, valeur: string): Promise<void>;
}

export class DepotCleValeurMemoire implements DepotCleValeur {
  private readonly valeurs = new Map<string, string>();

  async lire(cle: string): Promise<string | null> {
    return this.valeurs.get(cle) ?? null;
  }

  async ecrire(cle: string, valeur: string): Promise<void> {
    this.valeurs.set(cle, valeur);
  }
}
