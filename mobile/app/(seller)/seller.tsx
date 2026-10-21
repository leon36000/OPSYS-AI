import { Link } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { BandeauIdentite } from "@/identite/BandeauIdentite";

/** Accueil du groupe vendeur (PLAN T1.4-a item 2), avec les liens vers ses écrans (PLAN T4.8) : la liste de ses leads
 * (`leads.tsx`, et de là la fiche `lead/[id].tsx`) et ses soumissions (`quotes.tsx`). */
export default function AccueilSeller() {
  const { t } = useTranslation();
  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("groupes.seller.accueil")}</Text>
      <BandeauIdentite />
      <Link href="/leads" style={styles.lien}>
        {t("vendeur.accueil.leads")}
      </Link>
      <Link href="/quotes" style={styles.lien}>
        {t("vendeur.accueil.quotes")}
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16 },
  titre: { fontSize: 20, fontWeight: "600" },
  lien: { color: "#1c6f5c", fontWeight: "600", fontSize: 16 },
});
