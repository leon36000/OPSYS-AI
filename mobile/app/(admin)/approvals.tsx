import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { chargerDemandesApprobation } from "@/approbations/service";
import type { AccuseDecision, DecisionApprobation, DemandeApprobation, ListeApprobations, VerdictServeurApprobation } from "@/approbations/contrat";
import {
  accuseDepuisResume,
  decisionsEnFile,
  creerMutationDecision,
  evaluerOffre,
  formaterArguments,
  formaterDepuis,
  issueAffichee,
  MOTIF_LONGUEUR_MAX,
} from "@/ecrans/approvals";
import type { DecisionEnFile, RaisonLectureSeule } from "@/ecrans/approvals";
import { demarrerDeclencheursVidange } from "@/outbox/declencheurs";
import { genererMutationId } from "@/outbox/id";
import { declencherVidange, obtenirDepot } from "@/outbox/service";
import { obtenirConfigurationAppel } from "@/protocole/configuration";

/**
 * `approvals.tsx` (§9.2 et §9.5 : « le propriétaire approuve tout depuis le téléphone », PLAN T1.4-f
 * étape 6). Liste les demandes d'approbation en attente (`m9_lister_demandes_approbation`) et envoie
 * chaque décision par la file sortante (`approval_decision` -> `m9_decider_demande_approbation`), avec
 * sa clé d'idempotence : une décision renvoyée ne s'applique qu'une fois.
 *
 * Fail-closed : rien d'inventé. La liste vient du serveur, sans cache (hors ligne, elle n'est pas montrée) ;
 * une demande n'a des boutons que si `evaluerOffre` (`src/ecrans/approvals.ts`) le permet — N5 et tout
 * ce que le serveur refuse restent en lecture seule, « à décider à la console » ; un verdict du serveur
 * est affiché tel quel. Toute la logique est dans `src/ecrans/approvals.ts` et `src/approbations/`, testée
 * là ; ce fichier n'est que le câblage React (non couvert en rendu, même limite que les autres écrans).
 */

type EtatListe =
  | { readonly genre: "chargement" }
  | { readonly genre: "sans_appairage" }
  | { readonly genre: "erreur"; readonly verdict: VerdictServeurApprobation }
  | { readonly genre: "pret"; readonly liste: ListeApprobations };

type ResultatSession =
  | { readonly genre: "accuse"; readonly accuse: AccuseDecision }
  | { readonly genre: "echec"; readonly verdict: VerdictServeurApprobation }
  | { readonly genre: "en_file" };

