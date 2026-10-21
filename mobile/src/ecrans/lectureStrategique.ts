import type { LectureStrategiqueM9 } from "../m9/lectureStrategique";
import type { ResultatSection } from "../admin/lecture";
import { message, presenterSection, formaterDateOuInstant } from "./adminCommun";
import type { Message, VueSection } from "./adminCommun";
import { texteSansChemin } from "./texteSur";

export interface GroupeLectureStrategiqueM9 {
  readonly titre: Message;
  readonly lignes: readonly Message[];
}
export interface VueLectureStrategiqueM9 {
  readonly lignes: readonly Message[];
  readonly preuves: readonly Message[];
  readonly metriques: readonly GroupeLectureStrategiqueM9[];
  readonly manques: readonly Message[];
  readonly lectures: readonly GroupeLectureStrategiqueM9[];
  readonly pagination: readonly Message[];
}
const prefixe = "admin.lectureStrategique.";
const msg = (cle: string, params?: Readonly<Record<string, string | number>>): Message => message(prefixe + cle, params);
function champs(cle: string, valeurs: Readonly<Record<string, string>>): Message {
  const surs: Record<string, string> = {};
  for (const [nom, valeur] of Object.entries(valeurs)) {
    const sur = texteSansChemin(valeur);
    if (sur === null) return msg("detailMasque");
    if (sur === "") return msg("texteVide");
    surs[nom] = sur;
  }
  return msg(cle, surs);
}
function source(valeur: string): Message {
  // Littéral fermé provenant de lecture_strategique.py. Aucun préfixe ni chemin arbitraire admis.
  return valeur === "m8.alerte_proposee (registre m09-strategic-intelligence/alertes_m8)"
    ? msg("sourceAlertesM8") : champs("source", { source: valeur });
}

/** Affiche les faits déjà cités par M9 : ni seuil réévalué, ni décision ou lien commercial déduit. */
export function presenterLectureStrategique(v: LectureStrategiqueM9, decalage: number): VueLectureStrategiqueM9 {
  return {
    lignes: [source(v.source), champs("jour", { jour: formaterDateOuInstant(v.jour, decalage) }),
      champs("periode", { du: formaterDateOuInstant(v.periode.du, decalage), au: formaterDateOuInstant(v.periode.au, decalage) }),
      champs("texte", { texte: v.resume }), msg("decisionNonPrise"),
      champs("decideur", { personne: v.decision.a_prendre_par }),
      msg(v.decision.requise ? "decisionRequise" : "decisionNonRequise")],
    preuves: v.preuves_m8.length === 0 ? [msg("aucunePreuve")] : v.preuves_m8.map(metrique => champs("preuve", { metrique })),
    metriques: v.par_metrique.map(m => ({ titre: champs("metrique", { metrique: m.metric_id }),
      lignes: [msg("agregat", { alertes: m.nb_alertes, chantiers: m.nb_chantiers }),
        ...m.a_qui.map(personne => champs("destinataire", { personne }))] })),
    manques: [...(v.manques.seuils_a_configurer.length === 0 ? [msg("aucunSeuilManquant")] :
      v.manques.seuils_a_configurer.map(metrique => champs("seuilAConfigurer", { metrique }))),
      msg("qualiteNonRelue", { nombre: v.manques.alertes_de_qualite_non_relues })],
    lectures: v.lectures.map(l => ({ titre: champs("metrique", { metrique: l.metric_id }), lignes: [
      champs("version", { version: l.version_definition }), champs("evenement", { id: l.evenement_id }),
      champs("chantier", { id: l.chantier }), champs("mesure", { valeur: l.valeur, unite: l.unite }),
      champs("seuil", { seuil: l.seuil, sens: l.sens }), champs("regle", { regle: l.regle }),
      champs("destinataire", { personne: l.a_qui }), source(l.source),
      l.action_proposee_par_m8 === null ? msg("actionAbsente") : champs("action", { action: l.action_proposee_par_m8 }),
      champs("statutDecision", { statut: l.statut_decision }),
    ] })),
    pagination: [msg("pagination", { total: v.affichage.n_lectures, depart: v.affichage.depart,
      affichees: v.affichage.affichees, reste: v.affichage.reste }),
      msg("borne", { borne: v.affichage.borne_caracteres, taille: v.affichage.taille_caracteres }),
      v.affichage.prochain_depart === null ? msg("finPage") : msg("prochain", { depart: v.affichage.prochain_depart }),
      ...(v.affichage.message === null ? [] : [champs("texte", { texte: v.affichage.message })]),
      msg("pageNonFigee")],
  };
}
export function vueLectureStrategique(
  resultat: ResultatSection<LectureStrategiqueM9>, decalage: number,
): VueSection<VueLectureStrategiqueM9> {
  return presenterSection(resultat, decalage, v => presenterLectureStrategique(v, decalage));
}
