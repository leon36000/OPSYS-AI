import { appelerLecture } from "./appel";
import type { ResultatSection } from "./lecture";
import type { DepotOutbox } from "../outbox/depot";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
import { creerChargeurApprobations } from "../approbations/chargeur";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { obtenirDepot, declencherVidange } from "../outbox/service";
import { genererMutationId } from "../outbox/id";
import { formaterHorodatageLocal } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import {
  construireArgumentsDossierRevueCompletion, construireArgumentsPropositionRevueCompletion,
  construireArgumentsDecisionRevueCompletion, lireDossierRevueCompletion, OUTIL_DOSSIER_REVUE_COMPLETION,
} from "../m4/revueCompletionSources";
import type { DossierRevueCompletion } from "../m4/revueCompletionSources";
import {
  creerMutationPropositionRevueCompletion, creerMutationDecisionRevueCompletion,
  validerRecuRevueCompletion, verifierDestinationRevueCompletion,
} from "../m4/revueCompletionOutbox";
export interface DependancesRevueCompletion {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => { readonly enLigne: boolean; readonly courante: () => boolean };
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch; readonly horloge: () => Date; readonly decalageMinutesUTC: () => number;
  readonly obtenirDepot: () => Promise<DepotOutbox>; readonly genererId: () => string;
  readonly declencher: (courante: () => boolean) => Promise<unknown>;
}
export type EtatIntentionRevueCompletion =
  | { readonly genre: "en_attente" | "creation_confirmee" | "decision_confirmee"; readonly mutation: MutationOutbox }
  | { readonly genre: "aucune" | "indisponible" | "quarantaine" };
const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });
const groupe = (m: MutationOutbox) => m.chantierId === "approbations" &&
  ["approval_decision", "completion_review_proposal", "completion_review_decision"].includes(m.type);
const typed = (m: MutationOutbox) => m.type === "completion_review_proposal" || m.type === "completion_review_decision";
const bloque = (m: MutationOutbox) => typed(m) ? !validerRecuRevueCompletion(m) : m.statut !== "envoyee" && m.statut !== "echec_permanent";
const etat = (m: MutationOutbox): EtatIntentionRevueCompletion => ({ genre: bloque(m) ? "en_attente" :
  m.type === "completion_review_proposal" ? "creation_confirmee" : "decision_confirmee", mutation: m });
