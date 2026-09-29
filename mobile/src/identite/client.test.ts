import { lireIdentiteServeur } from "./client";

const APPAREIL = "a".repeat(64);

function fausseReponse(status: number, corps: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (corps === undefined) {
        throw new SyntaxError("Unexpected token < in JSON");
      }
      return corps;
    },
  } as unknown as Response;
}

const IDENTITE_VALIDE = { ok: true, identite: { appareilId: APPAREIL, personne: "jdupont", role: "employee" } };

describe("lireIdentiteServeur — la requête envoyée", () => {
  test("GET <urlBase>/opsys/identite avec le seul jeton d'appareil : ni corps, ni identifiant, ni personne, ni rôle", async () => {
    const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => fausseReponse(200, IDENTITE_VALIDE));

    await lireIdentiteServeur({ fetchImpl, urlBase: "https://grs.exemple.ca", jeton: "jeton-secret", appareilId: APPAREIL });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    if (!init) {
      throw new Error("attendu : un RequestInit passé à fetch");
    }
    expect(url).toBe("https://grs.exemple.ca/opsys/identite");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(init.headers).toEqual({ accept: "application/json", authorization: "Bearer jeton-secret" });
    // L'appareil de la session ne sert qu'à confronter la réponse : il ne part pas dans la requête.
    expect(String(url)).not.toContain(APPAREIL);
  });
});

describe("lireIdentiteServeur — le résultat", () => {
  test("200 avec une identité complète -> confirmée", async () => {
    const fetchImpl = jest.fn(async () => fausseReponse(200, IDENTITE_VALIDE));
    await expect(lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL })).resolves.toEqual({
      genre: "confirmee",
      identite: { appareilId: APPAREIL, personne: "jdupont", role: "employee" },
    });
  });

  test("200 pour un autre appareil -> refusée", async () => {
    const fetchImpl = jest.fn(async () =>
      fausseReponse(200, { ok: true, identite: { appareilId: "b".repeat(64), personne: "jdupont", role: "employee" } }),
    );
    await expect(lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL })).resolves.toEqual({
      genre: "refusee",
      motif: "reponse_invalide",
    });
  });

  test("403 device_unknown -> appareil non attribué", async () => {
    const fetchImpl = jest.fn(async () =>
      fausseReponse(403, { ok: false, error: { type: "forbidden", reason: "device_unknown", message: "x" } }),
    );
    await expect(lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL })).resolves.toEqual({
      genre: "refusee",
      motif: "appareil_non_attribue",
    });
  });

  test("401 -> jeton refusé", async () => {
    const fetchImpl = jest.fn(async () => fausseReponse(401, { error: { type: "unauthorized" } }));
    await expect(lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL })).resolves.toEqual({
      genre: "refusee",
      motif: "jeton_refuse",
    });
  });

  test("503 avec un corps illisible -> indisponible", async () => {
    const fetchImpl = jest.fn(async () => fausseReponse(503, undefined));
    const resultat = await lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL });
    expect(resultat.genre).toBe("indisponible");
  });

  test("200 dont le corps n'est pas du JSON -> indisponible, jamais un refus ni un profil", async () => {
    const fetchImpl = jest.fn(async () => fausseReponse(200, undefined));
    const resultat = await lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL });
    expect(resultat.genre).toBe("indisponible");
  });

  test("réseau coupé (fetch rejette) -> indisponible, ne lève jamais", async () => {
    const fetchImpl = jest.fn(async () => {
      throw new TypeError("Network request failed");
    });
    await expect(lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL })).resolves.toEqual({
      genre: "indisponible",
      message: "Network request failed",
    });
  });

  test("délai dépassé (AbortError) -> indisponible", async () => {
    const fetchImpl = jest.fn(async () => {
      const erreur = new Error("The operation was aborted");
      erreur.name = "AbortError";
      throw erreur;
    });
    await expect(
      lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL, delaiMs: 5 }),
    ).resolves.toEqual({ genre: "indisponible", message: "délai dépassé" });
  });

  test("le délai coupe réellement une requête qui ne répond jamais (signal d'annulation)", async () => {
    const fetchImpl = jest.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const erreur = new Error("aborted");
            erreur.name = "AbortError";
            reject(erreur);
          });
        }),
    );
    const resultat = await lireIdentiteServeur({ fetchImpl, urlBase: "https://x", jeton: "t", appareilId: APPAREIL, delaiMs: 10 });
    expect(resultat).toEqual({ genre: "indisponible", message: "délai dépassé" });
  });
});
