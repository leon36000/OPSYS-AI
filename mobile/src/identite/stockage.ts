import { coffreExpoSecureStore, type CoffreAppairage } from "../appairage/stockage";
import { estRoleNomme, type IdentiteOpsys } from "./contrat";

/**
 * Dernière identité CONFIRMÉE par le serveur, gardée dans `expo-secure-store` (même coffre que le jeton
 * d'appareil) pour que l'app reste utilisable hors ligne. Ce n'est jamais une source de vérité : elle est
 * marquée « à reconfirmer » tant que le serveur ne l'a pas relue, et effacée dès qu'il refuse l'appareil
 * ou que l'appareil est appairé de nouveau.
 */

export interface IdentiteMemorisee extends IdentiteOpsys {
  /** Moment de la dernière confirmation par le serveur, ISO 8601. */
  readonly confirmeLe: string;
}

const CLE_IDENTITE_CONFIRMEE = "opsys_identite_confirmee_v1";

export async function sauvegarderIdentiteMemorisee(
  identite: IdentiteMemorisee,
  coffre: CoffreAppairage = coffreExpoSecureStore,
): Promise<void> {
  await coffre.setItemAsync(CLE_IDENTITE_CONFIRMEE, JSON.stringify(identite));
}

function estIdentiteMemorisee(valeur: unknown): valeur is IdentiteMemorisee {
  if (typeof valeur !== "object" || valeur === null) {
    return false;
  }
  const objet = valeur as Record<string, unknown>;
  return (
    typeof objet.appareilId === "string" &&
    typeof objet.personne === "string" &&
    objet.personne.trim() !== "" &&
    estRoleNomme(objet.role) &&
    typeof objet.confirmeLe === "string" &&
    !Number.isNaN(Date.parse(objet.confirmeLe))
  );
}

/**
 * `null` si rien n'est gardé, si la valeur est corrompue ou d'un format inconnu, si le rôle n'est pas un
 * rôle nommé connu, ou si l'identité gardée est celle d'un AUTRE appareil que `appareilId` — fail-closed :
 * jamais une identité devinée, complétée ou héritée d'un appairage précédent.
 */
export async function chargerIdentiteMemorisee(
  appareilId: string,
  coffre: CoffreAppairage = coffreExpoSecureStore,
): Promise<IdentiteMemorisee | null> {
  const brute = await coffre.getItemAsync(CLE_IDENTITE_CONFIRMEE);
  if (!brute) {
    return null;
  }
  try {
    const valeur: unknown = JSON.parse(brute);
    if (!estIdentiteMemorisee(valeur) || valeur.appareilId !== appareilId) {
      return null;
    }
    return {
      appareilId: valeur.appareilId,
      personne: valeur.personne,
      role: valeur.role,
      confirmeLe: valeur.confirmeLe,
    };
  } catch {
    return null;
  }
}

export async function effacerIdentiteMemorisee(coffre: CoffreAppairage = coffreExpoSecureStore): Promise<void> {
  await coffre.deleteItemAsync(CLE_IDENTITE_CONFIRMEE);
}
