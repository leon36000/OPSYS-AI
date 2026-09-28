/** Ce qu'il faut pour appeler `/tools/invoke` en production : l'URL de la passerelle, le jeton
 * d'appareil scellé par rôle, et l'identité d'appareil (R12 §1.2, §1.3, §6). */
export interface ConfigurationAppel {
  readonly urlBase: string;
  readonly jeton: string;
  readonly appareilId: string;
}

/**
 * Source de la configuration de connexion. Renvoie TOUJOURS `null` pour l'instant : aucun
 * appairage réel n'existe (PLAN T1.4-c, docs/architecture/MOBILE.md « Appairage — à faire »),
 * donc aucune URL de passerelle ni jeton d'appareil scellé à lire nulle part dans l'app — même
 * philosophie que `src/roles/contexte.tsx` (`SessionProvider` démarre TOUJOURS
 * `{presente: false}`) : « on n'invente aucun faux état apparié ».
 *
 * Un vidangeur sans configuration n'est simplement pas construit (`src/outbox/service.ts`) :
 * la file sortante continue d'accumuler les mutations sans risque (R12 §4, « ne jamais perdre
 * silencieusement ») en attendant. Point d'extension pour T1.4-c : remplacer le corps de cette
 * fonction par une lecture de la session appairée, sans toucher à
 * `src/outbox/service.ts`/`vidangeur.ts` ni à aucun écran.
 */
export function obtenirConfigurationAppel(): ConfigurationAppel | null {
  return null;
}
