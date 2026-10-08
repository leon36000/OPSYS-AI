import { estAffairePaquetM10Valide } from "../m10/paquetAffaire";
import type { FaitPaquetAffaireM10, PaquetAffaireM10 } from "../m10/paquetAffaire";
import type { ResultatSection } from "../admin/lecture";
import { message, presenterSection, formaterDateOuInstant } from "./adminCommun";
import type { Message, VueSection } from "./adminCommun";
import { texteSansChemin } from "./texteSur";

export interface FaitVuePaquetAffaireM10 {
  readonly titre: Message;
  readonly lignes: readonly Message[];
}
export interface CoucheVuePaquetAffaireM10 {
  readonly nom: string;
  readonly titre: Message;
  readonly lignes: readonly Message[];
  readonly faits: readonly FaitVuePaquetAffaireM10[];
}
export interface VuePaquetAffaireM10 {
  readonly lignes: readonly Message[];
  readonly etatAffaire: readonly Message[];
  readonly couches: readonly CoucheVuePaquetAffaireM10[];
  readonly confidentialite: readonly Message[];
  readonly signaux: readonly Message[];
  readonly consolidation: readonly Message[];
}
const prefixe = "admin.paquetAffaire.";
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
function referenceAffaire(cle: string, affaire: string, autres: Readonly<Record<string, string>> = {}): Message {
  // Exception locale : seul l'identifiant d'affaire validé par le motif natif fermé conserve ~opp~.
  // Pas de découpage, de navigation ni d'élargissement du filtre partagé.
  if (!estAffairePaquetM10Valide(affaire)) return msg("detailMasque");
  for (const valeur of Object.values(autres)) if (texteSansChemin(valeur) === null) return msg("detailMasque");
  return msg(cle, { affaire, ...autres });
}
const sources: Readonly<Record<string, string>> = {
  "m10:decision": "sourceDecision", "m10:consolidation": "sourceConsolidation",
  "m1.lead_qualifie": "sourceLeadQualifie", "m2.client_associe": "sourceClientAssocie",
  "m3.devis_envoye": "sourceDevisEnvoye", "m3.devis_accepte": "sourceDevisAccepte",
  "m3.devis_sans_reponse": "sourceDevisSansReponse", "m4.travaux_termines": "sourceWct",
  "m6.variance_chantier": "sourceVariance", "inconnu": "sourceInconnue",
};
function source(valeur: string): Message {
  return Object.hasOwn(sources, valeur) ? msg(sources[valeur]) : champs("source", { source: valeur });
}
const titres: Readonly<Record<string, string>> = {
  regles_entreprise: "coucheRegles", faits_affaire: "coucheFaits",
  evenements_recents: "coucheEvenements", signaux_non_resolus: "coucheSignaux",
};
function presenterFait(f: FaitPaquetAffaireM10, decalage: number): FaitVuePaquetAffaireM10 {
  const lignes: Message[] = [source(f.source), champs("horodatage", { date: formaterDateOuInstant(f.horodatage, decalage) }),
    champs("resume", { resume: f.resume }), champs("niveau", { niveau: f.confidentialite })];
  if ("etat" in f) {
    lignes.push(champs("etatSignal", { etat: f.etat }));
    lignes.push(f.traite_par === null || f.traite_le === null ? msg("traitementInconnu") :
      champs("traitement", { personne: f.traite_par, date: formaterDateOuInstant(f.traite_le, decalage) }));
  }
  return { titre: champs("fait", { id: f.identifiant }), lignes };
}

/** Lecture du paquet déjà filtré par le contrat appareil : aucune somme, décision, consolidation ou autorisation. */
export function presenterPaquetAffaire(v: PaquetAffaireM10, decalage: number): VuePaquetAffaireM10 {
  return {
    lignes: [referenceAffaire("identification", v.affaire_id),
      champs("horodatage", { date: formaterDateOuInstant(v.horodatage, decalage) }), msg("provenancePaquet"),
      msg("budgetFaits", { budget: v.budget_caracteres, utilises: v.caracteres_utilises }),
      msg("budgetCadreExclu"), msg("paquetPartiel")],
    etatAffaire: [msg(v.affaire.connue ? "connue" : "inconnue"),
      msg(v.affaire.origine_recue ? "origineRecue" : "origineManquante"),
      v.affaire.origine === null ? msg("origineInconnue") : champs("origine", { origine: v.affaire.origine }),
      ...(v.affaire.verdict === null ? [] : [champs("verdict", { code: v.affaire.verdict })])],
    couches: v.couches.map(c => ({ nom: c.nom,
      titre: Object.hasOwn(titres, c.nom) ? msg(titres[c.nom]) : msg("detailMasque"),
      lignes: [msg(c.vide ? "coucheVide" : "coucheAvecFaits"), msg(c.tronque ? "coucheTronquee" : "coucheNonTronquee"),
        msg("coucheComptes", { total: c.nb_total, inclus: c.nb_inclus, omis: c.nb_omis }),
        msg("coucheCaracteres", { caracteres: c.caracteres })],
      faits: c.faits.map(f => presenterFait(f, decalage)) })),
    confidentialite: [msg("vueRestrictive"), msg("confidentialite", { regle: v.confidentialite.regle, retenus: v.confidentialite.nb_retenus })],
    signaux: [msg("signaux", { ouverts: v.signaux.nb_ouverts, pris: v.signaux.nb_pris_en_compte, clos: v.signaux.nb_clos })],
    consolidation: [msg("consolidationTotal", { nombre: v.consolidation.nb_a_consolider }),
      ...(v.consolidation.a_consolider.length === 0 ? [msg("aucuneConsolidationListee")] :
        v.consolidation.a_consolider.map(j => referenceAffaire("consolidationJour", j.affaire_id, { jour: formaterDateOuInstant(j.jour, decalage) }))),
      msg("consolidationInformative")],
  };
}
export function vuePaquetAffaire(
  resultat: ResultatSection<PaquetAffaireM10>, decalage: number,
): VueSection<VuePaquetAffaireM10> {
  return presenterSection(resultat, decalage, v => presenterPaquetAffaire(v, decalage));
}
