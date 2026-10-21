import type { ChampsClientM4 } from "./consentementClient";
import type { PreuvesCompletionM4 } from "./preuvesCompletion";

/**
 * Contrat mobile de `m4_completer_intervention` (« Terminer », PLAN T1.4-f).
 *
 * Lecture SEULE de `departments/m04-field-ops/src/m4_field_ops/outils.py` (closure
 * `completer_intervention`, lignes 341-405) et de `outbox.py::completer_intervention`
 * (lignes 279-486) — jamais exécuté ici (ADR-0008), même discipline que `src/m4/pointage.ts`.
 *
 * **Portée volontairement RÉDUITE par rapport au schéma complet de l'outil.** `outils.py`
 * accepte aussi `photos`, `description_factuelle`, `consentement_marketing`, `client_satisfait`,
 * `consentement_demande_avis` et `consentement_version_texte` — des FAITS DU CLIENT (Loi 25,
 * T1.2-f, T1.5-d) que « un agent ne peut JAMAIS affirmer à sa place ». PLAN T1.5-d : l'écran
 * « Terminer » recueille, AUPRÈS DU CLIENT, ses deux consentements (être contacté pour un avis ;
 * l'usage de photos) et, s'il l'a dit, sa satisfaction (`src/m4/consentementClient.ts`) et les envoie
 * dans `champsClient`, SANS clé pour une case non cochée (absence = non consenti). `photos` et
 * `description_factuelle` restent non envoyés : ce ne sont pas des paroles du client. Qui a recueilli
 * le consentement et quand, l'appareil ne peut pas le dire : le serveur les pose (personne du jeton,
 * heure de réception). Documenté aussi dans MOBILE.md.
 *
 * **L'accusé de `m4_completer_intervention` n'est PAS le WCT complet, et n'a pas à l'être.**
 * `outbox.completer_intervention` (étape 13) renvoie un résumé de 8 clés (`wct_id`,
 * `intervention_id`, `ligne_id`, `statut`, `hash_maillon`, `duree_reelle_minutes`,
 * `ecart_signale`, `tete_chaine`). Il porte `wct_id`, et c'est tout ce dont le mobile a besoin
 * pour la suite : depuis PLAN T1.4-i, `m6_declarer_materiaux_utilises` prend ce `wct_id` et M6
 * relit lui-même le WCT que M4 a publié (`m4.travaux_termines`, `evenement_id = wct_id`). Le
 * mobile ne relit donc plus l'outbox de M4 (`m4_lire_outbox`) et ne garde plus de copie du WCT :
 * un fait vient de sa source de vérité, jamais de l'appareil (AGENTS.md). Seul le `wct_id` est
 * mémorisé, par chantier (`src/m4/wctIdCompletion.ts`), pour `materials.tsx`.
 */

/** Args RÉELLEMENT envoyés par cette tranche (sous-ensemble volontaire du schéma complet, voir
 * en-tête). `intervention_id`/`horodatage`/`preuves_completion` sont `required` côté serveur ;
 * `signature_requise` a un défaut serveur (`false`) mais est envoyé EXPLICITEMENT ici, jamais
 * omis — `src/ecrans/complete.ts` exige un choix explicite de l'employé avant de construire ces
 * args (fail-closed, jamais un défaut deviné côté mobile, voir sa docstring). Les champs client
 * (`ChampsClientM4`) n'y figurent que s'ils ont été recueillis. */
export interface ArgumentsM4CompleterIntervention extends ChampsClientM4 {
  readonly intervention_id: string;
  readonly horodatage: string;
  readonly preuves_completion: PreuvesCompletionM4;
  readonly signature_requise: boolean;
}

export function construireArgumentsCompleterIntervention(
  interventionId: string,
  horodatage: string,
  preuvesCompletion: PreuvesCompletionM4,
  signatureRequise: boolean,
  champsClient: ChampsClientM4 = {},
): ArgumentsM4CompleterIntervention {
  return {
    intervention_id: interventionId,
    horodatage,
    preuves_completion: preuvesCompletion,
    signature_requise: signatureRequise,
    ...champsClient,
  };
}

