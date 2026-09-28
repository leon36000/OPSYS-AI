import { AppState } from "react-native";
import NetInfo from "@react-native-community/netinfo";

import { declencherVidange } from "./service";

/** Sous-ensemble de `AppState` (react-native) réellement utilisé ici — injectable pour les
 * tests, sans dépendre du natif. */
export interface FournisseurEtatApp {
  addEventListener(type: "change", listener: (etat: string) => void): { remove(): void };
}

/** Sous-ensemble de `NetInfo` (@react-native-community/netinfo) réellement utilisé ici. */
export interface FournisseurReseau {
  addEventListener(listener: (etat: { readonly isConnected: boolean | null }) => void): () => void;
}

export interface OptionsDeclencheursVidange {
  /** Injecté pour les tests (mission item 5, même principe que `src/protocole/client.ts`) ; en
   * production, `declencherVidange` de `src/outbox/service.ts`. */
  readonly declencher?: () => Promise<unknown>;
  readonly appState?: FournisseurEtatApp;
  readonly netInfo?: FournisseurReseau;
  /** Appelé après CHAQUE tentative de vidange déclenchée ici (succès ou échec) — un écran monté
   * s'en sert pour rafraîchir l'état de synchro qu'il affiche sans avoir à poser son propre
   * abonnement AppState/NetInfo. */
  readonly aoDeclenchement?: () => void;
}

/**
 * Câble les deux déclencheurs de vidange prévus par la mission (R12 §4) : premier plan
 * (`AppState`, état `"active"`) et retour du réseau (`NetInfo`, `isConnected: true`). N'avale
 * PAS les erreurs de `declencher` sans les signaler : elles sont attrapées ici (un déclencheur
 * d'arrière-plan ne doit jamais faire planter l'écran qui l'a monté), mais journalisées via
 * `console.error` plutôt qu'ignorées en silence — un échec de VIDANGE elle-même (réseau/HTTP)
 * est déjà, lui, absorbé et reflété dans le statut de chaque mutation (`src/outbox/vidangeur.ts`) ;
 * ce qui est attrapé ici, ce sont les pannes plus rares de la couche stockage (SQLite) que
 * `service.ts` documente comme volontairement PAS avalées à sa propre frontière.
 *
 * Retourne une fonction de nettoyage (à appeler dans le retour d'un `useEffect`).
 */
export function demarrerDeclencheursVidange(options: OptionsDeclencheursVidange = {}): () => void {
  const declencher = options.declencher ?? declencherVidange;
  const appState = options.appState ?? AppState;
  const netInfo = options.netInfo ?? NetInfo;

  function declencherEtSignaler(): void {
    declencher()
      .catch((erreur: unknown) => {
        // eslint-disable-next-line no-console
        console.error("opsys: échec de la vidange déclenchée en arrière-plan", erreur);
      })
      .finally(() => {
        options.aoDeclenchement?.();
      });
  }

  const abonnementEtat = appState.addEventListener("change", (etat) => {
    if (etat === "active") {
      declencherEtSignaler();
    }
  });
  const abonnementReseau = netInfo.addEventListener((etat) => {
    if (etat.isConnected) {
      declencherEtSignaler();
    }
  });

  return () => {
    abonnementEtat.remove();
    abonnementReseau();
  };
}
