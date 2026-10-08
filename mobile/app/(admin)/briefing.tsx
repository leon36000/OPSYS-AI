import { useNetInfo } from "@react-native-community/netinfo";
import { capturerSessionAdminLecture } from "@/protocole/configuration";
import { useEtatIdentite } from "@/roles/contexte";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { useTranslation } from "react-i18next";
import {
  chargerBriefingM9,
  chargerSuiteBriefingM9,
  chargerAlertesM9,
  chargerEtatConsolideM9,
  chargerLectureStrategiqueM9,
  actualiserConnectiviteBriefingM9,
} from "@/admin/service";
import {
  BoutonSecondaire,
  Carte,
  EtatSection,
  Ligne,
  Lignes,
  stylesAdmin as styles,
} from "@/admin/composants";
import type { ResultatSection } from "@/admin/lecture";
import { instantLocal } from "@/admin/horloge";
import { presenterSection, message } from "@/ecrans/adminCommun";
import { presenterItemM9, presenterManqueM9, presenterContradictionM9 } from "@/ecrans/briefing";
import { presenterLectureStrategique } from "@/ecrans/lectureStrategique";
import type { LectureStrategiqueM9 } from "@/m9/lectureStrategique";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { SECTIONS_BRIEFING } from "@/m9/briefing";
import type {
  BriefingM9,
  SuiteBriefingM9,
  AlertesM9,
  EtatConsolideM9,
  SectionBriefing,
  ItemM9,
} from "@/m9/briefing";