export interface VerdictServeurCompletion {
  readonly code: string;
  readonly detail: string;
}

/** Résumé de 8 clés (`outbox.py::completer_intervention`, étape 13) — PAS le WCT complet, voir
 * en-tête. `statut` porte `"completed_pending_review"` ou `"completed_verified"` TEL QUEL,
 * jamais retypé en union fermée ici : la mission exige que ce verdict soit affiché « tel quel »
 * (item 2), donc `complete.tsx` l'affiche sans le reformuler, y compris s'il portait une valeur
 * future non encore connue de ce module. */
export interface AccuseCompletionM4 {
  readonly wct_id: string;
  readonly intervention_id: string;
  readonly ligne_id: string;
  readonly statut: string;
  readonly hash_maillon: string;
  readonly duree_reelle_minutes: number;
  readonly ecart_signale: boolean;
  readonly tete_chaine: string | null;
}

export type InterpretationCompletion =
  | { readonly accepte: true; readonly resultat: AccuseCompletionM4 | null }
  | { readonly accepte: false; readonly verdict: VerdictServeurCompletion };

/** Garde de type pour narrower le `resume: unknown` générique de
 * `RapportVidange.resultatsAcceptes` (`src/outbox/vidangeur.ts`) une fois qu'une mutation
 * `job_completion` a été acceptée — `complete.tsx` en a besoin pour lire `wct_id`/`statut` sans
 * `as` non vérifié. */
export function estAccuseCompletionM4(valeur: unknown): valeur is AccuseCompletionM4 {
  return (
    estObjet(valeur) &&
    typeof valeur.wct_id === "string" &&
    typeof valeur.intervention_id === "string" &&
    typeof valeur.ligne_id === "string" &&
    typeof valeur.statut === "string" &&
    typeof valeur.hash_maillon === "string" &&
    typeof valeur.duree_reelle_minutes === "number" && Number.isFinite(valeur.duree_reelle_minutes) &&
    typeof valeur.ecart_signale === "boolean" &&
    (valeur.tete_chaine === null || typeof valeur.tete_chaine === "string")
  );
}

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null;
}

function texteOu(valeur: unknown, repli: string): string {
  return typeof valeur === "string" ? valeur : repli;
}

function verdictDepuisErreurTechnique(enveloppe: Record<string, unknown>): VerdictServeurCompletion {
  return { code: texteOu(enveloppe.erreur, "erreur_inconnue"), detail: texteOu(enveloppe.details, "") };
}

/**
 * Interprète la réponse BUSINESS de `m4_completer_intervention` — même patron `depuis_couple`
 * défensif que `interpreterResultatPointage` (`src/m4/pointage.ts`) : un HTTP 200 peut être un
 * REJET métier définitif (preuves incomplètes, transition illégale, durée indéterminable…),
 * affiché TEL QUEL par `complete.tsx` (mission item 2), jamais maquillé ni retenté
 * automatiquement (un rejet de `m4_completer_intervention` ne se corrige pas en renvoyant le
 * même payload).
 */
export function interpreterResultatCompleterIntervention(resultatBrut: unknown): InterpretationCompletion {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { accepte: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultatMetier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;

  if (resultatMetier?.accepte === false) {
    const v = estObjet(resultatMetier.verdict) ? resultatMetier.verdict : {};
    return { accepte: false, verdict: { code: texteOu(v.code, "REJ-INCONNU"), detail: texteOu(v.detail, "") } };
  }
  if (resultatMetier?.accepte === true) {
    const accuseBrut = resultatMetier.resultat;
    if (estAccuseCompletionM4(accuseBrut)) return { accepte: true, resultat: accuseBrut };
    return { accepte: false, verdict: { code: "accuse_invalide", detail: "Accusé de complétion incomplet ou invalide." } };
  }
  return { accepte: false, verdict: { code: "accuse_invalide", detail: "Réponse métier de complétion inconnue." } };
}
