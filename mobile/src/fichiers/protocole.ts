import type { MutationOutbox } from "../outbox/types";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { TAILLE_BLOC_OCTETS, TAILLE_FICHIER_MAX_OCTETS, NOMBRE_BLOCS_MAX } from "./decoupage";

/**
 * Contrat mobile de `m4_deposer_fichier`/`m4_etat_fichier` (PLAN T1.4-f).
 *
 * CONTRAT FIXE, écrit avant la route serveur puis confronté à elle à l'intégration : les deux
 * outils sont livrés par PLAN T1.4-e2 (`departments/m04-field-ops/src/m4_field_ops/outils.py`,
 * dépôt `src/opsys/fichiers.py`, `docs/architecture/FICHIERS.md`) avec exactement ces paramètres
 * et ces formes de réponse. `m4_deposer_fichier` est N2 (tâche interne, jamais mis en attente
 * d'approbation) ; la complétion qui s'en sert reste soumise aux approbations :
 *
 *  - `m4_deposer_fichier(empreinte_sha256, taille_octets, type_mime, index_bloc, nombre_blocs,
 *    bloc_base64) -> {"accepte": true, "resultat": {"reference", "complet", "blocs_recus"}} |
 *    {"accepte": false, "verdict": {...}}` — même patron `depuis_couple` que `m4_pointer`
 *    (`src/m4/pointage.ts`) : un HTTP 200 peut être un REJET métier définitif
 *    (`REJ-FICHIER-PARAMETRES-INVALIDES`, `REJ-FICHIER-TROP-VOLUMINEUX`, `REJ-FICHIER-INCOHERENT`,
 *    `REJ-FICHIER-EMPREINTE-DISCORDANTE`, `REJ-FICHIER-TYPE-NON-PERMIS`).
 *  - `m4_etat_fichier(empreinte_sha256) -> {"accepte": true, "resultat": {"existe", "complet",
 *    "blocs_recus", "reference"}}` — MÊME patron `accepte`/`resultat`|`verdict`, pour reprendre
 *    un envoi interrompu sans réémettre les blocs déjà reçus.
 *
 * FILE_ACK_BOUND : le dépôt utilise le snapshot JSON commun avant toute lecture et exige
 * la mutation persistée. B1 ferme aussi l'état sous contexte local léger et l'observation
 * live de readiness ; le statut local historique ne constitue jamais une permission.
 */

/** `m4_deposer_fichier` n'accepte que ces deux types — CONTRAT FIXE. Les photos capturées par
 * `src/photos/service.ts` sont toujours `.jpg` (capture `imageType: "jpg"`) ; la signature
 * capturée par `src/signature/service.ts` est toujours `.png` par défaut de
 * `react-native-signature-canvas` (vérifié en lisant `node_modules/react-native-signature-canvas
 * /index.js` : `imageType || "image/png"`, jamais fixé autrement par `signature.tsx`) — voir
 * `src/fichiers/candidats.ts::deduireTypeMimeDepuisUri` pour la DÉRIVATION depuis l'extension
 * réelle du fichier local, jamais une valeur supposée en dur à cet endroit. */
export type TypeMimeFichier = "image/jpeg" | "image/png";

export const TYPES_MIME_FICHIER: readonly TypeMimeFichier[] = ["image/jpeg", "image/png"];

export interface VerdictServeurFichier {
  readonly code: string;
  readonly detail: string;
}

/** Args EXACTS d'un appel `m4_deposer_fichier` (un bloc). Snake_case : forme du contrat outil,
 * jamais retraduite ici (même discipline que `src/m4/pointage.ts::ArgumentsM4Pointer`). */
export interface ArgumentsM4DeposerFichier {
  readonly empreinte_sha256: string;
  readonly taille_octets: number;
  readonly type_mime: TypeMimeFichier;
  readonly index_bloc: number;
  readonly nombre_blocs: number;
  readonly bloc_base64: string;
}

export function construireArgumentsDeposerFichier(
  empreinteSha256: string,
  tailleOctets: number,
  typeMime: TypeMimeFichier,
  indexBloc: number,
  nombreBlocs: number,
  blocBase64: string,
): ArgumentsM4DeposerFichier {
  return {
    empreinte_sha256: empreinteSha256,
    taille_octets: tailleOctets,
    type_mime: typeMime,
    index_bloc: indexBloc,
    nombre_blocs: nombreBlocs,
    bloc_base64: blocBase64,
  };
}

