import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import * as Crypto from "expo-crypto";
import { useTranslation } from "react-i18next";

import {
  ajouterLigne,
  creerLigneVide,
  evaluerPreparationFormulaire,
  modifierLigne,
  retirerLigne,
  TYPES_LIGNE_MATERIAUX,
  validerLigne,
} from "@/ecrans/materials";
import type { LigneEnSaisie } from "@/ecrans/materials";
import { construireArgumentsDeclarerMateriauxUtilises } from "@/m6/materiaux";
import type { VerdictServeurMateriaux } from "@/m6/materiaux";
import { lireWctEnCache } from "@/m4/wctCache";
import type { WctRecuM4 } from "@/m4/completion";
import { genererMutationId } from "@/outbox/id";
import { creerMutation, formaterHorodatageLocal, soumettreMutation } from "@/outbox/mutation";
import { declencherVidange, obtenirDepot } from "@/outbox/service";
import { obtenirConfigurationAppel } from "@/protocole/configuration";
import { obtenirDepotLocal } from "@/stockage/service";

/**
 * `materials.tsx` (M6.10, R12 §5 étape 5, PLAN T1.4-f) : formulaire des matériaux utilisés,
 * ouvert APRÈS « Terminer » (`complete.tsx`) — DEFINITION-PRODUIT.md §9.7 étape 3. Envoie
 * `m6_declarer_materiaux_utilises` par la file sortante (mission item 3).
 *
 * **Aucune quantité ni prix proposés par défaut** — `src/ecrans/materials.ts::creerLigneVide` ne
 * pré-remplit rien : l'employé saisit, le serveur calcule le coût unitaire
 * (`_dernier_cout_unitaire_connu`, jamais transmis par le mobile).
 *
 * **`wct` lu depuis le cache posé par `complete.tsx`** (`src/m4/wctCache.ts`) — jamais reconstruit
 * ici : voir la docstring de `src/m4/completion.ts` pour le pont `m4_lire_outbox` qui l'a peuplé.
 * Aucun WCT en cache -> `materials.aucunWct`, formulaire bloqué (fail-closed, jamais un WCT
 * deviné) : l'employé doit retourner à l'écran « Terminer ».
 *
 * Écran non testé en rendu (même limite que les autres écrans de cette tranche) :
 * `src/ecrans/materials.ts`, `src/m6/materiaux.ts` portent la logique, testée là.
 */
