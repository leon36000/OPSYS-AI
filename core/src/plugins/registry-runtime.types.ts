import type { createChannelIngressDrain } from "../channels/message/ingress-drain.js";
import type { createChannelIngressQueue } from "../channels/message/ingress-queue.js";
import type { PluginRecord } from "./registry-types.js";
import type { PluginRuntime } from "./runtime/types.js";

export type { ChannelIngressHostOwner } from "../channels/message-access/ingress-host-owner.js";
export type { SessionEntry } from "../config/sessions/types.js";
export type { OpenBlobStoreOptions } from "../plugin-state/plugin-blob-store.js";
export type {
  OpenAsyncKeyedStoreOptions,
  OpenKeyedStoreOptions,
} from "../plugin-state/plugin-state-store.js";
export type { PluginRecord } from "./registry-types.js";
export type { PluginRuntime } from "./runtime/types.js";

export type AdmissionOwnerLifetime = { isLive: () => boolean; dispose: () => void };

export type ResolutionFailure = {
  error: unknown;
  record: PluginRecord;
  prop: PropertyKey;
};

export type TrustedMethod =
  | "dispatchHookAgentTurn"
  | "openBlobStore"
  | "openKeyedStore"
  | "openSyncKeyedStore"
  | "openChannelIngressQueue"
  | "openChannelIngressDrain";

export type ChannelRuntime = PluginRuntime["channel"];
export type InboundContextBuilder = PluginRuntime["channel"]["inbound"]["buildContext"];
export type EmbeddedAgentRun = PluginRuntime["agent"]["runEmbeddedAgent"];

export type InboundContextParams = Parameters<
  PluginRuntime["channel"]["inbound"]["buildContext"]
>[0];
export type IngressRun = PluginRuntime["agent"]["runCommandFromIngress"];

export type IngressDrainOptions<TPayload, TMetadata = unknown, TCompletedMetadata = unknown> = Omit<
  Parameters<typeof createChannelIngressDrain<TPayload, TMetadata, TCompletedMetadata>>[0],
  "queue"
> & {
  queue?: ReturnType<typeof createChannelIngressQueue<TPayload, TMetadata, TCompletedMetadata>>;
  accountId?: string;
  stateDir?: string;
};
