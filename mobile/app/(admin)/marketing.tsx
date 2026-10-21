import { useCallback, useEffect, useRef, useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";
import { useTranslation } from "react-i18next";
import { controleMarketing } from "@/m7/service";
import { chargerFileMarketing, chargerDemandesAvisMarketing } from "@/m7/lecturesAdminService";
import type { PropositionHistoriqueM7, DemandeAvisM7 } from "@/m7/lecturesAdmin";
import type { LigneContenuM7 } from "@/m7/contrat";
import type { ResultatSection } from "@/admin/lecture";
import { BoutonSecondaire, Carte, EtatSection, stylesAdmin as styles } from "@/admin/composants";
import { presenterSection } from "@/ecrans/adminCommun";
import { capturerSessionLecture } from "@/protocole/configuration";
import { useSessionAppareil } from "@/roles/contexte";
import { BandeauIdentite } from "@/identite/BandeauIdentite";

type Avis = { readonly total: number; readonly demandes: readonly DemandeAvisM7[]; readonly reste: number };
async function securiser<T>(operation: Promise<ResultatSection<T> | null>): Promise<ResultatSection<T> | null> {
  try { return await operation; } catch {
    return { source: "aucune", raison: { code: "lecture_indisponible", detail: "Lecture momentanément indisponible." } };
  }
}

/** Three native objects; only stored job content can create a durable decision intention. */
export default function MarketingAdmin() {
  const { t } = useTranslation();
  const session = useSessionAppareil();
  const connected = useNetInfo().isConnected === true;
  const [, render] = useState(0);
  const [motifs, setMotifs] = useState(() => new Map<string, string>());
  const [file, setFile] = useState<ResultatSection<readonly PropositionHistoriqueM7[]>>();
  const [avis, setAvis] = useState<ResultatSection<Avis>>();
  const [sansSession, setSansSession] = useState(false);
  const [erreurAction, setErreurAction] = useState(false);
  const sequence = useRef(0);
  const garde = useRef<(() => boolean) | null>(null);
  const refresh = () => render(value => value + 1);
  useEffect(() => { controleMarketing.actualiserConnectivite(connected); refresh(); }, [connected]);

  const charger = useCallback(async () => {
    if (controleMarketing.etat().statut === "decision_en_cours") return;
    const n = ++sequence.current;
    const capture = capturerSessionLecture();
    garde.current = capture.courante;
    setFile(undefined); setAvis(undefined); setSansSession(!capture.session); setErreurAction(false);
    const courant = () => n === sequence.current && capture.courante();
    const recevoir = <T,>(poser: (v: ResultatSection<T>) => void) => (v: ResultatSection<T> | null) => {
      if (!courant()) return;
      if (v === null) setSansSession(true); else poser(v);
    };
    if (!connected) {
      const indisponible = { source: "aucune" as const, raison: { code: "hors_ligne", detail: t("admin.marketing.connexion") } };
      setFile(indisponible); setAvis(indisponible);
      await controleMarketing.charger();
      if (courant()) refresh();
      return;
    }
    const durable = controleMarketing.charger(); refresh();
    await Promise.all([
      durable.catch(() => { if (courant()) { controleMarketing.invalider(); setErreurAction(true); } }).then(() => { if (courant()) refresh(); }),
      securiser(chargerFileMarketing()).then(recevoir(setFile)),
      securiser(chargerDemandesAvisMarketing()).then(recevoir(setAvis)),
    ]);
  }, [connected, t]);
  useFocusEffect(useCallback(() => {
    setMotifs(new Map()); void charger();
    return () => { ++sequence.current; garde.current = null; controleMarketing.invalider(); };
  }, [charger, session, connected]));

  async function decider(item: LigneContenuM7, decision: "approuver" | "rejeter") {
    const n = sequence.current;
    try {
      const pending = controleMarketing.decider(item.contenu_id, decision, motifs.get(item.contenu_id) ?? "");
      refresh(); await pending;
    } catch { if (n === sequence.current) setErreurAction(true); }
    if (n === sequence.current) refresh();
  }
  async function suite() {
    const n = sequence.current;
    const pending = controleMarketing.chargerSuite(); refresh();
    try { await pending; } catch { if (n === sequence.current) setErreurAction(true); }
    if (n === sequence.current) refresh();
  }
  const state = controleMarketing.etat();
  const visible = garde.current?.() === true;
  const decalage = -new Date().getTimezoneOffset();
  const vueFile = visible && file ? presenterSection(file, decalage, v => v) : undefined;
  const vueAvis = visible && avis ? presenterSection(avis, decalage, v => v) : undefined;
  const inconnu = t("admin.marketing.inconnue");
  const statut = (v: LigneContenuM7["approval_status"]) => t(`admin.marketing.statuts.${v}`);

  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("admin.marketing.titre")}</Text><BandeauIdentite />
    <Text style={styles.avis}>{t("admin.marketing.note")}</Text>
    <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />
    {sansSession ? <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text> : null}
    {!connected ? <Text style={styles.avis}>{t("admin.marketing.connexion")}</Text> : null}
    {erreurAction ? <Text style={styles.erreur}>{t("admin.marketing.erreurAction")}</Text> : null}
    <Carte>
      <Text style={styles.sousTitre}>{t("admin.marketing.contenus")}</Text>
      <Text style={styles.avis}>{t("admin.marketing.pagesCourantes")}</Text>
      {!visible || state.statut === "chargement" || state.statut === "decision_en_cours" ? <Text>{t("admin.marketing.chargement")}</Text> : null}
      {visible && state.message ? <Text accessibilityRole="alert" style={styles.erreur}>{state.codeMessage ? t(`admin.marketing.messages.${state.codeMessage}`) : state.message}</Text> : null}
      {visible && state.sourceDate ? <Text style={styles.avis}>{t("admin.marketing.sourceDate", { date: state.sourceDate })}</Text> : null}
      {visible && !state.owner && state.statut === "pret" ? <Text style={styles.avis}>{t("admin.marketing.lectureSeule")}</Text> : null}
      {visible && state.statut === "pret" && state.items.length === 0 ? <Text>{t("admin.marketing.vide")}</Text> : null}
      {visible && state.items.map(item => <Carte key={item.contenu_id}>
        <Text style={styles.petitTitre}>{t("admin.marketing.revision", { plateforme: item.plateforme, statut: statut(item.approval_status), revision: item.revision })}</Text>
        <Text>{t("admin.marketing.chantier", { reference: item.wct_id })}</Text><Text>{item.texte}</Text>
        <Text>{t("admin.marketing.motsClics", { texte: item.mots_clics.length > 0 ? item.mots_clics.join(" ") : inconnu })}</Text>
        <Text>{t("admin.marketing.lien", { texte: item.lien_utm ?? inconnu })}</Text>
        <Text>{t("admin.marketing.origine", { texte: item.origine_texte })}</Text>
        <Text>{t("admin.marketing.consentement", { personne: item.consentement.recueilli_par, date: item.consentement.recueilli_le, version: item.consentement.version_texte })}</Text>
        <Text>{t("admin.marketing.marque", { source: item.marque_source ? t(`admin.marketing.sources.${item.marque_source.source}`) : inconnu, fraicheur: t(`admin.marketing.fraicheurs.${item.fraicheur_marque}`) })}</Text>
        {item.avertissements.map((v, i) => <Text key={i} style={styles.avis}>{v}</Text>)}
        {controleMarketing.peutDecider(item) ? <View>
          <TextInput accessibilityLabel={`${t("admin.marketing.motif")} ${item.contenu_id}`} maxLength={500}
            value={motifs.get(item.contenu_id) ?? ""} placeholder={t("admin.marketing.motif")}
            onChangeText={value => setMotifs(current => new Map(current).set(item.contenu_id, value))} />
          <BoutonSecondaire texte={t("admin.marketing.approuver")} onPress={() => void decider(item, "approuver")} />
          <BoutonSecondaire texte={t("admin.marketing.rejeter")} onPress={() => void decider(item, "rejeter")} />
        </View> : null}
      </Carte>)}
      {visible && state.suivant !== null ? <BoutonSecondaire texte={t("admin.marketing.suite")} onPress={() => void suite()} /> : null}
      {visible && state.intentions.length > 0 ? <>
        <Text style={styles.sousTitre}>{t("admin.marketing.intentions")}</Text><Text style={styles.avis}>{t("admin.marketing.attente")}</Text>
        {state.intentions.map(item => <Text key={item.id}>{t("admin.marketing.intention", { reference: item.contenuId ?? inconnu,
          decision: item.decision ? t(`admin.marketing.decisions.${item.decision}`) : inconnu,
          statut: t(`admin.marketing.etatsFile.${item.statut}`), personne: item.personne ?? inconnu })}</Text>)}
      </> : null}
    </Carte>
    <Carte><Text style={styles.sousTitre}>{t("admin.marketing.historique")}</Text><Text style={styles.avis}>{t("admin.marketing.volatil")}</Text>
      <EtatSection vue={vueFile} rendre={items => <>
        {items.length === 0 ? <Text>{t("admin.marketing.vide")}</Text> : null}
        {items.map(item => <Carte key={item.id}>
          <Text style={styles.petitTitre}>{item.title}</Text><Text>{item.body}</Text>
          <Text>{t("admin.marketing.proposition", { surface: t(`admin.marketing.surfaces.${item.surface}`), type: t(`admin.marketing.types.${item.type}`), statut: statut(item.approval_status) })}</Text>
          <Text>{t("admin.marketing.proposeLe", { personne: item.proposer, date: item.propose_timestamp })}</Text>
          <Text>{t("admin.marketing.approuveLe", { personne: item.approver || inconnu, date: item.approval_timestamp || inconnu})}</Text>
        </Carte>)}
      </>} />
    </Carte>
    <Carte><Text style={styles.sousTitre}>{t("admin.marketing.avis")}</Text><Text style={styles.avis}>{t("admin.marketing.avisNote")}</Text>
      <EtatSection vue={vueAvis} rendre={data => <>
        <Text>{t("admin.marketing.totalAvis", { nombre: data.total })}</Text>
        {data.demandes.length === 0 ? <Text>{t("admin.marketing.vide")}</Text> : null}
        {data.demandes.map(item => <Carte key={item.id}>
          <Text style={styles.petitTitre}>{t("admin.marketing.chantier", { reference: item.wct_id })}</Text>
          <Text>{item.nature_travaux ?? inconnu} · {item.ville ?? inconnu}</Text><Text>{item.texte}</Text>
          <Text>{t("admin.marketing.consentement", { personne: item.consentement.recueilli_par, date: item.consentement.recueilli_le, version: item.consentement.version_texte })}</Text>
          {item.avertissements.map((v, i) => <Text key={i} style={styles.avis}>{v}</Text>)}
        </Carte>)}
        {data.reste > 0 ? <Text style={styles.avis}>{t("admin.marketing.resteAvis", { nombre: data.reste })}</Text> : null}
      </>} />
    </Carte>
  </ScrollView>;
}
