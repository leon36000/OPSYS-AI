import { Link, useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { chargerAVoir } from "@/admin/service";
import { BoutonSecondaire, Carte, EtatSection, Ligne, stylesAdmin as styles } from "@/admin/composants";
import type { VueSection } from "@/ecrans/adminCommun";
import { vueAccueil } from "@/ecrans/admin";
import type { VueAVoir } from "@/ecrans/admin";
import { BandeauIdentite } from "@/identite/BandeauIdentite";

/**
 * Accueil du propriétaire, « À voir » (§9.5 « Approbations » et alertes ; PLAN T4.20) : les demandes d'approbation en
 * attente et les attentes des départements que `m9_lister_demandes_approbation` rend, avec le lien vers l'écran des
 * approbations (`approvals.tsx`, PLAN T1.4-f), où l'on décide, et vers « Chiffres » et « Chantiers du jour ».
 *
 * L'accueil ne décide de rien : aucun bouton d'approbation, ni arguments, ni motif à l'écran. Lecture d'abord, cache
 * SQLite hors ligne marqué (date, raison) ; un refus du serveur est dit et n'est jamais remplacé par une copie. Toute la
 * logique est dans `src/ecrans/admin.ts` et `src/admin/`, testée là ; ce fichier n'est que le câblage React (non couvert
 * en rendu, même limite que les autres écrans). La liste est relue chaque fois que l'écran reprend le focus (retour de
 * l'écran des approbations, où une demande vient peut-être d'être décidée).
 */
type Etat =
  | { readonly genre: "chargement" }
  | { readonly genre: "sans_session" }
  | { readonly genre: "pret"; readonly vue: VueSection<VueAVoir> };

export default function AccueilAdmin() {
  const { t } = useTranslation();
  const [etat, setEtat] = useState<Etat>({ genre: "chargement" });
  const sequence = useRef(0);

  const charger = useCallback(async () => {
    const numero = ++sequence.current;
    setEtat((precedent) => (precedent.genre === "pret" ? precedent : { genre: "chargement" }));
    const lu = await chargerAVoir();
    if (numero !== sequence.current) {
      return;
    }
    const decalage = -new Date().getTimezoneOffset();
    setEtat(lu === null ? { genre: "sans_session" } : { genre: "pret", vue: vueAccueil(lu, decalage) });
  }, []);

  useFocusEffect(
    useCallback(() => {
      void charger();
    }, [charger]),
  );

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("admin.aVoir.titre")}</Text>
      <BandeauIdentite />
      <Text style={styles.trace}>{t("admin.aVoir.aucuneDecision")}</Text>
      <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />

      {etat.genre === "sans_session" ? (
        <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text>
      ) : (
        <EtatSection vue={etat.genre === "pret" ? etat.vue : undefined} rendre={(vue) => <ContenuAVoir vue={vue} />} />
      )}

      <View style={{ gap: 12 }}>
        <Link href="/approvals" style={styles.lien}>
          {t("admin.aVoir.liens.approbations")}
        </Link>
        <Link href="/chiffres" style={styles.lien}>
          {t("admin.aVoir.liens.chiffres")}
        </Link>
        <Link href="/chantiers" style={styles.lien}>
          {t("admin.aVoir.liens.chantiers")}
        </Link>
      </View>
    </ScrollView>
  );
}

function ContenuAVoir({ vue }: { readonly vue: VueAVoir }) {
  const { t } = useTranslation();
  return (
    <View style={{ gap: 12 }}>
      {vue.rienAVoir ? <Text style={styles.meta}>{t("admin.aVoir.rienAVoir")}</Text> : null}

      <Text style={styles.sousTitre}>{t("admin.aVoir.demandes.titre")}</Text>
      <Ligne m={vue.totalEnAttente} style={styles.meta} />
      {vue.demandes.length === 0 ? <Text style={styles.vide}>{t("admin.aVoir.demandes.aucune")}</Text> : null}
      {vue.demandes.map((demande) => (
        <Carte key={demande.id}>
          <Text style={styles.petitTitre}>{demande.outil}</Text>
          <Ligne m={demande.departement} style={styles.meta} />
          <Ligne m={demande.niveau} style={styles.meta} />
          <Ligne m={demande.depuis} style={styles.trace} />
        </Carte>
      ))}
      {vue.resteDemandes !== null ? <Ligne m={vue.resteDemandes} style={styles.avis} /> : null}
      {vue.illisibles !== null ? <Ligne m={vue.illisibles} style={styles.avis} /> : null}
      {!vue.proprietaire ? <Text style={styles.avis}>{t("approvals.lectureSeuleProprietaire")}</Text> : null}

      <Text style={styles.sousTitre}>{t("admin.aVoir.attentes.titre")}</Text>
      {vue.attentes.genre === "inconnues" ? <Text style={styles.avis}>{t("admin.aVoir.attentes.inconnues")}</Text> : null}
      {vue.attentes.genre === "aucune" ? <Text style={styles.vide}>{t("admin.aVoir.attentes.aucune")}</Text> : null}
      {vue.attentes.genre === "presentes" ? (
        <>
          <Text style={styles.trace}>{t("approvals.attentes.informatif")}</Text>
          {vue.attentes.items.map((attente) => (
            <Carte key={attente.cle}>
              <Text style={styles.petitTitre}>{attente.resume}</Text>
              <Ligne m={attente.departement} style={styles.meta} />
              <Ligne m={attente.niveau} style={styles.meta} />
              <Ligne m={attente.depuis} style={styles.trace} />
              {attente.geste !== null ? <Ligne m={attente.geste} style={styles.avis} /> : null}
            </Carte>
          ))}
          {vue.attentes.reste !== null ? <Ligne m={vue.attentes.reste} style={styles.avis} /> : null}
          {vue.attentes.illisibles !== null ? <Ligne m={vue.attentes.illisibles} style={styles.avis} /> : null}
          {vue.attentes.departementsIllisibles !== null ? <Ligne m={vue.attentes.departementsIllisibles} style={styles.avis} /> : null}
        </>
      ) : null}
    </View>
  );
}
