import type { ReapprovisionnementM6 } from "../m6/reapprovisionnement";
import { message } from "./adminCommun";
import type { Message } from "./adminCommun";
import { texteSansChemin } from "./texteSur";

const msg = (cle: string, params?: Readonly<Record<string, string | number>>) => message(`admin.reapprovisionnement.${cle}`, params);
const champ = (cle: string, valeur: string | null): Message => {
  const texte = texteSansChemin(valeur);
  return texte === null || texte === "" ? msg("referenceInconnue") : msg(cle, { valeur: texte });
};
/** Les chiffres du serveur sont présentés tels quels, sans somme, conversion ou calcul de commande. */
export function presenterReapprovisionnementM6(v: ReapprovisionnementM6) {
  return {
    lignes: [msg("couverture"), msg("pagesCourantes"), msg("uniteInconnue"), msg("dateDistincte"),
      msg("page", { debut: v.pagination.decalage, affichees: v.pagination.affichees, total: v.pagination.total, reste: v.pagination.reste }),
      ...(v.articles.length === 0 ? [msg(v.pagination.total === 0 ? "aucunArticleConstate" : "aucunArticlePage")] : [])],
    sources: [msg("configuration"), msg("empreinteConfiguration", { empreinte: v.source_configuration.sha256 }),
      msg("empreintesSnapshots"),
      ...v.sources_registres.map(s => msg("source", { source: s.registre, lignes: s.lignes, empreinte: s.empreinte_snapshot })),
      msg("source", { source: "m4.travaux_termines", lignes: v.source_publications.evenements.lignes,
        empreinte: v.source_publications.evenements.empreinte_snapshot }),
      msg("source", { source: "wct_recus", lignes: v.source_publications.recus_m6.lignes,
        empreinte: v.source_publications.recus_m6.empreinte_snapshot })],
    articles: v.articles.map(a => ({ cle: a.materiau_id, titre: champ("article", a.materiau_id),
      lignes: [msg(`statuts.${a.statut}`), champ("stockTheorique", a.chiffres.stock_theorique),
        champ("horsMain", a.chiffres.hors_main), champ("enMain", a.chiffres.en_main), champ("reserve", a.chiffres.reserve),
        champ("disponible", a.chiffres.disponible),
        a.seuil_reapprovisionnement === null ? msg("seuilInconnu") : champ("seuil", a.seuil_reapprovisionnement),
        a.quantite_cible === null ? msg("cibleInconnue") : champ("cible", a.quantite_cible),
        a.quantite_a_commander === null ? msg(a.stock_negatif ? "propositionStockNegatif" : "propositionAbsente") : champ("proposition", a.quantite_a_commander),
        ...(a.stock_negatif ? [msg("stockNegatif")] : []),
        ...(a.code_configuration === null ? [] : [champ("codeConfiguration", a.code_configuration)]),
        a.unite_dernier_constat === null ? msg("uniteConstatInconnue") : champ("uniteConstat", a.unite_dernier_constat),
        msg("uniteConstatDistincte"), msg("aucunAchat")],
      sources: [champ("dateConstat", a.dernier_constat.horodatage), msg("dateDistincte"),
        champ("evenement", a.dernier_constat.reference_bus.evenement_id),
        a.dernier_constat.chantier_id === null ? msg("chantierInconnu") : champ("chantier", a.dernier_constat.chantier_id),
        msg("referenceConstat", { rang: a.dernier_constat.reference.rang, empreinte: a.dernier_constat.reference.empreinte_snapshot })],
    })),
  };
}
