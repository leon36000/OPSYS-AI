import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Model } from "../llm/types.js";
import type {
  PluginManifestModelIdNormalizationProvider,
  PluginManifestProviderRequestProvider,
} from "../plugins/manifest-types.js";
import type { PluginMetadataSnapshotOwnerMaps } from "../plugins/plugin-metadata-snapshot.types.js";

// Fictitious HTTP fixtures only. These counters are not provider or M9 evidence.
const fixture = vi.hoisted(() => {
  const fetch = vi.fn<typeof globalThis.fetch>();
  const localService = vi.fn<() => Promise<undefined>>();
  return { fetch, localService };
});

// Only the local-service dependency is replaced, to hold a preparation await.
vi.mock("./provider-local-service.js", () => {
  const unexpected = () => {
    throw new Error("unexpected local-service fixture dependency");
  };
  return {
    ensureModelProviderLocalService: fixture.localService,
    createConfiguredProviderLocalServiceAcquirer: unexpected,
    attachModelProviderLocalService: unexpected,
    getModelProviderLocalService: unexpected,
    ensureProviderLocalService: unexpected,
    stopManagedProviderLocalServices: unexpected,
    getManagedProviderLocalServiceDiagnosticsForTest: unexpected,
  };
});

import { fetchWithSsrFGuard } from "../infra/net/fetch-guard.js";
import { withGuardedFetchRequestAuthority } from "../infra/net/fetch-request-authority.js";
import {
  capturePrivateProviderRequestFence,
  withPrivateSingleProviderRequest,
} from "./private-single-provider-request.js";
import { attachModelProviderRequestRouteFacts } from "./provider-request-config.js";
import { buildGuardedModelFetch } from "./provider-transport-fetch.js";

const url = "https://public.example/v1/responses";
// Fictitious prepared routing generation only; no runtime/catalogue, grant or credential.
const fixtureMetadataOwners: PluginMetadataSnapshotOwnerMaps = {
  channels: new Map<string, readonly string[]>(),
  channelConfigs: new Map<string, readonly string[]>(),
  providers: new Map<string, readonly string[]>(),
  modelCatalogProviders: new Map<string, readonly string[]>(),
  cliBackends: new Map<string, readonly string[]>(),
  setupProviders: new Map<string, readonly string[]>(),
  commandAliases: new Map<string, readonly string[]>(),
  contracts: new Map<string, readonly string[]>(),
  modelIdNormalizationPolicies: new Map<string, PluginManifestModelIdNormalizationProvider>(),
  providerAuthContributions: [],
  providerEndpoints: [
    {
      endpointClass: "custom",
      hosts: ["public.example"],
      baseUrls: ["https://public.example/v1"],
    },
  ],
  providerRequests: new Map<string, PluginManifestProviderRequestProvider>([
    ["openai", { family: "openai-family" }],
  ]),
};

const unpreparedModel = {
  id: "fictitious-private-http-model",
  name: "Fictitious private HTTP model",
  provider: "openai",
  api: "openai-responses",
  baseUrl: "https://public.example/v1",
  reasoning: false,
  input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 4096,
  maxTokens: 128,
} satisfies Model<"openai-responses">;
const model = attachModelProviderRequestRouteFacts(unpreparedModel, fixtureMetadataOwners);
const route = { provider: model.provider, modelId: model.id, sourceApi: model.api, url };
const init = {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: '{"fictif":true}',
};
const refusal = /M9_SINGLE_PROVIDER_REQUEST_/;

