import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import type { Reponse } from "../m7/contrat";
import { horodatageM10Valide } from "./contrat";
import type { ReferenceDocumentM10 } from "./documentsAffaireOutbox";

export type StatutVersionDocumentM10 =
  | "DEPOSEE_NON_ACTIVEE" | "COURANTE" | "HISTORIQUE_NON_COURANTE" | "RETIREE";
interface MetadataVersionM10 {
  readonly version_schema: 1;
  readonly affaire_id: string;
  readonly document_ref: ReferenceDocumentM10;
  readonly version_source: ReferenceDocumentM10;
  readonly statut: StatutVersionDocumentM10;
  readonly titre: string;
  readonly methode: "utf8-exact-v1";
  readonly source_sha256: string;
  readonly taille_points: number;
  readonly taille_octets: number;
  readonly auteur: { readonly personne: string; readonly role: "admin"; readonly source: "appareil" };
  readonly horodatage: string;
  readonly activation_ref: ReferenceDocumentM10 | null;
}
export interface LigneIndexDocumentM10 extends MetadataVersionM10 {
  readonly version_no: number;
  readonly version_precedente_attendue: ReferenceDocumentM10;
  readonly activation_attendue: ReferenceDocumentM10 | null;
}
export interface IndexDocumentsAffaireM10 {
  readonly version_schema: 1;
  readonly affaire_id: string;
  readonly decalage: number;
  readonly limite: number;
  readonly total_versions: number;
  readonly suivant_decalage: number | null;
  readonly versions: readonly LigneIndexDocumentM10[];
}
export type VersionDocumentAffaireM10 =
  | (MetadataVersionM10 & { readonly statut: "RETIREE"; readonly corps?: never })
  | (MetadataVersionM10 & { readonly statut: Exclude<StatutVersionDocumentM10, "RETIREE">; readonly corps: string });
export interface ArgumentsIndexDocumentsAffaireM10 {
  readonly affaire_id: string; readonly decalage: number; readonly limite: number;
}
export interface ArgumentsVersionDocumentAffaireM10 {
  readonly affaire_id: string;
  readonly document_ref: ReferenceDocumentM10;
  readonly version_source: ReferenceDocumentM10;
}

const META = ["version_schema", "affaire_id", "document_ref", "version_source", "statut", "titre",
  "methode", "source_sha256", "taille_points", "taille_octets", "auteur", "horodatage", "activation_ref"];
const LIGNE = [...META, "version_no", "version_precedente_attendue", "activation_attendue"];
const INDEX = ["version_schema", "affaire_id", "decalage", "limite", "total_versions", "suivant_decalage", "versions"];
const objet = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const ferme = (v: unknown, cles: readonly string[]): v is Record<string, unknown> => objet(v) &&
  Object.keys(v).length === cles.length && cles.every(k => Object.hasOwn(v, k));
const entier = (v: unknown, min: number, max: number): v is number => typeof v === "number" &&
  Number.isSafeInteger(v) && !Object.is(v, -0) && v >= min && v <= max;
const hash = (v: unknown): v is string => typeof v === "string" && v.length === 64 && /^[0-9a-f]{64}$/.test(v);
const scalaire = (v: unknown): v is string => typeof v === "string" && !/[\p{Cs}]/u.test(v);
const texte = (v: unknown, max: number): v is string => scalaire(v) && [...v].length <= max &&
  /[^\p{White_Space}\u001c-\u001f]/u.test(v);
// Même forme fermée que affaire.valide et le writer mobile ; aucune normalisation.
const affaire = (v: unknown): v is string => typeof v === "string" &&
  /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}(?:~opp~[A-Za-z0-9][A-Za-z0-9._:-]{0,127})?$/.test(v) &&
  !/[^A-Za-z0-9._:~\-]/.test(v);
const egalRef = (a: ReferenceDocumentM10 | null, b: ReferenceDocumentM10 | null): boolean => a === null ? b === null :
  b !== null && a.registre === b.registre && a.index === b.index && a.ligne_id === b.ligne_id;

