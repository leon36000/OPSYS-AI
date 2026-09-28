import { Redirect } from "expo-router";

import { useSessionAppareil } from "@/roles/contexte";
import { PROFILS } from "@/roles/types";

/**
 * Route racine « / » : simple redirection, pas un écran (PLAN T1.4-a, aucun écran métier).
 * Aucune session dans ce squelette n'est jamais authentifiée (protocole d'appairage = T1.4-c),
 * donc ceci redirige aujourd'hui toujours vers /pairing — le branchement vers le groupe du
 * rôle est déjà écrit pour ne pas avoir à retoucher ce fichier une fois T1.4-c livré.
 */
export default function Index() {
  const session = useSessionAppareil();
  if (session.presente && (PROFILS as readonly string[]).includes(session.role)) {
    return <Redirect href={`/${session.role}`} />;
  }
  return <Redirect href="/pairing" />;
}
