import { creerMutation, formaterHorodatageLocal } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";

/**
 * Contrat mobile de `m4_definir_consentement_gps` : l'employé donne ou retire SON consentement à
 * la géolocalisation depuis l'app (POLITIQUE-geolocalisation.md §4 « l'employé peut retirer son
 * consentement via l'app employé », §7 « droit de retrait à tout moment » — PLAN T1.4-k).
 *
 * Lecture SEULE de `departments/m04-field-ops/src/m4_field_ops/outils.py` (closure
 * `definir_consentement_gps` et l'entrée `Outil(nom="m4_definir_consentement_gps", ...)`) et de
 * `consentement.py` (`ACTIONS_CONSENTEMENT`, `enregistrer_consentement`) — jamais exécuté ici
 * (ADR-0008 ; même discipline que `src/m4/pointage.ts`). Les clés suivent LITTÉRALEMENT le JSON
 * Schema serveur (`additionalProperties: false`, les cinq champs `required`).
 *
 * CE QUE LE SERVEUR FAIT DE CET APPEL (`acces.controler_technicien`, M4) :
 *  - `technicien_id` doit être la personne authentifiée par le jeton d'appareil : un identifiant
 *    différent est REFUSÉ (`REJ-IDENTITE-FOURNIE-DIFFERENTE`), jamais remplacé en silence — un
 *    employé ne donne ni ne retire jamais le consentement d'un autre ;
 *  - l'heure du retrait est celle de RÉCEPTION du serveur, pas `horodatage` (R12 §4, T1.4-d) : le
 *    retrait prend effet à cet instant, et `m4_pointer` bascule aussitôt en mode manuel ;
 *  - un retrait n'est jamais annulé par un renvoi : la mutation est idempotente par son `id`
 *    (R12 §4), donc une reprise après coupure rejoue la même réponse sans réécrire.
 *
 * LIMITES, dites plutôt que masquées :
 *  - l'app ne connaît pas encore la personne appairée : `technicienId` est saisi par l'employé,
 *    comme sur `punch.tsx` ; le serveur, lui, le confronte à l'identité authentifiée ;
 *  - `preuve` reste `{fictif: true, reference}` : `consentement.py` refuse toute preuve réelle
 *    tant que le mode ombre dure (même garde que `pointage.ATTESTATION`) ;
 *  - `version_politique` désigne le texte présenté à l'employé. La politique est une PROPOSITION
 *    (P0-7) que Nathan n'a pas encore validée : la constante ci-dessous nomme cette proposition,
 *    elle ne prétend pas à une version publiée. À remplacer quand la politique le sera.
 */

/** `consentement.ACTIONS_CONSENTEMENT` — catalogue fermé, jamais une valeur inventée côté mobile. */
export type ActionConsentementGps = "donne" | "retire";

export const ACTIONS_CONSENTEMENT_GPS: readonly ActionConsentementGps[] = ["donne", "retire"];

/** `docs/compliance/politiques/POLITIQUE-geolocalisation.md` : « PROPOSITION (P0-7) », sans numéro
 * de version tant que Nathan ne l'a pas validée (T3). */
export const VERSION_POLITIQUE_GEOLOCALISATION = "POLITIQUE-geolocalisation-proposition-P0-7";

/**
 * Regroupement d'ordre de la file sortante (`planification.ts` trie par `chantierId` puis
 * `sequence`) : un consentement n'est pas rattaché à un chantier. Cette valeur se trie AVANT tout
 * identifiant d'intervention (hexadécimal minuscule : « 0- » précède « 00… », « 0a… », « 1… »), donc
 * un retrait en file part avant les pointages en attente — un pointage créé après le retrait ne
 * doit jamais arriver au serveur avant lui.
 */
export const CHANTIER_ID_CONSENTEMENT_GPS = "0-consentement-gps";

/** Préfixe de `preuve.reference` : renvoie à la mutation de la file sortante, dont l'`id` est aussi la
 * clé d'idempotence journalisée par le serveur (jamais le document lui-même, POLITIQUE §4). */
export const PREFIXE_REFERENCE_PREUVE_CONSENTEMENT = "app:consentement-gps:";

/** `outils.py`, `_PREUVE_CONSENTEMENT` : « {fictif: true, reference} — mode ombre uniquement. » */
export interface PreuveConsentementGpsM4 {
  readonly fictif: true;
  readonly reference: string;
}

