import {
  decimalNullable,
  entierOuNull,
  entierPositifOuNull,
  estDecimal,
  estObjet,
  listeDeTextes,
  lireListe,
  texteNullable,
  texteOuNull,
} from "../admin/lecteurs";

/**
 * Contrats mobiles des trois lectures financières de M5 que l'écran `(admin)/chiffres.tsx` affiche (§9.5 M5 :
 * « trésorerie et cash libre réel » ; PLAN T4.16, T4.16-d, T4.20) : `m5_etat_tresorerie`, `m5_prevoir_tresorerie` et
 * `m5_lire_echeances_fiscales`. Lecture SEULE de `departments/m05-financecore/src/m5_financecore/` (`outils.py`,
 * `cash_libre.py`, `prevision.py`, `calendrier_fiscal.py`) — jamais exécuté ici (ADR-0008) ; la forme d'une VRAIE
 * réponse du moteur est celle de `src/admin/fixtures/reponses-moteur.json` (`tests/e2e/test_admin_appareil.py`).
 *
 * **Aucun montant, pourcentage ni date n'est calculé ici.** Un montant est un texte décimal que M5 a arrêté (`format(
 * Decimal, "f")`), et il reste un texte de bout en bout : ni conversion en nombre, ni somme, ni arrondi. Une date est
 * celle que M5 rend (`AAAA-MM-JJ`), les jours restants sont ceux de M5.
 *
 * **Une donnée inconnue est dite inconnue, avec ce qui manque, jamais zéro.** Ce que ces lecteurs refusent de lire :
 *  - une composante « calculée » sans montant, ou « non calculable » avec un montant ; un cash libre « calculable » dont
 *    une composante ne l'est pas, ou « non calculable » avec un chiffre ; une semaine « calculée » après la semaine où la
 *    prévision devient non calculable (le serveur se contredit : rien n'est montré) ;
 *  - le solde de l'état gelé (`solde`, `argent_disponible`) : un registre sans aucun mouvement rend « 0 » à cet
 *    endroit, alors que le cash libre dit « solde non calculable » (aucun solde d'ouverture). Le solde de l'app est celui
 *    de la composante `solde` du cash libre ; le « 0 » gelé n'est jamais montré comme un solde ;
 *  - une réponse d'analyse sans la mention « Analyse préparatoire IA » : la mention voyage avec la donnée (§13.3), elle
 *    est exigée, et l'écran l'affiche à côté d'elle.
 */

export const OUTIL_ETAT_TRESORERIE = "m5_etat_tresorerie";
export const OUTIL_PREVOIR_TRESORERIE = "m5_prevoir_tresorerie";
export const OUTIL_ECHEANCES_FISCALES = "m5_lire_echeances_fiscales";

/**
 * `m5_etat_tresorerie` : aucun argument. Ni `role` ni `autorise_couts` : la vue vient du rôle authentifié du jeton
 * (T1.4-k2), un argument ne pourrait que la restreindre, et l'app ne se restreint pas elle-même.
 */
export function construireArgumentsEtatTresorerie(): Record<string, never> {
  return {};
}

/**
 * `m5_prevoir_tresorerie` : le jour de l'appareil (M5 n'a pas d'horloge), et le rang de la page suivante quand on la
 * demande. Ni l'horizon, ni le seuil, ni les délais : ils sont au propriétaire (`department.yaml`, GATE NATHAN), et
 * absents, le serveur refuse en disant quoi déclarer.
 */
export function construireArgumentsPrevision(aujourdHui: string, depart?: number): Record<string, string | number> {
  return depart === undefined || depart === 0 ? { aujourd_hui: aujourdHui } : { aujourd_hui: aujourdHui, depart };
}

/** `m5_lire_echeances_fiscales` : le jour de l'appareil. Aucune date d'échéance ni aucun montant ne passe en argument. */
export function construireArgumentsEcheances(aujourdHui: string): { readonly aujourd_hui: string } {
  return { aujourd_hui: aujourdHui };
}

/** `outils.py` (`analyse.avec_mention`) : la mention est une clé de la réponse ; sans elle, la réponse est illisible. */
function lireMention(brut: Record<string, unknown>): string | null {
  return texteOuNull(brut.mention);
}

export interface VerdictM5 {
  readonly code: string;
  readonly detail: string;
}

function lireVerdict(brut: unknown): VerdictM5 | null {
  if (!estObjet(brut)) {
    return null;
  }
  const code = texteOuNull(brut.code);
  return code === null || typeof brut.detail !== "string" ? null : { code, detail: brut.detail };
}

function lireVerdicts(brut: unknown): readonly VerdictM5[] | null {
  if (brut === undefined) {
    return [];
  }
  const lus = lireListe(brut, lireVerdict);
  return lus === null || lus.illisibles > 0 ? null : lus.items;
}

