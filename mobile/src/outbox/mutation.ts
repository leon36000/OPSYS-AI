import { calculerProchaineTentativeA } from "./recul";
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
 * `sequence` reste `null` tant que le dépôt n'a pas inséré la mutation (voir `depot.ts`) ;
 * `prochaineTentativeA` reste `null` : elle n'a encore jamais échoué ; `proprietaire` reste `null` :
 * c'est le dépôt de l'app (`src/outbox/proprietaire.ts`) qui le pose à l'insertion, d'après la personne
 * confirmée par le serveur — jamais l'appelant, qui pourrait se tromper de personne.
 */
export function creerMutation(
  params: ParametresCreationMutation,
  genererId: () => string,
  horloge: HorlogeAppareil,
): MutationOutbox {
  return {
    id: genererId(),
    sequence: null,
    type: params.type,
    chantierId: params.chantierId,
    payload: params.payload,
    dependsOn: params.dependsOn ?? null,
    statut: "brouillon",
    tentatives: 0,
    createdAtLocal: formaterHorodatageLocal(horloge),
    prochaineTentativeA: null,
    proprietaire: null,
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

/**
 * `envoi` -> `en_attente` : échec réessayable (réseau, délai, 408/429/5xx — src/protocole).
 * Incrémente le compteur de tentatives ET pose `prochaineTentativeA` via le recul exponentiel
 * de `src/outbox/recul.ts` — `maintenant` est injecté (fonction pure). `mutation.tentatives`
 * (AVANT incrément) est exactement le « compteur avant l'échec courant » attendu par
 * `calculerProchaineTentativeA`. Sans ce champ posé ici, le recul calculé n'était jamais
 * appliqué à la sélection (`selectionnerProchainesEnvoyables` renvoyait tout de suite) —
 * corrigé en relecture après PLAN T1.4-a.
 */
export function marquerEchecReessayable(mutation: MutationOutbox, maintenant: Date): MutationOutbox {
  transitionnerOuLever(mutation, "en_attente");
  return {
    ...mutation,
    statut: "en_attente",
    tentatives: mutation.tentatives + 1,
    prochaineTentativeA: calculerProchaineTentativeA(mutation.tentatives, maintenant).toISOString(),
  };
}

/** `envoi` -> `echec_permanent` : échec non réessayable (statut terminal). */
export function marquerEchecPermanent(mutation: MutationOutbox): MutationOutbox {
  transitionnerOuLever(mutation, "echec_permanent");
  return { ...mutation, statut: "echec_permanent" };
}

/**
 * `envoi` -> `en_attente` SANS faute de la mutation : ni tentative comptée, ni recul. Pour ce qui n'est pas
 * son échec — le serveur refuse l'APPAREIL (jeton révoqué, attribution retirée), ou la session a changé
 * pendant l'envoi. Elle repartira, avec la même `id` (donc la même clé d'idempotence), dès qu'une
 * session valide pour sa personne existera : la marquer `echec_permanent` la rendrait définitive alors
 * qu'elle n'a rien de faux.
 */
export function remettreEnAttenteSansFaute(mutation: MutationOutbox): MutationOutbox {
  // Le graphe permet aussi `brouillon` -> `en_attente` (la soumission par l'employé) : cette remise ne
  // doit JAMAIS soumettre un brouillon. Seule une mutation en `envoi` peut être remise en file ainsi.
  if (mutation.statut !== "envoi") {
    throw new ErreurTransitionInterdite(mutation.statut, "en_attente");
  }
  transitionnerOuLever(mutation, "en_attente");
  return { ...mutation, statut: "en_attente" };
}
