import { estObjet, texteNullable, texteOuNull } from "../admin/lecteurs";

/** Contrats M9 T4.21 : lectures courantes, jamais un snapshot figé entre pages. */
export const OUTIL_BRIEFING = "m9_produire_briefing_matin";
export const OUTIL_SUITE_BRIEFING = "m9_lire_suite_briefing";
export const OUTIL_ALERTES_M9 = "m9_lire_alertes_m8";
export const OUTIL_ETAT_M9 = "m9_lire_etat_consolide";
export const SECTIONS_BRIEFING = ["decisions_en_attente", "alertes_m8", "faits_veille"] as const;
export type SectionBriefing = (typeof SECTIONS_BRIEFING)[number];
export interface DecisionM9 {
  readonly type: string;
  readonly id: string;
  readonly resume: string;
  readonly niveau: string | null;
  readonly depuis: string;
  readonly action_proposee: string;
  readonly departement: string;
}
export interface AlerteM9 {
  readonly evenement_id: string;
  readonly metric_id: string;
  readonly type_alerte: string;
  readonly quoi: string;
  readonly a_qui: string;
  readonly pourquoi: string;
  readonly preuve: Readonly<Record<string, unknown>>;
  readonly source: string;
  readonly horodatage_reference: string;
}
export interface FaitM9 {
  readonly module_source: string;
  readonly horodatage: string;
  readonly valeurs: Readonly<Record<string, string>>;
}
export interface MaillonM9 extends FaitM9 {
  readonly index: number;
  readonly hash_precedent: string;
  readonly hash_maillon: string;
}
export interface ContradictionM9 {
  readonly ligne_id_a: number;
  readonly ligne_id_b: number;
  readonly module_source: string;
  readonly horodatage: string;
  readonly horodatage_utc: string;
  readonly horodatages_sources: readonly string[];
}
export interface ManqueM9 {
  readonly section: string;
  readonly constat: string;
  readonly verifie: string;
}
export type ItemM9 = DecisionM9 | AlerteM9 | FaitM9;
export interface SectionM9<T> {
  readonly items: readonly T[];
  readonly vide: boolean;
}
export interface SuiteDemandee {
  readonly section: SectionBriefing;
  readonly reste: number;
  readonly outil: typeof OUTIL_SUITE_BRIEFING;
  readonly arguments: {
    readonly maintenant: string;
    readonly section: SectionBriefing;
    readonly depart: number;
  };
}
export interface BriefingM9 {
  readonly type: "BRIEFING_MATIN";
  readonly jour: string;
  readonly veille: string;
  readonly briefing_id: string;
  readonly ordre_sections: readonly string[];
  readonly sections: {
    readonly decisions_en_attente: SectionM9<DecisionM9>;
    readonly alertes_m8: SectionM9<AlerteM9>;
    readonly faits_veille: SectionM9<FaitM9>;
    readonly manques_pour_conclure: SectionM9<ManqueM9>;
  };
  readonly affichage: {
    readonly complet: boolean;
    readonly n_non_affiches: number;
    readonly non_affiches: Readonly<Record<SectionBriefing, number>>;
    readonly lire_la_suite: readonly SuiteDemandee[];
    readonly message: string | null;
  };
}
export interface PageM9<T> {
  readonly depart: number;
  readonly total: number;
  readonly reste: number;
  readonly prochain_depart: number | null;
  readonly message: string | null;
  readonly items: readonly T[];
}
export interface SuiteBriefingM9 extends PageM9<ItemM9> {
  readonly type: "BRIEFING_MATIN_SUITE";
  readonly jour: string;
  readonly section: SectionBriefing;
}
export interface AlertesM9 extends PageM9<AlerteM9> {
  readonly type: "ALERTES_M8";
  readonly source: string;
  readonly ordre: string;
  readonly alertes: readonly AlerteM9[];
}
export interface EtatConsolideM9 {
  readonly type: "ETAT_CONSOLIDE";
  readonly etat_id: string;
  readonly faits_par_module: Readonly<Record<string, MaillonM9>>;
  readonly contradictions: readonly ContradictionM9[];
}

function entierSur(v: unknown): number | null {
  return typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : null;
}