// ---------------------------------------------------------------------------------------------------------------------
// m5_etat_tresorerie : le solde, l'argent disponible et le cash libre réel
// ---------------------------------------------------------------------------------------------------------------------
/** `cash_libre.py` (`_composante`) : les statuts d'une composante. */
export const STATUT_COMPOSANTE_CALCULEE = "CALCULE";
export const STATUT_COMPOSANTE_NON_CALCULABLE = "NON_CALCULABLE";
/** `cash_libre.py` (`_ORDRE_COMPOSANTES`) : les composantes retranchées du solde, dans l'ordre de la définition produit. */
export const COMPOSANTES_DU_CASH_LIBRE: readonly string[] = [
  "taxes_a_remettre",
  "paies",
  "das",
  "comptes_a_payer",
  "dettes",
  "reserves",
];

export interface ComposanteCash {
  readonly id: string;
  readonly calculee: boolean;
  /** `null` : non calculable. `"0.00"` : un zéro que le registre ou le propriétaire a écrit. */
  readonly montant: string | null;
  /** Le certain, quand le total est inconnu (`null` : aucun repère). */
  readonly plancher: string | null;
  /** D'où vient le chiffre (registre lu, déclaration du propriétaire). */
  readonly source: string;
  readonly dernierePiece: string | null;
  readonly pieces: number;
  readonly manque: readonly VerdictM5[];
  readonly reserves: readonly string[];
}

export interface CashLibre {
  /** `null` : non calculable (`calculable` faux). Un déficit est un montant négatif, rendu tel quel. */
  readonly montant: string | null;
  readonly calculable: boolean;
  readonly enDeficit: boolean | null;
  /** Un repère quand le cash libre est non calculable : le solde moins ce qui est connu. Ce n'est PAS de l'argent disponible. */
  readonly auPlus: string | null;
  /** La phrase que M5 écrit de ce résultat, telle quelle. */
  readonly lecture: string;
  readonly solde: ComposanteCash;
  readonly composantes: readonly ComposanteCash[];
  readonly manque: readonly string[];
  readonly reserves: readonly string[];
  readonly hypotheses: readonly string[];
  /** Hypothèses que M5 a retirées de la réponse pour qu'elle tienne dans la limite du serveur. */
  readonly hypothesesOmises: number;
  /** M5 a retiré le détail de ses composantes (taille de la réponse). */
  readonly detailOmis: boolean;
}

/** Le solde que l'écran montre : celui de la composante `solde` du cash libre, jamais le « 0 » gelé d'un registre vide. */
export type SoldeAffiche =
  | { readonly genre: "connu"; readonly montant: string }
  | { readonly genre: "inconnu"; readonly manque: readonly VerdictM5[] }
  /** La vue sans droit de voir les montants : ni solde ni cash libre. */
  | { readonly genre: "masque" };

export interface EtatTresorerie {
  readonly role: string | null;
  readonly solde: SoldeAffiche;
  /** Le solde moins les réserves : montré seulement avec sa note (« ce n'est PAS le cash libre ») et si le solde est connu. */
  readonly argentDisponible: string | null;
  readonly argentDisponibleNote: string | null;
  readonly cashLibre: CashLibre | null;
  readonly mention: string;
}

function lireComposante(brut: unknown): ComposanteCash | null {
  if (!estObjet(brut) || !estObjet(brut.source) || !estObjet(brut.fraicheur)) {
    return null;
  }
  const id = texteOuNull(brut.id);
  const montant = decimalNullable(brut.montant);
  const plancher = brut.plancher === undefined ? null : decimalNullable(brut.plancher);
  const source = texteOuNull(brut.source.de);
  const dernierePiece = texteNullable(brut.fraicheur.derniere_piece);
  const pieces = entierPositifOuNull(brut.fraicheur.pieces);
  const manque = lireVerdicts(brut.manque);
  const reserves = brut.reserves === undefined ? [] : listeDeTextes(brut.reserves);
  if (
    id === null ||
    montant === undefined ||
    plancher === undefined ||
    source === null ||
    dernierePiece === undefined ||
    pieces === null ||
    manque === null ||
    reserves === null
  ) {
    return null;
  }
  // « calculée » = un montant ; « non calculable » = aucun. Une contradiction est illisible, jamais un zéro.
  if (brut.statut === STATUT_COMPOSANTE_CALCULEE && montant !== null) {
    return { id, calculee: true, montant, plancher: null, source, dernierePiece, pieces, manque, reserves };
  }
  if (brut.statut === STATUT_COMPOSANTE_NON_CALCULABLE && montant === null) {
    return { id, calculee: false, montant: null, plancher, source, dernierePiece, pieces, manque, reserves };
  }
  return null;
}

