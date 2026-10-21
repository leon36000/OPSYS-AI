import { CHEMIN_IDENTITE, interpreterReponseIdentite, type ResultatLectureIdentite } from "./contrat";

export interface ParametresLectureIdentite {
  /** Injecté : jamais `globalThis.fetch` en dur, pour rester testable (même règle que `invoquerOutil`). */
  readonly fetchImpl: typeof fetch;
  /** Ex. `https://grs.exemple.opsys-ai.ca` — sans le `/opsys/identite` final. */
  readonly urlBase: string;
  readonly jeton: string;
  /** L'appareil de CETTE session : sert à confronter la réponse, jamais à la demander. */
  readonly appareilId: string;
  readonly delaiMs?: number;
}

const DELAI_PAR_DEFAUT_MS = 10_000;

/**
 * Lit auprès du serveur la personne et le rôle nommé de cet appareil (`GET /opsys/identite`).
 *
 * La requête ne porte que le jeton d'appareil : ni identifiant, ni personne, ni rôle. Le serveur les
 * tire du jeton vérifié et de `opsys/appareils.json` ; la réponse est confrontée à `appareilId` avant
 * d'être adoptée (`interpreterReponseIdentite`). Ne lève jamais : un réseau coupé ou un délai dépassé
 * est « indisponible », et n'apprend rien sur l'attribution.
 */
export async function lireIdentiteServeur(params: ParametresLectureIdentite): Promise<ResultatLectureIdentite> {
  const { fetchImpl, urlBase, jeton, appareilId, delaiMs = DELAI_PAR_DEFAUT_MS } = params;
  const controleur = new AbortController();
  const minuteur = setTimeout(() => controleur.abort(), delaiMs);
  try {
    let reponse: Response;
    try {
      reponse = await fetchImpl(`${urlBase}${CHEMIN_IDENTITE}`, {
        method: "GET",
        headers: { accept: "application/json", authorization: `Bearer ${jeton}` },
        signal: controleur.signal,
      });
    } catch (erreur) {
      const delaiDepasse = erreur instanceof Error && erreur.name === "AbortError";
      return {
        genre: "indisponible",
        message: delaiDepasse ? "délai dépassé" : erreur instanceof Error ? erreur.message : String(erreur),
      };
    }
    let corps: unknown;
    try {
      corps = await reponse.json();
    } catch {
      corps = undefined;
    }
    return interpreterReponseIdentite(reponse.status, corps, appareilId);
  } finally {
    clearTimeout(minuteur);
  }
}
