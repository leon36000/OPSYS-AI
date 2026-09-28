import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useTranslation } from "react-i18next";
import SignatureView from "react-native-signature-canvas";
import type { SignatureViewRef } from "react-native-signature-canvas";

import { enregistrerSignatureCapturee } from "@/signature/service";

/**
 * `signature.tsx` (R12 §5 étape 4, PLAN T1.4-e) : capture locale de la signature du client,
 * MÊME PRINCIPE que les photos (R12 §4) — jamais de binaire inline dans une mutation. Le rendu
 * (`react-native-signature-canvas`, WebView) livre une DataURL via `onOK`, décodée et écrite sur
 * disque par `src/signature/service.ts::enregistrerSignatureCapturee` (fichier local + SHA-256,
 * mutation `signature_capture` délibérément `brouillon` — aucune route serveur d'envoi du
 * binaire, même gap documenté que les photos, voir MOBILE.md).
 *
 * Mission (item 4) : cette brique (WebView) n'étant pas testable sous Jest, sa logique est isolée
 * en fonctions PURES ailleurs (`src/signature/dataUrl.ts`, `mutation.ts`) — ce fichier ne fait
 * QUE le câblage React, non testé en rendu (même limite que les autres écrans de cette tranche).
 */
export default function EcranSignature() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const interventionId = typeof id === "string" ? id : "";
  const signatureRef = useRef<SignatureViewRef>(null);

  const [enregistrement, setEnregistrement] = useState(false);
  const [enregistree, setEnregistree] = useState(false);
  const [vide, setVide] = useState(false);

  const surSignatureConfirmee = useCallback(
    async (dataUrl: string) => {
      if (!interventionId) {
        return;
      }
      setEnregistrement(true);
      setVide(false);
      try {
        await enregistrerSignatureCapturee(dataUrl, interventionId);
        setEnregistree(true);
      } finally {
        setEnregistrement(false);
      }
    },
    [interventionId],
  );

  const surSignatureVide = useCallback(() => {
    setVide(true);
    setEnregistree(false);
  }, []);

  const surEffacement = useCallback(() => {
    setEnregistree(false);
    setVide(false);
  }, []);

  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("signature.titre")}</Text>

      <View style={styles.zone}>
        <SignatureView
          ref={signatureRef}
          onOK={(dataUrl) => void surSignatureConfirmee(dataUrl)}
          onEmpty={surSignatureVide}
          onClear={surEffacement}
          confirmText={t("signature.confirmer")}
          clearText={t("signature.effacer")}
          descriptionText=""
          style={styles.canevas}
        />
      </View>

      {enregistrement ? <ActivityIndicator /> : null}
      {vide ? <Text style={styles.erreur}>{t("signature.vide")}</Text> : null}
      {enregistree ? <Text style={styles.succes}>{t("signature.enregistree")}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, padding: 16, gap: 10 },
  titre: { fontSize: 20, fontWeight: "600" },
  zone: { flex: 1, minHeight: 320, borderWidth: 1, borderColor: "#ccc", borderRadius: 8, overflow: "hidden" },
  canevas: { flex: 1 },
  erreur: { color: "#b00020" },
  succes: { color: "#1c6f5c", fontWeight: "600" },
});
