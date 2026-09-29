import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { chargerDigestDuJour, chargerGroupesDeChantiers, chargerPreparation } from "@/admin/service";
import type { GroupeInterventions } from "@/admin/chantiers";
import { Bouton, BoutonSecondaire, Carte, EtatSection, Ligne, Lignes, stylesAdmin as styles, TextesDuServeur } from "@/admin/composants";
import type { VueSection } from "@/ecrans/adminCommun";
import { presenterGroupes, vueDigest, vuePreparation } from "@/ecrans/chantiers";
import type { LigneIntervention, VueDigest, VueGroupe, VuePreparation } from "@/ecrans/chantiers";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import type { ResultatSection } from "@/admin/lecture";
import type { DigestDuJour } from "@/m4/dispatch";

/**
 * « Chantiers du jour » du propriétaire (§9.5 M4 « dispatch du jour, retards, file de complétion » ; PLAN T4.20) : les
 * interventions par statut (`m4_lister_interventions`, un appel par statut), le digest du jour (`m4_produire_digest`) et,
 * à la demande, la préparation d'une intervention (`m4_verifier_preparation`, volet par volet). Que des lectures : aucune
 * cédule n'est proposée ni appliquée, aucune intervention ne change d'état.
 *
 * Un manque de la préparation se dit en mots simples, par une phrase de l'app choisie d'après son code
 * (`src/ecrans/manquesM4.ts`) : jamais le texte de M4, qui cite le fichier du serveur et les commandes `opsys-metier`.
 *
 * La météo n'est pas lue ici, et l'écran le dit : la préparation ne dit que si les RÈGLES météo de l'entreprise sont
 * déclarées ; la prévision d'un créneau se juge par une cédule proposée, qui écrit au registre. Chaque groupe est lu POUR
 * LUI-MÊME : un groupe trop gros, refusé ou hors ligne sans copie dit pourquoi, il ne ressemble jamais à un groupe vide ;
 * une copie gardée est marquée avec sa date et sa raison. Toute la logique est dans `src/ecrans/chantiers.ts` et
 * `src/admin/`, testée là ; ce fichier n'est que le câblage React (non couvert en rendu, même limite que les autres écrans).
 */
type Chargement<T> = { readonly genre: "chargement" } | { readonly genre: "pret"; readonly valeur: T };

type EtatPreparation = "chargement" | VueSection<VuePreparation>;

export default function EcranChantiers() {
  const { t } = useTranslation();
  const decalage = -new Date().getTimezoneOffset();
  const [sansSession, setSansSession] = useState(false);
  const [groupes, setGroupes] = useState<Chargement<readonly GroupeInterventions[]>>({ genre: "chargement" });
  const [digest, setDigest] = useState<Chargement<ResultatSection<DigestDuJour>>>({ genre: "chargement" });
  const [preparations, setPreparations] = useState<Readonly<Record<string, EtatPreparation>>>({});
  const sequence = useRef(0);

  const charger = useCallback(async () => {
    const numero = ++sequence.current;
    setPreparations({});
    await Promise.all([
      chargerGroupesDeChantiers().then((lus) => {
        if (numero !== sequence.current) {
          return;
        }
        if (lus === null) {
          setSansSession(true);
          return;
        }
        setSansSession(false);
        setGroupes({ genre: "pret", valeur: lus });
      }),
      chargerDigestDuJour().then((lu) => {
        if (numero !== sequence.current) {
          return;
        }
        if (lu === null) {
          setSansSession(true);
          return;
        }
        setSansSession(false);
        setDigest({ genre: "pret", valeur: lu });
      }),
    ]);
  }, []);

  useFocusEffect(
    useCallback(() => {
      void charger();
    }, [charger]),
  );

  const verifier = useCallback(
    async (interventionId: string) => {
      const numero = sequence.current;
      setPreparations((precedentes) => ({ ...precedentes, [interventionId]: "chargement" }));
      const lu = await chargerPreparation(interventionId);
      if (numero !== sequence.current) {
        return;
      }
      if (lu === null) {
        setSansSession(true);
        return;
      }
      setPreparations((precedentes) => ({ ...precedentes, [interventionId]: vuePreparation(lu, decalage) }));
    },
    [decalage],
  );

  const vueGroupes: readonly VueGroupe[] | undefined = groupes.genre === "pret" ? presenterGroupes(groupes.valeur, decalage) : undefined;
  const vueDuDigest: VueSection<VueDigest> | undefined = digest.genre === "pret" ? vueDigest(digest.valeur, decalage) : undefined;

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("admin.chantiers.titre")}</Text>
      <BandeauIdentite />
      <Text style={styles.trace}>{t("admin.chantiers.lectureSeule")}</Text>
      <Text style={styles.avis}>{t("admin.chantiers.meteo")}</Text>
      <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />
      {sansSession ? (
        <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text>
      ) : (
        <>
          <Text style={styles.sousTitre}>{t("admin.chantiers.digestTitre")}</Text>
          <EtatSection vue={vueDuDigest} rendre={(contenu) => <DigestUI vue={contenu} />} />

          <Text style={styles.sousTitre}>{t("admin.chantiers.dispatchTitre")}</Text>
          {vueGroupes === undefined ? (
            <EtatSection vue={undefined} rendre={() => null} />
          ) : (
            vueGroupes.map((groupe) => (
              <Carte key={groupe.statut}>
                <Ligne m={groupe.titre} style={styles.petitTitre} />
                <EtatSection
                  vue={groupe.section}
                  rendre={(contenu) => (
                    <View style={{ gap: 8 }}>
                      <Ligne m={contenu.resume} style={styles.trace} />
                      {contenu.illisibles !== null ? <Ligne m={contenu.illisibles} style={styles.avis} /> : null}
                      {contenu.interventions.map((intervention) => (
                        <InterventionUI
                          key={intervention.interventionId}
                          intervention={intervention}
                          preparation={preparations[intervention.interventionId]}
                          onVerifier={() => void verifier(intervention.interventionId)}
                        />
                      ))}
                    </View>
                  )}
                />
              </Carte>
            ))
          )}
        </>
      )}
    </ScrollView>
  );
}

function InterventionUI({
  intervention,
  preparation,
  onVerifier,
}: {
  readonly intervention: LigneIntervention;
  readonly preparation: EtatPreparation | undefined;
  readonly onVerifier: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Carte>
      <Text style={styles.petitTitre}>{intervention.reference}</Text>
      <Ligne m={intervention.travaux} style={styles.meta} />
      <Ligne m={intervention.lead} style={styles.meta} />
      {intervention.devis !== null ? <Ligne m={intervention.devis} style={styles.meta} /> : null}
      <Ligne m={intervention.technicien} style={styles.meta} />
      {intervention.fenetre !== null ? <Ligne m={intervention.fenetre} style={styles.meta} /> : null}
      {intervention.preparable ? (
        <Bouton texte={preparation === "chargement" ? t("admin.chantiers.preparerEnCours") : t("admin.chantiers.preparer")} desactive={preparation === "chargement"} onPress={onVerifier} />
      ) : null}
      {preparation !== undefined && preparation !== "chargement" ? (
        <EtatSection vue={preparation} rendre={(contenu) => <PreparationUI vue={contenu} />} />
      ) : null}
    </Carte>
  );
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
