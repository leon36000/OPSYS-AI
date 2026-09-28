// Initialise i18next avant le premier rendu (effet de bord d'import — R12 §3, P12 AGENTS.md).
import "@/i18n";

import { Stack } from "expo-router";

import { SessionProvider } from "@/roles/contexte";

/**
 * Layout racine (PLAN T1.4-a item 2) : session (`SessionProvider`), i18n (import ci-dessus).
 * Le « profil actif » est simplement dérivé de la session par src/roles — rien à faire ici.
 * Le routage par rôle vit dans chaque `_layout.tsx` de groupe (src/roles/garde.ts), pas ici :
 * ce layout ne fait que composer les fournisseurs et le navigateur racine.
 */
export default function LayoutRacine() {
  return (
    <SessionProvider>
      <Stack screenOptions={{ headerShown: false }} />
    </SessionProvider>
  );
}
