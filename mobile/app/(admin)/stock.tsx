import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text } from "react-native";
import { useTranslation } from "react-i18next";
import { chargerDisponibiliteM6, chargerDigestM6 } from "@/admin/service";
import { BoutonSecondaire, Carte, Depliant, EtatSection, Lignes, stylesAdmin as styles } from "@/admin/composants";
import type { ResultatSection } from "@/admin/lecture";
import { presenterSection } from "@/ecrans/adminCommun";
import { presenterDisponibilite, presenterDigest } from "@/ecrans/stock";
import type { GroupeStock } from "@/ecrans/stock";
import type { LangueMontant } from "@/ecrans/quotes";
import type { DisponibiliteStock, DigestStock } from "@/m6/stock";
import { BandeauIdentite } from "@/identite/BandeauIdentite";

async function securiser<T>(operation: Promise<ResultatSection<T> | null>): Promise<ResultatSection<T> | null> {
  try { return await operation; } catch {
    return { source: "aucune", raison: { code: "lecture_indisponible", detail: "Lecture momentanément indisponible." } };
  }
}

/** T4.23 : deux lectures admin indépendantes, aucune mutation ni pagination absente du serveur. */
export default function EcranStock() {
  const { t, i18n } = useTranslation();
  const langue: LangueMontant = i18n.language === "en-CA" ? "en-CA" : "fr-CA";
  const decalage = -new Date().getTimezoneOffset();
  const [disponibilite, setDisponibilite] = useState<ResultatSection<DisponibiliteStock>>();
  const [digest, setDigest] = useState<ResultatSection<DigestStock>>();
  const [sansSession, setSansSession] = useState(false);
  const sequence = useRef(0);
  const charger = useCallback(async () => {
    const n = ++sequence.current;
    setDisponibilite(undefined); setDigest(undefined); setSansSession(false);
    const recevoir = <T,>(poser: (v: ResultatSection<T>) => void) => (v: ResultatSection<T> | null) => {
      if (n !== sequence.current) return;
      if (v === null) setSansSession(true); else poser(v);
    };
    await Promise.all([
      securiser(chargerDisponibiliteM6()).then(recevoir(setDisponibilite)),
      securiser(chargerDigestM6()).then(recevoir(setDigest)),
    ]);
  }, []);
  useFocusEffect(useCallback(() => {
    void charger();
    return () => { ++sequence.current; };
  }, [charger]));
  const dispo = disponibilite ? presenterSection(disponibilite, decalage, v => presenterDisponibilite(v, langue)) : undefined;
  const ecarts = digest ? presenterSection(digest, decalage, v => presenterDigest(v, langue)) : undefined;
  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("admin.stock.titre")}</Text>
    <BandeauIdentite />
    <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />
    {sansSession ? <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text> : <>
      <Carte>
        <Text style={styles.sousTitre}>{t("admin.stock.disponibilite")}</Text>
        <EtatSection vue={dispo} rendre={v => <>
          <Lignes items={v.lignes} style={styles.avis} />
          {v.articles.map((g, i) => <Groupe key={i} groupe={g} />)}
          <Text style={styles.sousTitre}>{t("admin.stock.reservations")}</Text>
          {v.reservations.map((g, i) => <Groupe key={i} groupe={g} />)}
        </>} />
      </Carte>
      <Carte>
        <Text style={styles.sousTitre}>{t("admin.stock.ecarts")}</Text>
        <EtatSection vue={ecarts} rendre={v => <>
          <Lignes items={v.lignes} style={styles.avis} />
          {v.variances.map((g, i) => <Groupe key={i} groupe={g} />)}
        </>} />
      </Carte>
    </>}
  </ScrollView>;
}
function Groupe({ groupe }: { readonly groupe: GroupeStock }) {
  const { t } = useTranslation();
  return <Carte>
    <Text style={styles.petitTitre}>{groupe.titre ?? t("admin.stock.referenceInconnue")}</Text>
    <Lignes items={groupe.lignes} />
    {groupe.detail.length > 0 ? <Depliant><Lignes items={groupe.detail} /></Depliant> : null}
  </Carte>;
}
