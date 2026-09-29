import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";

import { formaterDepuis } from "@/ecrans/approvals";
import { avisDesSources, presenterEntree } from "@/ecrans/quotes";
import type { CarteDevis, LangueMontant, VueEntreeDevis } from "@/ecrans/quotes";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import type { EntreeDevis, ResultatDevis } from "@/vendeur/chargeurDevis";
import { chargerDevis, ouvrirDevisParNumero } from "@/vendeur/service";

/**
 * `quotes.tsx` (§9.4 « soumissions » ; M3 ; PLAN T4.8) : les devis du vendeur par `m3_lire_devis` — statut et prix,
 * JAMAIS le coût ni la marge (la vue interne que M3 rend au vendeur est réduite à sa liste blanche avant tout
 * affichage et tout cache : `src/m3/devis.ts`). Lecture d'abord, cache SQLite hors ligne marqué comme tel.
 *
 * Aucun outil ne liste les devis d'un vendeur : la liste montre ceux que les leads citent (`m2_lister_leads`,
 * segments `won_pending_schedule` et `quote_stale`), et le vendeur ouvre les autres par leur numéro. L'écran le dit ;
 * un segment non calculable, une lecture partielle ou en échec l'est aussi (`avisDesSources`). Toute la logique est
 * dans `src/ecrans/quotes.ts` et `src/vendeur/`, testée là ; ce fichier n'est que le câblage React (non couvert en
 * rendu, même limite que les autres écrans).
 */
export default function EcranSoumissions() {
  const { t, i18n } = useTranslation();
  const langue: LangueMontant = i18n.language === "en-CA" ? "en-CA" : "fr-CA";
  const [resultat, setResultat] = useState<ResultatDevis | null | undefined>(undefined);
  const [chargement, setChargement] = useState(true);
  const [numero, setNumero] = useState("");
  const [ouverts, setOuverts] = useState<readonly EntreeDevis[]>([]);
  const [numeroVide, setNumeroVide] = useState(false);
  const [sansSession, setSansSession] = useState(false);
  const [ouverture, setOuverture] = useState(false);
  const [lignesVisibles, setLignesVisibles] = useState<ReadonlySet<string>>(new Set());
  const sequence = useRef(0);

  const charger = useCallback(async () => {
    const numeroLecture = ++sequence.current;
    setChargement(true);
    try {
      const lu = await chargerDevis();
      if (numeroLecture !== sequence.current) {
        return;
      }
      setResultat(lu);
      setSansSession(lu === null);
    } finally {
      if (numeroLecture === sequence.current) {
        setChargement(false);
      }
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  const ouvrir = useCallback(async () => {
    setNumeroVide(false);
    setOuverture(true);
    try {
      const entree = await ouvrirDevisParNumero(numero);
      if (entree === undefined) {
        setSansSession(true);
        return;
      }
      if (entree === null) {
        setNumeroVide(true);
        return;
      }
      setSansSession(false);
      setOuverts((precedents) => [entree, ...precedents.filter((e) => e.connu.devisId !== entree.connu.devisId)]);
      setNumero("");
    } finally {
      setOuverture(false);
    }
  }, [numero]);

  const basculerLignes = useCallback((devisId: string) => {
    setLignesVisibles((precedentes) => {
      const suivantes = new Set(precedentes);
      if (suivantes.has(devisId)) {
        suivantes.delete(devisId);
      } else {
        suivantes.add(devisId);
      }
      return suivantes;
    });
  }, []);

  const decalageMinutesUTC = -new Date().getTimezoneOffset();
  const entrees = resultat?.entrees ?? [];
  const dejaAffiches = new Set(entrees.map((e) => e.connu.devisId));
  const ouvertsEnPlus = ouverts.filter((e) => !dejaAffiches.has(e.connu.devisId));

  const carte = (entree: EntreeDevis) => (
    <VueDevis
      key={entree.connu.devisId}
      vue={presenterEntree(entree, langue)}
      lignesVisibles={lignesVisibles.has(entree.connu.devisId)}
      decalageMinutesUTC={decalageMinutesUTC}
      onBasculerLignes={() => basculerLignes(entree.connu.devisId)}
    />
  );

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("vendeur.quotes.titre")}</Text>
      <BandeauIdentite />
      <Text style={styles.meta}>{t("vendeur.quotes.prixSeulement")}</Text>
      <Text style={styles.avis}>{t("vendeur.quotes.limiteListe")}</Text>

      <Pressable style={styles.boutonSecondaire} disabled={chargement} onPress={() => void charger()}>
        <Text style={styles.boutonSecondaireTexte}>{t("vendeur.commun.rafraichir")}</Text>
      </Pressable>

      <View style={styles.carte}>
        <TextInput
          style={styles.champ}
          placeholder={t("vendeur.quotes.numero.indice")}
          accessibilityLabel={t("vendeur.quotes.numero.etiquette")}
          value={numero}
          onChangeText={setNumero}
          autoCapitalize="none"
          autoCorrect={false}
          editable={!ouverture}
        />
        {numeroVide ? <Text style={styles.erreur}>{t("vendeur.quotes.numero.vide")}</Text> : null}
        <Pressable style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]} disabled={ouverture} onPress={() => void ouvrir()}>
          <Text style={styles.boutonTexte}>{t("vendeur.quotes.numero.ouvrir")}</Text>
        </Pressable>
      </View>

      {chargement ? <ActivityIndicator /> : null}
      {sansSession ? <Text style={styles.erreur}>{t("vendeur.commun.sansSession")}</Text> : null}

      {resultat
        ? avisDesSources(resultat.sources).map((avis) => (
            <Text key={`${avis.segment}:${avis.genre}`} style={avis.genre === "echouee" ? styles.erreur : styles.avis}>
              {avis.genre === "non_calculable"
                ? t("vendeur.quotes.avis.non_calculable", { segment: avis.segment, manque: avis.manque })
                : avis.genre === "echouee"
                  ? t("vendeur.quotes.avis.echouee", { segment: avis.segment, code: avis.verdict.code, detail: avis.verdict.detail })
                  : avis.genre === "partielle"
                    ? t("vendeur.quotes.avis.partielle", { segment: avis.segment, reste: avis.reste })
                    : t("vendeur.quotes.avis.depuis_cache", { segment: avis.segment, code: avis.raison.code })}
            </Text>
          ))
        : null}

      {ouvertsEnPlus.length > 0 ? <Text style={styles.sousTitre}>{t("vendeur.quotes.numero.ouvertsTitre")}</Text> : null}
      {ouvertsEnPlus.map(carte)}

      {resultat && entrees.length === 0 && ouvertsEnPlus.length === 0 ? <Text style={styles.vide}>{t("vendeur.quotes.aucune")}</Text> : null}
      {entrees.map(carte)}
    </ScrollView>
  );
}

