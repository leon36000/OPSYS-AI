import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { Redirect, useRouter } from "expo-router";
import { useTranslation } from "react-i18next";

import { useCycleIdentite } from "@/identite/hooks";
import { obtenirConfigurationAppel } from "@/protocole/configuration";
import { useEtatIdentite } from "@/roles/contexte";

/**
 * Écran d'erreur d'identité (PLAN T1.4-c5) : l'appareil est apparié, mais le serveur ne lui donne pas de
 * personne ni de rôle nommé (jamais attribué, révoqué, rôle inconnu), ou ne peut pas être joint et
 * aucune confirmation n'est gardée. Aucun profil n'est ouvert : ni « employé » par défaut, ni le rôle de
 * transport du jeton. La personne peut réessayer (le propriétaire a peut-être attribué l'appareil entre-
 * temps) ou appairer de nouveau. Non testé en rendu (même limite que les autres écrans) : la logique est
 * dans `src/identite/`.
 */
export default function EcranIdentite() {
  const { t } = useTranslation();
  const router = useRouter();
  const etat = useEtatIdentite();
  const { restaurer } = useCycleIdentite();
  const [enCours, setEnCours] = useState(false);

  const surReessayer = useCallback(async () => {
    setEnCours(true);
    try {
      await restaurer();
    } finally {
      setEnCours(false);
    }
  }, [restaurer]);

  if (etat.genre === "confirmee" || etat.genre === "a_reconfirmer") {
    return <Redirect href="/" />;
  }
  if (etat.genre === "non_appairee") {
    return <Redirect href="/pairing" />;
  }
  if (etat.genre !== "erreur") {
    return (
      <View style={styles.conteneur}>
        <ActivityIndicator />
        <Text style={styles.message}>{t("identite.chargement")}</Text>
      </View>
    );
  }

  const appareilId = obtenirConfigurationAppel()?.appareilId ?? null;
  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("identite.erreur.titre")}</Text>
      <Text style={styles.message}>{t(`identite.erreur.motifs.${etat.motif}`)}</Text>
      <Text style={styles.message}>{t("identite.erreur.envoisConserves")}</Text>
      {appareilId ? <Text selectable style={styles.appareil}>{t("identite.erreur.appareil", { appareilId })}</Text> : null}

      <Pressable
        style={({ pressed }) => [styles.bouton, pressed || enCours ? styles.boutonDesactive : null]}
        disabled={enCours}
        onPress={() => void surReessayer()}
      >
        <Text style={styles.boutonTexte}>{enCours ? t("identite.erreur.reessayerEnCours") : t("identite.erreur.reessayer")}</Text>
      </Pressable>
      <Pressable style={styles.boutonSecondaire} disabled={enCours} onPress={() => router.push("/pairing")}>
        <Text style={styles.boutonSecondaireTexte}>{t("identite.erreur.reappairer")}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, justifyContent: "center", gap: 16, padding: 24 },
  titre: { fontSize: 20, fontWeight: "600", textAlign: "center" },
  message: { fontSize: 15, textAlign: "center", opacity: 0.85 },
  appareil: { fontSize: 12, textAlign: "center", color: "#444" },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 12, borderRadius: 6, alignItems: "center" },
  boutonDesactive: { opacity: 0.5 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  boutonSecondaire: { paddingVertical: 12, borderRadius: 6, alignItems: "center", borderWidth: 1, borderColor: "#1c6f5c" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
});
