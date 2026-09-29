import { useCallback, useMemo, useRef } from "react";

import { useDefinirEtatIdentite } from "../roles/contexte";
import {
  definirConfigurationAppel,
  obtenirConfigurationAppel,
  type ConfigurationAppel,
} from "../protocole/configuration";
import { lireEtMemoriserIdentite, oublierIdentiteMemorisee, restaurerSession } from "./service";

export interface CycleIdentite {
  /** Relit le coffre (session et dernière identité confirmée), puis l'identité auprès du serveur. */
  readonly restaurer: () => Promise<void>;
  /** Relit l'identité auprès du serveur (démarrage, retour au premier plan, retour du réseau, « Réessayer »). */
  readonly rafraichir: () => Promise<void>;
  /**
   * Après un appairage réussi (la configuration de la nouvelle session est déjà posée) : l'ancienne identité
   * ne vaut plus, la lecture repart de zéro. L'état passe à « en lecture » avant le premier `await`.
   */
  readonly apresAppairage: () => Promise<void>;
}

interface LectureEnCours {
  readonly configuration: ConfigurationAppel;
  /** Ne rejette jamais : `lireEtMemoriserIdentite` ne lève pas. */
  readonly promesse: Promise<void>;
}

function memeSession(a: ConfigurationAppel | null, b: ConfigurationAppel): boolean {
  return a !== null && a.jeton === b.jeton && a.appareilId === b.appareilId;
}

/**
 * Cycle de vie de l'identité de l'appareil (PLAN T1.4-c5), branché sur l'état de l'app. Une seule lecture
 * du serveur à la fois par session : le retour au premier plan et le retour du réseau arrivent souvent
 * ensemble. Le résultat d'une lecture est jeté si la session a changé entre-temps (nouvel appairage) : une
 * réponse pour l'ancien jeton ne dit rien de la nouvelle session, dont la propre lecture attend la fin de
 * l'ancienne.
 */
export function useCycleIdentite(): CycleIdentite {
  const definirEtat = useDefinirEtatIdentite();
  const enCours = useRef<LectureEnCours | null>(null);

  const rafraichir = useCallback((): Promise<void> => {
    const configuration = obtenirConfigurationAppel();
    if (!configuration) {
      return Promise.resolve();
    }
    const existante = enCours.current;
    if (existante && memeSession(existante.configuration, configuration)) {
      return existante.promesse;
    }
    const promesse = (async () => {
      if (existante) {
        await existante.promesse;
      }
      const etat = await lireEtMemoriserIdentite({ configuration });
      if (memeSession(obtenirConfigurationAppel(), configuration)) {
        definirEtat(etat);
      }
    })();
    const lecture: LectureEnCours = { configuration, promesse };
    enCours.current = lecture;
    void promesse.finally(() => {
      if (enCours.current === lecture) {
        enCours.current = null;
      }
    });
    return promesse;
  }, [definirEtat]);

  const restaurer = useCallback(async (): Promise<void> => {
    const { configuration, etat } = await restaurerSession();
    // Un coffre illisible ne retire pas la configuration déjà en mémoire : la file sortante continue.
    if (etat.genre !== "erreur") {
      definirConfigurationAppel(configuration);
    }
    definirEtat(etat);
    if (configuration) {
      await rafraichir();
    }
  }, [definirEtat, rafraichir]);

  const apresAppairage = useCallback(async (): Promise<void> => {
    // L'état d'abord, de façon synchrone : l'appelant navigue vers l'aiguilleur tout de suite après, qui ne
    // doit pas lire l'état d'avant l'appairage (« non appairé ») et renvoyer la personne à l'appairage.
    definirEtat({ genre: "en_lecture" });
    await oublierIdentiteMemorisee();
    await rafraichir();
  }, [definirEtat, rafraichir]);

  return useMemo(() => ({ restaurer, rafraichir, apresAppairage }), [restaurer, rafraichir, apresAppairage]);
}