export interface ArgumentsM4EtatFichier {
  readonly empreinte_sha256: string;
}

export function construireArgumentsEtatFichier(empreinteSha256: string): ArgumentsM4EtatFichier {
  return { empreinte_sha256: empreinteSha256 };
}

/** Référence construite par le serveur à la réception du DERNIER bloc — `"fichier:sha256:<hex>"`
 * (contrat donné). DÉTERMINISTE depuis l'empreinte déjà connue localement : le mobile n'a donc
 * jamais besoin d'attendre/relire la chaîne exacte renvoyée par le serveur pour la calculer —
 * seulement pour savoir QUAND le fichier est `complet` (voir `src/fichiers/etatEnvoi.ts`). */
export function construireReferenceFichier(empreinteSha256: string): string {
  return `fichier:sha256:${empreinteSha256}`;
}

export interface ResultatDepotBloc {
  readonly reference: string | null;
  readonly complet: boolean;
  readonly blocsRecus: readonly number[];
}

export type InterpretationDeposerFichier =
  | { readonly accepte: true; readonly resultat: ResultatDepotBloc }
  | { readonly accepte: false; readonly verdict: VerdictServeurFichier };

export interface ResultatEtatFichier {
  readonly existe: boolean;
  readonly complet: boolean;
  readonly blocsRecus: readonly number[];
  readonly reference: string | null;
}

export type InterpretationEtatFichier =
  | { readonly accepte: true; readonly resultat: ResultatEtatFichier }
  | { readonly accepte: false; readonly verdict: VerdictServeurFichier };

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null;
}

const ACK_INCONNU: { readonly accepte: false; readonly verdict: VerdictServeurFichier } = { accepte: false,
  verdict: { code: "accuse_invalide", detail: "Réponse métier de dépôt de fichier inconnue." } };
function objetFerme(v: unknown, cles: readonly string[]): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v) &&
    Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
}
function entierBorne(v: unknown, min: number, max: number): v is number {
  return typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
}
/** Après snapshot entier uniquement : forme exacte de l'appel persistant, jamais une réparation.
 * Bornes du socle fichiers.py : 10MiB, blocs de 262144 octets, 64 blocs maximum. */
function argumentsMutation(v: unknown): ArgumentsM4DeposerFichier | null {
  if (!estObjet(v) || v.type !== "fichier_bloc" || typeof v.id !== "string" || !v.id ||
    typeof v.proprietaire !== "string" || !v.proprietaire || typeof v.chantierId !== "string" || !v.chantierId) return null;
  const p = v.payload;
  if (!objetFerme(p, ["empreinte_sha256", "taille_octets", "type_mime", "index_bloc", "nombre_blocs", "bloc_base64"]) ||
    typeof p.empreinte_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(p.empreinte_sha256) ||
    !entierBorne(p.taille_octets, 1, TAILLE_FICHIER_MAX_OCTETS) || !entierBorne(p.nombre_blocs, 1, NOMBRE_BLOCS_MAX) ||
    !entierBorne(p.index_bloc, 0, p.nombre_blocs - 1) ||
    (p.type_mime !== "image/jpeg" && p.type_mime !== "image/png") ||
    typeof p.bloc_base64 !== "string") return null;
  if (p.nombre_blocs !== Math.ceil(p.taille_octets / TAILLE_BLOC_OCTETS)) return null;
  const b64 = p.bloc_base64;
  // Longueur bornée avant regex ; pas de décodeur natif ni de lecture de fichier à cette frontière.
  const octets = Math.min(TAILLE_BLOC_OCTETS, p.taille_octets - p.index_bloc * TAILLE_BLOC_OCTETS);
  if (b64.length !== 4 * Math.ceil(octets / 3) || !/^[A-Za-z0-9+/]*={0,2}$/.test(b64)) return null;
  const padding = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
  if (b64.length / 4 * 3 - padding !== octets) return null;
  return { empreinte_sha256: p.empreinte_sha256, taille_octets: p.taille_octets, type_mime: p.type_mime,
    index_bloc: p.index_bloc, nombre_blocs: p.nombre_blocs, bloc_base64: b64 };
}
function confirmationBloc(v: unknown, args: ArgumentsM4DeposerFichier, durable = false): ResultatDepotBloc | null {
  const cle = durable ? "blocsRecus" : "blocs_recus";
  if (!objetFerme(v, ["reference", "complet", cle]) || typeof v.complet !== "boolean") return null;
  const reference = v.reference;
  if (reference !== null && typeof reference !== "string") return null;
  const indices = v[cle];
  if (!Array.isArray(indices) || indices.length > args.nombre_blocs ||
    !indices.every((i): i is number => entierBorne(i, 0, args.nombre_blocs - 1)) ||
    new Set(indices).size !== indices.length || !indices.includes(args.index_bloc)) return null;
  if (v.complet) {
    if (indices.length !== args.nombre_blocs || v.reference !== construireReferenceFichier(args.empreinte_sha256)) return null;
  } else if (v.reference !== null || indices.length === args.nombre_blocs) return null;
  return { reference, complet: v.complet, blocsRecus: indices };
}
const REFUS_DEPOT = ["REJ-FICHIER-PARAMETRES-INVALIDES", "REJ-FICHIER-TROP-VOLUMINEUX",
  "REJ-FICHIER-INCOHERENT", "REJ-FICHIER-EMPREINTE-DISCORDANTE", "REJ-FICHIER-TYPE-NON-PERMIS",
  "REJ-CONTRAT-INVALIDE"]; // m4.deposer_fichier : absence de connexion durable.
