import type { VerdictServeurFichier } from "./protocole";

/**
 * Découpage en blocs — CONTRAT FIXE `m4_deposer_fichier`/`m4_etat_fichier` (PLAN T1.4-f, donné
 * par la mission, aucune route serveur lisible dans ce bac à sable au moment d'écrire ce module
 * — un autre agent la livre EN PARALLÈLE, voir MOBILE.md) : blocs de taille FIXE
 * `TAILLE_BLOC_OCTETS` (262 144 octets décodés), sauf le DERNIER (1..262 144).
 */
export const TAILLE_BLOC_OCTETS = 262_144;

/** `taille_octets` : 1..10 485 760 (10 MiB) — borne du contrat. */
export const TAILLE_FICHIER_MAX_OCTETS = 10_485_760;

/** `nombre_blocs` : 1..64 — borne du contrat. Jamais atteinte en pratique tant que
 * `TAILLE_FICHIER_MAX_OCTETS` est respectée (10 485 760 / 262 144 = 40 blocs au maximum), donc
 * aucune validation séparée dessus : la borne de taille la couvre déjà entièrement. */
export const NOMBRE_BLOCS_MAX = 64;

/** `Math.ceil` : le dernier bloc peut être partiel (1..262 144 octets), jamais vide — voir
 * `validerTailleFichier` pour le rejet d'un `tailleOctets` de 0 ou hors bornes AVANT d'en arriver
 * ici (fail-closed, jamais un fichier à « 0 bloc » envoyé). */
export function calculerNombreBlocs(tailleOctets: number): number {
  return Math.ceil(tailleOctets / TAILLE_BLOC_OCTETS);
}

/** Découpe les octets fournis en blocs de `TAILLE_BLOC_OCTETS`, le dernier portant le reste.
 * `octets.length === 0` renvoie `[]` (aucun bloc) — jamais atteint en production si
 * `validerTailleFichier` a déjà refusé la taille en amont (voir `envoiOrchestrateur.ts`).
 * `Uint8Array#subarray` (pas `slice`) : une VUE sur le même buffer, jamais une copie — le fichier
 * complet ne double jamais en mémoire pour ce découpage (les 10 MiB maximum restent partagés). */
export function decouperEnBlocs(octets: Uint8Array): Uint8Array[] {
  const blocs: Uint8Array[] = [];
  for (let debut = 0; debut < octets.length; debut += TAILLE_BLOC_OCTETS) {
    blocs.push(octets.subarray(debut, Math.min(debut + TAILLE_BLOC_OCTETS, octets.length)));
  }
  return blocs;
}

/**
 * Garde locale AVANT toute tentative réseau — jamais un remplacement de l'autorité serveur
 * (celui-ci reste seul juge, voir `REJ-FICHIER-TROP-VOLUMINEUX` dans `protocole.ts`), seulement
 * un premier filtre fail-closed qui évite de découper/encoder puis d'envoyer un fichier que le
 * contrat refusera de toute façon. Réutilise le MÊME code `REJ-*` que le serveur (vocabulaire
 * partagé, jamais un code local inventé à part) : l'écran affiche un seul et même vocabulaire,
 * peu importe où le refus a été détecté.
 */
export function validerTailleFichier(tailleOctets: number): VerdictServeurFichier | null {
  if (!Number.isInteger(tailleOctets) || tailleOctets < 1 || tailleOctets > TAILLE_FICHIER_MAX_OCTETS) {
    return {
      code: "REJ-FICHIER-TROP-VOLUMINEUX",
      detail: `taille_octets hors bornes (1..${TAILLE_FICHIER_MAX_OCTETS}) : ${tailleOctets}`,
    };
  }
  return null;
}
