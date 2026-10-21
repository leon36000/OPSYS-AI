/**
 * Pont entre la file sortante et le cycle d'identité (PLAN T1.4-l). La file (`src/outbox/service.ts`) vit
 * hors de React ; le cycle d'identité (`src/identite/hooks.ts`) est un hook. Quand le serveur refuse
 * l'APPAREIL pendant une vidange (`estRefusAppareil`), la file le SIGNALE ici, et la racine de l'app
 * (`app/_layout.tsx`) relit l'identité auprès du serveur : un jeton révoqué y reçoit 401, l'état de l'app
 * passe à « erreur » et l'aiguilleur renvoie à l'écran d'identité, d'où l'on peut appairer de nouveau.
 *
 * Ce pont ne relance JAMAIS de vidange : signaler un refus lit l'identité, et s'arrête là. Sinon un
 * serveur qui refuserait les outils mais confirmerait l'identité ferait boucler vidange -> refus ->
 * lecture -> vidange. La prochaine vidange vient d'un déclencheur ordinaire (premier plan, retour du
 * réseau) ou d'un nouvel appairage.
 */

type Ecouteur = () => void;

const ecouteurs = new Set<Ecouteur>();

/** Enregistre un écouteur ; renvoie la fonction qui le retire (retour d'un `useEffect`). */
export function ecouterRefusAppareil(ecouteur: Ecouteur): () => void {
  ecouteurs.add(ecouteur);
  return () => {
    ecouteurs.delete(ecouteur);
  };
}

/** Prévient les écouteurs. Un écouteur qui lève n'empêche pas les autres, et ne fait jamais échouer la vidange. */
export function signalerRefusAppareil(): void {
  for (const ecouteur of [...ecouteurs]) {
    try {
      ecouteur();
    } catch (erreur) {
      // eslint-disable-next-line no-console
      console.error("opsys: écouteur de refus d'appareil en échec", erreur);
    }
  }
}
