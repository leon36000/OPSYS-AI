import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { lireVueExecutive, STATUT_MESURE_CALCULEE, STATUT_MESURE_NON_CALCULABLE } from "../m8/vueExecutive";
import type { CashLibreDeM8, DevisEnAttente } from "../m8/vueExecutive";

/** Ne garde que les valeurs du modèle validé. Une ligne illisible garde sa place dans le compte,
 * sous forme de null sans données. Aucun montant ni âge n'est recalculé. */
export function epurerVueExecutive(brut: unknown): unknown {
  const copie = copierJsonLecture(brut);
  if (copie === JSON_LECTURE_INVALIDE || typeof copie !== "object" || copie === null || Array.isArray(copie)) return null;
  const lue = lireVueExecutive(copie.resultat);
  if (lue === null) return null;
  const liste = <T,>(items: readonly T[], illisibles: number, projeter: (item: T) => unknown) =>
    [...items.map(projeter), ...Array.from({ length: illisibles }, () => null)];
  const devis = (d: DevisEnAttente) => ({ n: d.n, devis: d.devis, reste: d.reste });
  const statut = (calculee: boolean) => calculee ? STATUT_MESURE_CALCULEE : STATUT_MESURE_NON_CALCULABLE;
  const e = lue.entonnoir, m = lue.margeReelle, s = lue.stock;
  const vue = {
    vue: "executive", portee: lue.portee,
    entonnoir: {
      mesures: liste(e.mesures, e.mesuresIllisibles, v => ({ metric_id: v.metricId, nom: v.nom,
        valeur: v.valeur, unite: v.unite, statut: statut(v.calculee), proprietaire: v.proprietaire,
        ...(v.calculee ? {} : { manque: v.manque }) })),
      sources: liste(e.sources, e.sourcesIllisibles, v => ({ evenement: v.evenement, n: v.n, dernier_fait_le: v.dernierFaitLe })),
      devis_en_attente: { sans_reponse: devis(e.sansReponse), brouillons_en_retard: devis(e.brouillonsEnRetard) },
      seuils: { a_configurer: e.seuils.aConfigurer, invalides: e.seuils.invalides, ignores: e.seuils.ignores,
        configuration: e.seuils.configuration,
        evalues: liste(e.seuils.evalues, e.seuils.illisibles, v => ({ metric_id: v.metricId, statut: v.statut,
          valeur: v.valeur, unite: v.unite, sens: v.sens, seuil: v.seuil })) },
    },
    marge_reelle: { source: m.source, n_chantiers: m.nChantiers, n_marge_connue: m.nMargeConnue,
      n_non_calculable: m.nNonCalculable, reste: m.reste,
      chantiers: liste(m.chantiers, m.illisibles, v => ({ wct_id: v.wctId, devis_id: v.devisId,
        horodatage_completion: v.horodatageCompletion, marge_reelle_cad: v.margeReelleCad,
        statut: statut(v.margeReelleCad !== null), ...(v.margeReelleCad === null ? { raison: v.raison } : {}) })) },
    stock_a_commander: s.genre === "manque" ? { source: s.source, statut: "manque", manque: s.manque } : {
      source: s.source, statut: "lu", n_articles: s.nArticles, reste: s.reste, seuils_a_configurer: s.seuilsAConfigurer,
      articles: liste(s.articles, s.illisibles, v => ({ id: v.id, resume: v.resume, depuis: v.depuis, action_proposee: v.actionProposee })) },
    cash_libre: cashPourCache(lue.cashLibre),
    manques: liste(lue.manques, lue.manquesIllisibles, v => ({ champ: v.champ, source: v.source, raison: v.raison })),
  };
  const relue = lireVueExecutive(vue);
  return relue === null || JSON.stringify(relue) !== JSON.stringify(lue) ? null : { ok: true, resultat: vue };
}

function cashPourCache(cash: CashLibreDeM8): unknown {
  if (cash.genre === "inconnu") return { statut: cash.statut };
  if (cash.genre === "manque") return { statut: "manque", source: cash.source, manque: cash.manque, a_lire: cash.aLire };
  const c = cash.constat, a = cash.age;
  return { statut: "lu", source: cash.source, a_lire: cash.aLire, n_constats_recus: cash.nConstatsRecus,
    non_repris: cash.nonRepris,
    age: { jours: a.jours, aujourd_hui: a.aujourdHui, ...(a.raison === null ? {} : { raison: a.raison }) },
    constat: { sequence: c.sequence, date_reference: c.dateReference, statut: c.statut,
      cash_libre_cad: c.cashLibreCad, au_plus_cad: c.auPlusCad, en_deficit: c.enDeficit, lecture: c.lecture,
      manque: c.manque, reserves: c.reserves, mention: c.mention,
      ...(c.composantes === null ? { composantes_omises: c.composantesOmises } : { composantes: c.composantes }),
      ...(c.planchersCad === null ? {} : { planchers_cad: c.planchersCad }) } };
}
