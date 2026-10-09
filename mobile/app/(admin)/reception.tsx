import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { Link, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";
import { useTranslation } from "react-i18next";
import { actualiserConnectiviteTransferts, chargerDigestReception, chargerTransfertReception } from "@/m1/service";
import { dateDigestM1Valide, identifiantTransfertM1Valide } from "@/m1/contrat";
import type { DigestM1, MessageTransfertM1, TransfertM1 } from "@/m1/contrat";
import type { ResultatSection } from "@/admin/lecture";
import { BoutonSecondaire, Carte, EtatSection, stylesAdmin as styles } from "@/admin/composants";
import { presenterSection } from "@/ecrans/adminCommun";
import { capturerSessionAdminLecture } from "@/protocole/configuration";
import { useSessionAppareil } from "@/roles/contexte";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { RappelsM1 } from "@/admin/RappelsM1";

/** Deux lectures indépendantes : synthèse datée, puis fiche serveur choisie depuis « À voir ». */
export default function ReceptionAdmin() {
  const { t } = useTranslation(), session = useSessionAppareil();
  const connected = useNetInfo().isConnected === true;
  const params = useLocalSearchParams<{ transfert?: string | string[] }>();
  const id = typeof params.transfert === "string" ? params.transfert : null;
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const dateDemandee = useRef(date);
  const [digest, setDigest] = useState<ResultatSection<DigestM1> | null>(null);
  const [fiche, setFiche] = useState<ResultatSection<TransfertM1> | null>(null);
  const [charge, setCharge] = useState(false), [visible, setVisible] = useState(false);
  const sequence = useRef(0), garde = useRef<(() => boolean) | null>(null);
  const charger = useCallback(async () => {
    actualiserConnectiviteTransferts(connected);
    const capture = capturerSessionAdminLecture(), n = ++sequence.current;
    garde.current = capture.session ? capture.courante : null;
    setDigest(null); setFiche(null); setVisible(capture.session !== null && capture.courante());
    if (!capture.session || !capture.courante()) { setCharge(false); return; }
    setCharge(true);
    const courante = () => n === sequence.current && capture.courante();
    const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });
    await Promise.all([
      chargerDigestReception(dateDemandee.current).then(v => { if (courante()) setDigest(v); })
        .catch(() => { if (courante()) setDigest(aucune("lecture_indisponible")); }),
      id !== null && identifiantTransfertM1Valide(id) ?
        chargerTransfertReception(id).then(v => { if (courante()) setFiche(v); })
          .catch(() => { if (courante()) setFiche(aucune("lecture_indisponible")); }) : Promise.resolve(),
    ]);
    if (courante()) setCharge(false);
  }, [connected, id]);
  useFocusEffect(useCallback(() => {
    void charger();
    return () => { ++sequence.current; garde.current = null; setVisible(false); };
  }, [charger, session]));
  const autorisee = visible && garde.current?.() === true;
  const vue = <T,>(r: ResultatSection<T> | null) => r ? presenterSection(r, -new Date().getTimezoneOffset(), v => v) : undefined;
  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("admin.reception.titre")}</Text><BandeauIdentite />
    <Text style={styles.avis}>{t("admin.reception.note")}</Text>
    {!autorisee ? <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text> : <>
      <Carte><Text style={styles.sousTitre}>{t("admin.reception.digest")}</Text>
        <Text>{t("admin.reception.date")}</Text>
        <TextInput accessibilityLabel={t("admin.reception.date")} value={date} placeholder="YYYY-MM-DD"
          onChangeText={v => { dateDemandee.current = v; setDate(v); }} autoCapitalize="none" autoCorrect={false} />
        {!dateDigestM1Valide(date) ? <Text accessibilityRole="alert">{t("admin.reception.dateInvalide")}</Text> : null}
        <BoutonSecondaire texte={t("admin.commun.rafraichir")} desactive={charge || !dateDigestM1Valide(date)} onPress={() => void charger()} />
        <Text style={styles.avis}>{t("admin.reception.dateNote")}</Text>
        <EtatSection vue={vue(digest)} rendre={v => <Text selectable>{v}</Text>} />
      </Carte>
      <RappelsM1 connected={connected} autorisee={() => visible && garde.current?.() === true} />
      <Carte><Text style={styles.sousTitre}>{t("admin.reception.fiche")}</Text>
        <Text style={styles.avis}>{t("admin.reception.serveurSeul")}</Text>
        {id === null ? <><Text>{t("admin.reception.selection")}</Text><Link href="/admin" style={styles.lien}>{t("admin.aVoir.titre")}</Link></> :
          !identifiantTransfertM1Valide(id) ? <Text accessibilityRole="alert">{t("admin.reception.referenceInvalide")}</Text> :
          !connected ? <Text style={styles.avis}>{t("admin.reception.connexion")}</Text> :
          <EtatSection vue={vue(fiche)} rendre={v => <Fiche transfert={v} />} />}
      </Carte>
    </>}
  </ScrollView>;
}
function Fiche({ transfert: v }: { readonly transfert: TransfertM1 }) {
  const { t } = useTranslation();
  const inconnu = t("admin.reception.inconnu");
  return <View style={{ gap: 12 }}>
    <Text selectable>{v.transfert_id} · {v.conversation_id}</Text>
    <Text>{t(`admin.reception.statuts.${v.statut}`)} · {t(`admin.reception.types.${v.type_transfert}`)} · {v.niveau}</Text>
    <Text>{v.canal} · {v.ouvert_le}</Text><Text>{t("admin.reception.lead", { id: v.lead_id ?? inconnu })}</Text>
    <Text>{t("admin.reception.destinataire", { personne: v.destinataire ?? inconnu })}</Text>
    {v.verdict_destinataire ? <Text accessibilityRole="alert">{v.verdict_destinataire.code} · {v.verdict_destinataire.detail}</Text> : null}
    <Text style={styles.petitTitre}>{t("admin.reception.resume", { origine: v.resume_origine })}</Text><Text selectable>{v.resume}</Text>
    <Text>{t("admin.reception.categories", { categories: v.categories.join(", ") })}</Text>
    {Object.entries(v.termes).map(([categorie, termes]) => <Text key={categorie}>{categorie} : {termes.join(", ")}</Text>)}
    <Text style={styles.petitTitre}>{t("admin.reception.contact")}</Text>
    {v.contact ? <><Text selectable>{v.contact.telephone ?? inconnu}</Text><Text selectable>{v.contact.courriel ?? inconnu}</Text></> : <Text>{inconnu}</Text>}
    {v.client_retire_des_messages ? <Text style={styles.avis}>{t("admin.reception.stop")}</Text> : null}
    <Messages titre={t("admin.reception.messagesCouverts")} messages={v.messages_couverts} omis={v.messages_couverts_omis} />
    <Messages titre={t("admin.reception.messagesSuivants")} messages={v.messages_suivants} omis={v.messages_suivants_omis} />
    {v.suivi_rappel ? <Carte><Text style={styles.petitTitre}>{t("admin.reception.rappel")}</Text>
      <Text>{t("admin.reception.responsable", { personne: v.suivi_rappel.responsable ?? inconnu })}</Text>
      <Text>{t("admin.reception.tentatives", { nombre: v.suivi_rappel.tentatives_sans_contact })}</Text>
      <Text>{t("admin.reception.derniere", { date: v.suivi_rappel.derniere_tentative_le ?? inconnu })}</Text>
      <Text>{t("admin.reception.prochaine", { date: v.suivi_rappel.prochaine_tentative_le ?? inconnu })}</Text>
    </Carte> : null}
    {Object.hasOwn(v, "brouillon_reponse") ? <Carte><Text style={styles.petitTitre}>{t("admin.reception.brouillon")}</Text>
      <Text style={styles.avis}>{t("admin.reception.nonEnvoye")}</Text><Text selectable>{v.brouillon_reponse ?? v.sans_brouillon ?? inconnu}</Text>
    </Carte> : null}
    {v.cloture ? <Text>{t("admin.reception.cloture", { personne: v.cloture.par, date: v.cloture.clos_le, motif: v.cloture.motif })}</Text> : null}
  </View>;
}
function Messages({ titre, messages, omis }: { readonly titre: string; readonly messages: readonly MessageTransfertM1[]; readonly omis: number }) {
  const { t } = useTranslation();
  return <Carte><Text style={styles.petitTitre}>{titre}</Text>
    {messages.length === 0 ? <Text>{t("admin.reception.messagesVides")}</Text> : null}
    {messages.map(m => <View key={m.signal_id}><Text style={styles.trace}>{m.signal_id} · {m.recu_le}</Text><Text selectable>{m.texte}</Text></View>)}
    <Text style={styles.avis}>{t("admin.reception.omis", { nombre: omis })}</Text>
  </Carte>;
}