export default function EcranApprobations() {
  const { t } = useTranslation();
  const [etat, setEtat] = useState<EtatListe>({ genre: "chargement" });
  const [enFile, setEnFile] = useState<ReadonlyMap<string, DecisionEnFile>>(new Map());
  const [confirmation, setConfirmation] = useState<{ readonly id: string; readonly decision: DecisionApprobation } | null>(null);
  const [motifs, setMotifs] = useState<Readonly<Record<string, string>>>({});
  const [resultats, setResultats] = useState<Readonly<Record<string, ResultatSession>>>({});
  const [enTraitement, setEnTraitement] = useState<string | null>(null);
  const [erreurAppareil, setErreurAppareil] = useState(false);

  const charger = useCallback(async () => {
    const depot = await obtenirDepot();
    setEnFile(decisionsEnFile(await depot.lister()));
    const resultat = await chargerDemandesApprobation();
    if (resultat === null) {
      setEtat({ genre: "sans_appairage" });
    } else if (resultat.source === "serveur") {
      setEtat({ genre: "pret", liste: resultat.liste });
    } else {
      setEtat({ genre: "erreur", verdict: resultat.raison });
    }
  }, []);

  const rafraichir = useCallback(async () => {
    setEtat({ genre: "chargement" });
    // Une décision restée en file part d'abord : la liste qui suit reflète ce que le serveur sait.
    await declencherVidange().catch(() => null);
    await charger();
  }, [charger]);

  useEffect(() => {
    void charger();
    return demarrerDeclencheursVidange({ aoDeclenchement: () => void charger() });
  }, [charger]);

  const decider = useCallback(
    async (demande: DemandeApprobation, decision: DecisionApprobation) => {
      const configuration = obtenirConfigurationAppel();
      if (!configuration) {
        setErreurAppareil(true);
        return;
      }
      setErreurAppareil(false);
      setConfirmation(null);
      setEnTraitement(demande.id);
      try {
        const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
        const mutation = creerMutationDecision(demande.id, decision, motifs[demande.id] ?? "", genererMutationId, horloge);
        const depot = await obtenirDepot();
        const persistee = await depot.inserer(mutation);

        // Tentative immédiate, best-effort : hors ligne, la décision reste en file avec sa clé.
        const rapport = await declencherVidange();
        const echec = rapport?.echecsPermanents.find((e) => e.id === persistee.id);
        const acceptee = rapport?.resultatsAcceptes.find((r) => r.id === persistee.id);
        const accuse = acceptee ? accuseDepuisResume(acceptee.resume) : null;
        setResultats((precedents) => ({
          ...precedents,
          [demande.id]: echec
            ? { genre: "echec", verdict: echec.verdict }
            : accuse
              ? { genre: "accuse", accuse }
              : { genre: "en_file" },
        }));
        await charger();
      } finally {
        setEnTraitement(null);
      }
    },
    [motifs, charger],
  );

  const decalageMinutesUTC = -new Date().getTimezoneOffset();
  const dernieresDecisions = Object.entries(resultats);

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("approvals.titre")}</Text>

      <Pressable style={styles.boutonSecondaire} disabled={etat.genre === "chargement"} onPress={() => void rafraichir()}>
        <Text style={styles.boutonSecondaireTexte}>{t("approvals.rafraichir")}</Text>
      </Pressable>

      {erreurAppareil ? <Text style={styles.erreur}>{t("approvals.appareilNonAppaire")}</Text> : null}

      {dernieresDecisions.length > 0 ? (
        <View style={styles.carte}>
          <Text style={styles.sousTitre}>{t("approvals.decisionsDeLaSession")}</Text>
          {dernieresDecisions.map(([id, resultat]) => (
            <ResultatDecision key={id} demandeId={id} resultat={resultat} decalageMinutesUTC={decalageMinutesUTC} />
          ))}
        </View>
      ) : null}

      {etat.genre === "chargement" ? <ActivityIndicator /> : null}
      {etat.genre === "sans_appairage" ? <Text style={styles.erreur}>{t("approvals.appareilNonAppaire")}</Text> : null}
      {etat.genre === "erreur" ? (
        <Text style={styles.erreur}>
          {t("approvals.echecChargement", { code: etat.verdict.code, detail: etat.verdict.detail })}
        </Text>
      ) : null}

      {etat.genre === "pret" ? (
        <>
          {!etat.liste.proprietaire ? <Text style={styles.avis}>{t("approvals.lectureSeuleProprietaire")}</Text> : null}
          <Text style={styles.compte}>{t("approvals.enAttente", { total: etat.liste.totalEnAttente })}</Text>
          {etat.liste.demandes.length === 0 && etat.liste.illisibles === 0 ? (
            <Text style={styles.vide}>{t("approvals.aucuneDemande")}</Text>
          ) : null}
          {etat.liste.illisibles > 0 ? (
            <Text style={styles.avis}>{t("approvals.illisibles", { nombre: etat.liste.illisibles })}</Text>
          ) : null}

          {etat.liste.demandes.map((demande) => (
            <CarteDemande
              key={demande.id}
              demande={demande}
              proprietaire={etat.liste.proprietaire}
              enFile={enFile.get(demande.id) ?? null}
              confirmation={confirmation?.id === demande.id ? confirmation.decision : null}
              motif={motifs[demande.id] ?? ""}
              occupe={enTraitement !== null}
              decalageMinutesUTC={decalageMinutesUTC}
              onMotif={(texte) => setMotifs((precedents) => ({ ...precedents, [demande.id]: texte }))}
              onDemanderConfirmation={(decision) => setConfirmation({ id: demande.id, decision })}
              onAnnuler={() => setConfirmation(null)}
              onConfirmer={(decision) => void decider(demande, decision)}
            />
          ))}

          {etat.liste.reste > 0 ? <Text style={styles.avis}>{t("approvals.reste", { nombre: etat.liste.reste })}</Text> : null}
        </>
      ) : null}
    </ScrollView>
  );
}

