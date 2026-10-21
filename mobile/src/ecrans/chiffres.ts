import type { SuitePrevision } from "../admin/chiffres";
import type { ResultatSection } from "../admin/lecture";
import {
  COMPOSANTES_DU_CASH_LIBRE,
  FREQUENCES_FISCALES,
  STATUTS_ALERTE_PREVISION,
  STATUTS_ECHEANCE,
  VALIDATIONS_CPA,
} from "../m5/tresorerie";
import type {
  AlertePrevision,
  CashLibre,
  ComposanteCash,
  DetailTaxe,
  EcheanceFiscale,
  EcheancesFiscales,
  EtatTresorerie,
  PrevisionLue,
  PrevisionTresorerie,
  SemainePrevue,
  VerdictM5,
} from "../m5/tresorerie";
import {
  formaterDateOuInstant,
  libelleDeCatalogue,
  message,
  montantOuTexte,
  presenterSection,
} from "./adminCommun";
import type { Message, VueSection } from "./adminCommun";
import type { LangueMontant } from "./quotes";

/**
 * Logique PURE de l'écran « Chiffres » du propriétaire, `(admin)/chiffres.tsx` (PLAN T4.20, §9.5 M5) : la trésorerie et
 * le cash libre, la prévision et les échéances fiscales de M5 (la vue d'ensemble de M8 est dans `vueExecutive.ts`).
 * Aucun montant, pourcentage ni date n'est calculé ici (voir `adminCommun.ts`).
 *
 * **Un « non calculable » ou un « à configurer » est montré avec ce qui manque, jamais un zéro.** Une valeur absente
 * n'est jamais rendue « 0 » ni « — » : elle dit qu'elle n'est pas calculable, et ce que le serveur dit qu'il faut
 * fournir (le code du manque et son détail, tels qu'il les écrit). Une section que le serveur refuse (M5 : « à
 * déclarer », personne désactivée) dit le refus de M5 avec son détail, et aucune copie gardée ne le remplace.
 *
 * **La mention « Analyse préparatoire IA » de M5 voyage avec la donnée** : chaque vue M5 porte la mention que le
 * serveur a écrite (`mention`), et le lecteur (`m5/tresorerie.ts`) refuse une réponse qui n'en a pas. L'écran la montre à
 * côté des chiffres, jamais en bas d'une autre page.
 *
 * **Tout texte à variables est un `Message`** : l'écran ne compose aucune phrase, il rend des clés i18n (voir
 * `adminCommun.ts`). Les chaînes brutes de ces vues sont celles que le serveur écrit (la « lecture » de M5, ses
 * hypothèses, ses limites, la mention) : montrées telles quelles.
 */

/** Les lignes du cash libre qui ont un libellé : le solde, puis les composantes retranchées (`cash_libre.py`). */
const COMPOSANTES_AVEC_LIBELLE: readonly string[] = ["solde", ...COMPOSANTES_DU_CASH_LIBRE];

/** Un manque de M5 (code et détail), tel qu'il l'écrit. */
export function ligneDeManque(manque: VerdictM5): Message {
  return message("admin.commun.manqueLigne", { code: manque.code, detail: manque.detail });
}

/** Des codes de réserve (un manque de confirmation que M5 garde ouvert), mis bout à bout ; `null` : aucune. */
function reserves(codes: readonly string[]): Message | null {
  return codes.length === 0 ? null : message("admin.chiffres.reserves", { reserves: codes.join(", ") });
}

// ---------------------------------------------------------------------------------------------------------------------
// M5 : trésorerie et cash libre
// ---------------------------------------------------------------------------------------------------------------------
export interface VueComposante {
  readonly id: string;
  readonly libelle: Message;
  readonly calculee: boolean;
  /** Le montant mis en forme, ou « non calculable » : jamais 0. */
  readonly valeur: Message;
  /** Le certain, quand le total est inconnu ; `null` : aucun repère. */
  readonly plancher: Message | null;
  /** D'où vient le chiffre, tel que M5 l'écrit. */
  readonly source: Message;
  readonly dernierePiece: Message | null;
  /** Ce que M5 dit qu'il faut fournir pour la calculer. */
  readonly manque: readonly Message[];
  readonly reserves: Message | null;
}

