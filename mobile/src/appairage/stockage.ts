import { getRandomBytes } from "expo-crypto";
import * as SecureStore from "expo-secure-store";

import { chargerIdentiteDepuisCleSecrete, creerIdentiteDepuisGraine, type IdentiteAppareil } from "./identite";

/**
 * Persistance de l'identité d'appareil et de la session appariée dans `expo-secure-store`
 * (Keychain iOS / Keystore Android — R12 §3, §6 : « jamais dans la base SQLite ni
 * `AsyncStorage` », mission item 2 : « jamais journalisée »). Aucune fonction de ce module
 * n'écrit la clé secrète ni le jeton dans un `console.*`/une erreur — seules les CLÉS de
 * stockage (des noms fixes, pas des secrets) apparaissent dans un message d'erreur éventuel.
 */

export interface SessionAppairee {
  readonly urlBase: string;
  readonly jeton: string;
  readonly role: string;
  readonly appareilId: string;
}

/** Sous-ensemble de `expo-secure-store` réellement utilisé — injectable (mission item 5, même
 * principe que `FournisseurEtatApp`/`FournisseurReseau` de `src/outbox/declencheurs.ts`). */
export interface CoffreAppairage {
  getItemAsync(cle: string): Promise<string | null>;
  setItemAsync(cle: string, valeur: string): Promise<void>;
  deleteItemAsync(cle: string): Promise<void>;
}

const CLE_IDENTITE = "opsys_appareil_cle_secrete_v1";
const CLE_SESSION = "opsys_appareil_session_v1";

export const coffreExpoSecureStore: CoffreAppairage = {
  getItemAsync: (cle) => SecureStore.getItemAsync(cle),
  setItemAsync: (cle, valeur) => SecureStore.setItemAsync(cle, valeur),
  deleteItemAsync: (cle) => SecureStore.deleteItemAsync(cle),
};

/**
 * Charge l'identité d'appareil persistée, ou en génère et en persiste une nouvelle si aucune
 * n'existe encore (premier lancement). La MÊME identité traverse ainsi les ré-appairages : le
 * `deviceId` (dérivé de la clé publique, `identite.ts`) reste stable pour l'historique
 * d'approbation côté propriétaire.
 */
export async function chargerOuCreerIdentite(
  coffre: CoffreAppairage = coffreExpoSecureStore,
  genererGraine: () => Uint8Array = () => getRandomBytes(32),
): Promise<IdentiteAppareil> {
  const existante = await coffre.getItemAsync(CLE_IDENTITE);
  if (existante) {
    return chargerIdentiteDepuisCleSecrete(existante);
  }
  const identite = creerIdentiteDepuisGraine(genererGraine());
  await coffre.setItemAsync(CLE_IDENTITE, identite.cleSecreteBase64Url);
  return identite;
}

export async function sauvegarderSession(
  session: SessionAppairee,
  coffre: CoffreAppairage = coffreExpoSecureStore,
): Promise<void> {
  await coffre.setItemAsync(CLE_SESSION, JSON.stringify(session));
}

function estSessionAppairee(valeur: unknown): valeur is SessionAppairee {
  if (typeof valeur !== "object" || valeur === null) {
    return false;
  }
  const objet = valeur as Record<string, unknown>;
  return (
    typeof objet.urlBase === "string" &&
    typeof objet.jeton === "string" &&
    typeof objet.role === "string" &&
    typeof objet.appareilId === "string"
  );
}

/** `null` si aucune session n'est stockée, ou si la valeur stockée est corrompue/d'un format
 * inconnu — fail-closed (AGENTS.md) : jamais une session partielle ou devinée. */
export async function chargerSession(coffre: CoffreAppairage = coffreExpoSecureStore): Promise<SessionAppairee | null> {
  const brute = await coffre.getItemAsync(CLE_SESSION);
  if (!brute) {
    return null;
  }
  try {
    const valeur: unknown = JSON.parse(brute);
    return estSessionAppairee(valeur) ? valeur : null;
  } catch {
    return null;
  }
}

export async function effacerSession(coffre: CoffreAppairage = coffreExpoSecureStore): Promise<void> {
  await coffre.deleteItemAsync(CLE_SESSION);
}
