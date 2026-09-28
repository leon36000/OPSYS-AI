import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";

import { deriverEtatSynchroAffiche } from "@/ecrans/punch";
import { creerMutationConsentementGps } from "@/m4/consentementGps";
import { demarrerDeclencheursVidange } from "@/outbox/declencheurs";
import { genererMutationId } from "@/outbox/id";
import { soumettreMutation } from "@/outbox/mutation";
import { declencherVidange, obtenirDepot } from "@/outbox/service";
import type { MutationOutbox } from "@/outbox/types";
import { obtenirConfigurationAppel } from "@/protocole/configuration";

/**
 * `consent.tsx` (POLITIQUE-geolocalisation.md §4, PLAN T1.4-k) : l'employé retire SON consentement
 * à la géolocalisation, en file AVANT tout réseau (R12 §4). La logique (args exacts, preuve,
 * ordre dans la file, lecture du verdict) vit dans `src/m4/consentementGps.ts`, purement testée
 * là — ce fichier ne fait que le câblage React (état, effets, JSX), non couvert par des tests
 * automatisés faute de `@testing-library/react-native` dans la pile installée (voir MOBILE.md).
 *
 * Seul le RETRAIT est proposé ici : donner son consentement demande le formulaire d'accueil avec
 * l'explication des finalités et la case à cocher (POLITIQUE §4), qu'aucun écran ne présente
 * encore ; le serveur, lui, accepte déjà « donne » pour la propre personne de l'employé.
 *
 * `technicien` est saisi à la main, comme sur `punch.tsx` : l'app ne connaît pas encore la
 * personne appairée. Le serveur, lui, le confronte à l'identité AUTHENTIFIÉE du jeton d'appareil
 * et refuse un identifiant qui n'est pas celui de la personne.
 */
export default function EcranConsentementGps() {
  const { t } = useTranslation();
  const [technicien, setTechnicien] = useState("");
  const [derniereMutation, setDerniereMutation] = useState<MutationOutbox | null>(null);
  const [dernierVerdict, setDernierVerdict] = useState<{ code: string; detail: string } | null>(null);
  const [enTraitement, setEnTraitement] = useState(false);
  const [erreurValidation, setErreurValidation] = useState(false);
  const [erreurAppareil, setErreurAppareil] = useState(false);

  const derniereMutationIdRef = useRef<string | null>(null);

  const rafraichirDerniereMutation = useCallback(async () => {
    const id = derniereMutationIdRef.current;
    if (!id) {
      return;
    }
    const depot = await obtenirDepot();
    const fraiche = await depot.obtenir(id);
    if (fraiche) {
      setDerniereMutation(fraiche);
    }
  }, []);

  useEffect(() => {
    // Déclencheurs de vidange (premier plan, retour réseau) : voir src/outbox/declencheurs.ts.
    return demarrerDeclencheursVidange({ aoDeclenchement: () => void rafraichirDerniereMutation() });
  }, [rafraichirDerniereMutation]);

  const surRetrait = useCallback(async () => {
    const technicienId = technicien.trim();
    if (!technicienId) {
      setErreurValidation(true);
      return;
    }
    // Même règle que punch.tsx : sans session appairée, aucune mutation n'est créée (fail-closed).
    if (!obtenirConfigurationAppel()) {
      setErreurAppareil(true);
      return;
    }
    setErreurValidation(false);
    setErreurAppareil(false);
    setEnTraitement(true);
    try {
      const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
      const brouillon = creerMutationConsentementGps({ technicienId, action: "retire" }, genererMutationId, horloge);
      const depot = await obtenirDepot();
      const persistee = await depot.inserer(soumettreMutation(brouillon));

      derniereMutationIdRef.current = persistee.id;
      setDerniereMutation(persistee);
      setDernierVerdict(null);

      // Tentative immédiate, best-effort : hors ligne, le retrait reste en file (R12 §4) et partira
      // avec les déclencheurs de vidange ci-dessus — jamais perdu.
      const rapport = await declencherVidange();
      if (rapport) {
        const echec = rapport.echecsPermanents.find((e) => e.id === persistee.id);
        if (echec) {
          setDernierVerdict(echec.verdict);
        }
      }
      await rafraichirDerniereMutation();
    } finally {
      setEnTraitement(false);
    }
  }, [technicien, rafraichirDerniereMutation]);

  const etatSynchro = derniereMutation ? deriverEtatSynchroAffiche(derniereMutation.statut, dernierVerdict) : null;

  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("consentementGps.titre")}</Text>
      <Text style={styles.explication}>{t("consentementGps.explication")}</Text>

      <TextInput
        style={styles.champ}
        placeholder={t("consentementGps.champTechnicien")}
        value={technicien}
        onChangeText={setTechnicien}
        editable={!enTraitement}
        autoCapitalize="none"
        autoCorrect={false}
        accessibilityLabel={t("consentementGps.champTechnicien")}
      />
      {erreurValidation && technicien.trim() === "" ? (
        <Text style={styles.erreur}>{t("consentementGps.champRequis")}</Text>
      ) : null}
      {erreurAppareil ? <Text style={styles.erreur}>{t("consentementGps.appareilNonAppaire")}</Text> : null}

      <Pressable
        style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
        disabled={enTraitement}
        onPress={() => void surRetrait()}
      >
        <Text style={styles.boutonTexte}>{t("consentementGps.retirer")}</Text>
      </Pressable>

      {enTraitement ? <ActivityIndicator /> : null}

      {etatSynchro ? <EtatRetraitTexte etat={etatSynchro} /> : <Text style={styles.neutre}>{t("consentementGps.aucunChangement")}</Text>}
    </View>
  );
}

function EtatRetraitTexte({ etat }: { etat: ReturnType<typeof deriverEtatSynchroAffiche> }) {
  const { t } = useTranslation();
  switch (etat.genre) {
    case "en_attente":
      return <Text style={styles.neutre}>{t("consentementGps.etat.enAttente")}</Text>;
    case "envoi":
      return <Text style={styles.neutre}>{t("consentementGps.etat.envoi")}</Text>;
    case "envoyee":
      return <Text style={styles.neutre}>{t("consentementGps.etat.envoye")}</Text>;
    case "echec_permanent":
      return (
        <Text style={styles.erreur}>
          {etat.verdict
            ? t("consentementGps.etat.echecPermanentAvecVerdict", { code: etat.verdict.code, detail: etat.verdict.detail })
            : t("consentementGps.etat.echecPermanent")}
        </Text>
      );
    default:
      return null;
  }
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, padding: 16, gap: 12 },
  titre: { fontSize: 20, fontWeight: "600" },
  explication: { color: "#444" },
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 10 },
  erreur: { color: "#b00020" },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  neutre: { color: "#444" },
});
