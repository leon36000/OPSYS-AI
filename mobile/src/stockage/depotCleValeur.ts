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
  /** Efface UNE clé ; une clé absente n'est pas une erreur. */
  supprimer(cle: string): Promise<void>;
  /**
   * Efface toutes les clés qui COMMENCENT par `prefixe` (PLAN T1.4-n : purge des caches d'une identité qui n'est plus
   * celle de l'appareil, `src/identite/caches.ts`). Un préfixe vide est refusé : il effacerait tout le dépôt, y compris
   * ce qui n'est pas un cache (checklists, identifiants de complétion).
   */
  supprimerParPrefixe(prefixe: string): Promise<void>;
}

export const ERREUR_PREFIXE_VIDE = "supprimerParPrefixe : un préfixe vide effacerait tout le dépôt";

export class DepotCleValeurMemoire implements DepotCleValeur {
  private readonly valeurs = new Map<string, string>();

  async lire(cle: string): Promise<string | null> {
    return this.valeurs.get(cle) ?? null;
  }

  async ecrire(cle: string, valeur: string): Promise<void> {
    this.valeurs.set(cle, valeur);
  }

  async supprimer(cle: string): Promise<void> {
    this.valeurs.delete(cle);
  }

  async supprimerParPrefixe(prefixe: string): Promise<void> {
    if (prefixe === "") {
      throw new Error(ERREUR_PREFIXE_VIDE);
    }
    for (const cle of [...this.valeurs.keys()]) {
      if (cle.startsWith(prefixe)) {
        this.valeurs.delete(cle);
      }
    }
  }

  /** Les clés présentes, triées : ce que les tests regardent pour dire « il ne reste rien ». */
  cles(): readonly string[] {
    return [...this.valeurs.keys()].sort();
  }
}
