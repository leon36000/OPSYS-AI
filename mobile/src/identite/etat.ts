import type { SessionAppareil } from "../roles/types";
import type { IdentiteOpsys, MotifRefusIdentite, ResultatLectureIdentite } from "./contrat";
import type { IdentiteMemorisee } from "./stockage";

/**
 * Ce que l'app sait de sa personne et de son rôle, à chaque instant (PLAN T1.4-c5). Fonctions PURES :
 * le profil (`admin`, `employee`, `seller`) est choisi d'après le rôle NOMMÉ que le serveur a confirmé,
 * jamais d'après le rôle de transport du jeton (`operator`), et jamais par défaut.
 */

/** Motifs d'erreur montrés à la personne : les refus du serveur, plus deux échecs que seule l'app voit. */
export type MotifErreurIdentite = MotifRefusIdentite | "hors_ligne_sans_memoire" | "stockage_illisible";

// Un `Record` exhaustif : ajouter un motif à l'union sans l'ajouter ici est une erreur de compilation, et
// `MOTIFS_ERREUR_IDENTITE` sert aux tests de traduction (chaque motif a son texte, dans chaque langue).
const MOTIFS: Record<MotifErreurIdentite, true> = {
  appareil_non_attribue: true,
  role_inconnu: true,
  jeton_refuse: true,
  refus_inattendu: true,
  reponse_invalide: true,
  hors_ligne_sans_memoire: true,
  stockage_illisible: true,
};

export const MOTIFS_ERREUR_IDENTITE = Object.keys(MOTIFS) as readonly MotifErreurIdentite[];

// Un `Record` exhaustif, lui aussi : ajouter un motif sans dire s'il est un REFUS DU SERVEUR est une erreur de compilation.
// Un refus (401, 403, autre 4xx, corps qui n'est pas une identité) est le serveur qui dit non à cet appareil : c'est ce
// qu'apprend l'app quand le jeton est révoqué, l'attribution retirée ou le rôle retiré. Les deux autres motifs sont des
// pannes que seule l'app voit (pas de réseau ni de mémoire, coffre illisible) : ils ne disent rien de l'attribution.
const MOTIF_EST_UN_REFUS: Record<MotifErreurIdentite, boolean> = {
  appareil_non_attribue: true,
  role_inconnu: true,
  jeton_refuse: true,
  refus_inattendu: true,
  reponse_invalide: true,
  hors_ligne_sans_memoire: false,
  stockage_illisible: false,
};

/** Ce motif est-il le serveur qui refuse l'appareil (et non une panne locale) ? */
export function estRefusDuServeur(motif: MotifErreurIdentite): boolean {
  return MOTIF_EST_UN_REFUS[motif];
}

export type EtatIdentite =
  /** Lecture du coffre en cours : on ne sait pas encore si l'appareil est apparié. */
  | { readonly genre: "restauration" }
  | { readonly genre: "non_appairee" }
  /** Apparié, première lecture en cours, aucune identité gardée : aucun profil pour l'instant. */
  | { readonly genre: "en_lecture" }
  | { readonly genre: "confirmee"; readonly identite: IdentiteOpsys }
  /** Le serveur n'a pas pu être joint : la dernière identité confirmée sert, marquée à reconfirmer. */
  | { readonly genre: "a_reconfirmer"; readonly identite: IdentiteOpsys; readonly confirmeLe: string }
  | { readonly genre: "erreur"; readonly motif: MotifErreurIdentite };

export const ETAT_RESTAURATION: EtatIdentite = { genre: "restauration" };

/** Un effet à appliquer au coffre après une décision. */
export type EcritureIdentite =
  | { readonly genre: "memoriser"; readonly identite: IdentiteMemorisee }
  | { readonly genre: "effacer" };

export interface Decision {
  readonly etat: EtatIdentite;
  /** `null` : le coffre reste tel quel. */
  readonly ecriture: EcritureIdentite | null;
}

/**
 * État au démarrage, d'après ce que le coffre contient. Une identité gardée pour un autre appareil que
 * celui de la session ne sert à rien.
 */
export function restaurerEtat(
  session: { readonly appareilId: string } | null,
  memorisee: IdentiteMemorisee | null,
): EtatIdentite {
  if (!session) {
    return { genre: "non_appairee" };
  }
  if (!memorisee || memorisee.appareilId !== session.appareilId) {
    return { genre: "en_lecture" };
  }
  const { confirmeLe, ...identite } = memorisee;
  return { genre: "a_reconfirmer", identite, confirmeLe };
}

/**
 * Nouvel état après une lecture du serveur.
 *  - confirmée : le profil est celui du serveur, et il est gardé pour le hors ligne ;
 *  - refusée : aucun profil, l'identité gardée est effacée (un appareil révoqué ou dépersonnalisé ne
 *    garde pas son profil) ;
 *  - indisponible : la dernière identité confirmée sert, à reconfirmer ; sans elle, aucun profil.
 */
export function decider(
  memorisee: IdentiteMemorisee | null,
  resultat: ResultatLectureIdentite,
  maintenant: Date,
): Decision {
  if (resultat.genre === "confirmee") {
    return {
      etat: { genre: "confirmee", identite: resultat.identite },
      ecriture: { genre: "memoriser", identite: { ...resultat.identite, confirmeLe: maintenant.toISOString() } },
    };
  }
  if (resultat.genre === "refusee") {
    return { etat: { genre: "erreur", motif: resultat.motif }, ecriture: { genre: "effacer" } };
  }
  if (memorisee) {
    const { confirmeLe, ...identite } = memorisee;
    return { etat: { genre: "a_reconfirmer", identite, confirmeLe }, ecriture: null };
  }
  return { etat: { genre: "erreur", motif: "hors_ligne_sans_memoire" }, ecriture: null };
}

/** L'identité qui fait foi pour l'écran, confirmée ou à reconfirmer ; `null` sinon. */
export function identiteDepuisEtat(etat: EtatIdentite): IdentiteOpsys | null {
  return etat.genre === "confirmee" || etat.genre === "a_reconfirmer" ? etat.identite : null;
}

/**
 * La session que la garde de routes regarde : le rôle NOMMÉ, seulement quand une identité existe. Sans
 * identité (restauration, non appairé, lecture en cours, erreur), aucune session : jamais un profil
 * par défaut.
 */
export function sessionDepuisEtat(etat: EtatIdentite): SessionAppareil {
  const identite = identiteDepuisEtat(etat);
  return identite ? { presente: true, role: identite.role } : { presente: false };
}

/** La personne à envoyer comme technicien : celle du serveur, ou `null` (l'écran refuse alors d'agir). */
export function personneDepuisEtat(etat: EtatIdentite): string | null {
  return identiteDepuisEtat(etat)?.personne ?? null;
}
