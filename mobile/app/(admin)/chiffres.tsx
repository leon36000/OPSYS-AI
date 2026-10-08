import { useNetInfo } from "@react-native-community/netinfo";
import { capturerSessionAdminLecture } from "@/protocole/configuration";
import { useEtatIdentite } from "@/roles/contexte";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text } from "react-native";
import { useTranslation } from "react-i18next";

import {
  actualiserConnectiviteChiffres,
  chargerEcheances,
  chargerPrevision,
  chargerSuitePrevision,
  chargerTresorerie,
  chargerVueExecutive,
} from "@/admin/service";
import { BoutonSecondaire, Carte, EtatSection, stylesAdmin as styles } from "@/admin/composants";
import { EcheancesUI, PrevisionUI, TresorerieUI, VueDEnsembleUI } from "@/admin/vuesChiffres";
import type { Message, VueSection } from "@/ecrans/adminCommun";
import {
  decisionSuitePrevision,
  previsionAPoursuivre,
  remplacerPrevision,
  vueEcheances,
  vuePrevision,
  vueTresorerie,
} from "@/ecrans/chiffres";
import type { VueEcheances, VuePrevision, VueTresorerie } from "@/ecrans/chiffres";
import type { LangueMontant } from "@/ecrans/quotes";
import { vueDEnsemble } from "@/ecrans/vueExecutive";
import type { VueVueExecutive } from "@/ecrans/vueExecutive";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import type { EcheancesFiscales, EtatTresorerie, PrevisionLue } from "@/m5/tresorerie";
import type { VueExecutive } from "@/m8/vueExecutive";
import type { ResultatSection } from "@/admin/lecture";

/**
 * « Chiffres » du propriétaire (§9.5 M5 et M8 ; PLAN T4.20) : la trésorerie et le cash libre (`m5_etat_tresorerie`), la
 * prévision (`m5_prevoir_tresorerie`), les échéances fiscales (`m5_lire_echeances_fiscales`) et la vue d'ensemble de M8
 * (`m8_lire_vue_executive`). Chaque section est lue POUR ELLE-MÊME et s'affiche dès qu'elle arrive : une section lente,
 * refusée ou « à configurer » ne cache pas les trois autres.
 *
 * Aucun montant, pourcentage ni date n'est calculé ici : chaque chiffre est un texte du serveur mis en forme. Un « non
 * calculable » ou un « à configurer » est dit avec ce qui manque, jamais un zéro ; la mention « Analyse préparatoire IA »
 * de M5 est montrée avec la donnée ; un refus du serveur n'est jamais remplacé par une copie gardée (une copie est marquée
 * avec sa date et sa raison). Toute la logique est dans `src/ecrans/chiffres.ts`, `vueExecutive.ts` et `src/admin/`, testée
 * là ; ce fichier n'est que le câblage React (non couvert en rendu, même limite que les autres écrans).
 */
type Chargement<T> = { readonly genre: "chargement" } | { readonly genre: "pret"; readonly lu: ResultatSection<T> };

const EN_CHARGEMENT = { genre: "chargement" } as const;

