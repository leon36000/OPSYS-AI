/**
 * Contrats mobiles de `m9_lister_demandes_approbation` et `m9_decider_demande_approbation` (l'écran
 * `(admin)/approvals`, PLAN T1.4-f étape 6 ; DEFINITION-PRODUIT §9.2 : « le propriétaire approuve
 * tout depuis le téléphone »).
 *
 * Lecture SEULE de `src/opsys/approbations_appareil.py` (la logique) et de
 * `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils.py` (les deux outils,
 * qui rendent `depuis_couple`) — jamais exécuté ici (ADR-0008), même discipline que `src/m4/pointage.ts`.
 *
 * Enveloppe : un appel réussi de `/tools/invoke` rend `{ok: true, result: X}` où `X` est
 * `{ok: true, resultat: Y, rejoue?: bool}`, `Y` étant `{accepte: true, resultat: R}` ou
 * `{accepte: false, verdict: {code, detail, ...}}` ; ou `X = {ok: false, erreur, details}` pour un refus
 * technique (`arguments_invalides`, `mutation_conflit`...).
 *
 * **Le serveur décide, l'écran n'offre que ce que le serveur permet.** Aucune règle d'approbation n'est
 * recalculée ici : ni qui est le propriétaire, ni ce qui est N5, ni quel département autorise quoi. Une
 * demande n'est offerte à la décision que si le serveur l'a marquée `decidable` ET que les indices
 * qu'il donne s'accordent (niveau N3 ou N4, arguments présents, aucune raison de lecture seule) : au
 * moindre doute, lecture seule (fail-closed). Un verdict du serveur est montré tel quel, jamais retraduit.
 *
 * **Rien d'inventé.** Une réponse mal formée n'est jamais lue comme un succès : pour la liste, c'est un
 * verdict `reponse_illisible` ; pour une décision, c'est un rejet (`accepte: false`) qui dit de
 * revérifier la liste (le serveur a peut-être appliqué la décision : la file sortante ne la rejouera pas).
 */

export interface VerdictServeurApprobation {
  readonly code: string;
  readonly detail: string;
}

export type DecisionApprobation = "approuver" | "refuser";

/** Niveaux qu'un appareil peut décider (ADR-0009 §4) ; N5 ne se décide jamais depuis l'app. */
export const NIVEAUX_DECIDABLES_DEPUIS_L_APP: readonly string[] = ["N3", "N4"];

/** Une demande d'approbation en attente, telle que le serveur la montre à cette personne. */
export interface DemandeApprobation {
  readonly id: string;
  readonly departement: string;
  readonly departementNom: string | null;
  readonly outil: string;
  readonly descriptionOutil: string | null;
  /** `null` pour une ancienne demande sans niveau : jamais deviné (le serveur la lit N5). */
  readonly niveau: string | null;
  readonly depuis: string;
  readonly motifDemande: string | null;
  /** `null` : la personne n'a pas le droit de les voir, ou ils sont trop gros pour un téléphone. */
  readonly arguments: Readonly<Record<string, unknown>> | null;
  readonly decidable: boolean;
  /** Pourquoi la demande n'est pas décidable ici, dit par le serveur ; `null` si elle l'est. */
  readonly lectureSeule: VerdictServeurApprobation | null;
}

export interface ListeApprobations {
  readonly demandes: readonly DemandeApprobation[];
  readonly totalEnAttente: number;
  readonly affichees: number;
  /** Demandes en attente que le serveur n'a pas montrées (limite, taille de la réponse). */
  readonly reste: number;
  /** `true` si la personne authentifiée est le propriétaire : seule à pouvoir décider depuis l'app. */
  readonly proprietaire: boolean;
  /** Éléments de la réponse que ce client n'a pas su lire : comptés, jamais devinés ni cachés. */
  readonly illisibles: number;
}

export type InterpretationListeApprobations =
  | { readonly ok: true; readonly liste: ListeApprobations }
  | { readonly ok: false; readonly verdict: VerdictServeurApprobation };

export type StatutDecision = "refusee" | "executee" | "echec";

/** Ce que l'outil approuvé a rendu, en petit (`approbations_appareil._issue`). */
export interface IssueDecision {
  readonly ok: boolean;
  /** Présent quand l'outil rend un verdict métier ; `false` : il a tourné mais refusé sur le fond. */
  readonly accepte: boolean | null;
  readonly verdict: VerdictServeurApprobation | null;
  readonly erreur: string | null;
  readonly details: string | null;
}

