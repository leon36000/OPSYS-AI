import { message } from "./adminCommun";
import type { Message } from "./adminCommun";
import { formaterQuantite } from "./quotes";
import type { LangueMontant } from "./quotes";
import { texteSansChemin } from "./texteSur";
import type { DisponibiliteStock, DigestStock } from "../m6/stock";

export interface GroupeStock {
  readonly titre: string | null;
  readonly lignes: readonly Message[];
  readonly detail: readonly Message[];
}
export interface VueDisponibiliteStock {
  readonly lignes: readonly Message[];
  readonly articles: readonly GroupeStock[];
  readonly reservations: readonly GroupeStock[];
}
export interface VueDigestStock {
  readonly lignes: readonly Message[];
  readonly variances: readonly GroupeStock[];
}
const sur = (v: string | null) => v === null ? null : texteSansChemin(v);
const quantite = (v: string, langue: LangueMontant) => formaterQuantite(v, langue) ?? v;
const negative = (v: string) => v.startsWith("-") && /[1-9]/.test(v);
const ref = (cle: string, valeur: string | null): Message => sur(valeur) === null
  ? message(`admin.stock.${cle}Inconnu`) : message(`admin.stock.${cle}`, { valeur: sur(valeur)! });

/** Présentation seule : nombres serveur, pas de total/stock physique/unités déduits localement. */
export function presenterDisponibilite(v: DisponibiliteStock, langue: LangueMontant): VueDisponibiliteStock {
  const lignes: Message[] = [message("admin.stock.physiqueNonFourni"), message("admin.stock.manquesHorsSelection")];
  if (v.tronque) lignes.push(message("admin.stock.articlesTronques"));
  if (v.reservations_tronquees) lignes.push(message("admin.stock.reservationsTronquees"));
  if (v.articles.length === 0) lignes.push(message("admin.stock.articlesVides"));
  if (v.reservations_actives.length === 0) lignes.push(message("admin.stock.reservationsVides"));
  return { lignes,
    articles: v.articles.map(a => ({ titre: sur(a.materiau_id),
      lignes: [
        message("admin.stock.disponible", { quantite: quantite(a.disponible, langue) }),
        message("admin.stock.enMain", { quantite: quantite(a.en_main, langue) }),
        message("admin.stock.reserve", { quantite: quantite(a.reserve, langue) }),
        message("admin.stock.uniteInconnue"),
        ...([a.stock_theorique, a.hors_main, a.en_main, a.reserve, a.disponible].some(negative)
          ? [message("admin.stock.negatif")] : []),
      ],
      detail: [
        message("admin.stock.theorique", { quantite: quantite(a.stock_theorique, langue) }),
        message("admin.stock.horsMain", { quantite: quantite(a.hors_main, langue) }),
        ...Object.entries(a.par_emplacement).map(([nom, valeur]) => sur(nom) === null
          ? message("admin.stock.emplacementInconnu", { quantite: quantite(valeur, langue) })
          : message("admin.stock.emplacement", { nom: sur(nom)!, quantite: quantite(valeur, langue) })),
      ],
    })),
    reservations: v.reservations_actives.map(r => ({ titre: sur(r.devis_id),
      lignes: [ref("chantier", r.chantier_id), message(`admin.stock.statuts.${r.statut}`)],
      detail: r.lignes_manquantes.flatMap(l => [
        ref("materiau", l.materiau_id),
        l.unite === null || sur(l.unite) === null ? message("admin.stock.uniteInconnue") : ref("unitePrevue", l.unite),
        message("admin.stock.besoin", { quantite: quantite(l.quantite_besoin, langue) }),
        message("admin.stock.reserve", { quantite: quantite(l.quantite_reservee, langue) }),
        message("admin.stock.manquant", { quantite: quantite(l.quantite_manquante, langue) }),
      ]),
    })),
  };
}

/** Le chargeur utilise lireDigestSansSeuils : aucun besoin d'achat déduit d'une liste vide. */
export function presenterDigest(v: DigestStock, langue: LangueMontant): VueDigestStock {
  const lignes = [message("admin.stock.historique"), message("admin.stock.seuilsNonFournis"),
    message("admin.stock.constats", { nombre: v.nb_variances_stock })];
  if (v.variances_significatives.length === 0) lignes.push(message("admin.stock.constatsVides"));
  return { lignes, variances: v.variances_significatives.map(x => ({ titre: sur(x.materiau_id),
    lignes: [ref("chantier", x.chantier_id),
      message(`admin.stock.verdicts.${x.verdict_variance}`),
      message("admin.stock.ecart", { quantite: quantite(String(x.ecart), langue) }),
      message("admin.stock.uniteInconnue")], detail: [],
  })) };
}
