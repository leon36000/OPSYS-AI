import { entierPositifOuNull, estObjet, listeDeTextes, lireListe, texteNullable, texteOuNull } from "../admin/lecteurs";

/**
 * Contrats mobiles de ce que M4 expose à l'admin pour le dispatch du jour (§9.5 M4 : « dispatch du jour, retards,
 * file de complétion » ; écran `(admin)/chantiers.tsx`, PLAN T4.20) : `m4_lister_interventions`,
 * `m4_verifier_preparation` et `m4_produire_digest`. Lecture SEULE de `departments/m04-field-ops/src/m4_field_ops/`
 * (`outils.py`, `etats.py`, `preparation.py`, `digest.py`) — jamais exécuté ici (ADR-0008) ; la forme d'une VRAIE réponse
 * du moteur est celle de `src/admin/fixtures/reponses-moteur.json` (`tests/e2e/test_admin_appareil.py`).
 *
 * **Le dispatch est par statut, pas par jour.** `m4_lister_interventions` ne rend aucune date : `fenetre_planifiee` est
 * toujours nulle (le registre ne porte aucune fenêtre, `etats.lister_interventions`). L'app ne dit donc jamais « du
 * jour » d'une intervention, et n'invente ni date ni créneau. Un appel par statut (`STATUTS_DU_DISPATCH`) : la réponse
 * de l'outil n'a pas de pagination et le socle la tronque au-delà de 6 000 caractères ; un groupe trop gros est dit trop
 * gros (`reponse_tronquee`) sans cacher les autres, et l'historique terminé ou annulé n'est jamais demandé.
 *
 * **La préparation est celle de M4, volet par volet.** Un verdict « prêt » n'est montré que si le serveur le dit ET que
 * chaque volet est `ok` (une contradiction rend la réponse illisible : jamais un « prêt » supposé) ; un volet qui manque
 * ou qu'on ne peut pas vérifier dit ce qu'il faut fournir, avec les mots de M4.
 */

export const OUTIL_LISTER_INTERVENTIONS = "m4_lister_interventions";
export const OUTIL_VERIFIER_PREPARATION = "m4_verifier_preparation";
export const OUTIL_PRODUIRE_DIGEST = "m4_produire_digest";

/**
 * Les statuts d'intervention que « Chantiers du jour » demande, dans l'ordre où l'écran les montre : ce qui se passe
 * (en route, sur place, en revue), ce qui est planifié ou reste à planifier, ce qui est reporté, et la file de
 * complétion (`completed_pending_review`). Tous sont dans `etats.ETATS` (épinglé par l'E2E). `completed_verified` et
 * `annulee` (l'historique) n'y sont pas : le digest dit ce qui s'est terminé aujourd'hui.
 */
export const STATUTS_DU_DISPATCH: readonly string[] = [
  "en_route",
  "sur_site",
  "en_revue",
  "planifiee",
  "a_planifier",
  "reportee",
  "completed_pending_review",
];

/** `preparation.py` (`STATUTS_PREPARABLES`) : avant le départ, la question « prête à planifier ? » a un sens. */
export const STATUTS_PREPARABLES: readonly string[] = ["a_planifier", "planifiee", "reportee"];
/** `preparation.py` (`VOLETS`), dans l'ordre d'affichage de M4. */
export const VOLETS_DE_PREPARATION: readonly string[] = ["soumission", "adresse", "equipe", "materiel", "meteo"];
/** `preparation.py` (`STATUT_OK`, `STATUT_MANQUE`, `STATUT_NON_VERIFIABLE`). */
export const STATUTS_DE_VOLET: readonly string[] = ["ok", "manque", "non_verifiable"];
/** `preparation.py` (`VERDICT_PRET`, `VERDICT_BLOQUE`, `VERDICT_NON_VERIFIABLE`). */
export const VERDICTS_DE_PREPARATION: readonly string[] = ["pret", "bloque", "non_verifiable"];
/** `ecarts.py` (`TYPES_DEMANDE`) : les types de la file de revue que le digest compte. */
export const TYPES_DE_DEMANDE_DE_REVUE: readonly string[] = ["ecart_metier", "anomalie_pointage"];

/** `m4_lister_interventions` : un statut, et rien d'autre (jamais une personne : le serveur tient la personne du jeton). */
export function construireArgumentsListerInterventions(statut: string): { readonly statut: string } {
  return { statut };
}

/** `m4_verifier_preparation` : le numéro de l'intervention, tel que le serveur l'a donné. */
export function construireArgumentsPreparation(interventionId: string): { readonly intervention_id: string } {
  return { intervention_id: interventionId };
}

/**
 * `m4_produire_digest` : le jour de l'appareil (`date_cible`) et l'instant de référence avec fuseau. M4 n'a pas
 * d'horloge : c'est l'appareil qui dit quel jour on est ; le serveur en tire les heures écoulées des demandes bloquées.
 */
export function construireArgumentsDigest(
  dateCible: string,
  horodatageReference: string,
): { readonly date_cible: string; readonly horodatage_reference: string } {
  return { date_cible: dateCible, horodatage_reference: horodatageReference };
}

