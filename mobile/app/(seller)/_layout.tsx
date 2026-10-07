import { Redirect, Stack } from "expo-router";

import { useSessionAppareil, usePersonneAppairee } from "@/roles/contexte";
import { evaluerGarde } from "@/roles/garde";

/** Garde du groupe `(seller)` — voir app/(employee)/_layout.tsx pour le commentaire complet. */
export default function LayoutSeller() {
  const session = useSessionAppareil();
  const personne = usePersonneAppairee();
  const verdict = evaluerGarde(session, "seller");
  if (!verdict.autorise) {
    return <Redirect href={verdict.redirectionVers} />;
  }
  return <Stack key={JSON.stringify([personne, session.presente ? session.role : null])} screenOptions={{ headerShown: false }} />;
}
