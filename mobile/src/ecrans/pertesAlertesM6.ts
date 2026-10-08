import type { ListeWctPertesM6, PertesAlertesWctM6, WctPertesM6 } from "../m6/pertesAlertes";
import { message } from "./adminCommun";
import type { Message } from "./adminCommun";
import { texteSansChemin } from "./texteSur";

const msg = (cle: string, params?: Readonly<Record<string, string | number>>) => message(`admin.pertesAlertes.${cle}`, params);
const champ = (cle: string, valeur: string | null): Message => {
  const texte = texteSansChemin(valeur);
  return texte === null || texte === "" ? msg("referenceInconnue") : msg(cle, { valeur: texte });
};
const page = (p: ListeWctPertesM6["pagination"]) => msg("page", {
  debut: p.decalage, affichees: p.affichees, total: p.total, reste: p.reste,
});
export function presenterWctPertes(w: WctPertesM6) {
  return {
    titre: champ("wct", w.wct_id),
    lignes: [champ("intervention", w.intervention_id), w.devis_id === null ? msg("devisInconnu") : champ("devis", w.devis_id),
      champ("completion", w.horodatage_completion), msg("dateDistincte"), msg("sourcesWct"),
      msg("referenceRecu", { rang: w.reference_recu.rang, empreinte: w.reference_recu.empreinte_contenu })],
  };
}
export function presenterListeWctPertes(v: ListeWctPertesM6) {
  return { lignes: [msg("pagesCourantes"), msg("corpusListe"), page(v.pagination), ...(v.wcts.length === 0 ? [msg("aucunWctPage")] : [])],
    wcts: v.wcts.map(wct => ({ wct, ...presenterWctPertes(wct) })) };
}
/** Aucune quantité additionnée, unité empruntée, responsabilité déduite ou variance recalculée. */
export function presenterPertesAlertesWct(v: PertesAlertesWctM6) {
  const wct = presenterWctPertes(v.wct);
  return {
    lignes: [wct.titre, ...wct.lignes, v.chantier_id === null ? msg("chantierInconnu") : champ("chantier", v.chantier_id),
      msg(v.declaration_presente ? "declarationRecue" : "declarationNonRecue"), msg("declarationLimite"),
      msg("pagesCourantes"), page(v.pagination), msg("corpusDetail"), msg("horsCorpus"),
      ...(v.pertes_bris.length === 0 ? [msg(!v.declaration_presente ? "pertesNonDocumentees" :
        v.pagination.total === 0 ? "aucunePerteConnue" : "aucunePertePage")] : []),
      msg(v.evaluee_terminal ? "terminalPublie" : "terminalNonPublie"), msg("ordreHistorique")],
    mouvements: v.pertes_bris.map(m => ({ cle: m.reference.hash_maillon,
      lignes: [msg(m.type_mouvement === "PERTE" ? "perte" : "bris"), champ("article", m.materiau_id),
        champ("chantier", m.chantier_id), champ("quantite", m.quantite_signee), msg("uniteInconnue"), msg("dateInconnue"),
        msg("referenceMouvement", { index: m.reference.index, empreinte: m.reference.hash_maillon })] })),
    historique: v.historique_variance.map(slot => ({ cle: slot.statut,
      lignes: [msg(`statuts.${slot.statut}`), msg(slot.presente ? "publicationPresente" : "publicationAbsente"),
        ...(slot.publication ? [champ("evenement", slot.publication.reference_bus.evenement_id),
          slot.publication.chantier_id === null ? msg("chantierInconnu") : champ("chantier", slot.publication.chantier_id),
          msg(slot.publication.signal_critique === null ? "signalInconnu" : slot.publication.signal_critique ? "signalCritique" : "signalNonCritique"),
          slot.publication.seuil_pourcentage === null ? msg("seuilInconnu") : msg("seuil", { valeur: String(slot.publication.seuil_pourcentage) }),
          champ("completion", slot.publication.horodatage_completion), msg("datePublicationInconnue")] : [])] })),
  };
}