interface ProprietesResultat {
  readonly demandeId: string;
  readonly resultat: ResultatSession;
  readonly decalageMinutesUTC: number;
}

/** Ce que le serveur a répondu à une décision de cette session — ses mots, pas les nôtres. */
function ResultatDecision({ demandeId, resultat, decalageMinutesUTC }: ProprietesResultat) {
  const { t } = useTranslation();
  if (resultat.genre === "en_file") {
    return (
      <Text style={styles.avis}>
        {demandeId} — {t("approvals.enFileHorsLigne")}
      </Text>
    );
  }
  if (resultat.genre === "echec") {
    return (
      <Text style={styles.erreur}>
        {demandeId} — {t("approvals.echecDefinitif", { code: resultat.verdict.code, detail: resultat.verdict.detail })}
      </Text>
    );
  }
  const issue = issueAffichee(resultat.accuse);
  const texte =
    issue.genre === "executee_refusee_par_l_outil"
      ? t("approvals.resultat.executee_refusee_par_l_outil", {
          code: issue.verdict?.code ?? "",
          detail: issue.verdict?.detail ?? "",
        })
      : issue.genre === "echec_execution"
        ? t("approvals.resultat.echec_execution", { detail: issue.detail })
        : t(`approvals.resultat.${issue.genre}`);
  const problematique = issue.genre === "echec_execution" || issue.genre === "executee_refusee_par_l_outil";
  return (
    <View style={styles.ligneResultat}>
      <Text style={problematique ? styles.erreur : styles.succes}>
        {resultat.accuse.outil || demandeId} — {texte}
      </Text>
      <Text style={styles.trace}>
        {t("approvals.resultat.tracee", {
          decidePar: resultat.accuse.decidePar,
          role: resultat.accuse.role,
          date: resultat.accuse.decideLe ? formaterDepuis(resultat.accuse.decideLe, decalageMinutesUTC) : "",
        })}
      </Text>
    </View>
  );
}

interface ProprietesCarte {
  readonly demande: DemandeApprobation;
  readonly proprietaire: boolean;
  readonly enFile: DecisionEnFile | null;
  readonly confirmation: DecisionApprobation | null;
  readonly motif: string;
  readonly occupe: boolean;
  readonly decalageMinutesUTC: number;
  readonly onMotif: (texte: string) => void;
  readonly onDemanderConfirmation: (decision: DecisionApprobation) => void;
  readonly onAnnuler: () => void;
  readonly onConfirmer: (decision: DecisionApprobation) => void;
}

function texteLectureSeule(raison: RaisonLectureSeule, t: TFunction): string {
  if (raison.genre === "serveur") {
    return t("approvals.lectureSeule.serveur", { code: raison.verdict.code, detail: raison.verdict.detail });
  }
  return t(`approvals.lectureSeule.${raison.genre}`);
}

/** Une demande : ce qu'elle est, ses arguments exacts, puis des boutons SI `evaluerOffre` les permet,
 * sinon la raison — le mot du serveur quand il en a un. Une décision en file n'a plus de boutons. */
