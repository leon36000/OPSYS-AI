import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { BoutonSecondaire, Carte, stylesAdmin as styles } from "./composants";
import type { ResultatSection } from "./lecture";
import { construireArgumentsDeclarationObligation, construireArgumentsObligations } from "../m5/obligationsPreparees";
import type { ArgumentsDeclarationObligation, CalendrierDeclareObligation, CategorieObligation, LigneObligationPreparee, PageObligationsPreparees } from "../m5/obligationsPreparees";
import { actualiserConnectiviteObligationsM5, chargerObligationsM5, lireIntentionObligationM5, reprendreObligationM5, soumettreObligationM5 } from "./obligationsPrepareesM5";
import type { EtatIntentionObligationM5 } from "./obligationsPrepareesM5";

const vierge = () => ({ montant: "", source: "", au: "", echeance: "", motif: "", autorite: "", periode_debut: "", periode_fin: "", echeance_source: "", source_consultee_le: "", source_applicable_du: "", source_applicable_jusqu_au: "", annee: "", version: "" });
type Saisie = ReturnType<typeof vierge>;
const champsCalendrier = ["autorite", "periode_debut", "periode_fin", "echeance_source", "source_consultee_le", "source_applicable_du", "source_applicable_jusqu_au", "annee", "version"] as const;
const inconnuSiVide = (v: string) => v === "" ? null : v;

