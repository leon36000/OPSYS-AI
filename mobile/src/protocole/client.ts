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
  let reponse: Response | null = null;
  let minuteur: ReturnType<typeof setTimeout> | undefined;
  let rejeterDelai!: (erreur: Error) => void;
  const delai = new Promise<never>((_resolve, reject) => { rejeterDelai = reject; });
  minuteur = setTimeout(() => {
    controleur.abort();
    const erreur = new Error("délai dépassé pendant l'appel outil");
    erreur.name = "AbortError";
    rejeterDelai(erreur);
  }, delaiMs);
  try {
    reponse = await Promise.race([fetchImpl(`${urlBase}/tools/invoke`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${jeton}`,
      },
      body: JSON.stringify(requete),
      signal: controleur.signal,
    }), delai]);
    const corps = (await Promise.race([reponse.json(), delai])) as CorpsReponseOutilsInvoke<R>;
    if (reponse.ok && corps?.ok === true) return { ok: true, result: corps.result };
    const erreurCorps = corps && corps.ok === false ? corps.error : undefined;
    return {
      ok: false,
      echec: {
        origine: "http",
        reessayable: estStatutReessayable(reponse.status),
        message: erreurCorps?.message ?? `réponse HTTP ${reponse.status} inattendue`,
        status: reponse.status,
        erreur: erreurCorps,
      },
    };
  } catch (erreur) {
    const delaiDepasse = erreur instanceof Error && erreur.name === "AbortError";
    if (reponse && !reponse.ok) {
      return {
        ok: false,
        echec: { origine: "http", reessayable: estStatutReessayable(reponse.status), message: `lecture de la réponse HTTP ${reponse.status} interrompue`, status: reponse.status },
      };
    }
    return {
      ok: false,
      echec: {
        origine: delaiDepasse ? "delai" : "reseau",
        reessayable: true, // réseau et délai sont toujours réessayables (mission item 5)
        message: erreur instanceof Error ? erreur.message : String(erreur),
      },
    };
  } finally {
    if (minuteur !== undefined) clearTimeout(minuteur);
  }
}