const date = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/i.test(v);
function textes(v: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((k) => texteOuNull(v[k]) !== null);
}
function liste<T>(v: unknown, lire: (v: unknown) => T | null): readonly T[] | null {
  if (!Array.isArray(v)) return null;
  const items = v.map(lire);
  return items.some((x) => x === null) ? null : (items as T[]);
}
function decision(v: unknown): DecisionM9 | null {
  if (
    !estObjet(v) ||
    !textes(v, ["type", "id", "resume", "depuis", "action_proposee", "departement"]) ||
    texteNullable(v.niveau) === undefined
  )
    return null;
  return {
    type: v.type as string,
    id: v.id as string,
    resume: v.resume as string,
    depuis: v.depuis as string,
    action_proposee: v.action_proposee as string,
    departement: v.departement as string,
    niveau: v.niveau as string | null,
  };
}
function alerte(v: unknown): AlerteM9 | null {
  if (
    !estObjet(v) ||
    !textes(v, [
      "evenement_id",
      "metric_id",
      "type_alerte",
      "quoi",
      "a_qui",
      "pourquoi",
      "source",
      "horodatage_reference",
    ]) ||
    !estObjet(v.preuve)
  )
    return null;
  return {
    evenement_id: v.evenement_id as string,
    metric_id: v.metric_id as string,
    type_alerte: v.type_alerte as string,
    quoi: v.quoi as string,
    a_qui: v.a_qui as string,
    pourquoi: v.pourquoi as string,
    source: v.source as string,
    horodatage_reference: v.horodatage_reference as string,
    preuve: v.preuve,
  };
}
function fait(v: unknown): FaitM9 | null {
  if (
    !estObjet(v) ||
    !textes(v, ["module_source", "horodatage"]) ||
    !estObjet(v.valeurs) ||
    Object.values(v.valeurs).some((x) => typeof x !== "string")
  )
    return null;
  return {
    module_source: v.module_source as string,
    horodatage: v.horodatage as string,
    valeurs: v.valeurs as Record<string, string>,
  };
}
function manque(v: unknown): ManqueM9 | null {
  return estObjet(v) && textes(v, ["section", "constat", "verifie"])
    ? { section: v.section as string, constat: v.constat as string, verifie: v.verifie as string }
    : null;
}
function lireSection<T>(v: unknown, reader: (v: unknown) => T | null): SectionM9<T> | null {
  if (!estObjet(v) || typeof v.vide !== "boolean") return null;
  const items = liste(v.items, reader);
  return items === null || (v.vide && items.length > 0) ? null : { items, vide: v.vide };
}
export function estSectionBriefing(v: unknown): v is SectionBriefing {
  return typeof v === "string" && (SECTIONS_BRIEFING as readonly string[]).includes(v);
}
export function lireBriefing(v: unknown): BriefingM9 | null {
  if (
    !estObjet(v) ||
    v.type !== "BRIEFING_MATIN" ||
    !date(v.jour) ||
    !date(v.veille) ||
    !hash(v.briefing_id) ||
    !estObjet(v.sections) ||
    !estObjet(v.affichage)
  )
    return null;
  if (
    !Array.isArray(v.ordre_sections) ||
    v.ordre_sections.join("|") !== [...SECTIONS_BRIEFING, "manques_pour_conclure"].join("|")
  )
    return null;
  const decisions = lireSection(v.sections.decisions_en_attente, decision),
    alertes = lireSection(v.sections.alertes_m8, alerte),
    faits = lireSection(v.sections.faits_veille, fait),
    manques = lireSection(v.sections.manques_pour_conclure, manque);
  const a = v.affichage;
  if (
    !decisions ||
    !alertes ||
    !faits ||
    !manques ||
    typeof a.complet !== "boolean" ||
    !estObjet(a.non_affiches) ||
    !Array.isArray(a.lire_la_suite) ||
    texteNullable(a.message) === undefined
  )
    return null;
  const nonAffiches = a.non_affiches;
  const counts = Object.fromEntries(SECTIONS_BRIEFING.map((s) => [s, entierSur(nonAffiches[s])]));
  if (Object.values(counts).some((x) => x === null) || entierSur(a.n_non_affiches) === null)
    return null;
  if (
    a.n_non_affiches !== SECTIONS_BRIEFING.reduce((n, s) => n + (counts[s] as number), 0) ||
    a.complet !== (a.n_non_affiches === 0)
  )
    return null;
  const suites: SuiteDemandee[] = [];
  for (const raw of a.lire_la_suite) {
    if (
      !estObjet(raw) ||
      !estSectionBriefing(raw.section) ||
      raw.outil !== OUTIL_SUITE_BRIEFING ||
      !estObjet(raw.arguments) ||
      raw.arguments.section !== raw.section ||
      texteOuNull(raw.arguments.maintenant) === null ||
      entierSur(raw.arguments.depart) === null ||
      raw.reste !== counts[raw.section] ||
      raw.reste === 0
    )
      return null;
    const section = { decisions_en_attente: decisions, alertes_m8: alertes, faits_veille: faits }[
      raw.section
    ];
    if (
      raw.arguments.depart !== section.items.length ||
      suites.some((s) => s.section === raw.section)
    )
      return null;
    suites.push({
      section: raw.section,
      reste: raw.reste as number,
      outil: OUTIL_SUITE_BRIEFING,
      arguments: {
        maintenant: raw.arguments.maintenant as string,
        section: raw.section,
        depart: raw.arguments.depart as number,
      },
    });
  }
  if (suites.length !== SECTIONS_BRIEFING.filter((s) => (counts[s] as number) > 0).length)
    return null;
  return {
    type: "BRIEFING_MATIN",
    jour: v.jour,
    veille: v.veille,
    briefing_id: v.briefing_id,
    ordre_sections: v.ordre_sections as string[],
    sections: {
      decisions_en_attente: decisions,
      alertes_m8: alertes,
      faits_veille: faits,
      manques_pour_conclure: manques,
    },
    affichage: {
      complet: a.complet,
      n_non_affiches: a.n_non_affiches as number,
      non_affiches: counts as Record<SectionBriefing, number>,
      lire_la_suite: suites,
      message: a.message as string | null,
    },
  };
}
function page<T>(
  v: Record<string, unknown>,
  depart: number,
  items: readonly T[] | null,
  countKey: string,
): PageM9<T> | null {
  const total = entierSur(v.total),
    reste = entierSur(v.reste),
    nombre = entierSur(v[countKey]);
  const next = v.prochain_depart === null ? null : entierSur(v.prochain_depart);
  if (
    items === null ||
    total === null ||
    reste === null ||
    nombre === null ||
    v.depart !== depart ||
    !Number.isSafeInteger(depart) ||
    depart < 0 ||
    nombre !== items.length ||
    total !== depart + nombre + reste ||
    (reste === 0 ? v.prochain_depart !== null : next !== depart + nombre || nombre === 0) ||
    texteNullable(v.message) === undefined
  )
    return null;
  return {
    depart,
    total,
    reste,
    prochain_depart: next,
    message: v.message as string | null,
    items,
  };
}
export function lireSuiteBriefing(
  v: unknown,
  section: SectionBriefing,
  depart: number,
): SuiteBriefingM9 | null {
  if (!estObjet(v) || v.type !== "BRIEFING_MATIN_SUITE" || v.section !== section || !date(v.jour))
    return null;
  const reader: (v: unknown) => ItemM9 | null =
    section === "decisions_en_attente" ? decision : section === "alertes_m8" ? alerte : fait;
  const p = page(v, depart, liste(v.items, reader), "affiches");
  return p === null ? null : { ...p, type: "BRIEFING_MATIN_SUITE", jour: v.jour, section };
}
export function lireAlertesM9(v: unknown, depart: number): AlertesM9 | null {
  if (!estObjet(v) || v.type !== "ALERTES_M8" || !textes(v, ["source", "ordre"])) return null;
  const p = page(v, depart, liste(v.alertes, alerte), "affichees");
  return p === null
    ? null
    : {
        ...p,
        type: "ALERTES_M8",
        source: v.source as string,
        ordre: v.ordre as string,
        alertes: p.items,
      };
}
export function lireEtatConsolide(v: unknown): EtatConsolideM9 | null {
  if (
    !estObjet(v) ||
    v.type !== "ETAT_CONSOLIDE" ||
    !hash(v.etat_id) ||
    !estObjet(v.faits_par_module)
  )
    return null;
  const faits: Record<string, MaillonM9> = Object.create(null);
  for (const [module, raw] of Object.entries(v.faits_par_module)) {
    const f = fait(raw);
    if (
      !f ||
      !estObjet(raw) ||
      f.module_source !== module ||
      entierSur(raw.index) === null ||
      typeof raw.hash_precedent !== "string" ||
      !hash(raw.hash_maillon)
    )
      return null;
    faits[module] = {
      ...f,
      index: raw.index as number,
      hash_precedent: raw.hash_precedent,
      hash_maillon: raw.hash_maillon,
    };
  }
  const contradictions = liste<ContradictionM9>(v.contradictions, (raw) => {
    if (
      !estObjet(raw) ||
      entierSur(raw.ligne_id_a) === null ||
      entierSur(raw.ligne_id_b) === null ||
      !textes(raw, ["module_source", "horodatage", "horodatage_utc"]) ||
      !Array.isArray(raw.horodatages_sources) ||
      raw.horodatages_sources.some((x) => typeof x !== "string")
    )
      return null;
    return {
      ligne_id_a: raw.ligne_id_a as number,
      ligne_id_b: raw.ligne_id_b as number,
      module_source: raw.module_source as string,
      horodatage: raw.horodatage as string,
      horodatage_utc: raw.horodatage_utc as string,
      horodatages_sources: raw.horodatages_sources as string[],
    };
  });
  return contradictions === null
    ? null
    : { type: "ETAT_CONSOLIDE", etat_id: v.etat_id, faits_par_module: faits, contradictions };
}
