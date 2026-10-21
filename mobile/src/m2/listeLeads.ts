import { entierOuNull, estObjet, lireEnveloppeMetier, texteOuNull, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import type { LectureEnveloppe } from "../protocole/enveloppeOutil";
import type { VerdictServeur } from "../outbox/vidangeur";

/**
 * Contrat mobile de `m2_lister_leads` (`(seller)/leads.tsx`, PLAN T4.8 ; DEFINITION-PRODUIT §9.4 « ses leads »,
 * pipeline personnel ; M2.11).
 *
 * Lecture SEULE de `departments/m02-revenue-crm/src/m2_revenue_crm/outils.py` (`lister_leads` et l'entrée
 * `Outil(nom="m2_lister_leads", ...)`), de `liste_leads.py` (la page : `_item`, `lister`) et de `segments.py`
 * (les 14 segments, les règles citées) — jamais exécuté ici (ADR-0008). Les clés suivent LITTÉRALEMENT ce que
 * le serveur rend ; `tests/e2e/test_vendeur_appareil.py` compare la forme d'une vraie réponse du moteur à la
 * fixture que ce module lit dans ses tests.
 *
 * **Le serveur décide qui voit quoi.** L'appareil du vendeur ne reçoit que SES leads (`acces.leads_visibles`) ;
 * ce module n'envoie aucun argument qui désigne une personne (jamais `owner`, `vendeur`...), et n'en lit aucun
 * pour filtrer : la portée n'est pas recalculée côté app.
 *
 * **Rien d'inventé.** Un lead dont un élément est illisible n'est pas montré à moitié : il est compté
 * (`illisibles`) et dit. Un segment « non calculable » garde son « manque X », il n'est jamais rendu comme une
 * liste vide. La page qui contredirait sa propre pagination (`reste` sans `suivant`, `suivant` qui ne progresse
 * pas) est illisible : elle ferait manquer des leads ou tourner « Voir plus » en rond.
 */

/** `statuts.STATUTS` de M2. */
export const STATUTS_LEAD: readonly string[] = [
  "nouveau",
  "qualifie",
  "converti",
  "perdu",
  "cedule",
  "chantier",
  "facture",
  "paiement",
  "avis",
];

/** `segments.SEGMENTS` de M2, dans l'ordre de DEFINITION-PRODUIT §7 M2.11. */
export const SEGMENTS_LEAD: readonly string[] = [
  "hot_lead",
  "needs_photos",
  "estimate_ready",
  "quote_sent",
  "quote_stale",
  "won_pending_schedule",
  "active_job",
  "invoice_pending",
  "past_customer",
  "high_value_customer",
  "referral_candidate",
  "complaint_risk",
  "dormant_lead",
  "seasonal_opportunity",
];

export const OUTIL_LISTER_LEADS = "m2_lister_leads";

/** Code du refus d'un filtre sur un segment que M2 ne peut pas calculer (`REJ-SEGMENT-NON-CALCULABLE`). */
export const CODE_SEGMENT_NON_CALCULABLE = "REJ-SEGMENT-NON-CALCULABLE";

export interface FiltreLeads {
  readonly statut: string | null;
  readonly segment: string | null;
}

export const FILTRE_AUCUN: FiltreLeads = { statut: null, segment: null };

/** Un segment appliqué à un lead : sa règle citée (identifiant, énoncé dans `PageLeads.regles`) et la donnée
 * qui l'a déclenché, telle que M2 la rend. */
export interface SegmentApplique {
  readonly segment: string;
  readonly regle: string;
  readonly donnee: Readonly<Record<string, unknown>>;
}

/** « non calculable, manque X » : jamais deviné, jamais absent en silence. */
export interface SegmentNonCalculable {
  readonly segment: string;
  readonly manque: string;
}

export interface ProchaineActionLead {
  readonly description: string;
  readonly echeance: string | null;
}

/** Un lead de la liste : identité, statut, travaux, ville, urgence déclarée, deux dates, prochaine action et
 * segments. Ni montant ni contact (structurellement absents côté serveur). Une valeur absente est `null` :
 * l'écran la dit absente. */
export interface LeadListe {
  readonly leadId: string;
  readonly statut: string | null;
  readonly proprietaire: string | null;
  readonly travaux: string | null;
  readonly ville: string | null;
  readonly urgenceDeclaree: boolean | null;
  readonly ingereLe: string;
  readonly derniereActivite: string | null;
  readonly prochaineAction: ProchaineActionLead | null;
  readonly segments: readonly SegmentApplique[];
  /** Segments que CE lead ne permet pas de calculer, en plus de `PageLeads.segmentsNonCalculables`. */
  readonly nonCalculables: readonly SegmentNonCalculable[];
}

export interface PageLeads {
  /** Les leads visibles qui passent les filtres, toutes pages confondues. */
  readonly total: number;
  /** Rang du premier lead de cette page. */
  readonly decalage: number;
  readonly affichees: number;
  /** Leads qui viennent APRÈS cette page. */
  readonly reste: number;
  /** Rang à demander pour la page suivante ; `null` : rien ne suit. */
  readonly suivant: number | null;
  /** Leads du filtre dont le segment demandé n'a pas pu être calculé (donnée illisible). */
  readonly indetermines: number;
  readonly filtre: FiltreLeads;
  readonly leads: readonly LeadListe[];
  /** Énoncé de chaque règle citée par les leads de la page (identifiant -> texte). */
  readonly regles: Readonly<Record<string, string>>;
  /** Ce qui manque pour calculer un segment, pour TOUS les leads (les six sans donnée, un seuil à configurer). */
  readonly segmentsNonCalculables: readonly SegmentNonCalculable[];
  /** Leads de la réponse que ce client n'a pas su lire : comptés, jamais montrés à moitié. */
  readonly illisibles: number;
}

export type InterpretationListeLeads =
  | { readonly ok: true; readonly page: PageLeads }
  | { readonly ok: false; readonly genre: "refus" | "technique" | "illisible"; readonly verdict: VerdictServeur };

/** Les arguments EXACTS de `m2_lister_leads` (`additionalProperties: false`) : l'instant de référence
 * (`horodatage`, obligatoire), les filtres et le rang. Jamais une personne. `limite` n'est pas envoyée : le
 * serveur borne la page par la taille de sa sortie. */
export function construireArgumentsListerLeads(
  horodatage: string,
  filtre: FiltreLeads,
  decalage: number,
): Record<string, unknown> {
  const args: Record<string, unknown> = { horodatage };
  if (filtre.statut !== null) {
    args.statut = filtre.statut;
  }
  if (filtre.segment !== null) {
    args.segment = filtre.segment;
  }
  if (decalage > 0) {
    args.decalage = decalage;
  }
  return args;
}

function lireSegmentApplique(brut: unknown): SegmentApplique | null {
  if (!estObjet(brut)) {
    return null;
  }
  const segment = texteOuNull(brut.segment);
  const regle = texteOuNull(brut.regle);
  if (segment === null || regle === null || !estObjet(brut.donnee)) {
    return null;
  }
  return { segment, regle, donnee: brut.donnee };
}

function lireNonCalculable(brut: unknown): SegmentNonCalculable | null {
  if (!estObjet(brut)) {
    return null;
  }
  const segment = texteOuNull(brut.segment);
  const manque = texteOuNull(brut.manque);
  return segment === null || manque === null ? null : { segment, manque };
}

/** Une liste dont CHAQUE élément est lisible, ou `null` : un élément perdu ferait croire à « aucun segment ». */
function lireListeComplete<T>(brut: unknown, lire: (element: unknown) => T | null): readonly T[] | null {
  if (!Array.isArray(brut)) {
    return null;
  }
  const lus = brut.map(lire);
  return lus.every((e): e is T => e !== null) ? lus : null;
}

function lireProchaineAction(brut: unknown): ProchaineActionLead | null | undefined {
  if (brut === null) {
    return null;
  }
  if (!estObjet(brut)) {
    return undefined;
  }
  const description = texteOuNull(brut.description);
  if (description === null) {
    return undefined;
  }
  return { description, echeance: texteOuNull(brut.echeance) };
}

function lireLead(brut: unknown): LeadListe | null {
  if (!estObjet(brut)) {
    return null;
  }
  const leadId = texteOuNull(brut.lead_id);
  const ingereLe = texteOuNull(brut.ingere_le);
  const segments = lireListeComplete(brut.segments, lireSegmentApplique);
  const nonCalculables = brut.non_calculables === undefined ? [] : lireListeComplete(brut.non_calculables, lireNonCalculable);
  const prochaineAction = lireProchaineAction(brut.prochaine_action);
  if (leadId === null || ingereLe === null || segments === null || nonCalculables === null || prochaineAction === undefined) {
    return null;
  }
  return {
    leadId,
    statut: texteOuNull(brut.statut),
    proprietaire: texteOuNull(brut.proprietaire),
    travaux: texteOuNull(brut.travaux),
    ville: texteOuNull(brut.ville),
    urgenceDeclaree: typeof brut.urgence_declaree === "boolean" ? brut.urgence_declaree : null,
    ingereLe,
    derniereActivite: texteOuNull(brut.derniere_activite),
    prochaineAction,
    segments,
    nonCalculables,
  };
}

function lireRegles(brut: unknown): Readonly<Record<string, string>> | null {
  if (!estObjet(brut)) {
    return null;
  }
  const regles: Record<string, string> = {};
  for (const [cle, valeur] of Object.entries(brut)) {
    if (typeof valeur !== "string") {
      return null;
    }
    regles[cle] = valeur;
  }
  return regles;
}

function lireFiltre(brut: unknown): FiltreLeads | null {
  if (!estObjet(brut)) {
    return null;
  }
  const { statut, segment } = brut;
  if ((statut !== null && typeof statut !== "string") || (segment !== null && typeof segment !== "string")) {
    return null;
  }
  return { statut, segment };
}

/**
 * Lit `R` (la page) d'une réponse acceptée de `m2_lister_leads`. `null` : la page est illisible en entier
 * (totaux qui ne sont pas des entiers, pagination incohérente...) — jamais une liste vide, qui dirait « aucun
 * lead ». Un lead mal formé n'est pas deviné : il est compté dans `illisibles`.
 */
export function lirePageLeads(valeur: unknown): PageLeads | null {
  if (!estObjet(valeur)) {
    return null;
  }
  const total = entierOuNull(valeur.total);
  const decalage = entierOuNull(valeur.decalage);
  const affichees = entierOuNull(valeur.affichees);
  const reste = entierOuNull(valeur.reste);
  const indetermines = entierOuNull(valeur.indetermines);
  const suivant = valeur.suivant === null ? null : entierOuNull(valeur.suivant);
  const filtre = lireFiltre(valeur.filtre);
  const regles = lireRegles(valeur.regles);
  const nonCalculables = lireListeComplete(valeur.segments_non_calculables, lireNonCalculable);
  if (
    total === null ||
    decalage === null ||
    affichees === null ||
    reste === null ||
    indetermines === null ||
    (valeur.suivant !== null && suivant === null) ||
    filtre === null ||
    regles === null ||
    nonCalculables === null ||
    !Array.isArray(valeur.leads)
  ) {
    return null;
  }
  // La pagination doit se tenir : `reste` sans `suivant` ferait manquer des leads en silence ; un `suivant` qui ne
  // dépasse pas le rang de la page ferait tourner « Voir plus » en rond ; un `suivant` sans reste n'a pas d'objet.
  if ((reste > 0) !== (suivant !== null) || (suivant !== null && suivant <= decalage)) {
    return null;
  }
  const lus = valeur.leads.map(lireLead);
  const leads = lus.filter((l): l is LeadListe => l !== null);
  return {
    total,
    decalage,
    affichees,
    reste,
    suivant,
    indetermines,
    filtre,
    leads,
    regles,
    segmentsNonCalculables: nonCalculables,
    illisibles: lus.length - leads.length,
  };
}

/** Interprète la réponse de `m2_lister_leads`. Voir `lireEnveloppeMetier` pour les trois genres d'échec. */
export function interpreterResultatListerLeads(resultatBrut: unknown): InterpretationListeLeads {
  const lecture: LectureEnveloppe = lireEnveloppeMetier(resultatBrut);
  if (!lecture.ok) {
    return lecture;
  }
  const page = lirePageLeads(lecture.valeur);
  if (page === null) {
    return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
  }
  return { ok: true, page };
}