export default function EcranChiffres() {
  const { t, i18n } = useTranslation();
  const identite = useEtatIdentite(), connectee = useNetInfo().isConnected === true;
  const garde = useRef<(() => boolean) | null>(null);
  const langue: LangueMontant = i18n.language === "en-CA" ? "en-CA" : "fr-CA";
  const decalage = -new Date().getTimezoneOffset();

  const [sansSession, setSansSession] = useState(false);
  const [tresorerie, setTresorerie] = useState<Chargement<EtatTresorerie>>(EN_CHARGEMENT);
  const [prevision, setPrevision] = useState<Chargement<PrevisionLue>>(EN_CHARGEMENT);
  const [echeances, setEcheances] = useState<Chargement<EcheancesFiscales>>(EN_CHARGEMENT);
  const [vue, setVue] = useState<Chargement<VueExecutive>>(EN_CHARGEMENT);
  const [suiteEnCours, setSuiteEnCours] = useState(false);
  const [avisSuite, setAvisSuite] = useState<Message | null>(null);
  const sequence = useRef(0);

  const charger = useCallback(async () => {
    const numero = ++sequence.current, capture = capturerSessionAdminLecture();
    garde.current = capture.session ? capture.courante : null;
    actualiserConnectiviteChiffres(connectee);
    setAvisSuite(null); setSuiteEnCours(false);
    setTresorerie(EN_CHARGEMENT); setPrevision(EN_CHARGEMENT); setEcheances(EN_CHARGEMENT); setVue(EN_CHARGEMENT);
    setSansSession(!capture.session || !capture.courante());
    if (!capture.session || !capture.courante()) return;
    // Chaque section arrive à son rythme ; une lecture qui n'est plus la dernière demandée est ignorée.
    const arrivee =
      <T,>(poser: (etat: Chargement<T>) => void) =>
      (lu: ResultatSection<T> | null) => {
        if (numero !== sequence.current || garde.current?.() !== true) {
          return;
        }
        if (lu === null) {
          setSansSession(true);
          return;
        }
        setSansSession(false);
        poser({ genre: "pret", lu });
      };
    await Promise.all([
      chargerTresorerie().then(arrivee(setTresorerie)).catch(() => arrivee(setTresorerie)({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } })),
      chargerPrevision().then(arrivee(setPrevision)).catch(() => arrivee(setPrevision)({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } })),
      chargerEcheances().then(arrivee(setEcheances)).catch(() => arrivee(setEcheances)({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } })),
      chargerVueExecutive().then(arrivee(setVue)).catch(() => arrivee(setVue)({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } })),
    ]);
  }, [connectee]);

  useFocusEffect(
    useCallback(() => {
      void charger();
      return () => { ++sequence.current; garde.current = null; };
    }, [charger, identite]),
  );

  const voirPlus = useCallback(async () => {
    if (!connectee || garde.current?.() !== true || prevision.genre !== "pret") {
      return;
    }
    const aPoursuivre = previsionAPoursuivre(prevision.lu);
    if (aPoursuivre === null) {
      return;
    }
    const numero = sequence.current;
    setSuiteEnCours(true);
    setAvisSuite(null);
    try {
      const suite = await chargerSuitePrevision(aPoursuivre);
      if (numero !== sequence.current || garde.current?.() !== true) {
        // Un rafraîchissement est passé entre-temps : ces semaines ne se recollent pas à une autre lecture.
        return;
      }
      if (suite === null) {
        setSansSession(true);
        return;
      }
      const decision = decisionSuitePrevision(suite);
      if (decision.genre === "remplacer") {
        setPrevision({ genre: "pret", lu: remplacerPrevision(prevision.lu, decision.prevision) });
      } else if (decision.genre === "relire") {
        setAvisSuite(decision.avis);
        const relue = await chargerPrevision();
        if (numero === sequence.current && garde.current?.() === true && relue !== null) {
          setPrevision({ genre: "pret", lu: relue });
        }
      } else if (decision.genre === "avis") {
        setAvisSuite(decision.avis);
      }
    } finally {
      if (numero === sequence.current && garde.current?.() === true) setSuiteEnCours(false);
    }
  }, [prevision, connectee]);

  const vueTres: VueSection<VueTresorerie> | undefined =
    tresorerie.genre === "pret" ? vueTresorerie(tresorerie.lu, langue, decalage) : undefined;
  const vuePrev: VueSection<VuePrevision> | undefined =
    prevision.genre === "pret" ? vuePrevision(prevision.lu, langue, decalage) : undefined;
  const vueEch: VueSection<VueEcheances> | undefined =
    echeances.genre === "pret" ? vueEcheances(echeances.lu, langue, decalage) : undefined;
  const vueEns: VueSection<VueVueExecutive> | undefined = vue.genre === "pret" ? vueDEnsemble(vue.lu, langue, decalage) : undefined;
  const peutVoirPlus = prevision.genre === "pret" && previsionAPoursuivre(prevision.lu) !== null;

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("admin.chiffres.titre")}</Text>
      <BandeauIdentite />
      <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />
      {sansSession || garde.current?.() !== true ? (
        <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text>
      ) : (
        <>
          <Carte>
            <Text style={styles.sousTitre}>{t("admin.chiffres.sections.tresorerie")}</Text>
            <EtatSection vue={vueTres} rendre={(contenu) => <TresorerieUI vue={contenu} />} />
          </Carte>

          <Carte>
            <Text style={styles.sousTitre}>{t("admin.chiffres.sections.prevision")}</Text>
            <EtatSection
              vue={vuePrev}
              rendre={(contenu) => (
                <PrevisionUI
                  vue={contenu}
                  peutVoirPlus={peutVoirPlus}
                  suiteEnCours={suiteEnCours}
                  avisSuite={avisSuite}
                  onVoirPlus={() => void voirPlus()}
                />
              )}
            />
          </Carte>

          <Carte>
            <Text style={styles.sousTitre}>{t("admin.chiffres.sections.echeances")}</Text>
            <EtatSection vue={vueEch} rendre={(contenu) => <EcheancesUI vue={contenu} />} />
          </Carte>

          <Carte>
            <Text style={styles.sousTitre}>{t("admin.chiffres.sections.vue")}</Text>
            <EtatSection vue={vueEns} rendre={(contenu) => <VueDEnsembleUI vue={contenu} />} />
          </Carte>
        </>
      )}
    </ScrollView>
  );
}