function deferred<T>() {
  let resolve: (value: T | PromiseLike<T>) => void = () => {
    throw new Error("fixture deferred was not initialized");
  };
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function runPrivate<T>(
  run: () => Promise<T>,
  assertCurrent: () => void = () => {},
  signal: AbortSignal = new AbortController().signal,
): Promise<T> {
  return withPrivateSingleProviderRequest({ assertCurrent, signal, route }, run);
}

function requiredFence() {
  const fence = capturePrivateProviderRequestFence();
  if (fence === undefined) {
    throw new Error("fixture expected the active private restriction");
  }
  return fence;
}

async function read(fetch: typeof globalThis.fetch = buildGuardedModelFetch(model)) {
  if (globalThis.fetch !== fixture.fetch) {
    throw new Error("fictitious HTTP fixture lost transport ownership");
  }
  const response = await fetch(url, init);
  return await response.text();
}

beforeEach(() => {
  vi.stubGlobal("fetch", fixture.fetch);
  for (const key of [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
  ]) {
    vi.stubEnv(key, "");
  }
  vi.stubEnv("NO_PROXY", "*");
  vi.stubEnv("no_proxy", "*");
  vi.stubEnv("OPENCLAW_DEBUG_PROXY_ENABLED", "0");
  fixture.fetch
    .mockReset()
    .mockImplementation(
      async () =>
        new Response('{"fictif":true}', { headers: { "content-type": "application/json" } }),
    );
  fixture.localService.mockReset().mockResolvedValue(undefined);
});

afterAll(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("private provider HTTP restriction only", () => {
  it("preserves two ordinary provider fetch effects outside a private scope", async () => {
    const fetch = buildGuardedModelFetch(model);
    await read(fetch);
    await read(fetch);
    expect(fixture.fetch).toHaveBeenCalledTimes(2);
  });

  it("allows one private outward effect and refuses the second effect", async () => {
    await runPrivate(async () => {
      const fetch = buildGuardedModelFetch(model);
      await read(fetch);
      await expect(read(fetch)).rejects.toThrow(refusal);
    });
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });

  it("keeps the first claim spent after the outward fetch rejects", async () => {
    fixture.fetch.mockRejectedValueOnce(new Error("fictitious transport rejection"));
    await runPrivate(async () => {
      const fetch = buildGuardedModelFetch(model);
      await expect(read(fetch)).rejects.toThrow("fictitious transport rejection");
      await expect(read(fetch)).rejects.toThrow(refusal);
    });
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });

  it("fences a provider fetch constructed before entering the private scope", async () => {
    const cached = buildGuardedModelFetch(model);
    await runPrivate(async () => {
      await read(cached);
      await expect(read(cached)).rejects.toThrow(refusal);
    });
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });

  it("does not downgrade a fetch retaining a closed construction scope", async () => {
    const retained = await runPrivate(async () => buildGuardedModelFetch(model));
    await expect(read(retained)).rejects.toThrow(refusal);
    expect(fixture.fetch).not.toHaveBeenCalled();
    await read();
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });

  it("shares one claim across separate builders and concurrent fetch calls", async () => {
    await runPrivate(async () => {
      const results = await Promise.allSettled([
        read(buildGuardedModelFetch(model)),
        read(buildGuardedModelFetch(model)),
      ]);
      expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
      const rejected = results.filter((result) => result.status === "rejected");
      expect(rejected).toHaveLength(1);
      for (const result of rejected) {
        expect(result.reason).toBeInstanceOf(Error);
        expect(String(result.reason)).toMatch(refusal);
      }
      await expect(read(buildGuardedModelFetch(model))).rejects.toThrow(refusal);
    });
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });

  it("rechecks source authority after awaited local service preparation", async () => {
    const entered = deferred<void>();
    const release = deferred<void>();
    let current = true;
    fixture.localService.mockImplementation(async () => {
      entered.resolve();
      await release.promise;
      return undefined;
    });
    const operation = runPrivate(
      async () => {
        const pending = read();
        await entered.promise;
        current = false;
        release.resolve();
        await expect(pending).rejects.toThrow("fictitious source revoked");
      },
      () => {
        if (!current) {
          throw new Error("fictitious source revoked");
        }
      },
    );
    await operation;
    expect(fixture.localService).toHaveBeenCalledOnce();
    expect(fixture.fetch).not.toHaveBeenCalled();
  });

  it("rechecks abort after awaited local service preparation", async () => {
    const entered = deferred<void>();
    const release = deferred<void>();
    const controller = new AbortController();
    fixture.localService.mockImplementation(async () => {
      entered.resolve();
      await release.promise;
      return undefined;
    });
    await runPrivate(
      async () => {
        const pending = read();
        await entered.promise;
        controller.abort(new Error("fictitious private abort"));
        release.resolve();
        await expect(pending).rejects.toThrow("fictitious private abort");
      },
      () => {},
      controller.signal,
    );
    expect(fixture.fetch).not.toHaveBeenCalled();
  });

  it("refuses a bound outer fetch in a distinct nested private scope", async () => {
    await runPrivate(async () => {
      const boundOuter = buildGuardedModelFetch(model);
      await expect(runPrivate(async () => read(boundOuter))).rejects.toThrow(refusal);
    });
    expect(fixture.fetch).not.toHaveBeenCalled();
  });

  it("refuses a second same-origin redirect effect through the real fetch guard", async () => {
    fixture.fetch.mockResolvedValueOnce(
      new Response(null, {
        status: 307,
        headers: { location: "https://public.example/v1/redirected-responses" },
      }),
    );
    await runPrivate(async () => {
      const fence = requiredFence();
      fence.validateFetch(model, url, init);
      await expect(
        fetchWithSsrFGuard({
          url,
          init,
          fetchImpl: fixture.fetch,
          beforeRequest: () => fence.claim(),
        }),
      ).rejects.toThrow(refusal);
    });
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });

  it("rechecks source after a deferred lookup before the real guard effect", async () => {
    const entered = deferred<void>();
    const release = deferred<void>();
    let current = true;
    await runPrivate(
      async () => {
        const fence = requiredFence();
        fence.validateFetch(model, url, init);
        const pending = fetchWithSsrFGuard({
          url,
          init,
          fetchImpl: fixture.fetch,
          lookupFn: async () => {
            entered.resolve();
            await release.promise;
            return [{ address: "93.184.216.34", family: 4 }];
          },
          beforeRequest: () => fence.claim(),
        });
        await entered.promise;
        current = false;
        release.resolve();
        await expect(pending).rejects.toThrow("fictitious source revoked");
      },
      () => {
        if (!current) {
          throw new Error("fictitious source revoked");
        }
      },
    );
    expect(fixture.fetch).not.toHaveBeenCalled();
  });

  it("keeps repeated readonly validation free while awaiting the owned result", async () => {
    const release = deferred<void>();
    const entered = deferred<void>();
    fixture.fetch.mockImplementation(async () => {
      entered.resolve();
      await release.promise;
      return new Response('{"fictif":true}');
    });
    await runPrivate(async () => {
      const fence = requiredFence();
      for (let index = 0; index < 4; index += 1) {
        fence.validateFetch(model, url, init);
      }
      const pending = read();
      await entered.promise;
      fence.validateFetch(model, url, init);
      release.resolve();
      expect(await pending).toBe('{"fictif":true}');
    });
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });
  it("refuses a second redirect effect through the real provider fetch builder", async () => {
    fixture.fetch.mockResolvedValueOnce(
      new Response(null, {
        status: 307,
        headers: { location: "https://public.example/v1/redirected-responses" },
      }),
    );
    await runPrivate(async () => {
      const fetch = buildGuardedModelFetch(model);
      await expect(read(fetch)).rejects.toThrow(refusal);
    });
    expect(fixture.fetch).toHaveBeenCalledOnce();
  });

  it("refuses an inherited-authority abort after the private claim before HTTP emission", async () => {
    const controller = new AbortController();
    const abortReason = new Error("fictitious inherited post-claim abort");
    let sourceChecks = 0;
    let armed = false;
    const results = await Promise.allSettled([
      withGuardedFetchRequestAuthority(
        () => {
          if (armed) {
            controller.abort(abortReason);
          }
        },
        async () =>
          runPrivate(
            async () => {
              // Deliberately keep the private signal out of RequestInit.
              const fetch = buildGuardedModelFetch(model);
              await read(fetch);
            },
            () => {
              sourceChecks += 1;
              if (sourceChecks === 4) {
                armed = true;
              }
            },
            controller.signal,
          ),
      ),
    ]);
    expect(controller.signal.aborted).toBe(true);
    expect(sourceChecks).toBeGreaterThanOrEqual(4);
    expect(fixture.fetch).not.toHaveBeenCalled();
    expect(results).toEqual([{ status: "rejected", reason: abortReason }]);
  });

  it("rejects ordinary HTTP when beforeRequest revokes inherited authority", async () => {
    let current = true;
    await expect(
      withGuardedFetchRequestAuthority(
        () => {
          if (!current) {
            throw new Error("fictitious inherited authority revoked");
          }
        },
        async () =>
          fetchWithSsrFGuard({
            url,
            init,
            fetchImpl: fixture.fetch,
            beforeRequest: () => {
              current = false;
            },
          }),
      ),
    ).rejects.toThrow("fictitious inherited authority revoked");
    expect(fixture.fetch).not.toHaveBeenCalled();
  });

  it("rejects ordinary HTTP when capture metadata revokes inherited authority after the hook", async () => {
    const authorityError = new Error("fictitious inherited authority revoked by capture metadata");
    let current = true;
    let armed = false;
    let reads = 0;
    const meta = {
      get fictitiousCaptureValue() {
        reads += 1;
        if (armed) {
          current = false;
        }
        return "fictitious capture metadata";
      },
    };
    const results = await Promise.allSettled([
      withGuardedFetchRequestAuthority(
        () => {
          if (!current) {
            throw authorityError;
          }
        },
        async () =>
          fetchWithSsrFGuard({
            url,
            init,
            fetchImpl: fixture.fetch,
            capture: { meta },
            beforeRequest: () => {
              armed = true;
            },
          }),
      ),
    ]);
    for (const result of results) {
      if (result.status === "fulfilled") {
        await result.value.release();
      }
    }
    expect(reads).toBe(1);
    expect(current).toBe(false);
    expect(fixture.fetch).not.toHaveBeenCalled();
    expect(results).toEqual([{ status: "rejected", reason: authorityError }]);
  });
});
