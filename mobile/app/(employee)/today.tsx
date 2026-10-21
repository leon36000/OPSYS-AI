import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useTranslation } from "react-i18next";

import { vueChantiers } from "@/ecrans/today";
import type { ResultatChargementChantiers } from "@/today/orchestrateur";
import { chargerChantiersAujourdhui } from "@/today/service";

/**
 * `today.tsx` (M4.7, R12 §5 étape 3, PLAN T1.4-e) : chantiers du jour, lecture SEULE via
 * `m4_lister_interventions` (`src/today/service.ts` -> `src/today/orchestrateur.ts`), cache
 * local lisible hors ligne (`src/today/cache.ts`, `expo-sqlite`). AUCUNE donnée n'est inventée :
 * `m4_lister_interventions` ne renvoie ni date ni technicien assigné — « chantiers du jour » est
 * donc un PROXY assumé (statuts actifs, `src/today/selection.ts`), documenté là et dans
 * MOBILE.md, pas une vraie cédule datée.
 *
 * Ce que l'écran dit d'une lecture (PLAN T1.4-n, `src/ecrans/today.ts`) : la liste gardée est marquée comme telle ; une
 * liste que le socle a coupée est dite INCOMPLÈTE ; un refus du serveur (jeton révoqué, personne désactivée, rôle
 * retiré) est dit, sans jamais montrer la liste gardée ; « aucun chantier » n'est dit que si une lecture le dit.
 *
 * Écran non testé en rendu (`@testing-library/react-native` absent de la pile, même limite que
 * `punch.tsx`/l'écran d'appairage) : toute la logique sous-jacente (sélection, cache, décision
 * serveur/cache) est testée ailleurs (`src/today/*.test.ts`).
 */
export default function EcranChantiersAujourdhui() {
  const { t } = useTranslation();
  const router = useRouter();
  const [resultat, setResultat] = useState<ResultatChargementChantiers | null>(null);
  const [chargement, setChargement] = useState(false);
  const [premierChargementFait, setPremierChargementFait] = useState(false);

  const charger = useCallback(async () => {
    setChargement(true);
    try {
      const prochainResultat = await chargerChantiersAujourdhui();
      setResultat(prochainResultat);
    } finally {
      setChargement(false);
      setPremierChargementFait(true);
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  const vue = vueChantiers(resultat, premierChargementFait);

  return (
    <View style={styles.conteneur}>
      <View style={styles.entete}>
        <Text style={styles.titre}>{t("today.titre")}</Text>
        <Pressable onPress={() => void charger()} disabled={chargement}>
          <Text style={styles.rafraichir}>{t("today.rafraichir")}</Text>
        </Pressable>
      </View>

      {vue.avis?.genre === "cache" ? (
        <Text style={styles.avis}>{t("today.source.cache", { heure: formaterHeureAffichage(vue.avis.misAJourLe) })}</Text>
      ) : null}
      {vue.avis?.genre === "aucune" ? <Text style={styles.avis}>{t("today.source.aucune")}</Text> : null}
      {vue.avis?.genre === "refus" ? (
        <Text style={styles.erreur}>
          {t("today.source.refus", { code: vue.avis.verdict.code, detail: vue.avis.verdict.detail })}
        </Text>
      ) : null}
      {vue.avis?.genre === "incomplet" ? (
        <Text style={styles.erreur}>
          {t("today.source.incomplet", { statuts: vue.avis.statuts.map((statut) => t(`today.statut.${statut}`)).join(", ") })}
        </Text>
      ) : null}

      {chargement && !premierChargementFait ? <ActivityIndicator /> : null}

      {vue.aucunChantier ? <Text style={styles.vide}>{t("today.aucunChantier")}</Text> : null}

      <FlatList
        data={vue.items}
        keyExtractor={(item) => item.intervention_id}
        renderItem={({ item }) => (
          <Pressable
            style={styles.ligne}
            onPress={() => router.push({ pathname: "/job/[id]", params: { id: item.intervention_id } })}
          >
            <Text style={styles.ligneTitre}>{item.type_travaux ?? item.service}</Text>
            <Text style={styles.ligneStatut}>{t(`today.statut.${item.statut}`)}</Text>
          </Pressable>
        )}
      />
    </View>
  );
}

function formaterHeureAffichage(horodatageIso: string): string {
  const date = new Date(horodatageIso);
  const heures = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${heures}:${minutes}`;
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, padding: 16, gap: 8 },
  entete: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  titre: { fontSize: 20, fontWeight: "600" },
  rafraichir: { color: "#1c6f5c", fontWeight: "600" },
  avis: { color: "#666", fontSize: 13 },
  erreur: { color: "#b00020", fontSize: 13 },
  vide: { color: "#666", marginTop: 16, textAlign: "center" },
  ligne: { paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: "#eee" },
  ligneTitre: { fontSize: 16, fontWeight: "600" },
  ligneStatut: { color: "#444", marginTop: 2 },
});
