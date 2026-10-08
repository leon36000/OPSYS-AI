import type { ResultatSection } from "../admin/lecture";
import { SENS_DE_SEUIL, STATUTS_SEUIL_EVALUE, UNITES_CONNUES } from "../m8/vueExecutive";
import type { CashLibreDeM8, DevisEnAttente, Entonnoir, MargeReelle, MesureEntonnoir, StockACommander, VueExecutive } from "../m8/vueExecutive";
import {
  abreger,
  formaterDateOuInstant,
  libelleDeCatalogue,
  message,
  montantOuTexte,
  presenterSection,
  quantiteOuTexte,
} from "./adminCommun";
import type { Message, VueSection } from "./adminCommun";
import type { LangueMontant } from "./quotes";
import { presenterCashConstatM8 } from "./cashConstatM8";
import type { VueCashConstatM8 } from "./cashConstatM8";

/**
 * Logique PURE de la « vue d'ensemble » de l'écran « Chiffres » (`(admin)/chiffres.tsx`, PLAN T4.20, §9.5 M8) : ce que
 * `m8_lire_vue_executive` rend — l'entonnoir (M8 le calcule), la marge réelle (M5) et le stock à commander (M6), repris
 * par M8 « tels que ces départements les publient, sans recalcul ». L'app ne recalcule rien non plus : chaque chiffre est
 * un texte du serveur mis en forme (`formaterMontant`, `formaterQuantite`), jamais un nombre.
 *
 * **Une mesure non calculable dit ce qui lui manque** (les champs des faits attendus, tels que M8 les nomme), jamais « 0 ».
 * Un « 0 » est un zéro que le serveur a écrit. Des seuils « à configurer » (GATE NATHAN) ne sont pas une alerte : c'est
 * un manque nommé, avec l'endroit où le déclarer. Le dernier constat de cash libre publié par M5 est repris par M8
 * avec son âge et ses limites ; l'état détaillé se lit dans Trésorerie. Tout texte à variables est un `Message`.
 */

export interface VueMesure {
  readonly metricId: string;
  /** Le nom de la mesure, tel que M8 l'écrit. */
  readonly nom: string;
  readonly calculee: boolean;
  /** La valeur mise en forme avec son unité, ou « non calculable » avec ce qui manque. */
  readonly valeur: Message;
}

export interface VueDevisEnAttente {
  readonly resume: Message;
  /** Des devis en attente que le serveur n'a pas cités (borne de la réponse) ; `null` : aucun. */
  readonly reste: Message | null;
}

export interface VueSeuilEvalue {
  readonly nom: string;
  readonly statut: Message;
  readonly valeur: Message | null;
  readonly seuil: Message | null;
  /** De quel côté du seuil la mesure est en alerte ; `null` : le serveur ne le dit pas. */
  readonly sens: Message | null;
}

export interface VueSeuils {
  /** « Seuils à configurer » : les mesures (par leur nom) et où les déclarer ; `null` : rien à configurer. */
  readonly aConfigurer: Message | null;
  readonly invalides: Message | null;
  readonly ignores: Message | null;
  readonly evalues: readonly VueSeuilEvalue[];
  readonly illisibles: Message | null;
}

export interface VueEntonnoir {
  readonly mesures: readonly VueMesure[];
  readonly mesuresIllisibles: Message | null;
  /** Une ligne par source d'événements : combien de faits, et le dernier à l'heure de l'appareil. */
  readonly sources: readonly Message[];
  readonly sourcesIllisibles: Message | null;
  readonly sansReponse: VueDevisEnAttente;
  readonly brouillonsEnRetard: VueDevisEnAttente;
  readonly seuils: VueSeuils;
}

export interface VueChantierMarge {
  readonly wctId: string;
  readonly titre: Message;
  /** La fin du chantier, à l'heure de l'appareil ; `null` : non datée. */
  readonly termineLe: Message | null;
  /** `true` seulement si M5 a chiffré la marge de ce chantier. */
  readonly calculee: boolean;
  /** La marge réelle chiffrée par M5, ou « non calculable » avec la raison de M5 : jamais 0. */
  readonly marge: Message;
}

export interface VueMargeReelle {
  /** D'où vient la marge, telle que M8 l'écrit. */
  readonly source: string;
  readonly resume: Message;
  readonly chantiers: readonly VueChantierMarge[];
  readonly illisibles: Message | null;
  readonly reste: Message | null;
}

export interface VueArticle {
  readonly id: string;
  /** Le résumé de M6, tel quel : quantités et seuils viennent de M6. */
  readonly resume: string;
  readonly depuis: Message | null;
  readonly geste: Message | null;
}

export type VueStock =
  | {
      readonly genre: "lu";
      readonly source: string;
      readonly resume: Message;
      readonly articles: readonly VueArticle[];
      readonly illisibles: Message | null;
      readonly reste: Message | null;
      /** Les seuils de stock ne sont pas configurés : l'absence d'article à commander n'est alors pas un « tout va bien ». */
      readonly seuilsAConfigurer: Message | null;
    }
  | { readonly genre: "manque"; readonly source: string; readonly avis: Message };

