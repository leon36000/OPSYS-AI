import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useTranslation } from "react-i18next";

import {
  basculerSegment,
  basculerStatut,
  etatSegment,
  listeVide,
  presenterLead,
  vueLeads,
} from "@/ecrans/leads";
import type { CarteLead } from "@/ecrans/leads";
import { formaterDepuis } from "@/ecrans/approvals";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { CODE_SEGMENT_NON_CALCULABLE, FILTRE_AUCUN, SEGMENTS_LEAD, STATUTS_LEAD } from "@/m2/listeLeads";
import type { FiltreLeads, SegmentNonCalculable } from "@/m2/listeLeads";
import type { ResultatLeads } from "@/vendeur/chargeurLeads";
import type { LeadsLus, RaisonRelecture } from "@/vendeur/lectureLeads";
import { chargerLeads, chargerSuiteLeads } from "@/vendeur/service";
import type { VerdictServeur } from "@/outbox/vidangeur";

/**
 * `leads.tsx` (§9.4 « ses leads », pipeline personnel ; M2.11 ; PLAN T4.8) : la liste de SES leads
 * (`m2_lister_leads`), paginée (`decalage`, `suivant`), avec un filtre par statut et par segment. Lecture d'abord,
 * cache SQLite hors ligne marqué comme tel (date du cache, raison).
 *
 * Fail-closed : rien d'inventé. La portée (« ses leads ») est celle du serveur ; un segment que M2 ne peut pas
 * calculer est montré comme « non calculable, manque X », jamais comme une liste vide ; une valeur absente est dite
 * absente. Toute la logique est dans `src/ecrans/leads.ts` et `src/vendeur/`, testée là ; ce fichier n'est que le
 * câblage React (non couvert en rendu, même limite que les autres écrans).
 */

type EtatSuite =
  | { readonly genre: "repos" }
  | { readonly genre: "chargement" }
  | { readonly genre: "echec"; readonly verdict: VerdictServeur }
  | { readonly genre: "relue"; readonly raison: RaisonRelecture };

