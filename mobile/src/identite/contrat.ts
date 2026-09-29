import { estStatutReessayable } from "../protocole/classification";

/**
 * Identité OPSYS de l'appareil (PLAN T1.4-c5) : la personne et le rôle NOMMÉ auxquels le serveur a
 * attribué cet appareil. Contrat de `GET /opsys/identite`, lu dans le code du core (lecture seule,
 * ADR-0008) : `core/src/gateway/opsys-device-identity-http.ts`.
 *
 * Ce que le serveur rend :
 *  - 200 `{ ok: true, identite: { appareilId, personne, role } }` ;
 *  - 401 : jeton d'appareil inconnu ou révoqué ;
 *  - 403 `{ ok: false, error: { type: "forbidden", reason, message } }`, `reason` parmi
 *    `device_unknown` (aucune attribution : jamais faite, ou révoquée), `role_unknown` (rôle non
 *    déclaré par la passerelle) et `device_required` (le secret partagé n'est pas un appareil) ;
 *  - 408, 429, 5xx : réessayable.
 *
 * L'identité vient toujours du serveur, jamais de l'app : la requête ne porte que le jeton.
 */

/** Les rôles nommés d'un appareil (`src/opsys/appareils.py::ROLES_APPAREIL`). `client` n'en est pas
 * un : le client passe par un lien signé, jamais par un appareil apparié. */
export type RoleNomme = "admin" | "employee" | "seller";

export const ROLES_NOMMES: readonly RoleNomme[] = ["admin", "employee", "seller"];

/** Égalité stricte : `"ADMIN"`, `"admin "` et `"operator"` (le rôle de transport du fork) ne sont pas des rôles nommés. */
export function estRoleNomme(valeur: unknown): valeur is RoleNomme {
  return typeof valeur === "string" && (ROLES_NOMMES as readonly string[]).includes(valeur);
}

export interface IdentiteOpsys {
  /** Identifiant de l'appareil (`deviceId`) auquel cette identité a été attribuée. */
  readonly appareilId: string;
  /** Identifiant OPSYS de la personne (`personnes.identifiant`), tel que le serveur le confronte. */
  readonly personne: string;
  readonly role: RoleNomme;
}

export const CHEMIN_IDENTITE = "/opsys/identite";

export type MotifRefusIdentite =
  /** 403 `device_unknown` : appairé côté passerelle, mais aucune attribution OPSYS (ou révoquée). */
  | "appareil_non_attribue"
  /** 403 `role_unknown`, ou un rôle que cette app ne connaît pas : aucun profil, jamais un défaut. */
  | "role_inconnu"
  /** 401 : jeton d'appareil inconnu ou révoqué. */
  | "jeton_refuse"
  /** Un autre refus (403 sans raison connue, 404 d'un core plus ancien, autre 4xx). */
  | "refus_inattendu"
  /** 200 dont le corps JSON n'est pas une identité : forme inconnue, ou identité d'un autre appareil. */
  | "reponse_invalide";

export type ResultatLectureIdentite =
  | { readonly genre: "confirmee"; readonly identite: IdentiteOpsys }
  /** Le serveur a répondu, et il n'y a pas d'identité pour cet appareil. À ne jamais contourner. */
  | { readonly genre: "refusee"; readonly motif: MotifRefusIdentite }
  /** Réseau, délai, 408, 429, 5xx, corps illisible : on ne sait pas. Ne dit rien sur l'attribution. */
  | { readonly genre: "indisponible"; readonly message: string };

function enObjet(valeur: unknown): Record<string, unknown> | null {
  return typeof valeur === "object" && valeur !== null && !Array.isArray(valeur)
    ? (valeur as Record<string, unknown>)
    : null;
}

function refusee(motif: MotifRefusIdentite): ResultatLectureIdentite {
  return { genre: "refusee", motif };
}

function interpreterSucces(corps: unknown, appareilId: string): ResultatLectureIdentite {
  // `undefined` ne sort jamais d'un JSON : c'est un corps illisible (portail captif, proxy). Le serveur n'a
  // rien dit sur l'attribution, comme un réseau coupé.
  if (corps === undefined) {
    return { genre: "indisponible", message: "corps de réponse illisible" };
  }
  const racine = enObjet(corps);
  if (!racine || racine.ok !== true) {
    return refusee("reponse_invalide");
  }
  const identite = enObjet(racine.identite);
  if (!identite) {
    return refusee("reponse_invalide");
  }
  // Une identité rendue pour un autre appareil n'est jamais adoptée, même bien formée.
  if (identite.appareilId !== appareilId) {
    return refusee("reponse_invalide");
  }
  const { personne, role } = identite;
  if (typeof personne !== "string" || personne.trim() === "" || typeof role !== "string") {
    return refusee("reponse_invalide");
  }
  if (!estRoleNomme(role)) {
    return refusee("role_inconnu");
  }
  return { genre: "confirmee", identite: { appareilId, personne, role } };
}

function lireRaisonRefus(corps: unknown): string | null {
  const erreur = enObjet(enObjet(corps)?.error);
  return typeof erreur?.reason === "string" ? erreur.reason : null;
}

/**
 * Classe la réponse du serveur. Fail-closed : seule une identité complète, d'un rôle nommé connu et de
 * CET appareil, est « confirmée ». Tout ce que le serveur refuse ou rend de travers est « refusée » (le
 * profil se retire) ; seul ce qui n'a rien dit (réseau, délai, 408, 429, 5xx, corps illisible) est
 * « indisponible », et garde la dernière identité confirmée, marquée à reconfirmer.
 */
export function interpreterReponseIdentite(
  status: number,
  corps: unknown,
  appareilId: string,
): ResultatLectureIdentite {
  if (status === 200) {
    return interpreterSucces(corps, appareilId);
  }
  if (status === 401) {
    return refusee("jeton_refuse");
  }
  if (status === 403) {
    const raison = lireRaisonRefus(corps);
    if (raison === "device_unknown") {
      return refusee("appareil_non_attribue");
    }
    if (raison === "role_unknown") {
      return refusee("role_inconnu");
    }
    return refusee("refus_inattendu");
  }
  if (estStatutReessayable(status)) {
    return { genre: "indisponible", message: `réponse HTTP ${status}` };
  }
  return refusee("refus_inattendu");
}
