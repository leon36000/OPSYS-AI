import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useTranslation } from "react-i18next";

import { formaterDepuis } from "@/ecrans/approvals";
import { issueNote, lignesContact, opportunitesDuClient, travauxDeOpportunite, vueFiche } from "@/ecrans/lead";
import type { IssueNote } from "@/ecrans/lead";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import type { Client360, Opportunite } from "@/m2/client360";
import { creerMutationNote, notesEnFile, RESUME_LONGUEUR_MAX, validerNote } from "@/m2/interaction";
import type { NoteEnFile } from "@/m2/interaction";
import { demarrerDeclencheursVidange } from "@/outbox/declencheurs";
import { genererMutationId } from "@/outbox/id";
import { declencherVidange, obtenirDepot } from "@/outbox/service";
import { obtenirConfigurationAppel } from "@/protocole/configuration";
import { usePersonneAppairee } from "@/roles/contexte";
import type { ResultatFiche } from "@/vendeur/chargeurFiche";
import { historiqueDuLead } from "@/vendeur/fiche";
import { chargerFiche } from "@/vendeur/service";

/**
 * `lead/[id].tsx` (§9.4 « prochaine meilleure action », « Client 360 », « notes » ; M2.2, M2.6 ; PLAN T4.8) : la fiche
 * d'un lead du vendeur. Prochaine action suggérée avec sa règle citée (`m2_suggerer_prochaine_action`), Client 360 du
 * client (`m2_trouver_client_de_lead`, `m2_obtenir_client_360`), historique, et une note (`m2_enregistrer_interaction`)
 * qui part par la file sortante avec sa clé d'idempotence. Lecture d'abord, cache SQLite hors ligne marqué comme tel.
 *
 * Fail-closed : rien d'inventé. Le lead d'un autre vendeur donne le même refus qu'un lead inconnu, montré tel quel ;
 * un contact absent est dit absent ; la note ne part pas sans personne confirmée par le serveur. Toute la logique est
 * dans `src/ecrans/lead.ts`, `src/m2/` et `src/vendeur/`, testée là ; ce fichier n'est que le câblage React (non couvert
 * en rendu, même limite que les autres écrans).
 */
