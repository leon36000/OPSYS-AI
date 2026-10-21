import fs from "node:fs/promises";
import { describe, expect, it, vi } from "vitest";
import { requireNodeSqlite } from "../infra/node-sqlite.js";
import { closeOpenClawStateDatabaseAsync } from "../state/openclaw-state-db.js";
import { captureOpenClawStateWorkerContext } from "../state/openclaw-state-worker-context.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import {
  operatorMcpOAuthIdentity,
  requesterMcpOAuthIdentity,
  requesterMcpOAuthStoreKeyPrefix,
} from "./mcp-oauth-identity.js";
import { createMcpOAuthClientProvider } from "./mcp-oauth-provider.js";
import {
  listMcpOAuthStoreKeysByPrefix,
  readMcpOAuthPendingAuthorization,
  readMcpOAuthStore,
  readMcpOAuthStoreReadOnly,
  type McpOAuthStore,
} from "./mcp-oauth-store.js";
import { countMcpOAuthPrincipals } from "./mcp-oauth.js";
import { seedMcpOAuthStoreForTest, withMcpOAuthProviderForTest } from "./mcp-oauth.test-support.js";

describe("MCP OAuth worker reads", () => {
  it.each([undefined, "", " ", "not-an-issuer"])(
    "withholds a client secret without a valid stored issuer (%s) before and after rediscovery",
    async (issuer) => {
      await withOpenClawTestState({ prefix: "openclaw-mcp-oauth-unbound-client-" }, async () => {
        const identity = operatorMcpOAuthIdentity("legacy-client", "https://mcp.example.test/rpc");
        const clientInformation = {
          client_id: "fixture-client",
          client_secret: "fixture-client-secret",
          ...(issuer === undefined ? {} : { issuer }),
        };
        seedMcpOAuthStoreForTest(identity.storeKey, { clientInformation });
        await withMcpOAuthProviderForTest({ identity }, async (provider) => {
          expect(await provider.clientInformation()).toBeUndefined();
          await provider.saveDiscoveryState?.({
            authorizationServerUrl: "https://replacement-issuer.example.test",
          });
          expect(await provider.clientInformation()).toBeUndefined();
        });
        expect((await readMcpOAuthStore(identity.storeKey)).clientInformation).toEqual(
          clientInformation,
        );
      });
    },
  );

  it("preserves issuer-bound client information and tokens through save and store reopen", async () => {
    await withOpenClawTestState({ prefix: "openclaw-mcp-oauth-bound-client-" }, async () => {
      const identity = operatorMcpOAuthIdentity("bound-client", "https://mcp.example.test/rpc");
      const clientInformation = {
        client_id: "fixture-client",
        client_secret: "fixture-client-secret",
        issuer: "https://issuer.example.test",
        vendor_extension: "fixture-client-extension",
      };
      const tokens = {
        access_token: "fixture-access",
        refresh_token: "fixture-refresh",
        token_type: "Bearer",
        issuer: clientInformation.issuer,
      };
      await withMcpOAuthProviderForTest({ identity }, async (provider) => {
        await provider.saveDiscoveryState?.({ authorizationServerUrl: clientInformation.issuer });
        await provider.saveClientInformation?.(clientInformation);
        await provider.saveTokens(tokens);
        expect(await provider.clientInformation()).toEqual(clientInformation);
        expect(await provider.tokens()).toEqual(tokens);
      });
      await closeOpenClawStateDatabaseAsync();
      await withMcpOAuthProviderForTest({ identity }, async (provider) => {
        expect(await provider.clientInformation()).toEqual(clientInformation);
        expect(await provider.tokens()).toEqual(tokens);
      });
    });
  });

  it("refuses to bind an existing secret using only newly discovered issuer metadata", async () => {
    await withOpenClawTestState(
      { prefix: "openclaw-mcp-oauth-client-new-discovery-" },
      async () => {
        const identity = operatorMcpOAuthIdentity("unbound-client", "https://mcp.example.test/rpc");
        const original = { client_id: "fixture-client", client_secret: "fixture-client-secret" };
        seedMcpOAuthStoreForTest(identity.storeKey, { clientInformation: original });
        await withMcpOAuthProviderForTest({ identity }, async (provider) => {
          const issuer = "https://replacement-issuer.example.test";
          await provider.saveDiscoveryState?.({ authorizationServerUrl: issuer });
          await expect(
            provider.saveClientInformation?.({ ...original, issuer }),
          ).rejects.toMatchObject({
            message:
              'MCP server "unbound-client" requires explicit OAuth login before replacing stored client information.',
          });
        });
        expect((await readMcpOAuthStore(identity.storeKey)).clientInformation).toEqual(original);
      },
    );
  });

  it("allows background issuer enrichment from previously bound token provenance", async () => {
    await withOpenClawTestState({ prefix: "openclaw-mcp-oauth-client-enrichment-" }, async () => {
      const identity = operatorMcpOAuthIdentity("upgrade-client", "https://mcp.example.test/rpc");
      const original = { client_id: "fixture-client", client_secret: "fixture-client-secret" };
      const issuer = "https://issuer.example.test";
      seedMcpOAuthStoreForTest(identity.storeKey, {
        clientInformation: original,
        tokens: { access_token: "fixture-access", token_type: "Bearer" },
        tokensAuthorizationServerUrl: issuer,
      });
      await withMcpOAuthProviderForTest({ identity }, async (provider) => {
        await provider.saveClientInformation?.({ ...original, issuer });
        expect(await provider.clientInformation()).toEqual({ ...original, issuer });
      });
      expect((await readMcpOAuthStore(identity.storeKey)).clientInformation).toEqual({
        ...original,
        issuer,
      });
    });
  });

  it("allows explicit CLI authorization to replace an existing unbound client", async () => {
    await withOpenClawTestState(
      { prefix: "openclaw-mcp-oauth-client-explicit-login-" },
      async () => {
        const identity = operatorMcpOAuthIdentity("cli-client", "https://mcp.example.test/rpc");
        seedMcpOAuthStoreForTest(identity.storeKey, {
          clientInformation: { client_id: "old-client", client_secret: "old-client-secret-fictif" },
        });
        const replacement = {
          client_id: "replacement-client",
          client_secret: "replacement-client-secret-fictif",
          issuer: "https://issuer.example.test",
        };
        await withMcpOAuthProviderForTest(
          { identity, allowAuthorizationRedirect: true },
          async (provider) => {
            await provider.saveClientInformation?.(replacement);
            expect(await provider.clientInformation()).toEqual(replacement);
          },
        );
        expect((await readMcpOAuthStore(identity.storeKey)).clientInformation).toEqual(replacement);
      },
    );
  });

  it("prepares provider facts and reopens persisted reads without parent SQL", async () => {
    await withOpenClawTestState({ prefix: "openclaw-mcp-oauth-worker-read-" }, async () => {
      const { DatabaseSync, StatementSync } = requireNodeSqlite();
      const operator = operatorMcpOAuthIdentity("worker-read", "https://mcp.example.test/rpc");
      const first = requesterMcpOAuthIdentity(operator.serverName, operator.serverUrl, {
        requesterSenderId: "first",
      });
      const second = requesterMcpOAuthIdentity(operator.serverName, operator.serverUrl, {
        requesterSenderId: "second",
      });
      const outside = requesterMcpOAuthIdentity("other-server", operator.serverUrl, {
        requesterSenderId: "first",
      });
      const prefix = requesterMcpOAuthStoreKeyPrefix(operator.serverName, operator.serverUrl);
      const store: McpOAuthStore = {
        clientInformation: { client_id: "fixture-client" },
        tokens: {
          access_token: "fixture-access",
          refresh_token: "fixture-refresh",
          token_type: "Bearer",
        },
        tokenExpiresAt: Date.now() + 3_600_000,
        tokensAuthorizationServerUrl: "https://issuer.example.test",
        codeVerifier: "fixture-verifier",
        discoveryState: { authorizationServerUrl: "https://issuer.example.test" },
        redirectUrl: "https://gateway.example.test/oauth/mcp/callback",
      };
      for (const identity of [first, second, outside]) {
        seedMcpOAuthStoreForTest(
          identity.storeKey,
          store,
          identity === first ? "fixture-pending-state" : undefined,
        );
      }
      await closeOpenClawStateDatabaseAsync();

      // Capability checks and native fixture writes precede the measured read lifecycle.
      const sql = {
        prepare: vi.spyOn(DatabaseSync.prototype, "prepare"),
        exec: vi.spyOn(DatabaseSync.prototype, "exec"),
        get: vi.spyOn(StatementSync.prototype, "get"),
        all: vi.spyOn(StatementSync.prototype, "all"),
        run: vi.spyOn(StatementSync.prototype, "run"),
        iterate: vi.spyOn(StatementSync.prototype, "iterate"),
      };
      try {
        for (let pass = 0; pass < 2; pass++) {
          await withMcpOAuthProviderForTest(
            {
              identity: first,
              config: { scope: "documents.read" },
            },
            async (provider) => {
              expect(provider.redirectUrl).toBe(store.redirectUrl);
              expect(provider.clientMetadata).toMatchObject({
                redirect_uris: [store.redirectUrl],
                scope: "documents.read",
              });
              expect(await provider.clientInformation()).toEqual(store.clientInformation);
              expect(await provider.tokens()).toEqual(store.tokens);
              expect(await provider.codeVerifier()).toBe(store.codeVerifier);
              expect(await provider.discoveryState?.()).toEqual(store.discoveryState);
            },
          );
          expect(await readMcpOAuthStore(first.storeKey)).toEqual(store);
          expect(await readMcpOAuthStoreReadOnly(first.storeKey)).toEqual(store);
          expect(await listMcpOAuthStoreKeysByPrefix(prefix)).toEqual(
            [first.storeKey, second.storeKey].toSorted(),
          );
          expect(await readMcpOAuthPendingAuthorization("fixture-pending-state")).toBe(
            first.storeKey,
          );
          expect(await countMcpOAuthPrincipals(operator)).toBe(2);
          await closeOpenClawStateDatabaseAsync();
        }
        expect(
          Object.fromEntries(
            Object.entries(sql).map(([name, spy]) => [name, spy.mock.calls.length]),
          ),
        ).toEqual({ prepare: 0, exec: 0, get: 0, all: 0, run: 0, iterate: 0 });
      } finally {
        try {
          await closeOpenClawStateDatabaseAsync();
        } finally {
          for (const spy of Object.values(sql)) {
            spy.mockRestore();
          }
        }
      }
    });
  });

  it("rejects a retired captured store instead of reopening it for a read", async () => {
    await withOpenClawTestState({ prefix: "openclaw-mcp-captured-read-" }, async () => {
      const identity = operatorMcpOAuthIdentity("retired-reader", "https://mcp.example.test/rpc");
      const context = captureOpenClawStateWorkerContext();
      await expect(fs.stat(context.admission.databasePath)).rejects.toMatchObject({
        code: "ENOENT",
      });
      await closeOpenClawStateDatabaseAsync();
      await expect(readMcpOAuthStoreReadOnly(identity.storeKey, context)).rejects.toMatchObject({
        code: "STATE_DATABASE_READ_ADMISSION_INVALIDATED",
      });
      await expect(
        createMcpOAuthClientProvider({
          identity,
          storeContext: context,
          // Read admission must reject before any lease verification can create state.
          lease: {
            signal: new AbortController().signal,
            async assertOwned() {},
            async renew() {},
          },
        }),
      ).rejects.toMatchObject({ code: "STATE_DATABASE_READ_ADMISSION_INVALIDATED" });
      await expect(fs.stat(context.admission.databasePath)).rejects.toMatchObject({
        code: "ENOENT",
      });
    });
  });

  it("keeps the legacy loopback redirect as the default for upgrade compatibility", async () => {
    await withOpenClawTestState({ prefix: "openclaw-mcp-oauth-default-redirect-" }, async () => {
      await withMcpOAuthProviderForTest(
        {
          identity: operatorMcpOAuthIdentity("Calendly", "https://mcp.calendly.com/"),
        },
        async (provider) => {
          expect(provider.clientMetadata.redirect_uris).toEqual([
            "http://127.0.0.1:8989/oauth/callback",
          ]);
          expect(provider.redirectUrl).toBe("http://127.0.0.1:8989/oauth/callback");
        },
      );
    });
  });
});
