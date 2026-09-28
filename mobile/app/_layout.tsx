// Initialise i18next avant le premier rendu (effet de bord d'import — R12 §3, P12 AGENTS.md).
import "@/i18n";

import { useEffect } from "react";
import { Stack } from "expo-router";

import { chargerSession } from "@/appairage/stockage";
import { definirConfigurationAppel } from "@/protocole/configuration";
import { SessionProvider, useDefinirSessionAppareil } from "@/roles/contexte";

/**
 * Layout racine (PLAN T1.4-a item 2 ; mis à jour PLAN T1.4-c3) : session (`SessionProvider`),
 * i18n (import ci-dessus), restauration au démarrage d'une session déjà appariée
 * (`RestaurationSession` ci-dessous). Le routage par rôle vit dans chaque `_layout.tsx` de
 * groupe (src/roles/garde.ts), pas ici : ce layout ne fait que composer les fournisseurs et le
 * navigateur racine.
 */
export default function LayoutRacine() {
  return (
    <SessionProvider>
      <RestaurationSession />
      <Stack screenOptions={{ headerShown: false }} />
    </SessionProvider>
  );
}

/**
 * Relit `expo-secure-store` UNE FOIS au montage (PLAN T1.4-c3) : si un appairage précédent a
 * persisté une session (`app/pairing/index.tsx`, `src/appairage/stockage.ts`), restaure à la
 * fois la configuration de connexion (`src/protocole/configuration.ts`, consommée par
 * `src/outbox/service.ts`) et la session de rôle (`src/roles/contexte.tsx`, consommée par
 * `src/roles/garde.ts`) SANS repasser par un nouvel appairage. Ne rend rien. Sans session
 * persistée (premier lancement, ou après une déconnexion), ne fait rien : la session reste
 * `{presente: false}` comme avant — aucun faux état apparié inventé (AGENTS.md, fail-closed).
 */
function RestaurationSession() {
  const definirSession = useDefinirSessionAppareil();

  useEffect(() => {
    let annulee = false;
    void (async () => {
      const session = await chargerSession();
      if (annulee || !session) {
        return;
      }
      definirConfigurationAppel({
        urlBase: session.urlBase,
        jeton: session.jeton,
        appareilId: session.appareilId,
      });
      definirSession({ presente: true, role: session.role });
    })();
    return () => {
      annulee = true;
    };
  }, [definirSession]);

  return null;
}
