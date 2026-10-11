import type { DepotOutbox } from "./depot";
import type { MutationOutbox, StatutMutation } from "./types";

/**
 * À qui appartient ce qui attend dans la file sortante (PLAN T1.4-l).
 *
 * Une mutation est créée sous UNE personne, celle que le serveur a confirmée pour l'appareil. Si
 * l'appareil est ensuite appairé pour quelqu'un d'autre, les mutations de la première personne ne
 * doivent jamais partir sous l'identité de la seconde : le serveur ne peut pas toujours le voir (une
 * décision d'approbation, un bloc de fichier ne nomment pas la personne). La règle, appliquée par le
 * vidangeur (`vidangeur.ts`) :
 *
 *  - même personne : la mutation peut partir avec le nouveau jeton, même `id`, donc même clé
 *    d'idempotence ;
 *  - autre personne, ou propriétaire inconnu : elle reste en file, EN QUARANTAINE — conservée à
 *    l'identique, comptée et montrée à l'écran, jamais envoyée sous la nouvelle identité, jamais
 *    supprimée. Elle repart d'elle-même si l'appareil est de nouveau appairé pour sa personne.
 */

export class ErreurSansPersonneConfirmee extends Error {
  constructor() {
    super("aucune personne confirmée : impossible de mettre une mutation en file sans propriétaire");
    this.name = "ErreurSansPersonneConfirmee";
  }
}

/**
 * Enveloppe un dépôt pour que CHAQUE mutation insérée porte sa personne (`MutationOutbox.proprietaire`),
 * lue à l'instant de l'insertion : les écrans et les services (`punch.tsx`, photos, fichiers…) n'ont pas
 * à la passer, donc pas à se tromper. Fail-closed : sans personne confirmée, l'insertion échoue plutôt
 * que de créer une mutation sans propriétaire, qui ne partirait jamais. Une mutation qui porte déjà un
 * propriétaire le garde.
 */
export function avecProprietaire(depot: DepotOutbox, personneCourante: () => string | null): DepotOutbox {
  return {
    lister: () => depot.lister(),
    obtenir: (id) => depot.obtenir(id),
    mettreAJourSiInchangee: (attendue, suivante) => depot.mettreAJourSiInchangee(attendue, suivante),
    mettreAJour: (mutation) => depot.mettreAJour(mutation),
    async inserer(mutation) {
      const proprietaire = mutation.proprietaire ?? personneCourante();
      if (proprietaire === null || proprietaire.trim() === "") {
        throw new ErreurSansPersonneConfirmee();
      }
      return depot.inserer({ ...mutation, proprietaire });
    },
  };
}

/** Les statuts qui attendent un envoi : c'est ce qui serait parti si la personne était la bonne. Un
 * `brouillon` est un enregistrement local pas encore soumis ; `envoyee` et `echec_permanent` sont terminaux. */
const STATUTS_EN_ATTENTE_D_ENVOI: ReadonlySet<StatutMutation> = new Set<StatutMutation>(["en_attente", "envoi"]);

/**
 * Les mutations qui attendent un envoi mais n'appartiennent pas à `personne` (autre personne, ou
 * propriétaire inconnu) : la quarantaine. Fonction pure, sur ce que le dépôt liste.
 */
export function identifierEnQuarantaine(mutations: readonly MutationOutbox[], personne: string): MutationOutbox[] {
  return mutations.filter((m) => STATUTS_EN_ATTENTE_D_ENVOI.has(m.statut) && m.proprietaire !== personne);
}

export interface ResumeQuarantaine {
  /** Combien de mutations attendent en quarantaine. */
  readonly nombre: number;
  /** Les personnes à qui elles appartiennent, sans doublon, triées. */
  readonly proprietaires: readonly string[];
  /** Combien n'ont aucun propriétaire connu (lignes d'avant T1.4-l) : elles ne partiront jamais seules. */
  readonly proprietaireInconnu: number;
}

export function resumerQuarantaine(mutations: readonly MutationOutbox[], personne: string): ResumeQuarantaine {
  const enQuarantaine = identifierEnQuarantaine(mutations, personne);
  const proprietaires = new Set<string>();
  let inconnu = 0;
  for (const mutation of enQuarantaine) {
    if (mutation.proprietaire === null) {
      inconnu += 1;
    } else {
      proprietaires.add(mutation.proprietaire);
    }
  }
  return { nombre: enQuarantaine.length, proprietaires: [...proprietaires].sort(), proprietaireInconnu: inconnu };
}
