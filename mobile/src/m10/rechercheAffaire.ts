import { ouvrirEnveloppe } from "../admin/enveloppe";
import { estObjet } from "../admin/lecteurs";
import type { Reponse } from "../m7/contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { horodatageM10Valide } from "./contrat";
import { estAffairePaquetM10Valide } from "./paquetAffaire";
export type { Reponse } from "../m7/contrat";

export const OUTIL_RECHERCHE_AFFAIRE = "m10_rechercher_affaire_appareil";
export interface ArgumentsRechercheAffaireM10 {
  readonly affaire_id: string; readonly requete: string; readonly decalage: number; readonly limite: number;
}
export interface ReferenceRechercheAffaireM10 {
  readonly ligne_id: string; readonly registre: "evenements" | "affaires"; readonly hash_tete: string;
}
export interface LigneRechercheAffaireM10 {
  readonly genre: "evenement" | "fait_consolide"; readonly affaire_id: string; readonly identifiant: string;
  readonly horodatage: string; readonly source: string; readonly resume: string;
  readonly confidentialite: "PUBLIC_INTERNAL" | "INTERNAL"; readonly reference: ReferenceRechercheAffaireM10;
}
export type ResultatRechercheAffaireM10 = LigneRechercheAffaireM10;
export interface SituationRechercheAffaireM10 {
  readonly connue: boolean; readonly origine_recue: boolean; readonly origine: string | null; readonly verdict: string | null;
}
export interface PaginationRechercheAffaireM10 {
  readonly decalage: number; readonly limite: number; readonly affichees: number; readonly total: number;
  readonly suivant: number | null; readonly reste: number; readonly courante: true;
}
const HORS_CORPUS = Object.freeze(["decisions_globales", "revisions", "signaux_traitements", "developpement", "documents_generiques"] as const);
const NIVEAUX = Object.freeze(["PUBLIC_INTERNAL", "INTERNAL"] as const);
export interface RechercheAffaireM10 {
  readonly affaire_id: string; readonly requete: string;
  readonly mode: "litteral_nfc_casefold_v1"; readonly corpus: "evenements_et_consolidations_affaire_v1";
  readonly resultats: readonly LigneRechercheAffaireM10[]; readonly affaire: SituationRechercheAffaireM10;
  readonly pagination: PaginationRechercheAffaireM10;
  readonly couverture: {
    readonly projections: "resume_200_caracteres"; readonly sources_parcourues: "completes";
    readonly historique_consolidations: "derniere_version_par_cle"; readonly hors_corpus: typeof HORS_CORPUS;
    readonly plafond_lignes: 10000;
  };
  readonly confidentialite: { readonly agent: null; readonly regle: "v1"; readonly niveaux: typeof NIVEAUX };
  readonly borne_caracteres: 5400; readonly taille_caracteres: number;
}
const SOURCES_EVENEMENTS = ["m1.lead_qualifie", "m2.client_associe", "m3.devis_envoye", "m3.devis_accepte", "m3.devis_sans_reponse", "m4.travaux_termines", "m6.variance_chantier"] as const;
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const texte = (v: unknown): v is string => typeof v === "string" && v.trim() !== "" && !/[\p{Cc}\p{Cs}]/u.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && v.length === 64 && /^[0-9a-f]{64}$/.test(v);
const ferme = (v: Record<string, unknown>, ks: readonly string[]) => Object.keys(v).length === ks.length && ks.every(k => Object.hasOwn(v, k));
const listeExacte = (v: unknown, attendue: readonly string[]) => Array.isArray(v) && v.length === attendue.length && v.every((x, i) => x === attendue[i]);
function requeteValide(v: unknown): v is string {
  return typeof v === "string" && v === v.normalize("NFC") && Array.from(v).length <= 200 && !/[\p{Cc}\p{Cs}]/u.test(v);
}
function argumentsValides(v: unknown): v is ArgumentsRechercheAffaireM10 {
  return estObjet(v) && ferme(v, ["affaire_id", "requete", "decalage", "limite"]) && estAffairePaquetM10Valide(v.affaire_id) &&
    requeteValide(v.requete) && entier(v.decalage) && v.decalage <= 10000 && entier(v.limite) && v.limite >= 1 && v.limite <= 8;
}
export function construireArgumentsRechercheAffaire(affaireId: string, requete: string, decalage = 0, limite = 8): ArgumentsRechercheAffaireM10 {
  if (typeof requete !== "string") throw new Error("Arguments de recherche d'affaire invalides.");
  const args = { affaire_id: affaireId, requete: requete.normalize("NFC"), decalage, limite };
  if (!argumentsValides(args)) throw new Error("Arguments de recherche d'affaire invalides.");
  return args;
}
const illisible = (): Reponse<RechercheAffaireM10> => ({ ok: false, code: "reponse_illisible", detail: "Recherche d'affaire illisible : aucun résultat partiel affiché." });
function ligne(v: unknown, affaireId: string): LigneRechercheAffaireM10 | null {
  if (!estObjet(v) || !ferme(v, ["genre", "affaire_id", "identifiant", "horodatage", "source", "resume", "confidentialite", "reference"]) ||
    (v.genre !== "evenement" && v.genre !== "fait_consolide") || v.affaire_id !== affaireId || !texte(v.identifiant) ||
    !horodatageM10Valide(v.horodatage) || typeof v.source !== "string" || typeof v.resume !== "string" || Array.from(v.resume).length > 200 ||
    (v.confidentialite !== "PUBLIC_INTERNAL" && v.confidentialite !== "INTERNAL") || !estObjet(v.reference) ||
    !ferme(v.reference, ["ligne_id", "registre", "hash_tete"]) || !hash(v.reference.ligne_id) || v.reference.hash_tete !== v.reference.ligne_id) return null;
  if (v.genre === "evenement" ? v.reference.registre !== "evenements" || !SOURCES_EVENEMENTS.some(s => s === v.source) :
    v.reference.registre !== "affaires" || v.source !== "m10:consolidation" || v.identifiant !== v.reference.ligne_id) return null;
  const registre = v.reference.registre;
  if (registre !== "evenements" && registre !== "affaires") return null;
  return { genre: v.genre, affaire_id: affaireId, identifiant: v.identifiant, horodatage: v.horodatage, source: v.source,
    resume: v.resume, confidentialite: v.confidentialite, reference: { ligne_id: v.reference.ligne_id, registre, hash_tete: v.reference.ligne_id } };
}
function situation(v: unknown, affaireId: string): SituationRechercheAffaireM10 | null {
  if (!estObjet(v) || !ferme(v, ["connue", "origine_recue", "origine", "verdict"]) || typeof v.connue !== "boolean" || typeof v.origine_recue !== "boolean") return null;
  if (!v.connue ? v.origine_recue || v.origine !== null || v.verdict !== "AMONT-AFFAIRE-INCONNUE" :
    !v.origine_recue ? v.origine !== null || v.verdict !== "AMONT-ORIGINE-NON-RECUE" :
      v.verdict !== null || v.origine !== (affaireId.includes("~opp~") ? "m2.client_associe" : "m1.lead_qualifie")) return null;
  const origine = v.origine, verdict = v.verdict;
  if (!(origine === null || typeof origine === "string") || !(verdict === null || typeof verdict === "string")) return null;
  return { connue: v.connue, origine_recue: v.origine_recue, origine, verdict };
}
/** DIRECT entier, lié aux quatre arguments. Compteurs natifs validés ; aucune taille JSON, date ou valeur recalculée. */
export function lireRechercheAffaire(brut: unknown, args: ArgumentsRechercheAffaireM10): Reponse<RechercheAffaireM10> {
  const argumentsCopies = copierJsonLecture(args);
  if (argumentsCopies === JSON_LECTURE_INVALIDE || !argumentsValides(argumentsCopies)) return illisible();
  const copie = copierJsonLecture(brut);
  if (copie === JSON_LECTURE_INVALIDE || !estObjet(copie)) return illisible();
  const metier = estObjet(copie.resultat) ? copie.resultat : null;
  if (metier?.accepte === false) {
    if (!estObjet(metier.verdict) || !ferme(metier.verdict, ["code", "detail"]) || !texte(metier.verdict.code) || typeof metier.verdict.detail !== "string") return illisible();
    return { ok: false, code: metier.verdict.code, detail: metier.verdict.detail };
  }
  if (copie.ok === false && (!texte(copie.erreur) || (typeof copie.details !== "string" && !(Array.isArray(copie.details) && copie.details.every(x => typeof x === "string"))))) return illisible();
  const ouverte = ouvrirEnveloppe(copie, "directe");
  if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  if (!ferme(copie, ["ok", "resultat"])) return illisible();
  const v = ouverte.valeur, a = argumentsCopies;
  if (!estObjet(v) || !ferme(v, ["affaire_id", "requete", "mode", "corpus", "resultats", "affaire", "pagination", "couverture", "confidentialite", "borne_caracteres", "taille_caracteres"]) ||
    v.affaire_id !== a.affaire_id || v.requete !== a.requete || v.mode !== "litteral_nfc_casefold_v1" || v.corpus !== "evenements_et_consolidations_affaire_v1" ||
    v.borne_caracteres !== 5400 || !entier(v.taille_caracteres) || v.taille_caracteres < 1 || v.taille_caracteres > 5400 || !Array.isArray(v.resultats) ||
    !estObjet(v.couverture) || !ferme(v.couverture, ["projections", "sources_parcourues", "historique_consolidations", "hors_corpus", "plafond_lignes"]) ||
    v.couverture.projections !== "resume_200_caracteres" || v.couverture.sources_parcourues !== "completes" ||
    v.couverture.historique_consolidations !== "derniere_version_par_cle" || !listeExacte(v.couverture.hors_corpus, HORS_CORPUS) || v.couverture.plafond_lignes !== 10000 ||
    !estObjet(v.confidentialite) || !ferme(v.confidentialite, ["agent", "regle", "niveaux"]) || v.confidentialite.agent !== null ||
    v.confidentialite.regle !== "v1" || !listeExacte(v.confidentialite.niveaux, NIVEAUX) || !estObjet(v.pagination) ||
    !ferme(v.pagination, ["decalage", "limite", "affichees", "total", "suivant", "reste", "courante"])) return illisible();
  const p = v.pagination;
  if (p.decalage !== a.decalage || p.limite !== a.limite || p.courante !== true || !entier(p.affichees) || p.affichees > a.limite ||
    p.affichees !== v.resultats.length || !(p.suivant === null || entier(p.suivant)) || !entier(p.total) || p.total > 10000 || !entier(p.reste)) return illisible();
  const suivant = p.suivant;
  const reste = Math.max(0, p.total - a.decalage - p.affichees);
  if (p.affichees > Math.max(0, p.total - a.decalage) || (a.decalage < p.total && p.affichees === 0) ||
    p.reste !== reste || p.suivant !== (reste > 0 ? a.decalage + p.affichees : null)) return illisible();
  const resultats: LigneRechercheAffaireM10[] = [];
  const refs = new Set<string>();
  for (const brutLigne of v.resultats) {
    const l = ligne(brutLigne, a.affaire_id);
    if (!l || refs.has(`${l.genre}:${l.reference.ligne_id}`)) return illisible();
    refs.add(`${l.genre}:${l.reference.ligne_id}`); resultats.push(l);
  }
  const affaire = situation(v.affaire, a.affaire_id);
  if (!affaire || (!affaire.connue && p.total > 0)) return illisible();
  return { ok: true, value: { affaire_id: a.affaire_id, requete: a.requete, mode: "litteral_nfc_casefold_v1", corpus: "evenements_et_consolidations_affaire_v1", resultats, affaire,
    pagination: { decalage: a.decalage, limite: a.limite, affichees: p.affichees, total: p.total, suivant, reste: p.reste, courante: true },
    couverture: { projections: "resume_200_caracteres", sources_parcourues: "completes", historique_consolidations: "derniere_version_par_cle", hors_corpus: HORS_CORPUS, plafond_lignes: 10000 },
    confidentialite: { agent: null, regle: "v1", niveaux: NIVEAUX }, borne_caracteres: 5400, taille_caracteres: v.taille_caracteres } };
}
