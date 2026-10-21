import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { Link } from "expo-router";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { BoutonSecondaire, Carte, stylesAdmin as styles } from "./composants";
import type { ResultatSection } from "./lecture";
import type { PageRappelsM1, RappelAppareilM1 } from "../m1/rappelsAppareil";
import { actualiserConnectiviteRappelsM1, chargerRappelsM1, lireIntentionRappelM1, soumettrePriseRappelM1, reprendrePriseRappelM1 } from "./rappelsM1";
import type { EtatIntentionRappelM1 } from "./rappelsM1";

/** Sélection humaine de rappels importés ; pages courantes, aucune copie de contact persistée. */
export function RappelsM1({ connected, autorisee }: { readonly connected: boolean; readonly autorisee: () => boolean }) {
  const { t } = useTranslation(), session = useSessionAppareil();
  const [page, setPage] = useState<ResultatSection<PageRappelsM1>>(), [selection, setSelection] = useState<string | null>(null);
  const [intention, setIntention] = useState<EtatIntentionRappelM1>(), [occupe, setOccupe] = useState(false);
  const [, rendre] = useState(0), generation = useRef(0), busy = useRef(false), garde = useRef<(() => boolean) | null>(null);
  const entree = useRef({ connected, autorisee }); entree.current = { connected, autorisee };
  const capture = capturerSessionAdminLecture(), rendu = generation.current;
  const autorite = () => entree.current.autorisee() && capture.session !== null && capture.courante();
  const permis = () => autorite() && entree.current.connected;
  const callbackCourant = () => permis() && rendu === generation.current;
  useEffect(() => {
    actualiserConnectiviteRappelsM1(connected); ++generation.current; garde.current = null; busy.current = false;
    setPage(undefined); setIntention(undefined); setOccupe(false); rendre(n => n + 1);
    return () => { ++generation.current; garde.current = null; };
  }, [connected]);
  useEffect(() => {
    ++generation.current; garde.current = null; busy.current = false; setPage(undefined); setIntention(undefined);
    setSelection(null); setOccupe(false); rendre(n => n + 1);
  }, [session]);
  useEffect(() => () => { actualiserConnectiviteRappelsM1(false); }, []);
  function commencer() {
    const n = ++generation.current; busy.current = true; garde.current = capture.courante; setOccupe(true); rendre(v => v + 1);
    return () => permis() && n === generation.current;
  }
  function finir(courante: () => boolean) { if (courante()) { busy.current = false; setOccupe(false); } }
  async function charger(apres: string | null = null) {
    if (!callbackCourant() || busy.current) return;
    const courante = commencer(); setPage(undefined); setSelection(null); setIntention(undefined);
    try {
      const r = await chargerRappelsM1(apres, 8);
      if (courante()) setPage(r ?? { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
    } catch { if (courante()) setPage({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } }); }
    finally { finir(courante); }
  }
  const visible = permis() && garde.current?.() === true;
  const valeur = visible && page?.source === "serveur" ? page.valeur : null;
  const choisie = valeur?.rappels.find(r => r.transfert_id === selection) ?? null;
  async function choisir(row: RappelAppareilM1) {
    if (!callbackCourant() || busy.current || !valeur?.rappels.includes(row)) return;
    const courante = commencer(); setSelection(row.transfert_id); setIntention(undefined);
    try { const i = await lireIntentionRappelM1(row.transfert_id); if (courante()) setIntention(i); }
    catch { if (courante()) setIntention({ genre: "indisponible" }); }
    finally { finir(courante); }
  }
  const bloquee = intention?.genre === "en_attente" || intention?.genre === "quarantaine" || intention?.genre === "indisponible" || !intention;
  async function prendre() {
    if (!callbackCourant() || busy.current || !choisie || choisie.suivi_rappel.responsable !== null || bloquee) return;
    const args = { transfert_id: choisie.transfert_id, snapshot_attendu: choisie.suivi_rappel.snapshot_suivi };
    const courante = commencer();
    try {
      const r = await soumettrePriseRappelM1(args, courante); if (!courante()) return;
      setIntention(r); if (r.genre === "confirmee" || r.genre === "refusee") setPage(undefined);
    } catch { if (courante()) setIntention({ genre: "indisponible" }); }
    finally { finir(courante); }
  }
  async function reprendre() {
    if (!callbackCourant() || busy.current || !selection || intention?.genre !== "en_attente") return;
    const courante = commencer();
    try {
      const r = await reprendrePriseRappelM1(selection, courante); if (!courante()) return;
      setIntention(r); if (r.genre === "confirmee" || r.genre === "refusee") setPage(undefined);
    } catch { if (courante()) setIntention({ genre: "indisponible" }); }
    finally { finir(courante); }
  }
  const probleme = visible && page && page.source !== "serveur" ? page.source === "refus" ? page.verdict : page.source === "aucune" ? page.raison : null : null;
  const inconnu = t("admin.rappelsM1.inconnu");
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.rappelsM1.titre")}</Text>
    <Text style={styles.avis}>{t("admin.rappelsM1.note")}</Text>
    {!connected ? <Text>{t("admin.rappelsM1.horsLigne")}</Text> : null}
    <BoutonSecondaire texte={t("admin.rappelsM1.lire")} desactive={!permis() || occupe} onPress={() => void charger()} />
    {autorite() && occupe ? <ActivityIndicator /> : null}
    {probleme ? <Text accessibilityRole="alert">{probleme.code} · {probleme.detail}</Text> : null}
    {valeur ? <>
      <Text>{t("admin.rappelsM1.pagesCourantes")}</Text>
      <Text>{t("admin.rappelsM1.page", { nombre: valeur.page.retournes, total: valeur.page.total, reste: valeur.page.reste })}</Text>
      {!valeur.rappels.length ? <Text>{t("admin.rappelsM1.vide")}</Text> : null}
      {valeur.rappels.map(r => <View key={r.transfert_id} style={{ gap: 8 }}>
        <Text selectable>{r.transfert_id}</Text><Text>{r.ouvert_le}</Text>
        <Text>{t(`admin.rappelsM1.${r.derniere_source.statut}`)} · {r.derniere_source.recu_le}</Text>
        <Text selectable>{r.derniere_source.ligne_id}</Text>
        <Text>{t("admin.rappelsM1.sources", { nombre: r.nombre_sources })}</Text>
        <Text>{t("admin.rappelsM1.responsable", { personne: r.suivi_rappel.responsable ?? inconnu })}</Text>
        <Text>{t("admin.rappelsM1.lead", { id: r.lead_id ?? inconnu })}</Text>
        <Text>{t("admin.rappelsM1.prochaine", { date: r.suivi_rappel.prochaine_tentative_le ?? inconnu })}</Text>
        <Link href={{ pathname: "/(admin)/reception", params: { transfert: r.transfert_id } }} style={styles.lien}>{t("admin.rappelsM1.fiche")}</Link>
        <BoutonSecondaire texte={t("admin.rappelsM1.choisir")} desactive={!callbackCourant() || occupe} onPress={() => void choisir(r)} />
      </View>)}
      {valeur.page.apres_suivant !== null ? <BoutonSecondaire texte={t("admin.rappelsM1.suite")} desactive={!callbackCourant() || occupe} onPress={() => void charger(valeur.page.apres_suivant)} /> : null}
    </> : null}
    {choisie ? <>
      <Text>{choisie.transfert_id}</Text>
      <BoutonSecondaire texte={t("admin.rappelsM1.prendre")} desactive={!callbackCourant() || occupe || bloquee || choisie.suivi_rappel.responsable !== null} onPress={() => void prendre()} />
    </> : null}
    {autorite() && intention && intention.genre !== "aucune" ? <Text>{t(`admin.rappelsM1.${intention.genre === "en_attente" ? "enAttente" : intention.genre === "confirmee" ? "confirmee" : intention.genre === "refusee" ? "refusee" : intention.genre === "quarantaine" ? "quarantaine" : "indisponible"}`)}</Text> : null}
    {autorite() && intention?.genre === "en_attente" ? <BoutonSecondaire texte={t("admin.rappelsM1.reprendre")} desactive={!callbackCourant() || occupe} onPress={() => void reprendre()} /> : null}
  </Carte>;
}