const enveloppe = (v: unknown) => ({ ok: true, resultat: { accepte: true, resultat: v } });
/** Lectures sans cache, créations/décisions explicites ; les champs locaux ne sont pas une autorité serveur. */
export function creerServiceRevueCompletionSources(d: DependancesRevueCompletion) {
  const verrous = new Map<string, Promise<void>>();
  async function chargerProprietaire(externe = () => true): Promise<boolean | null> {
    const capture = d.capturerSession(), reseau = d.capturerReseau(), session = capture.session;
    const courante = () => capture.courante() && reseau.courante() && externe();
    if (!session || !reseau.enLigne || !courante()) return null;
    try {
      const r = await creerChargeurApprobations({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl,
        urlBase: session.urlBase, jeton: session.jeton }).chargerDemandes();
      return courante() && r.source === "serveur" ? r.liste.proprietaire : null;
    } catch { return null; }
  }
  async function charger(intervention: unknown, demande: unknown = null, externe = () => true): Promise<ResultatSection<DossierRevueCompletion> | null> {
    const capture = d.capturerSession(), reseau = d.capturerReseau(), session = capture.session;
    const courante = () => capture.courante() && reseau.courante() && externe();
    if (!session) return null;
    if (!reseau.enLigne || !courante()) return aucune("hors_ligne");
    try {
      const args = construireArgumentsDossierRevueCompletion(intervention, demande);
      const r = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton }, OUTIL_DOSSIER_REVUE_COMPLETION, { ...args });
      if (!courante()) return aucune("lecture_remplacee");
      if (r.genre !== "reponse") return r.genre === "refuse" ? { source: "refus", verdict: r.verdict } : { source: "aucune", raison: r.verdict };
      const lu = lireDossierRevueCompletion(r.resultat, args);
      if (!courante()) return aucune("lecture_remplacee");
      if (!lu.ok) return lu.code === "reponse_illisible" || lu.code === "reponse_tronquee" ? aucune(lu.code) : { source: "refus", verdict: { code: lu.code, detail: lu.detail } };
      return { source: "serveur", valeur: lu.value, misAJourLe: d.horloge().toISOString() };
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  async function lireIntention(externe = () => true): Promise<EtatIntentionRevueCompletion> {
    const capture = d.capturerSession(), session = capture.session;
    const courante = () => capture.courante() && externe();
    if (!session || !courante()) return { genre: "indisponible" };
    try {
      const depot = await d.obtenirDepot(); if (!courante()) return { genre: "indisponible" };
      const toutes = (await depot.lister()).filter(groupe); if (!courante()) return { genre: "indisponible" };
      const attente = toutes.find(bloque);
      if (attente) return attente.proprietaire !== session.personne || (typed(attente) && !verifierDestinationRevueCompletion(attente, session)) ?
        { genre: "quarantaine" } : etat(attente);
      return { genre: "aucune" };
    } catch { return { genre: "indisponible" }; }
  }
  async function enregistrer(fabriquer: (session: NonNullable<ReturnType<DependancesRevueCompletion["capturerSession"]>["session"]>) => MutationOutbox,
    externe: () => boolean): Promise<EtatIntentionRevueCompletion> {
    const capture = d.capturerSession(), reseau = d.capturerReseau(), session = capture.session;
    const courante = () => capture.courante() && reseau.courante() && externe();
    if (!session || !reseau.enLigne || !courante()) return { genre: "indisponible" };
    const cle = session.personne;
    const operation = (verrous.get(cle) ?? Promise.resolve()).then(async (): Promise<EtatIntentionRevueCompletion> => {
      try {
        if (!courante()) return { genre: "indisponible" };
        const depot = await d.obtenirDepot(); if (!courante()) return { genre: "indisponible" };
        const toutes = (await depot.lister()).filter(groupe); if (!courante()) return { genre: "indisponible" };
        const attente = toutes.find(bloque);
        if (attente) return attente.proprietaire !== session.personne || (typed(attente) && !verifierDestinationRevueCompletion(attente, session)) ?
          { genre: "quarantaine" } : etat(attente);
        const m = fabriquer(session);
        const inseree = await depot.inserer({ ...m, proprietaire: session.personne });
        if (!courante()) return { genre: "indisponible" };
        try { await d.declencher(courante); } catch { /* L'intention déjà durable reste à relire. */ }
        if (!courante()) return { genre: "indisponible" };
        const relue = await depot.obtenir(inseree.id);
        return courante() ? etat(relue ?? inseree) : { genre: "indisponible" };
      } catch { return { genre: "indisponible" }; }
    });
    const fin = operation.then(() => undefined); verrous.set(cle, fin);
    const r = await operation; if (verrous.get(cle) === fin) verrous.delete(cle); return r;
  }
  async function proposer(brut: unknown, decision: unknown, motif: unknown, externe = () => true): Promise<EtatIntentionRevueCompletion> {
    try {
      // Copier/valider la source avant toute ouverture du dépôt et conserver l'heure de cette intention.
      const copie = lireDossierRevueCompletion(enveloppe(brut), construireArgumentsDossierRevueCompletion(
        // Le lecteur complet ferme getters/prototypes ; lire l'id sans getter grâce à son descripteur.
        typeof brut === "object" && brut !== null ? Object.getOwnPropertyDescriptor(brut, "intervention_id")?.value : null));
      if (!copie.ok || copie.value.lecture !== "courante") return { genre: "indisponible" };
      const horloge = { maintenant: d.horloge(), decalageMinutesUTC: d.decalageMinutesUTC() };
      const args = construireArgumentsPropositionRevueCompletion(copie.value.intervention_id, decision, formaterHorodatageLocal(horloge), motif, copie.value.sources);
      return enregistrer(session => creerMutationPropositionRevueCompletion(args, d.genererId, horloge, session), externe);
    } catch { return { genre: "indisponible" }; }
  }
  async function decider(brut: unknown, decision: unknown, motif: unknown, proprietaire: boolean, externe = () => true): Promise<EtatIntentionRevueCompletion> {
    if (proprietaire !== true) return { genre: "indisponible" };
    try {
      // Le service ne considère pas un booléen client comme autorité serveur ; le garde owner reste au backend.
      const b = copier(brut); if (!b || b.lecture !== "historique") return { genre: "indisponible" };
      const argsLecture = construireArgumentsDossierRevueCompletion(b.demande.arguments.intervention_id, b.demande.id);
      const lu = lireDossierRevueCompletion(enveloppe(b), argsLecture);
      if (!lu.ok || lu.value.lecture !== "historique" || lu.value.demande.statut !== "en_attente") return { genre: "indisponible" };
      const args = construireArgumentsDecisionRevueCompletion(lu.value.demande.id, decision, motif);
      const horloge = { maintenant: d.horloge(), decalageMinutesUTC: d.decalageMinutesUTC() };
      return enregistrer(session => creerMutationDecisionRevueCompletion(args, enveloppe(lu.value), argsLecture, d.genererId, horloge, session), externe);
    } catch { return { genre: "indisponible" }; }
  }
  return { charger, proposer, decider, lireIntention, chargerProprietaire };
}
function copier(v: unknown): DossierRevueCompletion | null {
  const c = copierJsonLecture(v); return c === JSON_LECTURE_INVALIDE ? null : c as unknown as DossierRevueCompletion;
}
let connectee = false, generation = 0;
export function actualiserConnectiviteRevueCompletion(v: boolean): void { if (connectee !== v) generation++; connectee = v; }
const service = creerServiceRevueCompletionSources({ capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => { const n = generation; return { enLigne: connectee, courante: () => connectee && n === generation }; },
  appelerOutil: invoquerOutil, fetchImpl: fetch, horloge: () => new Date(), decalageMinutesUTC: () => -new Date().getTimezoneOffset(),
  obtenirDepot, genererId: genererMutationId, declencher: declencherVidange });
export const chargerDossierRevueCompletion = service.charger;
export const proposerRevueCompletion = service.proposer;
export const deciderRevueCompletion = service.decider;
export const lireIntentionRevueCompletion = service.lireIntention;
export const chargerProprietaireRevueCompletion = service.chargerProprietaire;
