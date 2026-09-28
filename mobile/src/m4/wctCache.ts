import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { WctRecuM4 } from "./completion";

/**
 * Persiste le WCT complet obtenu après une complétion réussie (`complete.tsx`, via le pont
 * `m4_lire_outbox` documenté dans `src/m4/completion.ts`) — même dépôt clé/valeur PARTAGÉ que
 * `src/today/cache.ts`/`src/checklist/cache.ts` (`src/stockage/depotCleValeur.ts`), une clé PAR
 * CHANTIER, versionnée comme les deux autres caches.
 *
 * Raison d'être : `materials.tsx` (M6.10, « appelé après Terminer ») a besoin du MÊME WCT pour
 * construire `m6_declarer_materiaux_utilises({wct, formulaire})` — le lire depuis ce cache plutôt
 * que de le retransporter par un paramètre de route Expo Router (qui ne prend que des chaînes) ou
 * de le redemander au serveur (`m4_lire_outbox` n'offre aucun filtre par `wct_id`, un second
 * appel redondant coûterait plus cher, P11). Survit à une navigation ou un redémarrage entre
 * `complete.tsx` et `materials.tsx` — cohérent avec R12 §4 (hors ligne d'abord).
 */
function cleWct(chantierId: string): string {
  return `wct_${chantierId}_v1`;
}

function estWctValide(valeur: unknown): valeur is WctRecuM4 {
  return (
    typeof valeur === "object" &&
    valeur !== null &&
    typeof (valeur as { wct_id?: unknown }).wct_id === "string" &&
    typeof (valeur as { intervention_id?: unknown }).intervention_id === "string"
  );
}

/** `null` si aucun WCT n'a encore été mis en cache pour ce chantier, ou si la valeur stockée est
 * corrompue/d'un format inconnu — fail-closed (AGENTS.md) : `materials.tsx` doit alors dire à
 * l'employé de retourner à l'écran « Terminer », jamais deviner un WCT. */
export async function lireWctEnCache(depot: DepotCleValeur, chantierId: string): Promise<WctRecuM4 | null> {
  const brut = await depot.lire(cleWct(chantierId));
  if (!brut) {
    return null;
  }
  try {
    const valeur: unknown = JSON.parse(brut);
    return estWctValide(valeur) ? valeur : null;
  } catch {
    return null;
  }
}

export async function ecrireWctEnCache(depot: DepotCleValeur, chantierId: string, wct: WctRecuM4): Promise<void> {
  await depot.ecrire(cleWct(chantierId), JSON.stringify(wct));
}
