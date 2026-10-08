import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";

/** Lecture seule du DTO m8_analytics.cash_libre : montants et âge demeurent ceux du serveur. */
export interface AgeConstatCashLibre {
  readonly jours: number | null;
  readonly aujourdHui: string | null;
  readonly raison: string | null;
}
export interface ConstatCashLibre {
  readonly sequence: number;
  readonly dateReference: string;
  readonly statut: "CALCULE" | "NON_CALCULABLE";
  readonly cashLibreCad: string | null;
  readonly auPlusCad: string | null;
  readonly enDeficit: boolean | null;
  readonly lecture: string;
  readonly composantes: Readonly<Record<string, string | null>> | null;
  readonly composantesOmises: number | null;
  readonly planchersCad: Readonly<Record<string, string>> | null;
  readonly manque: readonly string[];
  readonly reserves: readonly string[];
  readonly mention: string;
}
export type CashLibreDeM8 =
  | { readonly genre: "manque"; readonly source: string; readonly manque: readonly string[]; readonly aLire: string | null }
  | { readonly genre: "inconnu"; readonly statut: string }
  | { readonly genre: "lu"; readonly statut: "lu"; readonly source: string; readonly nConstatsRecus: number;
      readonly constat: ConstatCashLibre; readonly age: AgeConstatCashLibre; readonly nonRepris: string; readonly aLire: string };

const texte = (v: unknown): v is string => typeof v === "string" && v.trim() !== "";
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const decimal = (v: unknown): v is string => typeof v === "string" && v.length <= 24 && /^-?\d+(?:\.\d+)?$/.test(v);
const decimalNullable = (v: unknown): v is string | null => v === null || decimal(v);
const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const textes = (v: unknown): v is string[] => Array.isArray(v) && v.every(texte);
// Le catalogue m5.cash_libre_constate fixe le solde et les six obligations ; la projection M8 les conserve.
const COMPOSANTES = ["solde", "taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"];

const codeReserve = (v: string): boolean => v.length <= 80 && /^REJ-[A-Z0-9-]+$/.test(v);

/** Validation du calendrier, sans horloge ni calcul de l'âge. */
export function estJourCashLibre(v: unknown): v is string {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const [annee, mois, jour] = v.split("-").map(Number);
  if (annee < 1 || mois < 1 || mois > 12 || jour < 1) return false;
  const jours = [31, annee % 4 === 0 && (annee % 100 !== 0 || annee % 400 === 0) ? 29 : 28,
    31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return jour <= jours[mois - 1];
}

function lireAge(v: unknown): AgeConstatCashLibre | null {
  if (!objet(v)) return null;
  const aujourdHui = v.aujourd_hui === undefined ? null : v.aujourd_hui;
  if (aujourdHui !== null && !estJourCashLibre(aujourdHui)) return null;
  if (entier(v.jours) && aujourdHui !== null && v.raison === undefined) {
    return { jours: v.jours, aujourdHui, raison: null };
  }
  if (v.jours === null && texte(v.raison)) return { jours: null, aujourdHui, raison: v.raison };
  return null;
}
function lireConstat(v: Record<string, unknown>): ConstatCashLibre | null {
  if (!entier(v.sequence) || v.sequence < 1 || !estJourCashLibre(v.date_reference) ||
      (v.statut !== "CALCULE" && v.statut !== "NON_CALCULABLE") ||
      !decimalNullable(v.cash_libre_cad) || !decimalNullable(v.au_plus_cad) || !texte(v.lecture) ||
      !textes(v.manque) || v.manque.length > 32 || new Set(v.manque).size !== v.manque.length ||
      !textes(v.reserves) || v.reserves.length > 16 || !v.reserves.every(codeReserve) ||
      new Set(v.reserves).size !== v.reserves.length ||
      !texte(v.mention) || (v.en_deficit !== null && typeof v.en_deficit !== "boolean")) return null;
  if (v.statut === "CALCULE" && (!decimal(v.cash_libre_cad) || v.au_plus_cad !== null ||
      typeof v.en_deficit !== "boolean" || v.manque.length !== 0)) return null;
  if (v.statut === "NON_CALCULABLE" && (v.cash_libre_cad !== null || v.en_deficit !== null || v.manque.length === 0)) return null;
  let composantes: Record<string, string | null> | null = null;
  let composantesOmises: number | null = null;
  let planchersCad: Record<string, string> | null = null;
  if (objet(v.composantes)) {
    if (v.composantes_omises !== undefined || Object.keys(v.composantes).length !== COMPOSANTES.length) return null;
    const montants: Record<string, string | null> = Object.create(null);
    for (const id of COMPOSANTES) {
      const montant = v.composantes[id];
      if (!decimalNullable(montant) || (v.statut === "CALCULE" && montant === null)) return null;
      montants[id] = montant;
    }
    if (v.statut === "NON_CALCULABLE" && !Object.values(montants).includes(null)) return null;
    // Le catalogue M5 lie le repère à la présence du solde, pas à un calcul côté mobile.
    if (v.statut === "NON_CALCULABLE" && ((montants.solde === null) !== (v.au_plus_cad === null))) return null;
    composantes = montants;
    if (v.planchers_cad !== undefined) {
      if (!objet(v.planchers_cad)) return null;
      const planchers: Record<string, string> = Object.create(null);
      for (const [id, montant] of Object.entries(v.planchers_cad)) {
        if (!COMPOSANTES.includes(id) || montants[id] !== null || !decimal(montant)) return null;
        planchers[id] = montant;
      }
      planchersCad = planchers;
    }
  } else {
    if (v.composantes !== undefined || v.planchers_cad !== undefined || v.composantes_omises !== COMPOSANTES.length) return null;
    composantesOmises = v.composantes_omises;
  }
  return { sequence: v.sequence, dateReference: v.date_reference, statut: v.statut,
    cashLibreCad: v.cash_libre_cad, auPlusCad: v.au_plus_cad, enDeficit: v.en_deficit,
    lecture: v.lecture, composantes, composantesOmises, planchersCad,
    manque: v.manque, reserves: v.reserves, mention: v.mention };
}
/** Champs M5 verbatim seulement ; statut inconnu n'expose jamais un montant. */
export function lireCashLibreDeM8(brut: unknown): CashLibreDeM8 | null {
  const v = copierJsonLecture(brut);
  if (v === JSON_LECTURE_INVALIDE || !objet(v) || !texte(v.statut)) return null;
  if (v.statut !== "manque" && v.statut !== "lu") return { genre: "inconnu", statut: v.statut };
  if (!texte(v.source)) return null;
  if (v.statut === "manque") {
    if (!textes(v.manque) || (v.a_lire !== null && !texte(v.a_lire))) return null;
    return { genre: "manque", source: v.source, manque: v.manque, aLire: v.a_lire };
  }
  if (!objet(v.constat) || !texte(v.constat.statut)) return null;
  if (v.constat.statut !== "CALCULE" && v.constat.statut !== "NON_CALCULABLE") {
    return { genre: "inconnu", statut: v.constat.statut };
  }
  const constat = lireConstat(v.constat), age = lireAge(v.age);
  if (!constat || !age || !entier(v.n_constats_recus) || v.n_constats_recus < 1 ||
      !texte(v.non_repris) || !texte(v.a_lire)) return null;
  return { genre: "lu", statut: "lu", source: v.source, nConstatsRecus: v.n_constats_recus,
    constat, age, nonRepris: v.non_repris, aLire: v.a_lire };
}