// ---------------------------------------------------------------------------------------------------------------------
// m4_lister_interventions
// ---------------------------------------------------------------------------------------------------------------------
export interface InterventionDuDispatch {
  readonly interventionId: string;
  readonly statut: string;
  readonly leadId: string;
  /** Exactement l'une des deux : `service` (lead v2, code déclaré par l'entreprise) ou `type_travaux` (lead v1). Jamais
   * l'une déduite de l'autre. */
  readonly travaux: { readonly genre: "service" | "type_travaux"; readonly valeur: string };
  readonly devisId: string | null;
  /** La personne assignée, telle que le serveur la donne ; `null` : personne (jamais devinée). */
  readonly technicienAssigne: string | null;
  /** Toujours `null` aujourd'hui côté serveur ; un texte s'affiche tel quel s'il en vient un. */
  readonly fenetrePlanifiee: string | null;
}

export interface InterventionsLues {
  /** Le statut demandé : chaque intervention du groupe a ce statut. */
  readonly statut: string;
  readonly interventions: readonly InterventionDuDispatch[];
  /** Éléments de la réponse que ce client n'a pas su lire : comptés, jamais devinés. */
  readonly illisibles: number;
}

function lireIntervention(brut: unknown, statutDemande: string): InterventionDuDispatch | null {
  if (!estObjet(brut)) {
    return null;
  }
  const interventionId = texteOuNull(brut.intervention_id);
  const leadId = texteOuNull(brut.lead_id);
  const service = texteOuNull(brut.service);
  const typeTravaux = texteOuNull(brut.type_travaux);
  const devisId = texteNullable(brut.devis_id);
  const technicien = texteNullable(brut.technicien_assigne);
  const fenetre = texteNullable(brut.fenetre_planifiee);
  // Le serveur filtre par statut : une intervention d'un autre statut n'a rien à faire dans ce groupe. Exactement une
  // nature de travaux. Toute clé attendue absente ou mal formée : l'élément est illisible.
  if (
    interventionId === null ||
    leadId === null ||
    brut.statut !== statutDemande ||
    (service === null) === (typeTravaux === null) ||
    devisId === undefined ||
    technicien === undefined ||
    fenetre === undefined
  ) {
    return null;
  }
  const travaux = service !== null ? { genre: "service" as const, valeur: service } : { genre: "type_travaux" as const, valeur: typeTravaux as string };
  return { interventionId, statut: statutDemande, leadId, travaux, devisId, technicienAssigne: technicien, fenetrePlanifiee: fenetre };
}

/** Lit la liste des interventions d'UN statut. `null` si la valeur n'est pas une liste (illisible, jamais « aucune »). */
export function lireInterventions(brut: unknown, statutDemande: string): InterventionsLues | null {
  const lues = lireListe(brut, (element) => lireIntervention(element, statutDemande));
  return lues === null ? null : { statut: statutDemande, interventions: lues.items, illisibles: lues.illisibles };
}

// ---------------------------------------------------------------------------------------------------------------------
// m4_verifier_preparation
// ---------------------------------------------------------------------------------------------------------------------
export interface VoletDePreparation {
  readonly nom: string;
  readonly statut: string;
  /** Ce qu'il faut fournir, dit par M4 (`null` : rien à fournir, le volet est `ok`). */
  readonly manque: string | null;
  readonly detail: string | null;
}

export interface Preparation {
  readonly interventionId: string;
  readonly statutIntervention: string;
  /** Le verdict d'ensemble : `pret`, `bloque` ou `non_verifiable`. */
  readonly verdict: string;
  /** `true` SEULEMENT si tous les volets sont `ok` (le serveur le dit, et chaque volet le confirme). */
  readonly pret: boolean;
  readonly volets: readonly VoletDePreparation[];
  readonly aFournir: readonly { readonly volet: string; readonly statut: string; readonly manque: string | null }[];
}

function lireVolet(nom: string, brut: unknown): VoletDePreparation | null {
  if (!estObjet(brut)) {
    return null;
  }
  const statut = texteOuNull(brut.statut);
  const manque = texteNullable(brut.manque);
  const detail = texteNullable(brut.detail);
  return statut === null || !STATUTS_DE_VOLET.includes(statut) || manque === undefined || detail === undefined
    ? null
    : { nom, statut, manque, detail };
}

function lireAFournir(brut: unknown): Preparation["aFournir"][number] | null {
  if (!estObjet(brut)) {
    return null;
  }
  const volet = texteOuNull(brut.volet);
  const statut = texteOuNull(brut.statut);
  const manque = texteNullable(brut.manque);
  return volet === null || statut === null || manque === undefined ? null : { volet, statut, manque };
}

/**
 * Lit la préparation d'une intervention. Un volet au statut inconnu, ou un « prêt » que les volets ne confirment pas,
 * rend toute la réponse illisible : la préparation est la porte de la cédule, elle ne se lit pas à moitié.
 */
