const DELAI_INITIAL_MS = 1_000;
const DELAI_PLAFOND_MS = 30_000;

/**
 * Délai de recul exponentiel avant la prochaine tentative (R12 §4 : « 1 s → 30 s, ×2 » —
 * même principe que le client `gateway-client` d'OpenClaw cité par R12 §1.2). `tentatives`
 * est le compteur AVANT l'échec courant (0 pour le tout premier réessai).
 */
export function calculerDelaiReculMs(tentatives: number): number {
  const exposant = Math.max(0, Math.trunc(tentatives));
  return Math.min(DELAI_INITIAL_MS * 2 ** exposant, DELAI_PLAFOND_MS);
}

/**
 * Horodatage de la prochaine tentative permise. Fonction pure : `maintenant` est injecté par
 * l'appelant plutôt que lu via `Date.now()` ici, exactement comme le demande PLAN T1.4-a item 4.
 */
export function calculerProchaineTentativeA(tentatives: number, maintenant: Date): Date {
  return new Date(maintenant.getTime() + calculerDelaiReculMs(tentatives));
}
