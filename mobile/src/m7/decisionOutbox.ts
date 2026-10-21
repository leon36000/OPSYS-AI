import { ouvrirEnveloppe } from "../admin/enveloppe";
import { creerMutation, formaterHorodatageLocal, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox, StatutMutation } from "../outbox/types";
import type { VerdictServeur } from "../outbox/vidangeur";
import type { LigneContenuM7 } from "./contrat";

export type DecisionMarketing = "approuver" | "rejeter";
export const CLE_PREUVE_LOCALE_MARKETING = "_marketing_local";
export interface AccuseDecisionMarketing {
  readonly contenu_id: string;
  readonly plateforme: string;
  readonly approval_status: "APPROVED" | "REJECTED";
  readonly par: string;
  readonly source: "appareil";
  readonly horodatage: string;
  readonly empreinte_texte: string;
  readonly prochaine_etape: string;
}
export type InterpretationDecisionMarketing =
  | { readonly accepte: true; readonly resume: AccuseDecisionMarketing }
  | { readonly accepte: false; readonly verdict: VerdictServeur };
export interface DecisionMarketingEnFile {
  readonly id: string;
  readonly contenuId: string | null;
  readonly statut: StatutMutation;
  readonly personne: string | null;
  readonly decision: DecisionMarketing | null;
}
interface ArgumentsDecisionMarketing {
  readonly contenu_id: string;
  readonly decision: DecisionMarketing;
  readonly horodatage: string;
  readonly motif?: string;
}
interface ContexteDecision {
  readonly args: ArgumentsDecisionMarketing;
  readonly plateforme: string;
}
const texte = (v: unknown): v is string => typeof v === "string" && v.trim() !== "";
const decisionValide = (v: unknown): v is DecisionMarketing => v === "approuver" || v === "rejeter";

function objet(v: unknown): Record<string, unknown> | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  try {
    const prototype = Object.getPrototypeOf(v);
    if (prototype !== Object.prototype && prototype !== null) {
      // JSON natif peut venir d'un autre realm (Response.json). Seul son prototype
      // Object terminal est admis ; aucun champ hérité ni accesseur n'est lu.
      if (Object.getPrototypeOf(prototype) !== null) return null;
      const constructeur = Object.getOwnPropertyDescriptor(prototype, "constructor");
      if (!constructeur || !("value" in constructeur) || typeof constructeur.value !== "function") return null;
      const nom = Object.getOwnPropertyDescriptor(constructeur.value, "name");
      if (!nom || !("value" in nom) || nom.value !== "Object") return null;
    }
    const propres: Record<string, unknown> = Object.create(null);
    for (const [cle, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(v))) {
      if (!("value" in descriptor)) return null;
      propres[cle] = descriptor.value;
    }
    return propres;
  } catch {
    return null;
  }
}
/** Instant ISO avec fuseau explicite ; Date.parse seul accepte des jours calendaires inexistants. */
function instant(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(v);
  if (!m || !Number.isFinite(Date.parse(v))) return false;
  const [annee, mois, jour, heure, minute, seconde] = m.slice(1, 7).map(Number);
  if (annee < 1 || mois < 1 || mois > 12 || jour < 1 || jour > 31 || heure > 23 || minute > 59 || seconde > 59) return false;
  const date = new Date(0);
  date.setUTCFullYear(annee, mois - 1, jour);
  return date.getUTCFullYear() === annee && date.getUTCMonth() === mois - 1 && date.getUTCDate() === jour;
}

/** L'intention porte les args et une preuve locale JSON ; rien n'est inféré d'un rôle fourni par le client. */
export function creerMutationDecisionMarketing(
  item: LigneContenuM7, decision: DecisionMarketing, motif: string,
  genererId: () => string, horloge: HorlogeAppareil,
): MutationOutbox {
  if (!texte(item.contenu_id) || !texte(item.wct_id) || !texte(item.plateforme) ||
    !Number.isSafeInteger(item.revision) || item.revision < 1 || !decisionValide(decision)) {
    throw new Error("contenu ou décision marketing invalide : aucune intention créée");
  }
  if (typeof motif !== "string" || (decision === "rejeter" && (motif.trim().length < 5 || motif.trim().length > 500))) {
    throw new Error("un rejet marketing exige un motif de 5 à 500 caractères");
  }
  if (!Number.isFinite(horloge.maintenant.getTime()) || !Number.isInteger(horloge.decalageMinutesUTC) ||
    Math.abs(horloge.decalageMinutesUTC) >= 24 * 60) throw new Error("horloge d'appareil marketing invalide");
  const horodatage = formaterHorodatageLocal(horloge);
  if (!instant(horodatage)) throw new Error("horodatage d'appareil marketing invalide");
  const brouillon = creerMutation({ type: "marketing_decision", chantierId: `marketing:${item.contenu_id}`,
    payload: { contenu_id: item.contenu_id, decision, horodatage,
      ...(decision === "rejeter" ? { motif: motif.trim() } : {}),
      [CLE_PREUVE_LOCALE_MARKETING]: { plateforme: item.plateforme, revision: item.revision, wct_id: item.wct_id },
    } }, genererId, horloge);
  if (!texte(brouillon.id)) throw new Error("identifiant d'intention marketing vide");
  return soumettreMutation(brouillon);
}

