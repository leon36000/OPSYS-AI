import { estObjet, lireEnveloppeMetier, texteOuNull, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import type { VerdictServeur } from "../outbox/vidangeur";

/**
 * Contrats mobiles de `m2_suggerer_prochaine_action`, `m2_trouver_client_de_lead` et `m2_obtenir_client_360`
 * (`(seller)/lead/[id].tsx`, PLAN T4.8 ; DEFINITION-PRODUIT §9.4 « prochaine meilleure action », « Client 360 »).
 *
 * Lecture SEULE de `departments/m02-revenue-crm/src/m2_revenue_crm/outils.py` (`suggerer_prochaine_action`,
 * `trouver_client_de_lead`, `obtenir_client_360`), de `suggestions.py` (`suggerer`, `_suggestion`) et de
 * `clients.py` (`vue_360`) — jamais exécuté ici (ADR-0008).
 *
 * **Le serveur filtre pour le vendeur** (`acces.controler_lead`, `acces.leads_visibles`) : un lead d'un autre,
 * un lead sans propriétaire et un lead inconnu donnent le MÊME refus (`REJ-LEAD-NON-ASSIGNE`), et le Client 360
 * d'un vendeur ne porte que SES opportunités. Ce module n'ajoute aucun filtre et n'en déduit aucun.
 *
 * **La règle est citée, jamais reformulée.** La suggestion vient d'une table de règles déterministe
 * (`suggestions.py`) : `regle` est son identifiant, `suggestion` son texte fixe, `motif` la raison. L'écran les
 * montre tels quels ; aucun texte de suggestion n'est produit par l'app.
 *
 * **Rien d'inventé.** Un élément mal formé du Client 360 (opportunité, interaction) est compté (`illisibles`),
 * jamais deviné ni tu : une interaction perdue en silence ferait un historique qui a l'air complet sans l'être.
 */

export const OUTIL_SUGGERER_PROCHAINE_ACTION = "m2_suggerer_prochaine_action";
export const OUTIL_TROUVER_CLIENT_DE_LEAD = "m2_trouver_client_de_lead";
export const OUTIL_OBTENIR_CLIENT_360 = "m2_obtenir_client_360";

/** Une écriture du système (`system:m3`, `system:m4`) n'est pas l'activité d'une personne : un identifiant de
 * personne ne contient pas de « : » (`acces.py`). */
export const PREFIXE_AUTEUR_SYSTEME = "system:";

export interface SuggestionAction {
  readonly leadId: string;
  readonly statut: string;
  /** L'identifiant de la règle de `suggestions.py` qui s'est appliquée (`transmettre_m3`, `planifier_chantier`...). */
  readonly regle: string;
  readonly suggestion: string;
  readonly motif: string;
}

export interface ClientDeLead {
  readonly leadId: string;
  readonly clientId: string;
}

export interface ProchaineActionOpportunite {
  readonly description: string;
  readonly echeance: string | null;
}

/** Une opportunité (un lead) du client, telle que le vendeur a le droit de la voir. */
export interface Opportunite {
  readonly leadId: string;
  readonly statut: string | null;
  readonly ville: string | null;
  readonly typeTravaux: string | null;
  readonly service: string | null;
  readonly canal: string | null;
  readonly source: string | null;
  readonly campagne: string | null;
  readonly prochaineAction: ProchaineActionOpportunite | null;
}

export interface InteractionClient {
  readonly leadId: string;
  readonly auteur: string;
  readonly resume: string;
  readonly horodatage: string;
}

export interface Client360 {
  readonly clientId: string;
  /** Le contact tel qu'ingéré (clés libres) ; `null` : le serveur n'en donne pas. */
  readonly contact: Readonly<Record<string, unknown>> | null;
  readonly opportunites: readonly Opportunite[];
  /** Les dix dernières interactions du client, sur les opportunités visibles, la plus ancienne d'abord. */
  readonly interactionsRecentes: readonly InteractionClient[];
  /** Éléments de la réponse que ce client n'a pas su lire : comptés, jamais devinés ni cachés. */
  readonly illisibles: number;
}

export type Interpretation<T> =
  | { readonly ok: true; readonly valeur: T }
  | { readonly ok: false; readonly genre: "refus" | "technique" | "illisible"; readonly verdict: VerdictServeur };

/** Args EXACTS de `m2_suggerer_prochaine_action` : le lead et l'instant de référence de l'appareil. */
export function construireArgumentsSuggerer(leadId: string, horodatage: string): { lead_id: string; horodatage: string } {
  return { lead_id: leadId, horodatage };
}

/** Args EXACTS de `m2_trouver_client_de_lead`. */
export function construireArgumentsTrouverClient(leadId: string): { lead_id: string } {
  return { lead_id: leadId };
}

/** Args EXACTS de `m2_obtenir_client_360`. */
export function construireArgumentsClient360(clientId: string): { client_id: string } {
  return { client_id: clientId };
}

export function lireSuggestion(valeur: unknown): SuggestionAction | null {
  if (!estObjet(valeur)) {
    return null;
  }
  const leadId = texteOuNull(valeur.lead_id);
  const statut = texteOuNull(valeur.statut);
  const regle = texteOuNull(valeur.regle);
  const suggestion = texteOuNull(valeur.suggestion);
  const motif = texteOuNull(valeur.motif);
  if (leadId === null || statut === null || regle === null || suggestion === null || motif === null) {
    return null;
  }
  return { leadId, statut, regle, suggestion, motif };
}

export function lireClientDeLead(valeur: unknown): ClientDeLead | null {
  if (!estObjet(valeur)) {
    return null;
  }
  const leadId = texteOuNull(valeur.lead_id);
  const clientId = texteOuNull(valeur.client_id);
  return leadId === null || clientId === null ? null : { leadId, clientId };
}

function lireProchaineAction(brut: unknown): ProchaineActionOpportunite | null | undefined {
  if (brut === null || brut === undefined) {
    return null;
  }
  if (!estObjet(brut)) {
    return undefined;
  }
  const description = texteOuNull(brut.description);
  return description === null ? undefined : { description, echeance: texteOuNull(brut.echeance) };
}

function lireOpportunite(brut: unknown): Opportunite | null {
  if (!estObjet(brut)) {
    return null;
  }
  const leadId = texteOuNull(brut.lead_id);
  const prochaineAction = lireProchaineAction(brut.prochaine_action);
  if (leadId === null || prochaineAction === undefined) {
    return null;
  }
  return {
    leadId,
    statut: texteOuNull(brut.statut),
    ville: texteOuNull(brut.ville),
    typeTravaux: texteOuNull(brut.type_travaux),
    service: texteOuNull(brut.service),
    canal: texteOuNull(brut.canal),
    source: texteOuNull(brut.source),
    campagne: texteOuNull(brut.campagne),
    prochaineAction,
  };
}

function lireInteraction(brut: unknown): InteractionClient | null {
  if (!estObjet(brut)) {
    return null;
  }
  const leadId = texteOuNull(brut.lead_id);
  const auteur = texteOuNull(brut.auteur);
  const resume = texteOuNull(brut.resume);
  const horodatage = texteOuNull(brut.horodatage);
  if (leadId === null || auteur === null || resume === null || horodatage === null) {
    return null;
  }
  return { leadId, auteur, resume, horodatage };
}

/** `null` : la vue est illisible en entier (jamais un Client 360 vide qui dirait « rien à voir »). */
export function lireClient360(valeur: unknown): Client360 | null {
  if (!estObjet(valeur)) {
    return null;
  }
  const clientId = texteOuNull(valeur.client_id);
  if (clientId === null || !Array.isArray(valeur.opportunites) || !Array.isArray(valeur.interactions_recentes)) {
    return null;
  }
  if (valeur.contact !== null && valeur.contact !== undefined && !estObjet(valeur.contact)) {
    return null;
  }
  const opportunitesLues = valeur.opportunites.map(lireOpportunite);
  const interactionsLues = valeur.interactions_recentes.map(lireInteraction);
  const opportunites = opportunitesLues.filter((o): o is Opportunite => o !== null);
  const interactionsRecentes = interactionsLues.filter((i): i is InteractionClient => i !== null);
  return {
    clientId,
    contact: estObjet(valeur.contact) ? valeur.contact : null,
    opportunites,
    interactionsRecentes,
    illisibles:
      opportunitesLues.length - opportunites.length + (interactionsLues.length - interactionsRecentes.length),
  };
}

function interpreter<T>(resultatBrut: unknown, lire: (valeur: unknown) => T | null): Interpretation<T> {
  const lecture = lireEnveloppeMetier(resultatBrut);
  if (!lecture.ok) {
    return lecture;
  }
  const valeur = lire(lecture.valeur);
  return valeur === null ? { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE } : { ok: true, valeur };
}

export function interpreterResultatSuggestion(resultatBrut: unknown): Interpretation<SuggestionAction> {
  return interpreter(resultatBrut, lireSuggestion);
}

export function interpreterResultatClientDeLead(resultatBrut: unknown): Interpretation<ClientDeLead> {
  return interpreter(resultatBrut, lireClientDeLead);
}

export function interpreterResultatClient360(resultatBrut: unknown): Interpretation<Client360> {
  return interpreter(resultatBrut, lireClient360);
}