/** Un ACK partiel ne porte aucun SHA : confirmation du bloc demandé dans ce RPC seulement.
 * La référence finale porte le SHA attendu ; le CAS serveur vérifie séparément les octets.
 * Aucun contexte, identité refusée, attente d'approbation ou réponse mal liée => même intention. */
export function interpreterResultatDeposerFichier(
  resultatBrut: unknown, mutation?: MutationOutbox,
): InterpretationDeposerFichier {
  const r = copierJsonLecture(resultatBrut), c = copierJsonLecture(mutation);
  if (r === JSON_LECTURE_INVALIDE || c === JSON_LECTURE_INVALIDE) return ACK_INCONNU;
  const args = argumentsMutation(c);
  if (!args || !estObjet(r)) return ACK_INCONNU;
  const rejoue = Object.hasOwn(r, "rejoue") ? ["rejoue"] : [];
  if (rejoue.length && typeof r.rejoue !== "boolean") return ACK_INCONNU;
  if (r.ok === false) {
    // Autorité/refus métier générique non attribuable : pas de terminalité fabriquée.
    if (!objetFerme(r, ["ok", "erreur", "details", ...rejoue]) || typeof r.details !== "string" ||
      typeof r.erreur !== "string" || ![...REFUS_DEPOT, "invalid_request", "arguments_invalides"].includes(r.erreur)) return ACK_INCONNU;
    return { accepte: false, verdict: { code: r.erreur, detail: r.details } };
  }
  if (!objetFerme(r, ["ok", "resultat", ...rejoue]) || r.ok !== true || !estObjet(r.resultat)) return ACK_INCONNU;
  const m = r.resultat;
  if (m.accepte === false) {
    if (!objetFerme(m, ["accepte", "verdict"]) || !estObjet(m.verdict)) return ACK_INCONNU;
    const v = m.verdict;
    const statut = Object.hasOwn(v, "statut") ? ["statut"] : [];
    if (!objetFerme(v, ["code", "detail", ...statut]) || typeof v.code !== "string" ||
      !REFUS_DEPOT.includes(v.code) || typeof v.detail !== "string" ||
      (statut.length && typeof v.statut !== "string")) return ACK_INCONNU;
    return { accepte: false, verdict: { code: v.code, detail: v.detail } };
  }
  if (!objetFerme(m, ["accepte", "resultat"]) || m.accepte !== true) return ACK_INCONNU;
  const resultat = confirmationBloc(m.resultat, args);
  return resultat ? { accepte: true, resultat } : ACK_INCONNU;
}
/** Validation locale, pas signature du reçu : ne promeut jamais un legacy sans contexte.
 * Le caller doit l'appliquer avant sa propre décision de disponibilité/terminalité. */
