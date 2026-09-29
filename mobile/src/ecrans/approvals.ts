import { construireArgumentsDeciderDemande, NIVEAUX_DECIDABLES_DEPUIS_L_APP } from "../approbations/contrat";
import type {
  AccuseDecision,
  AttenteDepartement,
  AttentesDepartements,
  DecisionApprobation,
  DemandeApprobation,
  VerdictServeurApprobation,
} from "../approbations/contrat";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";

/**
 * Logique PURE de `(admin)/approvals.tsx` (PLAN T1.4-f étape 6) : ce que l'écran offre, ce qu'il met en
 * file, ce qu'il affiche. Le fichier `.tsx` ne fait que le câblage React ; tout ce qui décide est ici,
 * testé (`approvals.test.ts`).
 *
 * **Le serveur décide ; l'écran n'offre que ce que le serveur permet, et moins au moindre doute.** Il ne
 * recalcule aucune règle d'approbation (propriétaire, N5, politique du département) : il lit ce que le
 * serveur dit (`decidable`, `lecture_seule`, `proprietaire`) et le recoupe avec les indices qu'il donne
 * (niveau, arguments). Une contradiction entre les deux est de la lecture seule, jamais un bouton.
 * Un refus du serveur reste montré tel quel (`VerdictServeurApprobation`).
 */

/** `chantierId` de toutes les décisions : la file sortante trie par chantier puis par séquence ; une
 * décision n'appartient à aucun chantier, elle a son propre groupe, dans l'ordre où le propriétaire les a prises. */
export const CHANTIER_ID_APPROBATIONS = "approbations";

/** Longueur maximale de la note du propriétaire (le serveur refuse au-delà : `motif_invalide`). */
export const MOTIF_LONGUEUR_MAX = 500;

/** Pourquoi une demande est montrée sans boutons. Le `serveur` porte le verdict du serveur, tel quel. */
export type RaisonLectureSeule =
  | { readonly genre: "serveur"; readonly verdict: VerdictServeurApprobation }
  | { readonly genre: "console" }
  | { readonly genre: "non_proprietaire" }
  | { readonly genre: "arguments_absents" }
  | { readonly genre: "incoherente" };

export type OffreDemande =
  | { readonly decidable: true }
  | { readonly decidable: false; readonly raison: RaisonLectureSeule };

/**
 * Ce que l'écran offre pour une demande. Les cinq conditions se cumulent : le serveur a dit
 * `decidable` ; il ne donne aucune raison de lecture seule ; le niveau est N3 ou N4 (N5, ou l'absence de
 * niveau, se décide à la console, même si le serveur laissait entendre le contraire) ; la personne est le
 * propriétaire ; les arguments exacts sont affichés (on ne décide pas ce qu'on ne peut pas lire).
 * La première condition qui manque donne la raison affichée, dans cet ordre : le verdict du serveur
 * d'abord (c'est lui qui sait).
 */
export function evaluerOffre(demande: DemandeApprobation, proprietaire: boolean): OffreDemande {
  if (demande.lectureSeule !== null) {
    return { decidable: false, raison: { genre: "serveur", verdict: demande.lectureSeule } };
  }
  if (demande.niveau === null || !NIVEAUX_DECIDABLES_DEPUIS_L_APP.includes(demande.niveau)) {
    return { decidable: false, raison: { genre: "console" } };
  }
  if (!proprietaire) {
    return { decidable: false, raison: { genre: "non_proprietaire" } };
  }
  if (demande.arguments === null) {
    return { decidable: false, raison: { genre: "arguments_absents" } };
  }
  if (!demande.decidable) {
    return { decidable: false, raison: { genre: "incoherente" } };
  }
  return { decidable: true };
}

/**
 * Ce que l'écran dit des attentes des départements (complétion en revue avec écart critique, facture prête,
 * chantier à réviser : PLAN T1.5). Rien n'est reclassé ni interprété ici : ni « critique », ni « urgent »,
 * ce que le département a écrit est montré tel quel.
 */
export type VueAttentes =
  /** Le moteur n'en donne pas (plus ancien) : l'écran ne dit ni « aucune » ni rien d'autre, il ne sait pas. */
  | { readonly genre: "inconnues" }
  /** Le serveur dit qu'il n'y en a aucune, et que tous les départements ont pu répondre. */
  | { readonly genre: "aucune" }
  | {
      readonly genre: "presentes";
      readonly items: readonly AttenteDepartement[];
      /** Attentes que le serveur n'a pas montrées. */
      readonly reste: number;
      /** Éléments que ce client n'a pas su lire. */
      readonly illisibles: number;
      /** Départements dont les attentes n'ont pas pu être lues : leur silence n'est pas « rien à signaler ». */
      readonly departementsIllisibles: readonly string[];
    };

export function vueAttentes(attentes: AttentesDepartements | null): VueAttentes {
  if (attentes === null) {
    return { genre: "inconnues" };
  }
  if (
    attentes.items.length === 0 &&
    attentes.reste === 0 &&
    attentes.illisibles === 0 &&
    attentes.departementsIllisibles.length === 0
  ) {
    return { genre: "aucune" };
  }
  return {
    genre: "presentes",
    items: attentes.items,
    reste: attentes.reste,
    illisibles: attentes.illisibles,
    departementsIllisibles: attentes.departementsIllisibles,
  };
}

/** Une décision déjà partie en file (pas encore acceptée par le serveur) pour une demande. */
export interface DecisionEnFile {
  readonly mutationId: string;
  readonly decision: DecisionApprobation;
  readonly statut: "en_attente" | "envoi";
}

