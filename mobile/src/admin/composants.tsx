import { useState } from "react";
import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import type { StyleProp, TextStyle } from "react-native";
import { useTranslation } from "react-i18next";

import type { Message, VueSection } from "../ecrans/adminCommun";

/**
 * Les briques d'affichage des trois écrans du profil admin (PLAN T4.20). Aucune décision ici : chaque texte arrive déjà
 * choisi par un modèle de vue (`src/ecrans/*.ts`, testé) sous forme de `Message` (clé i18n et variables) ou de chaîne du
 * serveur ; ces composants ne font que les rendre. Non couvert en rendu (même limite que les autres écrans) : les
 * tests de source (`src/ecrans/ecransAdmin.test.ts`) vérifient que chaque clé qu'ils nomment existe dans les deux langues.
 */

/** Un texte i18n : la clé et les variables viennent d'un modèle de vue. */
export function Ligne({ m, style }: { readonly m: Message; readonly style?: StyleProp<TextStyle> }) {
  const { t } = useTranslation();
  return <Text style={style}>{t(m.cle, m.params as Record<string, string | number> | undefined)}</Text>;
}

export function Lignes({ items, style }: { readonly items: readonly Message[]; readonly style?: StyleProp<TextStyle> }) {
  return (
    <>
      {items.map((item, index) => (
        <Ligne key={`${item.cle}:${index}`} m={item} style={style} />
      ))}
    </>
  );
}

/** Des textes que le serveur a écrits, montrés tels quels, une ligne chacun. */
export function TextesDuServeur({ items, style }: { readonly items: readonly string[]; readonly style?: StyleProp<TextStyle> }) {
  return (
    <>
      {items.map((item, index) => (
        <Text key={`${index}:${item}`} style={style}>
          {item}
        </Text>
      ))}
    </>
  );
}

export function Carte({ children }: { readonly children: ReactNode }) {
  return <View style={styles.carte}>{children}</View>;
}

/** Un morceau de détail que le propriétaire ouvre s'il le veut (l'état d'ouverture est le seul état de l'écran ici). */
export function Depliant({ children }: { readonly children: ReactNode }) {
  const { t } = useTranslation();
  const [ouvert, setOuvert] = useState(false);
  return (
    <View style={styles.depliant}>
      <Pressable onPress={() => setOuvert((precedent) => !precedent)} accessibilityRole="button">
        <Text style={styles.lien}>{ouvert ? t("admin.commun.masquerDetail") : t("admin.commun.voirDetail")}</Text>
      </Pressable>
      {ouvert ? children : null}
    </View>
  );
}

/**
 * Une section d'écran selon ce que le serveur a permis de lire : en chargement (`undefined`), lue (avec, si c'est une
 * copie gardée, le bandeau qui dit la date et la raison), refusée (le verdict du serveur, jamais une copie à sa place) ou
 * impossible à lire (dit, jamais une valeur inventée).
 */
export function EtatSection<C>({
  vue,
  rendre,
}: {
  readonly vue: VueSection<C> | undefined;
  readonly rendre: (contenu: C) => ReactNode;
}) {
  if (vue === undefined) {
    return <ActivityIndicator />;
  }
  if (vue.genre === "refus" || vue.genre === "aucune") {
    return <Ligne m={vue.avis} style={styles.erreur} />;
  }
  return (
    <>
      {vue.horsLigne !== null ? <Ligne m={vue.horsLigne} style={styles.avisCache} /> : null}
      <Ligne m={vue.lue} style={styles.trace} />
      {rendre(vue.contenu)}
    </>
  );
}

export function Bouton({ texte, onPress, desactive }: { readonly texte: string; readonly onPress: () => void; readonly desactive?: boolean }) {
  return (
    <Pressable
      style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
      disabled={desactive}
      onPress={onPress}
      accessibilityRole="button"
    >
      <Text style={styles.boutonTexte}>{texte}</Text>
    </Pressable>
  );
}

export function BoutonSecondaire({
  texte,
  onPress,
  desactive,
}: {
  readonly texte: string;
  readonly onPress: () => void;
  readonly desactive?: boolean;
}) {
  return (
    <Pressable style={styles.boutonSecondaire} disabled={desactive} onPress={onPress} accessibilityRole="button">
      <Text style={styles.boutonSecondaireTexte}>{texte}</Text>
    </Pressable>
  );
}

export const stylesAdmin = StyleSheet.create({
  conteneur: { padding: 16, gap: 12 },
  titre: { fontSize: 20, fontWeight: "600" },
  sousTitre: { fontSize: 16, fontWeight: "600" },
  petitTitre: { fontSize: 14, fontWeight: "600", color: "#333" },
  meta: { color: "#444" },
  trace: { color: "#666", fontSize: 12 },
  vide: { color: "#666" },
  avis: { color: "#7a5b00" },
  erreur: { color: "#b00020" },
  montant: { fontSize: 16, fontWeight: "600" },
  gros: { fontSize: 18, fontWeight: "700" },
  mention: { color: "#7a5b00", fontStyle: "italic", fontSize: 12 },
  citation: { color: "#444", fontStyle: "italic" },
  lien: { color: "#1c6f5c", fontWeight: "600" },
});

const styles = StyleSheet.create({
  carte: { borderWidth: 1, borderColor: "#bbb", borderRadius: 8, padding: 12, gap: 6 },
  depliant: { gap: 6 },
  lien: { color: "#1c6f5c", fontWeight: "600" },
  erreur: { color: "#b00020" },
  avisCache: { color: "#7a5b00" },
  trace: { color: "#666", fontSize: 12 },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  boutonSecondaire: { borderWidth: 1, borderColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
});