export interface VueCashLibre {
  readonly calculable: boolean;
  /** « Cash libre : X » (négatif : un déficit, avec son signe) ou « non calculable, aucun chiffre ». */
  readonly resume: Message;
  readonly enDeficit: Message | null;
  /** Un repère quand le cash libre n'est pas calculable : ce n'est PAS de l'argent disponible. */
  readonly auPlus: Message | null;
  /** La phrase que M5 écrit de ce résultat, telle quelle. */
  readonly lecture: string;
  /** Le solde d'abord, puis les six composantes retranchées. */
  readonly composantes: readonly VueComposante[];
  /** Ce qui manque, en une ligne par composante, tel que M5 l'écrit. */
  readonly manque: readonly string[];
  readonly reserves: Message | null;
  readonly hypotheses: readonly string[];
  readonly hypothesesOmises: Message | null;
  /** M5 a retiré le détail des composantes (taille de la réponse). */
  readonly detailOmis: boolean;
}

export interface VueSolde {
  readonly genre: "connu" | "inconnu" | "masque";
  /** Le solde, ou « non calculable : aucun solde n'est connu », ou « montants non affichés » : jamais un zéro. */
  readonly texte: Message;
  /** Pour un solde inconnu : ce que M5 dit qu'il manque. */
  readonly manque: readonly Message[];
}

export interface VueTresorerie {
  readonly solde: VueSolde;
  /** Le solde moins les réserves, avec la note de M5 (« ce n'est PAS le cash libre ») : jamais l'un sans l'autre. */
  readonly argentDisponible: { readonly texte: Message; readonly note: string } | null;
  readonly cashLibre: VueCashLibre | null;
  readonly mention: string;
}

function presenterComposante(composante: ComposanteCash, langue: LangueMontant, decalage: number): VueComposante {
  return {
    id: composante.id,
    libelle: libelleDeCatalogue("admin.chiffres.composantes", composante.id, COMPOSANTES_AVEC_LIBELLE),
    calculee: composante.calculee,
    valeur:
      composante.montant === null
        ? message("admin.chiffres.composante.nonCalculable")
        : message("admin.chiffres.composante.montant", { montant: montantOuTexte(composante.montant, langue) }),
    plancher:
      composante.plancher === null
        ? null
        : message("admin.chiffres.composante.plancher", { montant: montantOuTexte(composante.plancher, langue) }),
    source: message("admin.chiffres.composante.source", { source: composante.source }),
    dernierePiece:
      composante.dernierePiece === null
        ? null
        : message("admin.chiffres.composante.dernierePiece", { date: formaterDateOuInstant(composante.dernierePiece, decalage) }),
    manque: composante.manque.map(ligneDeManque),
    reserves: reserves(composante.reserves),
  };
}

function presenterCashLibre(cash: CashLibre, langue: LangueMontant, decalage: number): VueCashLibre {
  return {
    calculable: cash.calculable,
    resume:
      cash.montant === null
        ? message("admin.chiffres.cashLibre.nonCalculable")
        : message("admin.chiffres.cashLibre.calcule", { montant: montantOuTexte(cash.montant, langue) }),
    enDeficit: cash.enDeficit === true ? message("admin.chiffres.cashLibre.enDeficit") : null,
    auPlus:
      cash.auPlus === null ? null : message("admin.chiffres.cashLibre.auPlus", { montant: montantOuTexte(cash.auPlus, langue) }),
    lecture: cash.lecture,
    composantes: [cash.solde, ...cash.composantes].map((c) => presenterComposante(c, langue, decalage)),
    manque: cash.manque,
    reserves: reserves(cash.reserves),
    hypotheses: cash.hypotheses,
    hypothesesOmises:
      cash.hypothesesOmises === 0 ? null : message("admin.chiffres.cashLibre.hypothesesOmises", { nombre: cash.hypothesesOmises }),
    detailOmis: cash.detailOmis,
  };
}

