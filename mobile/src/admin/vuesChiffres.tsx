import { Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import type { Message } from "../ecrans/adminCommun";
import type {
  VueCashLibre,
  VueComposante,
  VueEcheance,
  VueEcheances,
  VuePrevision,
  VueSemaine,
  VueTresorerie,
} from "../ecrans/chiffres";
import type { VueDevisEnAttente, VueSeuils, VueStock, VueVueExecutive } from "../ecrans/vueExecutive";
import { BoutonSecondaire, Carte, Depliant, Ligne, Lignes, stylesAdmin as styles, TextesDuServeur } from "./composants";

/**
 * Le rendu des quatre sections de l'écran « Chiffres » (`(admin)/chiffres.tsx`, PLAN T4.20). Aucune décision ici : les
 * modèles de vue (`src/ecrans/chiffres.ts`, `vueExecutive.ts`, testés) ont déjà choisi chaque texte, dit chaque « non
 * calculable » avec ce qui manque, et gardé la mention « Analyse préparatoire IA » avec la donnée. Ce fichier ne fait
 * que les mettre à l'écran, la mention à côté des chiffres qu'elle qualifie.
 */

function Titre({ cle }: { readonly cle: string }) {
  const { t } = useTranslation();
  return <Text style={styles.petitTitre}>{t(cle)}</Text>;
}

/** Une mention de M5 (« Analyse préparatoire IA ») : le texte du serveur, tel quel. */
function Mention({ texte }: { readonly texte: string }) {
  return <Text style={styles.mention}>{texte}</Text>;
}

// ---------------------------------------------------------------------------------------------------------------------
// Trésorerie et cash libre
// ---------------------------------------------------------------------------------------------------------------------
function ComposanteUI({ composante }: { readonly composante: VueComposante }) {
  return (
    <Carte>
      <Ligne m={composante.libelle} style={styles.petitTitre} />
      <Ligne m={composante.valeur} style={composante.calculee ? styles.montant : styles.erreur} />
      {composante.plancher !== null ? <Ligne m={composante.plancher} style={styles.avis} /> : null}
      {composante.manque.length > 0 ? <Lignes items={composante.manque} style={styles.avis} /> : null}
      <Ligne m={composante.source} style={styles.trace} />
      {composante.dernierePiece !== null ? <Ligne m={composante.dernierePiece} style={styles.trace} /> : null}
      {composante.reserves !== null ? <Ligne m={composante.reserves} style={styles.avis} /> : null}
    </Carte>
  );
}

function CashLibreUI({ cash }: { readonly cash: VueCashLibre }) {
  const { t } = useTranslation();
  return (
    <View style={{ gap: 6 }}>
      <Ligne m={cash.resume} style={cash.calculable ? styles.gros : styles.erreur} />
      {cash.enDeficit !== null ? <Ligne m={cash.enDeficit} style={styles.erreur} /> : null}
      {cash.auPlus !== null ? <Ligne m={cash.auPlus} style={styles.avis} /> : null}
      <Titre cle="admin.chiffres.cashLibre.lectureTitre" />
      <Text style={styles.citation}>{cash.lecture}</Text>
      {cash.manque.length > 0 ? (
        <>
          <Titre cle="admin.chiffres.cashLibre.manqueTitre" />
          <TextesDuServeur items={cash.manque} style={styles.avis} />
        </>
      ) : null}
      {cash.reserves !== null ? <Ligne m={cash.reserves} style={styles.avis} /> : null}
      <Depliant>
        <Titre cle="admin.chiffres.cashLibre.composantesTitre" />
        {cash.detailOmis ? <Text style={styles.avis}>{t("admin.chiffres.cashLibre.detailOmis")}</Text> : null}
        {cash.composantes.map((composante) => (
          <ComposanteUI key={composante.id} composante={composante} />
        ))}
        {cash.hypotheses.length > 0 ? (
          <>
            <Titre cle="admin.chiffres.cashLibre.hypothesesTitre" />
            <TextesDuServeur items={cash.hypotheses} style={styles.trace} />
          </>
        ) : null}
        {cash.hypothesesOmises !== null ? <Ligne m={cash.hypothesesOmises} style={styles.avis} /> : null}
      </Depliant>
    </View>
  );
}

export function TresorerieUI({ vue }: { readonly vue: VueTresorerie }) {
  return (
    <View style={{ gap: 6 }}>
      <Ligne m={vue.solde.texte} style={vue.solde.genre === "connu" ? styles.gros : styles.erreur} />
      {vue.solde.manque.length > 0 ? <Lignes items={vue.solde.manque} style={styles.avis} /> : null}
      {vue.argentDisponible !== null ? (
        <>
          <Ligne m={vue.argentDisponible.texte} style={styles.montant} />
          <Text style={styles.avis}>{vue.argentDisponible.note}</Text>
        </>
      ) : null}
      {vue.cashLibre !== null ? <CashLibreUI cash={vue.cashLibre} /> : null}
      <Mention texte={vue.mention} />
    </View>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Prévision
// ---------------------------------------------------------------------------------------------------------------------
function SemaineUI({ semaine }: { readonly semaine: VueSemaine }) {
  return (
    <Carte>
      <Ligne m={semaine.titre} style={styles.petitTitre} />
      {semaine.calculee ? (
        <>
          <Ligne m={semaine.entrees} style={styles.meta} />
          <Ligne m={semaine.sorties} style={styles.meta} />
          <Ligne m={semaine.soldeFin} style={styles.montant} />
          <Ligne m={semaine.cashLibrePrevu} style={styles.meta} />
          {semaine.sousSeuil !== null ? <Ligne m={semaine.sousSeuil} style={styles.erreur} /> : null}
          {semaine.enDeficit !== null ? <Ligne m={semaine.enDeficit} style={styles.erreur} /> : null}
          <Ligne m={semaine.lignes} style={styles.trace} />
        </>
      ) : (
        <Ligne m={semaine.avis} style={styles.erreur} />
      )}
    </Carte>
  );
}

export interface ProprietesPrevision {
  readonly vue: VuePrevision;
  /** « Voir plus » est offert : la lecture vient du serveur et des semaines suivent. */
  readonly peutVoirPlus: boolean;
  readonly suiteEnCours: boolean;
  /** Ce que la dernière tentative de « Voir plus » a dit (échec, refus, relecture) ; `null` : rien. */
  readonly avisSuite: Message | null;
  readonly onVoirPlus: () => void;
}

export function PrevisionUI({ vue, peutVoirPlus, suiteEnCours, avisSuite, onVoirPlus }: ProprietesPrevision) {
  const { t } = useTranslation();
  if (vue.genre === "masquee") {
    return (
      <View style={{ gap: 6 }}>
        <Ligne m={vue.horizon} style={styles.meta} />
        <Mention texte={vue.mention} />
      </View>
    );
  }
  return (
    <View style={{ gap: 6 }}>
      <Ligne m={vue.horizon} style={styles.meta} />
      <Text style={styles.citation}>{vue.lecture}</Text>
      {vue.nonCalculable !== null ? <Ligne m={vue.nonCalculable} style={styles.erreur} /> : null}
      {vue.manque.length > 0 ? <Lignes items={vue.manque} style={styles.avis} /> : null}

      <Titre cle="admin.chiffres.alerte.titre" />
      <Ligne m={vue.alerte.statut} style={vue.alerte.enAlerte ? styles.erreur : styles.avis} />
      {vue.alerte.seuil !== null ? <Ligne m={vue.alerte.seuil} style={styles.meta} /> : null}
      {vue.alerte.sourceDuSeuil !== null ? <Ligne m={vue.alerte.sourceDuSeuil} style={styles.trace} /> : null}
      {vue.alerte.semaines !== null ? <Ligne m={vue.alerte.semaines} style={styles.erreur} /> : null}
      {vue.alerte.nonEvaluee !== null ? <Ligne m={vue.alerte.nonEvaluee} style={styles.avis} /> : null}
      {vue.alerte.manque !== null ? <Ligne m={vue.alerte.manque} style={styles.avis} /> : null}

      <Ligne m={vue.soldeInitial} style={styles.montant} />
      <Ligne m={vue.soldeInitialSource} style={styles.trace} />
      <Ligne m={vue.cashLibreAujourdhui} style={styles.montant} />
      {vue.cashLibreAujourdhuiManque.length > 0 ? <TextesDuServeur items={vue.cashLibreAujourdhuiManque} style={styles.avis} /> : null}
      {vue.plusBas !== null ? <Ligne m={vue.plusBas} style={styles.meta} /> : null}
      {vue.premiereSemaineEnDeficit !== null ? <Ligne m={vue.premiereSemaineEnDeficit} style={styles.erreur} /> : null}

      <Titre cle="admin.chiffres.prevision.semainesTitre" />
      <Ligne m={vue.progression} style={styles.trace} />
      {vue.semaines.map((semaine) => (
        <SemaineUI key={semaine.semaine} semaine={semaine} />
      ))}
      {vue.semainesIllisibles !== null ? <Ligne m={vue.semainesIllisibles} style={styles.avis} /> : null}
      {avisSuite !== null ? <Ligne m={avisSuite} style={styles.avis} /> : null}
      {peutVoirPlus && vue.prochainDepart !== null ? (
        <BoutonSecondaire
          texte={suiteEnCours ? t("admin.chiffres.prevision.chargementSuite") : t("admin.chiffres.prevision.voirPlus")}
          desactive={suiteEnCours}
          onPress={onVoirPlus}
        />
      ) : null}

      <Depliant>
        <Lignes items={vue.auDela} style={styles.meta} />
        {vue.encaissementsNonComptes.length > 0 ? <Lignes items={vue.encaissementsNonComptes} style={styles.avis} /> : null}
        {vue.reserves !== null ? <Ligne m={vue.reserves} style={styles.avis} /> : null}
        <Titre cle="admin.chiffres.prevision.limitesTitre" />
        <TextesDuServeur items={vue.limites} style={styles.trace} />
        {vue.limitesOmises !== null ? <Ligne m={vue.limitesOmises} style={styles.avis} /> : null}
      </Depliant>
      <Mention texte={vue.mention} />
    </View>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Échéances fiscales
// ---------------------------------------------------------------------------------------------------------------------
function EcheanceUI({ echeance }: { readonly echeance: VueEcheance }) {
  return (
    <Carte>
      <Ligne m={echeance.periode} style={styles.petitTitre} />
      <Ligne m={echeance.statut} style={echeance.enRetard ? styles.erreur : styles.meta} />
      <Ligne m={echeance.limitePaiement} style={styles.meta} />
      <Ligne m={echeance.limiteProduction} style={styles.meta} />
      {echeance.taxes !== null ? (
        <>
          <Ligne m={echeance.taxes.aRemettre} style={styles.montant} />
          <Ligne m={echeance.taxes.tps} style={styles.trace} />
          <Ligne m={echeance.taxes.tvq} style={styles.trace} />
          <Ligne m={echeance.taxes.factures} style={styles.trace} />
        </>
      ) : null}
      {echeance.couvertureTaxes !== null ? <Ligne m={echeance.couvertureTaxes} style={styles.avis} /> : null}
      {echeance.taxesNonChiffrees !== null ? <Ligne m={echeance.taxesNonChiffrees} style={styles.erreur} /> : null}
      {echeance.manque.length > 0 ? <Lignes items={echeance.manque} style={styles.avis} /> : null}
    </Carte>
  );
}

export function EcheancesUI({ vue }: { readonly vue: VueEcheances }) {
  const { t } = useTranslation();
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.trace}>{t("admin.chiffres.echeances.frequenceEtiquette")}</Text>
      <Ligne m={vue.frequence} style={styles.montant} />
      <Ligne m={vue.moisFinExercice} style={styles.meta} />
      <Ligne m={vue.particulierEnAffaires} style={styles.meta} />
      <Ligne m={vue.taxesRemises} style={styles.avis} />
      {vue.manque.length > 0 ? <Lignes items={vue.manque} style={styles.avis} /> : null}
      <Text style={styles.trace}>{t("admin.chiffres.echeances.joursNegatifs")}</Text>
      {vue.echeances.map((echeance) => (
        <EcheanceUI key={echeance.cle} echeance={echeance} />
      ))}
      {vue.echeancesIllisibles !== null ? <Ligne m={vue.echeancesIllisibles} style={styles.avis} /> : null}
      {vue.nonAffichees !== null ? <Ligne m={vue.nonAffichees} style={styles.avis} /> : null}
      <Text style={styles.avis}>{vue.couverture}</Text>
      <Ligne m={vue.connuJusquAu} style={styles.trace} />
      <Depliant>
        <Titre cle="admin.chiffres.echeances.validationsTitre" />
        <Lignes items={vue.validations} style={styles.meta} />
        <Titre cle="admin.chiffres.echeances.horsPerimetreTitre" />
        <TextesDuServeur items={vue.horsPerimetre} style={styles.trace} />
        <Titre cle="admin.chiffres.echeances.sourcesTitre" />
        {vue.sources.map((source) => (
          <View key={source.url}>
            <Ligne m={source.reference} style={styles.trace} />
            <Text style={styles.trace}>{source.url}</Text>
          </View>
        ))}
      </Depliant>
      <Mention texte={vue.mention} />
    </View>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Vue d'ensemble (M8)
// ---------------------------------------------------------------------------------------------------------------------
function DevisEnAttenteUI({ devis }: { readonly devis: VueDevisEnAttente }) {
  return (
    <>
      <Ligne m={devis.resume} style={styles.meta} />
      {devis.reste !== null ? <Ligne m={devis.reste} style={styles.avis} /> : null}
    </>
  );
}

function SeuilsUI({ seuils }: { readonly seuils: VueSeuils }) {
  const { t } = useTranslation();
  return (
    <>
      {seuils.aConfigurer !== null ? <Ligne m={seuils.aConfigurer} style={styles.avis} /> : null}
      {seuils.invalides !== null ? <Ligne m={seuils.invalides} style={styles.erreur} /> : null}
      {seuils.ignores !== null ? <Ligne m={seuils.ignores} style={styles.avis} /> : null}
      {seuils.evalues.map((evalue) => (
        <Carte key={evalue.nom}>
          <Text style={styles.petitTitre}>{evalue.nom}</Text>
          <Ligne m={evalue.statut} style={styles.meta} />
          {evalue.valeur !== null ? (
            <>
              <Text style={styles.trace}>{t("admin.chiffres.vue.valeurEtiquette")}</Text>
              <Ligne m={evalue.valeur} style={styles.montant} />
            </>
          ) : null}
          {evalue.seuil !== null ? (
            <>
              <Text style={styles.trace}>{t("admin.chiffres.vue.seuilEtiquette")}</Text>
              <Ligne m={evalue.seuil} style={styles.meta} />
            </>
          ) : null}
          {evalue.sens !== null ? <Ligne m={evalue.sens} style={styles.trace} /> : null}
        </Carte>
      ))}
      {seuils.illisibles !== null ? <Ligne m={seuils.illisibles} style={styles.avis} /> : null}
    </>
  );
}

function StockUI({ stock }: { readonly stock: VueStock }) {
  if (stock.genre === "manque") {
    return <Ligne m={stock.avis} style={styles.avis} />;
  }
  return (
    <>
      <Ligne m={stock.resume} style={styles.meta} />
      {stock.seuilsAConfigurer !== null ? <Ligne m={stock.seuilsAConfigurer} style={styles.avis} /> : null}
      {stock.articles.map((article) => (
        <Carte key={article.id}>
          <Text style={styles.meta}>{article.resume}</Text>
          {article.depuis !== null ? <Ligne m={article.depuis} style={styles.trace} /> : null}
          {article.geste !== null ? <Ligne m={article.geste} style={styles.avis} /> : null}
        </Carte>
      ))}
      {stock.illisibles !== null ? <Ligne m={stock.illisibles} style={styles.avis} /> : null}
      {stock.reste !== null ? <Ligne m={stock.reste} style={styles.avis} /> : null}
    </>
  );
}

export function VueDEnsembleUI({ vue }: { readonly vue: VueVueExecutive }) {
  const { t } = useTranslation();
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.trace}>{t("admin.chiffres.vue.portee")}</Text>
      <Text style={styles.trace}>{vue.portee}</Text>

      <Titre cle="admin.chiffres.vue.entonnoirTitre" />
      {vue.entonnoir.mesures.map((mesure) => (
        <View key={mesure.metricId}>
          <Text style={styles.meta}>{mesure.nom}</Text>
          <Ligne m={mesure.valeur} style={mesure.calculee ? styles.montant : styles.erreur} />
        </View>
      ))}
      {vue.entonnoir.mesuresIllisibles !== null ? <Ligne m={vue.entonnoir.mesuresIllisibles} style={styles.avis} /> : null}
      <DevisEnAttenteUI devis={vue.entonnoir.sansReponse} />
      <DevisEnAttenteUI devis={vue.entonnoir.brouillonsEnRetard} />

      <Titre cle="admin.chiffres.vue.seuilsTitre" />
      <SeuilsUI seuils={vue.entonnoir.seuils} />

      <Depliant>
        <Titre cle="admin.chiffres.vue.sourcesTitre" />
        <Lignes items={vue.entonnoir.sources} style={styles.trace} />
        {vue.entonnoir.sourcesIllisibles !== null ? <Ligne m={vue.entonnoir.sourcesIllisibles} style={styles.avis} /> : null}
      </Depliant>

      <Titre cle="admin.chiffres.vue.margeTitre" />
      <Text style={styles.trace}>{vue.margeReelle.source}</Text>
      <Ligne m={vue.margeReelle.resume} style={styles.meta} />
      {vue.margeReelle.chantiers.map((chantier) => (
        <Carte key={chantier.wctId}>
          <Ligne m={chantier.titre} style={styles.petitTitre} />
          {chantier.termineLe !== null ? <Ligne m={chantier.termineLe} style={styles.trace} /> : null}
          <Ligne m={chantier.marge} style={chantier.calculee ? styles.montant : styles.avis} />
        </Carte>
      ))}
      {vue.margeReelle.illisibles !== null ? <Ligne m={vue.margeReelle.illisibles} style={styles.avis} /> : null}
      {vue.margeReelle.reste !== null ? <Ligne m={vue.margeReelle.reste} style={styles.avis} /> : null}

      <Titre cle="admin.chiffres.vue.stockTitre" />
      <Text style={styles.trace}>{vue.stock.source}</Text>
      <StockUI stock={vue.stock} />

      <Ligne m={vue.cashLibre} style={styles.avis} />

      {vue.manques.length > 0 || vue.manquesIllisibles !== null ? (
        <>
          <Titre cle="admin.chiffres.vue.manquesTitre" />
          <Lignes items={vue.manques} style={styles.avis} />
          {vue.manquesIllisibles !== null ? <Ligne m={vue.manquesIllisibles} style={styles.avis} /> : null}
        </>
      ) : null}
    </View>
  );
}
