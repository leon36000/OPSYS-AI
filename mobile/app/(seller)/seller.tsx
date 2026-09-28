import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

/** Écran d'accueil minimal du groupe vendeur (PLAN T1.4-a item 2) — aucun écran métier ici. */
export default function AccueilSeller() {
  const { t } = useTranslation();
  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("groupes.seller.accueil")}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, alignItems: "center", justifyContent: "center" },
  titre: { fontSize: 20, fontWeight: "600" },
});
