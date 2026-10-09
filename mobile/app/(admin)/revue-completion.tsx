import { useCallback, useRef, useState } from "react";
import { ScrollView } from "react-native";
import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";
import { RevueCompletionSourcesM4 } from "@/admin/RevueCompletionSourcesM4";
import { capturerSessionAdminLecture } from "@/protocole/configuration";
import { construireArgumentsDossierRevueCompletion } from "@/m4/revueCompletionSources";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { stylesAdmin } from "@/admin/composants";

/** Les paramètres choisissent une lecture ; aucune autorité owner ni action ne vient d'une URL. */
export default function EcranRevueCompletionSources() {
  const params = useLocalSearchParams<{ intervention?: string; demande?: string }>();
  const focused = useRef(false), epoch = useRef(0), [active, setActive] = useState(false);
  useFocusEffect(useCallback(() => {
    ++epoch.current; focused.current = true; setActive(true);
    return () => { ++epoch.current; focused.current = false; setActive(false); };
  }, []));
  let intervention: string | null = null, demande: string | null = null;
  try { const a = construireArgumentsDossierRevueCompletion(params.intervention, params.demande ?? null);
    intervention = a.intervention_id; demande = a.demande_id; } catch { /* Paramètres invalides : aucune lecture ou mutation. */ }
  const capture = capturerSessionAdminLecture(), n = epoch.current;
  const connected = useNetInfo().isConnected === true;
  return <ScrollView contentContainerStyle={stylesAdmin.conteneur}>
    <BandeauIdentite />
    <RevueCompletionSourcesM4 interventionId={intervention} demandeId={demande} connected={connected && active}
      autorisee={() => focused.current && n === epoch.current && capture.session !== null && capture.courante()} />
  </ScrollView>;
}
