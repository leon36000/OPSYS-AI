import { CLES_HERITEES_SANS_PERSONNE, PREFIXES_DES_CACHES_PAR_PERSONNE } from "../stockage/cles";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { estRoleNomme } from "./contrat";
import type { RoleNomme } from "./contrat";
import { estRefusDuServeur } from "./etat";
import type { EtatIdentite } from "./etat";

/**
 * Les caches lus au serveur appartiennent à UNE identité, et quittent l'appareil avec elle (PLAN T1.4-n, Loi 25 :
 * minimisation). Les chiffres de l'entreprise (admin), les leads et le contact des clients (vendeur), les chantiers
 * d'un employé sont gardés sous la personne (`src/stockage/cles.ts`) ; quand l'appareil apprend qu'il est révoqué, ou
 * qu'il est appairé à une autre personne (ou qu'elle change de rôle), ce que l'ancienne identité y a laissé est effacé.
 *
 * **Le marqueur.** Un enregistrement dit POUR QUELLE identité les caches de l'appareil ont été écrits
 * (`proprietaire_des_caches_v1`, dans le même dépôt : il est effacé, ou perdu, avec ce qu'il décrit). À chaque identité
 * CONFIRMÉE par le serveur, on le compare : même personne et même rôle, on garde (un nouvel appairage de la même personne
 * garde ses caches) ; sinon, ou sans marqueur (caches d'avant ce changement, marqueur illisible : on ne devine pas à qui ils
 * sont), on efface tout, puis on marque la nouvelle identité. Comparer à ce marqueur plutôt qu'à l'identité gardée dans le
 * coffre est ce qui rend la purge sûre : `apresAppairage` efface l'identité gardée avant la première lecture de la
 * nouvelle, et une purge qui échoue est retentée à la confirmation suivante (le marqueur n'est écrit qu'après elle).
 *
 * **Ce qui n'est PAS effacé.** La file sortante (`opsys-outbox.db`) : « La file suit le jeton et la personne » de
 * `docs/architecture/MOBILE.md` décide de ses mutations en attente (quarantaine, retour de leur personne), et cette tranche
 * n'y touche pas. Ni les brouillons de l'employé (checklist, identifiant de complétion), qui ne sont pas des lectures du
 * serveur et suivent le même sort que les photos et la signature locales. Ni le coffre (jeton, clé de l'appareil).
 */
export const CLE_PROPRIETAIRE_DES_CACHES = "proprietaire_des_caches_v1";

export interface ProprietaireDesCaches {
  readonly personne: string;
  readonly role: RoleNomme;
}

/** `null` : aucun marqueur, ou marqueur illisible — jamais une identité devinée. */
export async function lireProprietaireDesCaches(depot: DepotCleValeur): Promise<ProprietaireDesCaches | null> {
  const brut = await depot.lire(CLE_PROPRIETAIRE_DES_CACHES);
  if (!brut) {
    return null;
  }
  try {
    const valeur: unknown = JSON.parse(brut);
    if (typeof valeur !== "object" || valeur === null) {
      return null;
    }
    const { personne, role } = valeur as Record<string, unknown>;
    return typeof personne === "string" && personne.trim() !== "" && estRoleNomme(role) ? { personne, role } : null;
  } catch {
    return null;
  }
}

export async function ecrireProprietaireDesCaches(depot: DepotCleValeur, proprietaire: ProprietaireDesCaches): Promise<void> {
  await depot.ecrire(CLE_PROPRIETAIRE_DES_CACHES, JSON.stringify({ personne: proprietaire.personne, role: proprietaire.role }));
}

/**
 * Efface tous les caches lus au serveur, de toutes les personnes (`PREFIXES_DES_CACHES_PAR_PERSONNE`), et les clés d'avant
 * qui n'avaient pas de personne. N'efface ni le marqueur, ni les brouillons, ni rien d'autre.
 */
export async function purgerCachesDeLaPersonne(depot: DepotCleValeur): Promise<void> {
  for (const prefixe of PREFIXES_DES_CACHES_PAR_PERSONNE) {
    await depot.supprimerParPrefixe(prefixe);
  }
  for (const cle of CLES_HERITEES_SANS_PERSONNE) {
    await depot.supprimer(cle);
  }
}

export type DecisionCaches =
  /** Rien n'a changé pour les caches : la même identité, ou l'état ne dit rien de l'attribution (hors ligne). */
  | { readonly genre: "conserver" }
  /** L'identité confirmée n'est pas celle des caches : on efface tout, puis on marque la nouvelle. */
  | { readonly genre: "purger_puis_marquer"; readonly proprietaire: ProprietaireDesCaches }
  /** Le serveur refuse l'appareil : on efface tout, et plus rien n'appartient à personne. */
  | { readonly genre: "purger_puis_oublier" };

/**
 * Ce qu'il faut faire des caches d'après l'état de l'identité et le marqueur. Fonction PURE.
 *  - identité confirmée : comparée au marqueur (personne ET rôle : un rôle retiré ne garde pas les chiffres de l'entreprise) ;
 *  - refus du serveur (jeton révoqué, attribution retirée, rôle inconnu, autre refus) : l'appareil « apprend qu'il est
 *    révoqué » ;
 *  - tout le reste (à reconfirmer, pas de réseau ni de mémoire, coffre illisible, lecture en cours) : rien.
 */
export function decisionCaches(marqueur: ProprietaireDesCaches | null, etat: EtatIdentite): DecisionCaches {
  if (etat.genre === "confirmee") {
    const { personne, role } = etat.identite;
    return marqueur !== null && marqueur.personne === personne && marqueur.role === role
      ? { genre: "conserver" }
      : { genre: "purger_puis_marquer", proprietaire: { personne, role } };
  }
  if (etat.genre === "erreur" && estRefusDuServeur(etat.motif)) {
    return { genre: "purger_puis_oublier" };
  }
  return { genre: "conserver" };
}

/**
 * Applique la décision. Lève si le dépôt lève : l'appelant décide (`synchroniserCachesSansEchouer`). L'ordre compte : le
 * marqueur n'est écrit qu'APRÈS la purge, donc une purge interrompue est retentée à la confirmation suivante.
 */
export async function synchroniserCaches(depot: DepotCleValeur, etat: EtatIdentite): Promise<DecisionCaches> {
  const decision = decisionCaches(await lireProprietaireDesCaches(depot), etat);
  if (decision.genre === "purger_puis_marquer") {
    await purgerCachesDeLaPersonne(depot);
    await ecrireProprietaireDesCaches(depot, decision.proprietaire);
  } else if (decision.genre === "purger_puis_oublier") {
    await purgerCachesDeLaPersonne(depot);
    await depot.supprimer(CLE_PROPRIETAIRE_DES_CACHES);
  }
  return decision;
}

/**
 * `synchroniserCaches` qui ne lève jamais : un dépôt qui ne répond pas (SQLite) ne bloque ni le changement de profil ni
 * l'app. Le journal ne porte que le nom de l'opération et l'erreur : jamais une personne, jamais un jeton.
 */
export async function synchroniserCachesSansEchouer(
  obtenirDepot: () => Promise<DepotCleValeur>,
  etat: EtatIdentite,
): Promise<DecisionCaches | null> {
  try {
    return await synchroniserCaches(await obtenirDepot(), etat);
  } catch (erreur) {
    // eslint-disable-next-line no-console
    console.error("opsys: caches de l'identité précédente non effacés (retenté à la prochaine confirmation)", erreur);
    return null;
  }
}
