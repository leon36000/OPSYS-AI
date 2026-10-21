import { ouvrirEnveloppe } from "../admin/enveloppe";
import { estObjet, lireListe, texteOuNull } from "../admin/lecteurs";
import type { Reponse } from "../m7/contrat";
import { horodatageM10Valide } from "./contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
export type { Reponse } from "../m7/contrat";

export const OUTIL_PAQUET_AFFAIRE = "m10_paquet_contexte_affaire";
export const COUCHES_PAQUET_AFFAIRE = ["regles_entreprise", "faits_affaire", "evenements_recents", "signaux_non_resolus"] as const;
export type NomCouchePaquetAffaireM10 = typeof COUCHES_PAQUET_AFFAIRE[number];
export interface FaitAffaireM10 {
  readonly identifiant: string; readonly horodatage: string; readonly source: string; readonly resume: string;
  readonly confidentialite: "PUBLIC_INTERNAL" | "INTERNAL";
}
export interface SignalPaquetAffaireM10 extends FaitAffaireM10 {
  readonly etat: "ouvert" | "pris_en_compte" | "clos";
  readonly traite_par: string | null; readonly traite_le: string | null;
}
export type FaitPaquetAffaireM10 = FaitAffaireM10 | SignalPaquetAffaireM10;
export interface CouchePaquetAffaireM10 {
  readonly nom: NomCouchePaquetAffaireM10; readonly vide: boolean; readonly tronque: boolean;
  readonly nb_total: number; readonly nb_inclus: number; readonly nb_omis: number; readonly caracteres: number;
  readonly faits: readonly FaitPaquetAffaireM10[];
}
export interface PaquetAffaireM10 {
  readonly affaire_id: string; readonly horodatage: string;
  readonly budget_caracteres: 4000; readonly caracteres_utilises: number;
  readonly couches: readonly CouchePaquetAffaireM10[];
  readonly signaux: { readonly nb_ouverts: number; readonly nb_pris_en_compte: number; readonly nb_clos: number };
  readonly confidentialite: { readonly agent: null; readonly regle: "v1"; readonly nb_retenus: number };
  readonly affaire: { readonly connue: boolean; readonly origine_recue: boolean; readonly origine: string | null; readonly verdict: string | null };
  readonly consolidation: { readonly a_consolider: readonly { readonly affaire_id: string; readonly jour: string }[]; readonly nb_a_consolider: number };
}
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const texte = (v: unknown): v is string => texteOuNull(v) !== null;
const ferme = (v: Record<string, unknown>, ks: readonly string[]) => Object.keys(v).length === ks.length && ks.every(k => Object.hasOwn(v, k));
const illisible = (): Reponse<PaquetAffaireM10> => ({ ok: false, code: "reponse_illisible", detail: "Paquet d'affaire illisible : aucun fait partiel affiché." });
/** Motif d'affaire.py, avec fin entière : le $ JavaScript seul accepterait un retour ligne final. */
export function estAffairePaquetM10Valide(v: unknown): v is string {
  return typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}(?:~opp~[A-Za-z0-9][A-Za-z0-9._:-]{0,127})?$/.exec(v)?.[0] === v;
}
function jour(v: unknown): v is string {
  return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && horodatageM10Valide(`${v}T00:00:00Z`);
}
export function construireArgumentsPaquetAffaire(affaireId: string, horodatage: string): { affaire_id: string; horodatage: string } {
  if (!estAffairePaquetM10Valide(affaireId) || !horodatageM10Valide(horodatage)) throw new Error("Affaire M10 ou horodatage avec fuseau invalide.");
  return { affaire_id: affaireId, horodatage };
}
function fait(v: unknown, signal: boolean): FaitPaquetAffaireM10 | null {
  const ks = ["identifiant", "horodatage", "source", "resume", "confidentialite"];
  if (!estObjet(v) || !ferme(v, signal ? [...ks, "etat", "traite_par", "traite_le"] : ks) || !texte(v.identifiant) ||
    !horodatageM10Valide(v.horodatage) || !texte(v.source) || typeof v.resume !== "string" || Array.from(v.resume).length > 200 ||
    (v.confidentialite !== "PUBLIC_INTERNAL" && v.confidentialite !== "INTERNAL")) return null;
  const base: FaitAffaireM10 = { identifiant: v.identifiant, horodatage: v.horodatage, source: v.source, resume: v.resume, confidentialite: v.confidentialite };
  if (!signal) return base;
  if (v.etat === "ouvert") {
    return v.traite_par === null && v.traite_le === null ? { ...base, etat: v.etat, traite_par: null, traite_le: null } : null;
  }
  if ((v.etat !== "pris_en_compte" && v.etat !== "clos") || !texte(v.traite_par) || !horodatageM10Valide(v.traite_le)) return null;
  return { ...base, etat: v.etat, traite_par: v.traite_par, traite_le: v.traite_le };
}
function couche(v: unknown, nom: NomCouchePaquetAffaireM10): CouchePaquetAffaireM10 | null {
  if (!estObjet(v) || !ferme(v, ["nom", "vide", "tronque", "nb_total", "nb_inclus", "nb_omis", "caracteres", "faits"]) || v.nom !== nom ||
    typeof v.vide !== "boolean" || typeof v.tronque !== "boolean" || !entier(v.nb_total) || !entier(v.nb_inclus) || v.nb_inclus > 5 || !entier(v.nb_omis) || !entier(v.caracteres) ||
    v.nb_inclus > v.nb_total || v.nb_total - v.nb_inclus !== v.nb_omis ||
    v.vide !== (v.nb_inclus === 0) || v.tronque !== (v.nb_omis > 0) ||
    (v.nb_total > 0 && v.nb_inclus === 0) || (v.nb_inclus === 0 ? v.caracteres !== 0 : v.caracteres === 0) ||
    (v.nb_inclus > 1 && v.caracteres > 1000)) return null;
  const lus = lireListe(v.faits, f => fait(f, nom === "signaux_non_resolus"));
  if (!lus || lus.illisibles !== 0 || lus.items.length !== v.nb_inclus || new Set(lus.items.map(f => `${f.source}\u0000${f.identifiant}`)).size !== lus.items.length) return null;
  return { nom, vide: v.vide, tronque: v.tronque, nb_total: v.nb_total, nb_inclus: v.nb_inclus, nb_omis: v.nb_omis, caracteres: v.caracteres, faits: lus.items };
}
/** Enveloppe DIRECTE entière. Aucun agent, fait confidentiel, défaut corrigé ou taille JSON calculée par le mobile. */
export function lirePaquetAffaire(brut: unknown, affaireId: string, horodatage: string): Reponse<PaquetAffaireM10> {
  if (!estAffairePaquetM10Valide(affaireId) || !horodatageM10Valide(horodatage)) return illisible();
  const copie = copierJsonLecture(brut);
  if (copie === JSON_LECTURE_INVALIDE || !estObjet(copie)) return illisible();
  const metier = estObjet(copie.resultat) ? copie.resultat : null;
  if (metier?.accepte === false) {
    if (!estObjet(metier.verdict) || !ferme(metier.verdict, ["code", "detail"]) || !texte(metier.verdict.code) || typeof metier.verdict.detail !== "string") return illisible();
    return { ok: false, code: metier.verdict.code, detail: metier.verdict.detail };
  }
  if (copie.ok === false && (!texte(copie.erreur) || (typeof copie.details !== "string" && !(Array.isArray(copie.details) && copie.details.every(d => typeof d === "string"))))) return illisible();
  const ouverte = ouvrirEnveloppe(copie, "directe");
  if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  if (!ferme(copie, ["ok", "resultat"])) return illisible();
  const v = ouverte.valeur;
  if (!estObjet(v) || !ferme(v, ["affaire_id", "horodatage", "budget_caracteres", "caracteres_utilises", "couches", "signaux", "confidentialite", "affaire", "consolidation"]) ||
    v.affaire_id !== affaireId || v.horodatage !== horodatage || v.budget_caracteres !== 4000 || !entier(v.caracteres_utilises) ||
    !Array.isArray(v.couches) || v.couches.length !== 4 || !estObjet(v.signaux) || !ferme(v.signaux, ["nb_ouverts", "nb_pris_en_compte", "nb_clos"]) ||
    !entier(v.signaux.nb_ouverts) || !entier(v.signaux.nb_pris_en_compte) || !entier(v.signaux.nb_clos) ||
    !estObjet(v.confidentialite) || !ferme(v.confidentialite, ["agent", "regle", "nb_retenus"]) || v.confidentialite.agent !== null ||
    v.confidentialite.regle !== "v1" || !entier(v.confidentialite.nb_retenus) ||
    !estObjet(v.affaire) || !ferme(v.affaire, ["connue", "origine_recue", "origine", "verdict"]) || typeof v.affaire.connue !== "boolean" || typeof v.affaire.origine_recue !== "boolean" ||
    !estObjet(v.consolidation) || !ferme(v.consolidation, ["a_consolider", "nb_a_consolider"]) || !entier(v.consolidation.nb_a_consolider) || !Array.isArray(v.consolidation.a_consolider)) return illisible();
  const couches: CouchePaquetAffaireM10[] = [];
  let restants = v.caracteres_utilises;
  for (let i = 0; i < 4; i++) {
    const c = couche(v.couches[i], COUCHES_PAQUET_AFFAIRE[i]);
    if (!c || c.caracteres > restants) return illisible();
    restants -= c.caracteres; couches.push(c);
  }
  if (restants !== 0) return illisible(); // validation des compteurs fournis, jamais mesure des faits/JSON
  const a = v.affaire;
  const connue = a.connue, origineRecue = a.origine_recue;
  if (typeof connue !== "boolean" || typeof origineRecue !== "boolean") return illisible();
  for (const [etat, total] of [["ouvert", v.signaux.nb_ouverts], ["pris_en_compte", v.signaux.nb_pris_en_compte], ["clos", v.signaux.nb_clos]] as const) {
    if (couches[3].faits.filter(f => "etat" in f && f.etat === etat).length > total) return illisible();
  }
  if (!a.connue ? a.origine_recue || a.origine !== null || a.verdict !== "AMONT-AFFAIRE-INCONNUE" :
    !a.origine_recue ? a.origine !== null || a.verdict !== "AMONT-ORIGINE-NON-RECUE" :
      a.verdict !== null || a.origine !== (affaireId.includes("~opp~") ? "m2.client_associe" : "m1.lead_qualifie")) return illisible();
  const origine = a.origine, verdict = a.verdict;
  if (!(origine === null || typeof origine === "string") || !(verdict === null || typeof verdict === "string")) return illisible();
  const jours: { affaire_id: string; jour: string }[] = [];
  if (v.consolidation.nb_a_consolider > couches[2].nb_omis) return illisible();
  if (v.consolidation.a_consolider.length !== Math.min(10, v.consolidation.nb_a_consolider)) return illisible();
  for (const e of v.consolidation.a_consolider) {
    if (!estObjet(e) || !ferme(e, ["affaire_id", "jour"]) || e.affaire_id !== affaireId || !jour(e.jour) || (jours.length > 0 && jours[jours.length - 1].jour >= e.jour)) return illisible();
    jours.push({ affaire_id: e.affaire_id, jour: e.jour });
  }
  return { ok: true, value: { affaire_id: affaireId, horodatage, budget_caracteres: 4000, caracteres_utilises: v.caracteres_utilises, couches,
    signaux: { nb_ouverts: v.signaux.nb_ouverts, nb_pris_en_compte: v.signaux.nb_pris_en_compte, nb_clos: v.signaux.nb_clos },
    confidentialite: { agent: null, regle: "v1", nb_retenus: v.confidentialite.nb_retenus },
    affaire: { connue, origine_recue: origineRecue, origine, verdict },
    consolidation: { a_consolider: jours, nb_a_consolider: v.consolidation.nb_a_consolider } } };
}
