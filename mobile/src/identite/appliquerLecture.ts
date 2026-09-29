import type { ConfigurationAppel } from "../protocole/configuration";
import type { EtatIdentite } from "./etat";

/**
 * Ce que fait l'app d'une lecture de l'identité qui vient d'aboutir (`useCycleIdentite`, PLAN T1.4-n) :
 *  1. si la session a changé entre-temps (nouvel appairage), le résultat est JETÉ : une réponse pour l'ancien jeton ne dit
 *     rien de la nouvelle session, ni pour le profil ni pour les caches ;
 *  2. sinon, les caches de l'identité précédente sont effacés AVANT que l'état change : les écrans du nouveau profil ne
 *     relisent jamais rien de l'ancien ;
 *  3. puis l'état est appliqué. Une purge qui échoue ne l'empêche jamais : le profil ne reste pas figé pour une panne de
 *     stockage, et la purge est retentée à la confirmation suivante (`src/identite/caches.ts`).
 * Fonction sans React ni stockage en dur : tout est injecté, l'ordre est testé (`appliquerLecture.test.ts`).
 */
export interface DependancesAppliquerLecture {
  readonly configurationCourante: () => ConfigurationAppel | null;
  readonly synchroniserCaches: (etat: EtatIdentite) => Promise<unknown>;
  readonly definirEtat: (etat: EtatIdentite, configuration: ConfigurationAppel) => void;
}

/** `true` : l'état a été appliqué ; `false` : la session avait changé, le résultat est jeté. */
export async function appliquerLecture(
  etat: EtatIdentite,
  configuration: ConfigurationAppel,
  dependances: DependancesAppliquerLecture,
): Promise<boolean> {
  const courante = dependances.configurationCourante();
  if (courante === null || courante.jeton !== configuration.jeton || courante.appareilId !== configuration.appareilId) {
    return false;
  }
  try {
    await dependances.synchroniserCaches(etat);
  } catch (erreur) {
    // Le journal ne porte que le nom de l'opération et l'erreur : jamais une personne, jamais un jeton.
    // eslint-disable-next-line no-console
    console.error("opsys: caches de l'identité précédente non effacés (retenté à la prochaine confirmation)", erreur);
  }
  dependances.definirEtat(etat, configuration);
  return true;
}
