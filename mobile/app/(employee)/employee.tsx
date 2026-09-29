import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { BandeauIdentite } from "@/identite/BandeauIdentite";

/**
 * Écran d'accueil minimal du groupe employé (PLAN T1.4-a item 2) — aucun écran métier ici :
 * la cédule du jour, le punch et le reste arrivent à l'étape 2 de R12 §5.
 */
export default function AccueilEmployee() {
  const { t } = useTranslation();
  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("groupes.employee.accueil")}</Text>
      <BandeauIdentite />
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  titre: { fontSize: 20, fontWeight: "600" },
});
