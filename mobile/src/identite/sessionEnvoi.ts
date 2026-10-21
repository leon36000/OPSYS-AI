import { definirPersonneConfirmee, type ConfigurationAppel } from "../protocole/configuration";
import { identiteDepuisEtat, type EtatIdentite } from "./etat";

/**
 * Fait suivre à la file sortante ce que l'app sait de sa personne (PLAN T1.4-l). Appelé chaque fois que
 * l'état de l'identité change, avec la configuration POUR LAQUELLE cet état a été établi (jamais celle
 * qui serait courante plus tard : un résultat pour l'ancien jeton ne dit rien du nouveau).
 *
 *  - identité confirmée, ou gardée et à reconfirmer : la file peut envoyer pour cette personne, avec CE
 *    jeton. La dernière confirmation gardée suffit hors ligne (c'est aussi ce qui ouvre le profil) ; si
 *    l'appareil a été révoqué entre-temps, le premier envoi reçoit un refus et le cycle relit l'identité ;
 *  - aucune identité (restauration, appairage en cours, lecture en cours, refus, hors ligne sans mémoire) :
 *    la file n'envoie rien ;
 *  - coffre illisible au démarrage : rien n'a changé EN MÉMOIRE (la configuration déjà posée n'est pas
 *    retirée, voir `useCycleIdentite`), la personne déjà confirmée pour ce jeton non plus.
 */
export function synchroniserPersonneConfirmee(etat: EtatIdentite, configuration: ConfigurationAppel | null): void {
  const identite = identiteDepuisEtat(etat);
  if (identite && configuration && identite.appareilId === configuration.appareilId) {
    definirPersonneConfirmee({
      jeton: configuration.jeton,
      appareilId: configuration.appareilId,
      personne: identite.personne,
      role: identite.role,
    });
    return;
  }
  if (etat.genre === "erreur" && etat.motif === "stockage_illisible") {
    return;
  }
  definirPersonneConfirmee(null);
}