function lireCashLibre(brut: unknown): CashLibre | null {
  if (!estObjet(brut) || brut.type !== "CASH_LIBRE" || typeof brut.calculable !== "boolean") {
    return null;
  }
  const montant = decimalNullable(brut.cash_libre);
  const auPlus = decimalNullable(brut.au_plus);
  const lecture = texteOuNull(brut.lecture);
  const solde = lireComposante(brut.solde);
  const composantes = lireListe(brut.composantes, lireComposante);
  const manque = listeDeTextes(brut.manque);
  const reserves = listeDeTextes(brut.reserves);
  const hypotheses = brut.hypotheses === undefined ? [] : listeDeTextes(brut.hypotheses);
  const hypothesesOmises = brut.hypotheses_omises === undefined ? 0 : entierPositifOuNull(brut.hypotheses_omises);
  const detailOmis = brut.detail_omis === undefined ? false : brut.detail_omis;
  if (
    montant === undefined ||
    auPlus === undefined ||
    lecture === null ||
    solde === null ||
    composantes === null ||
    composantes.illisibles > 0 ||
    manque === null ||
    reserves === null ||
    hypotheses === null ||
    hypothesesOmises === null ||
    typeof detailOmis !== "boolean"
  ) {
    return null;
  }
  const toutesCalculees = solde.calculee && composantes.items.every((composante) => composante.calculee);
  if (brut.calculable) {
    // Calculable : un montant, un déficit dit vrai ou faux, aucun repère « au plus », rien qui manque, tout calculé.
    if (montant === null || typeof brut.en_deficit !== "boolean" || auPlus !== null || manque.length > 0 || !toutesCalculees) {
      return null;
    }
    return {
      montant,
      calculable: true,
      enDeficit: brut.en_deficit,
      auPlus: null,
      lecture,
      solde,
      composantes: composantes.items,
      manque,
      reserves,
      hypotheses,
      hypothesesOmises,
      detailOmis,
    };
  }
  // Non calculable : aucun montant, et au moins une composante qui ne l'est pas (sinon le serveur se contredit).
  if (montant !== null || brut.en_deficit !== null || toutesCalculees) {
    return null;
  }
  return {
    montant: null,
    calculable: false,
    enDeficit: null,
    auPlus,
    lecture,
    solde,
    composantes: composantes.items,
    manque,
    reserves,
    hypotheses,
    hypothesesOmises,
    detailOmis,
  };
}

/**
 * Lit l'état de trésorerie. Le solde de l'écran est celui du cash libre ; le solde et l'argent disponible gelés de
 * l'état n'ont de sens que si ce solde est connu (sinon un registre vide y met « 0 »). Une vue sans montants (le
 * serveur n'a pas donné de cash libre) ne porte ni solde ni argent disponible : un montant sans cash libre, ou un cash
 * libre qui contredit le solde gelé, rend la réponse illisible.
 */
