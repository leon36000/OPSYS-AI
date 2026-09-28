import { Redirect, Stack } from "expo-router";

import { useSessionAppareil } from "@/roles/contexte";
import { evaluerGarde } from "@/roles/garde";

/**
 * Garde du groupe `(client)` — voir app/(employee)/_layout.tsx pour le commentaire complet.
 * R12 §6 : le profil client n'est pas un appareil apparié durablement (lien signé, à durée
 * limitée) — cette garde reste néanmoins la même : elle ne fait aucune hypothèse sur COMMENT
 * `session.role === "client"` a été obtenu, seulement sur CE QU'IL AUTORISE une fois obtenu.
 */
export default function LayoutClient() {
  const session = useSessionAppareil();
  const verdict = evaluerGarde(session, "client");
  if (!verdict.autorise) {
    return <Redirect href={verdict.redirectionVers} />;
  }
  return <Stack screenOptions={{ headerShown: false }} />;
}
