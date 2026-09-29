/**
 * Contrats mobiles de `m4_lister_interventions`, `m4_statut_intervention` et `m4_demarrer_route`
 * (M4.7, R12 §5 étape 3 — PLAN T1.4-e).
 *
 * Lecture SEULE de `departments/m04-field-ops/src/m4_field_ops/outils.py` (closures
 * `lister_interventions`, `statut_intervention`, `demarrer_route` et les trois entrées `Outil`
 * correspondantes) et de `etats.py` (`ETATS`, `TRANSITIONS_AUTORISEES`) — jamais exécuté ici
 * (ADR-0008, le bac à sable ne construit/teste que `core/`, pas les départements Python ; même
 * discipline que `src/m4/pointage.ts`).
 *
 * Enveloppe HTTP : confirmée en lisant `src/opsys/outils.py` (`executer`, `depuis_couple`) et
 * `departments/m04-field-ops/tests/test_outils_agent.py` (assertions directes sur la forme). Un
 * appel réussi de `/tools/invoke` renvoie `{"ok": true, "result": X}` où `X` est TOUJOURS
 * `{"ok": true, "resultat": Y, "rejoue"?: bool}` (`Capacites._appeler_idempotent`/
 * `opsys.outils.executer` produisent la même forme, `rejoue` en plus pour un appel idempotent).
 * `Y` dépend de l'outil :
 *  - `m4_lister_interventions` : `Y` = tableau `InterventionM4[]` directement (pas de couche
 *    accepte/verdict : `lister_interventions` ne peut refuser qu'au niveau TECHNIQUE de
 *    `outils.executer`, ex. `statut` hors énuméré -> `{"ok": false, "erreur": "refus_metier", ...}`) ;
 *  - `m4_statut_intervention` : `Y` = `{intervention_id, statut}` directement, `statut` pouvant
 *    être `null` pour un identifiant inconnu (`etats.statut_courant` renvoie `None`) — CE N'EST
 *    PAS une erreur technique, l'outil répond `ok:true` quand même ;
 *  - `m4_demarrer_route` : `Y` = `depuis_couple(etats.transitionner(...))`, donc
 *    `{"accepte": true, "resultat": AccuseTransitionM4} | {"accepte": false, "verdict": VerdictServeurM4}`
 *    — même patron que `m4_pointer` (`src/m4/pointage.ts`, `interpreterResultatPointage`).
 *
 * `VerdictServeurM4`/les petits utilitaires de lecture défensive (`estObjet`/`texteOu`) sont
 * délibérément RÉÉCRITS ici plutôt qu'importés de `src/m4/pointage.ts` : ce dernier est déjà
 * testé et utilisé en production par `punch.tsx` (T1.4-d) — le risque de régression d'un
 * refactor partagé dépasse le coût de dupliquer une dizaine de lignes (AGENTS.md : économie de
 * tokens, mais jamais au prix de casser un écran qui fonctionne déjà).
 */

/** `etats.py`, `ETATS` — catalogue fermé, jamais une valeur inventée côté mobile. */
export type StatutInterventionM4 =
  | "planifiee"
  | "en_route"
  | "sur_site"
  | "en_revue"
  | "reportee"
  | "completed_pending_review"
  | "completed_verified"
  | "annulee";

export const ETATS_INTERVENTION_M4: readonly StatutInterventionM4[] = [
  "planifiee",
  "en_route",
  "sur_site",
  "en_revue",
  "reportee",
  "completed_pending_review",
  "completed_verified",
  "annulee",
];

/** `etats.py`, `ETATS_TERMINAUX` — aucune transition ni pointage n'est légal depuis un de ces
 * statuts (`transitionner`, étape 4). */
export const ETATS_TERMINAUX_M4: readonly StatutInterventionM4[] = [
  "completed_pending_review",
  "completed_verified",
  "annulee",
];

/** `m4_lister_interventions` : forme exacte d'un élément (`etats.lister_interventions`) —
 * jamais de donnée de contact (nom/téléphone/courriel), structurellement absente côté serveur.
 *
 * La nature des travaux suit la version du lead dont l'intervention vient (PLAN T0.13-b) : EXACTEMENT
 * l'une des deux clés est présente, jamais les deux, et le mobile n'en déduit jamais l'une de l'autre.
 * `type_travaux` : lead v1 (contrat gelé). `service` : lead v2 (code d'un service déclaré par l'entreprise,
 * taxonomie du socle). */
export interface InterventionM4 {
  readonly intervention_id: string;
  readonly statut: StatutInterventionM4;
  readonly lead_id: string;
  readonly type_travaux?: string;
  readonly service?: string;
  readonly devis_id: string | null;
}

export interface VerdictServeurM4 {
  readonly code: string;
  readonly detail: string;
}

/** `etats.transitionner`, accusé de succès (étape 9). */
export interface AccuseTransitionM4 {
  readonly intervention_id: string;
  readonly ligne_id: string;
  readonly statut: StatutInterventionM4;
  readonly statut_precedent: StatutInterventionM4;
  readonly empreinte_maillon: string;
  readonly tete_chaine: string | null;
  readonly horodatage: string;
}

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null;
}

function texteOu(valeur: unknown, repli: string): string {
  return typeof valeur === "string" ? valeur : repli;
}

