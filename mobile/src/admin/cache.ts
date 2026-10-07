import { ecrireCacheSousGarde } from "../stockage/lecturesEnVol";
import { estObjet } from "../protocole/enveloppeOutil";
import { cleDeCachePersonne, PREFIXE_CACHE_ADMIN } from "../stockage/cles";
import type { DepotCleValeur } from "../stockage/depotCleValeur";

/**
 * Le cache hors ligne du profil admin (`(admin)/admin.tsx`, `chiffres.tsx`, `chantiers.tsx`, PLAN T4.20), au-dessus du
 * dépôt clé/valeur partagé (`src/stockage/depotCleValeur.ts`, `expo-sqlite`). Une lecture en ligne réussie écrit ; une
 * lecture qui ne peut pas joindre le serveur relit, et l'écran dit QUE c'est un cache, DE QUAND il date et POURQUOI.
 *
 * **Un cache par PERSONNE.** Ce cache porte les chiffres de l'entreprise (solde, cash libre, marges) : chaque clé
 * commence par la personne que le serveur a confirmée (`admin:<personne>:...`). Après un nouvel appairage pour quelqu'un
 * d'autre sur le même téléphone, la lecture de la nouvelle personne ne trouve rien de la précédente. La personne est
 * encodée (`encodeURIComponent`) : deux personnes ne peuvent pas partager une clé parce que l'une contient un « : ».
 *
 * **Les mots du serveur.** Le cache garde l'enveloppe que le serveur a rendue, telle quelle, et se relit par les MÊMES
 * lecteurs que la lecture en ligne (`lecture.ts`) : une valeur corrompue, ou d'une autre forme, est « pas de cache »,
 * jamais une valeur à moitié devinée. Les clés portent une version (`_v1`) pour qu'un changement de forme ne relise
 * rien de faux. Ce qu'on n'écrit jamais : un refus du serveur (un cache ne dit pas ce que le serveur refuse).
 *
 * **Effacé quand l'identité de l'appareil change** (PLAN T1.4-n) : révocation, autre personne, autre rôle. Le préfixe est
 * dans `src/stockage/cles.ts`, la purge dans `src/identite/caches.ts`.
 *
 * Stockage : protection au repos du système (R12 §6), comme le reste du cache de l'app.
 */

function cle(personne: string, nom: string): string {
  return cleDeCachePersonne(PREFIXE_CACHE_ADMIN, personne, `${nom}_v1`);
}

export interface SectionEnCache {
  /** L'enveloppe du serveur (`corps.result`), telle qu'elle a été lue, ou épurée par la section avant d'être gardée. */
  readonly resultat: unknown;
  /** ISO 8601 UTC de la lecture. */
  readonly misAJourLe: string;
}

export async function ecrireCacheSection(
  depot: DepotCleValeur,
  personne: string,
  nom: string,
  resultat: unknown,
  misAJourLe: string,
): Promise<void> {
  await ecrireCacheSousGarde(depot, () => depot.ecrire(cle(personne, nom), JSON.stringify({ resultat, misAJourLe })));
}

/** `null` : rien n'est gardé pour cette personne sous ce nom, ou la valeur gardée est illisible. */
export async function lireCacheSection(
  depot: DepotCleValeur,
  personne: string,
  nom: string,
): Promise<SectionEnCache | null> {
  const brut = await depot.lire(cle(personne, nom));
  if (!brut) {
    return null;
  }
  let valeur: unknown;
  try {
    valeur = JSON.parse(brut) as unknown;
  } catch {
    return null;
  }
  if (
    !estObjet(valeur) ||
    valeur.resultat === undefined ||
    valeur.resultat === null ||
    typeof valeur.misAJourLe !== "string" ||
    Number.isNaN(new Date(valeur.misAJourLe).getTime())
  ) {
    return null;
  }
  return { resultat: valeur.resultat, misAJourLe: valeur.misAJourLe };
}
