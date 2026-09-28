import { PROFILS, type MotifRefusGarde, type Profil, type SessionAppareil, type VerdictGarde } from "./types";

/**
 * Table de mappage rôle → groupe autorisé (R12 §6 : rôles mappés un-à-un sur les profils
 * OPSYS, jamais un secret partagé générique donnant accès à tout). Une `Map` plutôt qu'un
 * calcul : la règle est une donnée fermée, pas une formule.
 */
const GROUPE_AUTORISE_PAR_ROLE: ReadonlyMap<Profil, Profil> = new Map(PROFILS.map((profil) => [profil, profil]));

function estProfilConnu(role: string): role is Profil {
  return (PROFILS as readonly string[]).includes(role);
}

function refuser(motif: MotifRefusGarde): VerdictGarde {
  return { autorise: false, motif, redirectionVers: "/pairing" };
}

/**
 * Garde pure du routage par rôle (PLAN T1.4-a, item 3 ; R12 §5 « groupes de routes gardés par
 * le rôle du jeton d'appareil »). Ne lit ni ne modifie aucun état global : la décision est une
 * fonction du seul `(session, groupeCible)` fourni par l'appelant — c'est ce qui la rend
 * exhaustivement testable et réutilisable telle quelle dans les quatre `_layout.tsx` de groupe.
 *
 * Fail-closed (P2, AGENTS.md) : session absente, rôle inconnu, et rôle valide mais différent du
 * groupe visé produisent tous les trois un refus vers `/pairing` — jamais un accès par défaut.
 * Un jeton `employee` n'obtient donc jamais `autorise: true` pour le groupe `admin`, y compris
 * par navigation directe vers son URL : chaque `_layout.tsx` de groupe appelle cette garde avant
 * de rendre quoi que ce soit (voir app/(admin)/_layout.tsx et les trois autres).
 */
export function evaluerGarde(session: SessionAppareil, groupeCible: Profil): VerdictGarde {
  if (!session.presente) {
    return refuser("session_absente");
  }
  if (!estProfilConnu(session.role)) {
    return refuser("role_inconnu");
  }
  if (GROUPE_AUTORISE_PAR_ROLE.get(session.role) !== groupeCible) {
    return refuser("role_non_autorise");
  }
  return { autorise: true };
}
