import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { Redirect } from "expo-router";
import { useTranslation } from "react-i18next";

import { useEtatIdentite } from "@/roles/contexte";

/**
 * Route racine « / » : le SEUL aiguilleur de l'app (PLAN T1.4-a ; identité : PLAN T1.4-c5). Toute garde de
 * groupe qui refuse renvoie ici, et cet écran choisit d'après ce que l'app sait :
 *  - restauration ou première lecture de l'identité en cours : attente, aucune redirection prématurée ;
 *  - pas d'appairage : `/pairing` ;
 *  - identité du serveur (confirmée, ou gardée et à reconfirmer) : le groupe du rôle NOMMÉ ;
 *  - identité refusée ou introuvable : `/identite`, jamais un profil par défaut.
 * Le groupe visé est toujours revérifié par `evaluerGarde` dans son propre `_layout.tsx`.
 */
export default function Index() {
  const { t } = useTranslation();
  const etat = useEtatIdentite();
  switch (etat.genre) {
    case "restauration":
    case "en_lecture":
      return (
        <View style={styles.attente}>
          <ActivityIndicator />
          <Text style={styles.message}>{t("identite.chargement")}</Text>
        </View>
      );
    case "non_appairee":
      return <Redirect href="/pairing" />;
    case "confirmee":
    case "a_reconfirmer":
      return <Redirect href={`/${etat.identite.role}`} />;
    case "erreur":
      return <Redirect href="/identite" />;
  }
}

const styles = StyleSheet.create({
  attente: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12 },
  message: { fontSize: 15, opacity: 0.8 },
});