interface ProprietesVue {
  readonly vue: VueEntreeDevis;
  readonly lignesVisibles: boolean;
  readonly decalageMinutesUTC: number;
  readonly onBasculerLignes: () => void;
}

/** Un devis : statut et prix total, ses lignes décrites (jamais coût ni marge). Un refus du serveur ou l'impossibilité
 * de lire est dit, avec ses mots ; un cache est marqué comme tel, avec sa date. */
function VueDevis({ vue, lignesVisibles, decalageMinutesUTC, onBasculerLignes }: ProprietesVue) {
  const { t } = useTranslation();
  const absent = t("vendeur.commun.absent");
  if (vue.genre === "refus") {
    return (
      <View style={styles.carte}>
        <Text style={styles.erreur}>
          {t("vendeur.quotes.refus", { id: vue.devisId, code: vue.verdict.code, detail: vue.verdict.detail })}
        </Text>
      </View>
    );
  }
  if (vue.genre === "indisponible") {
    return (
      <View style={styles.carte}>
        <Text style={styles.erreur}>
          {t("vendeur.quotes.indisponible", { id: vue.devisId, code: vue.raison.code })}
        </Text>
      </View>
    );
  }
  const carte: CarteDevis = vue.carte;
  return (
    <View style={styles.carte}>
      <Text style={styles.outil}>{carte.devisId}</Text>
      <Text style={styles.meta}>{t("vendeur.quotes.lead", { id: carte.leadId })}</Text>
      <Text style={styles.meta}>{t(`vendeur.quotes.origine.${carte.origine}`)}</Text>
      <Text style={styles.meta}>
        {t("vendeur.quotes.statut", {
          statut: carte.statutConnu ? t(`vendeur.quotes.statuts.${carte.statut}`) : t("vendeur.quotes.statutInconnu", { statut: carte.statut }),
        })}
      </Text>
      <Text style={styles.prix}>
        {carte.prixTotal === null ? t("vendeur.quotes.prixAbsent") : t("vendeur.quotes.prixTotal", { montant: carte.prixTotal })}
      </Text>
      {carte.cache !== null ? (
        <Text style={styles.avis}>
          {t("vendeur.commun.cache", { date: formaterDepuis(carte.cache.misAJourLe, decalageMinutesUTC), code: carte.cache.raison.code })}
        </Text>
      ) : (
        <Text style={styles.trace}>{formaterDepuis(carte.misAJourLe, decalageMinutesUTC)}</Text>
      )}
      <Pressable onPress={onBasculerLignes} accessibilityRole="button">
        <Text style={styles.lien}>{lignesVisibles ? t("vendeur.quotes.masquerLignes") : t("vendeur.quotes.voirLignes")}</Text>
      </Pressable>
      {lignesVisibles
        ? carte.lignes.map((ligne) => (
            <View key={ligne.referenceLigne} style={styles.ligne}>
              <Text style={styles.outil}>
                {ligne.quantite === null
                  ? t("vendeur.quotes.ligneSansQuantite", { description: ligne.description })
                  : t("vendeur.quotes.ligne", { description: ligne.description, quantite: ligne.quantite, unite: ligne.unite ?? absent })}
              </Text>
              <Text style={styles.meta}>{t("vendeur.quotes.prixUnitaire", { montant: ligne.prixUnitaire ?? absent })}</Text>
              <Text style={styles.meta}>{t("vendeur.quotes.prixLigne", { montant: ligne.prixLigne ?? absent })}</Text>
            </View>
          ))
        : null}
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { padding: 16, gap: 12 },
  titre: { fontSize: 20, fontWeight: "600" },
  sousTitre: { fontSize: 14, fontWeight: "600" },
  vide: { color: "#666" },
  avis: { color: "#7a5b00" },
  erreur: { color: "#b00020" },
  meta: { color: "#444" },
  trace: { color: "#666", fontSize: 12 },
  prix: { fontSize: 16, fontWeight: "600" },
  lien: { color: "#1c6f5c", fontWeight: "600" },
  outil: { fontSize: 15, fontWeight: "600" },
  carte: { borderWidth: 1, borderColor: "#bbb", borderRadius: 8, padding: 12, gap: 6 },
  ligne: { gap: 2, paddingVertical: 4 },
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 8 },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  boutonSecondaire: { borderWidth: 1, borderColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
});
