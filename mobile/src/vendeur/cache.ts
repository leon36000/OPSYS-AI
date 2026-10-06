import { lirePageLeads } from "../m2/listeLeads";
import type { FiltreLeads } from "../m2/listeLeads";
import { estDevisVendeurValide } from "../m3/devis";
import type { DevisVendeur } from "../m3/devis";
import { estObjet } from "../protocole/enveloppeOutil";
import { cleDeCachePersonne, PREFIXE_CACHE_VENDEUR } from "../stockage/cles";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { estDevisConnuValide } from "./devisConnus";
import type { DevisConnu } from "./devisConnus";
import { estFicheBruteValide } from "./fiche";
import type { FicheBrute } from "./fiche";
import { cleFiltre, demarrerLecture, fusionnerPage } from "./lectureLeads";
import type { LeadsLus } from "./lectureLeads";

/**
 * Le cache hors ligne du profil vendeur (`(seller)/leads.tsx`, `lead/[id].tsx`, `quotes.tsx`, PLAN T4.8), au-dessus
 * du dépôt clé/valeur partagé (`src/stockage/depotCleValeur.ts`, `expo-sqlite`). Une lecture en ligne réussie écrit ;
 * une lecture qui ne peut pas joindre le serveur relit, et l'écran dit QUE c'est un cache et DE QUAND il date.
 *
 * **Un cache par PERSONNE.** Ce cache porte les leads d'un vendeur et le contact de ses clients : chaque clé
 * commence par la personne que le serveur a confirmée (`vendeur:<personne>:...`). Après un nouvel appairage pour
 * quelqu'un d'autre sur le même téléphone, la lecture de la nouvelle personne ne trouve rien de la précédente
 * (jamais un lead d'un autre vendeur, même hors ligne). Même esprit que la quarantaine de la file (T1.4-l).
 *
 * **Fail-closed en lecture.** Tout est relu par les MÊMES lecteurs que la lecture en ligne : une valeur corrompue,
 * d'une autre forme ou d'une version que ce code ne sait plus lire rend `null` (« pas de cache »), jamais une valeur
 * à moitié devinée. Les clés portent une version (`_v1`) pour que ce changement de forme ne relise rien de faux.
 *
 * **Ni coût ni marge, jamais.** Un devis n'est écrit qu'après la liste blanche (`m3/devis.ts`), et relu de façon
 * STRICTE (`estDevisVendeurValide` refuse une clé de plus) : un coût n'atteint jamais la base du téléphone.
 *
 * **Effacé quand l'identité de l'appareil change** (PLAN T1.4-n) : révocation, autre personne, autre rôle. Le préfixe est
 * dans `src/stockage/cles.ts`, la purge dans `src/identite/caches.ts`.
 *
 * Stockage : protection au repos du système (R12 §6), comme le reste du cache ; le contact d'un client y est de la
 * donnée personnelle (Loi 25), gardée pour les leads de CETTE personne seulement.
 */

function cle(personne: string, nom: string): string {
  return cleDeCachePersonne(PREFIXE_CACHE_VENDEUR, personne, `${nom}_v1`);
}

async function lireJson(depot: DepotCleValeur, cleComplete: string): Promise<unknown> {
  const brut = await depot.lire(cleComplete);
  if (!brut) {
    return null;
  }
  try {
    return JSON.parse(brut) as unknown;
  } catch {
    return null;
  }
}

// -- la liste des leads --------------------------------------------------------------------------------------------
function cleLeads(personne: string, filtre: FiltreLeads): string {
  return cle(personne, `leads:${cleFiltre(filtre)}`);
}

/** Écrit ce que l'écran a lu pour ce filtre : les pages brutes du serveur, et la date de la première. */
export async function ecrireCacheLeads(depot: DepotCleValeur, personne: string, lus: LeadsLus): Promise<void> {
  await depot.ecrire(
    cleLeads(personne, lus.filtre),
    JSON.stringify({ filtre: lus.filtre, pages: lus.pagesBrutes, misAJourLe: lus.misAJourLe }),
  );
}

/** Relit la liste de ce filtre en recollant les pages écrites, par les mêmes règles que la lecture en ligne. `null`
 * si rien n'est gardé, ou si une page est illisible ou ne se recolle pas. */
