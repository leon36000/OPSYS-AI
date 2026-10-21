import { expectDefined } from "@openclaw/normalization-core";
import { describe, expect, it } from "vitest";
import { assertAdmittedRunOperatorAuthority } from "../agents/admitted-run-context.js";
import {
  clearRuntimeConfigSnapshot,
  getRuntimeConfigSnapshot,
  setRuntimeConfigSnapshot,
} from "../config/runtime-snapshot.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { resetGatewayWorkAdmission } from "../process/gateway-work-admission.js";
import { closeOpenClawStateDatabaseForTest } from "../state/openclaw-state-db.js";
import { ensureProfileForEmail, setUserProfileRole } from "../state/user-profiles.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import { isGatewayAuthPolicyCurrent, resolveGatewayAuthPolicyGeneration } from "./auth-policy.js";
import {
  captureGatewayDeviceRevocation,
  closeGatewayDeviceRevocation,
  invalidateGatewayDeviceRevocation,
} from "./device-revocation.js";
import { capturePrivateM9AuditSource } from "./m9-private-audit-source.js";
import {
  invalidateOperatorRolePolicy,
  onOperatorRolePolicyChanged,
  publishOperatorRoleConfigChange,
} from "./operator-role-policy.js";
import { captureGatewayOperatorRunAuthority } from "./operator-run-authority.js";
import { createDirectChatContext } from "./server-chat.agent-events.test-helpers.js";
import {
  bindGatewayRequestHandlerMutationAuthority,
  bindWebSocketRequestMutationAuthority,
  readGatewayRequestMutationAuthority,
} from "./server-methods/session-mutation-guards.js";
import type {
  GatewayClient,
  GatewayRequestHandlerOptions,
  GatewayRequestOptions,
} from "./server-methods/shared-types.js";
import {
  disconnectStaleSharedGatewayAuthClients,
  SharedGatewaySessionGenerationState,
} from "./server-shared-auth-generation.js";
import {
  hasCurrentGatewayPolicyClientSource,
  onGatewayPolicyClientInvalidated,
} from "./server/ws-policy-close.js";
import type { GatewayWsClient } from "./server/ws-types.js";

type AuditSource = ReturnType<typeof capturePrivateM9AuditSource>;
type UnitClient = GatewayWsClient & GatewayClient;
type BindingVariant = "real" | "equivalent-reader" | "unwrapped-predicate";
type FixtureScope = {
  options: GatewayRequestHandlerOptions;
  client: UnitClient;
  context: ReturnType<typeof createDirectChatContext>;
  generation: SharedGatewaySessionGenerationState;
  connection: AbortController;
  profileId: string;
  initialConfig: OpenClawConfig;
  commitConfig: (config: OpenClawConfig) => void;
  bindOptions: (variant: BindingVariant) => GatewayRequestHandlerOptions;
  capture: (options?: GatewayRequestHandlerOptions) => AuditSource;
  canonical: () => NonNullable<ReturnType<typeof captureGatewayOperatorRunAuthority>>;
};
function roleConfig(): OpenClawConfig {
  return {
    gateway: {
      roles: {
        default: "reader",
        definitions: {
          reader: { sessions: { others: "view" }, agents: ["main"], scopes: ["operator.read"] },
          maintainer: { sessions: { others: "write" }, agents: "*", scopes: ["operator.admin"] },
        },
      },
    },
  };
}

