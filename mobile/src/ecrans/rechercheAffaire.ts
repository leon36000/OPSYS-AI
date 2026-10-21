import type { RechercheAffaireM10 } from "../m10/rechercheAffaire";
import { estAffairePaquetM10Valide } from "../m10/paquetAffaire";
import { message } from "./adminCommun";
import type { Message } from "./adminCommun";
import { texteSansChemin } from "./texteSur";

const msg = (cle: string, params?: Readonly<Record<string, string | number>>) => message(`admin.rechercheAffaire.${cle}`, params);
const champ = (cle: string, nom: string, valeur: string): Message => {
  const texte = texteSansChemin(valeur);
  return texte === null ? msg("detailMasque") : texte === "" ? msg("texteVide") : msg(cle, { [nom]: texte });
};
/** Les nombres et instants viennent du producteur ; aucun score, âge ou montant n'est calculé. */
export function presenterRechercheAffaire(v: RechercheAffaireM10) {
  return {
    lignes: [estAffairePaquetM10Valide(v.affaire_id) ? msg("affaire", { affaire: v.affaire_id }) : msg("detailMasque"),
      msg("pagesCourantes"), msg("couverture"), msg("confidentialite"),
      msg("page", { debut: v.pagination.decalage, affichees: v.pagination.affichees, total: v.pagination.total, reste: v.pagination.reste }),
      msg(v.affaire.connue ? "connue" : "inconnue"), msg(v.affaire.origine_recue ? "origineRecue" : "origineManquante"),
      ...(v.resultats.length === 0 ? [msg("aucunResultat")] : [])],
    resultats: v.resultats.map(r => ({
      cle: `${r.genre}:${r.reference.ligne_id}`,
      lignes: [champ("identifiant", "id", r.identifiant), champ("source", "source", r.source),
        champ("date", "date", r.horodatage), champ("resume", "resume", r.resume),
        champ("niveau", "niveau", r.confidentialite),
        msg("reference", { registre: r.reference.registre, ligne: r.reference.ligne_id, tete: r.reference.hash_tete })],
    })),
  };
}