export function presenterTresorerie(etat: EtatTresorerie, langue: LangueMontant, decalage: number): VueTresorerie {
  const solde: VueSolde =
    etat.solde.genre === "connu"
      ? {
          genre: "connu",
          texte: message("admin.chiffres.tresorerie.solde", { montant: montantOuTexte(etat.solde.montant, langue) }),
          manque: [],
        }
      : etat.solde.genre === "inconnu"
        ? { genre: "inconnu", texte: message("admin.chiffres.tresorerie.soldeInconnu"), manque: etat.solde.manque.map(ligneDeManque) }
        : { genre: "masque", texte: message("admin.chiffres.tresorerie.masque"), manque: [] };
  return {
    solde,
    // Un « argent disponible » sans la note qui dit que ce n'est pas le cash libre pourrait être pris pour lui : non montré.
    argentDisponible:
      etat.argentDisponible !== null && etat.argentDisponibleNote !== null
        ? {
            texte: message("admin.chiffres.tresorerie.argentDisponible", { montant: montantOuTexte(etat.argentDisponible, langue) }),
            note: etat.argentDisponibleNote,
          }
        : null,
    cashLibre: etat.cashLibre === null ? null : presenterCashLibre(etat.cashLibre, langue, decalage),
    mention: etat.mention,
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// M5 : prévision
// ---------------------------------------------------------------------------------------------------------------------
export interface VueAlertePrevision {
  readonly statut: Message;
  /** `true` seulement pour une alerte que M5 a levée (des semaines sous le seuil). */
  readonly enAlerte: boolean;
  readonly seuil: Message | null;
  readonly sourceDuSeuil: Message | null;
  /** Les semaines sous le seuil ; `null` : aucune. */
  readonly semaines: Message | null;
  readonly nonEvaluee: Message | null;
  /** Le seuil à configurer (code et détail de M5) ; `null` : rien à configurer. */
  readonly manque: Message | null;
}

export type VueSemaine =
  | {
      readonly calculee: true;
      readonly semaine: number;
      readonly titre: Message;
      readonly entrees: Message;
      readonly sorties: Message;
      readonly soldeFin: Message;
      /** Le cash libre prévu, ou « non calculable » (le cash libre d'aujourd'hui ne l'est pas). */
      readonly cashLibrePrevu: Message;
      readonly sousSeuil: Message | null;
      readonly enDeficit: Message | null;
      readonly lignes: Message;
    }
  /** Aucun chiffre : ce qui manque est dit par la prévision (`manque`), pas par la semaine. */
  | { readonly calculee: false; readonly semaine: number; readonly titre: Message; readonly avis: Message };

export interface VuePrevisionMasquee {
  readonly genre: "masquee";
  readonly horizon: Message;
  readonly mention: string;
}

export interface VuePrevisionComplete {
  readonly genre: "prevision";
  readonly lecture: string;
  readonly horizon: Message;
  readonly calculable: boolean;
  /** « Non calculable à partir de la semaine X » ; `null` : calculable sur tout l'horizon. */
  readonly nonCalculable: Message | null;
  /** Ce que M5 dit qu'il faut fournir : un message par manque (code, semaine de départ, nombre, exemples, détail). */
  readonly manque: readonly Message[];
  readonly alerte: VueAlertePrevision;
  readonly plusBas: Message | null;
  readonly premiereSemaineEnDeficit: Message | null;
  readonly soldeInitial: Message;
  readonly soldeInitialSource: Message;
  readonly cashLibreAujourdhui: Message;
  /** Pourquoi le cash libre d'aujourd'hui n'est pas calculable, tel que M5 l'écrit. */
  readonly cashLibreAujourdhuiManque: readonly string[];
  readonly auDela: readonly Message[];
  readonly encaissementsNonComptes: readonly Message[];
  readonly reserves: Message | null;
  readonly limites: readonly string[];
  readonly limitesOmises: Message | null;
  readonly semaines: readonly VueSemaine[];
  readonly semainesIllisibles: Message | null;
  /** « Voir plus » : le rang de la page suivante ; `null` : rien ne suit. */
  readonly prochainDepart: number | null;
  /** Les semaines lues sur le total, telles que M5 les compte (`affichees` et `total`), jamais recomptées ici. */
  readonly progression: Message;
  readonly mention: string;
}

export type VuePrevision = VuePrevisionMasquee | VuePrevisionComplete;

function presenterAlerte(alerte: AlertePrevision, langue: LangueMontant): VueAlertePrevision {
  return {
    statut: libelleDeCatalogue("admin.chiffres.alerte.statuts", alerte.statut, STATUTS_ALERTE_PREVISION),
    enAlerte: alerte.statut === "ALERTE",
    seuil: alerte.seuil === null ? null : message("admin.chiffres.alerte.seuil", { montant: montantOuTexte(alerte.seuil, langue) }),
    sourceDuSeuil:
      alerte.sourceDuSeuil === null
        ? null
        : message("admin.chiffres.alerte.sourceDuSeuil", { source: alerte.sourceDuSeuil.source, date: alerte.sourceDuSeuil.au }),
    semaines: alerte.semaines.length === 0 ? null : message("admin.chiffres.alerte.semaines", { semaines: alerte.semaines.join(", ") }),
    nonEvaluee:
      alerte.nonEvalueeAPartirDe === null
        ? null
        : message("admin.chiffres.alerte.nonEvaluee", { semaine: alerte.nonEvalueeAPartirDe }),
    manque: alerte.manque === null ? null : ligneDeManque(alerte.manque),
  };
}

function presenterSemaine(semaine: SemainePrevue, langue: LangueMontant): VueSemaine {
  const titre = message("admin.chiffres.prevision.semaine", { semaine: semaine.semaine, du: semaine.du });
  if (!semaine.calculee) {
    return { calculee: false, semaine: semaine.semaine, titre, avis: message("admin.chiffres.prevision.semaineNonCalculable") };
  }
  return {
    calculee: true,
    semaine: semaine.semaine,
    titre,
    entrees: message("admin.chiffres.prevision.entrees", { montant: montantOuTexte(semaine.entrees, langue) }),
    sorties: message("admin.chiffres.prevision.sorties", { montant: montantOuTexte(semaine.sorties, langue) }),
    soldeFin: message("admin.chiffres.prevision.soldeFin", { montant: montantOuTexte(semaine.soldeFin, langue) }),
    cashLibrePrevu:
      semaine.cashLibrePrevu === null
        ? message("admin.chiffres.prevision.cashLibrePrevuNonCalculable")
        : message("admin.chiffres.prevision.cashLibrePrevu", { montant: montantOuTexte(semaine.cashLibrePrevu, langue) }),
    sousSeuil: semaine.sousSeuil ? message("admin.chiffres.prevision.sousSeuil") : null,
    enDeficit: semaine.enDeficit ? message("admin.chiffres.prevision.enDeficit") : null,
    lignes: message("admin.chiffres.prevision.lignes", { nombre: semaine.lignes }),
  };
}

function presenterPrevisionComplete(prevision: PrevisionTresorerie, langue: LangueMontant, decalage: number): VuePrevisionComplete {
  const initial = prevision.soldeInitial;
  return {
    genre: "prevision",
    lecture: prevision.lecture,
    horizon: message("admin.chiffres.prevision.horizon", {
      semaines: prevision.horizonSemaines,
      du: prevision.aujourdHui,
      au: prevision.finHorizon,
    }),
    calculable: prevision.calculable,
    nonCalculable:
      prevision.nonCalculableAPartirDe === null
        ? null
        : message("admin.chiffres.prevision.nonCalculable", { semaine: prevision.nonCalculableAPartirDe }),
    manque: prevision.manque.map((manque) =>
      message("admin.chiffres.prevision.manque", {
        code: manque.code,
        semaine: manque.aPartirDeSemaine,
        nombre: manque.nombre,
        detail: manque.detail,
        exemples: manque.exemples.length === 0 ? "—" : manque.exemples.join(", "),
      }),
    ),
    alerte: presenterAlerte(prevision.alerte, langue),
    plusBas:
      prevision.plusBas === null
        ? null
        : message("admin.chiffres.prevision.plusBas", {
            semaine: prevision.plusBas.semaine,
            montant: montantOuTexte(prevision.plusBas.solde, langue),
          }),
    premiereSemaineEnDeficit:
      prevision.premiereSemaineEnDeficit === null
        ? null
        : message("admin.chiffres.prevision.premiereSemaineEnDeficit", { semaine: prevision.premiereSemaineEnDeficit }),
    soldeInitial:
      initial.montant === null
        ? message("admin.chiffres.prevision.soldeInitialInconnu")
        : message("admin.chiffres.prevision.soldeInitial", { montant: montantOuTexte(initial.montant, langue) }),
    soldeInitialSource:
      initial.dernierePiece === null
        ? message("admin.chiffres.prevision.soldeInitialSource", { source: initial.source })
        : message("admin.chiffres.prevision.soldeInitialSourceDatee", {
            source: initial.source,
            date: formaterDateOuInstant(initial.dernierePiece, decalage),
          }),
    cashLibreAujourdhui:
      prevision.cashLibreAujourdhui.montant === null
        ? message("admin.chiffres.prevision.cashLibreAujourdhuiNonCalculable")
        : message("admin.chiffres.prevision.cashLibreAujourdhui", {
            montant: montantOuTexte(prevision.cashLibreAujourdhui.montant, langue),
          }),
    cashLibreAujourdhuiManque: prevision.cashLibreAujourdhui.manque,
    auDela: [
      message("admin.chiffres.prevision.auDelaEntrees", {
        nombre: prevision.auDela.entrees.nombre,
        montant: montantOuTexte(prevision.auDela.entrees.total, langue),
        nonChiffres: prevision.auDela.entrees.nonChiffres,
      }),
      message("admin.chiffres.prevision.auDelaSorties", {
        nombre: prevision.auDela.sorties.nombre,
        montant: montantOuTexte(prevision.auDela.sorties.total, langue),
        nonChiffres: prevision.auDela.sorties.nonChiffres,
      }),
    ],
    encaissementsNonComptes: prevision.encaissementsNonComptes.map((e) =>
      message("admin.chiffres.prevision.encaissementNonCompte", {
        code: e.code,
        nombre: e.nombre,
        montant: montantOuTexte(e.montantConnu, langue),
        exemples: e.exemples.length === 0 ? "—" : e.exemples.join(", "),
      }),
    ),
    reserves: reserves(prevision.reserves),
    limites: prevision.limites,
    limitesOmises:
      prevision.limitesOmises === 0 ? null : message("admin.chiffres.prevision.limitesOmises", { nombre: prevision.limitesOmises }),
    semaines: prevision.semaines.map((semaine) => presenterSemaine(semaine, langue)),
    semainesIllisibles:
      prevision.semainesIllisibles === 0
        ? null
        : message("admin.chiffres.prevision.semainesIllisibles", { nombre: prevision.semainesIllisibles }),
    prochainDepart: prevision.prochainDepart,
    progression: message("admin.chiffres.prevision.progression", { affichees: prevision.affichees, total: prevision.total }),
    mention: prevision.mention,
  };
}

export function presenterPrevision(prevision: PrevisionLue, langue: LangueMontant, decalage: number): VuePrevision {
  return prevision.genre === "masquee"
    ? {
        genre: "masquee",
        horizon: message("admin.chiffres.prevision.horizonMasque", { semaines: prevision.horizonSemaines }),
        mention: prevision.mention,
      }
    : presenterPrevisionComplete(prevision, langue, decalage);
}

/**
 * Ce que l'écran fait de la suite de la prévision (« Voir plus »). Rien n'est décidé ailleurs : une page qui se recolle
 * remplace la prévision affichée ; une prévision changée ou incohérente se relit depuis le début, et le dit ; un refus
 * ou un échec se dit sans toucher aux semaines déjà lues.
 */
export type DecisionSuite =
  | { readonly genre: "remplacer"; readonly prevision: PrevisionTresorerie }
  | { readonly genre: "relire"; readonly avis: Message }
  | { readonly genre: "avis"; readonly avis: Message }
  | { readonly genre: "rien" };

export function decisionSuitePrevision(suite: SuitePrevision): DecisionSuite {
  switch (suite.genre) {
    case "fusionnee":
      return { genre: "remplacer", prevision: suite.prevision };
    case "a_relire":
      return { genre: "relire", avis: message(`admin.chiffres.prevision.suite.${suite.raison}`) };
    case "refus":
      return {
        genre: "avis",
        avis: message("admin.chiffres.prevision.suite.refus", { code: suite.verdict.code, detail: suite.verdict.detail }),
      };
    case "echec":
      return {
        genre: "avis",
        avis: message("admin.chiffres.prevision.suite.echec", { code: suite.verdict.code, detail: suite.verdict.detail }),
      };
    case "sans_suite":
      return { genre: "rien" };
  }
}

/**
 * La prévision dont l'écran peut lire la suite : SEULEMENT une lecture faite au serveur à l'instant, et qui a encore des
 * semaines à lire. Une copie gardée ne se prolonge pas (hors ligne, la suite n'est pas inventée), et une prévision dont
 * les montants sont masqués n'a pas de semaines.
 */
export function previsionAPoursuivre(resultat: ResultatSection<PrevisionLue> | null): PrevisionTresorerie | null {
  if (resultat === null || resultat.source !== "serveur" || resultat.valeur.genre !== "prevision") {
    return null;
  }
  return resultat.valeur.prochainDepart === null ? null : resultat.valeur;
}

/** La lecture de la prévision, avec les semaines que « Voir plus » vient de recoller ; son origine et sa date restent celles de la première page. */
export function remplacerPrevision(
  resultat: ResultatSection<PrevisionLue>,
  prevision: PrevisionTresorerie,
): ResultatSection<PrevisionLue> {
  return resultat.source === "serveur" ? { ...resultat, valeur: prevision } : resultat;
}

// ---------------------------------------------------------------------------------------------------------------------
// M5 : échéances fiscales
// ---------------------------------------------------------------------------------------------------------------------
export interface VueEcheance {
  readonly cle: string;
  readonly periode: Message;
  readonly statut: Message;
  readonly enRetard: boolean;
  /** La limite de paiement, avec les jours restants que M5 compte (négatifs quand elle est passée). */
  readonly limitePaiement: Message;
  readonly limiteProduction: Message;
  /** Les taxes nettes que M5 chiffre ; `null` : M5 ne les chiffre pas (`taxesNonChiffrees` et `manque` le disent). */
  readonly taxes: {
    readonly aRemettre: Message;
    readonly tps: Message;
    readonly tvq: Message;
    readonly factures: Message;
  } | null;
  readonly taxesNonChiffrees: Message | null;
  /** Couverture fournie par M5, ou inconnue pour une ancienne réponse. */
  readonly couvertureTaxes: Message | null;
  readonly manque: readonly Message[];
}

export interface VueSourceFiscale {
  readonly reference: Message;
  readonly url: string;
}

export interface VueEcheances {
  readonly frequence: Message;
  readonly moisFinExercice: Message;
  readonly particulierEnAffaires: Message;
  /** La date de la dernière remise de taxes ; non déclarée : aucun retard n'est détectable, et l'écran le dit. */
  readonly taxesRemises: Message;
  readonly echeances: readonly VueEcheance[];
  readonly echeancesIllisibles: Message | null;
  readonly nonAffichees: Message | null;
  readonly manque: readonly Message[];
  /** L'avertissement de couverture du calendrier, tel que M5 l'écrit. */
  readonly couverture: string;
  readonly connuJusquAu: Message;
  /** Une ligne par année déclarée : sa version du calendrier et où en est la validation du CPA. */
  readonly validations: readonly Message[];
  readonly sources: readonly VueSourceFiscale[];
  readonly horsPerimetre: readonly string[];
  readonly mention: string;
}

function messageDeTaxe(cle: string, detail: DetailTaxe, langue: LangueMontant): Message {
  return message(cle, {
    collectee: montantOuTexte(detail.collectee, langue),
    credits: montantOuTexte(detail.creditsIntrants, langue),
    nette: montantOuTexte(detail.nette, langue),
    aRemettre: montantOuTexte(detail.aRemettre, langue),
  });
}

function presenterEcheance(echeance: EcheanceFiscale, langue: LangueMontant): VueEcheance {
  const { taxesNettes } = echeance;
  return {
    cle: `${echeance.periodeDebut}:${echeance.periodeFin}`,
    periode: message(echeance.periodeTerminee ? "admin.chiffres.echeances.periodeTerminee" : "admin.chiffres.echeances.periode", {
      debut: echeance.periodeDebut,
      fin: echeance.periodeFin,
    }),
    statut: libelleDeCatalogue("admin.chiffres.echeances.statuts", echeance.statut, STATUTS_ECHEANCE),
    enRetard: echeance.statut === "EN_RETARD",
    limitePaiement: message("admin.chiffres.echeances.limitePaiement", {
      date: echeance.limitePaiement,
      jours: echeance.joursAvantPaiement,
    }),
    limiteProduction: message("admin.chiffres.echeances.limiteProduction", {
      date: echeance.limiteProduction,
      jours: echeance.joursAvantProduction,
    }),
    taxes:
      taxesNettes === null
        ? null
        : {
            aRemettre: message("admin.chiffres.echeances.aRemettre", { montant: montantOuTexte(taxesNettes.aRemettre, langue) }),
            tps: messageDeTaxe("admin.chiffres.echeances.tps", taxesNettes.tps, langue),
            tvq: messageDeTaxe("admin.chiffres.echeances.tvq", taxesNettes.tvq, langue),
            factures: message("admin.chiffres.echeances.factures", {
              clients: taxesNettes.facturesClients,
              fournisseurs: taxesNettes.facturesFournisseurs,
            }),
          },
    taxesNonChiffrees: taxesNettes === null ? message("admin.chiffres.echeances.taxesNonChiffrees") : null,
    couvertureTaxes:
      taxesNettes === null
        ? null
        : message(
            taxesNettes.couverture.statut === "PARTIELLE"
              ? "admin.chiffres.echeances.couverturePartielle"
              : "admin.chiffres.echeances.couvertureInconnue",
          ),
    manque: echeance.manque.map(ligneDeManque),
  };
}

function ligneDeValidation(annee: string, validation: string, version: string | undefined): Message {
  const params = { annee, version: version ?? "—" };
  return VALIDATIONS_CPA.includes(validation)
    ? message(`admin.chiffres.echeances.validations.${validation}`, params)
    : message("admin.chiffres.echeances.validationInconnue", { ...params, validation });
}

export function presenterEcheances(echeances: EcheancesFiscales, langue: LangueMontant): VueEcheances {
  const annees = Object.keys(echeances.validationCpa).sort();
  return {
    frequence: libelleDeCatalogue("admin.chiffres.echeances.frequences", echeances.frequence, FREQUENCES_FISCALES),
    moisFinExercice: message("admin.chiffres.echeances.moisFinExercice", { mois: echeances.moisFinExercice }),
    particulierEnAffaires: message(
      echeances.particulierEnAffaires === null
        ? "admin.chiffres.echeances.particulierNonDeclare"
        : echeances.particulierEnAffaires
          ? "admin.chiffres.echeances.particulierOui"
          : "admin.chiffres.echeances.particulierNon",
    ),
    taxesRemises:
      echeances.taxesRemisesJusquAu === null
        ? message("admin.chiffres.echeances.taxesRemisesNonDeclarees")
        : message("admin.chiffres.echeances.taxesRemises", { date: echeances.taxesRemisesJusquAu }),
    echeances: echeances.echeances.map((echeance) => presenterEcheance(echeance, langue)),
    echeancesIllisibles:
      echeances.echeancesIllisibles === 0
        ? null
        : message("admin.chiffres.echeances.illisibles", { nombre: echeances.echeancesIllisibles }),
    nonAffichees:
      echeances.nonAffichees === 0 ? null : message("admin.chiffres.echeances.nonAffichees", { nombre: echeances.nonAffichees }),
    manque: echeances.manque.map(ligneDeManque),
    couverture: echeances.avertissementCouverture,
    connuJusquAu: message("admin.chiffres.echeances.connuJusquAu", { date: echeances.connuJusquAu }),
    validations: annees.map((annee) => ligneDeValidation(annee, echeances.validationCpa[annee], echeances.versions[annee])),
    sources: echeances.sources.map((source) => ({
      reference: message("admin.chiffres.echeances.source", {
        organisme: source.organisme,
        titre: source.titre,
        date: source.consulteLe,
      }),
      url: source.url,
    })),
    horsPerimetre: echeances.horsPerimetre,
    mention: echeances.mention,
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// Les sections, telles que l'écran les reçoit du chargeur (`ResultatSection`)
// ---------------------------------------------------------------------------------------------------------------------
export function vueTresorerie(
  resultat: ResultatSection<EtatTresorerie>,
  langue: LangueMontant,
  decalage: number,
): VueSection<VueTresorerie> {
  return presenterSection(resultat, decalage, (etat) => presenterTresorerie(etat, langue, decalage));
}

export function vuePrevision(
  resultat: ResultatSection<PrevisionLue>,
  langue: LangueMontant,
  decalage: number,
): VueSection<VuePrevision> {
  return presenterSection(resultat, decalage, (prevision) => presenterPrevision(prevision, langue, decalage));
}

export function vueEcheances(
  resultat: ResultatSection<EcheancesFiscales>,
  langue: LangueMontant,
  decalage: number,
): VueSection<VueEcheances> {
  return presenterSection(resultat, decalage, (echeances) => presenterEcheances(echeances, langue));
}
