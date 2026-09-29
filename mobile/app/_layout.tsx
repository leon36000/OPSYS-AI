// Initialise i18next avant le premier rendu (effet de bord d'import — R12 §3, P12 AGENTS.md).
import "@/i18n";

import { useEffect } from "react";
import { Stack } from "expo-router";

import { useCycleIdentite } from "@/identite/hooks";
import { demarrerDeclencheursVidange } from "@/outbox/declencheurs";
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
 */
function CycleIdentiteApp() {
  const { restaurer, rafraichir } = useCycleIdentite();

  useEffect(() => {
    void restaurer();
  }, [restaurer]);

  useEffect(() => demarrerDeclencheursVidange({ declencher: rafraichir }), [rafraichir]);

  return null;
}
