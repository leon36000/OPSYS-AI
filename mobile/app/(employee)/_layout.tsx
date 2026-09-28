import { Redirect, Stack } from "expo-router";

import { useSessionAppareil } from "@/roles/contexte";
import { evaluerGarde } from "@/roles/garde";

/**
 * Garde du groupe `(employee)` (PLAN T1.4-a item 3, src/roles/garde.ts). Un jeton d'un autre
 * rôle — ou aucune session — est refusé ici, avant que quoi que ce soit du groupe ne s'affiche,
 * y compris par navigation directe vers son URL.
 */
export default function LayoutEmployee() {
  const session = useSessionAppareil();
  const verdict = evaluerGarde(session, "employee");
  if (!verdict.autorise) {
    return <Redirect href={verdict.redirectionVers} />;
  }
  return <Stack screenOptions={{ headerShown: false }} />;
}
