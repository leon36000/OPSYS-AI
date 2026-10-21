// Initialise i18next avant le premier rendu (effet de bord d'import — R12 §3, P12 AGENTS.md).
import "@/i18n";

import { useEffect } from "react";
import { Stack } from "expo-router";

import { useCycleIdentite } from "@/identite/hooks";
import { demarrerDeclencheursVidange } from "@/outbox/declencheurs";
import { ecouterRefusAppareil } from "@/outbox/refusAppareil";
import { declencherVidange, vidangerEnArrierePlan } from "@/outbox/service";
import { SessionProvider } from "@/roles/contexte";

/**
 * Layout racine (PLAN T1.4-a item 2 ; mis à jour PLAN T1.4-c3 puis T1.4-c5) : état de l'app
 * (`SessionProvider`), i18n (import ci-dessus), et le cycle de l'identité (`CycleIdentiteApp` ci-dessous).
 * Le routage par rôle vit dans chaque `_layout.tsx` de groupe (src/roles/garde.ts) et dans l'aiguilleur
 * `app/index.tsx` : ce layout ne fait que composer les fournisseurs et le navigateur racine.
 */
export default function LayoutRacine() {
  return (
    <SessionProvider>
      <CycleIdentiteApp />
      <Stack screenOptions={{ headerShown: false }} />
    </SessionProvider>
  );
}

/**
 * Restaure la session appairée depuis `expo-secure-store` (jeton, URL, dernière identité confirmée),
 * puis relit l'identité auprès du serveur : au démarrage, à chaque retour au premier plan et à chaque
 * retour du réseau (mêmes déclencheurs que la file sortante). Sans session persistée (premier lancement),
 * l'état devient « non appairé ». Ne rend rien. Voir `src/identite/hooks.ts`.
 *
 * File sortante (PLAN T1.4-l) : l'identité d'abord, la vidange ensuite — la file n'envoie que pour la
 * personne que le serveur vient de confirmer pour le jeton courant, donc après un nouvel appairage elle
 * repart d'elle-même, avec le nouveau jeton, sans redémarrer l'app. Et quand la file se fait refuser
 * l'APPAREIL (jeton révoqué), on relit l'identité — ce qui renvoie l'app à l'écran d'identité — sans
 * relancer de vidange : voir `src/outbox/refusAppareil.ts`.
 */
function CycleIdentiteApp() {
  const { restaurer, rafraichir } = useCycleIdentite();

  useEffect(() => {
    void restaurer().then(vidangerEnArrierePlan);
  }, [restaurer]);

  useEffect(
    () =>
      demarrerDeclencheursVidange({
        declencher: async () => {
          await rafraichir();
          await declencherVidange();
        },
      }),
    [rafraichir],
  );

  useEffect(
    () =>
      ecouterRefusAppareil(() => {
        void rafraichir();
      }),
    [rafraichir],
  );

  return null;
}