export default function EcranLead() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const leadId = typeof id === "string" ? id : "";
  const personne = usePersonneAppairee();

  const [resultat, setResultat] = useState<ResultatFiche | null | undefined>(undefined);
  const [chargement, setChargement] = useState(true);
  const [enFile, setEnFile] = useState<readonly NoteEnFile[]>([]);
  const [texte, setTexte] = useState("");
  const [erreurNote, setErreurNote] = useState<"vide" | "trop_longue" | null>(null);
  const [erreurIdentite, setErreurIdentite] = useState(false);
  const [erreurAppareil, setErreurAppareil] = useState(false);
  const [enTraitement, setEnTraitement] = useState(false);
  const [issue, setIssue] = useState<IssueNote | null>(null);
  const sequence = useRef(0);

  const charger = useCallback(async () => {
    if (leadId === "") {
      setChargement(false);
      return;
    }
    const numero = ++sequence.current;
    setChargement(true);
    try {
      const depot = await obtenirDepot().catch(() => null);
      const [fiche, mutations] = await Promise.all([chargerFiche(leadId), depot ? depot.lister() : Promise.resolve([])]);
      if (numero !== sequence.current) {
        return;
      }
      setResultat(fiche);
      setEnFile(notesEnFile(mutations, leadId));
    } finally {
      if (numero === sequence.current) {
        setChargement(false);
      }
    }
  }, [leadId]);

  useEffect(() => {
    void charger();
    // Une note restée en file part au premier plan et au retour du réseau : la fiche se relit alors.
    return demarrerDeclencheursVidange({ aoDeclenchement: () => void charger() });
  }, [charger]);

  const ajouterNote = useCallback(async () => {
    // Fail-closed : sans personne confirmée par le serveur, aucune note n'est mise en file.
    if (!personne) {
      setErreurIdentite(true);
      return;
    }
    if (!obtenirConfigurationAppel()) {
      setErreurAppareil(true);
      return;
    }
    const validation = validerNote(texte);
    if (!validation.ok) {
      setErreurNote(validation.raison);
      return;
    }
    setErreurIdentite(false);
    setErreurAppareil(false);
    setErreurNote(null);
    setEnTraitement(true);
    try {
      const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
      const mutation = creerMutationNote(leadId, validation.resume, genererMutationId, horloge);
      const depot = await obtenirDepot();
      const persistee = await depot.inserer(mutation);
      setTexte("");

      // Tentative immédiate, best-effort : hors ligne, la note reste en file avec sa clé d'idempotence (R12 §4) et
      // partira avec les déclencheurs de vidange — jamais perdue, jamais écrite deux fois.
      const rapport = await declencherVidange().catch(() => null);
      setIssue(issueNote(rapport, persistee.id));
      await charger();
    } finally {
      setEnTraitement(false);
    }
  }, [personne, texte, leadId, charger]);

  const decalageMinutesUTC = -new Date().getTimezoneOffset();
  const vue = resultat === undefined ? null : vueFiche(resultat);

  if (leadId === "") {
    return (
      <View style={styles.conteneur}>
        <Text style={styles.erreur}>{t("vendeur.lead.identifiantInvalide")}</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("vendeur.lead.titre", { id: leadId })}</Text>
      <BandeauIdentite />

      <Pressable style={styles.boutonSecondaire} disabled={chargement} onPress={() => void charger()}>
        <Text style={styles.boutonSecondaireTexte}>{t("vendeur.commun.rafraichir")}</Text>
      </Pressable>

      {chargement ? <ActivityIndicator /> : null}
      {vue?.genre === "sans_appairage" ? <Text style={styles.erreur}>{t("vendeur.commun.sansSession")}</Text> : null}
      {vue?.genre === "aucune" ? (
        <Text style={styles.erreur}>{t("vendeur.commun.echecLecture", { code: vue.raison.code, detail: vue.raison.detail })}</Text>
      ) : null}

      {vue?.genre === "fiche" ? (
        <>
          {vue.cache !== null ? (
            <Text style={styles.avis}>
              {t("vendeur.commun.cache", { date: formaterDepuis(vue.cache.misAJourLe, decalageMinutesUTC), code: vue.cache.raison.code })}
            </Text>
          ) : null}

          <View style={styles.carte}>
            <Text style={styles.sousTitre}>{t("vendeur.lead.suggestion.titre")}</Text>
            {vue.fiche.suggestion.genre === "lue" ? (
              <>
                <Text style={styles.outil}>{vue.fiche.suggestion.valeur.suggestion}</Text>
                <Text style={styles.meta}>{t("vendeur.lead.suggestion.regle", { regle: vue.fiche.suggestion.valeur.regle })}</Text>
                <Text style={styles.meta}>{t("vendeur.lead.suggestion.motif", { motif: vue.fiche.suggestion.valeur.motif })}</Text>
              </>
            ) : (
              <Text style={styles.avis}>
                {t("vendeur.lead.suggestion.refus", {
                  code: vue.fiche.suggestion.verdict.code,
                  detail: vue.fiche.suggestion.verdict.detail,
                })}
              </Text>
            )}
          </View>

          <View style={styles.carte}>
            <Text style={styles.sousTitre}>{t("vendeur.lead.client.titre")}</Text>
            {vue.fiche.client.genre === "lue" ? (
              <ClientLu
                lignesContact={lignesContact(vue.fiche.client.valeur)}
                courante={opportunitesDuClient(vue.fiche.client.valeur, leadId).courante}
                autres={opportunitesDuClient(vue.fiche.client.valeur, leadId).autres}
                illisibles={vue.fiche.client.valeur.illisibles}
                decalageMinutesUTC={decalageMinutesUTC}
              />
            ) : (
              <Text style={styles.avis}>
                {t("vendeur.lead.client.refus", { code: vue.fiche.client.verdict.code, detail: vue.fiche.client.verdict.detail })}
              </Text>
            )}
          </View>

          {vue.fiche.client.genre === "lue" ? (
            <Historique client={vue.fiche.client.valeur} leadId={leadId} decalageMinutesUTC={decalageMinutesUTC} />
          ) : null}
        </>
      ) : null}

      {enFile.length > 0 ? (
        <View style={styles.carte}>
          <Text style={styles.sousTitre}>{t("vendeur.lead.notes.enFileTitre")}</Text>
          {enFile.map((note) => (
            <View key={note.mutationId} style={styles.ligne}>
              <Text style={styles.outil}>{note.resume}</Text>
              <Text style={note.statut === "echec_permanent" ? styles.erreur : styles.avis}>
                {t(`vendeur.lead.notes.statut.${note.statut}`)}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      <View style={styles.carte}>
        <Text style={styles.sousTitre}>{t("vendeur.lead.notes.titre")}</Text>
        <TextInput
          style={styles.champ}
          multiline
          placeholder={t("vendeur.lead.notes.champ", { max: RESUME_LONGUEUR_MAX })}
          accessibilityLabel={t("vendeur.lead.notes.champ", { max: RESUME_LONGUEUR_MAX })}
          value={texte}
          onChangeText={setTexte}
          maxLength={RESUME_LONGUEUR_MAX}
          editable={!enTraitement}
        />
        {erreurNote === "vide" ? <Text style={styles.erreur}>{t("vendeur.lead.notes.vide")}</Text> : null}
        {erreurNote === "trop_longue" ? <Text style={styles.erreur}>{t("vendeur.lead.notes.tropLongue", { max: RESUME_LONGUEUR_MAX })}</Text> : null}
        {erreurIdentite ? <Text style={styles.erreur}>{t("identite.absente")}</Text> : null}
        {erreurAppareil ? <Text style={styles.erreur}>{t("vendeur.lead.notes.appareilNonAppaire")}</Text> : null}
        <Pressable
          style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
          disabled={enTraitement}
          onPress={() => void ajouterNote()}
        >
          <Text style={styles.boutonTexte}>{enTraitement ? t("vendeur.lead.notes.enCours") : t("vendeur.lead.notes.ajouter")}</Text>
        </Pressable>
        {issue?.genre === "enregistree" ? <Text style={styles.succes}>{t("vendeur.lead.notes.resultat.enregistree")}</Text> : null}
        {issue?.genre === "refusee" ? (
          <Text style={styles.erreur}>
            {t("vendeur.lead.notes.resultat.refusee", { code: issue.verdict.code, detail: issue.verdict.detail })}
          </Text>
        ) : null}
        {issue?.genre === "en_file" ? <Text style={styles.avis}>{t("vendeur.lead.notes.resultat.enFile")}</Text> : null}
      </View>
    </ScrollView>
  );
}

interface ProprietesClient {
  readonly lignesContact: ReturnType<typeof lignesContact>;
  readonly courante: Opportunite | null;
  readonly autres: readonly Opportunite[];
  readonly illisibles: number;
  readonly decalageMinutesUTC: number;
}

function ClientLu({ lignesContact: contact, courante, autres, illisibles, decalageMinutesUTC }: ProprietesClient) {
  const { t } = useTranslation();
  return (
    <>
      <Text style={styles.sousTitre}>{t("vendeur.lead.client.contact")}</Text>
      {contact === null ? (
        <Text style={styles.avis}>{t("vendeur.lead.client.contactAbsent")}</Text>
      ) : (
        contact.map((ligne) => (
          <Text key={ligne.cle} style={styles.donnee}>
            {t("vendeur.leads.donnee", { cle: ligne.cle, valeur: ligne.valeur })}
          </Text>
        ))
      )}

      <Text style={styles.sousTitre}>{t("vendeur.lead.client.ceLead")}</Text>
      {courante === null ? (
        <Text style={styles.avis}>{t("vendeur.lead.client.opportuniteAbsente")}</Text>
      ) : (
        <CarteOpportunite opportunite={courante} decalageMinutesUTC={decalageMinutesUTC} />
      )}

      {autres.length > 0 ? <Text style={styles.sousTitre}>{t("vendeur.lead.client.autres")}</Text> : null}
      {autres.map((opportunite) => (
        <CarteOpportunite key={opportunite.leadId} opportunite={opportunite} decalageMinutesUTC={decalageMinutesUTC} />
      ))}
      {illisibles > 0 ? <Text style={styles.avis}>{t("vendeur.lead.client.illisibles", { nombre: illisibles })}</Text> : null}
    </>
  );
}

function CarteOpportunite({ opportunite, decalageMinutesUTC }: { readonly opportunite: Opportunite; readonly decalageMinutesUTC: number }) {
  const { t } = useTranslation();
  const absent = t("vendeur.commun.absent");
  return (
    <View style={styles.ligne}>
      <Text style={styles.trace}>{opportunite.leadId}</Text>
      <Text style={styles.meta}>
        {t("vendeur.lead.client.statut", {
          statut:
            opportunite.statut === null ? absent : t(`vendeur.statuts.${opportunite.statut}`, { defaultValue: opportunite.statut }),
        })}
      </Text>
      <Text style={styles.meta}>{t("vendeur.lead.client.travaux", { travaux: travauxDeOpportunite(opportunite) ?? absent })}</Text>
      <Text style={styles.meta}>{t("vendeur.lead.client.ville", { ville: opportunite.ville ?? absent })}</Text>
      <Text style={styles.meta}>{t("vendeur.lead.client.canal", { canal: opportunite.canal ?? absent })}</Text>
      {opportunite.source !== null ? <Text style={styles.meta}>{t("vendeur.lead.client.source", { source: opportunite.source })}</Text> : null}
      {opportunite.prochaineAction !== null ? (
        <Text style={styles.meta}>
          {t("vendeur.lead.client.prochaineAction", {
            description: opportunite.prochaineAction.description,
            echeance:
              opportunite.prochaineAction.echeance === null
                ? absent
                : formaterDepuis(opportunite.prochaineAction.echeance, decalageMinutesUTC),
          })}
        </Text>
      ) : null}
    </View>
  );
}

function Historique({
  client,
  leadId,
  decalageMinutesUTC,
}: {
  readonly client: Client360;
  readonly leadId: string;
  readonly decalageMinutesUTC: number;
}) {
  const { t } = useTranslation();
  const historique = historiqueDuLead(client, leadId);
  return (
    <View style={styles.carte}>
      <Text style={styles.sousTitre}>{t("vendeur.lead.historique.titre")}</Text>
      <Text style={styles.trace}>{t("vendeur.lead.historique.dernieres")}</Text>
      {historique.interactions.length === 0 ? <Text style={styles.vide}>{t("vendeur.lead.historique.aucune")}</Text> : null}
      {historique.interactions.map((interaction, index) => (
        <View key={`${interaction.horodatage}-${index}`} style={styles.ligne}>
          <Text style={styles.outil}>{interaction.resume}</Text>
          <Text style={styles.trace}>
            {formaterDepuis(interaction.horodatage, decalageMinutesUTC)} — {interaction.auteur}
            {interaction.systeme ? ` (${t("vendeur.lead.historique.systeme")})` : ""}
          </Text>
        </View>
      ))}
      {historique.autresOpportunites > 0 ? (
        <Text style={styles.avis}>{t("vendeur.lead.historique.autres", { nombre: historique.autresOpportunites })}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { padding: 16, gap: 12 },
  titre: { fontSize: 20, fontWeight: "600" },
  sousTitre: { fontSize: 14, fontWeight: "600" },
  vide: { color: "#666" },
  avis: { color: "#7a5b00" },
  erreur: { color: "#b00020" },
  succes: { color: "#1c6f5c" },
  meta: { color: "#444" },
  trace: { color: "#666", fontSize: 12 },
  donnee: { fontFamily: "monospace", fontSize: 13 },
  outil: { fontSize: 16, fontWeight: "600" },
  carte: { borderWidth: 1, borderColor: "#bbb", borderRadius: 8, padding: 12, gap: 6 },
  ligne: { gap: 2, paddingVertical: 4 },
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 8, minHeight: 72, textAlignVertical: "top" },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  boutonSecondaire: { borderWidth: 1, borderColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
});
