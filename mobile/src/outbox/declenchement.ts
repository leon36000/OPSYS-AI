import { signalerRefusAppareil } from "./refusAppareil";
import type { RapportVidange, Vidangeur } from "./vidangeur";

/** Ce que `service.ts` branche pour de vrai (SQLite, `fetch`, jeton courant) et que les tests remplacent. */
export interface DependancesDeclenchement {
  /** Y a-t-il une session pour envoyer (apparié, personne confirmée pour le jeton courant) ? */
  readonly sessionDisponible: () => boolean;
  /** Le vidangeur, construit une seule fois : un seul verrou pour toute l'app. */
  readonly obtenirVidangeur: () => Promise<Vidangeur>;
  /** Appelé quand le serveur refuse l'appareil ; en production, `signalerRefusAppareil`. */
  readonly signalerRefus?: () => void;
}

/**
 * Construit `declencherVidange` (PLAN T1.4-l) : une vidange best-effort.
 *  - sans session : `null`, rien n'est tenté ni ouvert (pas une erreur : la file continue d'accumuler) ;
 *  - sinon : une passe, dont le rapport est rendu tel quel. Si le serveur a refusé l'APPAREIL, le refus
 *    est signalé UNE fois (l'app relit alors son identité) ; la passe s'est déjà arrêtée, il n'y a rien à
 *    réessayer ici.
 * Ne lève pas pour une raison réseau/HTTP ; une panne de stockage remonte à l'appelant, qui décide.
 */
export function creerDeclencheurVidange(dependances: DependancesDeclenchement): () => Promise<RapportVidange | null> {
  const signaler = dependances.signalerRefus ?? signalerRefusAppareil;
  return async () => {
    if (!dependances.sessionDisponible()) {
      return null;
    }
    const vidangeur = await dependances.obtenirVidangeur();
    const rapport = await vidangeur.vidangerFileSortante();
    if (rapport.arret?.genre === "appareil_refuse") {
      signaler();
    }
    return rapport;
  };
}
