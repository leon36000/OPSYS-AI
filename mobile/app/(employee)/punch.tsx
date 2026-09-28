import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";

import {
  actionsDisponibles,
  deriverEtatSynchroAffiche,
  extraireHeureMinuteLocale,
  resoudreActionEmploye,
} from "@/ecrans/punch";
import type { ActionEmploye, PhasePointage } from "@/ecrans/punch";
import { obtenirContextePointageProvisoire } from "@/m4/contextePointageProvisoire";
import { construireArgumentsPointer } from "@/m4/pointage";
import { demarrerDeclencheursVidange } from "@/outbox/declencheurs";
import { genererMutationId } from "@/outbox/id";
import { creerMutation, formaterHorodatageLocal, soumettreMutation } from "@/outbox/mutation";
import { declencherVidange, obtenirDepot } from "@/outbox/service";
import type { MutationOutbox } from "@/outbox/types";
import { obtenirConfigurationAppel } from "@/protocole/configuration";

/**
 * `punch.tsx` (M4.4, R12 §5 étape 2) : entrée/sortie/pause, en file AVANT tout réseau. La
 * logique (machine à états locale, formatage de l'heure, état de synchro affiché) vit dans
 * `src/ecrans/punch.ts`, purement testée là — ce fichier ne fait que le câblage React (état,
 * effets, JSX), non couvert par des tests automatisés faute de `@testing-library/react-native`
 * dans la pile installée (voir MOBILE.md).
 *
 * `intervention`/`technicien` sont saisis à la main : aucune session appairée (T1.4-c) ni
 * `today.tsx` (R12 §5 étape 3) pour les connaître à l'avance — voir la docstring de
 * `src/m4/contextePointageProvisoire.ts` pour les autres champs que `m4_pointer` exige et que
 * cette tranche ne peut pas encore fournir avec de vraies données (GPS, fenêtre, référentiel).
 */

const LIBELLES_BOUTON: Record<ActionEmploye, (phase: PhasePointage) => "entree" | "sortie" | "pauseDebut" | "pauseFin"> = {
  entree: () => "entree",
  sortie: () => "sortie",
  pause: (phase) => (phase === "en_pause" ? "pauseFin" : "pauseDebut"),
};

