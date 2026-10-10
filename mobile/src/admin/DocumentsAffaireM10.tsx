import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, Text, TextInput } from "react-native";
import { useFocusEffect } from "expo-router";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { creerControleDocumentsAffaireService } from "../m10/documentsAffaireControleService";
import type { OperationDocumentM10 } from "../m10/documentsAffaireOutbox";
import { BoutonSecondaire, Carte, stylesAdmin as styles } from "./composants";

interface Props {
  readonly affaireId: string | null;
  /** Chaque ouverture explicite relit la page, même pour la même affaire. */
  readonly ouverture: number;
  readonly connected: boolean;
}
/** Brouillon RAM et intentions durables séparés ; les lectures n'envoient aucune mutation. */
export function DocumentsAffaireM10({ affaireId, ouverture, connected }: Props) {
  const { t } = useTranslation();
  const session = useSessionAppareil();
  const props = useRef({ affaireId, connected }); props.current = { affaireId, connected };
  const [controle] = useState(() => creerControleDocumentsAffaireService(() => props.current.connected));
  const [, rendre] = useState(0);
  const generation = useRef(0), focused = useRef(false);
  const refresh = useCallback(() => rendre(v => v + 1), []);
  useFocusEffect(useCallback(() => {
    focused.current = true;
    const n = ++generation.current, capture = capturerSessionAdminLecture();
    controle.actualiserConnectivite(connected);
    const operation = capture.session && capture.courante() ? (affaireId !== null ? controle.ouvrirAffaire(affaireId) : controle.rafraichir()) : Promise.resolve();
    refresh();
    void operation.catch(() => undefined).finally(() => { if (n === generation.current && capture.courante()) refresh(); });
    return () => { focused.current = false; ++generation.current; controle.invaliderLectures(); };
  }, [controle, affaireId, ouverture, connected, session, refresh]));
  const capture = capturerSessionAdminLecture(), n = generation.current;
  const state = controle.etat();
  const courante = () => focused.current && n === generation.current && capture.session !== null && capture.courante() && props.current.affaireId === affaireId;
  const visible = capture.session !== null && capture.courante() && state.affaireId === affaireId;
  function executer(operation: () => Promise<unknown>) {
    if (!courante()) return;
    ++generation.current;
    const pending = operation(); refresh();
    void pending.catch(() => undefined).finally(() => {
      // Le contrôleur a écarté les données tardives. Relire son état libère aussi busy
      // si le panneau a retrouvé le focus pendant l’attente, sans adopter la réponse.
      if (focused.current && capture.courante()) refresh();
    });
  }
  function local(operation: () => void) { if (courante()) { ++generation.current; operation(); refresh(); } }
  const titre = visible ? state.brouillon.titre : "", corps = visible ? state.brouillon.corps : "";
  // Les limites métier portent sur les points Unicode. Aucun trim, NFC ou découpage du contenu.
  // oxlint-disable-next-line no-control-regex -- Séparateurs U+001C à U+001F exclus, comme dans le contrat documentaire.
  const brouillonValide = /[^\p{White_Space}\u001c-\u001f]/u.test(titre) && !/[\p{Cs}]/u.test(titre + corps) &&
    [...titre].length <= 120 && [...corps].length > 0 && [...corps].length <= 2000;
  const page = visible && connected && state.page?.source === "serveur" ? state.page.valeur : null;
  const detail = visible && connected && state.detail?.source === "serveur" ? state.detail.valeur : null;
  const action = (op: OperationDocumentM10) => {
    if (courante() && (op !== "deposer" || brouillonValide) && controle.disponible(op)) executer(() => controle.soumettre(op));
  };
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.documentsAffaire.titre")}</Text>
    <Text style={styles.avis}>{t("admin.documentsAffaire.pagesCourantes")}</Text>
    {!visible || affaireId === null ? <Text>{t("admin.documentsAffaire.choisirAffaire")}</Text> : <>
      <Text selectable>{t("admin.documentsAffaire.affaire", { affaire: affaireId })}</Text>
      {!connected ? <Text style={styles.avis}>{t("admin.documentsAffaire.horsLigne")}</Text> : null}
      <BoutonSecondaire texte={t("admin.documentsAffaire.rafraichir")} desactive={!connected || state.enCours}
        onPress={() => executer(() => controle.rafraichir())} />
      {state.enCours ? <ActivityIndicator /> : null}
      {state.message ? <Text accessibilityRole="alert">{t(`admin.documentsAffaire.messages.${state.message}`)}</Text> : null}
      {connected && state.page?.source === "refus" ? <Text accessibilityRole="alert">{t("admin.documentsAffaire.refus")}</Text> : null}
      {page ? <>
        <Text>{t("admin.documentsAffaire.page", { decalage: page.decalage, affichees: page.versions.length, total: page.total_versions })}</Text>
        {page.versions.length === 0 ? <Text>{t("admin.documentsAffaire.vide")}</Text> : null}
        {page.versions.map(ligne => <Carte key={ligne.version_source.ligne_id}>
          <Text selectable style={styles.petitTitre}>{ligne.titre}</Text>
          <Text>{t(`admin.documentsAffaire.statuts.${ligne.statut}`)}</Text>
          <Text>{t("admin.documentsAffaire.version", { numero: ligne.version_no })}</Text>
          <Text selectable>{t("admin.documentsAffaire.reference", { document: ligne.document_ref.ligne_id, version: ligne.version_source.ligne_id })}</Text>
          <Text>{t("admin.documentsAffaire.provenance", { personne: ligne.auteur.personne, role: ligne.auteur.role, source: ligne.auteur.source, date: ligne.horodatage })}</Text>
          <Text selectable>{t("admin.documentsAffaire.empreinte", { hash: ligne.source_sha256, points: ligne.taille_points, octets: ligne.taille_octets })}</Text>
          <BoutonSecondaire texte={t("admin.documentsAffaire.lireVersion")} desactive={state.enCours}
            onPress={() => executer(() => controle.selectionner(ligne))} />
        </Carte>)}
        {page.suivant_decalage !== null ? <BoutonSecondaire texte={t("admin.documentsAffaire.suite")} desactive={state.enCours}
          onPress={() => executer(() => controle.suite())} /> : null}
      </> : null}
      {connected && state.detail?.source === "refus" ? <Text accessibilityRole="alert">{t("admin.documentsAffaire.refus")}</Text> : null}
      {connected && state.detail?.source === "aucune" ? <Text>{t("admin.documentsAffaire.messages.lecture_indisponible")}</Text> : null}
      {detail ? <Carte>
        <Text style={styles.petitTitre}>{t("admin.documentsAffaire.detail")}</Text>
        <Text>{t(`admin.documentsAffaire.statuts.${detail.statut}`)}</Text>
        <Text selectable>{t("admin.documentsAffaire.reference", { document: detail.document_ref.ligne_id, version: detail.version_source.ligne_id })}</Text>
        {detail.statut !== "RETIREE" && "corps" in detail ? <Text selectable>{detail.corps}</Text> : <Text>{t("admin.documentsAffaire.retire")}</Text>}
      </Carte> : null}
      <Text style={styles.petitTitre}>{t("admin.documentsAffaire.brouillon")}</Text>
      <Text style={styles.avis}>{t("admin.documentsAffaire.ram")}</Text>
      <Text selectable>{state.cibleBrouillon ? t("admin.documentsAffaire.cibleVersion", { reference: state.cibleBrouillon.ligne_id }) : t("admin.documentsAffaire.cibleNouveau")}</Text>
      <BoutonSecondaire texte={t("admin.documentsAffaire.nouveau")} desactive={state.enCours}
        onPress={() => local(() => controle.nouveauDocument())} />
      <TextInput accessibilityLabel={t("admin.documentsAffaire.saisieTitre")} value={titre} editable={!state.enCours}
        onChangeText={v => local(() => controle.modifierBrouillon(v, corps))} />
      <TextInput accessibilityLabel={t("admin.documentsAffaire.saisieCorps")} value={corps} editable={!state.enCours} multiline
        onChangeText={v => local(() => controle.modifierBrouillon(titre, v))} />
      <Text>{t("admin.documentsAffaire.limites", { titre: [...titre].length, corps: [...corps].length })}</Text>
      <Text style={styles.avis}>{t("admin.documentsAffaire.actionsNote")}</Text>
      {(["deposer", "activer", "retirer"] as const).map(op => <BoutonSecondaire key={op} texte={t(`admin.documentsAffaire.${op}`)}
        desactive={!connected || !controle.disponible(op) || (op === "deposer" && !brouillonValide)} onPress={() => action(op)} />)}
    </>}
    {capture.session && capture.courante() && (state.intentionId || state.intentions.length > 0) ? <Carte>
        <Text style={styles.petitTitre}>{t("admin.documentsAffaire.intentions")}</Text>
        <Text style={styles.avis}>{t("admin.documentsAffaire.recuNote")}</Text>
        {state.intentionId ? <Text selectable>{t("admin.documentsAffaire.intentionEnCours", { id: state.intentionId })}</Text> : null}
        {state.intentions.map(i => <Text selectable key={i.id}>{t("admin.documentsAffaire.intention", { id: i.id, statut: t(`admin.documentsAffaire.etatsFile.${["brouillon", "en_attente", "envoi", "envoyee", "echec_permanent"].includes(i.statut) ? i.statut : "inconnu"}`) })}</Text>)}
        <BoutonSecondaire texte={t("admin.documentsAffaire.reprendre")} desactive={!connected || state.enCours}
          onPress={() => executer(() => controle.reprendre())} />
      </Carte> : null}
  </Carte>;
}