/**
 * Les décisions que la file sortante n'a pas encore livrées, par identifiant de demande. Sert à ne pas
 * offrir un second bouton pour une demande dont la décision attend le réseau : deux décisions =
 * deux clés d'idempotence, donc la seconde ne serait pas absorbée par la première. Une décision en échec
 * permanent n'y est pas (le verdict du serveur a été montré ; la demande, si elle est encore en attente,
 * revient dans la liste et peut être décidée de nouveau).
 */
export function decisionsEnFile(mutations: readonly MutationOutbox[]): ReadonlyMap<string, DecisionEnFile> {
  const enFile = new Map<string, DecisionEnFile>();
  for (const mutation of mutations) {
    if (mutation.type !== "approval_decision" || (mutation.statut !== "en_attente" && mutation.statut !== "envoi")) {
      continue;
    }
    const { demande_id: demandeId, decision } = mutation.payload;
    if (typeof demandeId !== "string" || (decision !== "approuver" && decision !== "refuser")) {
      continue;
    }
    if (!enFile.has(demandeId)) {
      enFile.set(demandeId, { mutationId: mutation.id, decision, statut: mutation.statut });
    }
  }
  return enFile;
}

/**
 * La mutation `approval_decision` d'une décision, prête à être insérée dans la file sortante : `en_attente`
 * (soumise), son id (généré sur l'appareil, avant tout réseau) sera la clé d'idempotence. Le payload est
 * EXACTEMENT les args de l'outil (`construireArgumentsDeciderDemande`) : ni personne, ni rôle, ni appareil.
 */
export function creerMutationDecision(
  demandeId: string,
  decision: DecisionApprobation,
  motif: string,
  genererId: () => string,
  horloge: HorlogeAppareil,
): MutationOutbox {
  if (demandeId.trim() === "") {
    throw new Error("identifiant de demande vide : aucune décision n'est créée");
  }
  const brouillon = creerMutation(
    {
      type: "approval_decision",
      chantierId: CHANTIER_ID_APPROBATIONS,
      payload: { ...construireArgumentsDeciderDemande(demandeId, decision, motif) },
    },
    genererId,
    horloge,
  );
  return soumettreMutation(brouillon);
}

/**
 * Relit le `resume` d'une mutation acceptée (`RapportVidange.resultatsAcceptes`, laissé `unknown` par le
 * vidangeur générique) comme un accusé de décision. Il vient de `interpreterResultatDeciderDemande` : le
 * contrôle de forme ici n'est qu'une ceinture, et `null` (rien d'affiché comme fait) si la forme diffère.
 */
export function accuseDepuisResume(resume: unknown): AccuseDecision | null {
  if (typeof resume !== "object" || resume === null) {
    return null;
  }
  const r = resume as Partial<AccuseDecision>;
  const statutConnu = r.statut === "refusee" || r.statut === "executee" || r.statut === "echec";
  const decisionConnue = r.decision === "approuver" || r.decision === "refuser";
  if (!statutConnu || !decisionConnue || typeof r.demandeId !== "string") {
    return null;
  }
  return r as AccuseDecision;
}

export interface ArgumentAffiche {
  readonly cle: string;
  readonly valeur: string;
}

/** Les arguments EXACTS de la demande, un par ligne : un texte tel quel, tout le reste en JSON. Rien n'est
 * abrégé, résumé ni reformulé (le serveur a déjà refusé de montrer ce qu'un téléphone ne saurait lire en entier). */
export function formaterArguments(args: Readonly<Record<string, unknown>>): readonly ArgumentAffiche[] {
  return Object.entries(args).map(([cle, valeur]) => ({
    cle,
    valeur: typeof valeur === "string" ? valeur : JSON.stringify(valeur),
  }));
}

function partie(n: number): string {
  return String(n).padStart(2, "0");
}

/** « Depuis » en heure locale de l'appareil, `AAAA-MM-JJ HH:MM`. `decalageMinutesUTC` est injecté (comme
 * `formaterHorodatageLocal`) ; un horodatage illisible est rendu tel quel, jamais remplacé par une date inventée. */
export function formaterDepuis(iso: string, decalageMinutesUTC: number): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) {
    return iso;
  }
  const local = new Date(instant.getTime() + decalageMinutesUTC * 60_000);
  return (
    `${local.getUTCFullYear()}-${partie(local.getUTCMonth() + 1)}-${partie(local.getUTCDate())} ` +
    `${partie(local.getUTCHours())}:${partie(local.getUTCMinutes())}`
  );
}

/** Le genre d'issue d'une décision acceptée par le serveur, pour choisir le texte à afficher. */
export type IssueAffichee =
  | { readonly genre: "refusee" }
  | { readonly genre: "executee" }
  | { readonly genre: "executee_refusee_par_l_outil"; readonly verdict: VerdictServeurApprobation | null }
  | { readonly genre: "echec_execution"; readonly detail: string };

/**
 * Ce que le propriétaire lit après sa décision. Une approbation dont l'outil a tourné mais refusé sur le
 * fond (`issue.accepte === false`) n'est PAS présentée comme faite ; une exécution en échec dit son erreur.
 */
export function issueAffichee(accuse: AccuseDecision): IssueAffichee {
  if (accuse.statut === "refusee") {
    return { genre: "refusee" };
  }
  if (accuse.statut === "echec") {
    const { erreur, details } = accuse.issue ?? { erreur: null, details: null };
    return { genre: "echec_execution", detail: [erreur, details].filter((t) => t !== null).join(" : ") };
  }
  if (accuse.issue !== null && accuse.issue.accepte === false) {
    return { genre: "executee_refusee_par_l_outil", verdict: accuse.issue.verdict };
  }
  return { genre: "executee" };
}