/** L'accusé d'une décision enregistrée par le serveur. */
export interface AccuseDecision {
  readonly demandeId: string;
  readonly decision: DecisionApprobation;
  readonly statut: StatutDecision;
  readonly outil: string;
  readonly departement: string;
  readonly niveau: string | null;
  readonly decidePar: string;
  readonly role: string;
  readonly decideLe: string | null;
  readonly issue: IssueDecision | null;
}

export type InterpretationDecision =
  | { readonly accepte: true; readonly resultat: AccuseDecision }
  | { readonly accepte: false; readonly verdict: VerdictServeurApprobation };

/** Args EXACTS de `m9_decider_demande_approbation` : rien d'autre, surtout pas une personne ni un rôle
 * (le serveur les tient du jeton d'appareil, et refuse un paramètre inconnu). */
export interface ArgumentsDeciderDemandeApprobation {
  readonly demande_id: string;
  readonly decision: DecisionApprobation;
  readonly motif?: string;
}

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null && !Array.isArray(valeur);
}

function texteOu(valeur: unknown, repli: string): string {
  return typeof valeur === "string" ? valeur : repli;
}

function texteOuNull(valeur: unknown): string | null {
  return typeof valeur === "string" && valeur.trim() !== "" ? valeur : null;
}

function entierPositifOuNull(valeur: unknown): number | null {
  return typeof valeur === "number" && Number.isInteger(valeur) && valeur >= 0 ? valeur : null;
}

/** `details` d'un refus technique : un texte, ou une liste (`arguments_invalides`) à mettre bout à bout. */
function detailsEnTexte(details: unknown): string {
  if (typeof details === "string") {
    return details;
  }
  if (Array.isArray(details)) {
    return details.filter((d): d is string => typeof d === "string").join(" ; ");
  }
  return "";
}

function verdictDepuisErreurTechnique(enveloppe: Record<string, unknown>): VerdictServeurApprobation {
  return { code: texteOu(enveloppe.erreur, "erreur_inconnue"), detail: detailsEnTexte(enveloppe.details) };
}

/** Le verdict `{code, detail}` d'un `Y = {accepte: false, verdict}` ; les champs en plus (`statut`,
 * `decide_par`...) restent au serveur, l'écran n'affiche que le code et le détail, tels quels. */
function verdictDepuis(valeur: unknown, codeRepli: string): VerdictServeurApprobation {
  const v = estObjet(valeur) ? valeur : {};
  return { code: texteOu(v.code, codeRepli), detail: texteOu(v.detail, "") };
}

const VERDICT_REPONSE_INATTENDUE: VerdictServeurApprobation = {
  code: "reponse_illisible",
  detail: "Réponse du serveur illisible : rien n'est affiché de ce que l'app ne comprend pas.",
};

function lireDemande(brut: unknown): DemandeApprobation | null {
  if (!estObjet(brut)) {
    return null;
  }
  const id = texteOuNull(brut.id);
  const outil = texteOuNull(brut.outil);
  const departement = texteOuNull(brut.departement);
  const depuis = texteOuNull(brut.depuis);
  if (!id || !outil || !departement || !depuis || typeof brut.decidable !== "boolean") {
    return null;
  }
  const args = brut.arguments === null ? null : estObjet(brut.arguments) ? brut.arguments : undefined;
  const lectureSeule = brut.lecture_seule === null ? null : estObjet(brut.lecture_seule) ? verdictDepuis(brut.lecture_seule, "lecture_seule") : undefined;
  if (args === undefined || lectureSeule === undefined) {
    return null;
  }
  if (brut.niveau !== null && typeof brut.niveau !== "string") {
    return null;
  }
  return {
    id,
    departement,
    departementNom: texteOuNull(brut.departement_nom),
    outil,
    descriptionOutil: texteOuNull(brut.description_outil),
    niveau: brut.niveau,
    depuis,
    motifDemande: texteOuNull(brut.motif_demande),
    arguments: args,
    decidable: brut.decidable,
    lectureSeule,
  };
}

/**
 * Interprète la réponse de `m9_lister_demandes_approbation`. Un élément mal formé n'est pas deviné : il
 * est compté dans `illisibles`. Une réponse dont l'enveloppe est inattendue, ou dont les totaux ne sont
 * pas des entiers, est un verdict `reponse_illisible` (jamais une liste vide, qui dirait « rien à
 * décider »).
 */