/** Erreur TECHNIQUE de `outils.executer` (`{"ok": false, "erreur": ..., "details": ...}`) —
 * distincte d'un rejet MÉTIER (`accepte: false`), voir la docstring d'en-tête. Les deux sont
 * normalisées vers `VerdictServeurM4` pour que l'écran n'ait qu'une seule forme à afficher. */
function verdictDepuisErreurTechnique(enveloppe: Record<string, unknown>): VerdictServeurM4 {
  return {
    code: texteOu(enveloppe.erreur, "erreur_inconnue"),
    detail: Array.isArray(enveloppe.details)
      ? enveloppe.details.map((d) => texteOu(d, "")).join("; ")
      : texteOu(enveloppe.details, ""),
  };
}

export type ResultatListerInterventions =
  | { readonly ok: true; readonly interventions: readonly InterventionM4[] }
  | { readonly ok: false; readonly verdict: VerdictServeurM4 };

/** Lecture défensive (même esprit que `interpreterResultatPointage`) : une forme non reconnue
 * (ex. `resultat` n'est pas un tableau) est traitée comme une liste VIDE plutôt qu'un blocage —
 * `today.tsx` retombe alors sur son cache local (R12 §4), jamais un écran cassé. */
export function interpreterResultatListerInterventions(resultatBrut: unknown): ResultatListerInterventions {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { ok: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultat = enveloppe.resultat;
  if (!Array.isArray(resultat)) {
    return { ok: true, interventions: [] };
  }
  return { ok: true, interventions: resultat.filter(estInterventionM4) };
}

/** Garde de type exportée pour être réutilisée par `src/today/cache.ts` (validation du cache
 * relu depuis le stockage local, qui peut être corrompu ou d'un ancien schéma). */
export function estInterventionM4(valeur: unknown): valeur is InterventionM4 {
  return (
    estObjet(valeur) &&
    typeof valeur.intervention_id === "string" &&
    typeof valeur.statut === "string" &&
    typeof valeur.lead_id === "string" &&
    // Exactement une nature de travaux : `type_travaux` (lead v1) OU `service` (lead v2). Les deux, ou
    // aucune, ne sont pas une intervention lisible (jamais l'une choisie ou déduite à la place de l'autre).
    (typeof valeur.type_travaux === "string") !== (typeof valeur.service === "string") &&
    (typeof valeur.devis_id === "string" || valeur.devis_id === null)
  );
}

export type ResultatStatutIntervention =
  | { readonly ok: true; readonly intervention_id: string; readonly statut: StatutInterventionM4 | null }
  | { readonly ok: false; readonly verdict: VerdictServeurM4 };

/** `m4_statut_intervention` : `statut: null` (intervention inconnue) N'EST PAS une erreur — le
 * distinguer d'un échec technique est la seule raison d'être de cette fonction plutôt qu'une
 * lecture directe de `enveloppe.resultat`. */
export function interpreterResultatStatutIntervention(resultatBrut: unknown): ResultatStatutIntervention {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { ok: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultat = estObjet(enveloppe.resultat) ? enveloppe.resultat : {};
  const interventionId = texteOu(resultat.intervention_id, "");
  const statut = typeof resultat.statut === "string" ? (resultat.statut as StatutInterventionM4) : null;
  return { ok: true, intervention_id: interventionId, statut };
}

export type InterpretationDemarrerRoute =
  | { readonly accepte: true; readonly resultat: AccuseTransitionM4 | null }
  | { readonly accepte: false; readonly verdict: VerdictServeurM4 };

/** `m4_demarrer_route` : même patron `depuis_couple` que `m4_pointer`
 * (`interpreterResultatPointage`, `src/m4/pointage.ts`) — un HTTP 200 peut être un REJET métier
 * définitif (ex. assignation déjà prise, transition illégale). Sans cette lecture, un rejet
 * s'afficherait comme un succès silencieux (R12 §4). */
export function interpreterResultatDemarrerRoute(resultatBrut: unknown): InterpretationDemarrerRoute {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { accepte: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultatMetier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;

  if (resultatMetier?.accepte === false) {
    const verdictBrut = estObjet(resultatMetier.verdict) ? resultatMetier.verdict : {};
    return {
      accepte: false,
      verdict: { code: texteOu(verdictBrut.code, "REJ-INCONNU"), detail: texteOu(verdictBrut.detail, "") },
    };
  }
  if (resultatMetier?.accepte === true) {
    const accuseBrut = estObjet(resultatMetier.resultat) ? (resultatMetier.resultat as unknown) : null;
    return { accepte: true, resultat: accuseBrut as AccuseTransitionM4 | null };
  }
  return { accepte: true, resultat: null };
}

/** Args EXACTS de `m4_demarrer_route` (`outils.py`, propriétés de l'`Outil` : `intervention_id`,
 * `technicien_id`, `horodatage`, tous requis, `additionalProperties: false`). Fonction pure,
 * même discipline que `construireArgumentsPointer` (`src/m4/pointage.ts`). */
export interface ArgumentsM4DemarrerRoute {
  readonly intervention_id: string;
  readonly technicien_id: string;
  readonly horodatage: string;
}

export function construireArgumentsDemarrerRoute(
  interventionId: string,
  technicienId: string,
  horodatage: string,
): ArgumentsM4DemarrerRoute {
  return { intervention_id: interventionId, technicien_id: technicienId, horodatage };
}
