import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { BoutonSecondaire, Carte, stylesAdmin as styles } from "./composants";
import type { ResultatSection } from "./lecture";
import {
  actualiserConnectiviteClassementM6, chargerVariancesClassablesM6, chargerHistoriqueClassementsM6,
  lireIntentionClassementM6, soumettreClassementVarianceM6,
} from "./classementVariances";
import type { EtatIntentionClassement } from "./classementVariances";
import { CAUSES_VARIANCE, motifClassementValide } from "../m6/classementVariance";
import type { CauseVariance, LigneVarianceClassableM6, PageVariancesM6, PageHistoriqueClassementsM6, PieceClassementM6, SelectionVarianceM6 } from "../m6/classementVariance";
const cle = (s: SelectionVarianceM6) => JSON.stringify([s.wct_id, s.reference_variance.evenement_id, s.reference_variance.empreinte_charge, s.position_ligne, s.materiau_id]);
const clePiece = (p: PieceClassementM6) => JSON.stringify([p.reference_mouvement.index, p.reference_mouvement.hash_maillon, p.reference_preuve]);
/** Saisie humaine explicite, pages courantes sans cache ; seule l'intention confirmée est persistée. */
export function ClassementVariancesM6({ wctId, connected, autorisee, surRefus }: {
  readonly wctId: string | null; readonly connected: boolean; readonly autorisee: () => boolean; readonly surRefus?: () => void;
}) {
  const { t } = useTranslation(), session = useSessionAppareil();
  const [page, setPage] = useState<ResultatSection<PageVariancesM6>>();
  const [historique, setHistorique] = useState<ResultatSection<PageHistoriqueClassementsM6>>();
  const [ligne, setLigne] = useState<LigneVarianceClassableM6 | null>(null);
  const [cause, setCause] = useState<CauseVariance | null>(null), [motif, setMotif] = useState("");
  const [pieces, setPieces] = useState<readonly PieceClassementM6[]>([]);
  const [intention, setIntention] = useState<EtatIntentionClassement>();
  const [occupe, setOccupe] = useState(false);
  const [, rendreGeneration] = useState(0);
  const generation = useRef(0), dernierWct = useRef<string | null>(null), garde = useRef<(() => boolean) | null>(null);
  const entree = useRef({ wctId, connected, autorisee }); entree.current = { wctId, connected, autorisee };
  const saisie = useRef(0), saisieRendu = saisie.current;
  const capture = capturerSessionAdminLecture(), rendu = generation.current;
  const permis = () => entree.current.wctId !== null && entree.current.connected && entree.current.autorisee() && capture.session !== null && capture.courante();
  const callbackCourant = () => permis() && rendu === generation.current;
  useEffect(() => {
    actualiserConnectiviteClassementM6(connected); ++generation.current; garde.current = null;
    setPage(undefined); setHistorique(undefined); setIntention(undefined); setOccupe(false); rendreGeneration(n => n + 1);
    // null pendant une interruption masque les sources ; le motif saisi reste dans cette instance.
    if (wctId !== null && dernierWct.current !== null && wctId !== dernierWct.current) {
      setLigne(null); setCause(null); setMotif(""); setPieces([]);
    }
    if (wctId !== null) dernierWct.current = wctId;
    return () => { ++generation.current; garde.current = null; };
  }, [wctId, connected]);
  useEffect(() => {
    ++generation.current; garde.current = null; setPage(undefined); setHistorique(undefined);
    setLigne(null); setCause(null); setMotif(""); setPieces([]); setIntention(undefined); setOccupe(false); rendreGeneration(n => n + 1);
  }, [session]);
  useEffect(() => () => { actualiserConnectiviteClassementM6(false); }, []);
  function requeteCourante() {
    const n = ++generation.current; garde.current = capture.courante; setOccupe(true);
    return () => permis() && n === generation.current;
  }
  async function charger(decalage = 0) {
    if (!callbackCourant() || !wctId || occupe) return;
    const courante = requeteCourante(); setPage(undefined); setHistorique(undefined);
    try {
      const r = await chargerVariancesClassablesM6(wctId, decalage);
      if (!courante()) return;
      setPage(r ?? { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
      if (r?.source === "refus") { surRefus?.(); return; }
      const i = await lireIntentionClassementM6(wctId); if (courante()) setIntention(i);
    } catch { if (courante()) setPage({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } }); }
    finally { if (courante()) setOccupe(false); }
  }
  const visible = permis() && garde.current?.() === true;
  const valeur = visible && page?.source === "serveur" ? page.valeur : null;
  const couranteLigne = valeur && ligne ? valeur.lignes.find(l => cle(l.selection) === cle(ligne.selection)) ?? null : null;
  const enAttente = intention?.genre === "en_attente" || intention?.genre === "quarantaine";
  const piecesActuelles = couranteLigne && pieces.every(p => couranteLigne.pieces_disponibles_a_selectionner.some(a => clePiece(a) === clePiece(p) && p.positions_photos.every(n => a.positions_photos.includes(n))));
  function choisir(l: LigneVarianceClassableM6) {
    if (!callbackCourant() || !visible || !valeur?.lignes.includes(l) || occupe) return;
    if (!ligne || cle(ligne.selection) !== cle(l.selection)) { setCause(null); setMotif(""); setPieces([]); }
    ++generation.current; ++saisie.current; setLigne(l); setHistorique(undefined); rendreGeneration(n => n + 1);
  }
  async function relireHistorique(decalage = 0) {
    if (!callbackCourant() || !couranteLigne || occupe) return;
    const courante = requeteCourante(); setHistorique(undefined);
    try {
      const r = await chargerHistoriqueClassementsM6(couranteLigne.selection, decalage);
      if (courante()) { setHistorique(r ?? { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } }); if (r?.source === "refus") surRefus?.(); }
    } finally { if (courante()) setOccupe(false); }
  }
  async function confirmer() {
    if (!callbackCourant() || saisieRendu !== saisie.current || !couranteLigne || !cause || !motifClassementValide(motif) || !piecesActuelles || enAttente || occupe) return;
    const courante = requeteCourante();
    const args = { selection: couranteLigne.selection, cause, motif, classement_attendu: couranteLigne.classement_courant?.reference ?? null, references_pieces: pieces };
    try {
      const r = await soumettreClassementVarianceM6(args, courante);
      if (courante()) {
        setIntention(r);
        if (r.genre === "confirmee" || r.genre === "refusee") { setPage(undefined); setHistorique(undefined); }
      }
    }
    finally { if (courante()) setOccupe(false); }
  }
  const inactive = !callbackCourant() || occupe || enAttente;
  const defaut = visible && page && page.source !== "serveur" ? page.source === "refus" ? page.verdict : page.source === "aucune" ? page.raison : null : null;
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.classementVariances.titre")}</Text>
    <Text style={styles.avis}>{t("admin.classementVariances.limites")}</Text>
    {!connected ? <Text style={styles.avis}>{t("admin.classementVariances.horsLigne")}</Text> : null}
    <BoutonSecondaire texte={t("admin.classementVariances.lire")} desactive={!permis() || occupe} onPress={() => void charger()} />
    {visible && occupe ? <ActivityIndicator /> : null}
    {defaut ? <Text>{t("admin.classementVariances.refus", { code: defaut.code, detail: defaut.detail })}</Text> : null}
    {valeur ? <>
      <Text>{t("admin.classementVariances.pagesCourantes")}</Text>
      <Text>{t("admin.classementVariances.source", { valeur: valeur.source_variance.evenement_id })}</Text>
      <Text>{t("admin.classementVariances.reference", { valeur: valeur.source_variance.empreinte_charge })}</Text>
      <Text>{t("admin.classementVariances.page", { debut: valeur.pagination.decalage, affichees: valeur.pagination.affichees, total: valeur.pagination.total })}</Text>
      {!valeur.lignes.length ? <Text>{t("admin.classementVariances.aucuneLigne")}</Text> : null}
      {valeur.lignes.map(l => <View key={cle(l.selection)}>
        <Text>{t("admin.classementVariances.article", { valeur: l.selection.materiau_id })}</Text>
        <Text>{t("admin.classementVariances.prevu", { valeur: l.source_ligne.quantite_prevue })}</Text>
        <Text>{t("admin.classementVariances.reel", { valeur: l.source_ligne.quantite_reelle })}</Text>
        <Text>{l.source_ligne.ecart_pourcentage === null ? t("admin.classementVariances.ecartInconnu") : t("admin.classementVariances.ecart", { valeur: l.source_ligne.ecart_pourcentage })}</Text>
        <Text>{l.source_ligne.unite ?? t("admin.classementVariances.uniteInconnue")}</Text>
        {l.source_ligne.critique ? <Text>{t("admin.classementVariances.critique")}</Text> : null}
        <BoutonSecondaire texte={t("admin.classementVariances.choisir")} desactive={!callbackCourant() || occupe} onPress={() => choisir(l)} />
      </View>)}
      {valeur.pagination.decalage_suivant !== null ? <BoutonSecondaire texte={t("admin.classementVariances.suite")} desactive={!callbackCourant() || occupe} onPress={() => void charger(valeur.pagination.decalage_suivant!)} /> : null}
    </> : null}
    {couranteLigne ? <>
      <Text>{t("admin.classementVariances.article", { valeur: couranteLigne.selection.materiau_id })}</Text>
      {couranteLigne.classement_courant ? <Text>{t(`admin.classementVariances.causes.${couranteLigne.classement_courant.cause}`)} : {couranteLigne.classement_courant.motif}</Text> : <Text>{t("admin.classementVariances.aucunClassement")}</Text>}
      <Text>{t("admin.classementVariances.cause")}</Text>
      {CAUSES_VARIANCE.map(c => <View key={c}>
        <BoutonSecondaire texte={t(`admin.classementVariances.causes.${c}`)} desactive={inactive} onPress={() => { if (callbackCourant() && !enAttente && !occupe) { ++saisie.current; setCause(c); } }} />
        {cause === c ? <Text>{t("admin.classementVariances.causeChoisie")}</Text> : null}
      </View>)}
      <Text>{t("admin.classementVariances.motif")}</Text>
      <TextInput accessibilityLabel={t("admin.classementVariances.motif")} multiline editable={!inactive} value={motif}
        onChangeText={v => { if (callbackCourant() && !enAttente && !occupe) { ++saisie.current; setMotif(v); } }} />
      <Text>{t("admin.classementVariances.pieces")}</Text>
      {!couranteLigne.pieces_disponibles_a_selectionner.length ? <Text>{t("admin.classementVariances.aucunePiece")}</Text> : null}
      {couranteLigne.pieces_disponibles_a_selectionner.map(p => {
        const choisie = pieces.find(v => clePiece(v) === clePiece(p));
        return <View key={clePiece(p)}>
          <Text>{t("admin.classementVariances.reference", { valeur: `${p.reference_mouvement.index} / ${p.reference_mouvement.hash_maillon}` })}</Text>
          <BoutonSecondaire texte={t(`admin.classementVariances.${choisie ? "retirerPiece" : "ajouterPiece"}`)} desactive={inactive || (!choisie && pieces.length >= 8)} onPress={() => {
            if (callbackCourant() && !enAttente && !occupe) { ++saisie.current; setPieces(v => choisie ? v.filter(a => clePiece(a) !== clePiece(p)) : [...v, { ...p, positions_photos: [] }]); }
          }} />
          {choisie ? p.positions_photos.map(position => <BoutonSecondaire key={position} texte={t("admin.classementVariances.photo", { position })} desactive={inactive} onPress={() => {
            if (callbackCourant() && !enAttente && !occupe) { ++saisie.current; setPieces(v => v.map(a => clePiece(a) === clePiece(p) ? { ...a, positions_photos: a.positions_photos.includes(position) ? a.positions_photos.filter(n => n !== position) : [...a.positions_photos, position] } : a)); }
          }} />) : null}
        </View>;
      })}
      {!piecesActuelles ? <Text>{t("admin.classementVariances.pieceIndisponible")}</Text> : null}
      <BoutonSecondaire texte={t("admin.classementVariances.confirmer")} desactive={inactive || !cause || !motifClassementValide(motif) || !piecesActuelles} onPress={() => void confirmer()} />
      <BoutonSecondaire texte={t("admin.classementVariances.historique")} desactive={!callbackCourant() || occupe} onPress={() => void relireHistorique()} />
      {historique?.source === "serveur" ? <>
        {historique.valeur.historique.map(c => <View key={c.reference.hash_maillon}>
          <Text>{t(`admin.classementVariances.causes.${c.cause}`)} : {c.motif}</Text>
          <Text>{t("admin.classementVariances.reference", { valeur: `${c.reference.index} / ${c.reference.hash_maillon}` })}</Text>
          <Text>{t("admin.classementVariances.auteur", { valeur: c.auteur.personne })}</Text>
          <Text>{t("admin.classementVariances.dateServeur", { valeur: c.classe_le })}</Text>
          <Text>{t("admin.classementVariances.dateAppareil", { valeur: c.horodatage_appareil_declare })}</Text>
        </View>)}
        {historique.valeur.pagination.decalage_suivant !== null ? <BoutonSecondaire texte={t("admin.classementVariances.suiteHistorique")} desactive={!callbackCourant() || occupe} onPress={() => void relireHistorique(historique.valeur.pagination.decalage_suivant!)} /> : null}
      </> : null}
    </> : null}
    {visible && intention && intention.genre !== "aucune" ? <Text>{t(`admin.classementVariances.${enAttente ? "enAttente" : intention.genre === "confirmee" ? "confirme" : "echecLocal"}`)}</Text> : null}
  </Carte>;
}