export default function EcranMateriaux() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const interventionId = typeof id === "string" ? id : "";

  const [wct, setWct] = useState<WctRecuM4 | null>(null);
  const [charge, setCharge] = useState(false);
  const [lignes, setLignes] = useState<LigneEnSaisie[]>([]);
  const [enTraitement, setEnTraitement] = useState(false);
  const [erreurAppareil, setErreurAppareil] = useState(false);
  const [blocage, setBlocage] = useState<"aucune_ligne" | "lignes_invalides" | null>(null);
  const [dernierVerdict, setDernierVerdict] = useState<VerdictServeurMateriaux | null>(null);
  const [soumis, setSoumis] = useState(false);
  const [enAttenteConfirmation, setEnAttenteConfirmation] = useState(false);

  const rafraichirWct = useCallback(async () => {
    if (!interventionId) {
      return;
    }
    const valeur = await lireWctEnCache(await obtenirDepotLocal(), interventionId);
    setWct(valeur);
    setCharge(true);
  }, [interventionId]);

  useEffect(() => {
    void rafraichirWct();
  }, [rafraichirWct]);

  const surAjouterLigne = useCallback(() => {
    setLignes((actuelles) => ajouterLigne(actuelles, creerLigneVide(Crypto.randomUUID())));
  }, []);

  const surSoumettre = useCallback(async () => {
    if (!interventionId || !wct) {
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
      const etat = evaluerPreparationFormulaire(wct.wct_id, interventionId, interventionId, lignes);
      if (!etat.pret) {
        setBlocage(etat.raison);
        return;
      }
      setBlocage(null);

      const args = construireArgumentsDeclarerMateriauxUtilises(wct, etat.formulaire);
      const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };

      const depot = await obtenirDepot();
      const toutes = await depot.lister();
      // Lien de traçabilité vers la complétion dont ce WCT provient (P3) — sans effet sur
      // l'envoi lui-même : au moment où ce formulaire est soumissible, le WCT est déjà connu, donc
      // sa mutation `job_completion` est nécessairement déjà `envoyee` (voir src/m4/wctCache.ts).
      const completion = toutes.find((m) => m.type === "job_completion" && m.chantierId === interventionId && m.statut === "envoyee");

      const brouillon = creerMutation(
        { type: "materials_submit", chantierId: interventionId, payload: { ...args }, dependsOn: completion?.id ?? null },
        genererMutationId,
        horloge,
      );
      const enAttente = soumettreMutation(brouillon);
      await depot.inserer(enAttente);

      const rapport = await declencherVidange();
      if (!rapport) {
        setEnAttenteConfirmation(true);
        return;
      }

      const echec = rapport.echecsPermanents.find((e) => e.id === enAttente.id);
      if (echec) {
        setDernierVerdict(echec.verdict);
        return;
      }
      const accepte = rapport.resultatsAcceptes.find((r) => r.id === enAttente.id);
      if (accepte) {
        setSoumis(true);
        return;
      }
      setEnAttenteConfirmation(true);
    } finally {
      setEnTraitement(false);
    }
  }, [interventionId, wct, lignes]);

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("materials.titre")}</Text>
      <Text style={styles.identifiant}>{interventionId}</Text>

      {!charge ? <ActivityIndicator /> : null}
      {charge && !wct ? <Text style={styles.erreur}>{t("materials.aucunWct")}</Text> : null}

      {wct ? (
        <>
          {lignes.length === 0 ? <Text style={styles.vide}>{t("materials.aucuneLigne")}</Text> : null}

          {lignes.map((ligne) => (
            <LigneMateriau
              key={ligne.id}
              ligne={ligne}
              enTraitement={enTraitement}
              onChange={(patch) => setLignes((actuelles) => modifierLigne(actuelles, ligne.id, patch))}
              onRetirer={() => setLignes((actuelles) => retirerLigne(actuelles, ligne.id))}
            />
          ))}

          <Pressable style={styles.boutonSecondaire} disabled={enTraitement} onPress={surAjouterLigne}>
            <Text style={styles.boutonSecondaireTexte}>{t("materials.ajouterLigne")}</Text>
          </Pressable>

          {erreurAppareil ? <Text style={styles.erreur}>{t("materials.appareilNonAppaire")}</Text> : null}
          {blocage ? <Text style={styles.avis}>{t(`materials.blocages.${blocage}`)}</Text> : null}
          {dernierVerdict ? (
            <Text style={styles.erreur}>
              {t("materials.verdict.echecPermanentAvecVerdict", { code: dernierVerdict.code, detail: dernierVerdict.detail })}
            </Text>
          ) : null}
          {enAttenteConfirmation && !soumis ? <Text style={styles.avis}>{t("materials.enAttenteEnvoi")}</Text> : null}
          {soumis ? <Text style={styles.succes}>{t("materials.succes")}</Text> : null}

          <Pressable
            style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
            disabled={enTraitement || soumis}
            onPress={() => void surSoumettre()}
          >
            {enTraitement ? <ActivityIndicator color="#fff" /> : <Text style={styles.boutonTexte}>{t("materials.bouton")}</Text>}
          </Pressable>
        </>
      ) : null}
    </ScrollView>
  );
}

interface ProprietesLigneMateriau {
  readonly ligne: LigneEnSaisie;
  readonly enTraitement: boolean;
  readonly onChange: (patch: Partial<LigneEnSaisie>) => void;
  readonly onRetirer: () => void;
}

/** Un éditeur de ligne — composant local, pas exporté : uniquement le câblage React d'une
 * `LigneEnSaisie` (`src/ecrans/materials.ts`, qui porte toute la logique testée). */
