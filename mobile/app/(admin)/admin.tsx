import { Link } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

/** Accueil du groupe admin (PLAN T1.4-a item 2), avec le lien vers l'écran des approbations du
 * propriétaire (PLAN T1.4-f étape 6, `approvals.tsx`) — le seul écran métier du groupe pour l'instant. */
export default function AccueilAdmin() {
  const { t } = useTranslation();
  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("groupes.admin.accueil")}</Text>
      <Link href="/approvals" style={styles.lien}>
        {t("approvals.lienDepuisAccueil")}
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16 },
  titre: { fontSize: 20, fontWeight: "600" },
  lien: { color: "#1c6f5c", fontWeight: "600", fontSize: 16 },
});
