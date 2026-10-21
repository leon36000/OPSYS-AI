import { estDecimal, estObjet, lireListe, listeDeTextes, texteOuNull } from "../admin/lecteurs";
import { horodatageM10Valide } from "../m10/contrat";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";

export const OUTIL_LECTURE_STRATEGIQUE = "m9_produire_lecture_strategique";
export interface LectureChantierM9 {
  readonly metric_id: string;
  readonly version_definition: string;
  readonly evenement_id: string;
  readonly chantier: string;
  readonly valeur: string;
  readonly unite: string;
  readonly sens: "au_dessus" | "au_dessous";
  readonly seuil: string;
  readonly regle: string;
  readonly a_qui: string;
  readonly action_proposee_par_m8: string | null;
  readonly source: string;
  readonly statut_decision: "en_attente_du_proprietaire";
}
export interface AgregatMetriqueM9 {
  readonly metric_id: string;
  readonly nb_alertes: number;
  readonly nb_chantiers: number;
  readonly a_qui: readonly string[];
}
export interface LectureStrategiqueM9 {
  readonly type: "LECTURE_STRATEGIQUE_M8";
  readonly jour: string;
  readonly periode: { readonly du: string; readonly au: string };
  readonly source: string;
  readonly resume: string;
  readonly decision: { readonly prise_par_m9: false; readonly a_prendre_par: string; readonly requise: boolean };
  readonly preuves_m8: readonly string[];
  readonly par_metrique: readonly AgregatMetriqueM9[];
  readonly manques: { readonly seuils_a_configurer: readonly string[]; readonly alertes_de_qualite_non_relues: number };
  readonly lectures: readonly LectureChantierM9[];
  readonly affichage: {
    readonly borne_caracteres: number;
    readonly taille_caracteres: number;
    readonly n_lectures: number;
    readonly depart: number;
    readonly affichees: number;
    readonly reste: number;
    readonly prochain_depart: number | null;
    readonly message: string | null;
  };
}
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const texte = (v: unknown): v is string => texteOuNull(v) !== null;
const texteNullable = (v: unknown): v is string | null => v === null || texte(v);
function ferme(v: Record<string, unknown>, cles: readonly string[]): boolean {
  return Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
}
function textesUniques(v: unknown): readonly string[] | null {
  const l = listeDeTextes(v);
  return l && new Set(l).size === l.length ? l : null;
}
function listeStricte<T>(v: unknown, lecteur: (v: unknown) => T | null): readonly T[] | null {
  const l = lireListe(v, lecteur);
  return l && l.illisibles === 0 ? l.items : null;
}
function jour(v: unknown): v is string {
  return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && horodatageM10Valide(`${v}T00:00:00Z`);
}
function reference(v: unknown): v is string {
  return typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v) && horodatageM10Valide(v);
}
/** Référence explicite avec fuseau : jamais l'horloge ni un jour reconstruit en UTC. */
export function construireArgumentsLectureStrategique(maintenant: string, depart = 0): { maintenant: string; depart: number } {
  if (!reference(maintenant) || !entier(depart)) throw new Error("Référence ISO avec fuseau ou départ M9 invalide.");
  return { maintenant, depart };
}
function preuve(v: unknown): LectureChantierM9 | null {
  if (!estObjet(v) || !ferme(v, ["metric_id", "version_definition", "evenement_id", "chantier", "valeur", "unite",
    "sens", "seuil", "regle", "a_qui", "action_proposee_par_m8", "source", "statut_decision"]) ||
    !texte(v.metric_id) || !texte(v.version_definition) || !/^[0-9a-f]{64}$/i.test(v.version_definition) ||
    !texte(v.evenement_id) || !texte(v.chantier) || !texte(v.valeur) || !estDecimal(v.valeur) || !/\.[0-9]{2}$/.test(v.valeur) ||
    !texte(v.unite) || (v.sens !== "au_dessus" && v.sens !== "au_dessous") ||
    !texte(v.seuil) || !estDecimal(v.seuil) || !/\.[0-9]{2}$/.test(v.seuil) || !texte(v.regle) || !texte(v.a_qui) ||
    !texteNullable(v.action_proposee_par_m8) || !texte(v.source) || v.statut_decision !== "en_attente_du_proprietaire") return null;
  return { metric_id: v.metric_id, version_definition: v.version_definition, evenement_id: v.evenement_id,
    chantier: v.chantier, valeur: v.valeur, unite: v.unite, sens: v.sens, seuil: v.seuil, regle: v.regle,
    a_qui: v.a_qui, action_proposee_par_m8: v.action_proposee_par_m8, source: v.source, statut_decision: v.statut_decision };
}
function groupe(v: unknown): AgregatMetriqueM9 | null {
  if (!estObjet(v) || !ferme(v, ["metric_id", "nb_alertes", "nb_chantiers", "a_qui"]) || !texte(v.metric_id) ||
    !entier(v.nb_alertes) || v.nb_alertes < 1 || !entier(v.nb_chantiers) || v.nb_chantiers < 1 || v.nb_chantiers > v.nb_alertes) return null;
  const destinataires = textesUniques(v.a_qui);
  return destinataires && destinataires.length > 0
    ? { metric_id: v.metric_id, nb_alertes: v.nb_alertes, nb_chantiers: v.nb_chantiers, a_qui: destinataires } : null;
}
/** DTO DIRECT de lecture_strategique.py : refus total si une preuve/page contredit son contrat.
 * Les agrégats, mesures, seuils, résumé et décision sont ceux du serveur, jamais recalculés pour l'affichage. */