/** Déclarations internes explicites : aucun versement, calcul fiscal ou état de paiement. */
export function ObligationsPrepareesM5({ connected, autorisee }: { readonly connected: boolean; readonly autorisee: () => boolean }) {
  const { t } = useTranslation(), session = useSessionAppareil();
  const [aujourdHui, setAujourdHui] = useState(""), [page, setPage] = useState<ResultatSection<PageObligationsPreparees>>();
  const [selection, setSelection] = useState<CategorieObligation | null>(null), [intention, setIntention] = useState<EtatIntentionObligationM5>();
  const [saisie, setSaisie] = useState(vierge), [avecCalendrier, setAvecCalendrier] = useState(false), [occupe, setOccupe] = useState(false);
  const [, rendre] = useState(0), generation = useRef(0), busy = useRef(false), garde = useRef<(() => boolean) | null>(null);
  const entree = useRef({ connected, autorisee }); entree.current = { connected, autorisee };
  const capture = capturerSessionAdminLecture(), rendu = generation.current;
  const autorite = () => entree.current.autorisee() && capture.session !== null && capture.courante();
  const permis = () => autorite() && entree.current.connected;
  const callbackCourant = () => permis() && rendu === generation.current;
  useEffect(() => {
    actualiserConnectiviteObligationsM5(connected); ++generation.current; garde.current = null; busy.current = false;
    setPage(undefined); setOccupe(false); rendre(n => n + 1);
    return () => { ++generation.current; garde.current = null; };
  }, [connected]);
  useEffect(() => {
    ++generation.current; garde.current = null; busy.current = false; setPage(undefined); setIntention(undefined);
    setSelection(null); setSaisie(vierge()); setAvecCalendrier(false); setOccupe(false); rendre(n => n + 1);
  }, [session]);
  useEffect(() => () => { actualiserConnectiviteObligationsM5(false); }, []);
  function commencer() {
    const n = ++generation.current; busy.current = true; garde.current = capture.courante; setOccupe(true); rendre(v => v + 1);
    return () => permis() && n === generation.current;
  }
  function finir(courante: () => boolean) { if (courante()) { busy.current = false; setOccupe(false); } }
  function changerDate(v: string) {
    ++generation.current; garde.current = null; setAujourdHui(v); setPage(undefined); setSelection(null); setIntention(undefined); setSaisie(vierge()); setAvecCalendrier(false);
  }
  let dateValide = false;
  try { construireArgumentsObligations(aujourdHui); dateValide = true; } catch { /* Date fournie explicitement. */ }
  async function charger(decalage = 0) {
    if (!callbackCourant() || busy.current || !dateValide) return;
    const date = aujourdHui, courante = commencer(); setPage(undefined); setSelection(null); setIntention(undefined); setSaisie(vierge()); setAvecCalendrier(false);
    try { const r = await chargerObligationsM5(date, decalage, 1); if (courante()) setPage(r ?? { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } }); }
    catch { if (courante()) setPage({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } }); }
    finally { finir(courante); }
  }
  const visible = permis() && garde.current?.() === true;
  const valeur = visible && page?.source === "serveur" ? page.valeur : null;
  const choisie = valeur?.obligations.find(r => r.categorie === selection) ?? null;
  async function choisir(row: LigneObligationPreparee) {
    if (!callbackCourant() || busy.current || !valeur?.obligations.includes(row)) return;
    const courante = commencer(); setSelection(row.categorie); setSaisie(vierge()); setAvecCalendrier(false); setIntention(undefined);
    try { const i = await lireIntentionObligationM5(row.categorie); if (courante()) setIntention(i); }
    catch { if (courante()) setIntention({ genre: "indisponible" }); }
    finally { finir(courante); }
  }
  const bloquee = !intention || ["en_attente", "quarantaine", "indisponible"].includes(intention.genre);
  function argumentsSaisie(operation: "declarer" | "retirer"): ArgumentsDeclarationObligation | null {
    if (!choisie) return null;
    let calendrier: CalendrierDeclareObligation | null = null;
    if (avecCalendrier) {
      if (saisie.annee !== "" && !/^[1-9]\d{0,3}$/.test(saisie.annee)) return null;
      calendrier = { autorite: inconnuSiVide(saisie.autorite), periode_debut: inconnuSiVide(saisie.periode_debut), periode_fin: inconnuSiVide(saisie.periode_fin),
        echeance_source: inconnuSiVide(saisie.echeance_source), source_consultee_le: inconnuSiVide(saisie.source_consultee_le), source_applicable_du: inconnuSiVide(saisie.source_applicable_du),
        source_applicable_jusqu_au: inconnuSiVide(saisie.source_applicable_jusqu_au), annee: saisie.annee === "" ? null : Number(saisie.annee), version: inconnuSiVide(saisie.version) };
    }
    try { return construireArgumentsDeclarationObligation(choisie.categorie, operation, operation === "retirer" ? null : {
      montant: inconnuSiVide(saisie.montant), source: inconnuSiVide(saisie.source), au: inconnuSiVide(saisie.au), echeance: inconnuSiVide(saisie.echeance), calendrier,
    }, choisie.reference, saisie.motif); } catch { return null; }
  }
  async function soumettre(operation: "declarer" | "retirer") {
    if (!callbackCourant() || busy.current || bloquee) return;
    const args = argumentsSaisie(operation); if (!args) return;
    const courante = commencer();
    try { const r = await soumettreObligationM5(args, courante); if (!courante()) return; setIntention(r); if (r.genre === "confirmee") setPage(undefined); }
    catch { if (courante()) setIntention({ genre: "indisponible" }); }
    finally { if (courante()) setPage(undefined); finir(courante); }
  }
  async function reprendre() {
    if (!callbackCourant() || busy.current || !selection || intention?.genre !== "en_attente") return;
    const categorie = selection, courante = commencer();
    try { const r = await reprendreObligationM5(categorie, courante); if (!courante()) return; setIntention(r); if (r.genre === "confirmee") setPage(undefined); }
    catch { if (courante()) setIntention({ genre: "indisponible" }); }
    finally { if (courante()) setPage(undefined); finir(courante); }
  }
  const probleme = visible && page && page.source !== "serveur" ? page.source === "refus" ? page.verdict : page.source === "aucune" ? page.raison : null : null;
  const inconnu = t("admin.obligationsM5.inconnu");
  function champ(n: keyof Saisie) {
    return <View key={n}><Text>{t(`admin.obligationsM5.${n}`)}</Text><TextInput accessibilityLabel={t(`admin.obligationsM5.${n}`)}
      value={saisie[n]} editable={!occupe && !bloquee} onChangeText={v => { if (callbackCourant() && !busy.current && !bloquee) { ++generation.current; setSaisie(s => ({ ...s, [n]: v })); } }} autoCapitalize="none" autoCorrect={false} /></View>;
  }
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.obligationsM5.titre")}</Text><Text style={styles.avis}>{t("admin.obligationsM5.note")}</Text>
    <Text>{t("admin.obligationsM5.aujourdHui")}</Text><TextInput accessibilityLabel={t("admin.obligationsM5.aujourdHui")} value={aujourdHui}
      editable={autorite() && !occupe} onChangeText={v => { if (autorite() && rendu === generation.current && !busy.current) changerDate(v); }} placeholder="YYYY-MM-DD" autoCapitalize="none" autoCorrect={false} />
    {!connected ? <Text>{t("admin.obligationsM5.horsLigne")}</Text> : null}
    <BoutonSecondaire texte={t("admin.obligationsM5.lire")} desactive={!permis() || occupe || !dateValide} onPress={() => void charger()} />
    {autorite() && occupe ? <ActivityIndicator /> : null}{probleme ? <Text accessibilityRole="alert">{probleme.code} · {probleme.detail}</Text> : null}
    {valeur ? <><Text>{valeur.mention}</Text><Text>{t("admin.obligationsM5.pagesCourantes")}</Text>
      <Text>{t("admin.obligationsM5.page", { debut: valeur.decalage, nombre: valeur.obligations.length, total: valeur.total })}</Text>
      {valeur.obligations.map(r => <View key={r.categorie} style={{ gap: 8 }}>
        <Text>{t(`admin.obligationsM5.categories.${r.categorie}`)} · {t(`admin.obligationsM5.etats.${r.etat_declaration}`)}</Text>
        <Text selectable>{r.declaration?.montant ?? inconnu} · {r.declaration?.source ?? inconnu} · {r.declaration?.au ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.echeanceDeclaree")} : {r.declaration?.echeance ?? inconnu}</Text>
        <Text selectable>{r.reference?.ligne_id ?? inconnu}</Text><Text>{r.enregistree_le ?? inconnu} · {r.auteur?.personne ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.projection")}: {t(`admin.obligationsM5.statuts.${r.calendrier_preparatoire.statut}`)} · {r.calendrier_preparatoire.echeance ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.sourceMontantNormalisee")} : {r.calendrier_preparatoire.source_montant.description ?? inconnu} · {r.calendrier_preparatoire.source_montant.au ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.sourceEcheanceNormalisee")} : {r.calendrier_preparatoire.source_echeance.description ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.autorite")} : {r.calendrier_preparatoire.autorite ?? inconnu} · {t("admin.obligationsM5.version")} : {r.calendrier_preparatoire.version ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.periode_debut")} : {r.calendrier_preparatoire.periode.debut ?? inconnu} · {t("admin.obligationsM5.periode_fin")} : {r.calendrier_preparatoire.periode.fin ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.source_consultee_le")} : {r.calendrier_preparatoire.source_echeance.consultee_le ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.source_applicable_du")} : {r.calendrier_preparatoire.source_echeance.applicable_du ?? inconnu} · {t("admin.obligationsM5.source_applicable_jusqu_au")} : {r.calendrier_preparatoire.source_echeance.applicable_jusqu_au ?? inconnu}</Text>
        <Text>{t("admin.obligationsM5.annee")} : {r.calendrier_preparatoire.annee ?? inconnu}</Text>
        {r.calendrier_preparatoire.manque.map((m, i) => <Text key={i}>{m.code} · {m.detail}</Text>)}
        <BoutonSecondaire texte={t("admin.obligationsM5.choisir")} desactive={!callbackCourant() || occupe} onPress={() => void choisir(r)} />
      </View>)}
      {valeur.decalage_suivant !== null ? <BoutonSecondaire texte={t("admin.obligationsM5.suite")} desactive={!callbackCourant() || occupe} onPress={() => void charger(valeur.decalage_suivant!)} /> : null}
    </> : null}
    {choisie ? <><Text>{t(`admin.obligationsM5.categories.${choisie.categorie}`)}</Text><Text>{t("admin.obligationsM5.saisieNote")}</Text>
      {(["montant", "source", "au", "echeance", "motif"] as const).map(champ)}
      <BoutonSecondaire texte={t("admin.obligationsM5.calendrier")} desactive={!callbackCourant() || occupe || bloquee} onPress={() => { if (callbackCourant() && !busy.current && !bloquee) { ++generation.current; setAvecCalendrier(v => !v); } }} />
      {avecCalendrier ? champsCalendrier.map(champ) : null}
      <BoutonSecondaire texte={t("admin.obligationsM5.declarer")} desactive={!callbackCourant() || occupe || bloquee || !argumentsSaisie("declarer")} onPress={() => void soumettre("declarer")} />
      <BoutonSecondaire texte={t("admin.obligationsM5.retirer")} desactive={!callbackCourant() || occupe || bloquee || !argumentsSaisie("retirer")} onPress={() => void soumettre("retirer")} />
    </> : null}
    {autorite() && selection && !choisie ? <Text>{t(`admin.obligationsM5.categories.${selection}`)}</Text> : null}
    {autorite() && intention && intention.genre !== "aucune" ? <Text>{t(`admin.obligationsM5.${intention.genre === "en_attente" ? "enAttente" : intention.genre}`)}</Text> : null}
    {autorite() && intention?.genre === "en_attente" ? <BoutonSecondaire texte={t("admin.obligationsM5.reprendre")} desactive={!callbackCourant() || occupe} onPress={() => void reprendre()} /> : null}
  </Carte>;
}
