import { getRuntimeConfig } from "../config/config.js";
import { purgeExpiredSecretStoreEntries } from "../secrets/store/secret-store.js";
import {
  createGitHubOAuthLifecycle,
  installActiveGitHubOAuthLifecycle,
} from "./github-oauth-lifecycle.js";
import { createModelAccountConnectService } from "./model-account-connect.js";
import { startOpsysMetierSidecar } from "./opsys-metier-supervisor.js";
import {
  broadcastChatMetadataChanged,
  type createGatewayChatMetadataLifecycle,
} from "./server-chat-metadata-lifecycle.js";
import { attachSessionChangeEventLifetime } from "./server-methods/session-change-event.js";
import type { GatewayRequestContext } from "./server-methods/types.js";
import type { GatewaySidecarStopOwner } from "./server-sidecar-owners.js";
import type { GatewayPostReadySidecarHandle } from "./server-startup-sidecar-scheduler.js";

type GatewayChatMetadataLifecycle = Awaited<ReturnType<typeof createGatewayChatMetadataLifecycle>>;
const SECRET_STORE_EXPIRY_INTERVAL_MS = 60_000;
const GITHUB_PUBLICATION_RECONCILE_INTERVAL_MS = 60_000;

function startGitHubPublicationMaintenance(
  reconcile: () => Promise<void>,
  logWarning: (message: string) => void,
): GatewayPostReadySidecarHandle {
  let current: Promise<void> | undefined;
  let stopped = false;
  const run = () => {
    if (stopped || current) {
      return;
    }
    const operation = reconcile()
      .catch(() => logWarning("GitHub publication recovery failed; will retry."))
      .finally(() => {
        if (current === operation) {
          current = undefined;
        }
      });
    current = operation;
  };
  run();
  const interval = setInterval(run, GITHUB_PUBLICATION_RECONCILE_INTERVAL_MS);
  interval.unref?.();
  return {
    stop: async () => {
      stopped = true;
      clearInterval(interval);
      await current;
    },
  };
}

function startSecretStoreExpiryMaintenance(
  logWarning: (message: string) => void,
): GatewayPostReadySidecarHandle {
  let warned = false;
  let current: Promise<void> | undefined;
  let stopped = false;
  const purge = () => {
    if (stopped || current) {
      return;
    }
    current = purgeExpiredSecretStoreEntries()
      .then(() => {
        warned = false;
      })
      .catch(() => {
        if (!warned) {
          logWarning("Secret store expiry cleanup failed; will retry.");
          warned = true;
        }
      })
      .finally(() => {
        current = undefined;
      });
  };
  purge();
  const interval = setInterval(purge, SECRET_STORE_EXPIRY_INTERVAL_MS);
  interval.unref?.();
  return {
    stop: async () => {
      stopped = true;
      clearInterval(interval);
      await current;
    },
  };
}

export async function attachInitialGatewayLifetimeSidecars(params: {
  chatMetadataLifecycle: GatewayChatMetadataLifecycle;
  gatewayRequestContext: GatewayRequestContext;
  flushPendingSessionsChangedEvents: (context?: object) => Promise<void>;
  minimalTestGateway: boolean;
  logWarning: (message: string) => void;
  reconcileGitHubPublications?: () => Promise<void>;
  reconcileOpsysCron?: () => Promise<unknown>;
  publishSidecars: GatewaySidecarStopOwner["publish"];
}): Promise<void> {
  await params.chatMetadataLifecycle.attachContext(
    params.gatewayRequestContext,
    params.publishSidecars,
  );
  const modelAccountConnect = createModelAccountConnectService({
    getConfig: params.gatewayRequestContext.getRuntimeConfig,
    onChanged: () => broadcastChatMetadataChanged(params.gatewayRequestContext),
  });
  params.gatewayRequestContext.modelAccountConnectService = modelAccountConnect;
  params.publishSidecars({
    stop: async () => {
      await modelAccountConnect.stop();
      if (params.gatewayRequestContext.modelAccountConnectService === modelAccountConnect) {
        delete params.gatewayRequestContext.modelAccountConnectService;
      }
    },
  });
  const githubOAuth = createGitHubOAuthLifecycle({
    getConfig: params.gatewayRequestContext.getRuntimeConfig,
    getPersistedConfig: () => getRuntimeConfig({ pin: false }),
    warn: params.logWarning,
  });
  params.gatewayRequestContext.githubOAuthService = githubOAuth;
  const uninstallGitHubOAuth = installActiveGitHubOAuthLifecycle(githubOAuth);
  if (!params.minimalTestGateway) {
    githubOAuth.start();
  }
  params.publishSidecars({
    stop: async () => {
      uninstallGitHubOAuth();
      await githubOAuth.stop();
      if (params.gatewayRequestContext.githubOAuthService === githubOAuth) {
        delete params.gatewayRequestContext.githubOAuthService;
      }
    },
  });
  if (!params.minimalTestGateway) {
    params.publishSidecars(startSecretStoreExpiryMaintenance(params.logWarning));
    // OPSYS (PLAN T0.10): launches and supervises the Python business engine when
    // `opsys/metier.json` enables it; returns nothing otherwise, so upstream behavior is intact.
    let opsysCronReconcile: Promise<unknown> | undefined;
    let opsysCronSidecarStopped = false;
    const opsysMetier = startOpsysMetierSidecar({
      onHealthy: () => {
        if (opsysCronSidecarStopped || opsysCronReconcile || !params.reconcileOpsysCron) return;
        const pass = Promise.resolve()
          .then(params.reconcileOpsysCron)
          .catch(() =>
            params.logWarning(
              "OPSYS cron reconciliation failed; it will retry on a later healthy probe.",
            ),
          )
          .finally(() => {
            if (opsysCronReconcile === pass) opsysCronReconcile = undefined;
          });
        opsysCronReconcile = pass;
      },
    });
    if (opsysMetier) {
      let active = true;
      const service = opsysMetier.getPrivateCronClient
        ? { getClient: () => (active ? opsysMetier.getPrivateCronClient?.() : undefined) }
        : undefined;
      if (service) params.gatewayRequestContext.opsysCronPrivateClientService = service;
      params.publishSidecars({
        stop: async () => {
          active = false;
          opsysCronSidecarStopped = true;
          if (service && params.gatewayRequestContext.opsysCronPrivateClientService === service) {
            delete params.gatewayRequestContext.opsysCronPrivateClientService;
          }
          await opsysMetier.stop();
          await opsysCronReconcile;
        },
      });
    }
  }
  if (params.reconcileGitHubPublications) {
    params.publishSidecars(
      startGitHubPublicationMaintenance(params.reconcileGitHubPublications, params.logWarning),
    );
  }
  attachSessionChangeEventLifetime(params.gatewayRequestContext, () =>
    params.publishSidecars({
      stop: async () => {
        await params.flushPendingSessionsChangedEvents(params.gatewayRequestContext);
      },
    }),
  );
}
