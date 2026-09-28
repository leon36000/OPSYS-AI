import { estStatutReessayable } from "./classification";
import type { CorpsReponseOutilsInvoke, ErreurOutilsInvoke, RequeteOutilsInvoke } from "./types";

export interface EchecAppelOutil {
  readonly origine: "reseau" | "delai" | "http";
  readonly reessayable: boolean;
  readonly message: string;
  readonly status?: number;
  readonly erreur?: ErreurOutilsInvoke;
}

export type ResultatAppelOutil<R = unknown> =
  | { readonly ok: true; readonly result: R }
  | { readonly ok: false; readonly echec: EchecAppelOutil };

export interface ParametresAppelOutil {
  /** Injecté : jamais `globalThis.fetch` en dur, pour rester testable (mission item 5). */
  readonly fetchImpl: typeof fetch;
  /** Ex. `https://grs.exemple.opsys-ai.ca` — sans le `/tools/invoke` final. */
  readonly urlBase: string;
  readonly jeton: string;
  readonly requete: RequeteOutilsInvoke;
  readonly delaiMs?: number;
}

const DELAI_PAR_DEFAUT_MS = 15_000;

/**
 * Client typé de `POST /tools/invoke` (voir src/protocole/types.ts pour la provenance exacte
 * du contrat, lue dans core/src/gateway/tools-invoke-http.ts et tools-invoke-shared.ts —
 * jamais exécuté ici, seulement lu : le core ne se construit/teste qu'en CI, ADR-0008).
 *
 * `idempotencyKey` doit porter le `mutation_id` de src/outbox pour tout appel émis par la file
 * sortante. Classement des échecs : réseau/délai et 408/429/5xx -> réessayable ; les autres
 * 4xx -> permanent (src/protocole/classification.ts).
 */
export async function invoquerOutil<R = unknown>(params: ParametresAppelOutil): Promise<ResultatAppelOutil<R>> {
  const { fetchImpl, urlBase, jeton, requete, delaiMs = DELAI_PAR_DEFAUT_MS } = params;
  const controleur = new AbortController();
  const minuteur = setTimeout(() => controleur.abort(), delaiMs);

  let reponse: Response;
  try {
    reponse = await fetchImpl(`${urlBase}/tools/invoke`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${jeton}`,
      },
      body: JSON.stringify(requete),
      signal: controleur.signal,
    });
  } catch (erreur) {
    const delaiDepasse = erreur instanceof Error && erreur.name === "AbortError";
    return {
      ok: false,
      echec: {
        origine: delaiDepasse ? "delai" : "reseau",
        reessayable: true, // réseau et délai sont toujours réessayables (mission item 5)
        message: erreur instanceof Error ? erreur.message : String(erreur),
      },
    };
  } finally {
    clearTimeout(minuteur);
  }

  let corps: CorpsReponseOutilsInvoke<R> | undefined;
  try {
    corps = (await reponse.json()) as CorpsReponseOutilsInvoke<R>;
  } catch {
    corps = undefined;
  }

  if (reponse.ok && corps?.ok === true) {
    return { ok: true, result: corps.result };
  }

  const erreurCorps = corps && corps.ok === false ? corps.error : undefined;
  return {
    ok: false,
    echec: {
      origine: "http",
      // Le fork classe ses réponses ok:false par code HTTP (400/403/404/500) ; on applique la
      // même règle 408/429/5xx que pour le réseau, "selon ce que le code du fork renvoie".
      reessayable: estStatutReessayable(reponse.status),
      message: erreurCorps?.message ?? `réponse HTTP ${reponse.status} inattendue`,
      status: reponse.status,
      erreur: erreurCorps,
    },
  };
}
