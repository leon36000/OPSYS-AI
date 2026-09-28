import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

/**
 * Écran d'appairage (PLAN T1.4-a item 2). Explique l'appairage et affiche l'état actuel —
 * TOUJOURS « non apparié » dans ce squelette, puisque le protocole d'appairage lui-même
 * (QR / code, échange du jeton d'appareil — R12 §1.3) est PLAN T1.4-c. Aucun bouton, aucun
 * scan, aucune simulation de succès ici : on n'invente aucun comportement qui n'existe pas
 * encore.
 */
export default function EcranAppairage() {
  const { t } = useTranslation();
  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("pairing.titre")}</Text>
      <Text style={styles.explication}>{t("pairing.explication")}</Text>
      <Text style={styles.etat}>{t("pairing.etatNonApparie")}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 16,
    padding: 24,
  },
  titre: {
    fontSize: 20,
    fontWeight: "600",
    textAlign: "center",
  },
  explication: {
    fontSize: 15,
    textAlign: "center",
    opacity: 0.8,
  },
  etat: {
    fontSize: 14,
    fontWeight: "500",
  },
});