export async function lireCacheLeads(
  depot: DepotCleValeur,
  personne: string,
  filtre: FiltreLeads,
): Promise<LeadsLus | null> {
  const valeur = await lireJson(depot, cleLeads(personne, filtre));
  if (
    !estObjet(valeur) ||
    !Array.isArray(valeur.pages) ||
    valeur.pages.length === 0 ||
    typeof valeur.misAJourLe !== "string" ||
    Number.isNaN(new Date(valeur.misAJourLe).getTime())
  ) {
    return null;
  }
  const premiere = lirePageLeads(valeur.pages[0]);
  if (premiere === null) {
    return null;
  }
  let lus = demarrerLecture(filtre, premiere, valeur.pages[0], valeur.misAJourLe);
  for (const brute of valeur.pages.slice(1)) {
    const page = lirePageLeads(brute);
    if (lus === null || page === null) {
      return null;
    }
    const fusion = fusionnerPage(lus, page, brute);
    if (fusion.genre !== "fusionnee") {
      return null;
    }
    lus = fusion.lus;
  }
  return lus;
}

// -- la fiche d'un lead --------------------------------------------------------------------------------------------
export async function ecrireCacheFiche(
  depot: DepotCleValeur,
  personne: string,
  leadId: string,
  fiche: FicheBrute,
): Promise<void> {
  await depot.ecrire(cle(personne, `fiche:${leadId}`), JSON.stringify(fiche));
}

export async function lireCacheFiche(depot: DepotCleValeur, personne: string, leadId: string): Promise<FicheBrute | null> {
  const valeur = await lireJson(depot, cle(personne, `fiche:${leadId}`));
  return estFicheBruteValide(valeur) ? valeur : null;
}

// -- les devis -----------------------------------------------------------------------------------------------------
export interface DevisEnCache {
  readonly devis: DevisVendeur;
  /** ISO 8601 UTC de la lecture. */
  readonly misAJourLe: string;
}

export async function ecrireCacheDevis(
  depot: DepotCleValeur,
  personne: string,
  devis: DevisVendeur,
  misAJourLe: string,
): Promise<void> {
  await depot.ecrire(cle(personne, `devis:${devis.devisId}`), JSON.stringify({ devis, misAJourLe }));
}

export async function lireCacheDevis(
  depot: DepotCleValeur,
  personne: string,
  devisId: string,
): Promise<DevisEnCache | null> {
  const valeur = await lireJson(depot, cle(personne, `devis:${devisId}`));
  if (
    !estObjet(valeur) ||
    !estDevisVendeurValide(valeur.devis) ||
    valeur.devis.devisId !== devisId ||
    typeof valeur.misAJourLe !== "string" ||
    Number.isNaN(new Date(valeur.misAJourLe).getTime())
  ) {
    return null;
  }
  return { devis: valeur.devis, misAJourLe: valeur.misAJourLe };
}

// -- les numéros de devis connus -----------------------------------------------------------------------------------
export async function ecrireDevisConnus(
  depot: DepotCleValeur,
  personne: string,
  devis: readonly DevisConnu[],
): Promise<void> {
  await depot.ecrire(cle(personne, "devis_connus"), JSON.stringify(devis));
}

/** Efface la copie d'un devis refusé et enlève son identifiant connu, sans toucher au reste du profil. */
export async function supprimerCacheDevis(
  depot: DepotCleValeur,
  personne: string,
  devisId: string,
): Promise<void> {
  await depot.supprimer(cle(personne, `devis:${devisId}`));
  const connus = await lireDevisConnus(depot, personne);
  const restants = connus.filter((devis) => devis.devisId !== devisId);
  if (restants.length !== connus.length) {
    await ecrireDevisConnus(depot, personne, restants);
  }
}

/** Efface les copies de devis de cette personne après un refus M3; les fiches/leads restent intacts. */
export async function purgerCachesDevis(depot: DepotCleValeur, personne: string): Promise<void> {
  await depot.supprimerParPrefixe(cleDeCachePersonne(PREFIXE_CACHE_VENDEUR, personne, "devis:"));
  await depot.supprimer(cle(personne, "devis_connus"));
}

/** Les numéros gardés ; `[]` si rien n'est gardé ou si la valeur est illisible (jamais un numéro deviné). */
export async function lireDevisConnus(depot: DepotCleValeur, personne: string): Promise<readonly DevisConnu[]> {
  const valeur = await lireJson(depot, cle(personne, "devis_connus"));
  if (!Array.isArray(valeur) || !valeur.every(estDevisConnuValide)) {
    return [];
  }
  return valeur;
}
