import type { ResultatSection } from "../admin/lecture";
import type { CauseMeteo, CreneauMeteoIntervention, MeteoIntervention } from "../m4/meteoIntervention";
import type { PageDispatch } from "../m4/paginationDispatch";
import type { HeureRetard, RetardsIncidents } from "../m4/retardsIncidents";
import { abreger, formaterDateOuInstant, message, presenterSection } from "./adminCommun";
import type { Message, ParametresMessage, VueSection } from "./adminCommun";
import { texteSansChemin } from "./texteSur";

/** Modèles de vue purs du dispatch courant (T4.27-m). Les DTO ont déjà été lus
 * par les contrats natifs : aucun statut, âge, seuil ou prévision n'est recalculé.
 * Les textes serveur montrables restent littéraux ; aucun chemin ou commande
 * n'est transmis au rendu. Les identifiants entiers servent seulement de clés. */
export interface VueMeteoIntervention {
  readonly lignes: readonly Message[];
  readonly creneaux: readonly { readonly id: string; readonly lignes: readonly Message[]; readonly textes: readonly string[] }[];
  readonly textes: readonly string[];
}
export interface VueRetardsIncidents {
  readonly lignes: readonly Message[];
  readonly reports: readonly { readonly id: string; readonly lignes: readonly Message[] }[];
  readonly incidents: readonly { readonly id: string; readonly lignes: readonly Message[] }[];
  readonly textes: readonly string[];
}
export interface VuePageDispatch {
  readonly lignes: readonly Message[];
  /** Curseur opaque réellement fourni ; l'écran décide si sa session peut relire. */
  readonly curseurSuivant: string | null;
}

