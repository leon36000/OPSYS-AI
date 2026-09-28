import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import { useTranslation } from "react-i18next";

import { appairerAppareil } from "@/appairage/client";
import { resoudreInfoClientAppairage } from "@/appairage/clientInfo";
import { chargerOuCreerIdentite, sauvegarderSession } from "@/appairage/stockage";
import type { EtatAppairage, MotifEchecAppairage, SocketAppairageLike } from "@/appairage/types";
import { definirConfigurationAppel } from "@/protocole/configuration";
import { useDefinirSessionAppareil } from "@/roles/contexte";

/**
 * Écran d'appairage RÉEL (PLAN T1.4-c3). Saisie du CODE seulement (pas de lecture QR : voir
 * `docs/architecture/MOBILE.md` § Appairage — `expo-camera` alourdirait cette tranche pour un
 * gain marginal tant que le code peut être copié/collé). Le protocole lui-même
 * (`src/appairage/client.ts`) gère la signature, l'attente de l'approbation du propriétaire et
 * le recul entre tentatives ; cet écran ne fait que le câblage React (état affiché, stockage,
 * session), non couvert par des tests automatisés faute de `@testing-library/react-native` dans
 * la pile installée — même limite assumée que `app/(employee)/punch.tsx` (voir MOBILE.md). La
 * logique sous-jacente, elle, est intégralement testée (`src/appairage/*.test.ts`).
 */
export default function EcranAppairage() {
  const { t } = useTranslation();
  const router = useRouter();
  const definirSession = useDefinirSessionAppareil();

  const [code, setCode] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [phase, setPhase] = useState<EtatAppairage | null>(null);
  const [motifEchec, setMotifEchec] = useState<MotifEchecAppairage | null>(null);
  const [messageEchec, setMessageEchec] = useState<string | null>(null);

  const surAppairer = useCallback(async () => {
    const saisie = code.trim();
    if (!saisie || enCours) {
      return;
    }
    setEnCours(true);
    setMotifEchec(null);
    setMessageEchec(null);
    setPhase(null);
    try {
      const identite = await chargerOuCreerIdentite();
      const resultat = await appairerAppareil({
        code: saisie,
        identite,
        clientInfo: resoudreInfoClientAppairage(Constants.expoConfig?.version ?? "0.0.0"),
        // `WebSocket` global RN (jamais le paquet npm `ws`) — même esprit que
        // `@openclaw/gateway-client/browser`, R12 §1.2 : « l'hôte fournit son propre WebSocket ».
        creerSocket: (url) => new WebSocket(url) as unknown as SocketAppairageLike,
        genererId: () => Crypto.randomUUID(),
        onEtat: setPhase,
      });

      if (!resultat.ok) {
        setMotifEchec(resultat.motif);
        setMessageEchec(resultat.message);
        return;
      }

      await sauvegarderSession({
        urlBase: resultat.urlBase,
        jeton: resultat.jeton,
        role: resultat.role,
        appareilId: resultat.appareilId,
      });
      definirConfigurationAppel({
        urlBase: resultat.urlBase,
        jeton: resultat.jeton,
        appareilId: resultat.appareilId,
      });
      // Rôle reçu du serveur -> garde de routes existante (`src/roles/garde.ts`). Un rôle
      // encore inconnu (générique "operator" tant que T1.4-c2 n'a pas livré les rôles nommés
      // admin/employee/seller — voir MOBILE.md) reste ici fail-closed : `evaluerGarde` refuse
      // tout groupe et redirige vers /pairing, exactement comme un jeton absent.
      definirSession({ presente: true, role: resultat.role });
      router.replace("/");
    } finally {
      setEnCours(false);
    }
  }, [code, enCours, definirSession, router]);

  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("pairing.titre")}</Text>
      <Text style={styles.explication}>{t("pairing.explication")}</Text>

      <TextInput
        style={styles.champ}
        placeholder={t("pairing.champCode.indice")}
        value={code}
        onChangeText={setCode}
        editable={!enCours}
        autoCapitalize="none"
        autoCorrect={false}
        accessibilityLabel={t("pairing.champCode.etiquette")}
      />

      <Pressable
        style={({ pressed }) => [styles.bouton, (pressed || enCours || !code.trim()) ? styles.boutonDesactive : null]}
        disabled={enCours || !code.trim()}
        onPress={() => void surAppairer()}
      >
        <Text style={styles.boutonTexte}>{enCours ? t("pairing.boutonEnCours") : t("pairing.bouton")}</Text>
      </Pressable>

      {enCours ? <ActivityIndicator /> : null}
      {phase ? <Text style={styles.etat}>{libellePhase(phase, t)}</Text> : null}
      {motifEchec ? (
        <Text style={styles.erreur}>{messageEchec ?? t(`pairing.erreurs.${motifEchec}`)}</Text>
      ) : null}
    </View>
  );
}

function libellePhase(etat: EtatAppairage, t: (cle: string, options?: Record<string, unknown>) => string): string {
  switch (etat.phase) {
    case "connexion":
      return t("pairing.phases.connexion");
    case "attente_defi":
      return t("pairing.phases.attenteDefi");
    case "signature":
      return t("pairing.phases.signature");
    case "attente_approbation":
      return t("pairing.phases.attenteApprobation", { tentative: etat.tentative });
    case "nouvelle_tentative_reseau":
      return t("pairing.phases.nouvelleTentativeReseau", { tentative: etat.tentative });
    case "reussi":
      return t("pairing.phases.reussi");
    case "echec":
      return "";
  }
}

const styles = StyleSheet.create({
  conteneur: {
    flex: 1,
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
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 10 },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 12, borderRadius: 6, alignItems: "center" },
  boutonDesactive: { opacity: 0.5 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  etat: { textAlign: "center", color: "#444" },
  erreur: { textAlign: "center", color: "#b00020" },
});
