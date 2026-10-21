import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { ETATS_INTERVENTION_M4 } from "./interventions";
import type { StatutInterventionM4 } from "./interventions";
import { estDecimal } from "../admin/lecteurs";
import { horodatageM10Valide } from "../m10/contrat";
import { CAUSES_VARIANCE, empreinteArgumentsClassementVariance, motifClassementValide } from "../m6/classementVariance";
import type { ClassementVarianceM6, ReferenceClassementM6, ReferenceVarianceM6, SelectionVarianceM6 } from "../m6/classementVariance";
import type { Reponse } from "../m7/contrat";

export const OUTIL_DOSSIER_REVUE_COMPLETION = "m4_lire_dossier_revue_completion_appareil";
export const OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES = "m4_resoudre_revue_completion_sources";
export const OUTIL_DECISION_REVUE_COMPLETION = "m9_decider_demande_approbation";
export interface SourcesRevueCompletion {
  readonly wct_id: string; readonly chantier_id: string; readonly completion_ligne_id: string;
  readonly transition_attendue_ligne_id: string; readonly reference_variance: ReferenceVarianceM6;
  readonly classements: readonly { readonly position_ligne: number; readonly materiau_id: string; readonly reference: ReferenceClassementM6 | null }[];
}
export interface ArgumentsPropositionRevueCompletion {
  readonly intervention_id: string; readonly decision: "verifiee" | "correction"; readonly horodatage: string;
  readonly motif: string; readonly sources: SourcesRevueCompletion;
}
export interface ArgumentsDecisionRevueCompletion {
  readonly demande_id: string; readonly decision: "approuver" | "refuser"; readonly motif?: string;
}
export interface ArgumentsDossierRevueCompletion { readonly intervention_id: string; readonly demande_id: string | null }
export interface BornesRevueCompletion { readonly limite_arguments_caracteres: 1500; readonly limite_enveloppe_caracteres: number }
export interface DossierRevueCompletionCourant {
  readonly version_schema: 1; readonly lecture: "courante"; readonly intervention_id: string; readonly statut: StatutInterventionM4;
  readonly wct: { readonly wct_id: string; readonly intervention_id: string; readonly chantier_id: string };
  readonly reference_completion: { readonly ligne_id: string; readonly hash_maillon: string };
  readonly reference_transition: { readonly ligne_id: string };
  readonly source_variance: ReferenceVarianceM6 & { readonly statut_variance: "evaluee"; readonly signal_critique: boolean;
    readonly seuil_pourcentage: number; readonly horodatage_completion: string };
  readonly lignes_critiques: readonly { readonly selection: SelectionVarianceM6;
    readonly source_ligne: { readonly materiau: string; readonly unite: string | null; readonly quantite_prevue: string;
      readonly quantite_reelle: string; readonly ecart_pourcentage: string | null; readonly critique: boolean };
    readonly classement_courant: ClassementVarianceM6 | null }[];
  readonly sources: SourcesRevueCompletion;
  readonly couverture: { readonly positions_critiques: readonly number[]; readonly positions_sans_classement: readonly number[] };
  readonly bornes: BornesRevueCompletion;
}
export interface PreuvePropositionRevueCompletion {
  readonly demande_id: string; readonly departement: "m04-field-ops"; readonly outil: typeof OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES;
  readonly niveau: "N4"; readonly empreinte_arguments: string;
  readonly proposant: { readonly personne: string; readonly role: "admin"; readonly appareil_id: string; readonly intention_uuid: string };
}
export interface PreuveCompletionRevueSources {
  readonly version_schema: 2; readonly demande_approbation_id: string;
  readonly association_decision: { readonly appareil_id: string; readonly intention_uuid: string; readonly empreinte_arguments: string; readonly horodatage_appareil_declare: string };
  readonly empreinte_arguments_proposition: string; readonly intervention_id: string; readonly wct_id: string; readonly chantier_id: string;
  readonly statut: "completed_pending_review" | "completed_verified"; readonly decision: "verifiee" | "correction";
  readonly ligne_id: string; readonly tete_chaine: string; readonly sources: SourcesRevueCompletion;
  readonly approuve_par: string; readonly role_approbateur: "nathan_owner"; readonly horodatage_decision_serveur: string;
}
export interface IssueRevueCompletion {
  readonly ok: boolean; readonly accepte?: boolean; readonly verdict?: { readonly code: string; readonly detail: string };
  readonly erreur?: string; readonly details?: string;
}
export interface DossierRevueCompletionHistorique {
  readonly version_schema: 1; readonly lecture: "historique";
  readonly demande: { readonly id: string; readonly cree_le: string; readonly departement: "m04-field-ops";
    readonly outil: typeof OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES; readonly niveau: "N4";
    readonly arguments: ArgumentsPropositionRevueCompletion; readonly statut: "en_attente" | "en_cours" | "refusee" | "executee" | "echec";
    readonly decide_par: string | null; readonly decide_role: string | null; readonly decide_le: string | null; readonly motif_decision: string | null };
  readonly proposition: PreuvePropositionRevueCompletion; readonly issue: IssueRevueCompletion | null;
  readonly preuve_completion: PreuveCompletionRevueSources | null; readonly bornes: BornesRevueCompletion;
}
export type DossierRevueCompletion = DossierRevueCompletionCourant | DossierRevueCompletionHistorique;
export interface MetaPropositionRevueCompletion { readonly personne: string; readonly appareil_id: string; readonly intention_uuid: string }
export interface MetaDecisionRevueCompletion extends MetaPropositionRevueCompletion { readonly horodatage_appareil_declare: string }
export interface PayloadDecisionRevueCompletion {
  readonly arguments_decision: ArgumentsDecisionRevueCompletion;
  readonly outil_proposition: typeof OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES;
  readonly capture_proposition: { readonly demande_id: string; readonly empreinte_arguments: string; readonly sources: SourcesRevueCompletion };
  readonly destination_origine: { readonly personne: string; readonly appareil_id: string; readonly url_base: string };
}
export interface CreationPropositionRevueCompletion {
  readonly ok: true; readonly version_schema: 1; readonly statut: "en_attente_approbation"; readonly demande_id: string;
  readonly details: string; readonly preuve_proposition: PreuvePropositionRevueCompletion; readonly rejoue: boolean;
}
export interface AccuseDecisionRevueCompletion {
  readonly demande_id: string; readonly decision: "approuver"; readonly statut: "executee";
  readonly outil: typeof OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES; readonly departement: "m04-field-ops"; readonly niveau: "N4";
  readonly decide_par: string; readonly role: "nathan_owner"; readonly decide_le: string;
  readonly preuve_completion: PreuveCompletionRevueSources; readonly issue?: IssueRevueCompletion;
}

