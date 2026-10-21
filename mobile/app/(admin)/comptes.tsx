import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text } from "react-native";
import { useTranslation } from "react-i18next";
import { chargerCreancesM5, chargerComptesAPM5, chargerAttentesFacturationM5 } from "@/admin/service";
import { BoutonSecondaire, Carte, EtatSection, Lignes, stylesAdmin as styles } from "@/admin/composants";
import type { ResultatSection } from "@/admin/lecture";
import { presenterSection } from "@/ecrans/adminCommun";
import { presenterCreances, presenterAP, presenterAttentes } from "@/ecrans/comptes";
import type { VueComptes } from "@/ecrans/comptes";
import type { LangueMontant } from "@/ecrans/quotes";
import type { Creances, Masquee, PageAP, AttentesFacturation } from "@/m5/comptes";
import { BandeauIdentite } from "@/identite/BandeauIdentite";

async function securiser<T>(operation: Promise<ResultatSection<T> | null>): Promise<ResultatSection<T> | null> {
  try { return await operation; } catch {
    return { source: "aucune", raison: { code: "lecture_indisponible", detail: "Lecture momentanément indisponible." } };
  }
}

/** T4.22 : trois lectures indépendantes ; suites remplacées, aucune concaténation ni action financière. */
export default function EcranComptes() {
  const { t, i18n } = useTranslation();
  const langue: LangueMontant = i18n.language === "en-CA" ? "en-CA" : "fr-CA";
  const decalage = -new Date().getTimezoneOffset();
  const [creances, setCreances] = useState<ResultatSection<Creances | Masquee>>();
  const [ap, setAP] = useState<ResultatSection<PageAP | Masquee>>();
  const [attentes, setAttentes] = useState<ResultatSection<AttentesFacturation>>();
  const [sansPO, setSansPO] = useState(false);
  const [sansSession, setSansSession] = useState(false);
  const [enCours, setEnCours] = useState(false);
  const sequence = useRef(0), pageSequence = useRef(0), demande = useRef(false), filtre = useRef(false);
  const charger = useCallback(async () => {
    const n = ++sequence.current;
    const generationAP = ++pageSequence.current;
    demande.current = false; setEnCours(false);
    setCreances(undefined); setAP(undefined); setAttentes(undefined); setSansSession(false);
    const recevoir = <T,>(poser: (v: ResultatSection<T>) => void) => (v: ResultatSection<T> | null) => {
      if (n !== sequence.current) return;
      if (v === null) setSansSession(true); else poser(v);
    };
    await Promise.all([
      securiser(chargerCreancesM5()).then(recevoir(setCreances)),
      securiser(chargerComptesAPM5(filtre.current)).then(v => {
        if (generationAP === pageSequence.current) recevoir(setAP)(v);
      }),
      securiser(chargerAttentesFacturationM5()).then(recevoir(setAttentes)),
    ]);
  }, []);
  useFocusEffect(useCallback(() => {
    void charger();
    return () => { ++sequence.current; ++pageSequence.current; };
  }, [charger]));
  async function page(depart: number, mode = filtre.current) {
    if (demande.current) return;
    demande.current = true; setEnCours(true);
    const n = sequence.current, p = ++pageSequence.current;
    try {
      const v = await securiser(chargerComptesAPM5(mode, depart));
      if (n !== sequence.current || p !== pageSequence.current) return;
      if (v === null) setSansSession(true); else setAP(v);
    } finally {
      if (p === pageSequence.current) { demande.current = false; setEnCours(false); }
    }
  }
  function choisir(mode: boolean) {
    filtre.current = mode; setSansPO(mode); ++pageSequence.current; demande.current = false;
    setAP(undefined); void page(0, mode);
  }
  const vue = <T,>(v: ResultatSection<T> | undefined, presenter: (v: T) => VueComptes) =>
    v ? presenterSection(v, decalage, presenter) : undefined;
  const suite = ap?.source === "serveur" && ap.valeur.genre === "page" ? ap.valeur.prochain_depart : null;
  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("admin.comptes.titre")}</Text>
    <BandeauIdentite />
    <Text style={styles.avis}>{t("admin.comptes.courant")}</Text>
    <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />
    {sansSession ? <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text> : <>
      <Carte>
        <Text style={styles.sousTitre}>{t("admin.comptes.creances")}</Text>
        <EtatSection vue={vue(creances, v => presenterCreances(v, langue, decalage))} rendre={v => <Contenu vue={v} />} />
      </Carte>
      <Carte>
        <Text style={styles.sousTitre}>{t("admin.comptes.ap")}</Text>
        <BoutonSecondaire texte={t(sansPO ? "admin.comptes.voirPO" : "admin.comptes.voirSansPO")}
          onPress={() => choisir(!sansPO)} />
        <EtatSection vue={vue(ap, v => presenterAP(v, langue, decalage))} rendre={v => <Contenu vue={v} />} />
        {suite !== null && suite !== undefined ? <BoutonSecondaire texte={t("admin.comptes.suite")}
          desactive={enCours} onPress={() => void page(suite)} /> : null}
      </Carte>
      <Carte>
        <Text style={styles.sousTitre}>{t("admin.comptes.attentes")}</Text>
        <EtatSection vue={vue(attentes, presenterAttentes)} rendre={v => <Contenu vue={v} />} />
      </Carte>
    </>}
  </ScrollView>;
}
function Contenu({ vue }: { readonly vue: VueComptes }) {
  const { t } = useTranslation();
  return <>
    <Lignes items={vue.lignes} style={styles.trace} />
    {vue.vide ? <Text style={styles.vide}>{t("admin.comptes.vide")}</Text> : null}
    {vue.groupes.map((g, n) => <Carte key={n}>
      <Text style={styles.petitTitre}>{g.titre}</Text><Lignes items={g.lignes} />
    </Carte>)}
  </>;
}
