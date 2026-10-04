import { invoquerOutil } from "./client";
import type { RequeteOutilsInvoke } from "./types";

function fausseReponse(status: number, corps: unknown, ok = status >= 200 && status < 300): Response {
  return {
    ok,
    status,
    json: async () => corps,
  } as unknown as Response;
}

const REQUETE: RequeteOutilsInvoke = {
  tool: "m4_pointer_entree",
  args: { chantierId: "c1" },
  sessionKey: "main",
  idempotencyKey: "mutation-abc-123",
};

describe("invoquerOutil — forme de la requête envoyée", () => {
  test("POST vers <urlBase>/tools/invoke, en-tête Bearer, corps = requête telle quelle", async () => {
    const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      fausseReponse(200, { ok: true, result: { statut: "pointe" } }),
    );

    await invoquerOutil({
      fetchImpl,
      urlBase: "https://grs.exemple.ca",
      jeton: "jeton-secret",
      requete: REQUETE,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    if (!init) {
      throw new Error("attendu : invoquerOutil doit toujours passer un RequestInit à fetch");
    }
    expect(url).toBe("https://grs.exemple.ca/tools/invoke");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "content-type": "application/json",
      authorization: "Bearer jeton-secret",
    });
    expect(JSON.parse(init.body as string)).toEqual(REQUETE);
  });
});

describe("invoquerOutil — succès", () => {
  test("ok:true HTTP 200 -> { ok: true, result }", async () => {
    const fetchImpl = jest.fn(async () => fausseReponse(200, { ok: true, result: { statut: "pointe" } }));
    const resultat = await invoquerOutil({ fetchImpl, urlBase: "https://x", jeton: "t", requete: REQUETE });
    expect(resultat).toEqual({ ok: true, result: { statut: "pointe" } });
  });
});

describe("invoquerOutil — délai et erreur pendant le corps", () => {
  test("le délai couvre la lecture du corps après les en-têtes", async () => {
    let signal: AbortSignal | undefined;
    const fetchImpl = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      signal = init?.signal as AbortSignal;
      return { ok: true, status: 200, json: () => new Promise(() => undefined) } as unknown as Response;
    });
    const resultat = await Promise.race([
      invoquerOutil({ fetchImpl, urlBase: "https://x", jeton: "t", requete: REQUETE, delaiMs: 20 }),
      new Promise<"pending">((resolve) => setTimeout(() => resolve("pending"), 80)),
    ]);
    expect(resultat).not.toBe("pending");
    expect(signal?.aborted).toBe(true);
    if (resultat !== "pending") {
      expect(resultat).toMatchObject({ ok: false, echec: { origine: "delai", reessayable: true } });
    }
  });

  test("rupture du corps HTTP 200 est un échec réseau réessayable, pas un succès/permanent", async () => {
    const fetchImpl = jest.fn(async () => ({
      ok: true, status: 200,
      json: async () => { throw new TypeError("terminated"); },
    }) as unknown as Response);
    const resultat = await invoquerOutil({ fetchImpl, urlBase: "https://x", jeton: "t", requete: REQUETE });
    expect(resultat).toMatchObject({ ok: false, echec: { origine: "reseau", reessayable: true } });
  });
});

describe("invoquerOutil — échecs réseau/délai (toujours réessayables)", () => {
  test("échec réseau (fetch rejette) -> origine 'reseau', réessayable", async () => {
    const fetchImpl = jest.fn(async () => {
      throw new TypeError("Network request failed");
    });
    const resultat = await invoquerOutil({ fetchImpl, urlBase: "https://x", jeton: "t", requete: REQUETE });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.echec.origine).toBe("reseau");
      expect(resultat.echec.reessayable).toBe(true);
    }
  });

  test("délai dépassé (AbortError) -> origine 'delai', réessayable", async () => {
    const fetchImpl = jest.fn(async () => {
      const erreur = new Error("The operation was aborted");
      erreur.name = "AbortError";
      throw erreur;
    });
    const resultat = await invoquerOutil({ fetchImpl, urlBase: "https://x", jeton: "t", requete: REQUETE, delaiMs: 5 });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.echec.origine).toBe("delai");
      expect(resultat.echec.reessayable).toBe(true);
    }
  });
});

describe("invoquerOutil — échecs HTTP classés selon le code (core/src/gateway)", () => {
  test.each([
    [500, "tool_error", true],
    [429, "invalid_request", true], // 429 n'est pas émis par le fork lui-même, mais un proxy/limiteur en amont peut le renvoyer
    [408, "invalid_request", true],
    [400, "invalid_request", false],
    [403, "tool_call_blocked", false],
    [404, "not_found", false],
  ] as const)("HTTP %i (%s) -> réessayable=%s", async (status, type, reessayable) => {
    const fetchImpl = jest.fn(async () =>
      fausseReponse(status, { ok: false, error: { type, message: `échec ${type}` } }),
    );
    const resultat = await invoquerOutil({ fetchImpl, urlBase: "https://x", jeton: "t", requete: REQUETE });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.echec.origine).toBe("http");
      expect(resultat.echec.status).toBe(status);
      expect(resultat.echec.reessayable).toBe(reessayable);
      expect(resultat.echec.erreur).toEqual({ type, message: `échec ${type}` });
    }
  });

  test("corps non-JSON ou inattendu -> classé par le seul code HTTP, sans planter", async () => {
    const fetchImpl = jest.fn(async () => ({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error("pas du JSON");
      },
    }) as unknown as Response);
    const resultat = await invoquerOutil({ fetchImpl, urlBase: "https://x", jeton: "t", requete: REQUETE });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.echec.status).toBe(502);
      expect(resultat.echec.reessayable).toBe(true);
    }
  });
});
