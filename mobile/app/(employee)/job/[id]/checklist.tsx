import { useCallback, useEffect, useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import * as Crypto from "expo-crypto";
import { useTranslation } from "react-i18next";

import { chargerChecklist, sauvegarderChecklist } from "@/checklist/service";
import { ajouterItem, basculerItem, checklistTerminee, retirerItem } from "@/checklist/logique";
import type { ItemChecklist } from "@/checklist/types";

/**
 * `checklist.tsx` (R12 §5 étape 4, PLAN T1.4-e). AUCUN catalogue d'items n'existe côté serveur —
 * voir `src/checklist/types.ts` pour la décision documentée : l'employé compose sa propre liste
 * pour CE chantier, persistée localement (`expo-sqlite`, `src/checklist/service.ts`).
 * `checklist_complete` (préparé pour T1.4-f par `src/m4/preuvesCompletion.ts`) dérive de
 * `checklistTerminee(items)` : liste non vide ET tous les items cochés.
 *
 * Écran non testé en rendu (même limite que les autres écrans de cette tranche) :
 * `src/checklist/logique.ts`/`cache.ts` portent la logique, testée là.
 */
export default function EcranChecklist() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const interventionId = typeof id === "string" ? id : "";

  const [items, setItems] = useState<ItemChecklist[]>([]);
  const [texte, setTexte] = useState("");
  const [charge, setCharge] = useState(false);

  useEffect(() => {
    let annule = false;
    void (async () => {
      if (!interventionId) {
        return;
      }
      const chargee = await chargerChecklist(interventionId);
      if (!annule) {
        setItems(chargee);
        setCharge(true);
      }
    })();
    return () => {
      annule = true;
    };
  }, [interventionId]);

  const sauvegarder = useCallback(
    async (prochains: ItemChecklist[]) => {
      setItems(prochains);
      if (interventionId) {
        await sauvegarderChecklist(interventionId, prochains);
      }
    },
    [interventionId],
  );

  const surAjout = useCallback(() => {
    const prochains = ajouterItem(items, Crypto.randomUUID(), texte);
    setTexte("");
    void sauvegarder(prochains);
  }, [items, texte, sauvegarder]);

  const terminee = checklistTerminee(items);

  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("checklist.titre")}</Text>

      <View style={styles.ajout}>
        <TextInput
          style={styles.champ}
          placeholder={t("checklist.champNouvelItem")}
          value={texte}
          onChangeText={setTexte}
          accessibilityLabel={t("checklist.champNouvelItem")}
        />
        <Pressable style={styles.boutonAjouter} onPress={surAjout}>
          <Text style={styles.boutonAjouterTexte}>{t("checklist.ajouter")}</Text>
        </Pressable>
      </View>

      {charge && items.length === 0 ? <Text style={styles.vide}>{t("checklist.vide")}</Text> : null}

      <FlatList
        data={items}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <View style={styles.ligne}>
            <Pressable style={styles.case} onPress={() => void sauvegarder(basculerItem(items, item.id))}>
              <Text style={styles.caseTexte}>{item.fait ? "☑" : "☐"}</Text>
            </Pressable>
            <Text style={[styles.ligneTexte, item.fait ? styles.ligneTexteFaite : null]}>{item.texte}</Text>
            <Pressable onPress={() => void sauvegarder(retirerItem(items, item.id))}>
              <Text style={styles.retirer}>{t("checklist.retirer")}</Text>
            </Pressable>
          </View>
        )}
      />

      <Text style={terminee ? styles.etatTerminee : styles.etatNonTerminee}>
        {terminee ? t("checklist.etat.terminee") : t("checklist.etat.nonTerminee")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, padding: 16, gap: 10 },
  titre: { fontSize: 20, fontWeight: "600" },
  ajout: { flexDirection: "row", gap: 8 },
  champ: { flex: 1, borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 10 },
  boutonAjouter: { backgroundColor: "#1c6f5c", paddingHorizontal: 16, justifyContent: "center", borderRadius: 6 },
  boutonAjouterTexte: { color: "#fff", fontWeight: "600" },
  vide: { color: "#666" },
  ligne: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: "#eee" },
  case: { padding: 4 },
  caseTexte: { fontSize: 18 },
  ligneTexte: { flex: 1 },
  ligneTexteFaite: { textDecorationLine: "line-through", color: "#888" },
  retirer: { color: "#b00020" },
  etatTerminee: { color: "#1c6f5c", fontWeight: "600", marginTop: 8 },
  etatNonTerminee: { color: "#666", marginTop: 8 },
});
