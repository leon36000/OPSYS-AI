import { OUTIL_CLASSEMENT_VARIANCE, argumentsRpcClassementVariance, interpreterClassementGenerique, validerRecuClassementVariance } from "../m6/classementVariance";
import { OUTIL_MATERIAUX_AVEC_PREUVES, argumentsRpcMateriauxAvecPreuves, interpreterMateriauxAvecPreuves, validerRecuMateriauxAvecPreuves } from "../m6/materiauxAvecPreuves";
import { interpreterResultatCompleterIntervention } from "../m4/completion";
import { interpreterResultatDefinirConsentementGps } from "../m4/consentementGps";
import { interpreterResultatDemarrerRoute } from "../m4/interventions";
import { interpreterResultatPointage } from "../m4/pointage";
import { interpreterResultatDeciderDemande } from "../approbations/contrat";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import { interpreterResultatDeclarerMateriauxUtilises, validerRecuDeclarerMateriauxUtilises } from "../m6/materiaux";
import { interpreterResultatDeposerFichier, validerRecuDeposerFichier } from "../fichiers/protocole";
import { interpreterResultatEnregistrerInteraction } from "../m2/interaction";
import { construireArgumentsDecisionMarketing, interpreterDecisionMarketing } from "../m7/decisionOutbox";
import { construireArgumentsArbitrageMemoire, interpreterArbitrageMemoire } from "../m10/arbitrageOutbox";
import { OUTIL_PRISE_RAPPEL_M1, argumentsRpcPriseRappelM1, interpreterPriseRappelM1, validerRecuPriseRappelM1 } from "../m1/rappelsAppareil";
import type { DescripteurTypeMutation, InterpretationResultatMetier } from "./vidangeur";
import type { MutationOutbox, TypeMutation } from "./types";

/**
 * Adapte `interpreterResultatPointage` (src/m4/pointage.ts, vocabulaire M4 — `accuse`) à la
 * forme générique qu'attend `DescripteurTypeMutation.interpreterResultat` (src/outbox/vidangeur.ts,
 * vocabulaire neutre — `resume`) : `vidangeur.ts` ne connaît rien de M4, et `pointage.ts` ne
 * connaît rien de la file sortante — cette fonction est le SEUL endroit qui relie les deux
 * vocabulaires, pour qu'aucun des deux modules n'ait à emprunter le mot de l'autre.
 */