function contexte(m: MutationOutbox): ContexteDecision | null {
  if (m.type !== "marketing_decision") return null;
  const p = objet(m.payload), local = p && objet(p[CLE_PREUVE_LOCALE_MARKETING]);
  if (!p || !local || !texte(p.contenu_id) || m.chantierId !== `marketing:${p.contenu_id}` || !decisionValide(p.decision) ||
    !instant(p.horodatage) || p.horodatage !== m.createdAtLocal || !texte(local.plateforme) || !texte(local.wct_id) ||
    typeof local.revision !== "number" || !Number.isSafeInteger(local.revision) || local.revision < 1) return null;
  if (p.decision === "rejeter" && (typeof p.motif !== "string" || p.motif.trim().length < 5 || p.motif.trim().length > 500)) return null;
  const args: ArgumentsDecisionMarketing = p.decision === "rejeter" && typeof p.motif === "string"
    ? { contenu_id: p.contenu_id, decision: p.decision, horodatage: p.horodatage, motif: p.motif }
    : { contenu_id: p.contenu_id, decision: p.decision, horodatage: p.horodatage };
  return { args, plateforme: local.plateforme };
}

/** Arguments RPC stricts seulement. Une intention corrompue reste en file, sans envoi d'args devinés. */
export function construireArgumentsDecisionMarketing(m: MutationOutbox): Record<string, unknown> | null {
  const c = contexte(m);
  return c ? { ...c.args } : null;
}
/** Toutes les lignes marketing, y compris terminales/inconnues, pour ne masquer ni reçu ni quarantaine. */
export function decisionsMarketingEnFile(mutations: readonly MutationOutbox[]): readonly DecisionMarketingEnFile[] {
  return mutations.filter(m => m.type === "marketing_decision").map(m => {
    const p = objet(m.payload);
    const suffixe = m.chantierId.startsWith("marketing:") ? m.chantierId.slice("marketing:".length) : null;
    return { id: m.id, contenuId: texte(suffixe) ? suffixe : null, statut: m.statut,
      personne: m.proprietaire, decision: p && decisionValide(p.decision) ? p.decision : null };
  });
}
const INVALIDE: InterpretationDecisionMarketing = { accepte: false, verdict: {
  code: "accuse_invalide", detail: "Décision marketing non confirmée : conserver la même intention et sa clé.",
} };
const REFUS_TECHNIQUES_CONNUS = ["arguments_invalides", "mutation_conflit", "refus_metier", "hors_portee_role"];

/** ACK natif COUPLE lié à la personne persistée et à l'objet/choix/plateforme de l'intention. */
export function interpreterDecisionMarketing(brut: unknown, mutation?: MutationOutbox): InterpretationDecisionMarketing {
  const c = mutation && contexte(mutation);
  if (!mutation || !c || !texte(mutation.proprietaire)) return INVALIDE;
  const r = objet(brut);
  if (!r) return INVALIDE;
  if (r.ok === false) {
    if (typeof r.erreur !== "string" || !REFUS_TECHNIQUES_CONNUS.includes(r.erreur)) return INVALIDE;
    const ouverte = ouvrirEnveloppe(r, "couple");
    return ouverte.ok ? INVALIDE : { accepte: false, verdict: ouverte.verdict };
  }
  if (r.ok !== true || r.tronque === true) return INVALIDE;
  const metier = objet(r.resultat);
  if (!metier) return INVALIDE;
  if (metier.accepte === false) {
    const verdict = objet(metier.verdict);
    return verdict && texte(verdict.code) && typeof verdict.detail === "string"
      ? { accepte: false, verdict: { code: verdict.code, detail: verdict.detail } } : INVALIDE;
  }
  const valeur = objet(metier.resultat);
  const ouverte = ouvrirEnveloppe({ ok: true, resultat: { ...metier, resultat: valeur } }, "couple");
  if (!ouverte.ok || !valeur || valeur.contenu_id !== c.args.contenu_id || valeur.plateforme !== c.plateforme ||
    valeur.approval_status !== (c.args.decision === "approuver" ? "APPROVED" : "REJECTED") ||
    valeur.par !== mutation.proprietaire || valeur.source !== "appareil" || !instant(valeur.horodatage) ||
    typeof valeur.empreinte_texte !== "string" || !/^[0-9a-f]{64}$/.test(valeur.empreinte_texte) || !texte(valeur.prochaine_etape)) return INVALIDE;
  // Le statut a déjà été lié au choix ; les deux branches donnent un type exact sans assertion de type.
  const approval_status = c.args.decision === "approuver" ? "APPROVED" : "REJECTED";
  return { accepte: true, resume: { contenu_id: c.args.contenu_id, plateforme: c.plateforme, approval_status,
    par: mutation.proprietaire, source: "appareil", horodatage: valeur.horodatage,
    empreinte_texte: valeur.empreinte_texte, prochaine_etape: valeur.prochaine_etape } };
}
