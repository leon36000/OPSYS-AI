import type { ResultatInventaireDevis } from "./chargeurDevis";

/** Une page de devis n'est visible que sous l'identité qui l'a reçue. */
export function inventaireVisiblePourPersonne(
  resultat: ResultatInventaireDevis | null | undefined,
  personneCourante: string | null,
): resultat is ResultatInventaireDevis {
  return (
    resultat !== null &&
    resultat !== undefined &&
    personneCourante !== null &&
    resultat.personne === personneCourante
  );
}

/** Rejette une réponse asynchrone si l'identité ou la séquence de lecture a changé pendant l'appel. */
export function peutAppliquerReponseInventaire(
  personneReponse: string | null,
  personneCourante: string | null,
  sequenceReponse: number,
  sequenceCourante: number,
): boolean {
  return (
    personneReponse !== null &&
    personneCourante !== null &&
    personneReponse === personneCourante &&
    sequenceReponse === sequenceCourante
  );
}
