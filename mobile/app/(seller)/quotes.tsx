import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";

import { formaterDepuis } from "@/ecrans/approvals";
import { presenterEntree } from "@/ecrans/quotes";
import type { CarteDevis, LangueMontant, VueEntreeDevis } from "@/ecrans/quotes";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { identiteDepuisEtat } from "@/identite/etat";
import { useEtatIdentite } from "@/roles/contexte";
import type { EntreeDevis, ResultatInventaireDevis } from "@/vendeur/chargeurDevis";
import { chargerDevis, chargerSuiteDevis, ouvrirDevisParNumero } from "@/vendeur/service";
import { inventaireVisiblePourPersonne, peutAppliquerReponseInventaire } from "@/vendeur/visibiliteInventaire";

/**
 * `quotes.tsx` (§9.4 « soumissions » ; M3) : inventaire courant par `m3_lister_devis`, et lecture manuelle par
 * `m3_lire_devis`. L'app réduit chaque réponse à statut et prix, jamais coût ni marge, avant affichage ou cache
 * individuel (`src/m3/devis.ts`). La liste n'est pas gardée hors ligne.
 *
 * Une panne vide l'inventaire affiché; le vendeur peut toujours ouvrir manuellement un devis dont il a le numéro,
 * avec copie locale explicitement marquée si le serveur est injoignable. La logique de contrat et de cache est dans
 * `src/m3/` et `src/vendeur/`. Ce fichier câble React et reste à vérifier dans un environnement de rendu natif.
 */
export default function EcranSoumissions() {
  const identite = identiteDepuisEtat(useEtatIdentite());
  const personne = identite?.role === "seller" ? identite.personne : null;
  const cleIdentite = personne === null ? "sans-identite" : `${identite?.appareilId}:${personne}`;
  return <EcranSoumissionsParPersonne key={cleIdentite} personne={personne} />;
}

