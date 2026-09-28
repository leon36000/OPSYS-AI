import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Link, useLocalSearchParams } from "expo-router";
import { useTranslation } from "react-i18next";

import { checklistTerminee } from "@/checklist/logique";
import { chargerChecklist } from "@/checklist/service";
import type { ItemChecklist } from "@/checklist/types";
import { candidatSignature, candidatsPhotosApres } from "@/fichiers/candidats";
import { envoyerFichiersDuChantier } from "@/fichiers/service";
import { evaluerPreparationCompletion } from "@/ecrans/complete";
import type { RaisonBlocageCompletion } from "@/ecrans/complete";
import { construireArgumentsCompleterIntervention, estAccuseCompletionM4 } from "@/m4/completion";
import type { VerdictServeurCompletion } from "@/m4/completion";
import { ecrireWctIdCompletion, lireWctIdCompletion } from "@/m4/wctIdCompletion";
import { genererMutationId } from "@/outbox/id";
import { creerMutation, formaterHorodatageLocal, soumettreMutation } from "@/outbox/mutation";
import { declencherVidange, obtenirDepot } from "@/outbox/service";
import type { MutationOutbox } from "@/outbox/types";
import { obtenirConfigurationAppel } from "@/protocole/configuration";
import { obtenirDepotLocal } from "@/stockage/service";

/**
 * `complete.tsx` (« Terminer », R12 §5 étape 5, PLAN T1.4-f) : construit `PreuvesCompletionM4`
 * avec les RÉFÉRENCES SERVEUR (`fichier:sha256:<hex>`, jamais les placeholders `mutation_id` de
 * T1.4-e) puis appelle `m4_completer_intervention` par la file sortante — mission item 2.
 *
 * **Dépendance d'ordre obligatoire, structurellement garantie** : `evaluerPreparationCompletion`
 * (`src/ecrans/complete.ts`) est la SEULE porte qui produit `PreuvesCompletionM4` ; elle ne rend
 * jamais `pret: true` tant qu'un fichier attendu n'est pas `complet`
 * (`src/fichiers/etatEnvoi.ts`) — la mutation `job_completion` n'est donc jamais construite avant
 * que ses fichiers ne le soient. Si un dépôt est refusé de façon définitive, l'écran affiche
 * `complete.blocages.fichiers_en_echec` et NE RETENTE JAMAIS automatiquement (reprendre la même
 * photo ne changerait pas l'issue, voir `envoiOrchestrateur.ts`) : l'employé doit retourner à
 * `photos.tsx`/`signature.tsx`.
 *
 * **Le verdict serveur est affiché TEL QUEL** (mission item 2) : `resultatCompletion.statut`
 * porte `completed_pending_review` ou toute autre valeur renvoyée par le serveur, jamais
 * reformulé ni maquillé en « succès » générique.
 *
 * **Envoi des fichiers déclenché ICI** (au montage ET à l'appui sur « Terminer »), pas dans
 * `photos.tsx`/`signature.tsx` (T1.4-e, INCHANGÉS) — décision documentée (MOBILE.md) : garder ces
 * deux écrans déjà livrés intacts plutôt que d'y ajouter un déclenchement d'envoi, pour ne pas
 * risquer une régression sur des écrans déjà en production. Les déclencheurs génériques
 * (`src/outbox/declencheurs.ts`, premier plan/retour réseau) reprennent ensuite ce qui reste en
 * file même si l'employé quitte cet écran avant la fin.
 *
 * **Seul le `wct_id` de l'accusé est mémorisé pour `materials.tsx`** (`src/m4/wctIdCompletion.ts`) :
 * depuis PLAN T1.4-i, `m6_declarer_materiaux_utilises` prend ce `wct_id` et M6 relit lui-même le
 * WCT que M4 a publié — plus de relecture de `m4_lire_outbox` ni de copie du WCT sur l'appareil
 * (voir la docstring de `src/m4/completion.ts`).
 *
 * Écran non testé en rendu (même limite que les autres écrans de cette tranche) :
 * `src/ecrans/complete.ts`, `src/fichiers/*`, `src/m4/completion.ts` portent la logique, testée
 * là.
 */