export function validerRecuDeposerFichier(mutation: unknown): boolean {
  const c = copierJsonLecture(mutation);
  if (c === JSON_LECTURE_INVALIDE || !estObjet(c) || c.statut !== "envoyee") return false;
  const args = argumentsMutation(c);
  return args !== null && confirmationBloc(c.resumeAccepte, args, true) !== null;
}

/** Métadonnées LOCALES vérifiées avant la query SHA ; le serveur ne les réémet pas. */
export interface ContexteEtatFichierM4 {
  readonly empreinte_sha256: string;
  readonly taille_octets: number;
  readonly type_mime: TypeMimeFichier;
  readonly nombre_blocs: number;
}
function contexteEtatValide(v: unknown): ContexteEtatFichierM4 | null {
  if (!objetFerme(v, ["empreinte_sha256", "taille_octets", "type_mime", "nombre_blocs"]) ||
    typeof v.empreinte_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(v.empreinte_sha256) ||
    !entierBorne(v.taille_octets, 1, TAILLE_FICHIER_MAX_OCTETS) || !entierBorne(v.nombre_blocs, 1, NOMBRE_BLOCS_MAX) ||
    (v.type_mime !== "image/jpeg" && v.type_mime !== "image/png") ||
    v.nombre_blocs !== Math.ceil(v.taille_octets / TAILLE_BLOC_OCTETS)) return null;
  return { empreinte_sha256: v.empreinte_sha256, taille_octets: v.taille_octets,
    type_mime: v.type_mime, nombre_blocs: v.nombre_blocs };
}
function etatFichierValide(v: unknown, c: ContexteEtatFichierM4, durable = false): ResultatEtatFichier | null {
  const cle = durable ? "blocsRecus" : "blocs_recus";
  if (!objetFerme(v, ["existe", "complet", cle, "reference"]) || typeof v.existe !== "boolean" || typeof v.complet !== "boolean") return null;
  const indices = v[cle], reference = v.reference;
  if (reference !== null && typeof reference !== "string") return null;
  if (!Array.isArray(indices) || indices.length > c.nombre_blocs ||
    !indices.every((i): i is number => entierBorne(i, 0, c.nombre_blocs - 1)) || new Set(indices).size !== indices.length) return null;
  if (!v.existe && (v.complet || indices.length || reference !== null)) return null;
  if (v.complet ? (indices.length !== c.nombre_blocs || reference !== construireReferenceFichier(c.empreinte_sha256))
    : (reference !== null || indices.length === c.nombre_blocs)) return null;
  return { existe: v.existe, complet: v.complet, blocsRecus: indices, reference };
}
/** État lu sous la capture actuelle, lié au SHA demandé et au découpage vérifié localement.
 * Sans contexte ou réponse inconnue : aucune absence/complétude fabriquée. */