export function interpreterResultatListerDemandes(resultatBrut: unknown): InterpretationListeApprobations {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { ok: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const metier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;
  if (metier?.accepte === false) {
    return { ok: false, verdict: verdictDepuis(metier.verdict, "refus_inconnu") };
  }
  const corps = metier?.accepte === true && estObjet(metier.resultat) ? metier.resultat : undefined;
  if (!corps || !Array.isArray(corps.demandes) || typeof corps.proprietaire !== "boolean") {
    return { ok: false, verdict: VERDICT_REPONSE_INATTENDUE };
  }
  const total = entierPositifOuNull(corps.total_en_attente);
  const affichees = entierPositifOuNull(corps.affichees);
  const reste = entierPositifOuNull(corps.reste);
  if (total === null || affichees === null || reste === null) {
    return { ok: false, verdict: VERDICT_REPONSE_INATTENDUE };
  }
  const lues = corps.demandes.map(lireDemande);
  const demandes = lues.filter((d): d is DemandeApprobation => d !== null);
  return {
    ok: true,
    liste: {
      demandes,
      totalEnAttente: total,
      affichees,
      reste,
      proprietaire: corps.proprietaire,
      illisibles: lues.length - demandes.length,
    },
  };
}

function lireIssue(brut: unknown): IssueDecision | null {
  if (!estObjet(brut) || typeof brut.ok !== "boolean") {
    return null;
  }
  const verdict = estObjet(brut.verdict) ? verdictDepuis(brut.verdict, "verdict_inconnu") : null;
  return {
    ok: brut.ok,
    accepte: typeof brut.accepte === "boolean" ? brut.accepte : null,
    verdict,
    erreur: texteOuNull(brut.erreur),
    details: texteOuNull(brut.details),
  };
}

const STATUTS_DECISION: readonly StatutDecision[] = ["refusee", "executee", "echec"];

function estStatutDecision(valeur: unknown): valeur is StatutDecision {
  return typeof valeur === "string" && (STATUTS_DECISION as readonly string[]).includes(valeur);
}

const VERDICT_DECISION_ILLISIBLE: VerdictServeurApprobation = {
  code: "reponse_illisible",
  detail:
    "La réponse du serveur est illisible : la décision a peut-être été appliquée. Rouvrez la liste des demandes pour le vérifier ; l'app ne la renverra pas.",
};

/**
 * Interprète la réponse de `m9_decider_demande_approbation`. Un accusé mal formé (statut inconnu,
 * décision absente) n'est JAMAIS un succès : c'est un rejet dont le détail dit de revérifier la liste.
 * Un rejet du serveur (`deja_decidee`, `n5_a_la_console`, `reserve_au_proprietaire`...) passe tel quel.
 */
export function interpreterResultatDeciderDemande(resultatBrut: unknown): InterpretationDecision {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { accepte: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const metier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;
  if (metier?.accepte === false) {
    return { accepte: false, verdict: verdictDepuis(metier.verdict, "refus_inconnu") };
  }
  const accuse = metier?.accepte === true && estObjet(metier.resultat) ? metier.resultat : undefined;
  if (
    !accuse ||
    !estStatutDecision(accuse.statut) ||
    (accuse.decision !== "approuver" && accuse.decision !== "refuser") ||
    !texteOuNull(accuse.demande_id)
  ) {
    return { accepte: false, verdict: VERDICT_DECISION_ILLISIBLE };
  }
  return {
    accepte: true,
    resultat: {
      demandeId: accuse.demande_id as string,
      decision: accuse.decision,
      statut: accuse.statut,
      outil: texteOu(accuse.outil, ""),
      departement: texteOu(accuse.departement, ""),
      niveau: texteOuNull(accuse.niveau),
      decidePar: texteOu(accuse.decide_par, ""),
      role: texteOu(accuse.role, ""),
      decideLe: texteOuNull(accuse.decide_le),
      issue: lireIssue(accuse.issue),
    },
  };
}

/**
 * Args de `m9_decider_demande_approbation`. `motif` n'est envoyé que s'il n'est pas vide une fois épuré
 * (jamais une chaîne vide, jamais un défaut deviné). Aucune personne, aucun rôle, aucun appareil : ils ne
 * voyagent pas dans les arguments (`_meta` du jeton d'appareil, côté serveur).
 */
export function construireArgumentsDeciderDemande(
  demandeId: string,
  decision: DecisionApprobation,
  motif: string,
): ArgumentsDeciderDemandeApprobation {
  const note = motif.trim();
  return note === ""
    ? { demande_id: demandeId, decision }
    : { demande_id: demandeId, decision, motif: note };
}