export interface ArgumentsM4DefinirConsentementGps {
  readonly technicien_id: string;
  readonly action: ActionConsentementGps;
  readonly horodatage: string;
  readonly version_politique: string;
  readonly preuve: PreuveConsentementGpsM4;
}

/**
 * Args EXACTS de `m4_definir_consentement_gps` (fonction pure — `horodatage` et `mutationId` sont
 * injectés par l'appelant, jamais lus d'une horloge ou d'un état ici). `mutationId` est l'`id` de
 * la mutation qui portera ces args : la preuve y renvoie.
 */
export function construireArgumentsDefinirConsentementGps(
  technicienId: string,
  action: ActionConsentementGps,
  horodatage: string,
  mutationId: string,
): ArgumentsM4DefinirConsentementGps {
  return {
    technicien_id: technicienId,
    action,
    horodatage,
    version_politique: VERSION_POLITIQUE_GEOLOCALISATION,
    preuve: { fictif: true, reference: `${PREFIXE_REFERENCE_PREUVE_CONSENTEMENT}${mutationId}` },
  };
}

/**
 * Crée la mutation `brouillon` d'un changement de consentement GPS (fonction pure : l'id vient de
 * `genererId`, l'heure de `horloge`). L'id est tiré UNE fois, puis réutilisé comme `id` de la
 * mutation ET dans `preuve.reference` : la preuve désigne exactement la mutation envoyée.
 */
export function creerMutationConsentementGps(
  params: { readonly technicienId: string; readonly action: ActionConsentementGps },
  genererId: () => string,
  horloge: HorlogeAppareil,
): MutationOutbox {
  const id = genererId();
  const horodatage = formaterHorodatageLocal(horloge);
  const args = construireArgumentsDefinirConsentementGps(params.technicienId, params.action, horodatage, id);
  return creerMutation(
    { type: "gps_consent_change", chantierId: CHANTIER_ID_CONSENTEMENT_GPS, payload: { ...args } },
    () => id,
    horloge,
  );
}

/** Verdict de rejet M4 (`verdicts.construire_verdict`) — seuls `code`/`detail` servent à l'affichage. */
export interface VerdictServeurConsentementGps {
  readonly code: string;
  readonly detail: string;
}

/** Accusé de succès (`consentement.enregistrer_consentement`) : `actif` dit l'état APRÈS l'appel
 * (`false` après un retrait) ; `horodatage` est l'heure du serveur pour un appel d'appareil. */
export interface AccuseConsentementGpsM4 {
  readonly technicien_id: string;
  readonly action: ActionConsentementGps;
  readonly horodatage: string;
  readonly ligne_id: string;
  readonly actif: boolean;
  readonly tete_chaine: string;
}

export type InterpretationConsentementGps =
  | { readonly accepte: true; readonly accuse: AccuseConsentementGpsM4 | null }
  | { readonly accepte: false; readonly verdict: VerdictServeurConsentementGps };

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null;
}

function texteOu(valeur: unknown, repli: string): string {
  return typeof valeur === "string" ? valeur : repli;
}

/**
 * Interprète la réponse BUSINESS de `m4_definir_consentement_gps` — distincte du succès/échec HTTP
 * de `/tools/invoke`. Même patron `depuis_couple` que `m4_pointer` (`interpreterResultatPointage`) :
 * un HTTP 200 `ok:true` peut être un REJET métier définitif (`REJ-IDENTITE-FOURNIE-DIFFERENTE`,
 * `REJ-CONSENTEMENT-INVALIDE`, `REJ-IDENTITE-APPAREIL-INVALIDE`…) qu'il faut afficher tel quel, jamais
 * comme un succès silencieux : un retrait qui n'a pas eu lieu doit se voir (R12 §4).
 *
 * Forme non reconnue -> SUCCÈS sans accusé (le serveur a répondu HTTP 200) plutôt qu'un faux échec ;
 * même choix documenté que `interpreterResultatPointage`.
 */
export function interpreterResultatDefinirConsentementGps(resultatBrut: unknown): InterpretationConsentementGps {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};

  if (enveloppe.ok === false) {
    return {
      accepte: false,
      verdict: { code: texteOu(enveloppe.erreur, "erreur_inconnue"), detail: texteOu(enveloppe.details, "") },
    };
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
    return { accepte: true, accuse: accuseBrut as AccuseConsentementGpsM4 | null };
  }

  return { accepte: true, accuse: null };
}