type Pages = Partial<Record<SectionBriefing, ResultatSection<SuiteBriefingM9>>>;
/** T4.21 : des pages courantes séparées ; aucune concaténation qui prétendrait reconstituer un snapshot. */
export default function EcranBriefing() {
  const { t } = useTranslation();
  const identite = useEtatIdentite(), connectee = useNetInfo().isConnected === true;
  const garde = useRef<(() => boolean) | null>(null);
  const [briefing, setBriefing] = useState<ResultatSection<BriefingM9>>();
  const [alertes, setAlertes] = useState<ResultatSection<AlertesM9>>();
  const [etat, setEtat] = useState<ResultatSection<EtatConsolideM9>>();
  const [strategique, setStrategique] = useState<ResultatSection<LectureStrategiqueM9>>();
  const [pages, setPages] = useState<Pages>({});
  const [sansSession, setSansSession] = useState(false);
  const [enCours, setEnCours] = useState<readonly string[]>([]);
  const sequence = useRef(0),
    reference = useRef("");
  const demandes = useRef(new Set<string>());
  const decalage = -new Date().getTimezoneOffset();
  const charger = useCallback(async () => {
    const numero = ++sequence.current, capture = capturerSessionAdminLecture();
    garde.current = capture.session ? capture.courante : null;
    actualiserConnectiviteBriefingM9(connectee);
    reference.current = instantLocal({
      maintenant: new Date(),
      decalageMinutesUTC: -new Date().getTimezoneOffset(),
    });
    const maintenant = reference.current;
    demandes.current = new Set();
    setEnCours([]);
    setPages({});
    setBriefing(undefined);
    setAlertes(undefined);
    setEtat(undefined);
    setStrategique(undefined);
    setSansSession(!capture.session || !capture.courante());
    if (!capture.session || !capture.courante()) return;
    const recevoir =
      <T,>(poser: (v: ResultatSection<T>) => void) =>
      (lu: ResultatSection<T> | null) => {
        if (numero !== sequence.current || garde.current?.() !== true) return;
        if (lu === null) {
          setSansSession(true);
          return;
        }
        setSansSession(false);
        poser(lu);
      };
    await Promise.all([
      chargerBriefingM9(maintenant).then(recevoir(setBriefing)).catch(() => recevoir(setBriefing)(indisponible)),
      chargerAlertesM9().then(recevoir(setAlertes)).catch(() => recevoir(setAlertes)(indisponible)),
      chargerEtatConsolideM9().then(recevoir(setEtat)).catch(() => recevoir(setEtat)(indisponible)),
      chargerLectureStrategiqueM9(maintenant).then(recevoir(setStrategique)).catch(() => recevoir(setStrategique)(indisponible)),
    ]);
  }, [connectee]);
  useFocusEffect(
    useCallback(() => {
      void charger();
      return () => {
        sequence.current += 1;
        garde.current = null;
      };
    }, [charger, identite]),
  );
  const suite = async (cle: SectionBriefing | "registre_alertes" | "preuves", depart: number) => {
    if (!connectee || garde.current?.() !== true || demandes.current.has(cle)) return;
    const numero = sequence.current,
      requetes = demandes.current;
    requetes.add(cle);
    setEnCours([...requetes]);
    try {
      if (cle === "preuves") {
        const lu = await chargerLectureStrategiqueM9(reference.current, depart);
        if (numero === sequence.current && garde.current?.() === true) {
          if (lu === null) setSansSession(true);
          else setStrategique(lu);
        }
      } else if (cle === "registre_alertes") {
        const lu = await chargerAlertesM9(depart);
        if (numero === sequence.current && garde.current?.() === true) {
          if (lu === null) setSansSession(true);
          else setAlertes(lu);
        }
      } else {
        const lu = await chargerSuiteBriefingM9(reference.current, cle, depart);
        if (numero === sequence.current && garde.current?.() === true) {
          if (lu === null) setSansSession(true);
          else setPages((old) => ({ ...old, [cle]: lu }));
        }
      }
    } catch {
      if (numero === sequence.current && garde.current?.() === true) {
        if (cle === "preuves") setStrategique(indisponible);
        else if (cle === "registre_alertes") setAlertes(indisponible);
        else setPages(old => ({ ...old, [cle]: indisponible }));
      }
    } finally {
      requetes.delete(cle);
      if (numero === sequence.current && garde.current?.() === true) setEnCours([...requetes]);
    }
  };
  const vue = <T,>(lu: ResultatSection<T> | undefined) =>
    lu ? presenterSection(lu, decalage, (v) => v) : undefined;
  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("admin.briefing.titre")}</Text>
      <BandeauIdentite />
      <Text style={styles.avis}>{t("admin.briefing.courant")}</Text>
      <Text style={styles.trace}>{t("admin.briefing.aucuneDecision")}</Text>
      <BoutonSecondaire texte={t("admin.commun.rafraichir")} onPress={() => void charger()} />
      {sansSession || garde.current?.() !== true ? (
        <Text style={styles.erreur}>{t("admin.commun.sansSession")}</Text>
      ) : (
        <>
          <Carte>
            <Text style={styles.sousTitre}>{t("admin.lectureStrategique.titre")}</Text>
            <EtatSection vue={strategique ? presenterSection(strategique, decalage, v => presenterLectureStrategique(v, decalage)) : undefined}
              rendre={v => <>
                <Lignes items={v.lignes} />
                <Lignes items={v.preuves} />
                {v.metriques.map((m, i) => <View key={i}><Ligne m={m.titre} style={styles.sousTitre} /><Lignes items={m.lignes} /></View>)}
                <Lignes items={v.manques} />
                {v.lectures.map((m, i) => <View key={i}><Ligne m={m.titre} style={styles.sousTitre} /><Lignes items={m.lignes} /></View>)}
                <Lignes items={v.pagination} />
                {strategique?.source === "serveur" && strategique.valeur.affichage.prochain_depart !== null ?
                  <BoutonSecondaire texte={t("admin.lectureStrategique.suivante")} desactive={!connectee || enCours.includes("preuves")}
                    onPress={() => void suite("preuves", strategique.valeur.affichage.prochain_depart!)} /> : null}
                <BoutonSecondaire texte={t("admin.lectureStrategique.relire")} desactive={!connectee || enCours.includes("preuves")}
                  onPress={() => void suite("preuves", 0)} />
              </>} />
          </Carte>
          <EtatSection
            vue={vue(briefing)}
            rendre={(b) => (
              <>
                <Ligne
                  m={message("admin.briefing.reference", { jour: b.jour, veille: b.veille })}
                  style={styles.trace}
                />
                {briefing?.source === "cache" ? (
                  <Text style={styles.avis}>{t("admin.briefing.cacheSansSuite")}</Text>
                ) : null}
                {SECTIONS_BRIEFING.map((cle) => (
                  <Carte key={cle}>
                    <Text style={styles.sousTitre}>{t(`admin.briefing.sections.${cle}`)}</Text>
                    {pages[cle] ? (
                      <EtatSection
                        vue={vue(pages[cle])}
                        rendre={(p) => (
                          <>
                            <Items items={p.items} decalage={decalage} />
                            <Ligne
                              m={message("admin.briefing.page", {
                                depart: p.depart,
                                reste: p.reste,
                              })}
                              style={styles.trace}
                            />
                            {p.prochain_depart !== null ? (
                              <BoutonSecondaire
                                texte={t("admin.briefing.voirPlus")}
                                desactive={enCours.includes(cle)}
                                onPress={() => void suite(cle, p.prochain_depart!)}
                              />
                            ) : null}
                          </>
                        )}
                      />
                    ) : (
                      <>
                        <Items
                          items={b.sections[cle].items}
                          decalage={decalage}
                          vide={b.sections[cle].vide}
                        />
                        {b.affichage.non_affiches[cle] > 0 ? (
                          <Ligne
                            m={message("admin.briefing.reste", {
                              nombre: b.affichage.non_affiches[cle],
                            })}
                            style={styles.avis}
                          />
                        ) : null}
                        {briefing?.source === "serveur" && b.affichage.non_affiches[cle] > 0 ? (
                          <BoutonSecondaire
                            texte={t("admin.briefing.voirPlus")}
                            desactive={enCours.includes(cle)}
                            onPress={() => void suite(cle, b.sections[cle].items.length)}
                          />
                        ) : null}
                      </>
                    )}
                  </Carte>
                ))}
                <Carte>
                  <Text style={styles.sousTitre}>
                    {t("admin.briefing.sections.manques_pour_conclure")}
                  </Text>
                  {b.sections.manques_pour_conclure.vide ? (
                    <Text style={styles.vide}>{t("admin.briefing.vide")}</Text>
                  ) : null}
                  {b.sections.manques_pour_conclure.items.map((item, i) => {
                    const lignes = presenterManqueM9(item);
                    return (
                      <View key={i}>
                        <Ligne m={lignes.titre} />
                        <Lignes items={lignes.lignes} style={styles.trace} />
                      </View>
                    );
                  })}
                </Carte>
              </>
            )}
          />
          <Carte>
            <Text style={styles.sousTitre}>{t("admin.briefing.alertes")}</Text>
            <EtatSection
              vue={vue(alertes)}
              rendre={(a) => (
                <>
                  <Items items={a.alertes} decalage={decalage} />
                  <Ligne
                    m={message("admin.briefing.page", { depart: a.depart, reste: a.reste })}
                    style={styles.trace}
                  />
                  {alertes?.source === "serveur" && a.prochain_depart !== null ? (
                    <BoutonSecondaire
                      texte={t("admin.briefing.voirPlus")}
                      desactive={enCours.includes("registre_alertes")}
                      onPress={() => void suite("registre_alertes", a.prochain_depart!)}
                    />
                  ) : null}
                </>
              )}
            />
          </Carte>
          <Carte>
            <Text style={styles.sousTitre}>{t("admin.briefing.etat")}</Text>
            <EtatSection
              vue={vue(etat)}
              rendre={(e) => (
                <>
                  {Object.keys(e.faits_par_module).length === 0 ? (
                    <Text style={styles.vide}>{t("admin.briefing.aucunFait")}</Text>
                  ) : (
                    <Items items={Object.values(e.faits_par_module)} decalage={decalage} />
                  )}
                  <Ligne
                    m={message("admin.briefing.contradictions", {
                      nombre: e.contradictions.length,
                    })}
                    style={styles.avis}
                  />
                  {e.contradictions.map((c, i) => (
                    <Ligne key={i} m={presenterContradictionM9(c, decalage)} style={styles.avis} />
                  ))}
                </>
              )}
            />
          </Carte>
        </>
      )}
    </ScrollView>
  );
}

const indisponible = { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } } as const;
function Items({
  items,
  decalage,
  vide,
}: {
  readonly items: readonly ItemM9[];
  readonly decalage: number;
  readonly vide?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <View style={{ gap: 8 }}>
      {items.length === 0 && vide !== false ? (
        <Text style={styles.vide}>{t("admin.briefing.vide")}</Text>
      ) : null}
      {items.map((item, i) => {
        const p = presenterItemM9(item, decalage);
        return (
          <View key={i}>
            <Ligne m={p.titre} style={styles.petitTitre} />
            <Lignes items={p.lignes} style={styles.trace} />
          </View>
        );
      })}
    </View>
  );
}
