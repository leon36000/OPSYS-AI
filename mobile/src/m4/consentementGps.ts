import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { lireEnveloppeMetier } from "../protocole/enveloppeOutil";
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
 *  - `technicienId` n'est plus saisi (PLAN T1.4-c5) : l'écran envoie la personne que le serveur a
 *    confirmée pour l'appareil (`src/identite/`) ; le serveur, lui, la confronte à l'identité
 *    authentifiée du jeton et refuse tout autre identifiant ;
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

const ACCUSE_INVALIDE: InterpretationConsentementGps = { accepte: false, verdict: {
  code: "accuse_invalide", detail: "Consentement GPS non confirmé : conserver la même intention et sa clé.",
} };
const REFUS_EXPLICITES = new Set(["arguments_invalides", "mutation_conflit", "refus_metier", "hors_portee_role",
  "REJ-IDENTITE-FOURNIE-DIFFERENTE", "REJ-IDENTITE-APPAREIL-INVALIDE", "REJ-CONSENTEMENT-INVALIDE"]);
const CHAMPS_ACCUSE = ["technicien_id", "action", "horodatage", "ligne_id", "actif", "tete_chaine"];
const empreinte = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
function estObjet(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Même validation calendaire bornée que les autres accusés mobiles ; l'heure reste celle du serveur. */
function instant(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(v);
  if (!m || !Number.isFinite(Date.parse(v))) return false;
  const [annee, mois, jour, heure, minute, seconde] = m.slice(1, 7).map(Number);
  if (annee < 1 || mois < 1 || mois > 12 || jour < 1 || jour > 31 || heure > 23 || minute > 59 || seconde > 59) return false;
  const date = new Date(0); date.setUTCFullYear(annee, mois - 1, jour);
  return date.getUTCFullYear() === annee && date.getUTCMonth() === mois - 1 && date.getUTCDate() === jour;
}

/** Une réponse inconnue ne confirme jamais un retrait. Le contexte est l'intention persistée,
 * pas une nouvelle identité. Le serveur emploie sa réception : ne pas égaler son heure à celle
 * de l'appareil. Les empreintes sont validées syntaxiquement, sans prétendre vérifier la chaîne. */
export function interpreterResultatDefinirConsentementGps(
  resultatBrut: unknown, mutation?: MutationOutbox,
): InterpretationConsentementGps {
  const brut = copierJsonLecture(resultatBrut);
  if (brut === JSON_LECTURE_INVALIDE) return ACCUSE_INVALIDE;
  const lecture = lireEnveloppeMetier(brut);
  if (!lecture.ok) {
    return lecture.genre === "refus" && REFUS_EXPLICITES.has(lecture.verdict.code)
      ? { accepte: false, verdict: lecture.verdict } : ACCUSE_INVALIDE;
  }
  const copie = copierJsonLecture(mutation);
  const accuse = lecture.valeur;
  if (copie === JSON_LECTURE_INVALIDE || !estObjet(copie) || !estObjet(copie.payload) || !estObjet(accuse)) return ACCUSE_INVALIDE;
  const payload = copie.payload;
  if (copie.type !== "gps_consent_change" || copie.chantierId !== CHANTIER_ID_CONSENTEMENT_GPS ||
    typeof copie.id !== "string" || copie.id.trim() === "" || typeof copie.proprietaire !== "string" || copie.proprietaire.trim() === "" ||
    payload.technicien_id !== copie.proprietaire || (payload.action !== "donne" && payload.action !== "retire") ||
    payload.horodatage !== copie.createdAtLocal || !instant(copie.createdAtLocal) ||
    typeof payload.version_politique !== "string" || payload.version_politique.trim() === "" ||
    !estObjet(payload.preuve) || Object.keys(payload.preuve).length !== 2 || payload.preuve.fictif !== true ||
    payload.preuve.reference !== `${PREFIXE_REFERENCE_PREUVE_CONSENTEMENT}${copie.id}` ||
    Object.keys(accuse).length !== CHAMPS_ACCUSE.length || !CHAMPS_ACCUSE.every(c => Object.hasOwn(accuse, c)) ||
    accuse.technicien_id !== copie.proprietaire || accuse.action !== payload.action || accuse.actif !== (payload.action === "donne") ||
    !instant(accuse.horodatage) || !empreinte(accuse.ligne_id) || !empreinte(accuse.tete_chaine)) return ACCUSE_INVALIDE;
  return { accepte: true, accuse: { technicien_id: copie.proprietaire, action: payload.action,
    horodatage: accuse.horodatage, ligne_id: accuse.ligne_id, actif: payload.action === "donne", tete_chaine: accuse.tete_chaine } };
}