export interface VueVueExecutive {
  /** Ce que la vue couvre, tel que M8 l'écrit. */
  readonly portee: string;
  readonly entonnoir: VueEntonnoir;
  readonly margeReelle: VueMargeReelle;
  readonly stock: VueStock;
  /** Message v1 de provenance ; le constat natif détaillé est présenté dans cashConstat. */
  readonly cashLibre: Message;
  readonly cashConstat: VueCashConstatM8 | null;
  readonly manques: readonly Message[];
  readonly manquesIllisibles: Message | null;
}

/** La valeur d'une mesure avec son unité, mise en forme sans la convertir. */
export function mesureFormatee(valeur: string, unite: string, langue: LangueMontant): Message {
  if (unite === "CAD") {
    return message("admin.unites.CAD", { valeur: montantOuTexte(valeur, langue) });
  }
  if (UNITES_CONNUES.includes(unite)) {
    return message(`admin.unites.${unite}`, { valeur: quantiteOuTexte(valeur, langue) });
  }
  return message("admin.unites.autre", { valeur: quantiteOuTexte(valeur, langue), unite });
}

function nombreIllisible(cle: string, nombre: number): Message | null {
  return nombre === 0 ? null : message(cle, { nombre });
}

function presenterMesure(mesure: MesureEntonnoir, langue: LangueMontant): VueMesure {
  return {
    metricId: mesure.metricId,
    nom: mesure.nom,
    calculee: mesure.calculee,
    valeur:
      mesure.valeur !== null
        ? mesureFormatee(mesure.valeur, mesure.unite, langue)
        : mesure.manque.length === 0
          ? message("admin.chiffres.vue.mesureNonCalculableSansPrecision")
          : message("admin.chiffres.vue.mesureNonCalculable", { manque: mesure.manque.join(", ") }),
  };
}

function presenterDevisEnAttente(cle: string, devis: DevisEnAttente): VueDevisEnAttente {
  return {
    resume: message(cle, { n: devis.n, devis: devis.devis.length === 0 ? "—" : devis.devis.join(", ") }),
    reste: devis.reste === 0 ? null : message("admin.chiffres.vue.devisReste", { reste: devis.reste }),
  };
}

function presenterEntonnoir(entonnoir: Entonnoir, langue: LangueMontant, decalage: number): VueEntonnoir {
  const noms = new Map(entonnoir.mesures.map((mesure) => [mesure.metricId, mesure.nom]));
  const nomsDes = (ids: readonly string[]): string => ids.map((id) => noms.get(id) ?? id).join(", ");
  const { seuils } = entonnoir;
  return {
    mesures: entonnoir.mesures.map((mesure) => presenterMesure(mesure, langue)),
    mesuresIllisibles: nombreIllisible("admin.chiffres.vue.mesuresIllisibles", entonnoir.mesuresIllisibles),
    sources: entonnoir.sources.map((source) =>
      source.dernierFaitLe === null
        ? message("admin.chiffres.vue.sourceSansDate", { evenement: source.evenement, n: source.n })
        : message("admin.chiffres.vue.sourceDatee", {
            evenement: source.evenement,
            n: source.n,
            date: formaterDateOuInstant(source.dernierFaitLe, decalage),
          }),
    ),
    sourcesIllisibles: nombreIllisible("admin.chiffres.vue.sourcesIllisibles", entonnoir.sourcesIllisibles),
    sansReponse: presenterDevisEnAttente("admin.chiffres.vue.sansReponse", entonnoir.sansReponse),
    brouillonsEnRetard: presenterDevisEnAttente("admin.chiffres.vue.brouillonsEnRetard", entonnoir.brouillonsEnRetard),
    seuils: {
      aConfigurer:
        seuils.aConfigurer.length === 0
          ? null
          : seuils.configuration === null
            ? message("admin.chiffres.vue.seuilsAConfigurerSansEndroit", { mesures: nomsDes(seuils.aConfigurer) })
            : message("admin.chiffres.vue.seuilsAConfigurer", {
                mesures: nomsDes(seuils.aConfigurer),
                configuration: seuils.configuration,
              }),
      invalides:
        seuils.invalides.length === 0 ? null : message("admin.chiffres.vue.seuilsInvalides", { mesures: nomsDes(seuils.invalides) }),
      ignores: seuils.ignores.length === 0 ? null : message("admin.chiffres.vue.seuilsIgnores", { mesures: nomsDes(seuils.ignores) }),
      evalues: seuils.evalues.map((evalue) => ({
        nom: noms.get(evalue.metricId) ?? evalue.metricId,
        statut: libelleDeCatalogue("admin.chiffres.vue.seuilStatuts", evalue.statut, STATUTS_SEUIL_EVALUE),
        valeur: evalue.valeur === null ? null : mesureFormatee(evalue.valeur, evalue.unite, langue),
        seuil: evalue.seuil === null ? null : mesureFormatee(evalue.seuil, evalue.unite, langue),
        sens: evalue.sens === null ? null : libelleDeCatalogue("admin.chiffres.vue.sens", evalue.sens, SENS_DE_SEUIL),
      })),
      illisibles: nombreIllisible("admin.chiffres.vue.seuilsIllisibles", seuils.illisibles),
    },
  };
}

