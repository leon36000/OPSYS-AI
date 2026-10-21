import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { useNetInfo } from "@react-native-community/netinfo";
import { useTranslation } from "react-i18next";
import { actualiserConnectiviteDispatch, chargerDigestDispatch, chargerPageDispatch, chargerPreparationDispatch, chargerMeteoDispatch, chargerRetardsDispatch } from "@/admin/dispatchService";
import { Bouton, BoutonSecondaire, Carte, EtatSection, Ligne, Lignes, stylesAdmin as styles, TextesDuServeur } from "@/admin/composants";
import { presenterGroupes, vueDigest, vuePreparation } from "@/ecrans/chantiers";
import type { LigneIntervention, VueDigest, VuePreparation } from "@/ecrans/chantiers";
import { presenterPage, vueMeteo, vueRetards } from "@/ecrans/dispatchCourant";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { capturerSessionAdminLecture } from "@/protocole/configuration";
import { useEtatIdentite } from "@/roles/contexte";
import type { ResultatSection } from "@/admin/lecture";
import type { VueSection } from "@/ecrans/adminCommun";
import { STATUTS_DU_DISPATCH, dateCivileDispatch } from "@/m4/dispatch";
import type { DigestDuJour } from "@/m4/dispatch";
import type { PageDispatch } from "@/m4/paginationDispatch";
import type { MeteoIntervention } from "@/m4/meteoIntervention";
import type { RetardsIncidents } from "@/m4/retardsIncidents";

type EtatPreparation = "chargement" | VueSection<VuePreparation>;
type Pages = Readonly<Record<string, ResultatSection<PageDispatch> | undefined>>;
const absence = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });

