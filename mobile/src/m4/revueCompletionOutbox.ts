import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { horodatageM10Valide } from "../m10/contrat";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { InterpretationResultatMetier } from "../outbox/vidangeur";
import {
  construireArgumentsPropositionRevueCompletion, construireArgumentsDecisionRevueCompletion,
  empreinteArgumentsPropositionRevueCompletion, figerPayloadDecisionRevueCompletion,
  lireDossierRevueCompletion, lireCreationPropositionRevueCompletion, lireDecisionRevueCompletion,
} from "./revueCompletionSources";

const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const ferme = (v: unknown, keys: readonly string[]): v is Record<string, unknown> =>
  objet(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const texte = (v: unknown): v is string => typeof v === "string" && /\P{White_Space}/u.test(v) && !/\p{Cs}/u.test(v);
const copie = (v: unknown): unknown => { const c = copierJsonLecture(v); return c === JSON_LECTURE_INVALIDE ? null : c; };
export interface DestinationRevueCompletion { readonly personne: string; readonly appareilId: string; readonly urlBase: string }
function destination(v: unknown) {
  const c = copie(v); if (!objet(c)) return null;
  const d = { personne: c.personne, appareil_id: c.appareilId, url_base: c.urlBase };
  return texte(d.personne) && texte(d.appareil_id) && texte(d.url_base) ? d as { personne: string; appareil_id: string; url_base: string } : null;
}
function argsP(v: unknown) {
  const c = copie(v);
  if (!objet(c) || !empreinteArgumentsPropositionRevueCompletion(c)) return null;
  return construireArgumentsPropositionRevueCompletion(c.intervention_id, c.decision, c.horodatage, c.motif, c.sources);
}
function mutation(type: "completion_review_proposal" | "completion_review_decision", payload: Record<string, unknown>,
  generer: () => string, horloge: HorlogeAppareil): MutationOutbox {
  if (!Number.isFinite(horloge.maintenant.getTime()) || !Number.isInteger(horloge.decalageMinutesUTC) || Math.abs(horloge.decalageMinutesUTC) >= 1440)
    throw new Error("Heure d'intention invalide.");
  const m = creerMutation({ type, chantierId: "approbations", payload }, generer, horloge);
  if (!texte(m.id) || !horodatageM10Valide(m.createdAtLocal)) throw new Error("Intention invalide.");
  return soumettreMutation(m);
}
export function creerMutationPropositionRevueCompletion(arguments_: unknown, generer: () => string, horloge: HorlogeAppareil, session: unknown): MutationOutbox {
  const a = argsP(arguments_), d = destination(session); if (!a || !d) throw new Error("Proposition invalide.");
  return mutation("completion_review_proposal", { arguments_proposition: a, destination_origine: d }, generer, horloge);
}
export function creerMutationDecisionRevueCompletion(arguments_: unknown, dossierBrut: unknown, argumentsLecture: unknown,
  generer: () => string, horloge: HorlogeAppareil, session: unknown): MutationOutbox {
  const c = copie(arguments_), d = destination(session), h = lireDossierRevueCompletion(dossierBrut, argumentsLecture);
  if (!objet(c) || !d || !h.ok || h.value.lecture !== "historique") throw new Error("Demande historique invalide.");
  const a = construireArgumentsDecisionRevueCompletion(c.demande_id, c.decision, c.motif);
  if (JSON.stringify(a) !== JSON.stringify(c) || a.demande_id !== h.value.demande.id) throw new Error("Décision invalide.");
  const p = figerPayloadDecisionRevueCompletion({ arguments_decision: a, outil_proposition: h.value.proposition.outil,
    capture_proposition: { demande_id: h.value.demande.id, empreinte_arguments: h.value.proposition.empreinte_arguments,
      sources: h.value.demande.arguments.sources }, destination_origine: d });
  if (!p) throw new Error("Capture de proposition invalide.");
  return mutation("completion_review_decision", { ...p }, generer, horloge);
}
function charge(m: MutationOutbox) {
  const c = copie(m);
  if (!objet(c) || !texte(c.id) || !horodatageM10Valide(c.createdAtLocal) || c.chantierId !== "approbations" || !objet(c.payload)) return null;
  const d = c.payload.destination_origine;
  if (!ferme(d, ["personne", "appareil_id", "url_base"]) || !texte(d.personne) || !texte(d.appareil_id) || !texte(d.url_base) || c.proprietaire !== d.personne) return null;
  const meta = { personne: d.personne, appareil_id: d.appareil_id, intention_uuid: c.id };
  if (c.type === "completion_review_proposal" && ferme(c.payload, ["arguments_proposition", "destination_origine"])) {
    const a = argsP(c.payload.arguments_proposition); return a ? { type: "P" as const, a, d, meta, c } : null;
  }
  const p = c.type === "completion_review_decision" ? figerPayloadDecisionRevueCompletion(c.payload) : null;
  return p ? { type: "D" as const, a: p.arguments_decision, p, d, meta, c } : null;
}
export function argumentsRpcRevueCompletion(m: MutationOutbox): Readonly<Record<string, unknown>> | null { const c = charge(m); return c ? { ...c.a } : null; }
export function verifierDestinationRevueCompletion(m: MutationOutbox, session: unknown): boolean {
  const c = charge(m), d = destination(session); return !!c && !!d && c.d.personne === d.personne && c.d.appareil_id === d.appareil_id && c.d.url_base === d.url_base;
}
const inconnue: InterpretationResultatMetier = { accepte: false, verdict: { code: "accuse_invalide", detail: "Confirmation inconnue ; conserver l'intention et sa clé d'origine." } };
export function interpreterRevueCompletion(brut: unknown, m?: MutationOutbox): InterpretationResultatMetier {
  const c = m && charge(m); if (!c) return inconnue;
  const r = c.type === "P" ? lireCreationPropositionRevueCompletion(brut, c.a, c.meta) :
    lireDecisionRevueCompletion(brut, c.p, { ...c.meta, horodatage_appareil_declare: c.c.createdAtLocal });
  return r.ok ? { accepte: true, resume: r.value } : inconnue;
}
export function validerRecuRevueCompletion(m: MutationOutbox): boolean {
  if (m.statut !== "envoyee") return false;
  const r = m.type === "completion_review_proposal" ? m.resumeAccepte : { ok: true, resultat: { accepte: true, resultat: m.resumeAccepte }, rejoue: false };
  return interpreterRevueCompletion(r, m).accepte;
}
