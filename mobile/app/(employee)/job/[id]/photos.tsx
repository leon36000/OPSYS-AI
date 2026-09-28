import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, FlatList, Image, Pressable, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useTranslation } from "react-i18next";

import { choisirTaillePhoto } from "@/photos/taille";
import { enregistrerPhotoCapturee, listerPhotosCapturees } from "@/photos/service";
import { NATURES_PHOTO } from "@/photos/types";
import type { NaturePhoto } from "@/photos/types";
import type { MutationOutbox } from "@/outbox/types";

/**
 * `photos.tsx` (R12 §5 étape 4, PLAN T1.4-e) : photos avant/pendant/après (DEFINITION-PRODUIT.md
 * §9.2/§9.3), capture bridée ≈1600 px de long côté / JPEG ~0,8 (R12 §4 — voir
 * `src/photos/taille.ts` pour la limite exacte de `expo-camera` sur ce bridage). Fichier local +
 * SHA-256 : `src/photos/service.ts::enregistrerPhotoCapturee` copie le fichier temporaire de la
 * caméra vers le stockage géré par l'app, le hache, et persiste une mutation `photo_upload`
 * délibérément `brouillon` (AUCUNE route serveur d'envoi du binaire, voir `src/photos/mutation.ts`
 * et MOBILE.md — gap documenté, jamais inventé).
 *
 * Écran non testé en rendu (même limite que les autres écrans de cette tranche, `CameraView`
 * dépend en plus du natif) : `src/photos/taille.ts`/`mutation.ts`/`src/fichiers/empreinte.ts`
 * portent la logique, testée là.
 */
export default function EcranPhotos() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const interventionId = typeof id === "string" ? id : "";

  const [nature, setNature] = useState<NaturePhoto>("avant");
  const [photos, setPhotos] = useState<MutationOutbox[]>([]);
  const [permission, demanderPermission] = useCameraPermissions();
  const [cameraOuverte, setCameraOuverte] = useState(false);
  const [taillePhoto, setTaillePhoto] = useState<string | undefined>(undefined);
  const [enregistrement, setEnregistrement] = useState(false);
  const cameraRef = useRef<CameraView | null>(null);

  const rafraichir = useCallback(async () => {
    if (!interventionId) {
      return;
    }
    setPhotos(await listerPhotosCapturees(interventionId));
  }, [interventionId]);

  useEffect(() => {
    void rafraichir();
  }, [rafraichir]);

  const photosDeCetteNature = photos.filter((photo) => photo.payload.nature === nature);

  const surOuvrirCamera = useCallback(async () => {
    if (!permission?.granted) {
      const reponse = await demanderPermission();
      if (!reponse.granted) {
        return;
      }
    }
    setCameraOuverte(true);
  }, [permission, demanderPermission]);

  const surCameraPrete = useCallback(async () => {
    const tailles = await cameraRef.current?.getAvailablePictureSizesAsync();
    if (tailles) {
      setTaillePhoto(choisirTaillePhoto(tailles) ?? undefined);
    }
  }, []);

  const surCapture = useCallback(async () => {
    if (!cameraRef.current || !interventionId) {
      return;
    }
    setEnregistrement(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.8, imageType: "jpg" });
      await enregistrerPhotoCapturee({
        uriTemporaire: photo.uri,
        largeur: photo.width,
        hauteur: photo.height,
        nature,
        chantierId: interventionId,
      });
      setCameraOuverte(false);
      await rafraichir();
    } finally {
      setEnregistrement(false);
    }
  }, [interventionId, nature, rafraichir]);

  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("photos.titre")}</Text>

      <View style={styles.onglets}>
        {NATURES_PHOTO.map((valeur) => (
          <Pressable
            key={valeur}
            style={[styles.onglet, nature === valeur ? styles.ongletActif : null]}
            onPress={() => setNature(valeur)}
          >
            <Text style={nature === valeur ? styles.ongletTexteActif : styles.ongletTexte}>
              {t(`photos.natures.${valeur}`)}
            </Text>
          </Pressable>
        ))}
      </View>

      {cameraOuverte ? (
        <View style={styles.camera}>
          <CameraView
            ref={cameraRef}
            style={StyleSheet.absoluteFill}
            facing="back"
            pictureSize={taillePhoto}
            onCameraReady={() => void surCameraPrete()}
          />
          <Pressable style={styles.obturateur} disabled={enregistrement} onPress={() => void surCapture()}>
            {enregistrement ? <ActivityIndicator color="#fff" /> : <Text style={styles.obturateurTexte}>{t("photos.capturer")}</Text>}
          </Pressable>
        </View>
      ) : (
        <Pressable style={styles.boutonCapturer} onPress={() => void surOuvrirCamera()}>
          <Text style={styles.boutonCapturerTexte}>{t("photos.capturer")}</Text>
        </Pressable>
      )}
      {permission && !permission.granted && !permission.canAskAgain ? (
        <Text style={styles.erreur}>{t("photos.permissionRefusee")}</Text>
      ) : null}

      {photosDeCetteNature.length === 0 ? <Text style={styles.vide}>{t("photos.aucunePhoto")}</Text> : null}

      <FlatList
        horizontal
        data={photosDeCetteNature}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <Image
            source={{ uri: typeof item.payload.uri === "string" ? item.payload.uri : undefined }}
            style={styles.vignette}
          />
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, padding: 16, gap: 10 },
  titre: { fontSize: 20, fontWeight: "600" },
  onglets: { flexDirection: "row", gap: 8 },
  onglet: { paddingVertical: 8, paddingHorizontal: 14, borderRadius: 6, borderWidth: 1, borderColor: "#999" },
  ongletActif: { backgroundColor: "#1c6f5c", borderColor: "#1c6f5c" },
  ongletTexte: { color: "#333" },
  ongletTexteActif: { color: "#fff", fontWeight: "600" },
  camera: { height: 320, borderRadius: 8, overflow: "hidden", justifyContent: "flex-end", alignItems: "center" },
  obturateur: { backgroundColor: "#1c6f5c", paddingVertical: 12, paddingHorizontal: 24, borderRadius: 6, marginBottom: 16 },
  obturateurTexte: { color: "#fff", fontWeight: "600" },
  boutonCapturer: { backgroundColor: "#1c6f5c", paddingVertical: 12, borderRadius: 6, alignItems: "center" },
  boutonCapturerTexte: { color: "#fff", fontWeight: "600" },
  erreur: { color: "#b00020" },
  vide: { color: "#666" },
  vignette: { width: 96, height: 96, borderRadius: 6, marginRight: 8, backgroundColor: "#eee" },
});
