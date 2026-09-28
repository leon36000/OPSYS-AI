import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { SessionAppareil } from "./types";

const SESSION_ABSENTE: SessionAppareil = { presente: false };

interface ValeurContexteSession {
  readonly session: SessionAppareil;
  readonly definirSession: (session: SessionAppareil) => void;
}

const ContexteSession = createContext<ValeurContexteSession | null>(null);

/**
 * Fournit l'état de session de l'appareil à toute l'app (`app/_layout.tsx`). Démarre TOUJOURS
 * `{ presente: false }` : la lecture d'un jeton persistant (`expo-secure-store`) et le
 * protocole d'appairage lui-même sont PLAN T1.4-c, pas ce squelette — on n'invente aucun faux
 * état « apparié ». `definirSession` est déjà exposé pour que ce travail futur n'ait qu'à
 * appeler ce setter une fois l'appairage réussi, sans toucher au routage ni à `src/roles/garde`.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, definirSession] = useState<SessionAppareil>(SESSION_ABSENTE);
  const valeur = useMemo<ValeurContexteSession>(() => ({ session, definirSession }), [session]);
  return <ContexteSession.Provider value={valeur}>{children}</ContexteSession.Provider>;
}

function useContexteSession(): ValeurContexteSession {
  const contexte = useContext(ContexteSession);
  if (!contexte) {
    throw new Error("useSessionAppareil/useDefinirSessionAppareil doit être utilisé sous <SessionProvider>.");
  }
  return contexte;
}

export function useSessionAppareil(): SessionAppareil {
  return useContexteSession().session;
}

export function useDefinirSessionAppareil(): (session: SessionAppareil) => void {
  return useContexteSession().definirSession;
}
