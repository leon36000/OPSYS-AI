import type { PreuvesCompletionM4 } from "./preuvesCompletion";

/**
 * Contrat mobile de `m4_completer_intervention` (« Terminer », PLAN T1.4-f).
 *
 * Lecture SEULE de `departments/m04-field-ops/src/m4_field_ops/outils.py` (closure
 * `completer_intervention`, lignes 341-405) et de `outbox.py::completer_intervention`
 * (lignes 279-486) — jamais exécuté ici (ADR-0008), même discipline que `src/m4/pointage.ts`.
 *
 * **Portée volontairement RÉDUITE par rapport au schéma complet de l'outil.** `outils.py`
 * accepte aussi `photos`, `description_factuelle`, `consentement_marketing`, `client_satisfait`
 * — des FAITS DU CLIENT (Loi 25, T1.2-f) que « un agent ne peut JAMAIS affirmer à sa place »,
 * réservés au flux marketing (M7, DEFINITION-PRODUIT.md §9.3 : « Après le chantier, pour le
 * marketing… autorisation du client, qualité du résultat, client satisfait oui/non »). Aucun de
 * ces quatre champs n'a d'écran dédié dans R12 §5 pour cette tranche (l'ordre de livraison
 * s'arrête à `complete.tsx` -> `materials.tsx`) : `complete.tsx` ne les envoie PAS (ils restent
 * `NON_FOURNI` côté serveur, leur défaut) plutôt que d'inventer une capture de consentement
 * client bâclée. Documenté aussi dans MOBILE.md (« Ce qui n'est pas encore fait »).
 *
 * **ÉCART découvert en lisant le serveur (à documenter dans le rapport final, cadre de
 * travail) : l'accusé direct de `m4_completer_intervention` N'EST PAS le WCT complet.**
 * `outbox.completer_intervention` (étape 13) renvoie un résumé de 8 clés (`wct_id`,
 * `intervention_id`, `ligne_id`, `statut`, `hash_maillon`, `duree_reelle_minutes`,
 * `ecart_signale`, `tete_chaine`) — PAS les 12 clés du `WctRecu` complet (`lead_id`,
 * `technicien_id`, `horodatage_completion`, `fix_gps_completion`, `revue_id`,
 * `consommateurs_cibles`, `devis_id`, `type_travaux`?, en plus des 8 précédentes) que
 * `m6_declarer_materiaux_utilises` exige VERBATIM (`_WCT`, « 12 clés exactes émises par M4,
 * reproduites telles quelles », `departments/m06-material-control/.../outils.py:130`). Le WCT
 * complet n'est PAS dans le contrat fixe donné pour cette tranche. Pont retenu, en lisant le
 * serveur EXISTANT (pas une invention) : `m4_lire_outbox` (`outils.py`, déjà livré, T1.1-b#3,
 * lecture seule, autonomie T0) renvoie `[{"index", "wct"}, ...]` avec le WCT COMPLET
 * (`outbox.lire_outbox`, `maillon[CLE_WCT]`) — voir `obtenirWctComplet`/`trouverWctParId`
 * ci-dessous. Si le serveur PARALLÈLE (T1.4-f, route fichiers) finit par exposer le WCT complet
 * directement dans l'accusé de `m4_completer_intervention`, ce pont devient superflu mais reste
 * inoffensif (un appel de lecture en plus, jamais une écriture).
 */

/** Args RÉELLEMENT envoyés par cette tranche (sous-ensemble volontaire du schéma complet, voir
 * en-tête). `intervention_id`/`horodatage`/`preuves_completion` sont `required` côté serveur ;
 * `signature_requise` a un défaut serveur (`false`) mais est envoyé EXPLICITEMENT ici, jamais
 * omis — `src/ecrans/complete.ts` exige un choix explicite de l'employé avant de construire ces
 * args (fail-closed, jamais un défaut deviné côté mobile, voir sa docstring). */