export default function EcranPointage() {
  const { t } = useTranslation();
  const [intervention, setIntervention] = useState("");
  const [technicien, setTechnicien] = useState("");
  const [phase, setPhase] = useState<PhasePointage>("avant_arrivee");
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
    // Déclencheurs prévus par la mission (premier plan, retour réseau) : voir
    // src/outbox/declencheurs.ts. Nettoyage à la sortie de l'écran.
    return demarrerDeclencheursVidange({ aoDeclenchement: () => void rafraichirDerniereMutation() });
  }, [rafraichirDerniereMutation]);

  const surAction = useCallback(
    async (action: ActionEmploye) => {
      const interventionId = intervention.trim();
      const technicienId = technicien.trim();
      if (!interventionId || !technicienId) {
        setErreurValidation(true);
        return;
      }
      const resolue = resoudreActionEmploye(phase, action);
      if (!resolue) {
        return; // fail-closed : ne devrait pas arriver, actionsDisponibles(phase) filtre déjà.
      }
      // Mission T1.4-e item 3 : UN SEUL identifiant d'appareil dans toute l'app — celui de la
      // VRAIE session appairée (`src/appairage/`), jamais un identifiant provisoire par
      // processus. `obtenirConfigurationAppel()` est TOUJOURS non nulle à l'intérieur du groupe
      // `(employee)` (gardé par `evaluerGarde`, qui exige une session posée par le MÊME appel
      // que `definirConfigurationAppel` — `app/pairing/index.tsx`/`app/_layout.tsx`) ; on reste
      // fail-closed plutôt que de le supposer : sans configuration, aucune mutation n'est créée.
      const configuration = obtenirConfigurationAppel();
      if (!configuration) {
        setErreurAppareil(true);
        return;
      }
      setErreurValidation(false);
      setErreurAppareil(false);
      setEnTraitement(true);
      try {
        const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
        const horodatageLocal = formaterHorodatageLocal(horloge);
        const contexte = obtenirContextePointageProvisoire(configuration.appareilId);
        const args = construireArgumentsPointer(interventionId, technicienId, resolue.action, horodatageLocal, contexte);

        const brouillon = creerMutation(
          { type: resolue.typeMutation, chantierId: interventionId, payload: { ...args } },
          genererMutationId,
          horloge,
        );
        const enAttente = soumettreMutation(brouillon);
        const depot = await obtenirDepot();
        const persistee = await depot.inserer(enAttente);

        derniereMutationIdRef.current = persistee.id;
        setDerniereMutation(persistee);
        setDernierVerdict(null);
        setPhase(resolue.phaseSuivante);

        // Tentative immédiate, best-effort : si hors ligne ou pas encore appairé
        // (declencherVidange -> null), la mutation reste en_attente en file, sans risque
        // (R12 §4) — les déclencheurs (ci-dessus) reprendront plus tard.
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
    },
    [intervention, technicien, phase, rafraichirDerniereMutation],
  );

  const champsValides = intervention.trim() !== "" && technicien.trim() !== "";
  const heureMinute = derniereMutation ? extraireHeureMinuteLocale(derniereMutation.createdAtLocal) : null;
  const etatSynchro = derniereMutation
    ? deriverEtatSynchroAffiche(derniereMutation.statut, dernierVerdict)
    : null;

  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("pointage.titre")}</Text>

      <TextInput
        style={styles.champ}
        placeholder={t("pointage.champIntervention")}
        value={intervention}
        onChangeText={setIntervention}
        editable={!enTraitement}
        accessibilityLabel={t("pointage.champIntervention")}
      />
      <TextInput
        style={styles.champ}
        placeholder={t("pointage.champTechnicien")}
        value={technicien}
        onChangeText={setTechnicien}
        editable={!enTraitement}
        accessibilityLabel={t("pointage.champTechnicien")}
      />
      {erreurValidation && !champsValides ? <Text style={styles.erreur}>{t("pointage.champsRequis")}</Text> : null}
      {erreurAppareil ? <Text style={styles.erreur}>{t("pointage.appareilNonAppaire")}</Text> : null}

      <View style={styles.boutons}>
        {actionsDisponibles(phase).map((action) => (
          <Pressable
            key={action}
            style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
            disabled={enTraitement}
            onPress={() => void surAction(action)}
          >
            <Text style={styles.boutonTexte}>{t(`pointage.boutons.${LIBELLES_BOUTON[action](phase)}`)}</Text>
          </Pressable>
        ))}
      </View>

      {enTraitement ? <ActivityIndicator /> : null}

      {derniereMutation && heureMinute ? (
        <View style={styles.resume}>
          <Text style={styles.pointeA}>
            {t("pointage.pointeA", { heures: heureMinute.heures, minutes: heureMinute.minutes })}
          </Text>
          {etatSynchro ? <EtatSynchroTexte etat={etatSynchro} /> : null}
        </View>
      ) : (
        <Text style={styles.aucunPointage}>{t("pointage.aucunPointage")}</Text>
      )}
    </View>
  );
}

function EtatSynchroTexte({ etat }: { etat: ReturnType<typeof deriverEtatSynchroAffiche> }) {
  const { t } = useTranslation();
  switch (etat.genre) {
    case "en_attente":
      return <Text style={styles.etatSynchro}>{t("pointage.etatSynchro.enAttente")}</Text>;
    case "envoi":
      return <Text style={styles.etatSynchro}>{t("pointage.etatSynchro.envoi")}</Text>;
    case "envoyee":
      return <Text style={styles.etatSynchro}>{t("pointage.etatSynchro.envoyee")}</Text>;
    case "echec_permanent":
      return (
        <Text style={[styles.etatSynchro, styles.echec]}>
          {etat.verdict
            ? t("pointage.etatSynchro.echecPermanentAvecVerdict", { code: etat.verdict.code, detail: etat.verdict.detail })
            : t("pointage.etatSynchro.echecPermanent")}
        </Text>
      );
    default:
      return null;
  }
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, padding: 16, gap: 12 },
  titre: { fontSize: 20, fontWeight: "600" },
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 10 },
  erreur: { color: "#b00020" },
  boutons: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6 },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  resume: { marginTop: 8, gap: 4 },
  pointeA: { fontSize: 16 },
  aucunPointage: { color: "#666" },
  etatSynchro: { color: "#444" },
  echec: { color: "#b00020" },
});
