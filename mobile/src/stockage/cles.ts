/**
 * Les clés du dépôt clé/valeur (`src/stockage/depotCleValeur.ts`) qui portent des DONNÉES LUES AU SERVEUR pour une
 * personne, et donc ce qu'il faut effacer de l'appareil quand cette personne n'est plus celle de l'appareil (PLAN
 * T1.4-n, Loi 25 : minimisation). Écrites ici, une fois : chaque cache construit ses clés avec ces préfixes, et la purge
 * (`src/identite/caches.ts`) efface par ces mêmes préfixes. Un test écrit par chaque écrivain RÉEL puis purge, et exige
 * un dépôt vide : un cache ajouté sans son préfixe ici échoue à ce test.
 *
 * Trois profils, trois préfixes, la personne encodée ensuite (`admin:<personne>:<section>_v1`) : deux personnes ne
 * partagent jamais une clé, et effacer le préfixe d'un profil efface les caches de toutes les personnes qui s'y
 * trouvaient.
 *
 * Ce qui n'est PAS ici, volontairement : les brouillons de l'employé (la checklist d'un chantier, l'identifiant de
 * la complétion acceptée). Ce ne sont pas des lectures du serveur mais du travail en cours, du même ordre que les
 * photos et la signature que la file sortante garde en quarantaine (« La file suit le jeton et la personne » de
 * `docs/architecture/MOBILE.md`) : on ne les efface pas.
 */
export const PREFIXE_CACHE_ADMIN = "admin:";
export const PREFIXE_CACHE_VENDEUR = "vendeur:";
export const PREFIXE_CACHE_EMPLOYE = "employe:";

/** Tous les préfixes de caches lus au serveur. */
export const PREFIXES_DES_CACHES_PAR_PERSONNE: readonly string[] = [
  PREFIXE_CACHE_ADMIN,
  PREFIXE_CACHE_VENDEUR,
  PREFIXE_CACHE_EMPLOYE,
];

/**
 * Les clés d'avant T1.4-n : un cache SANS personne. Le cache des chantiers de l'employé était une seule clé pour tout
 * l'appareil, relue par n'importe quelle personne appairée ensuite. Plus jamais lue ; effacée avec le reste.
 */
export const CLES_HERITEES_SANS_PERSONNE: readonly string[] = ["today_chantiers_v1"];

/** La clé d'un cache d'un profil pour une personne : `<prefixe><personne encodée>:<nom>`. */
export function cleDeCachePersonne(prefixe: string, personne: string, nom: string): string {
  return `${prefixe}${encodeURIComponent(personne)}:${nom}`;
}
