import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import { ETAT_RESTAURATION, personneDepuisEtat, sessionDepuisEtat, type EtatIdentite } from "../identite/etat";
import type { SessionAppareil } from "./types";

interface ValeurContexteSession {
  readonly etat: EtatIdentite;
  readonly definirEtat: (etat: EtatIdentite) => void;
  /** Dérivée de `etat` : le rôle NOMMÉ confirmé par le serveur (ou gardé, à reconfirmer), sinon aucune session. */
  readonly session: SessionAppareil;
}

const ContexteSession = createContext<ValeurContexteSession | null>(null);

/**
 * Fournit à toute l'app ce qu'elle sait de sa personne et de son rôle (`app/_layout.tsx`, PLAN T1.4-c5).
 * Démarre TOUJOURS en `restauration` : la lecture du coffre (`expo-secure-store`) et celle du serveur
 * viennent après, et aucun faux état « apparié » n'est inventé. La session que la garde de routes regarde
 * (`useSessionAppareil`) est dérivée de cet état : un profil n'existe que si le serveur a confirmé un rôle
 * nommé (ou si la dernière confirmation est gardée, hors ligne).
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [etat, definirEtat] = useState<EtatIdentite>(ETAT_RESTAURATION);
  const valeur = useMemo<ValeurContexteSession>(
    () => ({ etat, definirEtat, session: sessionDepuisEtat(etat) }),
    [etat],
  );
  return <ContexteSession.Provider value={valeur}>{children}</ContexteSession.Provider>;
}

function useContexteSession(): ValeurContexteSession {
  const contexte = useContext(ContexteSession);
  if (!contexte) {
    throw new Error("Les hooks de session doivent être utilisés sous <SessionProvider>.");
  }
  return contexte;
}

/** Ce que la garde de routes (`src/roles/garde.ts`) regarde : le rôle nommé, ou aucune session. */
export function useSessionAppareil(): SessionAppareil {
  return useContexteSession().session;
}

export function useEtatIdentite(): EtatIdentite {
  return useContexteSession().etat;
}

export function useDefinirEtatIdentite(): (etat: EtatIdentite) => void {
  return useContexteSession().definirEtat;
}

/** La personne appairée, telle que le serveur l'a confirmée ; `null` tant qu'elle ne l'est pas. */
export function usePersonneAppairee(): string | null {
  return personneDepuisEtat(useContexteSession().etat);
}