export function lireLectureStrategique(brut: unknown, maintenant: string, depart: number): LectureStrategiqueM9 | null {
  if (!reference(maintenant) || !entier(depart)) return null;
  const v = copierJsonLecture(brut);
  if (v === JSON_LECTURE_INVALIDE || !estObjet(v) || !ferme(v, ["type", "jour", "periode", "source", "resume", "decision",
    "preuves_m8", "par_metrique", "manques", "lectures", "affichage"]) || v.type !== "LECTURE_STRATEGIQUE_M8" ||
    v.jour !== maintenant.slice(0, 10) || !jour(v.jour) || !estObjet(v.periode) || !ferme(v.periode, ["du", "au"]) ||
    !jour(v.periode.du) || v.periode.au !== v.jour || v.periode.du > v.jour || !texte(v.source) || !texte(v.resume) ||
    !estObjet(v.decision) || !ferme(v.decision, ["prise_par_m9", "a_prendre_par", "requise"]) ||
    v.decision.prise_par_m9 !== false || !texte(v.decision.a_prendre_par) || typeof v.decision.requise !== "boolean" ||
    !estObjet(v.manques) || !ferme(v.manques, ["seuils_a_configurer", "alertes_de_qualite_non_relues"]) ||
    !entier(v.manques.alertes_de_qualite_non_relues) || !estObjet(v.affichage) ||
    !ferme(v.affichage, ["borne_caracteres", "taille_caracteres", "n_lectures", "depart", "affichees", "reste", "prochain_depart", "message"])) return null;
  const preuves = textesUniques(v.preuves_m8), manques = textesUniques(v.manques.seuils_a_configurer);
  const groupes = listeStricte(v.par_metrique, groupe), lectures = listeStricte(v.lectures, preuve), a = v.affichage;
  if (!preuves || !manques || !groupes || !lectures || !entier(a.borne_caracteres) || a.borne_caracteres < 1 || a.borne_caracteres > 5900 ||
    !entier(a.taille_caracteres) || a.taille_caracteres < 1 || a.taille_caracteres > a.borne_caracteres ||
    !entier(a.n_lectures) || !entier(a.depart) || a.depart !== depart || depart > a.n_lectures ||
    !entier(a.affichees) || a.affichees !== lectures.length || a.affichees > a.n_lectures - depart ||
    !entier(a.reste) || a.reste !== a.n_lectures - depart - a.affichees ||
    !(a.prochain_depart === null || entier(a.prochain_depart)) || !texteNullable(a.message) ||
    (a.reste === 0 ? a.prochain_depart !== null || a.message !== null :
      a.affichees === 0 || a.prochain_depart !== depart + a.affichees || a.message === null) ||
    v.decision.requise !== (a.n_lectures > 0)) return null;
  // Borne de transport : le JSON compact est une borne inférieure du JSON espacé que Python compte.
  if (Array.from(JSON.stringify(v)).length > a.taille_caracteres) return null;
  const total = a.n_lectures;
  const parId = new Map(groupes.map(g => [g.metric_id, g]));
  if (parId.size !== groupes.length || preuves.length !== groupes.length || preuves.some(id => !parId.has(id)) ||
    (a.n_lectures === 0 ? groupes.length !== 0 : groupes.length === 0) ||
    groupes.some(g => g.nb_alertes > total) || new Set(lectures.map(l => l.evenement_id)).size !== lectures.length) return null;
  for (const l of lectures) {
    const g = parId.get(l.metric_id);
    if (!g || !g.a_qui.includes(l.a_qui)) return null;
  }
  // Cohérence des compteurs natifs, uniquement en validation ; aucun total n'est produit pour l'affichage.
  let resteCompte = total;
  for (const g of groupes) {
    if (g.nb_alertes > resteCompte) return null;
    resteCompte -= g.nb_alertes;
  }
  if (resteCompte !== 0) return null;
  // Témoins de la page seulement : un agrégat global ne peut annoncer moins que ce qui est visible.
  for (const g of groupes) {
    const visibles = lectures.filter(l => l.metric_id === g.metric_id);
    if (visibles.length > g.nb_alertes || new Set(visibles.map(l => l.chantier)).size > g.nb_chantiers) return null;
  }
  return { type: "LECTURE_STRATEGIQUE_M8", jour: v.jour, periode: { du: v.periode.du, au: v.periode.au }, source: v.source,
    resume: v.resume, decision: { prise_par_m9: false, a_prendre_par: v.decision.a_prendre_par, requise: v.decision.requise },
    preuves_m8: preuves, par_metrique: groupes, manques: { seuils_a_configurer: manques, alertes_de_qualite_non_relues: v.manques.alertes_de_qualite_non_relues },
    lectures, affichage: { borne_caracteres: a.borne_caracteres, taille_caracteres: a.taille_caracteres, n_lectures: a.n_lectures,
      depart: a.depart, affichees: a.affichees, reste: a.reste, prochain_depart: a.prochain_depart, message: a.message } };
}
