import type { MutationOutbox } from "./types";

/**
 * Frontière de stockage de la file sortante. La logique (transitions, planification, recul,
 * création) ne dépend jamais de cette interface — seule l'intégration en dépend : l'adaptateur
 * `expo-sqlite` (depot.sqlite.ts) en production, `DepotOutboxMemoire` ci-dessous dans les tests
 * (PLAN T1.4-a item 4 : « les tests exercent la logique via une implémentation mémoire »).
 */
export interface DepotOutbox {
  lister(): Promise<MutationOutbox[]>;
  obtenir(id: string): Promise<MutationOutbox | null>;
  /**
   * Insère la mutation et lui assigne sa `sequence` (entier strictement croissant, « clé
   * auto-incrémentée SQLite ou compteur du dépôt ») — c'est pourquoi ceci renvoie la mutation
   * PERSISTÉE (avec `sequence` non nulle), pas `void` : l'appelant doit utiliser cette valeur de
   * retour pour toute opération ultérieure, jamais l'objet passé en argument (dont la `sequence`
   * est encore `null`).
   */
  inserer(mutation: MutationOutbox): Promise<MutationOutbox>;
  mettreAJour(mutation: MutationOutbox): Promise<void>;
  /** Une seule comparaison/écriture atomique ; false conserve intégralement la ligne concurrente. */
  mettreAJourSiInchangee(attendue: InstantaneMutationOutbox, suivante: MutationOutbox): Promise<boolean>;
}

/** Snapshot de valeurs pris avant toute attente : aucune référence mutable au payload/reçu. */
export function capturerMutationOutbox(mutation: MutationOutbox) {
  return Object.freeze({ id: mutation.id, sequence: mutation.sequence, type: mutation.type,
    chantierId: mutation.chantierId, payload: JSON.stringify(mutation.payload), dependsOn: mutation.dependsOn,
    createdAtLocal: mutation.createdAtLocal, proprietaire: mutation.proprietaire, destination: mutation.destination ?? null,
    statut: mutation.statut, tentatives: mutation.tentatives, prochaineTentativeA: mutation.prochaineTentativeA,
    resumeAccepte: mutation.resumeAccepte == null ? null : JSON.stringify(mutation.resumeAccepte) });
}
export type InstantaneMutationOutbox = ReturnType<typeof capturerMutationOutbox>;

/** Les transitions CAS ne peuvent changer ni la clé, ni la charge, ni son propriétaire. */
export function memeIntentionOutbox(a: InstantaneMutationOutbox, b: InstantaneMutationOutbox): boolean {
  return a.id === b.id && a.sequence === b.sequence && a.type === b.type && a.chantierId === b.chantierId &&
    a.payload === b.payload && a.dependsOn === b.dependsOn && a.createdAtLocal === b.createdAtLocal && a.proprietaire === b.proprietaire && a.destination === b.destination;
}

/** Implémentation mémoire de `DepotOutbox`, utilisée par les tests. */
export class DepotOutboxMemoire implements DepotOutbox {
  private readonly lignes = new Map<string, MutationOutbox>();
  private prochaineSequence = 1;

  async lister(): Promise<MutationOutbox[]> {
    return Array.from(this.lignes.values());
  }

  async obtenir(id: string): Promise<MutationOutbox | null> {
    return this.lignes.get(id) ?? null;
  }

  async inserer(mutation: MutationOutbox): Promise<MutationOutbox> {
    if (this.lignes.has(mutation.id)) {
      throw new Error(`mutation déjà présente dans le dépôt : ${mutation.id}`);
    }
    const persistee: MutationOutbox = { ...mutation, sequence: this.prochaineSequence, resumeAccepte: mutation.resumeAccepte ?? null };
    this.prochaineSequence += 1;
    this.lignes.set(mutation.id, persistee);
    return persistee;
  }

  async mettreAJourSiInchangee(attendue: InstantaneMutationOutbox, suivante: MutationOutbox): Promise<boolean> {
    const actuelle = this.lignes.get(attendue.id);
    if (!actuelle || !memeIntentionOutbox(attendue, capturerMutationOutbox(suivante)) ||
      JSON.stringify(capturerMutationOutbox(actuelle)) !== JSON.stringify(attendue)) return false;
    this.lignes.set(attendue.id, suivante);
    return true;
  }

  async mettreAJour(mutation: MutationOutbox): Promise<void> {
    if (!this.lignes.has(mutation.id)) {
      throw new Error(`mutation absente du dépôt, impossible de la mettre à jour : ${mutation.id}`);
    }
    this.lignes.set(mutation.id, mutation);
  }
}
