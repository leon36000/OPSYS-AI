import { useCallback, useRef, useState } from "react";
import { ScrollView, Text } from "react-native";
import { useFocusEffect } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";
import { useTranslation } from "react-i18next";
import { ObligationsPrepareesM5 } from "@/admin/ObligationsPrepareesM5";
import { stylesAdmin as styles } from "@/admin/composants";
import { capturerSessionAdminLecture } from "@/protocole/configuration";
import { useSessionAppareil } from "@/roles/contexte";
import { BandeauIdentite } from "@/identite/BandeauIdentite";

export default function ObligationsAdmin() {
  const { t } = useTranslation(), session = useSessionAppareil(), connected = useNetInfo().isConnected === true;
  const [focused, setFocused] = useState(false), generation = useRef(0), garde = useRef<(() => boolean) | null>(null);
  useFocusEffect(useCallback(() => {
    const c = capturerSessionAdminLecture(), n = ++generation.current;
    garde.current = c.session ? () => n === generation.current && c.courante() : null;
    setFocused(c.session !== null && c.courante());
    return () => { ++generation.current; garde.current = null; setFocused(false); };
  }, [session]));
  const autorisee = () => focused && garde.current?.() === true;
  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("admin.obligationsM5.titre")}</Text><BandeauIdentite />
    {autorisee() ? <ObligationsPrepareesM5 connected={connected} autorisee={autorisee} /> : <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text>}
  </ScrollView>;
}