export function lirePreparation(brut: unknown): Preparation | null {
  if (!estObjet(brut) || !estObjet(brut.volets)) {
    return null;
  }
  const interventionId = texteOuNull(brut.intervention_id);
  const statutIntervention = texteOuNull(brut.statut_intervention);
  const verdict = texteOuNull(brut.statut);
  const aFournir = lireListe(brut.a_fournir, lireAFournir);
  if (
    interventionId === null ||
    statutIntervention === null ||
    verdict === null ||
    !VERDICTS_DE_PREPARATION.includes(verdict) ||
    typeof brut.pret !== "boolean" ||
    aFournir === null ||
    aFournir.illisibles > 0
  ) {
    return null;
  }
  const volets: VoletDePreparation[] = [];
  for (const [nom, valeur] of Object.entries(brut.volets)) {
    const volet = lireVolet(nom, valeur);
    if (volet === null) {
      return null;
    }
    volets.push(volet);
  }
  if (volets.length === 0) {
    return null;
  }
  const tousOk = volets.every((volet) => volet.statut === "ok");
  // « prêt » n'existe que si tout est `ok` ; l'inverse aussi : un verdict « prêt » avec un volet qui manque, ou des volets
  // tous `ok` sous un verdict qui n'est pas « prêt », sont les deux moitiés d'une contradiction.
  if (brut.pret !== (verdict === "pret") || (verdict === "pret" && (!tousOk || aFournir.items.length > 0))) {
    return null;
  }
  return { interventionId, statutIntervention, verdict, pret: brut.pret, volets, aFournir: aFournir.items };
}

// ---------------------------------------------------------------------------------------------------------------------
// m4_produire_digest
// ---------------------------------------------------------------------------------------------------------------------
export interface InterventionTerminee {
  readonly interventionId: string;
  readonly wctId: string;
  readonly dureeReelleMinutes: number;
  /** L'écart signalé au moment de la complétion (un booléen du serveur, jamais déduit). */
  readonly ecartSignale: boolean;
}

export interface InterventionBloquee {
  readonly interventionId: string;
  readonly demandeId: string;
  /** Les heures écoulées, comptées par M4 depuis l'instant de référence que l'appareil a donné. */
  readonly heuresEcoulees: number;
}

export interface DigestDuJour {
  readonly dateCible: string;
  readonly horodatageReference: string;
  readonly terminees: readonly InterventionTerminee[];
  readonly enRevue: readonly string[];
  readonly countPendingReview: number;
  /** Le compte de la file de revue par type (`ecart_metier`, `anomalie_pointage`), dans l'ordre du serveur. */
  readonly pendingParType: readonly { readonly type: string; readonly nombre: number }[];
  readonly bloquees: readonly InterventionBloquee[];
  /** Éléments des listes que ce client n'a pas su lire. */
  readonly illisibles: number;
}

function lireTerminee(brut: unknown): InterventionTerminee | null {
  if (!estObjet(brut)) {
    return null;
  }
  const interventionId = texteOuNull(brut.intervention_id);
  const wctId = texteOuNull(brut.wct_id);
  const duree = entierPositifOuNull(brut.duree_reelle_minutes);
  return interventionId === null || wctId === null || duree === null || typeof brut.ecart_signale !== "boolean"
    ? null
    : { interventionId, wctId, dureeReelleMinutes: duree, ecartSignale: brut.ecart_signale };
}

function lireBloquee(brut: unknown): InterventionBloquee | null {
  if (!estObjet(brut)) {
    return null;
  }
  const interventionId = texteOuNull(brut.intervention_id);
  const demandeId = texteOuNull(brut.demande_id);
  const heures = entierPositifOuNull(brut.heures_ecoulees);
  return interventionId === null || demandeId === null || heures === null ? null : { interventionId, demandeId, heuresEcoulees: heures };
}

export function lireDigest(brut: unknown): DigestDuJour | null {
  if (!estObjet(brut) || !estObjet(brut.pending_par_type)) {
    return null;
  }
  const dateCible = texteOuNull(brut.date_cible);
  const horodatageReference = texteOuNull(brut.horodatage_reference);
  const terminees = lireListe(brut.interventions_terminees, lireTerminee);
  const enRevue = listeDeTextes(brut.interventions_en_revue);
  const count = entierPositifOuNull(brut.count_pending_review);
  const bloquees = lireListe(brut.interventions_bloquees_en_revue, lireBloquee);
  if (dateCible === null || horodatageReference === null || terminees === null || enRevue === null || count === null || bloquees === null) {
    return null;
  }
  const pendingParType: { type: string; nombre: number }[] = [];
  for (const [type, valeur] of Object.entries(brut.pending_par_type)) {
    const nombre = entierPositifOuNull(valeur);
    if (nombre === null) {
      return null;
    }
    pendingParType.push({ type, nombre });
  }
  return {
    dateCible,
    horodatageReference,
    terminees: terminees.items,
    enRevue,
    countPendingReview: count,
    pendingParType,
    bloquees: bloquees.items,
    illisibles: terminees.illisibles + bloquees.illisibles,
  };
}