export default function EcranLeads() {
  const { t } = useTranslation();
  const router = useRouter();
  const [filtre, setFiltre] = useState<FiltreLeads>(FILTRE_AUCUN);
  const [resultat, setResultat] = useState<ResultatLeads | null | undefined>(undefined);
  const [chargement, setChargement] = useState(true);
  const [suite, setSuite] = useState<EtatSuite>({ genre: "repos" });
  const [regles, setRegles] = useState<ReadonlySet<string>>(new Set());
  // Ce que M2 a dit ne pas pouvoir calculer, gardé d'une lecture à l'autre : il pilote la mise en forme des filtres.
  const [nonCalculables, setNonCalculables] = useState<readonly SegmentNonCalculable[] | null>(null);
  const sequence = useRef(0);
  const nonCalculablesRef = useRef<readonly SegmentNonCalculable[] | null>(null);

  const charger = useCallback(async (f: FiltreLeads) => {
    const numero = ++sequence.current;
    setChargement(true);
    setSuite({ genre: "repos" });
    try {
      // Un segment que M2 a déjà dit non calculable n'est pas redemandé : son « manque X » est celui du serveur.
      const etat = f.segment === null ? null : etatSegment(f.segment, nonCalculablesRef.current);
      const lu: ResultatLeads | null =
        etat !== null && !etat.calculable
          ? { source: "refus", verdict: { code: CODE_SEGMENT_NON_CALCULABLE, detail: etat.manque } }
          : await chargerLeads(f);
      if (numero !== sequence.current) {
        return;
      }
      setResultat(lu);
      const vue = vueLeads(lu);
      if (vue.genre === "liste") {
        nonCalculablesRef.current = vue.lus.segmentsNonCalculables;
        setNonCalculables(vue.lus.segmentsNonCalculables);
      }
    } finally {
      if (numero === sequence.current) {
        setChargement(false);
      }
    }
  }, []);

  useEffect(() => {
    void charger(filtre);
  }, [charger, filtre]);

  const voirPlus = useCallback(
    async (lus: LeadsLus) => {
      setSuite({ genre: "chargement" });
      const issue = await chargerSuiteLeads(lus);
      if (issue === null) {
        setResultat(null);
        setSuite({ genre: "repos" });
      } else if (issue.genre === "fusionnee") {
        setResultat({ source: "serveur", lus: issue.lus });
        setSuite({ genre: "repos" });
      } else if (issue.genre === "a_relire") {
        await charger(filtre);
        setSuite({ genre: "relue", raison: issue.raison });
      } else if (issue.genre === "echec") {
        setSuite({ genre: "echec", verdict: issue.verdict });
      } else {
        setSuite({ genre: "repos" });
      }
    },
    [charger, filtre],
  );

  const basculerRegles = useCallback((leadId: string) => {
    setRegles((precedentes) => {
      const suivantes = new Set(precedentes);
      if (suivantes.has(leadId)) {
        suivantes.delete(leadId);
      } else {
        suivantes.add(leadId);
      }
      return suivantes;
    });
  }, []);

  const decalageMinutesUTC = -new Date().getTimezoneOffset();
  const vue = resultat === undefined ? null : vueLeads(resultat);

  return (
    <ScrollView contentContainerStyle={styles.conteneur}>
      <Text style={styles.titre}>{t("vendeur.leads.titre")}</Text>
      <BandeauIdentite />

      <Pressable style={styles.boutonSecondaire} disabled={chargement} onPress={() => void charger(filtre)}>
        <Text style={styles.boutonSecondaireTexte}>{t("vendeur.commun.rafraichir")}</Text>
      </Pressable>

      <Text style={styles.sousTitre}>{t("vendeur.leads.filtreStatut")}</Text>
      <View style={styles.puces}>
        <Puce texte={t("vendeur.leads.tous")} active={filtre.statut === null} onPress={() => setFiltre({ ...filtre, statut: null })} />
        {STATUTS_LEAD.map((statut) => (
          <Puce
            key={statut}
            texte={t(`vendeur.statuts.${statut}`, { defaultValue: statut })}
            active={filtre.statut === statut}
            onPress={() => setFiltre(basculerStatut(filtre, statut))}
          />
        ))}
      </View>

      <Text style={styles.sousTitre}>{t("vendeur.leads.filtreSegment")}</Text>
      <View style={styles.puces}>
        <Puce texte={t("vendeur.leads.tous")} active={filtre.segment === null} onPress={() => setFiltre({ ...filtre, segment: null })} />
        {SEGMENTS_LEAD.map((segment) => {
          const calculable = etatSegment(segment, nonCalculables).calculable;
          return (
            <Puce
              key={segment}
              texte={
                t(`vendeur.segments.${segment}`, { defaultValue: segment }) +
                (calculable ? "" : ` (${t("vendeur.leads.badgeNonCalculable")})`)
              }
              active={filtre.segment === segment}
              attenuee={!calculable}
              onPress={() => setFiltre(basculerSegment(filtre, segment))}
            />
          );
        })}
      </View>

      {chargement ? <ActivityIndicator /> : null}

      {vue?.genre === "sans_appairage" ? <Text style={styles.erreur}>{t("vendeur.commun.sansSession")}</Text> : null}
      {vue?.genre === "aucune" ? (
        <Text style={styles.erreur}>{t("vendeur.commun.echecLecture", { code: vue.raison.code, detail: vue.raison.detail })}</Text>
      ) : null}
      {vue?.genre === "refus" ? (
        <Text style={styles.erreur}>{t("vendeur.commun.refus", { code: vue.verdict.code, detail: vue.verdict.detail })}</Text>
      ) : null}
      {vue?.genre === "segment_non_calculable" ? (
        <Text style={styles.avis}>{t("vendeur.leads.segmentNonCalculable", { detail: vue.verdict.detail })}</Text>
      ) : null}

      {vue?.genre === "liste" ? (
        <>
          {vue.cache !== null ? (
            <Text style={styles.avis}>
              {t("vendeur.commun.cache", { date: formaterDepuis(vue.cache.misAJourLe, decalageMinutesUTC), code: vue.cache.raison.code })}
            </Text>
          ) : null}
          <Text style={styles.compte}>{t("vendeur.leads.total", { total: vue.lus.total })}</Text>
          {vue.lus.segmentsNonCalculables.length > 0 ? (
            <View style={styles.carte}>
              <Text style={styles.sousTitre}>
                {t("vendeur.leads.segmentsNonCalculablesTitre", { nombre: vue.lus.segmentsNonCalculables.length })}
              </Text>
              {vue.lus.segmentsNonCalculables.map((n) => (
                <Text key={n.segment} style={styles.meta}>
                  {t(`vendeur.segments.${n.segment}`, { defaultValue: n.segment })} : {n.manque}
                </Text>
              ))}
            </View>
          ) : null}
          {listeVide(vue.lus) ? <Text style={styles.vide}>{t("vendeur.leads.aucunLead")}</Text> : null}
          {vue.lus.illisibles > 0 ? <Text style={styles.avis}>{t("vendeur.leads.illisibles", { nombre: vue.lus.illisibles })}</Text> : null}
          {vue.lus.indetermines > 0 ? (
            <Text style={styles.avis}>{t("vendeur.leads.indetermines", { nombre: vue.lus.indetermines })}</Text>
          ) : null}

          {vue.lus.leads.map((lead) => (
            <CarteDeLead
              key={lead.leadId}
              carte={presenterLead(lead, vue.lus.regles)}
              reglesVisibles={regles.has(lead.leadId)}
              decalageMinutesUTC={decalageMinutesUTC}
              onOuvrir={() => router.push({ pathname: "/lead/[id]", params: { id: lead.leadId } })}
              onBasculerRegles={() => basculerRegles(lead.leadId)}
            />
          ))}

          {vue.cache === null && vue.lus.suivant !== null ? (
            <Pressable style={styles.boutonSecondaire} disabled={suite.genre === "chargement"} onPress={() => void voirPlus(vue.lus)}>
              <Text style={styles.boutonSecondaireTexte}>
                {suite.genre === "chargement"
                  ? t("vendeur.leads.chargementSuite")
                  : t("vendeur.leads.voirPlus", { nombre: vue.lus.reste })}
              </Text>
            </Pressable>
          ) : null}
          {vue.cache !== null && vue.lus.suivant !== null ? (
            <Text style={styles.avis}>
              {t("vendeur.leads.listePartielleCache", { nombre: vue.lus.leads.length, total: vue.lus.total })}
            </Text>
          ) : null}
          {suite.genre === "echec" ? (
            <Text style={styles.erreur}>{t("vendeur.leads.echecSuite", { code: suite.verdict.code, detail: suite.verdict.detail })}</Text>
          ) : null}
          {suite.genre === "relue" ? (
            <Text style={styles.avis}>{t(suite.raison === "liste_changee" ? "vendeur.leads.listeChangee" : "vendeur.leads.pageIncoherente")}</Text>
          ) : null}
        </>
      ) : null}
    </ScrollView>
  );
}

