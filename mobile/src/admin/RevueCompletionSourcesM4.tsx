import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { BoutonSecondaire, Carte, stylesAdmin as styles } from "./composants";
import type { ResultatSection } from "./lecture";
import type { DossierRevueCompletion } from "../m4/revueCompletionSources";
import { construireArgumentsPropositionRevueCompletion } from "../m4/revueCompletionSources";
import { validerRecuRevueCompletion } from "../m4/revueCompletionOutbox";
import { formaterHorodatageLocal } from "../outbox/mutation";
import {
  actualiserConnectiviteRevueCompletion, chargerDossierRevueCompletion, chargerProprietaireRevueCompletion,
  proposerRevueCompletion, deciderRevueCompletion, lireIntentionRevueCompletion,
} from "./revueCompletionSources";
import type { EtatIntentionRevueCompletion } from "./revueCompletionSources";

/** Sources courantes et capture P historique distinctes. Aucun choix, coût ou effet automatique. */
export function RevueCompletionSourcesM4({ interventionId, demandeId, connected, autorisee }: {
  readonly interventionId: string | null; readonly demandeId: string | null; readonly connected: boolean; readonly autorisee: () => boolean;
}) {
  const { t } = useTranslation(), session = useSessionAppareil();
  const [dossier, setDossier] = useState<ResultatSection<DossierRevueCompletion>>();
  const [demandeLocale, setDemandeLocale] = useState(demandeId), [owner, setOwner] = useState<boolean | null>(null);
  const [decision, setDecision] = useState<"verifiee" | "correction" | null>(null), [motif, setMotif] = useState("");
  const [intention, setIntention] = useState<EtatIntentionRevueCompletion>();
  const [occupe, setOccupe] = useState(false), [, rendre] = useState(0);
  const generation = useRef(0), saisie = useRef(0), busy = useRef(false), garde = useRef<(() => boolean) | null>(null);
  const entree = useRef({ interventionId, connected, autorisee }); entree.current = { interventionId, connected, autorisee };
  const capture = capturerSessionAdminLecture(), rendu = generation.current, saisieRendu = saisie.current;
  const permis = () => entree.current.interventionId !== null && entree.current.connected && entree.current.autorisee() && capture.session !== null && capture.courante();
  const callback = () => permis() && rendu === generation.current;
  useEffect(() => {
    actualiserConnectiviteRevueCompletion(connected); ++generation.current; garde.current = null; busy.current = false;
    setDossier(undefined); setOwner(null); setIntention(undefined); setOccupe(false); setDemandeLocale(demandeId);
    setDecision(null); setMotif(""); ++saisie.current; rendre(n => n + 1);
    return () => { ++generation.current; garde.current = null; busy.current = false; };
  }, [interventionId, demandeId, session, connected]);
  useEffect(() => () => { actualiserConnectiviteRevueCompletion(false); }, []);
  function commencer() {
    const n = ++generation.current; busy.current = true; setOccupe(true); garde.current = capture.courante;
    return () => permis() && n === generation.current;
  }
  async function charger(demande = demandeLocale) {
    if (!callback() || !interventionId || busy.current) return;
    const courante = commencer(); setDossier(undefined); setOwner(null); setDemandeLocale(demande);
    try {
      const r = await chargerDossierRevueCompletion(interventionId, demande, courante);
      if (!courante()) return;
      setDossier(r ?? { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
      if (r?.source !== "serveur") return;
      if (r.valeur.lecture === "historique") {
        const p = await chargerProprietaireRevueCompletion(courante); if (!courante()) return; setOwner(p);
      }
      const i = await lireIntentionRevueCompletion(courante); if (courante()) setIntention(i);
    } catch { if (courante()) setDossier({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } }); }
    finally { if (courante()) { busy.current = false; setOccupe(false); } }
  }
  const visible = permis() && garde.current?.() === true;
  const v = visible && dossier?.source === "serveur" ? dossier.valeur : null;
  const courant = v?.lecture === "courante" ? v : null, historique = v?.lecture === "historique" ? v : null;
  const attente = intention?.genre === "en_attente" || intention?.genre === "quarantaine";
  let propositionValide = false;
  try { if (courant && decision) propositionValide = !!construireArgumentsPropositionRevueCompletion(
    courant.intervention_id, decision, formaterHorodatageLocal({ maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() }), motif, courant.sources); } catch { /* La saisie demeure visible, sans effet. */ }
  async function confirmerP() {
    if (!callback() || saisieRendu !== saisie.current || !courant || !decision || !propositionValide || attente || busy.current) return;
    const courante = commencer(); setDossier(undefined);
    try { const r = await proposerRevueCompletion(courant, decision, motif, courante); if (courante()) setIntention(r); }
    finally { if (courante()) { busy.current = false; setOccupe(false); } }
  }
  async function confirmerD(choix: "approuver" | "refuser") {
    if (!callback() || !historique || historique.demande.statut !== "en_attente" || owner !== true || attente || busy.current) return;
    const courante = commencer(); setDossier(undefined); setOwner(null);
    try { const r = await deciderRevueCompletion(historique, choix, undefined, true, courante); if (courante()) setIntention(r); }
    finally { if (courante()) { busy.current = false; setOccupe(false); } }
  }
  const defaut = visible && dossier && dossier.source !== "serveur" ? dossier.source === "refus" ? dossier.verdict : dossier.source === "aucune" ? dossier.raison : null : null;
  const creation = visible && intention?.genre === "creation_confirmee" && validerRecuRevueCompletion(intention.mutation) ? intention.mutation.resumeAccepte : null;
  const demandeCreee = creation && typeof creation === "object" && "demande_id" in creation && typeof creation.demande_id === "string" ? creation.demande_id : null;
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.revueCompletion.titre")}</Text>
    <Text style={styles.avis}>{t("admin.revueCompletion.limites")}</Text>
    {!connected ? <Text style={styles.avis}>{t("admin.revueCompletion.horsLigne")}</Text> : null}
    <BoutonSecondaire texte={t("admin.revueCompletion.lire")} desactive={!permis() || occupe} onPress={() => void charger()} />
    {demandeLocale !== null ? <BoutonSecondaire texte={t("admin.revueCompletion.courant")} desactive={!permis() || occupe} onPress={() => void charger(null)} /> : null}
    {visible && occupe ? <ActivityIndicator /> : null}
    {defaut ? <Text style={styles.erreur}>{defaut.code} — {defaut.detail}</Text> : null}
    {courant ? <>
      <Text>{t("admin.revueCompletion.pagesCourantes")}</Text>
      <Text>{courant.intervention_id} — {courant.wct.wct_id} — {courant.wct.chantier_id}</Text>
      <Text>{courant.statut} — {courant.source_variance.horodatage_completion}</Text>
      <Text>{courant.reference_completion.ligne_id} — {courant.reference_completion.hash_maillon}</Text>
      <Text>{courant.reference_transition.ligne_id}</Text>
      <Text>{courant.source_variance.evenement_id} — {courant.source_variance.empreinte_charge}</Text>
      <Text>{t(courant.source_variance.signal_critique ? "admin.revueCompletion.signal" : "admin.revueCompletion.sansSignal")}</Text>
      {courant.lignes_critiques.map(l => <View key={l.selection.position_ligne}>
        <Text>{l.selection.position_ligne} — {l.selection.materiau_id}</Text>
        <Text>{l.source_ligne.quantite_prevue} / {l.source_ligne.quantite_reelle} — {l.source_ligne.unite ?? t("admin.revueCompletion.inconnu")}</Text>
        {l.classement_courant ? <>
          <Text>{l.classement_courant.cause} — {l.classement_courant.motif}</Text>
          <Text>{l.classement_courant.auteur.personne} — {l.classement_courant.classe_le} — {l.classement_courant.horodatage_appareil_declare}</Text>
          <Text>{JSON.stringify(l.classement_courant.reference)} — {JSON.stringify(l.classement_courant.references_pieces)}</Text>
        </> : <Text>{t("admin.revueCompletion.classementAbsent")}</Text>}
      </View>)}
      <Text>{t("admin.revueCompletion.choixExplicite")}</Text>
      <BoutonSecondaire texte={t("admin.revueCompletion.verifiee")} desactive={occupe || attente || !callback()} onPress={() => {
        if (callback() && !busy.current) { ++saisie.current; setDecision("verifiee"); }
      }} />
      <BoutonSecondaire texte={t("admin.revueCompletion.correction")} desactive={occupe || attente || !callback()} onPress={() => {
        if (callback() && !busy.current) { ++saisie.current; setDecision("correction"); }
      }} />
      {decision ? <Text>{t(`admin.revueCompletion.${decision}`)}</Text> : null}
      <TextInput value={motif} accessibilityLabel={t("admin.revueCompletion.motif")} placeholder={t("admin.revueCompletion.motif")}
        editable={!occupe && !attente && callback()} onChangeText={s => { if (callback() && !busy.current) { ++saisie.current; setMotif(s); } }} />
      <Text>{[...motif].length} / 500</Text>
      <BoutonSecondaire texte={t("admin.revueCompletion.proposer")} desactive={!propositionValide || occupe || attente || !callback()} onPress={() => void confirmerP()} />
    </> : null}
    {historique ? <>
      <Text>{t("admin.revueCompletion.captureHistorique")}</Text>
      <Text>{historique.demande.id} — {historique.demande.statut}</Text>
      <Text>{historique.demande.arguments.intervention_id} — {historique.demande.arguments.sources.wct_id} — {historique.demande.arguments.sources.chantier_id}</Text>
      <Text>{historique.demande.arguments.decision} — {historique.demande.arguments.motif} — {historique.demande.arguments.horodatage}</Text>
      <Text>{JSON.stringify(historique.demande.arguments.sources)}</Text>
      <Text>{historique.proposition.empreinte_arguments} — {historique.proposition.proposant.personne}</Text>
      {historique.issue ? <Text>{JSON.stringify(historique.issue)}</Text> : <Text>{t("admin.revueCompletion.inconnu")}</Text>}
      {historique.preuve_completion ? <Text>{historique.preuve_completion.ligne_id} — {historique.preuve_completion.approuve_par}</Text> : <Text>{t("admin.revueCompletion.preuveAbsente")}</Text>}
      {historique.demande.statut === "en_attente" && owner === true ? <>
        <BoutonSecondaire texte={t("admin.revueCompletion.approuver")} desactive={occupe || attente || !callback()} onPress={() => void confirmerD("approuver")} />
        <BoutonSecondaire texte={t("admin.revueCompletion.refuser")} desactive={occupe || attente || !callback()} onPress={() => void confirmerD("refuser")} />
      </> : <Text>{t("admin.revueCompletion.ownerRequis")}</Text>}
    </> : null}
    {visible && intention ? <Text>{t(intention.genre === "en_attente" ? "admin.revueCompletion.enAttente" :
      intention.genre === "creation_confirmee" ? "admin.revueCompletion.creationConfirmee" : intention.genre === "decision_confirmee" ?
      "admin.revueCompletion.decisionConfirmee" : intention.genre === "quarantaine" ? "admin.revueCompletion.quarantaine" : "admin.revueCompletion.inconnu")}</Text> : null}
    {demandeCreee ? <BoutonSecondaire texte={t("admin.revueCompletion.ouvrirDemande")} desactive={!callback() || occupe} onPress={() => void charger(demandeCreee)} /> : null}
  </Carte>;
}