/** Unit composition of actual owner APIs. The fictitious client shell grants no opaque authority. */
async function withFixture(
  inside: (fixture: FixtureScope) => void | Promise<void>,
  afterHostRequest?: (fixture: FixtureScope) => void | Promise<void>,
): Promise<void> {
  await withOpenClawTestState({ scenario: "minimal" }, async () => {
    const previousConfig = getRuntimeConfigSnapshot();
    const cleanup: Array<() => void> = [];
    let failed = false;
    let primary: unknown;
    const failures: unknown[] = [];
    let context: ReturnType<typeof createDirectChatContext> | undefined;
    try {
      resetGatewayWorkAdmission();
      const profile = ensureProfileForEmail("fictitious-m9-source@example.test");
      setUserProfileRole(profile.id, "maintainer");
      invalidateOperatorRolePolicy(profile.id);
      const initialConfig = roleConfig();
      let committedConfig = initialConfig;
      setRuntimeConfigSnapshot(initialConfig);
      const generation = new SharedGatewaySessionGenerationState({
        current: "generation-a",
        required: null,
      });
      const connection = new AbortController();
      const client: UnitClient = {
        // This shell is only transport data; all mutation and source proofs below come from owners.
        socket: { close: () => connection.abort() } as GatewayWsClient["socket"],
        connId: "fictitious-m9-unit-connection",
        usesSharedGatewayAuth: true,
        sharedGatewaySessionGeneration: "generation-a",
        authPolicyGeneration: resolveGatewayAuthPolicyGeneration(initialConfig),
        connectionSignal: connection.signal,
        authenticatedUserId: "fictitious-m9-source@example.test",
        authenticatedUserProfile: {
          profileId: profile.id,
          displayName: null,
          avatarRevision: "0",
          hasAvatar: false,
          updatedAt: profile.updatedAt,
        },
        internal: { operatorRoleActor: { kind: "operator", profileId: profile.id } },
        connect: {
          minProtocol: 1,
          maxProtocol: 1,
          client: { id: "gateway-client", version: "dev", platform: "test", mode: "backend" },
          role: "operator",
          scopes: ["operator.admin"],
          device: {
            id: "fictitious-m9-device",
            publicKey: "fictitious-public-key",
            signature: "fictitious-signature",
            signedAt: 1,
            nonce: "fictitious-nonce",
          },
        },
      };
      const ownerContext = createDirectChatContext({
        getRuntimeConfig: () => getRuntimeConfigSnapshot() ?? committedConfig,
        getCommittedRuntimeConfig: () => committedConfig,
      });
      context = ownerContext;
      ownerContext.resolveGatewayContext = () => ownerContext;
      const isCommittedPolicyCurrent = () =>
        client.authPolicyGeneration === undefined ||
        isGatewayAuthPolicyCurrent(client.authPolicyGeneration, committedConfig);
      const clientAuthority = captureGatewayDeviceRevocation(
        ownerContext,
        { deviceId: client.connect.device?.id, role: client.connect.role },
        () =>
          !client.invalidated &&
          !connection.signal.aborted &&
          (!client.usesSharedGatewayAuth ||
            generation.reader() === undefined ||
            generation.reader() === client.sharedGatewaySessionGeneration),
        connection.signal,
        {
          isCurrent: () =>
            hasCurrentGatewayPolicyClientSource(client) && isCommittedPolicyCurrent(),
          subscribe: (onRevoked) => {
            const releaseClient = onGatewayPolicyClientInvalidated(client, onRevoked);
            const releasePolicy = onOperatorRolePolicyChanged((change) => {
              if (
                change.kind === "config" &&
                change.context === ownerContext &&
                !isCommittedPolicyCurrent()
              ) {
                onRevoked();
              }
            });
            const releaseGeneration = generation.onInvalidated(
              client.sharedGatewaySessionGeneration,
              onRevoked,
            );
            return () => {
              releaseClient();
              releasePolicy();
              releaseGeneration();
            };
          },
        },
      );
      cleanup.push(clientAuthority.release);
      const bindOptions = (variant: BindingVariant): GatewayRequestHandlerOptions => {
        const request: GatewayRequestOptions = {
          req: {
            type: "req",
            id: "fictitious-m9-source",
            method: "opsys.m9.auditDraft",
            params: {},
          },
          client,
          context: ownerContext,
          isWebchatConnect: () => false,
          respond: () => {},
          hasCurrentClientAuthority:
            variant === "unwrapped-predicate" ? () => true : clientAuthority.isCurrent,
        };
        bindWebSocketRequestMutationAuthority(
          request,
          client,
          variant === "equivalent-reader" ? () => generation.reader() : generation.reader,
        );
        const handler: GatewayRequestHandlerOptions = { ...request, params: {} };
        return bindGatewayRequestHandlerMutationAuthority(request, handler, undefined);
      };
      const options = bindOptions("real");
      expect(readGatewayRequestMutationAuthority(options).family).toBe("worker");
      const fixture: FixtureScope = {
        options,
        client,
        context: ownerContext,
        generation,
        connection,
        profileId: profile.id,
        initialConfig,
        commitConfig: (config) => {
          committedConfig = config;
        },
        bindOptions,
        capture: (candidate = options) => {
          const source = capturePrivateM9AuditSource(candidate);
          cleanup.push(() => source.close());
          return source;
        },
        canonical: () => {
          const source = expectDefined(
            captureGatewayOperatorRunAuthority(options),
            "real canonical source",
          );
          cleanup.push(source.release);
          return source;
        },
      };
      await inside(fixture);
      // End the original request hold; accepted canonical handles must keep their own holds.
      clientAuthority.release();
      await afterHostRequest?.(fixture);
    } catch (error) {
      failed = true;
      primary = error;
    } finally {
      for (const release of [
        ...cleanup.toReversed(),
        () => {
          if (context) {
            closeGatewayDeviceRevocation(context);
          }
        },
        () => {
          if (previousConfig) {
            setRuntimeConfigSnapshot(previousConfig);
          } else {
            clearRuntimeConfigSnapshot();
          }
        },
        closeOpenClawStateDatabaseForTest,
        resetGatewayWorkAdmission,
      ]) {
        try {
          release();
        } catch (error) {
          failures.push(error);
        }
      }
    }
    if (failures.length) {
      throw new AggregateError(
        failed ? [primary, ...failures] : failures,
        "fictitious audit source fixture cleanup failed",
        { cause: failed ? primary : failures[0] },
      );
    }
    if (failed) {
      throw primary;
    }
  });
}

