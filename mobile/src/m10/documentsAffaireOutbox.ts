import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { copierJsonLecture } from "../protocole/jsonLecture";
import { horodatageM10Valide } from "./contrat";
import { creerMutation, soumettreMutation, type HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox, TypeMutation } from "../outbox/types";
import type { InterpretationResultatMetier } from "../outbox/vidangeur";
import type { SessionEnvoi } from "../protocole/configuration";

export type OperationDocumentM10 = "deposer" | "activer" | "retirer";
export interface ReferenceDocumentM10 { readonly registre: "documents_affaire"; readonly index: number; readonly ligne_id: string }
export interface DepotDocumentM10 { readonly affaire_id: string; readonly document_ref: ReferenceDocumentM10 | null;
  readonly version_precedente: ReferenceDocumentM10 | null; readonly titre: string; readonly corps: string; readonly confidentialite: "INTERNAL" }
export interface ActivationDocumentM10 { readonly affaire_id: string; readonly document_ref: ReferenceDocumentM10;
  readonly version_source: ReferenceDocumentM10; readonly activation_attendue: ReferenceDocumentM10 | null }
export interface RetraitDocumentM10 { readonly affaire_id: string; readonly document_ref: ReferenceDocumentM10;
  readonly activation_attendue: ReferenceDocumentM10 | null; readonly code_motif: "RETRAIT_ACCES" }