function reference(v: unknown): ReferenceDocumentM10 | undefined {
  return ferme(v, ["registre", "index", "ligne_id"]) && v.registre === "documents_affaire" &&
    entier(v.index, 0, 511) && hash(v.ligne_id)
    ? { registre: "documents_affaire", index: v.index, ligne_id: v.ligne_id } : undefined;
}
function argsIndex(v: unknown): ArgumentsIndexDocumentsAffaireM10 | undefined {
  return ferme(v, ["affaire_id", "decalage", "limite"]) && affaire(v.affaire_id) &&
    entier(v.decalage, 0, 64) && entier(v.limite, 1, 8)
    ? { affaire_id: v.affaire_id, decalage: v.decalage, limite: v.limite } : undefined;
}
function argsVersion(v: unknown): ArgumentsVersionDocumentAffaireM10 | undefined {
  if (!ferme(v, ["affaire_id", "document_ref", "version_source"]) || !affaire(v.affaire_id)) return undefined;
  const doc = reference(v.document_ref), source = reference(v.version_source);
  if (!doc || !source || doc.index > source.index || !refsCoherentes([doc, source])) return undefined;
  return { affaire_id: v.affaire_id, document_ref: doc, version_source: source };
}
function invalideArguments(): never { throw new Error("DOCUMENT-LECTURE-ARGUMENTS-INVALIDES"); }
export function construireArgumentsIndexDocumentsAffaireM10(
  affaireId: string, decalage: number, limite: number,
): ArgumentsIndexDocumentsAffaireM10 {
  const a = argsIndex(copierJsonLecture({ affaire_id: affaireId, decalage, limite }));
  if (!a) return invalideArguments();
  return Object.freeze(a);
}
export function construireArgumentsVersionDocumentAffaireM10(
  affaireId: string, documentRef: ReferenceDocumentM10, versionSource: ReferenceDocumentM10,
): ArgumentsVersionDocumentAffaireM10 {
  const a = argsVersion(copierJsonLecture({ affaire_id: affaireId, document_ref: documentRef, version_source: versionSource }));
  if (!a) return invalideArguments();
  Object.freeze(a.document_ref); Object.freeze(a.version_source);
  return Object.freeze(a);
}