export function interpreterResultatEtatFichier(brut: unknown, contexte?: ContexteEtatFichierM4): InterpretationEtatFichier {
  const r = copierJsonLecture(brut), cs = copierJsonLecture(contexte);
  if (r === JSON_LECTURE_INVALIDE || cs === JSON_LECTURE_INVALIDE) return ACK_INCONNU;
  const c = contexteEtatValide(cs);
  if (!c || !objetFerme(r, ["ok", "resultat"]) || r.ok !== true || !estObjet(r.resultat)) return ACK_INCONNU;
  const m = r.resultat;
  if (m.accepte === false) {
    const v = m.verdict;
    if (!objetFerme(m, ["accepte", "verdict"]) || !estObjet(v)) return ACK_INCONNU;
    const statut = Object.hasOwn(v, "statut") ? ["statut"] : [];
    if (!objetFerme(v, ["code", "detail", ...statut]) || typeof v.code !== "string" || typeof v.detail !== "string" ||
      (statut.length && typeof v.statut !== "string") ||
      ![...REFUS_DEPOT, "REJ-IDENTITE-APPAREIL-INVALIDE"].includes(v.code)) return ACK_INCONNU;
    return { accepte: false, verdict: { code: v.code, detail: v.detail } };
  }
  if (!objetFerme(m, ["accepte", "resultat"]) || m.accepte !== true) return ACK_INCONNU;
  const resultat = etatFichierValide(m.resultat, c);
  return resultat ? { accepte: true, resultat } : ACK_INCONNU;
}
/** Relit une preuve de bloc locale ; reconcilie legacy à trois champs reste illisible. */
export function lireContexteBlocFichier(mutation: unknown): { readonly contexte: ContexteEtatFichierM4; readonly index: number } | null {
  const m = copierJsonLecture(mutation);
  if (m === JSON_LECTURE_INVALIDE || !estObjet(m) || typeof m.proprietaire !== "string" || !m.proprietaire) return null;
  if (m.type === "fichier_bloc") {
    const a = argumentsMutation(m); return a ? { contexte: { empreinte_sha256: a.empreinte_sha256,
      taille_octets: a.taille_octets, type_mime: a.type_mime, nombre_blocs: a.nombre_blocs }, index: a.index_bloc } : null;
  }
  if (m.type !== "fichier_bloc_reconcilie" || !objetFerme(m.payload,
    ["empreinte_sha256", "taille_octets", "type_mime", "nombre_blocs", "index_bloc"])) return null;
  const p = m.payload, c = contexteEtatValide({ empreinte_sha256: p.empreinte_sha256,
    taille_octets: p.taille_octets, type_mime: p.type_mime, nombre_blocs: p.nombre_blocs });
  return c && entierBorne(p.index_bloc, 0, c.nombre_blocs - 1) ? { contexte: c, index: p.index_bloc } : null;
}
/** Historique local distinct de l'ACK dépôt, jamais une permission mise en cache. */
export function validerRecuEtatFichier(mutation: unknown): boolean {
  const m = copierJsonLecture(mutation), bloc = lireContexteBlocFichier(mutation);
  if (m === JSON_LECTURE_INVALIDE || !estObjet(m) || m.statut !== "envoyee" || !bloc ||
    !objetFerme(m.resumeAccepte, ["genre", "contexte", "etat"]) || m.resumeAccepte.genre !== "etat_fichier") return false;
  const c = contexteEtatValide(m.resumeAccepte.contexte);
  if (!c || Object.keys(c).some(k => Reflect.get(c, k) !== Reflect.get(bloc.contexte, k))) return false;
  const e = etatFichierValide(m.resumeAccepte.etat, c, true);
  return e !== null && e.existe && e.blocsRecus.includes(bloc.index);
}
export function validerRecuFichier(mutation: unknown): boolean {
  return validerRecuDeposerFichier(mutation) || validerRecuEtatFichier(mutation);
}

/** Copie typée des seules lignes fichier ; autres types ignorés après snapshot entier. */
export function lireMutationsFichiers(v: unknown): MutationOutbox[] | null {
  const copie = copierJsonLecture(v); if (copie === JSON_LECTURE_INVALIDE || !Array.isArray(copie)) return null;
  const sortie: MutationOutbox[] = [];
  for (const m of copie) {
    if (!estObjet(m) || Array.isArray(m)) return null;
    if (m.type !== "fichier_bloc" && m.type !== "fichier_bloc_reconcilie") continue;
    if (typeof m.id !== "string" || !m.id || typeof m.chantierId !== "string" ||
      !estObjet(m.payload) || Array.isArray(m.payload) ||
      !(m.sequence === null || entierBorne(m.sequence,1,Number.MAX_SAFE_INTEGER)) ||
      !(m.dependsOn === null || typeof m.dependsOn === "string") ||
      !(m.statut === "brouillon" || m.statut === "en_attente" || m.statut === "envoi" || m.statut === "envoyee" || m.statut === "echec_permanent") ||
      !entierBorne(m.tentatives,0,Number.MAX_SAFE_INTEGER) || typeof m.createdAtLocal !== "string" ||
      !(m.prochaineTentativeA === null || typeof m.prochaineTentativeA === "string") ||
      !(m.proprietaire === null || typeof m.proprietaire === "string")) return null;
    sortie.push({id:m.id,sequence:m.sequence,type:m.type,chantierId:m.chantierId,payload:m.payload,
      dependsOn:m.dependsOn,statut:m.statut,tentatives:m.tentatives,createdAtLocal:m.createdAtLocal,
      prochaineTentativeA:m.prochaineTentativeA,proprietaire:m.proprietaire,
      ...(Object.hasOwn(m,"resumeAccepte") ? {resumeAccepte:m.resumeAccepte} : {})});
  }
  return sortie;
}