export default function EcranCompletion() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const interventionId = typeof id === "string" ? id : "";

  const [checklistItems, setChecklistItems] = useState<ItemChecklist[]>([]);
  const [mutations, setMutations] = useState<MutationOutbox[]>([]);
  const [notes, setNotes] = useState("");
  const [signatureRequise, setSignatureRequise] = useState<boolean | null>(null);
  const [charge, setCharge] = useState(false);
  const [enTraitement, setEnTraitement] = useState(false);
  const [erreurAppareil, setErreurAppareil] = useState(false);
  const [blocage, setBlocage] = useState<RaisonBlocageCompletion | null>(null);
  const [dernierVerdict, setDernierVerdict] = useState<VerdictServeurCompletion | null>(null);
  const [resultatCompletion, setResultatCompletion] = useState<{ readonly statut: string } | null>(null);
  const [pretPourMateriaux, setPretPourMateriaux] = useState(false);

  const rafraichirMutations = useCallback(async (): Promise<MutationOutbox[]> => {
    const depot = await obtenirDepot();
    const toutes = await depot.lister();
    setMutations(toutes);
    return toutes;
  }, []);

  useEffect(() => {
    let annule = false;
    void (async () => {
      if (!interventionId) {
        return;
      }
      const items = await chargerChecklist(interventionId);
      await rafraichirMutations();
      // Un `wct_id` déjà mémorisé signifie qu'une complétion a déjà réussi PAR LE PASSÉ (cet
      // écran ou une session précédente) : rend le lien vers `materials.tsx` accessible dès ce
      // montage, sans dépendre de `resultatCompletion` (purement local à CETTE instance de l'écran
      // — voir la note sur `enAttenteConfirmation` plus bas, même limite documentée que `punch.tsx`).
      const wctIdDejaConnu = await lireWctIdCompletion(await obtenirDepotLocal(), interventionId);
      if (annule) {
        return;
      }
      setChecklistItems(items);
      setCharge(true);
      if (wctIdDejaConnu) {
        setPretPourMateriaux(true);
      }
      // Meilleur effort : démarre l'envoi des fichiers dès l'arrivée sur cet écran (photos
      // "après"/signature déjà capturées), sans attendre l'appui sur « Terminer » — voir en-tête.
      void envoyerFichiersDuChantier(interventionId)
        .then(() => declencherVidange())
        .then(() => rafraichirMutations())
        .catch(() => undefined); // best-effort, jamais bloquant pour le rendu de l'écran
    })();
    return () => {
      annule = true;
    };
  }, [interventionId, rafraichirMutations]);

  const surTerminer = useCallback(async () => {
    if (!interventionId) {
      return;
    }
    const configuration = obtenirConfigurationAppel();
    if (!configuration) {
      setErreurAppareil(true);
      return;
    }
    setErreurAppareil(false);
    setDernierVerdict(null);
    setEnTraitement(true);
    try {
      await envoyerFichiersDuChantier(interventionId);
      await declencherVidange();
      const mutationsActuelles = await rafraichirMutations();

      const photosCandidats = candidatsPhotosApres(mutationsActuelles, interventionId);
      const signatureCandidat = candidatSignature(mutationsActuelles, interventionId);

      const etat = evaluerPreparationCompletion({
        checklistComplete: checklistTerminee(checklistItems),
        photosApresSha256: photosCandidats.map((c) => c.sha256),
        signatureSha256: signatureCandidat ? signatureCandidat.sha256 : null,
        signatureRequise,
        notes,
        mutations: mutationsActuelles,
        chantierId: interventionId,
      });

      if (!etat.pret) {
        setBlocage(etat.raison);
        return;
      }
      setBlocage(null);

      const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
      const horodatageLocal = formaterHorodatageLocal(horloge);
      const args = construireArgumentsCompleterIntervention(interventionId, horodatageLocal, etat.preuves, signatureRequise === true);

      const brouillon = creerMutation({ type: "job_completion", chantierId: interventionId, payload: { ...args } }, genererMutationId, horloge);
      const enAttente = soumettreMutation(brouillon);
      const depot = await obtenirDepot();
      await depot.inserer(enAttente);

      const rapport = await declencherVidange();
      await rafraichirMutations();
      if (!rapport) {
        return;
      }

      const echec = rapport.echecsPermanents.find((e) => e.id === enAttente.id);
      if (echec) {
        setDernierVerdict(echec.verdict);
        return;
      }

      const accepte = rapport.resultatsAcceptes.find((r) => r.id === enAttente.id);
      if (accepte && estAccuseCompletionM4(accepte.resume)) {
        setResultatCompletion({ statut: accepte.resume.statut });

        // Le `wct_id` de l'accusé est tout ce que `materials.tsx` enverra à M6, qui relit le WCT
        // publié par M4 (voir src/m4/completion.ts, en-tête).
        await ecrireWctIdCompletion(await obtenirDepotLocal(), interventionId, accepte.resume.wct_id);
        setPretPourMateriaux(true);
      }
      // Ni accepté ni rejeté après cette tentative : la mutation reste `en_attente` (hors ligne) —
      // pas une erreur, voir complete.enAttenteEnvoi ci-dessous.
    } finally {
      setEnTraitement(false);
    }
  }, [interventionId, checklistItems, notes, signatureRequise, rafraichirMutations]);

  const mutationCompletion = mutations.find((m) => m.type === "job_completion" && m.chantierId === interventionId);
  // `en_attente`/`envoi` seulement : `envoyee`/`echec_permanent` sont des états déjà RÉSOLUS
  // (même si `resultatCompletion`/`dernierVerdict`, purement locaux à CET écran, ne les
  // connaissent pas en détail — ex. un déclencheur d'arrière-plan a résolu la mutation pendant
  // que l'écran était fermé, même limite documentée que `punch.tsx`, voir MOBILE.md) : les
  // afficher comme « en attente » serait un mensonge, pas seulement un texte moins détaillé.
  const enAttenteConfirmation =
    !resultatCompletion &&
    !dernierVerdict &&
    (mutationCompletion?.statut === "en_attente" || mutationCompletion?.statut === "envoi");
  // Vrai dès que le serveur a accepté la complétion — soit CETTE session le sait en détail
  // (`resultatCompletion`), soit une session précédente/un déclencheur d'arrière-plan l'a déjà
  // fait et seul le statut persisté (`envoyee`) en témoigne (voir la note ci-dessus) : dans les
  // deux cas, retenter « Terminer » n'a plus de sens (le serveur refuserait la retransition,
  // REJ-TRANSITION-ILLEGALE, `etats.py`) — le bouton reste désactivé dans les deux cas.
  const completionEnvoyee = resultatCompletion !== null || mutationCompletion?.statut === "envoyee";

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("complete.titre")}</Text>
      <Text style={styles.identifiant}>{interventionId}</Text>

      {!charge ? <ActivityIndicator /> : null}

      <TextInput
        style={styles.champMultiligne}
        placeholder={t("complete.champNotes")}
        value={notes}
        onChangeText={setNotes}
        editable={!enTraitement}
        multiline
        accessibilityLabel={t("complete.champNotes")}
      />

      <View style={styles.ligneSwitch}>
        <Text style={styles.libelleSwitch}>{t("complete.signatureRequise.question")}</Text>
        <View style={styles.boutonsSwitch}>
          <Pressable
            style={[styles.choixSignature, signatureRequise === true ? styles.choixSignatureActif : null]}
            disabled={enTraitement}
            onPress={() => setSignatureRequise(true)}
          >
            <Text style={signatureRequise === true ? styles.choixSignatureTexteActif : styles.choixSignatureTexte}>
              {t("complete.signatureRequise.oui")}
            </Text>
          </Pressable>
          <Pressable
            style={[styles.choixSignature, signatureRequise === false ? styles.choixSignatureActif : null]}
            disabled={enTraitement}
            onPress={() => setSignatureRequise(false)}
          >
            <Text style={signatureRequise === false ? styles.choixSignatureTexteActif : styles.choixSignatureTexte}>
              {t("complete.signatureRequise.non")}
            </Text>
          </Pressable>
        </View>
      </View>

      {erreurAppareil ? <Text style={styles.erreur}>{t("complete.appareilNonAppaire")}</Text> : null}
      {blocage ? <Text style={styles.avis}>{t(`complete.blocages.${blocage}`)}</Text> : null}
      {dernierVerdict ? (
        <Text style={styles.erreur}>
          {t("complete.verdict.echecPermanentAvecVerdict", { code: dernierVerdict.code, detail: dernierVerdict.detail })}
        </Text>
      ) : null}
      {enAttenteConfirmation ? <Text style={styles.avis}>{t("complete.enAttenteEnvoi")}</Text> : null}

      {completionEnvoyee ? (
        <View style={styles.succes}>
          <Text style={styles.succesTitre}>{t("complete.succes.titre")}</Text>
          {resultatCompletion ? (
            <Text style={styles.succesStatut}>{t("complete.succes.statut", { statut: resultatCompletion.statut })}</Text>
          ) : null}
        </View>
      ) : null}

      <Pressable
        style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
        disabled={enTraitement || completionEnvoyee}
        onPress={() => void surTerminer()}
      >
        {enTraitement ? <ActivityIndicator color="#fff" /> : <Text style={styles.boutonTexte}>{t("complete.bouton")}</Text>}
      </Pressable>

      {pretPourMateriaux ? (
        <Link href={{ pathname: "/job/[id]/materials", params: { id: interventionId } }} style={styles.lien}>
          {t("complete.lienMateriaux")}
        </Link>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  conteneur: { flexGrow: 1, padding: 16, gap: 10 },
  titre: { fontSize: 20, fontWeight: "600" },
  identifiant: { color: "#888", fontSize: 12 },
  champMultiligne: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 10, minHeight: 80, textAlignVertical: "top" },
  ligneSwitch: { gap: 8 },
  libelleSwitch: { fontWeight: "600" },
  boutonsSwitch: { flexDirection: "row", gap: 8 },
  choixSignature: { paddingVertical: 8, paddingHorizontal: 14, borderRadius: 6, borderWidth: 1, borderColor: "#999" },
  choixSignatureActif: { backgroundColor: "#1c6f5c", borderColor: "#1c6f5c" },
  choixSignatureTexte: { color: "#333" },
  choixSignatureTexteActif: { color: "#fff", fontWeight: "600" },
  erreur: { color: "#b00020" },
  avis: { color: "#666" },
  succes: { backgroundColor: "#eaf5f1", borderRadius: 8, padding: 12, gap: 4 },
  succesTitre: { color: "#1c6f5c", fontWeight: "600" },
  succesStatut: { color: "#1c6f5c" },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 12, borderRadius: 6, alignItems: "center" },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  lien: { color: "#1c6f5c", fontWeight: "600", marginTop: 8 },
});