/** Une référence n'atteste pas son hash de chaîne absent du DTO ; sa forme et ses liens restent contrôlés. */
function refsCoherentes(refs: readonly (ReferenceDocumentM10 | null)[]): boolean {
  const indices = new Map<number, string>(), hashes = new Map<string, number>();
  for (const ref of refs) {
    if (ref === null) continue;
    if (indices.has(ref.index) && indices.get(ref.index) !== ref.ligne_id ||
      hashes.has(ref.ligne_id) && hashes.get(ref.ligne_id) !== ref.index) return false;
    indices.set(ref.index, ref.ligne_id); hashes.set(ref.ligne_id, ref.index);
  }
  return true;
}
function metadata(v: Record<string, unknown>): MetadataVersionM10 | undefined {
  if (v.version_schema !== 1 || !affaire(v.affaire_id) || !texte(v.titre, 120) ||
    v.methode !== "utf8-exact-v1" || !hash(v.source_sha256) || !entier(v.taille_points, 1, 2000) ||
    !entier(v.taille_octets, v.taille_points, v.taille_points * 4) ||
    typeof v.horodatage !== "string" || v.horodatage.length > 40 || !horodatageM10Valide(v.horodatage) ||
    !ferme(v.auteur, ["personne", "role", "source"]) || typeof v.auteur.personne !== "string" ||
    !/^[a-z][a-z0-9_.-]{1,63}$/.test(v.auteur.personne) || /\s/.test(v.auteur.personne) ||
    v.auteur.role !== "admin" || v.auteur.source !== "appareil" ||
    (v.statut !== "DEPOSEE_NON_ACTIVEE" && v.statut !== "COURANTE" &&
      v.statut !== "HISTORIQUE_NON_COURANTE" && v.statut !== "RETIREE")) return undefined;
  const doc = reference(v.document_ref), source = reference(v.version_source);
  const act = v.activation_ref === null ? null : reference(v.activation_ref);
  if (!doc || !source || act === undefined || doc.index > source.index ||
    act !== null && act.index <= source.index || !refsCoherentes([doc, source, act]) ||
    v.statut === "DEPOSEE_NON_ACTIVEE" && act !== null ||
    (v.statut === "COURANTE" || v.statut === "HISTORIQUE_NON_COURANTE") && act === null) return undefined;
  return { version_schema: 1, affaire_id: v.affaire_id, document_ref: doc, version_source: source,
    statut: v.statut, titre: v.titre, methode: "utf8-exact-v1", source_sha256: v.source_sha256,
    taille_points: v.taille_points, taille_octets: v.taille_octets,
    auteur: { personne: v.auteur.personne, role: "admin", source: "appareil" },
    horodatage: v.horodatage, activation_ref: act };
}
function ligne(v: unknown): LigneIndexDocumentM10 | undefined {
  if (!ferme(v, LIGNE)) return undefined;
  const meta = metadata(v), precedente = reference(v.version_precedente_attendue);
  const attendue = v.activation_attendue === null ? null : reference(v.activation_attendue);
  if (!meta || !precedente || attendue === undefined || !entier(v.version_no, 1, 8) ||
    (v.version_no === 1) !== egalRef(meta.document_ref, meta.version_source) ||
    precedente.index < meta.version_source.index || attendue !== null && attendue.index <= meta.document_ref.index ||
    !refsCoherentes([meta.document_ref, meta.version_source, meta.activation_ref, precedente, attendue]) ||
    meta.activation_ref !== null && (attendue === null || attendue.index < meta.activation_ref.index) ||
    meta.statut === "COURANTE" && !egalRef(meta.activation_ref, attendue) ||
    meta.statut === "HISTORIQUE_NON_COURANTE" && egalRef(meta.activation_ref, attendue)) return undefined;
  return { ...meta, version_no: v.version_no, version_precedente_attendue: precedente, activation_attendue: attendue };
}
function page(v: unknown, args: ArgumentsIndexDocumentsAffaireM10): IndexDocumentsAffaireM10 | undefined {
  if (!ferme(v, INDEX) || v.version_schema !== 1 || v.affaire_id !== args.affaire_id ||
    v.decalage !== args.decalage || v.limite !== args.limite || !entier(v.total_versions, 0, 64) ||
    !Array.isArray(v.versions) || v.versions.length !== Math.min(args.limite, Math.max(0, v.total_versions - args.decalage)) ||
    v.suivant_decalage !== (args.decalage + args.limite < v.total_versions ? args.decalage + args.limite : null)) return undefined;
  const rows: LigneIndexDocumentM10[] = [], docs = new Map<string, LigneIndexDocumentM10>();
  const refs: (ReferenceDocumentM10 | null)[] = [], activations = new Set<string>();
  let index = -1;
  for (const raw of v.versions) {
    const row = ligne(raw);
    if (!row || row.affaire_id !== args.affaire_id || row.version_source.index <= index) return undefined;
    index = row.version_source.index;
    const ancienne = docs.get(row.document_ref.ligne_id);
    if (ancienne && (!egalRef(ancienne.version_precedente_attendue, row.version_precedente_attendue) ||
      !egalRef(ancienne.activation_attendue, row.activation_attendue) ||
      (ancienne.statut === "RETIREE") !== (row.statut === "RETIREE") || row.version_no <= ancienne.version_no)) return undefined;
    if (row.activation_ref !== null) {
      if (activations.has(row.activation_ref.ligne_id)) return undefined;
      activations.add(row.activation_ref.ligne_id);
    }
    docs.set(row.document_ref.ligne_id, row);
    refs.push(row.document_ref, row.version_source, row.activation_ref, row.version_precedente_attendue, row.activation_attendue);
    rows.push(row);
  }
  if (!refsCoherentes(refs)) return undefined;
  return { version_schema: 1, affaire_id: args.affaire_id, decalage: args.decalage, limite: args.limite,
    total_versions: v.total_versions, suivant_decalage: v.suivant_decalage as number | null, versions: rows };
}
function version(v: unknown, args: ArgumentsVersionDocumentAffaireM10): VersionDocumentAffaireM10 | undefined {
  if (!objet(v) || !ferme(v, v.statut === "RETIREE" ? META : [...META, "corps"])) return undefined;
  const meta = metadata(v);
  if (!meta || meta.affaire_id !== args.affaire_id || !egalRef(meta.document_ref, args.document_ref) ||
    !egalRef(meta.version_source, args.version_source)) return undefined;
  if (meta.statut === "RETIREE") return { ...meta, statut: "RETIREE" };
  if (!scalaire(v.corps)) return undefined;
  const octets = utf8ToBytes(v.corps);
  if ([...v.corps].length !== meta.taille_points || octets.length !== meta.taille_octets ||
    octets.length > 8000 || bytesToHex(sha256(octets)) !== meta.source_sha256) return undefined;
  return { ...meta, statut: meta.statut, corps: v.corps };
}
const illisible = <T>(): Reponse<T> => ({ ok: false, code: "reponse_illisible",
  detail: "Lecture documentaire illisible : aucune donnée partielle affichée." });
function lire<T>(brut: unknown, parser: (v: unknown) => T | undefined): Reponse<T> {
  const copie = copierJsonLecture(brut);
  if (copie === JSON_LECTURE_INVALIDE || !ferme(copie, ["ok", "resultat"]) || copie.ok !== true ||
    !ferme(copie.resultat, ["accepte", "resultat"]) || copie.resultat.accepte !== true) return illisible();
  const value = parser(copie.resultat.resultat);
  return value === undefined ? illisible() : { ok: true, value };
}
export function lireIndexDocumentsAffaireM10(brut: unknown, arguments3: unknown): Reponse<IndexDocumentsAffaireM10> {
  const args = argsIndex(copierJsonLecture(arguments3));
  return args ? lire(brut, v => page(v, args)) : illisible();
}
export function lireVersionDocumentAffaireM10(brut: unknown, arguments3: unknown): Reponse<VersionDocumentAffaireM10> {
  const args = argsVersion(copierJsonLecture(arguments3));
  return args ? lire(brut, v => version(v, args)) : illisible();
}
