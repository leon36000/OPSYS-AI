import { verifierTransition } from "./transitions";
import type { MutationOutbox, StatutMutation, TypeMutation } from "./types";

export interface ParametresCreationMutation {
  readonly type: TypeMutation;
  readonly chantierId: string;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly dependsOn?: string | null;
}

export interface HorlogeAppareil {
  readonly maintenant: Date;
  /** Décalage local par rapport à UTC, en minutes (ex. -240 pour l'heure avancée de l'Est). */
  readonly decalageMinutesUTC: number;
}

/** Refusé quand un appelant tente une transition hors du graphe de `transitions.ts` — une
 * erreur de programmation (l'orchestrateur n'aurait pas dû appeler cette fonction ici), pas
 * un aléa métier : voir `transitions.ts` pour le refus « attendu » et testé exhaustivement. */
export class ErreurTransitionInterdite extends Error {
  constructor(
    public readonly de: StatutMutation,
    public readonly vers: StatutMutation,
  ) {
    super(`transition de file sortante interdite : ${de} → ${vers}`);
    this.name = "ErreurTransitionInterdite";
  }
}

function transitionnerOuLever(mutation: MutationOutbox, vers: StatutMutation): void {
  const resultat = verifierTransition(mutation.statut, vers);
  if (!resultat.ok) {
    throw new ErreurTransitionInterdite(resultat.de, resultat.vers);
  }
}

function partie(n: number, longueur = 2): string {
  return String(n).padStart(longueur, "0");
}

/**
 * Formate un horodatage local ISO 8601 AVEC le décalage de l'appareil (jamais `Z`/UTC — R12
 * §4 : « chaque événement porte l'heure de l'appareil… et l'heure de réception du serveur »,
 * les deux sont conservées, mais ce module ne produit que la première).
 */
export function formaterHorodatageLocal(horloge: HorlogeAppareil): string {
  const local = new Date(horloge.maintenant.getTime() + horloge.decalageMinutesUTC * 60_000);
  const date = `${local.getUTCFullYear()}-${partie(local.getUTCMonth() + 1)}-${partie(local.getUTCDate())}`;
  const heure = `${partie(local.getUTCHours())}:${partie(local.getUTCMinutes())}:${partie(local.getUTCSeconds())}`;
  const signe = horloge.decalageMinutesUTC < 0 ? "-" : "+";
  const decalageAbs = Math.abs(horloge.decalageMinutesUTC);
  const decalage = `${partie(Math.floor(decalageAbs / 60))}:${partie(decalageAbs % 60)}`;
  return `${date}T${heure}${signe}${decalage}`;
}

/**
 * Crée une mutation `brouillon`. L'id est fourni par l'appelant (`genererId`) plutôt que généré
 * ici : en production c'est `src/outbox/id.ts` (expo-crypto `randomUUID`, appareil, avant tout
 * réseau — R12 §4) ; dans les tests, un générateur déterministe. Cela garde ce module pur.
 */
export function creerMutation(
  params: ParametresCreationMutation,
  genererId: () => string,
  horloge: HorlogeAppareil,
): MutationOutbox {
  return {
    id: genererId(),
    type: params.type,
    chantierId: params.chantierId,
    payload: params.payload,
    dependsOn: params.dependsOn ?? null,
    statut: "brouillon",
    tentatives: 0,
    createdAtLocal: formaterHorodatageLocal(horloge),
  };
}

/** `brouillon` -> `en_attente` : soumission explicite par l'employé (R12 §4, §9.3). */
export function soumettreMutation(mutation: MutationOutbox): MutationOutbox {
  transitionnerOuLever(mutation, "en_attente");
  return { ...mutation, statut: "en_attente" };
}

/** `en_attente` -> `envoi` : la boucle de vidage commence l'envoi réseau. */
export function marquerEnvoi(mutation: MutationOutbox): MutationOutbox {
  transitionnerOuLever(mutation, "envoi");
  return { ...mutation, statut: "envoi" };
}

/** `envoi` -> `envoyee` : accusé de réception du serveur (statut terminal). */
export function marquerEnvoyee(mutation: MutationOutbox): MutationOutbox {
  transitionnerOuLever(mutation, "envoyee");
  return { ...mutation, statut: "envoyee" };
}

/** `envoi` -> `en_attente` : échec réessayable (réseau, délai, 408/429/5xx — src/protocole).
 * Incrémente le compteur de tentatives, consommé ensuite par `src/outbox/recul.ts`. */
export function marquerEchecReessayable(mutation: MutationOutbox): MutationOutbox {
  transitionnerOuLever(mutation, "en_attente");
  return { ...mutation, statut: "en_attente", tentatives: mutation.tentatives + 1 };
}

/** `envoi` -> `echec_permanent` : échec non réessayable (statut terminal). */
export function marquerEchecPermanent(mutation: MutationOutbox): MutationOutbox {
  transitionnerOuLever(mutation, "echec_permanent");
  return { ...mutation, statut: "echec_permanent" };
}