interface ProprietesPuce {
  readonly texte: string;
  readonly active: boolean;
  readonly attenuee?: boolean;
  readonly onPress: () => void;
}

function Puce({ texte, active, attenuee = false, onPress }: ProprietesPuce) {
  return (
    <Pressable
      style={[styles.puce, active ? styles.puceActive : null, attenuee ? styles.puceAttenuee : null]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
    >
      <Text style={[styles.puceTexte, active ? styles.puceTexteActive : null]}>{texte}</Text>
    </Pressable>
  );
}

interface ProprietesCarte {
  readonly carte: CarteLead;
  readonly reglesVisibles: boolean;
  readonly decalageMinutesUTC: number;
  readonly onOuvrir: () => void;
  readonly onBasculerRegles: () => void;
}

/** Un lead : ce que M2 en rend, une valeur absente dite absente. Les règles citées (énoncé et donnée déclenchante) se
 * déplient ; les segments non calculables POUR CE LEAD sont dits, jamais tus. */
function CarteDeLead({ carte, reglesVisibles, decalageMinutesUTC, onOuvrir, onBasculerRegles }: ProprietesCarte) {
  const { t } = useTranslation();
  const absent = t("vendeur.commun.absent");
  return (
    <View style={styles.carte}>
      <Pressable onPress={onOuvrir} accessibilityRole="button" accessibilityLabel={t("vendeur.leads.ouvrir")}>
        <Text style={styles.outil}>{carte.travaux ?? absent}</Text>
        <Text style={styles.meta}>
          {carte.ville ?? absent}
          {" · "}
          {carte.statut === null ? absent : t(`vendeur.statuts.${carte.statut}`, { defaultValue: carte.statut })}
        </Text>
        <Text style={styles.trace}>{carte.leadId}</Text>
      </Pressable>
      {carte.urgent ? <Text style={styles.urgent}>{t("vendeur.leads.urgent")}</Text> : null}
      <Text style={styles.meta}>
        {carte.derniereActivite === null
          ? t("vendeur.leads.derniereActivite", { date: absent })
          : t("vendeur.leads.derniereActivite", { date: formaterDepuis(carte.derniereActivite, decalageMinutesUTC) })}
      </Text>
      <Text style={styles.meta}>
        {carte.prochaineAction === null
          ? t("vendeur.leads.aucuneProchaineAction")
          : t("vendeur.leads.prochaineAction", {
              description: carte.prochaineAction.description,
              echeance:
                carte.prochaineAction.echeance === null ? absent : formaterDepuis(carte.prochaineAction.echeance, decalageMinutesUTC),
            })}
      </Text>
      {carte.segments.length > 0 ? (
        <View style={styles.puces}>
          {carte.segments.map((s) => (
            <View key={s.segment} style={styles.badge}>
              <Text style={styles.badgeTexte}>{t(`vendeur.segments.${s.segment}`, { defaultValue: s.segment })}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {carte.segments.length > 0 ? (
        <Pressable onPress={onBasculerRegles} accessibilityRole="button">
          <Text style={styles.lien}>{reglesVisibles ? t("vendeur.leads.masquerRegles") : t("vendeur.leads.voirRegles")}</Text>
        </Pressable>
      ) : null}
      {reglesVisibles
        ? carte.segments.map((s) => (
            <View key={s.segment} style={styles.regle}>
              <Text style={styles.regleTitre}>{t(`vendeur.segments.${s.segment}`, { defaultValue: s.segment })}</Text>
              <Text style={styles.meta}>
                {s.enonce === null
                  ? t("vendeur.leads.regleSansEnonce", { regle: s.regle })
                  : t("vendeur.leads.regleCitee", { enonce: s.enonce })}
              </Text>
              {s.donnee.map((ligne) => (
                <Text key={ligne.cle} style={styles.donnee}>
                  {t("vendeur.leads.donnee", { cle: ligne.cle, valeur: ligne.valeur })}
                </Text>
              ))}
            </View>
          ))
        : null}
      {carte.nonCalculables.map((n) => (
        <Text key={n.segment} style={styles.avis}>
          {t("vendeur.leads.nonCalculableDuLead", {
            segment: t(`vendeur.segments.${n.segment}`, { defaultValue: n.segment }),
            manque: n.manque,
          })}
        </Text>
      ))}
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
  meta: { color: "#444" },
  trace: { color: "#666", fontSize: 12 },
  urgent: { color: "#8a1c1c", fontWeight: "600" },
  donnee: { fontFamily: "monospace", fontSize: 12 },
  lien: { color: "#1c6f5c", fontWeight: "600" },
  carte: { borderWidth: 1, borderColor: "#bbb", borderRadius: 8, padding: 12, gap: 6 },
  outil: { fontSize: 16, fontWeight: "600" },
  regle: { gap: 2, marginTop: 4 },
  regleTitre: { fontWeight: "600" },
  puces: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  puce: { borderWidth: 1, borderColor: "#1c6f5c", borderRadius: 16, paddingVertical: 6, paddingHorizontal: 12 },
  puceActive: { backgroundColor: "#1c6f5c" },
  puceAttenuee: { borderStyle: "dashed", borderColor: "#999" },
  puceTexte: { color: "#1c6f5c" },
  puceTexteActive: { color: "#fff", fontWeight: "600" },
  badge: { backgroundColor: "#e6f2ef", borderRadius: 4, paddingVertical: 2, paddingHorizontal: 8 },
  badgeTexte: { color: "#1c6f5c", fontSize: 12, fontWeight: "600" },
  boutonSecondaire: { borderWidth: 1, borderColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6, alignSelf: "flex-start" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
});
