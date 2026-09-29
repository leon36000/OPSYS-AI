import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { identiteDepuisEtat } from "./etat";
import { useQuarantaine } from "../outbox/hooks";
import { useEtatIdentite } from "../roles/contexte";

/**
 * Montre QUI est cette personne pour le serveur (nom de l'identifiant OPSYS et rôle nommé), avec la
 * mention « à reconfirmer » quand l'identité vient de la dernière confirmation gardée hors ligne. Ne rend
 * rien sans identité : un écran de profil n'affiche jamais une personne devinée.
 *
 * Montre aussi la QUARANTAINE de la file sortante (PLAN T1.4-l) : les envois en attente qui appartiennent à
 * une autre personne (l'appareil a été appairé pour quelqu'un d'autre depuis) — conservés, jamais envoyés
 * sous cette identité, jamais supprimés en silence.
 */
export function BandeauIdentite() {
  const { t } = useTranslation();
  const etat = useEtatIdentite();
  const identite = identiteDepuisEtat(etat);
  const quarantaine = useQuarantaine();
  if (!identite) {
    return null;
  }
  return (
    <View style={styles.conteneur} accessibilityRole="header">
      <Text style={styles.identite}>
        {t("identite.bandeau.connecte", { personne: identite.personne, role: t(`identite.roles.${identite.role}`) })}
      </Text>
      {etat.genre === "a_reconfirmer" ? <Text style={styles.avis}>{t("identite.bandeau.aReconfirmer")}</Text> : null}
      {quarantaine ? (
        <Text style={styles.avis}>{t("identite.bandeau.quarantaine", { nombre: quarantaine.nombre })}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { gap: 2 },
  identite: { fontSize: 14, color: "#1c6f5c", fontWeight: "600" },
  avis: { fontSize: 13, color: "#8a5a00" },
});