export type CommandeDocumentM10 = DepotDocumentM10 | ActivationDocumentM10 | RetraitDocumentM10;
export interface AccuseDocumentM10 {
  readonly version_schema: 1; readonly operation: OperationDocumentM10; readonly document_ref: ReferenceDocumentM10;
  readonly reference: ReferenceDocumentM10; readonly version_source: ReferenceDocumentM10 | null; readonly source_sha256: string | null;
  readonly auteur: { readonly personne: string; readonly role: "admin"; readonly source: "appareil" };
  readonly intention: { readonly appareil: string; readonly cle: string; readonly outil: string; readonly empreinte_arguments: string };
  readonly horodatage_appareil_declare: string; readonly horodatage: string;
}
export const OUTILS_DOCUMENT_M10 = {
  deposer: "m10_deposer_version_document_appareil", activer: "m10_activer_version_document_appareil", retirer: "m10_retirer_document_appareil",
} as const;
const TYPES: Record<OperationDocumentM10, TypeMutation> = {
  deposer: "document_m10_depot", activer: "document_m10_activation", retirer: "document_m10_retrait",
};
const LOCAL = "_document_m10_local";
type Destination = Pick<SessionEnvoi, "personne" | "appareilId" | "urlBase">;
interface Locale { personne: string; appareil_id: string; url_base: string }
const objet = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const ferme = (v: unknown, ks: readonly string[]): v is Record<string, unknown> => objet(v) && Object.keys(v).length === ks.length && ks.every(k => Object.hasOwn(v,k));
const scalaire = (v: unknown): v is string => typeof v === "string" && !/[\p{Cs}]/u.test(v);
const nonVide = (v: unknown): v is string => scalaire(v) && /[^\p{White_Space}\u001c-\u001f]/u.test(v);
const texte = (v: unknown, n: number): v is string => nonVide(v) && [...v].length <= n;
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v) && v.length === 64;
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(v) && v.length === 36;
const personne = (v: unknown): v is string => typeof v === "string" && /^[a-z][a-z0-9_.-]{1,63}$/.test(v) && !/\s/.test(v);
const hora = (v: unknown): v is string => typeof v === "string" && v.length <= 40 && horodatageM10Valide(v);
const operation = (v: unknown): v is OperationDocumentM10 => v === "deposer" || v === "activer" || v === "retirer";
const affaire = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}(?:~opp~[A-Za-z0-9][A-Za-z0-9._:-]{0,127})?$/.test(v) && !/[^A-Za-z0-9._:~\-]/.test(v);
function reference(v: unknown): v is ReferenceDocumentM10 {
  return ferme(v,["registre","index","ligne_id"]) && v.registre === "documents_affaire" && typeof v.index === "number" &&
    Number.isSafeInteger(v.index) && v.index >= 0 && v.index <= 511 && hash(v.ligne_id);
}
const optionRef = (v: unknown): v is ReferenceDocumentM10 | null => v === null || reference(v);
function argumentsValides(op: OperationDocumentM10, v: unknown): v is CommandeDocumentM10 {
  if(op === "deposer") return ferme(v,["affaire_id","document_ref","version_precedente","titre","corps","confidentialite"]) && affaire(v.affaire_id) &&
    optionRef(v.document_ref) && optionRef(v.version_precedente) && (v.document_ref === null) === (v.version_precedente === null) &&
    texte(v.titre,120) && scalaire(v.corps) && [...v.corps].length > 0 && [...v.corps].length <= 2000 && utf8ToBytes(v.corps).length <= 8000 && v.confidentialite === "INTERNAL";
  if(!ferme(v,op === "activer" ? ["affaire_id","document_ref","version_source","activation_attendue"] : ["affaire_id","document_ref","activation_attendue","code_motif"]) ||
    !affaire(v.affaire_id) || !reference(v.document_ref) || !optionRef(v.activation_attendue)) return false;
  return op === "activer" ? reference(v.version_source) : v.code_motif === "RETRAIT_ACCES";
}
function destination(v: unknown): v is Locale {
  if(!ferme(v,["personne","appareil_id","url_base"]) || !personne(v.personne) || !texte(v.appareil_id,128) || typeof v.url_base !== "string") return false;
  try { const u=new URL(v.url_base);return ["http:","https:"].includes(u.protocol) && !u.username && !u.password && !u.search && !u.hash; } catch {return false;}
}
// Command keys are ASCII and values are strings/null/references with bounded integer indices.
function canonique(v: unknown): string {
  if(objet(v)) return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${canonique(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
const empreinte = (v: CommandeDocumentM10): string => bytesToHex(sha256(utf8ToBytes(canonique(v))));
const egalRef = (a: ReferenceDocumentM10 | null, b: ReferenceDocumentM10 | null): boolean => a === null ? b === null : b !== null && a.registre === b.registre && a.index === b.index && a.ligne_id === b.ligne_id;
export function creerMutationDocumentM10(op: OperationDocumentM10, commande: unknown, genererId: () => string, horloge: HorlogeAppareil, cible: Destination): MutationOutbox {
  const a=copierJsonLecture(commande), c=copierJsonLecture(cible);
  const locale=objet(c) ? {personne:c.personne,appareil_id:c.appareilId,url_base:c.urlBase} : null;
  if(!operation(op) || !argumentsValides(op,a) || !destination(locale) || !Number.isFinite(horloge.maintenant.getTime()) || !Number.isInteger(horloge.decalageMinutesUTC) || Math.abs(horloge.decalageMinutesUTC)>=1440) throw new Error("Intention documentaire invalide.");
  const m=creerMutation({type:TYPES[op],chantierId:`document-m10:${a.affaire_id}`,payload:{commande:a,[LOCAL]:locale}},genererId,horloge);
  if(!uuid(m.id) || !hora(m.createdAtLocal)) throw new Error("UUID ou heure documentaire invalide.");
  return {...soumettreMutation(m),proprietaire:locale.personne};
}
function charge(mutation: unknown): {op:OperationDocumentM10;args:CommandeDocumentM10;locale:Locale;id:string;heure:string} | null {
  const m=copierJsonLecture(mutation);
  if(!objet(m) || !uuid(m.id) || !hora(m.createdAtLocal) || !ferme(m.payload,["commande",LOCAL]) || !destination(m.payload[LOCAL])) return null;
  const op=(Object.keys(TYPES) as OperationDocumentM10[]).find(o=>TYPES[o]===m.type);
  const args=m.payload.commande,locale=m.payload[LOCAL];
  if(!op || !argumentsValides(op,args) || m.proprietaire!==locale.personne || m.chantierId!==`document-m10:${args.affaire_id}`) return null;
  return {op,args,locale,id:m.id,heure:m.createdAtLocal};
}
export function argumentsRpcDocumentM10(m: MutationOutbox): Readonly<Record<string, unknown>> | null { const c=charge(m);return c ? {...c.args} : null; }
export function verifierDestinationDocumentM10(m: MutationOutbox, session: Destination): boolean {
  const c=charge(m),s=copierJsonLecture(session);return !!c && objet(s) && c.locale.personne===s.personne && c.locale.appareil_id===s.appareilId && c.locale.url_base===s.urlBase;
}
const inconnue: InterpretationResultatMetier = {accepte:false,verdict:{code:"accuse_invalide",detail:"Confirmation documentaire inconnue : même intention conservée."}};
function accuse(brut: unknown, c: NonNullable<ReturnType<typeof charge>>): AccuseDocumentM10 | null {
  const a=copierJsonLecture(brut);
  if(!ferme(a,["version_schema","operation","document_ref","reference","version_source","source_sha256","auteur","intention","horodatage_appareil_declare","horodatage"]) || a.version_schema!==1 || a.operation!==c.op ||
    !reference(a.document_ref) || !reference(a.reference) || !optionRef(a.version_source) || !ferme(a.auteur,["personne","role","source"]) ||
    a.auteur.personne!==c.locale.personne || a.auteur.role!=="admin" || a.auteur.source!=="appareil" || !ferme(a.intention,["appareil","cle","outil","empreinte_arguments"]) ||
    a.intention.appareil!==c.locale.appareil_id || a.intention.cle!==c.id || a.intention.outil!==OUTILS_DOCUMENT_M10[c.op] || a.intention.empreinte_arguments!==empreinte(c.args) ||
    a.horodatage_appareil_declare!==c.heure || !hora(a.horodatage)) return null;
  if(c.op === "deposer") {
    const args=c.args as DepotDocumentM10;
    if(!egalRef(a.document_ref,args.document_ref ?? a.reference) || !egalRef(a.reference,a.version_source) || a.source_sha256!==bytesToHex(sha256(utf8ToBytes(args.corps)))) return null;
  } else {
    if(!egalRef(a.document_ref,c.args.document_ref)) return null;
    if(c.op === "activer") {if(!egalRef(a.version_source,(c.args as ActivationDocumentM10).version_source) || !hash(a.source_sha256)) return null;}
    else if(a.version_source!==null || a.source_sha256!==null) return null;
  }
  return a as unknown as AccuseDocumentM10;
}
export function interpreterDocumentM10(brut: unknown, mutation?: MutationOutbox): InterpretationResultatMetier {
  const c=charge(mutation),r=copierJsonLecture(brut);
  if(!c || !ferme(r,["ok","resultat","rejoue"]) || r.ok!==true || typeof r.rejoue!=="boolean" || !ferme(r.resultat,["accepte","resultat"]) || r.resultat.accepte!==true) return inconnue;
  const a=accuse(r.resultat.resultat,c);return a ? {accepte:true,resume:a} : inconnue;
}
export function validerRecuDocumentM10(mutation: MutationOutbox): boolean {
  const m=copierJsonLecture(mutation),c=charge(m);return objet(m) && m.statut==="envoyee" && !!c && accuse(m.resumeAccepte,c)!==null;
}
