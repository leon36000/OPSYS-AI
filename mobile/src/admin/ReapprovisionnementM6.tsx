import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { actualiserConnectiviteReapprovisionnementM6, chargerReapprovisionnementM6 } from "./reapprovisionnement";
import type { ReapprovisionnementM6 as LectureReapprovisionnementM6 } from "../m6/reapprovisionnement";
import type { ResultatSection } from "./lecture";
import { presenterSection } from "../ecrans/adminCommun";
import { presenterReapprovisionnementM6 } from "../ecrans/reapprovisionnementM6";
import { BoutonSecondaire, Carte, Depliant, EtatSection, Lignes, stylesAdmin as styles } from "./composants";

const indisponible = () => ({ source: "aucune" as const, raison: { code: "lecture_indisponible", detail: "" } });
export function ReapprovisionnementM6({ connected }: { readonly connected: boolean }) {
  const { t } = useTranslation();
  const session = useSessionAppareil();
  const [lecture, setLecture] = useState<ResultatSection<LectureReapprovisionnementM6>>();
  const [enCours, setEnCours] = useState(false);
  const [, rendreGeneration] = useState(0);
  const generation = useRef(0), focus = useRef(false);
  const garde = useRef<(() => boolean) | null>(null), reseau = useRef(connected);
  reseau.current = connected;
  const captureRendu = capturerSessionAdminLecture(), generationRendu = generation.current;
  const invalider = useCallback(() => {
    ++generation.current; garde.current = null; setLecture(undefined); setEnCours(false);
    rendreGeneration(n => n + 1);
  }, []);
  useFocusEffect(useCallback(() => {
    focus.current = true; invalider();
    return () => { focus.current = false; ++generation.current; garde.current = null; };
  }, [invalider]));
  useEffect(() => {
    actualiserConnectiviteReapprovisionnementM6(connected); invalider();
    return () => { actualiserConnectiviteReapprovisionnementM6(false); ++generation.current; garde.current = null; };
  }, [connected, invalider]);
  useEffect(() => { invalider(); }, [session, invalider]);
  const permis = () => focus.current && reseau.current && captureRendu.session !== null && captureRendu.courante();
  const callbackCourant = () => permis() && generationRendu === generation.current;
  async function lire(decalage = 0) {
    if (!callbackCourant()) return;
    const n = ++generation.current;
    garde.current = captureRendu.courante; setLecture(undefined); setEnCours(true);
    const courante = () => permis() && n === generation.current;
    try {
      const r = await chargerReapprovisionnementM6(decalage);
      if (courante()) setLecture(r?.source === "cache" || r === null ? indisponible() : r);
    } catch { if (courante()) setLecture(indisponible()); }
    finally { if (courante()) setEnCours(false); }
  }
  const visible = connected && captureRendu.courante() && garde.current?.() === true;
  const page = visible && lecture?.source === "serveur" ? lecture.valeur : null;
  const decalage = -new Date().getTimezoneOffset();
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.reapprovisionnement.titre")}</Text>
    <Text style={styles.avis}>{t("admin.reapprovisionnement.note")}</Text>
    <BoutonSecondaire texte={t("admin.reapprovisionnement.lire")} desactive={!permis() || enCours} onPress={() => void lire()} />
    {!connected ? <Text style={styles.avis}>{t("admin.reapprovisionnement.horsLigne")}</Text> : null}
    {visible && enCours ? <ActivityIndicator /> : null}
    {visible && lecture ? <EtatSection vue={presenterSection(lecture, decalage, presenterReapprovisionnementM6)} rendre={v => <>
      <Lignes items={v.lignes} />
      <Depliant><Lignes items={v.sources} /></Depliant>
      {v.articles.map(a => <View key={a.cle}>
        <Text style={styles.petitTitre}>{t(a.titre.cle, a.titre.params)}</Text>
        <Lignes items={a.lignes} />
        <Depliant><Lignes items={a.sources} /></Depliant>
      </View>)}
      {page?.pagination.suivant != null ? <BoutonSecondaire texte={t("admin.reapprovisionnement.suite")}
        desactive={!permis() || enCours} onPress={() => void lire(page.pagination.suivant!)} /> : null}
    </>} /> : null}
  </Carte>;
}
