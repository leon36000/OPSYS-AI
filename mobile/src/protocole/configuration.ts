/** Ce qu'il faut pour appeler `/tools/invoke` en production : l'URL de la passerelle, le jeton
 * d'appareil scellé par rôle, et l'identité d'appareil (R12 §1.2, §1.3, §6). */
export interface ConfigurationAppel {
  readonly urlBase: string;
  readonly jeton: string;
  readonly appareilId: string;
}

/**
 * État EN MÉMOIRE de la configuration de connexion — jamais lu directement depuis
 * `expo-secure-store` ici (cette lecture est asynchrone ; `obtenirConfigurationAppel` doit
 * rester synchrone, voir plus bas). `définirConfigurationAppel` est appelé :
 * - par `app/pairing/index.tsx` juste après un appairage réussi (`src/appairage/client.ts`) ;
 * - par le bootstrap de `app/_layout.tsx` au lancement, s'il retrouve une session déjà persistée
 *   (`src/appairage/stockage.ts`, `chargerSession`) — restaure la configuration SANS repasser
 *   par un nouvel appairage.
 * Symétrique de `src/roles/contexte.tsx` (`SessionProvider`/`définirSession`), mais en dehors de
 * React : `src/outbox/service.ts` lit `obtenirConfigurationAppel()` depuis du code qui n'est pas
 * un composant.
 */
let configurationActuelle: ConfigurationAppel | null = null;

/**
 * Source de la configuration de connexion. Renvoie `null` tant qu'aucun appairage réel n'a eu
 * lieu ET qu'aucune session persistée n'a été restaurée — même philosophie que
 * `src/roles/contexte.tsx` (`SessionProvider` démarre TOUJOURS `{presente: false}`) : « on
 * n'invente aucun faux état apparié ».
 *
 * Un vidangeur sans configuration n'est simplement pas construit (`src/outbox/service.ts`) :
 * la file sortante continue d'accumuler les mutations sans risque (R12 §4, « ne jamais perdre
 * silencieusement ») en attendant. Reste SYNCHRONE à dessein (PLAN T1.4-c3) : `service.ts` n'a
 * pas eu à changer sa forme d'appel (`const configuration = obtenirConfigurationAppel();`),
 * seule la lecture d'`expo-secure-store` — intrinsèquement asynchrone — se fait en amont, au
 * moment de l'appairage ou du bootstrap (voir `définirConfigurationAppel`).
 */
export function obtenirConfigurationAppel(): ConfigurationAppel | null {
  return configurationActuelle;
}

/** Point d'entrée UNIQUE qui fait passer `obtenirConfigurationAppel` de `null` à une vraie
 * configuration (ou inversement, `null`, après une révocation/déconnexion — non câblé dans cette
 * tranche, aucun écran ne le déclenche encore). */
export function definirConfigurationAppel(configuration: ConfigurationAppel | null): void {
  configurationActuelle = configuration;
}