describe("private M9 direct opaque owner unit restriction", () => {
  it("captures a real fresh admin worker synchronously without an optional request signal", async () => {
    let accepted: AuditSource | undefined;
    await withFixture(
      (f) => {
        expect(f.options.signal).toBeUndefined();
        const source = f.capture();
        accepted = source;
        expect(Object.isFrozen(source)).toBe(true);
        expect(source.operatorAuthority.scopes).toContain("operator.admin");
        expect(() => assertAdmittedRunOperatorAuthority(source.operatorAuthority)).not.toThrow();
        expect(source.operatorAuthority.profileId).toBe(f.profileId);
        expect(source.signal.aborted).toBe(false);
        const independent = f.canonical();
        expect(source.operatorAuthority.source).toBe(independent.authority.source);
        expect(source.assertSourceCurrent).not.toThrow();
      },
      async () => {
        await Promise.resolve();
        expect(expectDefined(accepted, "accepted source").assertSourceCurrent).not.toThrow();
      },
    );
  });

  it("refuses another method and missing synthetic nonoperator or system callers", async () => {
    await withFixture((f) => {
      const method = f.options.req.method;
      try {
        f.options.req.method = "chat.send";
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_METHOD_REQUIRED");
      } finally {
        f.options.req.method = method;
      }
      const originalClient = f.options.client;
      try {
        f.options.client = null;
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_DIRECT_OPERATOR_REQUIRED");
      } finally {
        f.options.client = originalClient;
      }
      const internal = f.client.internal;
      try {
        f.client.internal = { ...internal, syntheticClient: true };
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_DIRECT_OPERATOR_REQUIRED");
        f.client.internal = { ...internal, operatorRoleActor: { kind: "system" } };
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_DIRECT_OPERATOR_REQUIRED");
      } finally {
        f.client.internal = internal;
      }
      const role = f.client.connect.role;
      try {
        f.client.connect.role = "node";
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_DIRECT_OPERATOR_REQUIRED");
      } finally {
        f.client.connect.role = role;
      }
      expect(f.capture().assertSourceCurrent).not.toThrow();
    });
  });

  it("refuses cloned options and copied opaque descriptors while the original worker remains usable", async () => {
    await withFixture((f) => {
      const copies: GatewayRequestHandlerOptions[] = [
        { ...f.options },
        Object.defineProperties({ ...f.options }, Object.getOwnPropertyDescriptors(f.options)),
      ];
      for (const copy of copies) {
        expect(readGatewayRequestMutationAuthority(copy).family).toBe("native-compatibility");
        expect(() => f.capture(copy)).toThrow("M9_PRIVATE_AUDIT_SOURCE_WORKER_REQUIRED");
      }
      for (const variant of ["equivalent-reader", "unwrapped-predicate"] as const) {
        const candidate = f.bindOptions(variant);
        expect(readGatewayRequestMutationAuthority(candidate).family).toBe("native-compatibility");
        expect(() => f.capture(candidate)).toThrow("M9_PRIVATE_AUDIT_SOURCE_WORKER_REQUIRED");
      }
      expect(readGatewayRequestMutationAuthority(f.options).family).toBe("worker");
      expect(f.capture().assertSourceCurrent).not.toThrow();
    });
  });

  it("refuses real inherited authority and an autonomous runtime identity without retiring their owner", async () => {
    await withFixture((f) => {
      const inherited = f.canonical();
      const internal = f.client.internal;
      try {
        f.client.internal = { ...internal, operatorRunAuthority: inherited.authority };
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_FRESH_SOURCE_REQUIRED");
        expect(inherited.authority.assertCurrent).not.toThrow();
        const instance = { instanceId: "fictitious-instance", runId: "fictitious-run" };
        f.client.internal = {
          ...internal,
          agentRuntimeIdentity: {
            kind: "agentRuntime",
            agentId: "main",
            sessionKey: "fictitious-session",
            operationalRunInstance: instance,
            delegatedAuthority: {
              kind: "local",
              lifecycleGeneration: "fictitious-generation",
              claimId: "fictitious-claim",
              operationalRunInstance: instance,
            },
          },
        };
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_FRESH_SOURCE_REQUIRED");
      } finally {
        f.client.internal = internal;
      }
      expect(inherited.authority.assertCurrent).not.toThrow();
      expect(f.capture().assertSourceCurrent).not.toThrow();
    });
  });

  it("requires explicit admin in the real captured scopes and preserves another canonical holder", async () => {
    await withFixture((f) => {
      const independent = f.canonical();
      const scopes = f.client.connect.scopes;
      try {
        f.client.connect.scopes = ["operator.read"];
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_ADMIN_REQUIRED");
      } finally {
        f.client.connect.scopes = scopes;
      }
      expect(independent.authority.assertCurrent).not.toThrow();
      expect(f.capture().assertSourceCurrent).not.toThrow();
    });
  });

  it("refuses an initially stale real worker before returning any retained handle", async () => {
    await withFixture((f) => {
      f.client.invalidated = true;
      try {
        expect(() => f.capture()).toThrow("M9_PRIVATE_AUDIT_SOURCE_WORKER_NOT_CURRENT");
      } finally {
        f.client.invalidated = false;
      }
      expect(f.capture().assertSourceCurrent).not.toThrow();
    });
  });

  it("preserves the accepted source after host request through tentative fencing transport retirement and rollback", async () => {
    let accepted: AuditSource | undefined;
    await withFixture(
      (f) => {
        accepted = f.capture();
      },
      async (f) => {
        const source = expectDefined(accepted, "accepted source");
        const authority = source.operatorAuthority;
        const signal = source.signal;
        const ownership = expectDefined(
          f.generation.claim(f.generation.capture(), "generation-b"),
          "generation claim",
        );
        disconnectStaleSharedGatewayAuthClients({
          state: f.generation,
          clients: [f.client],
          expectedGeneration: "generation-b",
          revokeSource: false,
        });
        f.connection.abort();
        setRuntimeConfigSnapshot({
          ...f.initialConfig,
          gateway: { ...f.initialConfig.gateway, auth: { allowTailscale: true } },
        });
        await Promise.resolve();
        expect(f.connection.signal.aborted).toBe(true);
        expect(source.assertSourceCurrent).not.toThrow();
        expect(source.signal).toBe(signal);
        expect(source.operatorAuthority).toBe(authority);
        expect(f.generation.replace(ownership, { current: "generation-a", required: null })).toBe(
          true,
        );
        setRuntimeConfigSnapshot(f.initialConfig);
        publishOperatorRoleConfigChange(f.context);
        expect(source.signal.aborted).toBe(false);
        expect(source.assertSourceCurrent).not.toThrow();
      },
    );
  });

  it("permanently retires the original accepted source when a generation is committed", async () => {
    let accepted: AuditSource | undefined;
    await withFixture(
      (f) => {
        accepted = f.capture();
      },
      async (f) => {
        const source = expectDefined(accepted, "accepted source");
        const ownership = expectDefined(
          f.generation.claim(f.generation.capture(), "generation-b"),
          "generation claim",
        );
        await Promise.resolve();
        expect(f.generation.finalize(ownership)).toBe(true);
        expect(source.signal.aborted).toBe(true);
        expect(source.assertSourceCurrent).toThrow();
        f.generation.publish({ current: "generation-a", required: null });
        expect(source.assertSourceCurrent).toThrow();
        expect(source.signal.aborted).toBe(true);
      },
    );
  });

  it("retires retained sources after real SQL role downgrade and committed policy changes", async () => {
    for (const change of ["role", "policy"]) {
      let accepted: AuditSource | undefined;
      await withFixture(
        (f) => {
          accepted = f.capture();
        },
        async (f) => {
          const source = expectDefined(accepted, "accepted source");
          await Promise.resolve();
          if (change === "role") {
            setUserProfileRole(f.profileId, "reader");
            invalidateOperatorRolePolicy(f.profileId);
          } else {
            const candidate = roleConfig();
            expectDefined(
              candidate.gateway?.roles?.definitions.maintainer,
              "maintainer role",
            ).agents = [];
            setRuntimeConfigSnapshot(candidate);
            publishOperatorRoleConfigChange({});
            expect(source.signal.aborted).toBe(false);
            expect(source.assertSourceCurrent).not.toThrow();
            f.commitConfig(candidate);
            publishOperatorRoleConfigChange(f.context);
          }
          expect(source.signal.aborted).toBe(true);
          expect(source.assertSourceCurrent).toThrow();
          setUserProfileRole(f.profileId, "maintainer");
          invalidateOperatorRolePolicy(f.profileId);
          f.commitConfig(f.initialConfig);
          setRuntimeConfigSnapshot(f.initialConfig);
          expect(source.assertSourceCurrent).toThrow();
        },
      );
    }
  });

  it("revokes only the original matching device and role after host request", async () => {
    let accepted: AuditSource | undefined;
    await withFixture(
      (f) => {
        accepted = f.capture();
      },
      async (f) => {
        const source = expectDefined(accepted, "accepted source");
        await Promise.resolve();
        invalidateGatewayDeviceRevocation(f.context, "unrelated-device", "operator");
        invalidateGatewayDeviceRevocation(f.context, "fictitious-m9-device", "node");
        expect(source.signal.aborted).toBe(false);
        expect(source.assertSourceCurrent).not.toThrow();
        invalidateGatewayDeviceRevocation(f.context, "fictitious-m9-device", "operator");
        expect(source.signal.aborted).toBe(true);
        expect(source.assertSourceCurrent).toThrow();
        expect(source.assertSourceCurrent).toThrow();
      },
    );
  });

  it("closes exactly its local hold idempotently without revoking an independent retained owner", async () => {
    let accepted: AuditSource | undefined;
    let independent: ReturnType<FixtureScope["canonical"]> | undefined;
    await withFixture(
      (f) => {
        accepted = f.capture();
        independent = f.canonical();
      },
      async () => {
        const source = expectDefined(accepted, "accepted source");
        const other = expectDefined(independent, "independent owner");
        await Promise.resolve();
        source.close();
        source.close();
        expect(source.signal.aborted).toBe(true);
        expect(source.assertSourceCurrent).toThrow("M9_PRIVATE_AUDIT_SOURCE_CLOSED");
        expect(source.operatorAuthority.assertCurrent).toThrow("no longer active");
        expect(other.authority.signal?.aborted).toBe(false);
        expect(other.authority.assertCurrent).not.toThrow();
        other.release();
        expect(other.authority.assertCurrent).toThrow("no longer active");
      },
    );
  });

  it("refuses source aborts triggered synchronously inside initial and accepted authority assertions", async () => {
    await withFixture((f) => {
      const access = new AbortController();
      let sourceChecks = 0;
      const internal = f.client.internal;
      f.client.internal = {
        ...internal,
        operatorAccessAuthority: {
          signal: access.signal,
          assertCurrent: () => {
            sourceChecks += 1;
            access.abort(new Error("fictitious synchronous initial revoke"));
          },
        },
      };
      try {
        expect(() => f.capture()).toThrow(
          /^M9_PRIVATE_AUDIT_SOURCE_(SOURCE_REVOKED|CAPTURE_FAILED)$/,
        );
        expect(sourceChecks).toBeGreaterThan(0);
        expect(access.signal.aborted).toBe(true);
      } finally {
        f.client.internal = internal;
      }
    });
    let accepted: AuditSource | undefined;
    let armed = false;
    let sourceChecks = 0;
    const access = new AbortController();
    await withFixture(
      (f) => {
        f.client.internal = {
          ...f.client.internal,
          operatorAccessAuthority: {
            signal: access.signal,
            assertCurrent: () => {
              sourceChecks += 1;
              if (armed) {
                access.abort(new Error("fictitious synchronous accepted revoke"));
              }
            },
          },
        };
        accepted = f.capture();
        expect(accepted.signal.aborted).toBe(false);
        expect(accepted.assertSourceCurrent).not.toThrow();
      },
      async () => {
        const source = expectDefined(accepted, "accepted source");
        await Promise.resolve();
        const before = sourceChecks;
        armed = true;
        expect(source.assertSourceCurrent).toThrow("M9_PRIVATE_AUDIT_SOURCE_SOURCE_REVOKED");
        expect(sourceChecks).toBeGreaterThan(before);
        expect(access.signal.aborted).toBe(true);
        expect(source.signal.aborted).toBe(true);
        armed = false;
        expect(source.assertSourceCurrent).toThrow();
      },
    );
  });
});
