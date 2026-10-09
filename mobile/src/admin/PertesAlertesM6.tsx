import { ClassementVariancesM6 } from "./ClassementVariancesM6";
import { PreuvesMateriauxM6 } from './PreuvesMateriauxM6';
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { actualiserConnectivitePertesM6, chargerPertesAlertesWctM6, chargerWctsPertesM6 } from "./pertesAlertes";
import type { ListeWctPertesM6, PertesAlertesWctM6, WctPertesM6 } from "../m6/pertesAlertes";
import type { ResultatSection } from "./lecture";
import { presenterSection } from "../ecrans/adminCommun";
import { presenterListeWctPertes, presenterPertesAlertesWct } from "../ecrans/pertesAlertesM6";
import { BoutonSecondaire, Carte, EtatSection, Lignes, stylesAdmin as styles } from "./composants";

const indisponible = () => ({ source: "aucune" as const, raison: { code: "lecture_indisponible", detail: "" } });
export function PertesAlertesM6({ connected }: { readonly connected: boolean }) {
  const { t } = useTranslation();
  const session = useSessionAppareil();
  const [liste, setListe] = useState<ResultatSection<ListeWctPertesM6>>();
  const [detail, setDetail] = useState<ResultatSection<PertesAlertesWctM6>>();
  const [selection, setSelection] = useState<WctPertesM6 | null>(null);
  const [enCours, setEnCours] = useState<"liste" | "detail" | null>(null);
  const [, rendreGeneration] = useState(0);
  const generation = useRef(0), focus = useRef(false);
  const gardeListe = useRef<(() => boolean) | null>(null), gardeDetail = useRef<(() => boolean) | null>(null);
  const reseau = useRef(connected); reseau.current = connected;
  const captureRendu = capturerSessionAdminLecture(), generationRendu = generation.current;
  const invalider = useCallback(() => {
    ++generation.current; gardeListe.current = null; gardeDetail.current = null;
    setListe(undefined); setDetail(undefined); setSelection(null); setEnCours(null);
    rendreGeneration(n => n + 1);
  }, []);
  useFocusEffect(useCallback(() => {
    focus.current = true; invalider();
    return () => { focus.current = false; ++generation.current; gardeListe.current = null; gardeDetail.current = null; };
  }, [invalider]));
  useEffect(() => {
    actualiserConnectivitePertesM6(connected); invalider();
    return () => { actualiserConnectivitePertesM6(false); ++generation.current; gardeListe.current = null; gardeDetail.current = null; };
  }, [connected, invalider]);
  useEffect(() => { invalider(); }, [session, invalider]);
  const permis = () => focus.current && reseau.current && captureRendu.session !== null && captureRendu.courante();
  const callbackCourant = () => permis() && generationRendu === generation.current;
  async function lister(decalage = 0) {
    if (!callbackCourant()) return;
    const n = ++generation.current;
    gardeListe.current = captureRendu.courante; gardeDetail.current = null;
    setListe(undefined); setDetail(undefined); setSelection(null); setEnCours("liste");
    const courante = () => permis() && n === generation.current;
    try {
      const r = await chargerWctsPertesM6(decalage);
      if (courante()) setListe(r?.source === "cache" || r === null ? indisponible() : r);
    } catch { if (courante()) setListe(indisponible()); }
    finally { if (courante()) setEnCours(null); }
  }
  async function lire(wct: WctPertesM6, decalage = 0) {
    if (!callbackCourant() || gardeListe.current?.() !== true) return;
    const n = ++generation.current;
    gardeDetail.current = captureRendu.courante;
    setDetail(undefined); setSelection(wct); setEnCours("detail");
    const courante = () => permis() && n === generation.current;
    try {
      const r = await chargerPertesAlertesWctM6(wct.wct_id, decalage);
      if (courante()) {
        if (r?.source === "refus") { gardeListe.current = null; setListe(undefined); setSelection(null); }
        setDetail(r?.source === "cache" || r === null ? indisponible() : r);
      }
    } catch { if (courante()) setDetail(indisponible()); }
    finally { if (courante()) setEnCours(null); }
  }
  const listeVisible = connected && captureRendu.courante() && gardeListe.current?.() === true;
  const detailVisible = connected && captureRendu.courante() && gardeDetail.current?.() === true;
  const pageListe = listeVisible && liste?.source === "serveur" ? liste.valeur : null;
  const pageDetail = detailVisible && detail?.source === "serveur" ? detail.valeur : null;
  const decalage = -new Date().getTimezoneOffset();
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.pertesAlertes.titre")}</Text>
    <Text style={styles.avis}>{t("admin.pertesAlertes.note")}</Text>
    <BoutonSecondaire texte={t("admin.pertesAlertes.lister")} desactive={!permis() || enCours === "liste"} onPress={() => void lister()} />
    {!connected ? <Text style={styles.avis}>{t("admin.pertesAlertes.horsLigne")}</Text> : null}
    {(listeVisible || detailVisible) && enCours ? <ActivityIndicator /> : null}
    {listeVisible && liste ? <EtatSection vue={presenterSection(liste, decalage, presenterListeWctPertes)} rendre={v => <>
      <Lignes items={v.lignes} />
      {v.wcts.map(w => <View key={w.wct.wct_id}>
        <Lignes items={[w.titre, ...w.lignes]} />
        <BoutonSecondaire texte={t("admin.pertesAlertes.choisir")} desactive={!permis()} onPress={() => void lire(w.wct)} />
      </View>)}
      {pageListe?.pagination.suivant != null ? <BoutonSecondaire texte={t("admin.pertesAlertes.suiteListe")}
        desactive={!permis()} onPress={() => void lister(pageListe.pagination.suivant!)} /> : null}
    </>} /> : null}
    {detailVisible && detail ? <EtatSection vue={presenterSection(detail, decalage, presenterPertesAlertesWct)} rendre={v => <>
      <Lignes items={v.lignes} />
      {v.mouvements.map(m => <View key={m.cle}><Lignes items={m.lignes} /></View>)}
      <Text style={styles.petitTitre}>{t("admin.pertesAlertes.historique")}</Text>
      {v.historique.map(h => <View key={h.cle}><Lignes items={h.lignes} /></View>)}
      {pageDetail?.pagination.suivant != null && selection ? <BoutonSecondaire texte={t("admin.pertesAlertes.suiteDetail")}
        desactive={!permis()} onPress={() => void lire(selection, pageDetail.pagination.suivant!)} /> : null}
    </>} /> : null}
    <ClassementVariancesM6 wctId={pageDetail && selection ? selection.wct_id : null} connected={connected}
      autorisee={() => focus.current && reseau.current && captureRendu.courante() && gardeDetail.current?.() === true}
      surRefus={invalider} />
    {pageDetail && selection ? <PreuvesMateriauxM6 key={selection.wct_id} wctId={selection.wct_id}
      connected={connected} surRefus={invalider} /> : null}
  </Carte>;
}
