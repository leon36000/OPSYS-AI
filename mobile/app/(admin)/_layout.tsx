import { Redirect, Stack } from "expo-router";

import { useSessionAppareil, usePersonneAppairee } from "@/roles/contexte";
import { evaluerGarde } from "@/roles/garde";

/**
 * Garde du groupe `(admin)` — voir app/(employee)/_layout.tsx pour le commentaire complet.
 * C'est précisément le cas nommé par la mission : un jeton `employee` n'atteint jamais ici.
 */
export default function LayoutAdmin() {
  const session = useSessionAppareil();
  const personne = usePersonneAppairee();
  const verdict = evaluerGarde(session, "admin");
  if (!verdict.autorise) {
    return <Redirect href={verdict.redirectionVers} />;
  }
  return <Stack key={JSON.stringify([personne, session.presente ? session.role : null])} screenOptions={{ headerShown: false }}>
    <Stack.Screen name="marketing" />
    <Stack.Screen name="reception" />
    <Stack.Screen name="memoire" />
  </Stack>;
}