export interface ArgumentsM4CompleterIntervention {
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
): ArgumentsM4CompleterIntervention {
  return {
    intervention_id: interventionId,
    horodatage,
    preuves_completion: preuvesCompletion,
    signature_requise: signatureRequise,
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
    typeof valeur.statut === "string"
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
    const accuseBrut = estObjet(resultatMetier.resultat) ? (resultatMetier.resultat as unknown) : null;
    return { accepte: true, resultat: accuseBrut as AccuseCompletionM4 | null };
  }
  return { accepte: true, resultat: null };
}

/** Args de `m4_lire_outbox` (`outils.py`, `{"depuis_index": {"type": "integer"}}`,
 * `additionalProperties: false`) — `depuis_index` omis (défaut serveur 0) : cette tranche relit
 * l'outbox complet à chaque appel plutôt que de suivre un curseur, un choix de SIMPLICITÉ (P11 le
 * signale comme un coût à surveiller si l'outbox grossit beaucoup — voir en-tête). */
export interface ArgumentsM4LireOutbox {
  readonly depuis_index?: number;
}

/** Le WCT COMPLET (`WctRecu`, `outbox.py::CLE_WCT`) — champs REPRODUITS TELS QUELS vers
 * `m6_declarer_materiaux_utilises` (`_WCT`), jamais retypés champ par champ ici : ce module ne
 * connaît QUE les deux clés dont il a besoin pour RETROUVER le bon WCT (`wct_id`,
 * `intervention_id`) — le reste voyage en `unknown` opaque, exactement comme le contrat serveur
 * le décrit (« 12 clés exactes… reproduites telles quelles »), jamais deviné ici. */
export interface WctRecuM4 {
  readonly wct_id: string;
  readonly intervention_id: string;
  readonly [cle: string]: unknown;
}

export interface EntreeOutboxM4 {
  readonly index: number;
  readonly wct: WctRecuM4;
}

export type InterpretationLireOutbox =
  | { readonly ok: true; readonly entrees: readonly EntreeOutboxM4[] }
  | { readonly ok: false; readonly verdict: VerdictServeurCompletion };

function estWctRecuM4(valeur: unknown): valeur is WctRecuM4 {
  return estObjet(valeur) && typeof valeur.wct_id === "string" && typeof valeur.intervention_id === "string";
}

function estEntreeOutboxM4(valeur: unknown): valeur is EntreeOutboxM4 {
  return estObjet(valeur) && typeof valeur.index === "number" && estWctRecuM4(valeur.wct);
}

/** `m4_lire_outbox` renvoie un TABLEAU directement (pas de couche `accepte`/`verdict` — même
 * patron que `m4_lister_interventions`, voir `src/m4/interventions.ts` en-tête) : seul
 * `outils.executer` peut refuser techniquement (ex. `depuis_index` négatif -> `ValueError`,
 * remonté en erreur technique par le socle). Lecture défensive : une entrée mal formée est
 * simplement exclue plutôt que de faire échouer toute la lecture. */
export function interpreterResultatLireOutbox(resultatBrut: unknown): InterpretationLireOutbox {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { ok: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultat = enveloppe.resultat;
  if (!Array.isArray(resultat)) {
    return { ok: true, entrees: [] };
  }
  return { ok: true, entrees: resultat.filter(estEntreeOutboxM4) };
}

/** Retrouve, dans une lecture de `m4_lire_outbox`, LE WCT complet émis par CETTE complétion
 * précise — apparié par `wct_id` (pas seulement `intervention_id`, qui pourrait un jour se
 * répéter si une intervention est un jour rouverte/reprise) — `null` si absent (ex. lecture
 * relancée avant que l'écriture n'ait été répliquée, ou `depuis_index` trop avancé). Fonction
 * pure, testable sans réseau. */
export function trouverWctParId(entrees: readonly EntreeOutboxM4[], wctId: string): WctRecuM4 | null {
  return entrees.find((e) => e.wct.wct_id === wctId)?.wct ?? null;
}