function CarteDemande(props: ProprietesCarte) {
  const { t } = useTranslation();
  const { demande, confirmation } = props;
  const offre = evaluerOffre(demande, props.proprietaire);
  const arguments_ = demande.arguments !== null ? formaterArguments(demande.arguments) : null;

  return (
    <View style={styles.carte}>
      <Text style={styles.outil}>{demande.outil}</Text>
      <Text style={styles.meta}>
        {demande.niveau !== null ? t("approvals.niveau", { niveau: demande.niveau }) : t("approvals.niveauInconnu")}
        {" · "}
        {t("approvals.depuis", { date: formaterDepuis(demande.depuis, props.decalageMinutesUTC) })}
      </Text>
      <Text style={styles.meta}>{t("approvals.departement", { nom: demande.departementNom ?? demande.departement })}</Text>
      {demande.descriptionOutil ? <Text style={styles.description}>{demande.descriptionOutil}</Text> : null}
      {demande.motifDemande ? <Text style={styles.meta}>{t("approvals.motifDemande", { motif: demande.motifDemande })}</Text> : null}

      {arguments_ !== null ? (
        <View style={styles.arguments}>
          <Text style={styles.sousTitre}>{t("approvals.argumentsTitre")}</Text>
          {arguments_.map((argument) => (
            <Text key={argument.cle} style={styles.argument}>
              {argument.cle} : {argument.valeur}
            </Text>
          ))}
        </View>
      ) : (
        <Text style={styles.meta}>{t("approvals.argumentsNonAffiches")}</Text>
      )}

      {props.enFile ? (
        <Text style={styles.avis}>{t(`approvals.decisionEnFile.${props.enFile.decision}`)}</Text>
      ) : !offre.decidable ? (
        <Text style={styles.lectureSeule}>{texteLectureSeule(offre.raison, t)}</Text>
      ) : confirmation !== null ? (
        <View style={styles.boutons}>
          <Pressable
            style={({ pressed }) => [confirmation === "approuver" ? styles.bouton : styles.boutonDanger, pressed ? styles.boutonPresse : null]}
            disabled={props.occupe}
            onPress={() => props.onConfirmer(confirmation)}
          >
            <Text style={styles.boutonTexte}>
              {confirmation === "approuver" ? t("approvals.confirmerApprouver") : t("approvals.confirmerRefuser")}
            </Text>
          </Pressable>
          <Pressable style={styles.boutonSecondaire} disabled={props.occupe} onPress={props.onAnnuler}>
            <Text style={styles.boutonSecondaireTexte}>{t("approvals.annuler")}</Text>
          </Pressable>
        </View>
      ) : (
        <>
          <TextInput
            style={styles.champ}
            placeholder={t("approvals.champMotif")}
            value={props.motif}
            onChangeText={props.onMotif}
            maxLength={MOTIF_LONGUEUR_MAX}
            editable={!props.occupe}
            accessibilityLabel={t("approvals.champMotif")}
          />
          <View style={styles.boutons}>
            <Pressable
              style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
              disabled={props.occupe}
              onPress={() => props.onDemanderConfirmation("approuver")}
            >
              <Text style={styles.boutonTexte}>{t("approvals.approuver")}</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.boutonDanger, pressed ? styles.boutonPresse : null]}
              disabled={props.occupe}
              onPress={() => props.onDemanderConfirmation("refuser")}
            >
              <Text style={styles.boutonTexte}>{t("approvals.refuser")}</Text>
            </Pressable>
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { padding: 16, gap: 12 },
  titre: { fontSize: 20, fontWeight: "600" },
  sousTitre: { fontSize: 14, fontWeight: "600" },
  compte: { color: "#444" },
  vide: { color: "#666" },
  avis: { color: "#7a5b00" },
  erreur: { color: "#b00020" },
  succes: { color: "#1c6f5c" },
  trace: { color: "#666", fontSize: 12 },
  lectureSeule: { color: "#444", fontStyle: "italic" },
  carte: { borderWidth: 1, borderColor: "#bbb", borderRadius: 8, padding: 12, gap: 6 },
  outil: { fontSize: 16, fontWeight: "600" },
  meta: { color: "#444" },
  description: { color: "#333" },
  arguments: { gap: 2, marginTop: 4 },
  argument: { fontFamily: "monospace", fontSize: 13 },
  ligneResultat: { gap: 2 },
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 8, marginTop: 6 },
  boutons: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 6 },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6 },
  boutonDanger: { backgroundColor: "#8a1c1c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6 },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  boutonSecondaire: { borderWidth: 1, borderColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
});