function EcranSoumissionsParPersonne({ personne }: { readonly personne: string | null }) {
  const { t, i18n } = useTranslation();
  const langue: LangueMontant = i18n.language === "en-CA" ? "en-CA" : "fr-CA";
  const [resultat, setResultat] = useState<ResultatInventaireDevis | null | undefined>(undefined);
  const [chargement, setChargement] = useState(true);
  const [numero, setNumero] = useState("");
  const [ouverts, setOuverts] = useState<readonly EntreeDevis[]>([]);
  const [numeroVide, setNumeroVide] = useState(false);
  const [sansSession, setSansSession] = useState(false);
  const [ouverture, setOuverture] = useState(false);
  const [lignesVisibles, setLignesVisibles] = useState<ReadonlySet<string>>(new Set());
  const sequence = useRef(0);
  const personneCourante = useRef(personne);
  personneCourante.current = personne;

  const charger = useCallback(async () => {
    const numeroLecture = ++sequence.current;
    setResultat(null);
    setOuverts([]);
    setSansSession(false);
    setOuverture(false);
    setChargement(true);
    try {
      if (personne === null) {
        setResultat(null);
        setSansSession(true);
        return;
      }
      const lu = await chargerDevis();
      if (numeroLecture !== sequence.current) {
        return;
      }
      if (lu === null) {
        setResultat(null);
        setSansSession(true);
        return;
      }
      if (
        !peutAppliquerReponseInventaire(
          lu.personne,
          personneCourante.current,
          numeroLecture,
          sequence.current,
        )
      ) {
        setResultat(null);
        setSansSession(true);
        return;
      }
      setResultat(lu);
      setSansSession(lu === null);
    } finally {
      if (numeroLecture === sequence.current) {
        setChargement(false);
      }
    }
  }, [personne]);

  const chargerSuite = useCallback(async () => {
    const courant = resultat;
    if (courant === null || courant === undefined || courant.curseurSuivant === null) {
      return;
    }
    const numeroLecture = ++sequence.current;
    setOuverts([]);
    setOuverture(false);
    setChargement(true);
    try {
      const suite = await chargerSuiteDevis(courant.curseurSuivant, courant.personne);
      if (numeroLecture !== sequence.current) {
        return;
      }
      if (suite === null) {
        setResultat(null);
        setSansSession(true);
        return;
      }
      if (
        !peutAppliquerReponseInventaire(
          suite.personne,
          personneCourante.current,
          numeroLecture,
          sequence.current,
        )
      ) {
        setResultat(null);
        setSansSession(true);
        return;
      }
      if (suite.etat.genre !== "serveur") {
        setResultat(suite);
        setSansSession(false);
        return;
      }
      setResultat((precedent) => {
        if (precedent === null || precedent === undefined || precedent.personne !== suite.personne) {
          return suite;
        }
        const parId = new Map(precedent.entrees.map((entree) => [entree.connu.devisId, entree]));
        for (const entree of suite.entrees) {
          parId.set(entree.connu.devisId, entree);
        }
        return { ...suite, entrees: [...parId.values()] };
      });
      setSansSession(false);
    } finally {
      if (numeroLecture === sequence.current) {
        setChargement(false);
      }
    }
  }, [resultat]);

  useEffect(() => {
    if (personne === null) {
      setChargement(false);
      setSansSession(true);
    } else {
      void charger();
    }
    return () => {
      sequence.current += 1;
    };
  }, [charger, personne]);

  const ouvrir = useCallback(async () => {
    const numeroLecture = ++sequence.current;
    setResultat(null);
    setOuverts([]);
    setNumeroVide(false);
    setSansSession(false);
    setChargement(false);
    setOuverture(true);
    try {
      if (personne === null) {
        setSansSession(true);
        return;
      }
      const entree = await ouvrirDevisParNumero(numero);
      if (numeroLecture !== sequence.current) {
        return;
      }
      if (entree === undefined) {
        setResultat(null);
        setSansSession(true);
        return;
      }
      if (entree === null) {
        setNumeroVide(true);
        return;
      }
      if (entree.etat.genre === "refus" && entree.etat.verdict.code !== "REJ-DEVIS-INTROUVABLE") {
        setResultat(null);
        setSansSession(true);
      } else if (entree.etat.genre === "refus") {
        setResultat((precedent) => precedent === null || precedent === undefined
          ? precedent
          : { ...precedent, entrees: precedent.entrees.filter((e) => e.connu.devisId !== entree.connu.devisId) });
      }
      setOuverts([entree]);
      setNumero("");
    } finally {
      if (numeroLecture === sequence.current) {
        setOuverture(false);
      }
    }
  }, [numero, personne]);

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
  const resultatVisible = inventaireVisiblePourPersonne(resultat, personne) ? resultat : null;
  const entrees = resultatVisible?.entrees ?? [];
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

      <Pressable
        style={styles.boutonSecondaire}
        disabled={chargement || personne === null}
        onPress={() => void charger()}
      >
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
          editable={!ouverture && personne !== null}
        />
        {numeroVide ? <Text style={styles.erreur}>{t("vendeur.quotes.numero.vide")}</Text> : null}
        <Pressable
          style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
          disabled={ouverture || personne === null}
          onPress={() => void ouvrir()}
        >
          <Text style={styles.boutonTexte}>{t("vendeur.quotes.numero.ouvrir")}</Text>
        </Pressable>
      </View>

      {chargement ? <ActivityIndicator /> : null}
      {sansSession ? <Text style={styles.erreur}>{t("vendeur.commun.sansSession")}</Text> : null}

      {resultatVisible?.etat.genre === "serveur" ? (
        <Text style={styles.trace}>
          {t("vendeur.quotes.liste.consulteLe", {
            date: formaterDepuis(resultatVisible.etat.consulteLe, decalageMinutesUTC),
          })}
        </Text>
      ) : null}
      {resultatVisible?.etat.genre === "refus" ? (
        <Text style={styles.erreur}>
          {t("vendeur.quotes.liste.refus", { code: resultatVisible.etat.verdict.code })}
        </Text>
      ) : null}
      {resultatVisible?.etat.genre === "indisponible" ? (
        <Text style={styles.erreur}>
          {t("vendeur.quotes.liste.indisponible", { code: resultatVisible.etat.verdict.code })}
        </Text>
      ) : null}
      {resultatVisible?.etat.genre === "illisible" ? (
        <Text style={styles.erreur}>
          {t("vendeur.quotes.liste.illisible", { code: resultatVisible.etat.verdict.code })}
        </Text>
      ) : null}

      {ouvertsEnPlus.length > 0 ? <Text style={styles.sousTitre}>{t("vendeur.quotes.numero.ouvertsTitre")}</Text> : null}
      {ouvertsEnPlus.map(carte)}

      {resultatVisible?.etat.genre === "serveur" && entrees.length === 0 && ouvertsEnPlus.length === 0 ? (
        <Text style={styles.vide}>{t("vendeur.quotes.aucune")}</Text>
      ) : null}
      {entrees.map(carte)}
      {resultatVisible?.etat.genre === "serveur" && resultatVisible.curseurSuivant !== null ? (
        <Pressable style={styles.boutonSecondaire} disabled={chargement} onPress={() => void chargerSuite()}>
          <Text style={styles.boutonSecondaireTexte}>{t("vendeur.quotes.liste.suite")}</Text>
        </Pressable>
      ) : null}
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