export function lireEtatTresorerie(brut: unknown): EtatTresorerie | null {
  if (!estObjet(brut) || brut.type !== "ETAT_FINANCIER") {
    return null;
  }
  const mention = lireMention(brut);
  const role = texteNullable(brut.role);
  const soldeGele = decimalNullable(brut.solde);
  const argentGele = decimalNullable(brut.argent_disponible);
  const note = brut.argent_disponible_note === undefined ? null : texteNullable(brut.argent_disponible_note);
  if (mention === null || role === undefined || soldeGele === undefined || argentGele === undefined || note === undefined) {
    return null;
  }
  if (brut.cash_libre === null) {
    return soldeGele === null && argentGele === null
      ? { role, solde: { genre: "masque" }, argentDisponible: null, argentDisponibleNote: note, cashLibre: null, mention }
      : null;
  }
  const cashLibre = lireCashLibre(brut.cash_libre);
  if (cashLibre === null) {
    return null;
  }
  if (!cashLibre.solde.calculee) {
    return {
      role,
      solde: { genre: "inconnu", manque: cashLibre.solde.manque },
      argentDisponible: null,
      argentDisponibleNote: note,
      cashLibre,
      mention,
    };
  }
  // Le solde connu du cash libre et le solde gelé de l'état sont la même vérité : s'ils diffèrent, le serveur se contredit.
  if (soldeGele !== cashLibre.solde.montant || argentGele === null) {
    return null;
  }
  return {
    role,
    solde: { genre: "connu", montant: cashLibre.solde.montant as string },
    argentDisponible: argentGele,
    argentDisponibleNote: note,
    cashLibre,
    mention,
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// m5_prevoir_tresorerie : la prévision, semaine par semaine
// ---------------------------------------------------------------------------------------------------------------------
/** `prevision.py` (`_alerte`) : les statuts de l'alerte de seuil. */
export const STATUTS_ALERTE_PREVISION: readonly string[] = ["ALERTE", "SEUIL_A_CONFIGURER", "NON_EVALUEE", "AUCUNE"];

export type SemainePrevue =
  | {
      readonly calculee: true;
      readonly semaine: number;
      readonly du: string;
      readonly entrees: string;
      readonly sorties: string;
      readonly soldeFin: string;
      /** `null` : le cash libre d'aujourd'hui n'est pas calculable, le cash libre prévu non plus. */
      readonly cashLibrePrevu: string | null;
      readonly sousSeuil: boolean;
      readonly enDeficit: boolean;
      readonly lignes: number;
    }
  /** Aucun chiffre : « non calculable à partir de la semaine X », et `manque` de la prévision dit quoi déclarer. */
  | { readonly calculee: false; readonly semaine: number; readonly du: string; readonly lignes: number };

export interface AlertePrevision {
  readonly statut: string;
  readonly seuil: string | null;
  readonly sourceDuSeuil: { readonly source: string; readonly au: string } | null;
  readonly semaines: readonly number[];
  readonly nonEvalueeAPartirDe: number | null;
  /** Le seuil à configurer, dit par M5 (code et détail). */
  readonly manque: VerdictM5 | null;
}

export interface ManquePrevision {
  readonly code: string;
  readonly aPartirDeSemaine: number;
  readonly nombre: number;
  readonly exemples: readonly string[];
  readonly detail: string;
}

export interface ResumeAuDela {
  readonly nombre: number;
  readonly total: string;
  readonly nonChiffres: number;
}

export interface EncaissementNonCompte {
  readonly code: string;
  readonly nombre: number;
  readonly montantConnu: string;
  readonly exemples: readonly string[];
}

export interface PrevisionTresorerie {
  readonly genre: "prevision";
  readonly role: string | null;
  /** La phrase que M5 écrit de la prévision, telle quelle. */
  readonly lecture: string;
  readonly aujourdHui: string;
  readonly horizonSemaines: number;
  readonly finHorizon: string;
  readonly calculable: boolean;
  readonly nonCalculableAPartirDe: number | null;
  readonly manque: readonly ManquePrevision[];
  readonly alerte: AlertePrevision;
  readonly plusBas: { readonly semaine: number; readonly solde: string } | null;
  readonly premiereSemaineEnDeficit: number | null;
  readonly soldeInitial: { readonly montant: string | null; readonly source: string; readonly dernierePiece: string | null };
  readonly cashLibreAujourdhui: { readonly montant: string | null; readonly manque: readonly string[] };
  readonly auDela: { readonly entrees: ResumeAuDela; readonly sorties: ResumeAuDela };
  readonly encaissementsNonComptes: readonly EncaissementNonCompte[];
  readonly reserves: readonly string[];
  readonly limites: readonly string[];
  readonly limitesOmises: number;
  /** L'empreinte de TOUTE la prévision : deux pages du même horizon la partagent, une page d'une autre prévision non. */
  readonly previsionId: string;
  readonly total: number;
  readonly depart: number;
  readonly affichees: number;
  readonly reste: number;
  /** Rang à demander pour la page suivante ; `null` : rien ne suit. */
  readonly prochainDepart: number | null;
  readonly semaines: readonly SemainePrevue[];
  readonly semainesIllisibles: number;
  readonly mention: string;
}

/** La vue sans droit de voir les montants : l'horizon seulement. */
export interface PrevisionMasquee {
  readonly genre: "masquee";
  readonly role: string | null;
  readonly horizonSemaines: number;
  readonly mention: string;
}

export type PrevisionLue = PrevisionTresorerie | PrevisionMasquee;

function lireSourceDuSeuil(brut: unknown): { source: string; au: string } | null {
  if (!estObjet(brut)) {
    return null;
  }
  const source = texteOuNull(brut.source);
  const au = texteOuNull(brut.au);
  return source === null || au === null ? null : { source, au };
}

function lireAlerte(brut: unknown): AlertePrevision | null {
  if (!estObjet(brut)) {
    return null;
  }
  const statut = texteOuNull(brut.statut);
  const seuil = decimalNullable(brut.seuil);
  const sourceBrute = brut.source_du_seuil;
  const sourceDuSeuil = sourceBrute === undefined ? null : lireSourceDuSeuil(sourceBrute);
  const semaines = brut.semaines === undefined ? { items: [], illisibles: 0 } : lireListe(brut.semaines, entierPositifOuNull);
  const nonEvaluee = brut.non_evaluee_a_partir_de === undefined ? null : entierPositifOuNull(brut.non_evaluee_a_partir_de);
  const manque = brut.manque === undefined ? null : lireVerdict(brut.manque);
  if (
    statut === null ||
    seuil === undefined ||
    (sourceBrute !== undefined && sourceDuSeuil === null) ||
    semaines === null ||
    semaines.illisibles > 0 ||
    (brut.non_evaluee_a_partir_de !== undefined && nonEvaluee === null) ||
    (brut.manque !== undefined && manque === null)
  ) {
    return null;
  }
  return { statut, seuil, sourceDuSeuil, semaines: semaines.items, nonEvalueeAPartirDe: nonEvaluee, manque };
}

function lireManquePrevision(brut: unknown): ManquePrevision | null {
  if (!estObjet(brut)) {
    return null;
  }
  const code = texteOuNull(brut.code);
  const aPartirDeSemaine = entierPositifOuNull(brut.a_partir_de_semaine);
  const nombre = entierPositifOuNull(brut.nombre);
  const exemples = listeDeTextes(brut.exemples);
  const detail = texteOuNull(brut.detail);
  return code === null || aPartirDeSemaine === null || nombre === null || exemples === null || detail === null
    ? null
    : { code, aPartirDeSemaine, nombre, exemples, detail };
}

function lireResumeAuDela(brut: unknown): ResumeAuDela | null {
  if (!estObjet(brut)) {
    return null;
  }
  const nombre = entierPositifOuNull(brut.nombre);
  const nonChiffres = brut.non_chiffres === undefined ? 0 : entierPositifOuNull(brut.non_chiffres);
  return nombre === null || nonChiffres === null || !estDecimal(brut.total) ? null : { nombre, total: brut.total, nonChiffres };
}

function lireEncaissementNonCompte(brut: unknown): EncaissementNonCompte | null {
  if (!estObjet(brut)) {
    return null;
  }
  const code = texteOuNull(brut.code);
  const nombre = entierPositifOuNull(brut.nombre);
  const exemples = listeDeTextes(brut.exemples);
  return code === null || nombre === null || exemples === null || !estDecimal(brut.montant_connu)
    ? null
    : { code, nombre, montantConnu: brut.montant_connu, exemples };
}

/**
 * Une semaine de la série. Le statut doit s'accorder avec `non_calculable_a_partir_de` : avant la semaine X la semaine
 * est calculée (avec ses montants), à partir d'elle elle ne l'est pas (et n'a aucun montant). Un désaccord la rend
 * illisible : l'écran ne montre jamais un solde pour une semaine que le serveur dit non calculable.
 */
function lireSemaine(brut: unknown, nonCalculableAPartirDe: number | null): SemainePrevue | null {
  if (!estObjet(brut)) {
    return null;
  }
  const semaine = entierPositifOuNull(brut.semaine);
  const du = texteOuNull(brut.du);
  const lignes = entierPositifOuNull(brut.lignes);
  if (semaine === null || semaine < 1 || du === null || lignes === null) {
    return null;
  }
  const devraitEtreCalculee = nonCalculableAPartirDe === null || semaine < nonCalculableAPartirDe;
  if (brut.statut === "NON_CALCULABLE" && !devraitEtreCalculee) {
    const sansMontant = ["entrees", "sorties", "solde_fin", "cash_libre_prevu"].every((cle) => brut[cle] === undefined);
    return sansMontant ? { calculee: false, semaine, du, lignes } : null;
  }
  if (brut.statut !== "CALCULE" || !devraitEtreCalculee) {
    return null;
  }
  const cashLibrePrevu = decimalNullable(brut.cash_libre_prevu);
  const sousSeuil = brut.sous_seuil === undefined ? false : brut.sous_seuil;
  const enDeficit = brut.en_deficit === undefined ? false : brut.en_deficit;
  if (
    !estDecimal(brut.entrees) ||
    !estDecimal(brut.sorties) ||
    !estDecimal(brut.solde_fin) ||
    cashLibrePrevu === undefined ||
    typeof sousSeuil !== "boolean" ||
    typeof enDeficit !== "boolean"
  ) {
    return null;
  }
  return {
    calculee: true,
    semaine,
    du,
    entrees: brut.entrees,
    sorties: brut.sorties,
    soldeFin: brut.solde_fin,
    cashLibrePrevu,
    sousSeuil,
    enDeficit,
    lignes,
  };
}

function lirePlusBas(brut: unknown): { semaine: number; solde: string } | null | undefined {
  if (brut === null) {
    return null;
  }
  if (!estObjet(brut)) {
    return undefined;
  }
  const semaine = entierPositifOuNull(brut.semaine);
  return semaine === null || !estDecimal(brut.solde) ? undefined : { semaine, solde: brut.solde };
}

function lireSoldeInitial(brut: unknown): PrevisionTresorerie["soldeInitial"] | null {
  if (!estObjet(brut) || !estObjet(brut.fraicheur)) {
    return null;
  }
  const montant = decimalNullable(brut.montant);
  const source = texteOuNull(brut.source);
  const dernierePiece = texteNullable(brut.fraicheur.derniere_piece);
  return montant === undefined || source === null || dernierePiece === undefined ? null : { montant, source, dernierePiece };
}

function lireCashLibreAujourdhui(brut: unknown): PrevisionTresorerie["cashLibreAujourdhui"] | null {
  if (!estObjet(brut)) {
    return null;
  }
  const montant = decimalNullable(brut.montant);
  const manque = listeDeTextes(brut.manque);
  return montant === undefined || manque === null ? null : { montant, manque };
}

/**
 * Lit une page de `m5_prevoir_tresorerie`. Une prévision « calculable » n'a aucune semaine non calculable et
 * réciproquement ; une page dont la pagination se contredit (`prochain_depart` qui n'est pas `depart + affichees`
 * quand il reste des semaines, `affichees` qui n'est pas le nombre de semaines rendues) est illisible : elle ferait
 * manquer des semaines ou tourner en rond.
 */
export function lirePrevisionTresorerie(brut: unknown): PrevisionLue | null {
  if (!estObjet(brut)) {
    return null;
  }
  const mention = lireMention(brut);
  const role = texteNullable(brut.role);
  if (mention === null || role === undefined) {
    return null;
  }
  if (brut.montants_masques === true) {
    const horizonSemaines = entierPositifOuNull(brut.horizon_semaines);
    return horizonSemaines === null ? null : { genre: "masquee", role, horizonSemaines, mention };
  }
  if (brut.type !== "PREVISION_TRESORERIE" || typeof brut.calculable !== "boolean") {
    return null;
  }
  const nonCalculableAPartirDe =
    brut.non_calculable_a_partir_de === null ? null : entierPositifOuNull(brut.non_calculable_a_partir_de);
  const lecture = texteOuNull(brut.lecture);
  const aujourdHui = texteOuNull(brut.aujourd_hui);
  const finHorizon = texteOuNull(brut.fin_horizon);
  const horizonSemaines = entierPositifOuNull(brut.horizon_semaines);
  const manque = lireListe(brut.manque, lireManquePrevision);
  const alerte = lireAlerte(brut.alerte);
  const plusBas = lirePlusBas(brut.plus_bas);
  const premiereEnDeficit = brut.premiere_semaine_en_deficit === null ? null : entierPositifOuNull(brut.premiere_semaine_en_deficit);
  const soldeInitial = lireSoldeInitial(brut.solde_initial);
  const cashLibre = lireCashLibreAujourdhui(brut.cash_libre_aujourd_hui);
  const auDela = estObjet(brut.au_dela_de_l_horizon)
    ? { entrees: lireResumeAuDela(brut.au_dela_de_l_horizon.entrees), sorties: lireResumeAuDela(brut.au_dela_de_l_horizon.sorties) }
    : null;
  const nonComptes = lireListe(brut.encaissements_non_comptes, lireEncaissementNonCompte);
  const reserves = listeDeTextes(brut.reserves);
  const limites = brut.limites === undefined ? [] : listeDeTextes(brut.limites);
  const limitesOmises = brut.limites_omises === undefined ? 0 : entierPositifOuNull(brut.limites_omises);
  const previsionId = texteOuNull(brut.prevision_id);
  const total = entierPositifOuNull(brut.total);
  const depart = entierPositifOuNull(brut.depart);
  const affichees = entierPositifOuNull(brut.affichees);
  const reste = entierPositifOuNull(brut.reste);
  const prochainDepart = brut.prochain_depart === null ? null : entierPositifOuNull(brut.prochain_depart);
  if (
    lecture === null ||
    aujourdHui === null ||
    finHorizon === null ||
    horizonSemaines === null ||
    (brut.non_calculable_a_partir_de !== null && nonCalculableAPartirDe === null) ||
    brut.calculable !== (nonCalculableAPartirDe === null) ||
    manque === null ||
    manque.illisibles > 0 ||
    alerte === null ||
    plusBas === undefined ||
    (brut.premiere_semaine_en_deficit !== null && premiereEnDeficit === null) ||
    soldeInitial === null ||
    cashLibre === null ||
    auDela === null ||
    auDela.entrees === null ||
    auDela.sorties === null ||
    nonComptes === null ||
    nonComptes.illisibles > 0 ||
    reserves === null ||
    limites === null ||
    limitesOmises === null ||
    previsionId === null ||
    total === null ||
    depart === null ||
    affichees === null ||
    reste === null ||
    (brut.prochain_depart !== null && prochainDepart === null) ||
    !Array.isArray(brut.semaines) ||
    brut.semaines.length !== affichees ||
    depart + affichees + reste !== total ||
    prochainDepart !== (reste > 0 ? depart + affichees : null)
  ) {
    return null;
  }
  const semaines = lireListe(brut.semaines, (element) => lireSemaine(element, nonCalculableAPartirDe));
  if (semaines === null) {
    return null;
  }
  return {
    genre: "prevision",
    role,
    lecture,
    aujourdHui,
    horizonSemaines,
    finHorizon,
    calculable: brut.calculable,
    nonCalculableAPartirDe,
    manque: manque.items,
    alerte,
    plusBas,
    premiereSemaineEnDeficit: premiereEnDeficit,
    soldeInitial,
    cashLibreAujourdhui: cashLibre,
    auDela: { entrees: auDela.entrees, sorties: auDela.sorties },
    encaissementsNonComptes: nonComptes.items,
    reserves,
    limites,
    limitesOmises,
    previsionId,
    total,
    depart,
    affichees,
    reste,
    prochainDepart,
    semaines: semaines.items,
    semainesIllisibles: semaines.illisibles,
    mention,
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// m5_lire_echeances_fiscales : les prochaines échéances TPS/TVQ
// ---------------------------------------------------------------------------------------------------------------------
/** `calendrier_fiscal.py` (`_echeance`) : les statuts d'une échéance. */
export const STATUTS_ECHEANCE: readonly string[] = ["A_VENIR", "EN_RETARD"];

export interface DetailTaxe {
  readonly collectee: string;
  readonly creditsIntrants: string;
  readonly nette: string;
  readonly aRemettre: string;
}

export interface TaxesNettes {
  readonly aRemettre: string;
  readonly tps: DetailTaxe;
  readonly tvq: DetailTaxe;
  readonly facturesClients: number;
  readonly facturesFournisseurs: number;
}

export interface EcheanceFiscale {
  readonly periodeDebut: string;
  readonly periodeFin: string;
  readonly periodeTerminee: boolean;
  readonly limitePaiement: string;
  readonly limiteProduction: string;
  /** Les jours restants, comptés par M5 (négatifs quand la limite est passée). */
  readonly joursAvantPaiement: number;
  readonly joursAvantProduction: number;
  readonly statut: string;
  /** `null` : M5 ne chiffre pas la taxe de cette période (date de dernière remise non déclarée, vue sans montants, ou
   * facture illisible : `manque` le dit). */
  readonly taxesNettes: TaxesNettes | null;
  readonly manque: readonly VerdictM5[];
}

export interface SourceFiscale {
  readonly organisme: string;
  readonly titre: string;
  readonly url: string;
  readonly consulteLe: string;
}

export interface EcheancesFiscales {
  readonly role: string | null;
  readonly aujourdHui: string;
  readonly frequence: string;
  readonly moisFinExercice: number;
  readonly particulierEnAffaires: boolean | null;
  /** `null` : aucune date de dernière remise déclarée : aucun retard n'est détectable. */
  readonly taxesRemisesJusquAu: string | null;
  readonly echeances: readonly EcheanceFiscale[];
  readonly echeancesIllisibles: number;
  readonly nonAffichees: number;
  readonly manque: readonly VerdictM5[];
  readonly anneesDeclarees: readonly number[];
  readonly connuJusquAu: string;
  readonly avertissementCouverture: string;
  readonly versions: Readonly<Record<string, string>>;
  readonly validationCpa: Readonly<Record<string, string>>;
  readonly sources: readonly SourceFiscale[];
  readonly horsPerimetre: readonly string[];
  readonly mention: string;
}

function lireDetailTaxe(brut: unknown): DetailTaxe | null {
  if (!estObjet(brut)) {
    return null;
  }
  return estDecimal(brut.collectee) && estDecimal(brut.credits_intrants) && estDecimal(brut.nette) && estDecimal(brut.a_remettre)
    ? { collectee: brut.collectee, creditsIntrants: brut.credits_intrants, nette: brut.nette, aRemettre: brut.a_remettre }
    : null;
}

function lireTaxesNettes(brut: unknown): TaxesNettes | null {
  if (!estObjet(brut)) {
    return null;
  }
  const tps = lireDetailTaxe(brut.tps);
  const tvq = lireDetailTaxe(brut.tvq);
  const facturesClients = entierPositifOuNull(brut.factures_clients);
  const facturesFournisseurs = entierPositifOuNull(brut.factures_fournisseurs);
  return !estDecimal(brut.a_remettre) || tps === null || tvq === null || facturesClients === null || facturesFournisseurs === null
    ? null
    : { aRemettre: brut.a_remettre, tps, tvq, facturesClients, facturesFournisseurs };
}

function lireEcheance(brut: unknown): EcheanceFiscale | null {
  if (!estObjet(brut)) {
    return null;
  }
  const periodeDebut = texteOuNull(brut.periode_debut);
  const periodeFin = texteOuNull(brut.periode_fin);
  const limitePaiement = texteOuNull(brut.limite_paiement);
  const limiteProduction = texteOuNull(brut.limite_production);
  const joursAvantPaiement = entierOuNull(brut.jours_avant_paiement);
  const joursAvantProduction = entierOuNull(brut.jours_avant_production);
  const statut = texteOuNull(brut.statut);
  const manque = lireVerdicts(brut.manque);
  // `taxes_nettes` : absente (rien n'est chiffré), nulle (M5 ne peut pas la chiffrer : `manque` le dit) ou lue.
  const taxes = brut.taxes_nettes === undefined || brut.taxes_nettes === null ? null : lireTaxesNettes(brut.taxes_nettes);
  if (
    periodeDebut === null ||
    periodeFin === null ||
    typeof brut.periode_terminee !== "boolean" ||
    limitePaiement === null ||
    limiteProduction === null ||
    joursAvantPaiement === null ||
    joursAvantProduction === null ||
    statut === null ||
    manque === null ||
    (brut.taxes_nettes !== undefined && brut.taxes_nettes !== null && taxes === null)
  ) {
    return null;
  }
  return {
    periodeDebut,
    periodeFin,
    periodeTerminee: brut.periode_terminee,
    limitePaiement,
    limiteProduction,
    joursAvantPaiement,
    joursAvantProduction,
    statut,
    taxesNettes: taxes,
    manque,
  };
}

function lireSourceFiscale(brut: unknown): SourceFiscale | null {
  if (!estObjet(brut)) {
    return null;
  }
  const organisme = texteOuNull(brut.organisme);
  const titre = texteOuNull(brut.titre);
  const url = texteOuNull(brut.url);
  const consulteLe = texteOuNull(brut.consulte_le);
  return organisme === null || titre === null || url === null || consulteLe === null ? null : { organisme, titre, url, consulteLe };
}

function lireTableauDeTextes(brut: unknown): Readonly<Record<string, string>> | null {
  if (!estObjet(brut)) {
    return null;
  }
  const table: Record<string, string> = {};
  for (const [cle, valeur] of Object.entries(brut)) {
    const texte = texteOuNull(valeur);
    if (texte === null) {
      return null;
    }
    table[cle] = texte;
  }
  return table;
}

export function lireEcheancesFiscales(brut: unknown): EcheancesFiscales | null {
  if (!estObjet(brut) || brut.type !== "ECHEANCES_FISCALES") {
    return null;
  }
  const mention = lireMention(brut);
  const role = texteNullable(brut.role);
  const aujourdHui = texteOuNull(brut.aujourd_hui);
  const frequence = texteOuNull(brut.frequence);
  const moisFinExercice = entierPositifOuNull(brut.mois_fin_exercice);
  const particulier = brut.particulier_en_affaires;
  const remises = texteNullable(brut.taxes_remises_jusqu_au);
  const echeances = lireListe(brut.echeances, lireEcheance);
  const nonAffichees = entierPositifOuNull(brut.non_affichees);
  const manque = lireVerdicts(brut.manque);
  const annees = lireListe(brut.annees_declarees, entierPositifOuNull);
  const connuJusquAu = texteOuNull(brut.connu_jusqu_au);
  const avertissement = texteOuNull(brut.avertissement_couverture);
  const versions = lireTableauDeTextes(brut.versions);
  const validationCpa = lireTableauDeTextes(brut.validation_cpa);
  const sources = lireListe(brut.sources, lireSourceFiscale);
  const horsPerimetre = listeDeTextes(brut.hors_perimetre);
  if (
    mention === null ||
    role === undefined ||
    aujourdHui === null ||
    frequence === null ||
    moisFinExercice === null ||
    (particulier !== null && typeof particulier !== "boolean") ||
    remises === undefined ||
    echeances === null ||
    nonAffichees === null ||
    manque === null ||
    annees === null ||
    annees.illisibles > 0 ||
    connuJusquAu === null ||
    avertissement === null ||
    versions === null ||
    validationCpa === null ||
    sources === null ||
    horsPerimetre === null
  ) {
    return null;
  }
  return {
    role,
    aujourdHui,
    frequence,
    moisFinExercice,
    particulierEnAffaires: particulier,
    taxesRemisesJusquAu: remises,
    echeances: echeances.items,
    echeancesIllisibles: echeances.illisibles,
    nonAffichees,
    manque,
    anneesDeclarees: annees.items,
    connuJusquAu,
    avertissementCouverture: avertissement,
    versions,
    validationCpa,
    sources: sources.items,
    horsPerimetre,
    mention,
  };
}
