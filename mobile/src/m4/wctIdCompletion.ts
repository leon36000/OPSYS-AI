import type { DepotCleValeur } from "../stockage/depotCleValeur";

/**
 * Garde, par chantier, le SEUL `wct_id` de la complétion acceptée — l'identifiant de l'accusé de
 * `m4_completer_intervention` (`AccuseCompletionM4.wct_id`, `src/m4/completion.ts`), jamais une
 * copie du WCT. Même dépôt clé/valeur PARTAGÉ que `src/today/cache.ts`/`src/checklist/cache.ts`
 * (`src/stockage/depotCleValeur.ts`), une clé PAR CHANTIER, versionnée comme les deux autres.
 *
 * Raison d'être : `materials.tsx` (M6.10, « appelé après Terminer ») envoie
 * `m6_declarer_materiaux_utilises({wct_id, formulaire})` et M6 relit lui-même le WCT publié par M4
 * pour cet identifiant (PLAN T1.4-i) — le mobile n'a donc plus rien d'autre à transporter. Mais
 * l'accusé n'est lu qu'une fois, par `complete.tsx`, au moment où le serveur répond : le
 * `wct_id` doit survivre à une navigation ou à un redémarrage entre `complete.tsx` et
 * `materials.tsx` (R12 §4, hors ligne d'abord), et un paramètre de route Expo Router ne survit
 * pas à un redémarrage. Ce n'est pas un droit d'accès : le serveur ne se fie pas à ce que
 * l'appareil envoie et ne connaît que les WCT que M4 a réellement publiés.
 */
function cleWctId(chantierId: string): string {
  return `wct_id_${chantierId}_v1`;
}

/** `null` si aucune complétion acceptée n'a été mémorisée pour ce chantier, ou si la valeur
 * stockée est vide — fail-closed (AGENTS.md) : `materials.tsx` doit alors dire à l'employé de
 * retourner à l'écran « Terminer », jamais deviner un identifiant. */
export async function lireWctIdCompletion(depot: DepotCleValeur, chantierId: string): Promise<string | null> {
  const brut = await depot.lire(cleWctId(chantierId));
  return brut && brut.length > 0 ? brut : null;
}

export async function ecrireWctIdCompletion(depot: DepotCleValeur, chantierId: string, wctId: string): Promise<void> {
  await depot.ecrire(cleWctId(chantierId), wctId);
}