/** Lectures admin : pages courantes remplacées, date météo explicite et retards sans cache. */
export default function EcranChantiers() {
  const { t } = useTranslation(), identite = useEtatIdentite();
  const connected = useNetInfo().isConnected === true;
  const decalage = -new Date().getTimezoneOffset();
  const [pages, setPages] = useState<Pages>({});
  const [digest, setDigest] = useState<ResultatSection<DigestDuJour> | null>(null);
  const [retards, setRetards] = useState<ResultatSection<RetardsIncidents> | null>(null);
  const [preparations, setPreparations] = useState<Readonly<Record<string, EtatPreparation>>>({});
  const [meteos, setMeteos] = useState<Readonly<Record<string, ResultatSection<MeteoIntervention> | undefined>>>({});
  const [dateMeteo, setDateMeteo] = useState("");
  const dateDemandee = useRef("");
  const [visible, setVisible] = useState(false);
  const sequence = useRef(0), garde = useRef<(() => boolean) | null>(null);
  const generationDetails = useRef(0), generationMeteo = useRef(0);
  const demandes = useRef<Record<string, number>>({});
  const courante = (n: number) => n === sequence.current && garde.current?.() === true;
  const charger = useCallback(async () => {
    actualiserConnectiviteDispatch(connected);
    const capture = capturerSessionAdminLecture(), n = ++sequence.current;
    garde.current = capture.session ? capture.courante : null;
    demandes.current = {};
    ++generationDetails.current; ++generationMeteo.current;
    setPages({}); setDigest(null); setRetards(null); setPreparations({}); setMeteos({});
    setVisible(capture.session !== null && capture.courante());
    if (!capture.session || !capture.courante()) return;
    const valide = () => n === sequence.current && capture.courante();
    await Promise.all([
      ...STATUTS_DU_DISPATCH.map(statut => chargerPageDispatch(statut).then(v => {
        if (valide()) setPages(p => ({ ...p, [statut]: v ?? absence("lecture_remplacee") }));
      }).catch(() => { if (valide()) setPages(p => ({ ...p, [statut]: absence("lecture_indisponible") })); })),
      chargerDigestDispatch().then(v => { if (valide()) setDigest(v); }).catch(() => { if (valide()) setDigest(absence("lecture_indisponible")); }),
      chargerRetardsDispatch().then(v => { if (valide()) setRetards(v); }).catch(() => { if (valide()) setRetards(absence("lecture_indisponible")); }),
    ]);
  }, [connected]);
  useFocusEffect(useCallback(() => {
    void charger();
    return () => { ++sequence.current; ++generationDetails.current; ++generationMeteo.current; garde.current = null; demandes.current = {}; };
  }, [charger, identite]));
  const autorisee = visible && garde.current?.() === true;
  async function changerPage(statut: string, curseur: string | null) {
    const n = sequence.current, cle = `page:${statut}`, requete = (demandes.current[cle] ?? 0) + 1;
    demandes.current[cle] = requete;
    ++generationDetails.current; ++generationMeteo.current;
    setPages(p => ({ ...p, [statut]: undefined })); setPreparations({}); setMeteos({});
    const v = await chargerPageDispatch(statut, curseur).catch(() => absence("lecture_indisponible"));
    if (courante(n) && demandes.current[cle] === requete) setPages(p => ({ ...p, [statut]: v ?? absence("lecture_remplacee") }));
  }
  async function verifier(id: string) {
    const n = sequence.current, details = generationDetails.current, cle = `preparation:${id}`, requete = (demandes.current[cle] ?? 0) + 1;
    demandes.current[cle] = requete;
    setPreparations(p => ({ ...p, [id]: "chargement" }));
    const lu = await chargerPreparationDispatch(id).catch(() => absence("lecture_indisponible"));
    if (courante(n) && details === generationDetails.current && demandes.current[cle] === requete) setPreparations(p => ({ ...p, [id]: vuePreparation(lu ?? absence("lecture_remplacee"), decalage) }));
  }
  async function lireMeteo(id: string) {
    const n = sequence.current, generation = generationMeteo.current, date = dateDemandee.current, cle = `meteo:${id}`, requete = (demandes.current[cle] ?? 0) + 1;
    demandes.current[cle] = requete;
    setMeteos(p => ({ ...p, [id]: undefined }));
    const lu = await chargerMeteoDispatch(id, date === "" ? null : date).catch(() => absence("lecture_indisponible"));
    if (courante(n) && generation === generationMeteo.current && date === dateDemandee.current && demandes.current[cle] === requete) setMeteos(p => ({ ...p, [id]: lu ?? absence("lecture_remplacee") }));
  }
  function changerDate(v: string) { ++generationMeteo.current; dateDemandee.current = v; setDateMeteo(v); setMeteos({}); }
  const dateValide = dateMeteo === "" || dateCivileDispatch(dateMeteo);
  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("admin.chantiers.titre")}</Text><BandeauIdentite />
    <Text style={styles.trace}>{t("admin.chantiers.lectureSeule")}</Text>
    <Text style={styles.avis}>{t("admin.dispatch.pageCourante")}</Text>
    <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />
    {!autorisee ? <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text> : <>
      <Text style={styles.sousTitre}>{t("admin.chantiers.digestTitre")}</Text>
      <EtatSection vue={digest ? vueDigest(digest, decalage) : undefined} rendre={v => <DigestUI vue={v} />} />
      <Text style={styles.sousTitre}>{t("admin.dispatch.retardsTitre")}</Text>
      <Text style={styles.avis}>{t("admin.dispatch.retardsServeur")}</Text>
      <EtatSection vue={retards ? vueRetards(retards, decalage) : undefined} rendre={v => <View style={{ gap: 8 }}>
        <Lignes items={v.lignes} /><TextesDuServeur items={v.textes} />
        {[...v.reports, ...v.incidents].map((l, index) => <Carte key={`${index}:${l.id}`}><Lignes items={l.lignes} /></Carte>)}
      </View>} />
      <Text style={styles.sousTitre}>{t("admin.dispatch.meteoTitre")}</Text>
      <Text style={styles.avis}>{t("admin.dispatch.dateNote")}</Text>
      <TextInput accessibilityLabel={t("admin.dispatch.dateEtiquette")} value={dateMeteo} placeholder="YYYY-MM-DD"
        autoCapitalize="none" autoCorrect={false} onChangeText={changerDate} />
      {!dateValide ? <Text accessibilityRole="alert">{t("admin.dispatch.dateInvalide")}</Text> : null}
      <Text style={styles.sousTitre}>{t("admin.chantiers.dispatchTitre")}</Text>
      {STATUTS_DU_DISPATCH.map(statut => {
        const r = pages[statut];
        const groupe = r ? presenterGroupes([{ statut, resultat: r }], decalage)[0] : null;
        const page = r?.source === "serveur" || r?.source === "cache" ? presenterPage(r.valeur) : null;
        return <Carte key={statut}>
          <Text style={styles.petitTitre}>{t(`admin.chantiers.statuts.${statut}`)}</Text>
          {page ? <Lignes items={page.lignes} style={styles.trace} /> : null}
          <EtatSection vue={groupe?.section} rendre={v => <View style={{ gap: 8 }}>
            <Ligne m={v.resume} />
            {v.interventions.map(i => <InterventionUI key={i.interventionId} intervention={i} preparation={preparations[i.interventionId]}
              meteo={meteos[i.interventionId]} onVerifier={() => void verifier(i.interventionId)}
              onMeteo={() => void lireMeteo(i.interventionId)} dateValide={dateValide} decalage={decalage} />)}
          </View>} />
          {page ? <><BoutonSecondaire texte={t("admin.dispatch.recommencer")} onPress={() => void changerPage(statut, null)} />
            {page.curseurSuivant !== null ? <BoutonSecondaire texte={t("admin.dispatch.suivante")} desactive={r?.source !== "serveur"}
              onPress={() => void changerPage(statut, page.curseurSuivant)} /> : null}</> : null}
        </Carte>;
      })}
    </>}
  </ScrollView>;
}

