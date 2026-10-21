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

/**
 * Une attente déclarée par un département (`attentes()` du moteur, PLAN T1.5) : une complétion en revue avec
 * écart de matériaux critique (M4), une facture prête à envoyer ou un chantier à réviser (M5). Ce n'est PAS
 * une demande d'approbation : elle n'a ni arguments ni décision ici, l'écran la montre pour qu'on la voie.
 */
export interface AttenteDepartement {
  readonly type: string;
  readonly id: string;
  readonly departement: string;
  readonly departementNom: string | null;
  readonly resume: string;
  /** `null` quand le département n'en donne pas : jamais deviné. */
  readonly niveau: string | null;
  readonly depuis: string;
  /** Le geste qui traite l'attente, dit par le département (`m4_resoudre_revue_completion`...). */
  readonly actionProposee: string | null;
}

export interface AttentesDepartements {
  readonly items: readonly AttenteDepartement[];
  readonly total: number;
  /** Attentes qui viennent APRÈS cette page dans l'ordre du serveur (la plus ancienne d'abord) : pas encore lues. */
  readonly reste: number;
  /** Rang, dans cet ordre, de la première attente de cette page (`attentes_decalage`) ; 0 pour un moteur plus ancien. */
  readonly decalage: number;
  /** Rang à demander pour la page suivante (`decalage_attentes`) ; `null` : rien ne suit, ou le moteur ne pagine
   * pas encore (plus ancien) : l'écran ne sait alors que compter `reste`, comme avant. */
  readonly suivant: number | null;
  /** Éléments de la réponse que ce client n'a pas su lire : comptés, jamais devinés ni cachés. */
  readonly illisibles: number;
  /** Départements dont le serveur n'a pas pu lire les attentes : leur silence n'est pas « rien à signaler ». */
  readonly departementsIllisibles: readonly string[];
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
  /** Attentes des départements ; `null` quand le moteur n'en donne pas (moteur plus ancien) : l'écran ne dit
   * alors ni « aucune » ni rien d'autre, il ne sait pas. */
  readonly attentes: AttentesDepartements | null;
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

function lireAttente(brut: unknown): AttenteDepartement | null {
  if (!estObjet(brut)) {
    return null;
  }
  const type = texteOuNull(brut.type);
  const id = texteOuNull(brut.id);
  const departement = texteOuNull(brut.departement);
  const resume = texteOuNull(brut.resume);
  const depuis = texteOuNull(brut.depuis);
  if (!type || !id || !departement || !resume || !depuis) {
    return null;
  }
  if (brut.niveau !== null && brut.niveau !== undefined && typeof brut.niveau !== "string") {
    return null;
  }
  return {
    type,
    id,
    departement,
    departementNom: texteOuNull(brut.departement_nom),
    resume,
    niveau: typeof brut.niveau === "string" ? brut.niveau : null,
    depuis,
    actionProposee: texteOuNull(brut.action_proposee),
  };
}

/** `undefined` : le moteur ne donne pas d'attentes. `null` : il en donne, mais la forme est illisible (la réponse
 * entière l'est alors : on ne dit jamais « aucune attente » sur la foi d'une réponse qu'on ne comprend pas).
 * PLAN T1.5-e : `attentes_decalage` et `attentes_suivant` disent quelle page c'est et laquelle demander ensuite. */
function lireAttentes(corps: Record<string, unknown>): AttentesDepartements | null | undefined {
  if (corps.attentes === undefined) {
    return undefined;
  }
  const total = entierPositifOuNull(corps.total_attentes);
  const reste = entierPositifOuNull(corps.attentes_reste);
  // Un moteur plus ancien ne pagine pas : ni `attentes_decalage` ni `attentes_suivant`. Présentes, elles doivent
  // être lisibles (entier ≥ 0, `null` pour « rien ne suit »), sinon la réponse entière l'est.
  const decalage = corps.attentes_decalage === undefined ? 0 : entierPositifOuNull(corps.attentes_decalage);
  const suivantDit = corps.attentes_suivant !== undefined && corps.attentes_suivant !== null;
  const suivant = suivantDit ? entierPositifOuNull(corps.attentes_suivant) : null;
  const departements = corps.attentes_illisibles;
  if (
    !Array.isArray(corps.attentes) ||
    total === null ||
    reste === null ||
    decalage === null ||
    (suivantDit && suivant === null) ||
    !Array.isArray(departements) ||
    !departements.every((d): d is string => typeof d === "string")
  ) {
    return null;
  }
  const lues = corps.attentes.map(lireAttente);
  const items = lues.filter((a): a is AttenteDepartement => a !== null);
  return { items, total, reste, decalage, suivant, illisibles: lues.length - items.length, departementsIllisibles: departements };
}

/**
 * Interprète la réponse de `m9_lister_demandes_approbation`. Un élément mal formé n'est pas deviné : il
 * est compté dans `illisibles` (demandes) ou `attentes.illisibles` (attentes des départements). Une réponse
 * dont l'enveloppe est inattendue, ou dont les totaux ne sont pas des entiers, est un verdict
 * `reponse_illisible` (jamais une liste vide, qui dirait « rien à décider »). Sans clé `attentes` (moteur plus
 * ancien), `attentes` vaut `null` ; avec une clé illisible, c'est toute la réponse qui l'est.
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
  const attentes = lireAttentes(corps);
  if (attentes === null) {
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
      attentes: attentes ?? null,
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
