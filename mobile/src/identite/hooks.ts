import { useCallback, useMemo, useRef } from "react";

import { useDefinirEtatIdentite } from "../roles/contexte";
import {
  definirConfigurationAppel,
  obtenirConfigurationAppel,
  type ConfigurationAppel,
} from "../protocole/configuration";
import { obtenirDepotLocal } from "../stockage/service";
import { appliquerLecture } from "./appliquerLecture";
import { synchroniserCachesSansEchouer } from "./caches";
import type { EtatIdentite } from "./etat";
import { lireEtMemoriserIdentite, oublierIdentiteMemorisee, restaurerSession } from "./service";
import { synchroniserPersonneConfirmee } from "./sessionEnvoi";

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
  const definirEtatApp = useDefinirEtatIdentite();
  const enCours = useRef<LectureEnCours | null>(null);

  // Chaque changement d'état de l'identité est aussi dit à la file sortante (PLAN T1.4-l) : elle n'envoie
  // que pour la personne confirmée POUR LE JETON de la configuration à laquelle cet état se rapporte.
  const definirEtat = useCallback(
    (etat: EtatIdentite, configuration: ConfigurationAppel | null): void => {
      synchroniserPersonneConfirmee(etat, configuration);
      definirEtatApp(etat);
    },
    [definirEtatApp],
  );

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
      // Révocation ou autre personne : les caches de l'ancienne identité sont effacés AVANT que le profil change (PLAN
      // T1.4-n, `src/identite/caches.ts`). Un résultat d'une session qui n'est plus la courante est jeté.
      await appliquerLecture(etat, configuration, {
        configurationCourante: obtenirConfigurationAppel,
        synchroniserCaches: (nouvelEtat, sessionToujoursCourante) => synchroniserCachesSansEchouer(obtenirDepotLocal, nouvelEtat, sessionToujoursCourante),
        definirEtat,
      });
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
    // La configuration EN MÉMOIRE après ce point : celle qui vient d'être posée, ou, si le coffre est
    // illisible, celle qui y était déjà.
    definirEtat(etat, obtenirConfigurationAppel());
    if (configuration) {
      await rafraichir();
    }
  }, [definirEtat, rafraichir]);

  const apresAppairage = useCallback(async (): Promise<void> => {
    // L'état d'abord, de façon synchrone : l'appelant navigue vers l'aiguilleur tout de suite après, qui ne
    // doit pas lire l'état d'avant l'appairage (« non appairé ») et renvoyer la personne à l'appairage.
    definirEtat({ genre: "en_lecture" }, obtenirConfigurationAppel());
    await oublierIdentiteMemorisee();
    await rafraichir();
  }, [definirEtat, rafraichir]);

  return useMemo(() => ({ restaurer, rafraichir, apresAppairage }), [restaurer, rafraichir, apresAppairage]);
}
