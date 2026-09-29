/**
 * Les quatre profils de l'app mobile (DEFINITION-PRODUIT §9, R12 §5). R12 §6 : le jeton
 * d'appareil porte un rôle d'opérateur nommé, mappé un-à-un sur ces profils — c'est pourquoi
 * un seul type sert à la fois pour « rôle porté par le jeton » et « groupe de routes protégé ».
 */
export type Profil = "admin" | "employee" | "seller" | "client";

export const PROFILS: readonly Profil[] = ["admin", "employee", "seller", "client"];

/**
 * État de session tel que le reste de l'app le consulte. `role` reste une chaîne libre (pas
 * `Profil`) : c'est à `evaluerGarde` de trancher, jamais à ce type de le présupposer (fail-closed, P2).
 * Depuis PLAN T1.4-c5, `role` est le rôle NOMMÉ que le serveur a confirmé pour cet appareil
 * (`src/identite/etat.ts::sessionDepuisEtat`), jamais le rôle de transport du jeton (`operator`).
 */
export type SessionAppareil = { readonly presente: false } | { readonly presente: true; readonly role: string };

export type MotifRefusGarde = "session_absente" | "role_inconnu" | "role_non_autorise";

export type VerdictGarde =
  | { readonly autorise: true }
  | { readonly autorise: false; readonly motif: MotifRefusGarde; readonly redirectionVers: "/" };