function versInterpretationGenerique(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatPointage(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.accuse };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle que `versInterpretationGenerique` ci-dessus, pour `m4_demarrer_route`
 * (`src/m4/interventions.ts`, PLAN T1.4-e) — `job/[id]/index.tsx`, bouton « En route ». */
function versInterpretationGeneriqueDemarrerRoute(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatDemarrerRoute(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.resultat };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle que `versInterpretationGenerique` ci-dessus, pour `m4_deposer_fichier`
 * (`src/fichiers/protocole.ts`, PLAN T1.4-f) — un bloc par mutation `fichier_bloc`. */
function versInterpretationGeneriqueDeposerFichier(resultatBrut: unknown, mutation?: MutationOutbox): InterpretationResultatMetier {
  const interpretation = interpreterResultatDeposerFichier(resultatBrut, mutation);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.resultat };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle, pour `m4_completer_intervention` (`src/m4/completion.ts`, PLAN T1.4-f) —
 * `complete.tsx`, « Terminer ». `resume` porte l'accusé (8 clés, PAS le WCT complet — voir
 * `completion.ts` en-tête) : `complete.tsx` lit `RapportVidange.resultatsAcceptes` pour
 * retrouver ce `resume` et mémoriser son `wct_id` avant `materials.tsx`. */
function versInterpretationGeneriqueCompletion(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatCompleterIntervention(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.resultat };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle, pour `m6_declarer_materiaux_utilises` (`src/m6/materiaux.ts`, PLAN T1.4-f) —
 * `materials.tsx`, M6.10. */
function versInterpretationGeneriqueMateriaux(resultatBrut: unknown, mutation?: MutationOutbox): InterpretationResultatMetier {
  const interpretation = interpreterResultatDeclarerMateriauxUtilises(resultatBrut, mutation);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.resultat };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle, pour `m4_definir_consentement_gps` (`src/m4/consentementGps.ts`, PLAN T1.4-k) —
 * `consent.tsx`. `resume` porte l'accusé (`actif` : l'état APRÈS l'appel). */
function versInterpretationGeneriqueConsentementGps(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatDefinirConsentementGps(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.accuse };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle, pour `m9_decider_demande_approbation` (`src/approbations/contrat.ts`, PLAN T1.4-f étape 6) —
 * `(admin)/approvals.tsx`. Un accusé illisible ou une panne passagère ne prouve pas l'absence d'un
 * effet antérieur : conserver l'intention et sa clé. Les refus métier certains restent inchangés.
 * `resume` porte l'accusé de la décision (`AccuseDecision`). */
function versInterpretationGeneriqueDecisionApprobation(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatDeciderDemande(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.resultat };
  }
  if (interpretation.verdict.code === "reponse_illisible" || interpretation.verdict.code === "reponse_tronquee" ||
    ERREURS_PASSAGERES.includes(interpretation.verdict.code)) {
    return { accepte: false, verdict: { code: "accuse_invalide", detail: interpretation.verdict.code === "reponse_illisible"
      ? "La confirmation de cette décision est inconnue : l'intention reste en file avec sa clé d'origine."
      : interpretation.verdict.detail } };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/** Même rôle, pour `m2_enregistrer_interaction` (`src/m2/interaction.ts`, PLAN T4.8) — `(seller)/lead/[id].tsx`,
 * la note du vendeur. Un accusé illisible n'est jamais un succès : c'est un rejet qui dit de vérifier
 * l'historique. `resume` porte l'accusé (`AccuseNote`). */
function versInterpretationGeneriqueNote(resultatBrut: unknown): InterpretationResultatMetier {
  const interpretation = interpreterResultatEnregistrerInteraction(resultatBrut);
  if (interpretation.accepte) {
    return { accepte: true, resume: interpretation.resultat };
  }
  return { accepte: false, verdict: interpretation.verdict };
}

/**
 * Association type de mutation -> outil réel (`/tools/invoke`, `tool`) + interprète de sa
 * réponse business. `punch_in`/`punch_out` : T1.4-d, R12 §5 étape 2 — voir
 * `app/(employee)/punch.tsx` pour le choix punch_in = arrivée/fin de pause, punch_out =
 * départ/début de pause (`src/ecrans/punch.ts`), réutilisé TEL QUEL par `job/[id]/index.tsx`
 * (T1.4-e, `src/ecrans/job.ts`) pour « Arrivé »/« Pause », bornés à CE chantier. `job_status_change`
 * : T1.4-e, `job/[id]/index.tsx`, bouton « En route » (`m4_demarrer_route`) — SEULE direction de
 * ce type aujourd'hui (voir `src/ecrans/job.ts`, en-tête) ; une tranche future qui ajouterait
 * d'autres transitions de statut (report, annulation) devra soit ajouter un type de mutation
 * dédié par transition, soit faire porter l'outil par le PAYLOAD plutôt que par le descripteur —
 * non fait ici, hors périmètre.
 *
 * `photo_upload`/`signature_capture` (T1.4-e, `src/photos/`, `src/signature/`) : TOUJOURS SANS
 * DESCRIPTEUR — ces mutations restent `brouillon` pour toujours (jamais `soumettreMutation`, voir
 * `src/photos/mutation.ts`/`src/signature/mutation.ts`) : ce sont les enregistrements LOCAUX de
 * capture (URI + SHA-256), pas le transport lui-même. Le transport passe désormais par
 * `fichier_bloc` (PLAN T1.4-f, `src/fichiers/envoiOrchestrateur.ts`) : UNE mutation par bloc de
 * 262 144 octets, construite et enfilée séparément — voir `src/fichiers/`. Un descripteur
 * enregistré ici SANS outil réel derrière ferait échouer le vidangeur (`Error`, `vidangeur.ts`) le
 * jour où l'une de ces mutations serait, par erreur, soumise — l'ABSENCE de descripteur pour
 * `photo_upload`/`signature_capture` reste le filet de sécurité, pas un oubli.
 *
 * `fichier_bloc` -> `m4_deposer_fichier`, `job_completion` -> `m4_completer_intervention`,
 * `materials_submit` -> `m6_declarer_materiaux_utilises` : les trois ajouts de PLAN T1.4-f (voir
 * `src/fichiers/`, `src/m4/completion.ts`, `src/m6/materiaux.ts`).
 *
 * `gps_consent_change` -> `m4_definir_consentement_gps` : PLAN T1.4-k (`src/m4/consentementGps.ts`).
 * `approval_decision` -> `m9_decider_demande_approbation` : l'étape 6 de PLAN T1.4-f (le propriétaire
 * décide depuis son téléphone, `src/approbations/contrat.ts`).
 * `lead_note` -> `m2_enregistrer_interaction` : PLAN T4.8 (le vendeur note un échange sur SON lead,
 * `src/m2/interaction.ts`).
 */
export const DESCRIPTEURS_MUTATION: ReadonlyMap<TypeMutation, DescripteurTypeMutation> = new Map<TypeMutation, DescripteurTypeMutation>([
  ["prise_en_charge_rappel", { tool: OUTIL_PRISE_RAPPEL_M1, construireArguments: argumentsRpcPriseRappelM1,
    interpreterResultat: interpreterPriseRappelM1, groupeSerie: "rappel", serialiserParChantier: true,
    conserverRefusHttpIncertains: true, verifierAvantEnvoi: true, validerRecuEnvoye: validerRecuPriseRappelM1 }],
  ["punch_in", { tool: "m4_pointer", interpreterResultat: versInterpretationGenerique }],
  ["punch_out", { tool: "m4_pointer", interpreterResultat: versInterpretationGenerique }],
  ["job_status_change", { tool: "m4_demarrer_route", interpreterResultat: versInterpretationGeneriqueDemarrerRoute }],
  ["fichier_bloc", { tool: "m4_deposer_fichier", interpreterResultat: versInterpretationGeneriqueDeposerFichier, validerRecuEnvoye: validerRecuDeposerFichier }],
  ["job_completion", { tool: "m4_completer_intervention", interpreterResultat: versInterpretationGeneriqueCompletion }],
  ["materials_submit", { groupeSerie:"materiaux", tool: "m6_declarer_materiaux_utilises", interpreterResultat: versInterpretationGeneriqueMateriaux,
    serialiserParChantier: true, validerRecuEnvoye: validerRecuDeclarerMateriauxUtilises }],
  ["materials_submit_with_proofs", {tool:OUTIL_MATERIAUX_AVEC_PREUVES,construireArguments:argumentsRpcMateriauxAvecPreuves,
    interpreterResultat:(r,m)=>{const i=interpreterMateriauxAvecPreuves(r,m);return i.accepte?{accepte:true,resume:i.resultat}:i;},
    serialiserParChantier:true,groupeSerie:"materiaux",verifierAvantEnvoi:true,validerRecuEnvoye:validerRecuMateriauxAvecPreuves}],
  ["variance_cause_classification", { tool: OUTIL_CLASSEMENT_VARIANCE, construireArguments: argumentsRpcClassementVariance,
    interpreterResultat: interpreterClassementGenerique, serialiserParChantier: true,
    conserverRefusHttpIncertains: true, verifierAvantEnvoi: true, validerRecuEnvoye: validerRecuClassementVariance }],
  ["gps_consent_change", { tool: "m4_definir_consentement_gps", interpreterResultat: versInterpretationGeneriqueConsentementGps }],
  // Le groupe technique existant « approbations » conserve toute décision suivante derrière une issue inconnue.
  ["approval_decision", { tool: "m9_decider_demande_approbation", interpreterResultat: versInterpretationGeneriqueDecisionApprobation,
    serialiserParChantier: true, conserverRefusHttpIncertains: true }],
  ["marketing_decision", { tool: "m7_decider_contenu", construireArguments: construireArgumentsDecisionMarketing,
    interpreterResultat: interpreterDecisionMarketing, serialiserParChantier: true,
    validerRecuEnvoye: mutation => interpreterDecisionMarketing({ ok: true,
      resultat: { accepte: true, resultat: mutation.resumeAccepte } }, mutation).accepte }],
  ["memory_revision_arbitration", { tool: "m10_arbitrer_revision", construireArguments: construireArgumentsArbitrageMemoire,
    interpreterResultat: interpreterArbitrageMemoire, serialiserParChantier: true,
    validerRecuEnvoye: mutation => interpreterArbitrageMemoire({ ok: true,
      resultat: { accepte: true, resultat: mutation.resumeAccepte } }, mutation).accepte }],
  ["lead_note", { tool: "m2_enregistrer_interaction", interpreterResultat: versInterpretationGeneriqueNote }],
]);
