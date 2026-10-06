import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";

import { controleMarketing } from "@/m7/service";
import type { LigneContenuM7 } from "@/m7/contrat";
import { usePersonneAppairee } from "@/roles/contexte";

export default function MarketingAdmin() {
  const personne = usePersonneAppairee();
  const net = useNetInfo();
  const [, render] = useState(0);
  const [motifs, setMotifs] = useState<Record<string, string>>({});
  const connected = net.isConnected === true && net.isInternetReachable !== false;

  const refresh = () => render((value) => value + 1);

  // A connected LAN can reach a locally deployed gateway even when public Internet reachability is unknown.
  // The actual gateway response remains authoritative; transport failures never trigger mutation replay.
  useEffect(() => {
    controleMarketing.actualiserConnectivite(connected);
    refresh();
  }, [connected]);

  useFocusEffect(
    useCallback(() => {
      setMotifs({});
      const loading = controleMarketing.charger();
      refresh();
      void loading.then(refresh);
      return () => {
        setMotifs({});
        controleMarketing.invalider();
        refresh();
      };
    }, [personne, connected]),
  );

  const state = controleMarketing.etat();

  async function decider(item: LigneContenuM7, decision: "approuver" | "rejeter") {
    const pending = controleMarketing.decider(item.contenu_id, decision, motifs[item.contenu_id] ?? "");
    refresh();
    await pending;
    refresh();
  }

  async function actualiser(): Promise<void> {
    const pending = controleMarketing.charger();
    refresh();
    await pending;
    refresh();
  }

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <Text style={styles.title}>Marketing · contenus de chantier</Text>
      <Text style={styles.note}>
        Brouillons reçus du serveur. Statut, consentement et source de marque sont relus à chaque
        chargement; le serveur revérifie les conditions au moment de la décision. Rien n’est publié
        depuis cet écran.
      </Text>

      <Pressable accessibilityRole="button" onPress={() => void actualiser()} style={styles.more}>
        <Text>Actualiser depuis le serveur</Text>
      </Pressable>
      {state.statut === "chargement" || state.statut === "decision_en_cours" ? <Text>Lecture en cours…</Text> : null}
      {state.statut === "hors_ligne" ? <Text>Connexion requise. Aucune liste locale n’est affichée.</Text> : null}
      {state.message ? <Text accessibilityRole="alert" style={styles.error}>{state.message}</Text> : null}
      {state.owner || state.statut !== "pret" ? null : <Text>Lecture seule : le serveur ne confirme pas le propriétaire.</Text>}

      {state.items.map((item) => (
        <View key={item.contenu_id} style={styles.card}>
          <Text style={styles.heading}>
            {item.plateforme} · {statutFr(item.approval_status)} · révision {item.revision}
          </Text>
          <Text>Chantier {item.wct_id} · fraîcheur de marque : {fraicheurFr(item.fraicheur_marque)}</Text>
          <Text style={styles.body}>{item.texte}</Text>
          <Text>
            Consentement indiqué : {item.consentement.recueilli_par}, {item.consentement.recueilli_le} · {item.consentement.version_texte}
          </Text>
          <Text>Origine de marque : {sourceFr(item.marque_source?.source ?? null)}</Text>
          {item.avertissements.length > 0 ? <Text>Avertissements : {item.avertissements.join(" · ")}</Text> : null}

          {controleMarketing.peutDecider(item) ? (
            <View>
              <TextInput
                accessibilityLabel={`Motif de rejet ${item.contenu_id}`}
                value={motifs[item.contenu_id] ?? ""}
                maxLength={500}
                onChangeText={(value) => setMotifs((current) => ({ ...current, [item.contenu_id]: value }))}
                placeholder="Motif du rejet (5 à 500 caractères)"
                style={styles.input}
              />
              <View style={styles.actions}>
                <Pressable accessibilityRole="button" onPress={() => void decider(item, "approuver")} style={styles.button}>
                  <Text style={styles.buttonText}>Approuver</Text>
                </Pressable>
                <Pressable accessibilityRole="button" onPress={() => void decider(item, "rejeter")} style={styles.button}>
                  <Text style={styles.buttonText}>Rejeter</Text>
                </Pressable>
              </View>
            </View>
          ) : null}
        </View>
      ))}

      {state.suivant !== null ? (
        <Pressable accessibilityRole="button" onPress={() => { const pending = controleMarketing.chargerSuite(); refresh(); void pending.then(refresh); }} style={styles.more}>
          <Text>Voir les 8 suivants ({state.reste} restants)</Text>
        </Pressable>
      ) : null}
    </ScrollView>
  );
}

function statutFr(statut: LigneContenuM7["approval_status"]): string {
  return {
    PROPOSE: "À examiner",
    APPROVED: "Approuvé",
    REJECTED: "Rejeté",
    CONSENTEMENT_RETIRE: "Consentement retiré",
  }[statut];
}

function fraicheurFr(fraicheur: LigneContenuM7["fraicheur_marque"]): string {
  return { courante: "courante", perimee: "ancienne", preuve_absente: "non établie" }[fraicheur];
}

function sourceFr(source: string | null): string {
  if (source === "brand_profiles") return "profil de marque";
  if (source === "yaml_legacy") return "configuration antérieure";
  return "non établie";
}

const styles = StyleSheet.create({
  page: { padding: 20, gap: 12 },
  title: { fontSize: 23, fontWeight: "700" },
  note: { color: "#444" },
  error: { color: "#9c1c1c" },
  card: { borderWidth: 1, borderColor: "#bbb", borderRadius: 8, padding: 14, gap: 8 },
  heading: { fontSize: 17, fontWeight: "700" },
  body: { fontSize: 16, lineHeight: 23 },
  input: { borderWidth: 1, borderColor: "#777", padding: 10, borderRadius: 5 },
  actions: { flexDirection: "row", gap: 12, marginTop: 8 },
  button: { padding: 12, backgroundColor: "#173e59", borderRadius: 5 },
  buttonText: { color: "white" },
  more: { padding: 14, alignItems: "center", backgroundColor: "#ddd" },
});
