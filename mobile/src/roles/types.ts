/**
 * Les quatre profils de l'app mobile (DEFINITION-PRODUIT §9, R12 §5). R12 §6 : le jeton
 * d'appareil porte un rôle d'opérateur nommé, mappé un-à-un sur ces profils — c'est pourquoi
 * un seul type sert à la fois pour « rôle porté par le jeton » et « groupe de routes protégé ».
 */
export type Profil = "admin" | "employee" | "seller" | "client";

export const PROFILS: readonly Profil[] = ["admin", "employee", "seller", "client"];

/**
 * État de session tel que le reste de l'app le consulte. `role` reste une chaîne libre (pas
 * `Profil`) : un jeton peut techniquement porter n'importe quelle valeur, connue ou non — c'est
 * à `evaluerGarde` de trancher, jamais à ce type de le présupposer (fail-closed, P2).
 */
export type SessionAppareil = { readonly presente: false } | { readonly presente: true; readonly role: string };

export type MotifRefusGarde = "session_absente" | "role_inconnu" | "role_non_autorise";

export type VerdictGarde =
  | { readonly autorise: true }
  | { readonly autorise: false; readonly motif: MotifRefusGarde; readonly redirectionVers: "/pairing" };