function LigneMateriau({ ligne, enTraitement, onChange, onRetirer }: ProprietesLigneMateriau) {
  const { t } = useTranslation();
  const erreur = validerLigne(ligne);

  return (
    <View style={styles.ligneCarte}>
      <View style={styles.onglets}>
        {TYPES_LIGNE_MATERIAUX.map((type) => (
          <Pressable
            key={type}
            style={[styles.onglet, ligne.typeLigne === type ? styles.ongletActif : null]}
            disabled={enTraitement}
            onPress={() => onChange({ typeLigne: type })}
          >
            <Text style={ligne.typeLigne === type ? styles.ongletTexteActif : styles.ongletTexte}>{t(`materials.typeLigne.${type}`)}</Text>
          </Pressable>
        ))}
      </View>

      <TextInput
        style={styles.champ}
        placeholder={t("materials.champMateriau")}
        value={ligne.materiauId}
        onChangeText={(v) => onChange({ materiauId: v })}
        editable={!enTraitement}
        accessibilityLabel={t("materials.champMateriau")}
      />
      <View style={styles.ligneChamps}>
        <TextInput
          style={[styles.champ, styles.champMoitie]}
          placeholder={t("materials.champQuantite")}
          value={ligne.quantiteTexte}
          onChangeText={(v) => onChange({ quantiteTexte: v })}
          editable={!enTraitement}
          keyboardType="numeric"
          accessibilityLabel={t("materials.champQuantite")}
        />
        <TextInput
          style={[styles.champ, styles.champMoitie]}
          placeholder={t("materials.champUnite")}
          value={ligne.unite}
          onChangeText={(v) => onChange({ unite: v })}
          editable={!enTraitement}
          accessibilityLabel={t("materials.champUnite")}
        />
      </View>

      {ligne.typeLigne === "prevu" ? (
        <TextInput
          style={styles.champ}
          placeholder={t("materials.champQuantiteEstimee")}
          value={ligne.quantiteEstimeeTexte}
          onChangeText={(v) => onChange({ quantiteEstimeeTexte: v })}
          editable={!enTraitement}
          keyboardType="numeric"
          accessibilityLabel={t("materials.champQuantiteEstimee")}
        />
      ) : null}

      {ligne.typeLigne === "achat_terrain" ? (
        <View style={styles.ligneChamps}>
          <Pressable
            style={[styles.casePreuve, ligne.photoFournie ? styles.casePreuveActive : null]}
            disabled={enTraitement}
            onPress={() => onChange({ photoFournie: !ligne.photoFournie })}
          >
            <Text style={ligne.photoFournie ? styles.casePreuveTexteActif : styles.casePreuveTexte}>{t("materials.photoFournie")}</Text>
          </Pressable>
          <Pressable
            style={[styles.casePreuve, ligne.recuFourni ? styles.casePreuveActive : null]}
            disabled={enTraitement}
            onPress={() => onChange({ recuFourni: !ligne.recuFourni })}
          >
            <Text style={ligne.recuFourni ? styles.casePreuveTexteActif : styles.casePreuveTexte}>{t("materials.recuFourni")}</Text>
          </Pressable>
        </View>
      ) : null}

      {erreur ? <Text style={styles.erreurLigne}>{t(`materials.erreurs.${erreur}`)}</Text> : null}

      <Pressable disabled={enTraitement} onPress={onRetirer}>
        <Text style={styles.retirer}>{t("materials.retirerLigne")}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flexGrow: 1, padding: 16, gap: 10 },
  titre: { fontSize: 20, fontWeight: "600" },
  identifiant: { color: "#888", fontSize: 12 },
  vide: { color: "#666" },
  erreur: { color: "#b00020" },
  erreurLigne: { color: "#b00020", fontSize: 12 },
  avis: { color: "#666" },
  succes: { color: "#1c6f5c", fontWeight: "600" },
  ligneCarte: { borderWidth: 1, borderColor: "#ddd", borderRadius: 8, padding: 12, gap: 8 },
  onglets: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  onglet: { paddingVertical: 6, paddingHorizontal: 10, borderRadius: 6, borderWidth: 1, borderColor: "#999" },
  ongletActif: { backgroundColor: "#1c6f5c", borderColor: "#1c6f5c" },
  ongletTexte: { color: "#333", fontSize: 12 },
  ongletTexteActif: { color: "#fff", fontWeight: "600", fontSize: 12 },
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 10 },
  ligneChamps: { flexDirection: "row", gap: 8 },
  champMoitie: { flex: 1 },
  casePreuve: { flex: 1, paddingVertical: 8, borderRadius: 6, borderWidth: 1, borderColor: "#999", alignItems: "center" },
  casePreuveActive: { backgroundColor: "#1c6f5c", borderColor: "#1c6f5c" },
  casePreuveTexte: { color: "#333" },
  casePreuveTexteActif: { color: "#fff", fontWeight: "600" },
  retirer: { color: "#b00020" },
  boutonSecondaire: { borderWidth: 1, borderColor: "#1c6f5c", paddingVertical: 10, borderRadius: 6, alignItems: "center" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 12, borderRadius: 6, alignItems: "center" },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
});
