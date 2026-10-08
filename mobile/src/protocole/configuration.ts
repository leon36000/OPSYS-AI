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
let generationLectures = 0;

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
  if (configurationActuelle?.urlBase !== configuration?.urlBase || configurationActuelle?.jeton !== configuration?.jeton ||
      configurationActuelle?.appareilId !== configuration?.appareilId) generationLectures += 1;
  configurationActuelle = configuration;
}

/**
 * La personne que le serveur a confirmée (ou dont la dernière confirmation est gardée hors ligne) POUR CE
 * JETON (PLAN T1.4-l). Elle est liée au jeton et à l'appareil, pas seulement à la personne : après un
 * nouvel appairage le jeton change, cette identité ne s'applique plus, et la file sortante n'envoie rien
 * tant que le serveur n'a pas dit, pour le NOUVEAU jeton, qui est cette personne.
 */
export interface PersonneConfirmee {
  readonly jeton: string;
  readonly appareilId: string;
  readonly personne: string;
  /** Named role confirmed by the identity reader; not sent as request authority. */
  readonly role?: string;
}

let personneConfirmee: PersonneConfirmee | null = null;

/** Posé par le cycle d'identité (`src/identite/sessionEnvoi.ts`) ; `null` quand aucune personne n'est confirmée. */
export function definirPersonneConfirmee(confirmee: PersonneConfirmee | null): void {
  if (personneConfirmee?.jeton !== confirmee?.jeton || personneConfirmee?.appareilId !== confirmee?.appareilId ||
      personneConfirmee?.personne !== confirmee?.personne || personneConfirmee?.role !== confirmee?.role) generationLectures += 1;
  personneConfirmee = confirmee;
}

/** Tout ce qu'il faut pour envoyer UNE mutation : où, avec quel jeton, et pour quelle personne. */
export interface SessionEnvoi extends ConfigurationAppel {
  readonly personne: string;
}

/**
 * Ce que la file sortante lit AVANT CHAQUE envoi (PLAN T1.4-l) : jamais un jeton gardé d'avant. `null`
 * (rien ne part) tant que l'appareil n'est pas apparié, ou que la personne confirmée n'est pas celle DU
 * JETON COURANT — le cas juste après un nouvel appairage, jusqu'à la première lecture de l'identité.
 * Synchrone, comme `obtenirConfigurationAppel`.
 */
export function obtenirSessionEnvoi(): SessionEnvoi | null {
  const configuration = configurationActuelle;
  const confirmee = personneConfirmee;
  if (
    !configuration ||
    !confirmee ||
    confirmee.jeton !== configuration.jeton ||
    confirmee.appareilId !== configuration.appareilId
  ) {
    return null;
  }
  return { ...configuration, personne: confirmee.personne };
}

/** Captures authority before an async read. Identical confirmations preserve it;
 * token, device, person or named-role changes invalidate it. No token is persisted. */
export function capturerSessionLecture(): { readonly session: SessionEnvoi | null; readonly courante: () => boolean } {
  const session = obtenirSessionEnvoi();
  const generation = generationLectures;
  return { session, courante: () => session !== null && generation === generationLectures && obtenirSessionEnvoi() !== null };
}

/** Les projections de mémoire ne sont lisibles que dans une session admin confirmée. */
export function capturerSessionAdminLecture(): { readonly session: SessionEnvoi | null; readonly courante: () => boolean } {
  const capture = capturerSessionLecture();
  if (personneConfirmee?.role !== "admin") return { session: null, courante: () => false };
  return { session: capture.session, courante: () => capture.courante() && personneConfirmee?.role === "admin" };
}
