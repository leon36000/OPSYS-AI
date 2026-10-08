import { useCallback, useEffect, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";
import { useTranslation } from "react-i18next";
import { controleMemoire, chargerPaquetAffaireMemoire } from "@/m10/service";
import type { ChoixArbitrageMemoire } from "@/m10/arbitrageOutbox";
import type { JsonMetier } from "@/m10/dossier";
import type { ReferenceM10 } from "@/m10/contrat";
import type { ResultatSection } from "@/admin/lecture";
import { BoutonSecondaire, Carte, EtatSection, Ligne, Lignes, stylesAdmin as styles } from "@/admin/composants";
import { presenterSection } from "@/ecrans/adminCommun";
import { capturerSessionAdminLecture } from "@/protocole/configuration";
import { useSessionAppareil } from "@/roles/contexte";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { presenterPaquetAffaire } from "@/ecrans/paquetAffaire";
import type { PaquetAffaireM10 } from "@/m10/paquetAffaire";
import { estAffairePaquetM10Valide } from "@/m10/paquetAffaire";
import { RechercheAffaireM10 } from "@/admin/RechercheAffaireM10";

const choix: readonly ChoixArbitrageMemoire[] = ["distincts_confirmes", "obsolete_marquee", "indetermine", "en_attente"];

/** Les lectures courantes sont indépendantes ; seul un dossier serveur permet un arbitrage durable. */
export default function MemoireAdmin() {
  const { t } = useTranslation();
  const session = useSessionAppareil();
  const connected = useNetInfo().isConnected === true;
  const [, render] = useState(0);
  const [erreurAction, setErreurAction] = useState(false);
  const [paquet, setPaquet] = useState<ResultatSection<PaquetAffaireM10>>();
  const [affaire, setAffaire] = useState<string | null>(null);
  const [paquetEnCours, setPaquetEnCours] = useState(false);
  const demandePaquet = useRef(0);
  const sequence = useRef(0);
  const garde = useRef<(() => boolean) | null>(null);
  const refresh = useCallback(() => render(v => v + 1), []);
  const fermerPaquet = useCallback(() => {
    ++demandePaquet.current; setPaquet(undefined); setAffaire(null); setPaquetEnCours(false);
  }, []);
  const charger = useCallback(async () => {
    if (controleMemoire.etat().statut === "arbitrage_en_cours") return;
    const capture = capturerSessionAdminLecture();
    garde.current = capture.session ? capture.courante : null;
    const n = ++sequence.current;
    ++demandePaquet.current; setPaquet(undefined); setAffaire(null); setPaquetEnCours(false);
    setErreurAction(false);
    if (!capture.session || !capture.courante()) { controleMemoire.invalider(); refresh(); return; }
    const operation = controleMemoire.charger(); refresh();
    try { await operation; } catch { if (n === sequence.current && capture.courante()) setErreurAction(true); }
    if (n === sequence.current && capture.courante()) refresh();
  }, [refresh]);
  useEffect(() => {
    // La lecture du dossier ferme même quand une intention bloque le rafraîchissement du contrôleur.
    ++demandePaquet.current; setPaquet(undefined); setAffaire(null); setPaquetEnCours(false);
    controleMemoire.actualiserConnectivite(connected); refresh();
    if (garde.current?.()) void charger();
  }, [connected, charger, refresh]);
  useFocusEffect(useCallback(() => {
    void charger();
    return () => { ++sequence.current; ++demandePaquet.current; garde.current = null; controleMemoire.invalider(); };
  }, [charger, session]));
  async function lireAffaire(affaireId: string) {
    if (!connected || garde.current?.() !== true || !estAffairePaquetM10Valide(affaireId) ||
        controleMemoire.etat().statut === "arbitrage_en_cours") return;
    const n = sequence.current, demande = ++demandePaquet.current;
    const courante = () => n === sequence.current && demande === demandePaquet.current && connected && garde.current?.() === true;
    setAffaire(affaireId); setPaquet(undefined); setPaquetEnCours(true);
    try {
      const lu = await chargerPaquetAffaireMemoire(affaireId, new Date().toISOString());
      if (courante()) setPaquet(lu ?? { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
    } catch {
      if (courante()) setPaquet({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
    } finally { if (courante()) setPaquetEnCours(false); }
  }
  async function executer(operation: () => Promise<unknown>) {
    if (!garde.current?.()) return;
    const n = sequence.current;
    setErreurAction(false);
    const pending = operation(); refresh();
    try { await pending; } catch { if (n === sequence.current && garde.current?.()) setErreurAction(true); }
    if (n === sequence.current && garde.current?.()) refresh();
  }
  const state = controleMemoire.etat();
  const visible = garde.current?.() === true;
  const decalage = -new Date().getTimezoneOffset();
  const vue = <T,>(r: ResultatSection<T> | null) => r ? presenterSection(r, decalage, v => v) : undefined;
  const statut = (categorie: string, valeur: string | null) => valeur === null ? t("admin.memoire.inconnu") : t(`admin.memoire.${categorie}.${valeur}`);
  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("admin.memoire.titre")}</Text><BandeauIdentite />
    <Text style={styles.avis}>{t("admin.memoire.note")}</Text>
    <BoutonSecondaire texte={t("admin.commun.rafraichir")} desactive={state.statut === "arbitrage_en_cours"} onPress={() => void charger()} />
    {!visible ? <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text> : <>
      {!connected ? <Text style={styles.avis}>{t("admin.memoire.messages.connexion")}</Text> : null}
      {erreurAction ? <Text accessibilityRole="alert">{t("admin.memoire.messages.lectureImpossible")}</Text> : null}
      {state.messageCode ? <Text accessibilityRole="alert" style={styles.avis}>{t(`admin.memoire.messages.${state.messageCode}`)}</Text> : null}
      {state.message ? <Text accessibilityRole="alert">{state.message}</Text> : null}
      <RechercheAffaireM10 connected={connected} bloque={state.statut === "arbitrage_en_cours"}
        autorisee={() => garde.current?.() === true} onOuvrir={id => void lireAffaire(id)} onInvalider={fermerPaquet} />
      <Carte><Text style={styles.sousTitre}>{t("admin.memoire.signaux")}</Text>
        <EtatSection vue={vue(state.signaux)} rendre={v => <>
          <Text>{t("admin.memoire.comptesSignaux", { total: v.nb_total, ouverts: v.nb_ouverts, pris: v.nb_pris_en_compte, clos: v.nb_clos, omis: v.nb_omis })}</Text>
          {v.signaux.length === 0 ? <Text>{t("admin.memoire.vide")}</Text> : null}
          {v.signaux.map(s => <Carte key={s.signal_id}>
            <Text>{t("admin.memoire.signal", { reference: s.signal_id })}</Text>
            <Text>{t("admin.memoire.affaire", { reference: s.affaire_id ?? t("admin.memoire.inconnu") })}</Text>
            {estAffairePaquetM10Valide(s.affaire_id) ? <BoutonSecondaire texte={t("admin.paquetAffaire.ouvrir")}
              desactive={!connected || state.statut === "arbitrage_en_cours"}
              onPress={() => void lireAffaire(s.affaire_id!)} /> : null}
            <Text>{statut("etatsSignal", s.etat)} · {s.horodatage}</Text>
            {s.traite_par ? <Text>{t("admin.memoire.traitement", { personne: s.traite_par, date: s.traite_le ?? t("admin.memoire.inconnu") })}</Text> : null}
            {s.motif !== null ? <Text>{s.motif}</Text> : null}
          </Carte>)}
        </>} />
      </Carte>
      {connected && affaire !== null ? <Carte><Text style={styles.sousTitre}>{t("admin.paquetAffaire.titre")}</Text>
        <EtatSection vue={paquetEnCours ? undefined : paquet ? presenterSection(paquet, decalage, v => presenterPaquetAffaire(v, decalage)) : undefined}
          rendre={v => <>
            <Lignes items={v.lignes} /><Lignes items={v.etatAffaire} />
            {v.couches.map(c => <View key={c.nom}><Ligne m={c.titre} style={styles.sousTitre} /><Lignes items={c.lignes} />
              {c.faits.map((f, i) => <View key={i}><Ligne m={f.titre} style={styles.petitTitre} /><Lignes items={f.lignes} /></View>)}</View>)}
            <Lignes items={v.confidentialite} /><Lignes items={v.signaux} /><Lignes items={v.consolidation} />
          </>} />
      </Carte> : null}
      <Carte><Text style={styles.sousTitre}>{t("admin.memoire.references")}</Text>
        <Text style={styles.avis}>{t("admin.memoire.pagesCourantes")}</Text>
        <EtatSection vue={vue(state.catalogue)} rendre={v => <>
          <Text>{t("admin.memoire.page", { debut: v.decalage, affichees: v.affichees, reste: v.reste, total: v.total })}</Text>
          <Text>{t("admin.memoire.confidentialite", { nombre: v.confidentialite.nb_retenus })}</Text>
          <Text style={styles.petitTitre}>{t("admin.memoire.decisions")}</Text>
          {v.decisions.length === 0 ? <Text>{t("admin.memoire.vide")}</Text> : null}
          {v.decisions.map(d => <Carte key={d.decision_id}>
            <Text>{d.decision_id}</Text><Text>{statut("etatsDecision", d.statut)} · {d.horodatage}</Text>
            <Reference reference={d.reference} />
            <BoutonSecondaire texte={t("admin.memoire.lireDecision")} onPress={() => void executer(() => controleMemoire.lireDecision(d.decision_id))} />
          </Carte>)}
          <Text style={styles.petitTitre}>{t("admin.memoire.revisions")}</Text>
          {v.revisions.length === 0 ? <Text>{t("admin.memoire.vide")}</Text> : null}
          {v.revisions.map(r => <Carte key={r.revision_ligne_id}>
            <Text>{statut("etatsRevision", r.statut)} · {r.statut_le}</Text><Reference reference={r.reference} />
            <BoutonSecondaire texte={t("admin.memoire.ouvrirRevision")} desactive={!connected || state.statut === "arbitrage_en_cours"}
              onPress={() => void executer(() => controleMemoire.ouvrirRevision(r.revision_ligne_id))} />
          </Carte>)}
          {v.suivant !== null ? <BoutonSecondaire texte={t("admin.memoire.suite")} desactive={state.statut === "arbitrage_en_cours"}
            onPress={() => void executer(() => controleMemoire.chargerSuite())} /> : null}
        </>} />
      </Carte>
      {state.decisionId !== null ? <Carte><Text style={styles.sousTitre}>{t("admin.memoire.statutDecision", { reference: state.decisionId })}</Text>
        <EtatSection vue={vue(state.statutDecision)} rendre={v => <Text>{statut("etatsDecision", v.statut)}</Text>} />
      </Carte> : null}
      {state.revisionId !== null ? <Carte><Text style={styles.sousTitre}>{t("admin.memoire.comparer")}</Text>
        <Text style={styles.avis}>{t("admin.memoire.arbitrageNote")}</Text>
        {!connected ? <Text>{t("admin.memoire.messages.connexion")}</Text> : <>
        <EtatSection vue={vue(state.statutRevision)} rendre={v => <Text>{statut("etatsRevision", v.statut)}</Text>} />
        <EtatSection vue={vue(state.dossier)} rendre={v => <>
          <Reference reference={v.revision.reference} />
          {v.faits.map((f, i) => <Carte key={f.reference.ligne_id}>
            <Text style={styles.petitTitre}>{t("admin.memoire.fait", { lettre: i === 0 ? "A" : "B" })}</Text>
            <Text>{t(`admin.memoire.typesFait.${f.type_entree}`)} · {f.horodatage}</Text><Reference reference={f.reference} />
            {Object.entries(f.champs).map(([cle, valeur]) => <View key={cle}>
              <Text style={styles.petitTitre}>{t(`admin.memoire.champs.${cle}`, { defaultValue: cle })}</Text>
              <ValeurMetier valeur={valeur} />
            </View>)}
          </Carte>)}
          {controleMemoire.peutArbitrer() ? choix.map(c => <BoutonSecondaire key={c} texte={t(`admin.memoire.choix.${c}`)}
            onPress={() => void executer(() => controleMemoire.arbitrer(c))} />) : <Text style={styles.avis}>{t("admin.memoire.lectureSeule")}</Text>}
        </>} />
        </>}
      </Carte> : null}
      {state.intentions.length > 0 ? <Carte><Text style={styles.sousTitre}>{t("admin.memoire.intentions")}</Text>
        <Text style={styles.avis}>{t("admin.memoire.attente")}</Text>
        {state.intentions.map(i => <Text key={i.id}>{t("admin.memoire.intention", { id: i.id, reference: i.revisionId ?? t("admin.memoire.inconnu"),
          choix: statut("etatsRevision", i.choix), statut: t(`admin.marketing.etatsFile.${i.statut}`), personne: i.personne ?? t("admin.memoire.inconnu") })}</Text>)}
      </Carte> : null}
    </>}
  </ScrollView>;
}
function Reference({ reference }: { readonly reference: ReferenceM10 }) {
  const { t } = useTranslation();
  return <Text selectable style={styles.trace}>{t("admin.memoire.reference", { ligne: reference.ligne_id })}</Text>;
}
function ValeurMetier({ valeur }: { readonly valeur: JsonMetier }) {
  const { t } = useTranslation();
  if (valeur === null) return <Text>{t("admin.memoire.inconnu")}</Text>;
  if (typeof valeur !== "object") return <Text selectable>{typeof valeur === "boolean" ? t(valeur ? "admin.memoire.oui" : "admin.memoire.non") : String(valeur)}</Text>;
  if (Array.isArray(valeur)) return <View>{valeur.length === 0 ? <Text>{t("admin.memoire.vide")}</Text> : valeur.map((v, i) => <ValeurMetier key={i} valeur={v} />)}</View>;
  return <View>{Object.entries(valeur).map(([cle, v]) => <View key={cle}><Text>{cle}</Text><ValeurMetier valeur={v} /></View>)}</View>;
}