function presenterMarge(marge: MargeReelle, langue: LangueMontant, decalage: number): VueMargeReelle {
  return {
    source: marge.source,
    resume: message("admin.chiffres.vue.margeResume", {
      n: marge.nChantiers,
      connue: marge.nMargeConnue,
      nonCalculable: marge.nNonCalculable,
    }),
    chantiers: marge.chantiers.map((chantier) => ({
      wctId: chantier.wctId,
      titre:
        chantier.devisId === null
          ? message("admin.chiffres.vue.chantierSansDevis", { chantier: abreger(chantier.wctId) })
          : message("admin.chiffres.vue.chantier", { chantier: abreger(chantier.wctId), devis: chantier.devisId }),
      termineLe:
        chantier.horodatageCompletion === null
          ? null
          : message("admin.chiffres.vue.chantierTermine", { date: formaterDateOuInstant(chantier.horodatageCompletion, decalage) }),
      calculee: chantier.margeReelleCad !== null,
      marge:
        chantier.margeReelleCad !== null
          ? message("admin.chiffres.vue.margeCalculee", { montant: montantOuTexte(chantier.margeReelleCad, langue) })
          : chantier.raison === null
            ? message("admin.chiffres.vue.margeNonCalculableSansRaison")
            : message("admin.chiffres.vue.margeNonCalculable", { raison: chantier.raison }),
    })),
    illisibles: nombreIllisible("admin.chiffres.vue.chantiersIllisibles", marge.illisibles),
    reste: nombreIllisible("admin.chiffres.vue.chantiersReste", marge.reste),
  };
}

function presenterStock(stock: StockACommander, decalage: number): VueStock {
  if (stock.genre === "manque") {
    return {
      genre: "manque",
      source: stock.source,
      avis: message("admin.chiffres.vue.stockManque", { manque: stock.manque.length === 0 ? "—" : stock.manque.join(", ") }),
    };
  }
  return {
    genre: "lu",
    source: stock.source,
    resume: message("admin.chiffres.vue.stockResume", { n: stock.nArticles }),
    articles: stock.articles.map((article) => ({
      id: article.id,
      resume: article.resume,
      depuis: article.depuis === null ? null : message("admin.chiffres.vue.articleDepuis", { date: formaterDateOuInstant(article.depuis, decalage) }),
      geste: article.actionProposee === null ? null : message("admin.chiffres.vue.articleGeste", { geste: article.actionProposee }),
    })),
    illisibles: nombreIllisible("admin.chiffres.vue.articlesIllisibles", stock.illisibles),
    reste: nombreIllisible("admin.chiffres.vue.articlesReste", stock.reste),
    seuilsAConfigurer: stock.seuilsAConfigurer ? message("admin.chiffres.vue.stockSeuilsAConfigurer") : null,
  };
}

function presenterCashLibreDeM8(cash: CashLibreDeM8): Message {
  if (cash.genre === "lu") return message("admin.cashConstatM8.source", { source: cash.source });
  return cash.genre === "manque"
    ? message("admin.chiffres.vue.cashLibreAilleurs")
    : message("admin.chiffres.vue.cashLibreInconnu", { statut: cash.statut });
}

export function presenterVueExecutive(vue: VueExecutive, langue: LangueMontant, decalage: number): VueVueExecutive {
  return {
    portee: vue.portee,
    entonnoir: presenterEntonnoir(vue.entonnoir, langue, decalage),
    margeReelle: presenterMarge(vue.margeReelle, langue, decalage),
    stock: presenterStock(vue.stock, decalage),
    cashLibre: presenterCashLibreDeM8(vue.cashLibre),
    cashConstat: presenterCashConstatM8(vue.cashLibre, langue, decalage),
    manques: vue.manques.map((manque) =>
      message("admin.chiffres.vue.manque", { champ: manque.champ, source: manque.source, raison: manque.raison }),
    ),
    manquesIllisibles: nombreIllisible("admin.chiffres.vue.manquesIllisibles", vue.manquesIllisibles),
  };
}

export function vueDEnsemble(
  resultat: ResultatSection<VueExecutive>,
  langue: LangueMontant,
  decalage: number,
): VueSection<VueVueExecutive> {
  return presenterSection(resultat, decalage, (vue) => presenterVueExecutive(vue, langue, decalage));
}
