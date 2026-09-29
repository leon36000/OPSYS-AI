import { estObjet, texteOuNull } from "../protocole/enveloppeOutil";

/**
 * Petits lecteurs défensifs des réponses du profil admin (PLAN T4.20). Une valeur qui n'a pas la forme attendue n'est
 * jamais corrigée ni devinée : le lecteur rend `null` (ou `undefined` pour « présente mais mal formée », quand `null` est
 * lui-même une valeur légitime), et l'appelant compte l'élément illisible ou refuse toute la réponse.
 *
 * Aucun lecteur ne convertit un montant en nombre : un montant est un texte décimal que le serveur a calculé
 * (`format(Decimal, "f")`), et il le reste de bout en bout (mise en forme par les chiffres, jamais par un flottant).
 */
export { estObjet, texteOuNull };

/** Un texte décimal positionnel, tel que le serveur le rend : « 14106.32 », « -500.00 », « 0 », « 3.01 ». */
const DECIMAL = /^-?\d+(?:\.\d+)?$/;

export function estDecimal(valeur: unknown): valeur is string {
  return typeof valeur === "string" && DECIMAL.test(valeur);
}

/** `string` : un décimal ; `null` : la valeur est nulle (le serveur dit « pas de valeur ») ; `undefined` : mal formée. */
export function decimalNullable(valeur: unknown): string | null | undefined {
  if (valeur === null) {
    return null;
  }
  return estDecimal(valeur) ? valeur : undefined;
}

export function entierPositifOuNull(valeur: unknown): number | null {
  return typeof valeur === "number" && Number.isInteger(valeur) && valeur >= 0 ? valeur : null;
}

/** Un entier, négatif permis (`jours_avant_paiement` : négatif quand la limite est passée). */
export function entierOuNull(valeur: unknown): number | null {
  return typeof valeur === "number" && Number.isInteger(valeur) ? valeur : null;
}

/** `string | null` : un texte non vide, ou nul ; `undefined` : ni l'un ni l'autre. */
export function texteNullable(valeur: unknown): string | null | undefined {
  if (valeur === null) {
    return null;
  }
  return texteOuNull(valeur) ?? undefined;
}

/** Une liste de textes non vides ; `null` si ce n'est pas une liste, ou si un élément n'est pas un texte. */
export function listeDeTextes(valeur: unknown): readonly string[] | null {
  if (!Array.isArray(valeur)) {
    return null;
  }
  const textes: string[] = [];
  for (const element of valeur) {
    const texte = texteOuNull(element);
    if (texte === null) {
      return null;
    }
    textes.push(texte);
  }
  return textes;
}

export interface ListeLue<T> {
  readonly items: readonly T[];
  /** Éléments de la liste que ce client n'a pas su lire : comptés, jamais devinés ni cachés. */
  readonly illisibles: number;
}

/** Lit chaque élément ; `null` si `brut` n'est pas une liste (la réponse entière est alors illisible). */
export function lireListe<T>(brut: unknown, lireElement: (element: unknown) => T | null): ListeLue<T> | null {
  if (!Array.isArray(brut)) {
    return null;
  }
  const lus = brut.map(lireElement);
  const items = lus.filter((element): element is T => element !== null);
  return { items, illisibles: lus.length - items.length };
}