function InterventionUI({ intervention, preparation, meteo, onVerifier, onMeteo, dateValide, decalage }: {
  readonly intervention: LigneIntervention; readonly preparation: EtatPreparation | undefined;
  readonly meteo: ResultatSection<MeteoIntervention> | undefined; readonly onVerifier: () => void;
  readonly onMeteo: () => void; readonly dateValide: boolean; readonly decalage: number;
}) {
  const { t } = useTranslation();
  return <Carte><Text style={styles.petitTitre}>{intervention.reference}</Text>
    <Ligne m={intervention.travaux} style={styles.meta} /><Ligne m={intervention.lead} style={styles.meta} />
    {intervention.devis !== null ? <Ligne m={intervention.devis} style={styles.meta} /> : null}
    <Ligne m={intervention.technicien} style={styles.meta} />
    {intervention.fenetre !== null ? <Ligne m={intervention.fenetre} style={styles.meta} /> : null}
    {intervention.preparable ? <Bouton texte={preparation === "chargement" ? t("admin.chantiers.preparerEnCours") : t("admin.chantiers.preparer")}
      desactive={preparation === "chargement"} onPress={onVerifier} /> : null}
    {preparation !== undefined && preparation !== "chargement" ? <EtatSection vue={preparation} rendre={v => <PreparationUI vue={v} />} /> : null}
    <BoutonSecondaire texte={t("admin.dispatch.lireMeteo")} desactive={!dateValide} onPress={onMeteo} />
    {meteo ? <EtatSection vue={vueMeteo(meteo, decalage)} rendre={v => <View style={{ gap: 6 }}>
      <Lignes items={v.lignes} /><TextesDuServeur items={v.textes} />
      {v.creneaux.map((c, index) => <Carte key={`${index}:${c.id}`}><Lignes items={c.lignes} /><TextesDuServeur items={c.textes} /></Carte>)}
    </View>} /> : null}
  </Carte>;
}

function PreparationUI({ vue }: { readonly vue: VuePreparation }) {
  const { t } = useTranslation();
  return (
    <View style={{ gap: 6 }}>
      <Ligne m={vue.titre} style={styles.petitTitre} />
      <Text style={styles.trace}>{t("admin.chantiers.preparation.statutEtiquette")}</Text>
      <Ligne m={vue.statutIntervention} style={styles.meta} />
      <Text style={styles.trace}>{t("admin.chantiers.preparation.verdictEtiquette")}</Text>
      <Ligne m={vue.verdict} style={vue.pret ? styles.montant : styles.erreur} />
      {vue.volets.map((volet, index) => (
        <View key={`${index}:${volet.nom.cle}`} style={{ gap: 2 }}>
          <Ligne m={volet.nom} style={styles.petitTitre} />
          <Ligne m={volet.statut} style={volet.ok ? styles.meta : styles.erreur} />
          {volet.manque !== null ? <Ligne m={volet.manque} style={styles.avis} /> : null}
          {volet.code !== null ? <Ligne m={volet.code} style={styles.trace} /> : null}
          {volet.detail !== null ? <Text style={styles.trace}>{volet.detail}</Text> : null}
        </View>
      ))}
      {vue.aFournir.length > 0 ? (
        <>
          <Text style={styles.petitTitre}>{t("admin.chantiers.preparation.aFournirTitre")}</Text>
          {vue.aFournir.map((entree, index) => (
            <View key={`${index}:${entree.volet.cle}`}>
              <Ligne m={entree.volet} style={styles.meta} />
              <Ligne m={entree.manque} style={styles.avis} />
            </View>
          ))}
        </>
      ) : null}
    </View>
  );
}

function DigestUI({ vue }: { readonly vue: VueDigest }) {
  const { t } = useTranslation();
  return (
    <View style={{ gap: 6 }}>
      <Ligne m={vue.titre} style={styles.trace} />
      {vue.rienASignaler ? <Text style={styles.meta}>{t("admin.chantiers.digest.rienASignaler")}</Text> : null}
      {vue.terminees.length > 0 ? <Text style={styles.petitTitre}>{t("admin.chantiers.digest.terminees")}</Text> : null}
      {vue.terminees.map((terminee, index) => (
        <Carte key={`${index}:${terminee.titre.cle}`}>
          <Ligne m={terminee.titre} style={styles.meta} />
          <Ligne m={terminee.duree} style={styles.trace} />
          <Ligne m={terminee.ecart} style={styles.trace} />
        </Carte>
      ))}
      {vue.enRevue.length > 0 ? (
        <>
          <Text style={styles.petitTitre}>{t("admin.chantiers.digest.enRevueTitre")}</Text>
          <Lignes items={vue.enRevue} style={styles.meta} />
        </>
      ) : null}
      <Ligne m={vue.enAttenteDeRevue} style={styles.meta} />
      {vue.parType.length > 0 ? (
        <>
          <Text style={styles.petitTitre}>{t("admin.chantiers.digest.parTypeTitre")}</Text>
          <Lignes items={vue.parType} style={styles.meta} />
        </>
      ) : null}
      {vue.bloquees.length > 0 ? <Text style={styles.petitTitre}>{t("admin.chantiers.digest.bloqueesTitre")}</Text> : null}
      {vue.bloquees.map((bloquee, index) => (
        <Carte key={`${index}:${bloquee.titre.cle}`}>
          <Ligne m={bloquee.titre} style={styles.meta} />
          <Ligne m={bloquee.attente} style={styles.avis} />
        </Carte>
      ))}
      {vue.illisibles !== null ? <Ligne m={vue.illisibles} style={styles.avis} /> : null}
    </View>
  );
}
