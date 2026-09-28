import { Redirect, Stack } from "expo-router";

import { useSessionAppareil } from "@/roles/contexte";
import { evaluerGarde } from "@/roles/garde";

/** Garde du groupe `(seller)` — voir app/(employee)/_layout.tsx pour le commentaire complet. */
export default function LayoutSeller() {
  const session = useSessionAppareil();
  const verdict = evaluerGarde(session, "seller");
  if (!verdict.autorise) {
    return <Redirect href={verdict.redirectionVers} />;
  }
  return <Stack screenOptions={{ headerShown: false }} />;
}
