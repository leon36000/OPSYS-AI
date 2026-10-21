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
 *  - même personne ET même passerelle : la mutation peut partir avec le nouveau jeton, même `id`, donc même clé
 *    d'idempotence ;
 *  - autre personne/passerelle, ou propriétaire/destination inconnus : elle reste en file, EN QUARANTAINE — conservée à
 *    l'identique, comptée et montrée à l'écran, jamais envoyée sous la nouvelle identité, jamais
 *    supprimée. Elle repart si sa personne ET sa passerelle d’origine sont rétablies.
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
 * propriétaire le garde. La destination est posée à la même insertion et conservée ensuite ;
 * un dépôt sans source de destination produit une ligne non envoyable, comme une ligne héritée.
 */
export function avecProprietaire(depot: DepotOutbox, personneCourante: () => string | null,
  destinationCourante: () => string | null = () => null): DepotOutbox {
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
      // Bind new insertions only; migrations never infer the gateway of an existing row.
      const destination = mutation.destination === undefined ? destinationCourante() : mutation.destination;
      return depot.inserer({ ...mutation, proprietaire, destination });
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
export function identifierEnQuarantaine(mutations: readonly MutationOutbox[], personne: string, destination?: string | null): MutationOutbox[] {
  return mutations.filter((m) => STATUTS_EN_ATTENTE_D_ENVOI.has(m.statut) && (m.proprietaire !== personne || (destination !== undefined && !appartientADestination(m, destination))));
}

export interface ResumeQuarantaine {
  /** Combien de mutations attendent en quarantaine. */
  readonly nombre: number;
  /** Les personnes à qui elles appartiennent, sans doublon, triées. */
  readonly proprietaires: readonly string[];
  /** Combien n'ont aucun propriétaire connu (lignes d'avant T1.4-l) : elles ne partiront jamais seules. */
  readonly proprietaireInconnu: number;
}

export function resumerQuarantaine(mutations: readonly MutationOutbox[], personne: string, destination?: string | null): ResumeQuarantaine {
  const enQuarantaine = identifierEnQuarantaine(mutations, personne, destination);
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

/** Exact gateway URL matching is deliberately conservative: aliases require explicit recovery. */
export function appartientADestination(mutation: MutationOutbox, destination: string | null): boolean {
  return typeof destination === "string" && destination.trim() !== "" && mutation.destination === destination;
}