const masque = (): Message => message("admin.dispatch.texteMasque");
function messageSur(m: Message): Message {
  return Object.values(m.params ?? {}).some(v => typeof v === "string" && texteSansChemin(v) === null) ? masque() : m;
}
function ligne(cle: string, params?: ParametresMessage): Message {
  return messageSur(message(`admin.dispatch.${cle}`, params));
}
function texte(serveur: string, textes: string[], lignes: Message[], unitesMeteo = false): void {
  // La barre d'une unité météo est une donnée métier. Vérifier une copie sans
  // ces deux unités, puis conserver le texte original ; les autres chemins,
  // fichiers et commandes restent soumis au filtre partagé inchangé.
  const verification = unitesMeteo ? serveur.replace(/\b(km|mm)\/h\b/g, "$1 par heure") : serveur;
  if (texteSansChemin(verification) === null) lignes.push(masque());
  else if (serveur !== "") textes.push(serveur);
}
function cause(v: CauseMeteo | null | undefined, lignes: Message[], textes: string[]): void {
  if (!v) return;
  lignes.push(ligne("meteo.cause", { code: v.code }));
  texte(v.detail, textes, lignes, true);
}
function heureDuCreneau(minutes: number): string {
  // Mise en forme de minutes du serveur, sans date civile déduite du jour du plan.
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function presenterCreneau(v: CreneauMeteoIntervention, decalage: number): VueMeteoIntervention["creneaux"][number] {
  const lignes: Message[] = [
    ligne("meteo.creneau", { equipe: v.equipe, jour: v.jour, debut: heureDuCreneau(v.debut_min), fin: heureDuCreneau(v.fin_min) }),
    v.date === null ? ligne("meteo.dateAbsente") : ligne("meteo.date", { date: v.date }),
    v.service === null ? ligne("meteo.serviceAbsent") : ligne("meteo.service", { nom: v.service }),
    ligne(v.plan_perime ? "meteo.planPerime" : "meteo.planCourant"),
    ligne(`meteo.statuts.${v.statut}`),
  ];
  const textes: string[] = [];
  for (const regle of v.regles) {
    lignes.push(ligne("meteo.regle", { risque: regle.risque, statut: regle.statut }));
    texte(regle.detail, textes, lignes, true);
  }
  for (const risque of v.sans_objet ?? []) lignes.push(ligne("meteo.sansObjet", { risque }));
  for (const manque of v.a_configurer ?? []) lignes.push(ligne("meteo.aConfigurer", { manque }));
  cause(v.cause, lignes, textes);
  if (v.prevision === null) {
    // Une règle sans objet peut donner « ok » sans aucune prévision : ces faits
    // indépendants restent visibles et ne deviennent jamais une mesure nulle.
    lignes.push(ligne("meteo.previsionAbsente"));
  } else {
    const p = v.prevision;
    lignes.push(ligne("meteo.prevision", { source: p.source, date: formaterDateOuInstant(p.emise_le, decalage) }));
    lignes.push(ligne("meteo.heureType", { type: p.heure_type }));
    if (p.saisi_par !== undefined) lignes.push(ligne("meteo.saisiPar", { personne: p.saisi_par }));
    if (p.reference !== undefined) lignes.push(ligne("meteo.reference", { reference: p.reference }));
    if (p.licence !== undefined) lignes.push(ligne("meteo.licence", { licence: p.licence }));
    if (p.forfait !== undefined) lignes.push(ligne("meteo.forfait", { forfait: p.forfait }));
    if (p.collection !== undefined) lignes.push(ligne("meteo.collection", { collection: p.collection }));
    if (p.page_meteo !== undefined) lignes.push(ligne("meteo.pageMeteo", { page: p.page_meteo }));
  }
  return { id: v.intervention_id, lignes, textes };
}
function presenterMeteo(v: MeteoIntervention, decalage: number): VueMeteoIntervention {
  const lignes: Message[] = [
    ligne("meteo.intervention", { id: abreger(v.intervention_id) }), ligne(`meteo.statuts.${v.statut}`),
    v.plan_id === null ? ligne("meteo.planAbsent") : ligne("meteo.plan", { id: abreger(v.plan_id) }),
  ];
  const textes: string[] = [];
  cause(v.cause, lignes, textes);
  if (v.attributions.length === 0) lignes.push(ligne("meteo.attributionsAbsentes"));
  for (const attribution of v.attributions) lignes.push(ligne("meteo.attribution", attribution));
  return { lignes, creneaux: v.creneaux.map(c => presenterCreneau(c, decalage)), textes };
}

function depuis(v: HeureRetard, decalage: number): Message[] {
  return [
    ligne("retards.depuis", { date: formaterDateOuInstant(v.depuis, decalage) }),
    ligne(`retards.origine.${v.origine_heure}`),
    v.heures_ecoulees === null ? ligne("retards.heuresInconnues") : ligne("retards.heures", { heures: v.heures_ecoulees }),
  ];
}
function presenterRetards(v: RetardsIncidents, decalage: number): VueRetardsIncidents {
  const lignes: Message[] = [
    // Cette référence fournie par l'appelant fait foi : garder secondes et
    // fuseau natifs, sans la confondre avec une date de lecture locale.
    ligne("retards.referenceAppelant", { date: v.reference }),
    ligne("retards.seuil", { heures: v.seuil_blocage_heures }),
    ligne("retards.reports", { total: v.reports.total, affiches: v.reports.affiches, reste: v.reports.reste }),
  ];
  const omissions = (liste: RetardsIncidents["reports"] | RetardsIncidents["incidents"]) => {
    if (liste.total === 0) lignes.push(ligne("retards.vide"));
    if (liste.reste > 0) lignes.push(ligne("retards.omis", { nombre: liste.reste }));
    // `suite` décrit des outils pour un agent. Elle ne crée aucun geste mobile.
    if (liste.suite !== null) lignes.push(ligne("retards.suiteNonLue"));
  };
  omissions(v.reports);
  lignes.push(ligne("retards.incidents", {
    total: v.incidents.total, affiches: v.incidents.affiches, reste: v.incidents.reste, bloques: v.incidents.bloques,
  }));
  omissions(v.incidents);
  lignes.push(ligne("retards.nonMesurable"));
  const textes: string[] = [];
  texte(v.retard_sur_cedule.manque, textes, lignes);
  return {
    lignes, textes,
    reports: v.reports.liste.map(r => ({ id: r.intervention_id, lignes: [
      ligne("retards.report", { intervention: abreger(r.intervention_id), motif: r.motif }), ...depuis(r, decalage),
    ] })),
    incidents: v.incidents.liste.map(r => ({ id: r.demande_id, lignes: [
      ligne("retards.incident", { intervention: abreger(r.intervention_id), demande: abreger(r.demande_id), type: r.type_demande }),
      ...depuis(r, decalage), ligne(r.bloquee ? "retards.bloquee" : "retards.nonBloquee"),
    ] })),
  };
}

/** La provenance commune reste datée, cache/refus/absence distincts. Même les
 * métadonnées techniques mal formées ne transmettent pas de chemin au rendu. */
function sectionSure<T, C>(r: ResultatSection<T>, decalage: number, presenter: (v: T) => C): VueSection<C> {
  const v = presenterSection(r, decalage, presenter);
  if (v.genre === "contenu") return {
    ...v, lue: messageSur(v.lue), horsLigne: v.horsLigne === null ? null : messageSur(v.horsLigne),
  };
  const verdict = v.genre === "refus" ? v.verdict : v.raison;
  if (texteSansChemin(verdict.code) !== null) return v;
  const sur = { code: "", detail: texteSansChemin(verdict.detail) ?? "" };
  return v.genre === "refus" ? { genre: "refus", avis: masque(), verdict: sur } : { genre: "aucune", avis: masque(), raison: sur };
}
export function vueMeteo(r: ResultatSection<MeteoIntervention>, decalage: number): VueSection<VueMeteoIntervention> {
  return sectionSure(r, decalage, v => presenterMeteo(v, decalage));
}
export function vueRetards(r: ResultatSection<RetardsIncidents>, decalage: number): VueSection<VueRetardsIncidents> {
  return sectionSure(r, decalage, v => presenterRetards(v, decalage));
}
export function presenterPage(v: PageDispatch): VuePageDispatch {
  const p = v.page;
  const lignes: Message[] = [
    ligne("page.resume", { affichees: p.taille, total: p.total, reste: p.reste }), ligne("page.ordre"), ligne("page.courante"),
  ];
  if (p.borne_atteinte) lignes.push(ligne("page.borne"));
  if (v.illisibles > 0) lignes.push(ligne("page.illisibles", { nombre: v.illisibles }));
  return { lignes, curseurSuivant: p.curseur_suivant };
}