const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const ferme = (v: unknown, keys: readonly string[], opt: readonly string[] = []): v is Record<string, unknown> =>
  objet(v) && keys.every(k => Object.hasOwn(v, k)) && Object.keys(v).every(k => keys.includes(k) || opt.includes(k));
const texte = (v: unknown): v is string => typeof v === "string" && /\P{White_Space}/u.test(v) && !/\p{Cs}/u.test(v);
const idM6 = (v: unknown): v is string => texte(v) && [...v].length <= 256 && !/\p{Cc}/u.test(v);
const demandeId = (v: unknown): v is string => texte(v) && [...v].length <= 32 && !/\p{Cc}/u.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && v.length === 64 && /^[0-9a-f]{64}$/.test(v);
const entier = (v: unknown, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
const decimal = (v: unknown): v is string => estDecimal(v) && !/[\p{Cc}\p{Cs}]/u.test(v);
const dateNative = (v: unknown): v is string => typeof v === "string" && horodatageM10Valide(v);
const motif = (v: unknown, vide = false): v is string => typeof v === "string" && [...v].length <= 500 &&
  !/\p{Cs}/u.test(v) && (vide || /\P{White_Space}/u.test(v));
function copie(v: unknown): unknown { const c = copierJsonLecture(v); return c === JSON_LECTURE_INVALIDE ? undefined : c; }
function egal(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => egal(v, b[i]));
  return objet(a) && objet(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && egal(a[k], b[k]));
}
function trierCles(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(trierCles);
  if (objet(v)) return Object.fromEntries(Object.keys(v).sort().map(k => [k, trierCles(v[k])]));
  return v;
}
const empreinte = (v: unknown) => bytesToHex(sha256(utf8ToBytes(JSON.stringify(trierCles(v)))));
const longueurJson = (v: unknown) => [...JSON.stringify(v)].length;
const statut = (v: unknown): v is StatutInterventionM4 => typeof v === "string" && ETATS_INTERVENTION_M4.some(s => s === v);
/** ISO civil avec fuseau et fraction exacte ; aucun Date.parse ou arrondi milliseconde. */
function microsecondes(v: unknown): bigint | null {
  if (!dateNative(v)) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(v);
  if (!m || m[0].length !== v.length) return null;
  const d = new Date(0); d.setUTCFullYear(Number(m[1]), Number(m[2]) - 1, Number(m[3])); d.setUTCHours(Number(m[4]), Number(m[5]), Number(m[6]), 0);
  const offset = m[8] === "Z" ? 0 : (Number(m[10]) * 60 + Number(m[11])) * (m[9] === "-" ? -1 : 1);
  return BigInt(d.getTime() - offset * 60000) * 1000n + BigInt((m[7] ?? "").padEnd(6, "0"));
}
const date = (v: unknown): v is string => microsecondes(v) !== null;
const memeInstant = (a: unknown, b: unknown) => microsecondes(a) !== null && microsecondes(a) === microsecondes(b);
function refClassement(v: unknown): v is ReferenceClassementM6 {
  return ferme(v, ["registre", "index", "hash_maillon"]) && v.registre === "classements_variance" && entier(v.index, 9999) && hash(v.hash_maillon);
}
function refVariance(v: unknown, wct: string): v is ReferenceVarianceM6 {
  return ferme(v, ["type", "evenement_id", "empreinte_charge"]) && v.type === "m6.variance_chantier" &&
    v.evenement_id === "m6-variance-" + wct + "-evaluee" && hash(v.empreinte_charge);
}
function sourcesValides(v: unknown): v is SourcesRevueCompletion {
  if (!ferme(v, ["wct_id", "chantier_id", "completion_ligne_id", "transition_attendue_ligne_id", "reference_variance", "classements"]) ||
    !idM6(v.wct_id) || !idM6(v.chantier_id) || !hash(v.completion_ligne_id) || !hash(v.transition_attendue_ligne_id) ||
    !refVariance(v.reference_variance, v.wct_id) || !Array.isArray(v.classements) || v.classements.length > 10000) return false;
  const positions = new Set<number>();
  return v.classements.every(c => {
    if (!ferme(c, ["position_ligne", "materiau_id", "reference"]) || !entier(c.position_ligne, 9999) || positions.has(c.position_ligne) ||
      !idM6(c.materiau_id) || !(c.reference === null || refClassement(c.reference))) return false;
    positions.add(c.position_ligne); return true;
  });
}
function argsPValides(v: unknown): v is ArgumentsPropositionRevueCompletion {
  return ferme(v, ["intervention_id", "decision", "horodatage", "motif", "sources"]) && idM6(v.intervention_id) &&
    (v.decision === "verifiee" || v.decision === "correction") && date(v.horodatage) && motif(v.motif) && sourcesValides(v.sources) &&
    (v.decision !== "verifiee" || v.sources.classements.every(c => c.reference !== null)) && longueurJson(v) <= 1500;
}
function argsDValides(v: unknown): v is ArgumentsDecisionRevueCompletion {
  return ferme(v, ["demande_id", "decision"], ["motif"]) && demandeId(v.demande_id) && (v.decision === "approuver" || v.decision === "refuser") &&
    (!Object.hasOwn(v, "motif") || motif(v.motif, true));
}
function argsLecture(v: unknown): v is ArgumentsDossierRevueCompletion {
  return ferme(v, ["intervention_id", "demande_id"]) && idM6(v.intervention_id) && (v.demande_id === null || demandeId(v.demande_id));
}
export function construireArgumentsDossierRevueCompletion(interventionId: unknown, demande: unknown = null): ArgumentsDossierRevueCompletion {
  const c = copie({ intervention_id: interventionId, demande_id: demande });
  if (!argsLecture(c)) throw new Error("Arguments de lecture de revue invalides.");
  return c;
}
export function construireArgumentsPropositionRevueCompletion(interventionId: unknown, decision: unknown, horodatage: unknown, motifDeclare: unknown, sources: unknown): ArgumentsPropositionRevueCompletion {
  const c = copie({ intervention_id: interventionId, decision, horodatage, motif: motifDeclare, sources });
  if (!argsPValides(c)) throw new Error("Proposition invalide ou hors borne ; aucune source partielle.");
  return c;
}
export function construireArgumentsDecisionRevueCompletion(demande: unknown, decision: unknown, motifDeclare?: unknown): ArgumentsDecisionRevueCompletion {
  const c = copie({ demande_id: demande, decision, ...(motifDeclare === undefined ? {} : { motif: motifDeclare }) });
  if (!argsDValides(c)) throw new Error("Arguments de décision invalides.");
  return c;
}
export function empreinteArgumentsPropositionRevueCompletion(brut: unknown): string | null {
  const c = copie(brut); return argsPValides(c) ? empreinte(c) : null;
}
export function empreinteArgumentsDecisionRevueCompletion(brut: unknown): string | null {
  const c = copie(brut); return argsDValides(c) ? empreinte(c) : null;
}
function bornes(v: unknown): v is BornesRevueCompletion {
  return ferme(v, ["limite_arguments_caracteres", "limite_enveloppe_caracteres"]) && v.limite_arguments_caracteres === 1500 &&
    entier(v.limite_enveloppe_caracteres, 5400) && v.limite_enveloppe_caracteres > 0;
}
function issue(v: unknown): v is IssueRevueCompletion {
  return ferme(v, ["ok"], ["accepte", "verdict", "erreur", "details"]) && typeof v.ok === "boolean" &&
    (!Object.hasOwn(v, "accepte") || typeof v.accepte === "boolean") &&
    (!Object.hasOwn(v, "verdict") || ferme(v.verdict, ["code", "detail"]) && typeof v.verdict.code === "string" && typeof v.verdict.detail === "string") &&
    (!Object.hasOwn(v, "erreur") || typeof v.erreur === "string") && (!Object.hasOwn(v, "details") || typeof v.details === "string");
}
function preuveP(v: unknown, args: ArgumentsPropositionRevueCompletion, demande: string): v is PreuvePropositionRevueCompletion {
  return ferme(v, ["demande_id", "departement", "outil", "niveau", "empreinte_arguments", "proposant"]) && v.demande_id === demande &&
    v.departement === "m04-field-ops" && v.outil === OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES && v.niveau === "N4" &&
    v.empreinte_arguments === empreinte(args) && ferme(v.proposant, ["personne", "role", "appareil_id", "intention_uuid"]) &&
    texte(v.proposant.personne) && v.proposant.role === "admin" && texte(v.proposant.appareil_id) && texte(v.proposant.intention_uuid);
}
function preuveD(v: unknown): v is PreuveCompletionRevueSources {
  return ferme(v, ["version_schema", "demande_approbation_id", "association_decision", "empreinte_arguments_proposition", "intervention_id",
    "wct_id", "chantier_id", "statut", "decision", "ligne_id", "tete_chaine", "sources", "approuve_par", "role_approbateur", "horodatage_decision_serveur"]) &&
    v.version_schema === 2 && demandeId(v.demande_approbation_id) && hash(v.empreinte_arguments_proposition) &&
    idM6(v.intervention_id) && idM6(v.wct_id) && idM6(v.chantier_id) && sourcesValides(v.sources) &&
    v.wct_id === v.sources.wct_id && v.chantier_id === v.sources.chantier_id &&
    ((v.decision === "verifiee" && v.statut === "completed_verified") || (v.decision === "correction" && v.statut === "completed_pending_review")) &&
    hash(v.ligne_id) && hash(v.tete_chaine) && texte(v.approuve_par) && v.role_approbateur === "nathan_owner" && date(v.horodatage_decision_serveur) &&
    ferme(v.association_decision, ["appareil_id", "intention_uuid", "empreinte_arguments", "horodatage_appareil_declare"]) &&
    texte(v.association_decision.appareil_id) && texte(v.association_decision.intention_uuid) && hash(v.association_decision.empreinte_arguments) &&
    date(v.association_decision.horodatage_appareil_declare);
}
function classification(v: unknown, sel: SelectionVarianceM6): v is ClassementVarianceM6 {
  const keys = ["reference", "selection", "cause", "motif", "reference_precedente", "auteur", "appareil_id", "classe_le", "horodatage_appareil_declare", "references_pieces"];
  if (!objet(v)) return false;
  const v2 = Object.hasOwn(v, "version_schema");
  if (!ferme(v, [...keys, ...(v2 ? ["version_schema", "intention"] : [])]) || !refClassement(v.reference) || !egal(v.selection, sel) ||
    !CAUSES_VARIANCE.some(c => c === v.cause) || !motifClassementValide(v.motif) || !(v.reference_precedente === null || refClassement(v.reference_precedente)) ||
    !ferme(v.auteur, ["personne", "role", "source"]) || !idM6(v.auteur.personne) || v.auteur.role !== "admin" || v.auteur.source !== "appareil" ||
    !idM6(v.appareil_id) || !dateNative(v.classe_le) || !dateNative(v.horodatage_appareil_declare) ||
    !Array.isArray(v.references_pieces) || v.references_pieces.length > 8) return false;
  const index = new Set<number>();
  for (const p of v.references_pieces) {
    if (!ferme(p, ["reference_mouvement", "reference_preuve", "positions_photos"]) ||
      !ferme(p.reference_mouvement, ["registre", "index", "hash_maillon"]) || p.reference_mouvement.registre !== "principal" ||
      !entier(p.reference_mouvement.index, 9999) || index.has(p.reference_mouvement.index) || !hash(p.reference_mouvement.hash_maillon) ||
      !(p.reference_preuve === null || ferme(p.reference_preuve, ["registre", "index", "hash_maillon"]) &&
        p.reference_preuve.registre === "preuves_pertes_bris" && entier(p.reference_preuve.index, 9999) && hash(p.reference_preuve.hash_maillon)) ||
      !Array.isArray(p.positions_photos) || p.positions_photos.length > 3 || !p.positions_photos.every(n => entier(n, 2)) ||
      new Set(p.positions_photos).size !== p.positions_photos.length || p.reference_preuve === null && p.positions_photos.length !== 0) return false;
    index.add(p.reference_mouvement.index);
  }
  if (v.reference_precedente !== null && (v.reference_precedente as ReferenceClassementM6).index >= v.reference.index) return false;
  return !v2 || v.version_schema === 2 && ferme(v.intention, ["appareil_id", "intention_uuid", "empreinte_arguments"]) &&
    v.intention.appareil_id === v.appareil_id && idM6(v.intention.intention_uuid) && v.intention.empreinte_arguments ===
      empreinteArgumentsClassementVariance({ selection: sel, cause: v.cause, motif: v.motif, classement_attendu: v.reference_precedente, references_pieces: v.references_pieces });
}
function dossierCourant(v: unknown, args: ArgumentsDossierRevueCompletion): v is DossierRevueCompletionCourant {
  if (!ferme(v, ["version_schema", "lecture", "intervention_id", "statut", "wct", "reference_completion", "reference_transition",
    "source_variance", "lignes_critiques", "sources", "couverture", "bornes"]) || v.version_schema !== 1 || v.lecture !== "courante" ||
    v.intervention_id !== args.intervention_id || args.demande_id !== null || !statut(v.statut) || !sourcesValides(v.sources) || !bornes(v.bornes) ||
    !ferme(v.wct, ["wct_id", "intervention_id", "chantier_id"]) || v.wct.intervention_id !== v.intervention_id ||
    v.wct.wct_id !== v.sources.wct_id || v.wct.chantier_id !== v.sources.chantier_id ||
    !ferme(v.reference_completion, ["ligne_id", "hash_maillon"]) || v.reference_completion.ligne_id !== v.sources.completion_ligne_id || !hash(v.reference_completion.hash_maillon) ||
    !ferme(v.reference_transition, ["ligne_id"]) || v.reference_transition.ligne_id !== v.sources.transition_attendue_ligne_id ||
    !ferme(v.source_variance, ["type", "evenement_id", "empreinte_charge", "statut_variance", "signal_critique", "seuil_pourcentage", "horodatage_completion"]) ||
    !egal({ type: v.source_variance.type, evenement_id: v.source_variance.evenement_id, empreinte_charge: v.source_variance.empreinte_charge }, v.sources.reference_variance) ||
    v.source_variance.statut_variance !== "evaluee" || typeof v.source_variance.signal_critique !== "boolean" ||
    typeof v.source_variance.seuil_pourcentage !== "number" || !Number.isFinite(v.source_variance.seuil_pourcentage) || !date(v.source_variance.horodatage_completion) ||
    !Array.isArray(v.lignes_critiques) || v.lignes_critiques.length !== v.sources.classements.length ||
    !ferme(v.couverture, ["positions_critiques", "positions_sans_classement"])) return false;
  const positions: number[] = [], manquantes: number[] = [];
  for (const [i, l] of v.lignes_critiques.entries()) {
    const capture = v.sources.classements[i];
    if (!ferme(l, ["selection", "source_ligne", "classement_courant"]) ||
      !ferme(l.selection, ["wct_id", "reference_variance", "position_ligne", "materiau_id"]) || l.selection.wct_id !== v.sources.wct_id ||
      !egal(l.selection.reference_variance, v.sources.reference_variance) || l.selection.position_ligne !== capture.position_ligne || l.selection.materiau_id !== capture.materiau_id ||
      !ferme(l.source_ligne, ["materiau", "unite", "quantite_prevue", "quantite_reelle", "ecart_pourcentage", "critique"]) ||
      !texte(l.source_ligne.materiau) || !(l.source_ligne.unite === null || texte(l.source_ligne.unite)) ||
      !decimal(l.source_ligne.quantite_prevue) || !decimal(l.source_ligne.quantite_reelle) ||
      !(l.source_ligne.ecart_pourcentage === null || decimal(l.source_ligne.ecart_pourcentage)) || l.source_ligne.critique !== true ||
      !(l.classement_courant === null ? capture.reference === null :
        classification(l.classement_courant, l.selection as unknown as SelectionVarianceM6) && egal(l.classement_courant.reference, capture.reference))) return false;
    positions.push(capture.position_ligne); if (l.classement_courant === null) manquantes.push(capture.position_ligne);
  }
  return egal(v.couverture.positions_critiques, positions) && egal(v.couverture.positions_sans_classement, manquantes);
}
function dossierHistorique(v: unknown, args: ArgumentsDossierRevueCompletion): v is DossierRevueCompletionHistorique {
  if (!ferme(v, ["version_schema", "lecture", "demande", "proposition", "issue", "preuve_completion", "bornes"]) ||
    v.version_schema !== 1 || v.lecture !== "historique" || !bornes(v.bornes) ||
    !ferme(v.demande, ["id", "cree_le", "departement", "outil", "niveau", "arguments", "statut", "decide_par", "decide_role", "decide_le", "motif_decision"]) ||
    args.demande_id === null || v.demande.id !== args.demande_id || !date(v.demande.cree_le) || v.demande.departement !== "m04-field-ops" ||
    v.demande.outil !== OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES || v.demande.niveau !== "N4" ||
    !argsPValides(v.demande.arguments) || v.demande.arguments.intervention_id !== args.intervention_id ||
    !["en_attente", "en_cours", "refusee", "executee", "echec"].includes(v.demande.statut as string) ||
    !(v.demande.decide_par === null || texte(v.demande.decide_par)) || !(v.demande.decide_role === null || texte(v.demande.decide_role)) ||
    !(v.demande.decide_le === null || date(v.demande.decide_le)) || !(v.demande.motif_decision === null || motif(v.demande.motif_decision, true)) ||
    !preuveP(v.proposition, v.demande.arguments, args.demande_id) || !(v.issue === null || issue(v.issue))) return false;
  if (v.preuve_completion === null) return true;
  if (v.issue !== null && (!v.issue.ok || v.issue.accepte === false)) return false;
  return preuveD(v.preuve_completion) && v.demande.statut === "executee" && v.preuve_completion.demande_approbation_id === args.demande_id &&
    v.preuve_completion.intervention_id === v.demande.arguments.intervention_id && v.preuve_completion.decision === v.demande.arguments.decision &&
    egal(v.preuve_completion.sources, v.demande.arguments.sources) && v.preuve_completion.empreinte_arguments_proposition === v.proposition.empreinte_arguments &&
    v.preuve_completion.approuve_par === v.demande.decide_par && v.preuve_completion.role_approbateur === v.demande.decide_role &&
    memeInstant(v.preuve_completion.horodatage_decision_serveur, v.demande.decide_le);
}
const illisible = <T,>(): Reponse<T> => ({ ok: false, code: "reponse_illisible", detail: "Dossier de revue illisible ; aucune projection partielle." });
const inconnue = <T,>(): Reponse<T> => ({ ok: false, code: "accuse_invalide", detail: "Confirmation inconnue ; conserver l'intention et sa clé d'origine." });
/** T0 couple unique r5 ; aucune donnée reconstruite depuis un refus. */
export function lireDossierRevueCompletion(brut: unknown, argumentsLecture: unknown): Reponse<DossierRevueCompletion> {
  const c = copie(brut), args = copie(argumentsLecture);
  if (!argsLecture(args) || !ferme(c, ["ok", "resultat"]) || c.ok !== true || !objet(c.resultat) || longueurJson(c) > 5400) return illisible();
  if (ferme(c.resultat, ["accepte", "verdict"]) && c.resultat.accepte === false && ferme(c.resultat.verdict, ["code", "detail"]) &&
    texte(c.resultat.verdict.code) && texte(c.resultat.verdict.detail)) return { ok: false, code: c.resultat.verdict.code, detail: c.resultat.verdict.detail };
  if (!ferme(c.resultat, ["accepte", "resultat"]) || c.resultat.accepte !== true) return illisible();
  const v = c.resultat.resultat;
  if (!(dossierCourant(v, args) || dossierHistorique(v, args)) || longueurJson(c) > v.bornes.limite_enveloppe_caracteres) return illisible();
  return { ok: true, value: v };
}
function metaPValide(v: unknown): v is MetaPropositionRevueCompletion {
  return ferme(v, ["personne", "appareil_id", "intention_uuid"]) && texte(v.personne) && texte(v.appareil_id) && texte(v.intention_uuid);
}
export function lireCreationPropositionRevueCompletion(brut: unknown, argumentsProposition: unknown, metadataLocale: unknown): Reponse<CreationPropositionRevueCompletion> {
  const c = copie(brut), args = copie(argumentsProposition), m = copie(metadataLocale);
  if (!argsPValides(args) || !metaPValide(m) || !ferme(c, ["ok", "version_schema", "statut", "demande_id", "details", "preuve_proposition", "rejoue"]) ||
    c.ok !== true || c.version_schema !== 1 || c.statut !== "en_attente_approbation" || !demandeId(c.demande_id) ||
    !texte(c.details) || [...c.details].length > 1000 || typeof c.rejoue !== "boolean" || longueurJson(c) > 5400 ||
    !preuveP(c.preuve_proposition, args, c.demande_id) ||
    c.preuve_proposition.proposant.personne !== m.personne || c.preuve_proposition.proposant.appareil_id !== m.appareil_id ||
    c.preuve_proposition.proposant.intention_uuid !== m.intention_uuid) return inconnue();
  // Le journal P n'atteste pas l'heure appareil.
  return { ok: true, value: c as unknown as CreationPropositionRevueCompletion };
}
function payloadValide(v: unknown): v is PayloadDecisionRevueCompletion {
  return ferme(v, ["arguments_decision", "outil_proposition", "capture_proposition", "destination_origine"]) &&
    argsDValides(v.arguments_decision) && v.outil_proposition === OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES &&
    ferme(v.capture_proposition, ["demande_id", "empreinte_arguments", "sources"]) &&
    v.capture_proposition.demande_id === v.arguments_decision.demande_id && hash(v.capture_proposition.empreinte_arguments) &&
    sourcesValides(v.capture_proposition.sources) && ferme(v.destination_origine, ["personne", "appareil_id", "url_base"]) &&
    texte(v.destination_origine.personne) && texte(v.destination_origine.appareil_id) && texte(v.destination_origine.url_base);
}
export function figerPayloadDecisionRevueCompletion(brut: unknown): PayloadDecisionRevueCompletion | null {
  const c = copie(brut); return payloadValide(c) ? c : null;
}
/** Seul own-maillon positif r4 est terminal ; refus sans preuve D = UNKNOWN. */
export function lireDecisionRevueCompletion(brut: unknown, payloadLocal: unknown, metadataLocale: unknown): Reponse<AccuseDecisionRevueCompletion> {
  const c = copie(brut), p = copie(payloadLocal), m = copie(metadataLocale);
  if (!payloadValide(p) || !ferme(m, ["personne", "appareil_id", "intention_uuid", "horodatage_appareil_declare"]) ||
    !texte(m.intention_uuid) || !date(m.horodatage_appareil_declare) || m.personne !== p.destination_origine.personne ||
    m.appareil_id !== p.destination_origine.appareil_id || p.arguments_decision.decision !== "approuver" ||
    !ferme(c, ["ok", "resultat", "rejoue"]) || c.ok !== true || typeof c.rejoue !== "boolean" || longueurJson(c) > 5400 ||
    !ferme(c.resultat, ["accepte", "resultat"]) || c.resultat.accepte !== true) return inconnue();
  const a = c.resultat.resultat;
  if (!ferme(a, ["demande_id", "decision", "statut", "outil", "departement", "niveau", "decide_par", "role", "decide_le", "preuve_completion"], ["issue"]) ||
    a.demande_id !== p.arguments_decision.demande_id || a.decision !== "approuver" || a.statut !== "executee" ||
    a.outil !== OUTIL_PROPOSITION_REVUE_COMPLETION_SOURCES || a.departement !== "m04-field-ops" || a.niveau !== "N4" ||
    a.decide_par !== m.personne || a.role !== "nathan_owner" || !date(a.decide_le) ||
    (Object.hasOwn(a, "issue") && (!issue(a.issue) || !a.issue.ok || a.issue.accepte === false)) || !preuveD(a.preuve_completion)) return inconnue();
  const proof = a.preuve_completion;
  if (proof.demande_approbation_id !== a.demande_id || proof.empreinte_arguments_proposition !== p.capture_proposition.empreinte_arguments ||
    !egal(proof.sources, p.capture_proposition.sources) || proof.approuve_par !== a.decide_par || proof.role_approbateur !== a.role ||
    !memeInstant(proof.horodatage_decision_serveur, a.decide_le) || proof.association_decision.appareil_id !== m.appareil_id ||
    proof.association_decision.intention_uuid !== m.intention_uuid || proof.association_decision.empreinte_arguments !== empreinte(p.arguments_decision) ||
    !memeInstant(proof.association_decision.horodatage_appareil_declare, m.horodatage_appareil_declare)) return inconnue();
  // P est opaque ici : APP.argsP et intervention sont liés par le checker serveur.
  return { ok: true, value: a as unknown as AccuseDecisionRevueCompletion };
}
