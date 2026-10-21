// Agent identity draft state and persistence, split out of agents-page.ts.
import type { AssistantAvatarModelId } from "../../../../src/shared/assistant-avatar-model-catalog.js";
import type { GatewayBrowserClient } from "../../api/gateway.ts";
import type { ApplicationContext, ApplicationNavigationPreferences } from "../../app/context.ts";
import { t } from "../../i18n/index.ts";
import { updateAgentIdentity } from "../../lib/agents/index.ts";
import { formatUiError } from "../../lib/format-error.ts";
import { fileToAvatarDataUrl, type AvatarDataUrlResult } from "./avatar-image.ts";
import type { AgentIdentityDraft } from "./panels-overview.ts";

const AVATAR_REJECTION_MESSAGE_KEYS = {
  unusable: "agents.identity.imageUnusable",
  "too-detailed": "agents.identity.imageTooDetailed",
} as const satisfies Record<Extract<AvatarDataUrlResult, { ok: false }>["reason"], string>;

type AgentIdentityEditorHost = {
  identityDraft: AgentIdentityDraft;
  identitySaving: boolean;
  identityError: string | null;
};

const avatarSelectionEpochs = new WeakMap<AgentIdentityEditorHost, number>();

function advanceAvatarSelectionEpoch(host: AgentIdentityEditorHost): number {
  const epoch = (avatarSelectionEpochs.get(host) ?? 0) + 1;
  avatarSelectionEpochs.set(host, epoch);
  return epoch;
}

export function resetIdentityDraft(host: AgentIdentityEditorHost) {
  advanceAvatarSelectionEpoch(host);
  host.identityDraft = { name: null, emoji: null, avatar: null };
  host.identitySaving = false;
  host.identityError = null;
}

export function setIdentityDraftField(
  host: AgentIdentityEditorHost,
  field: "name" | "emoji",
  value: string,
) {
  host.identityDraft = { ...host.identityDraft, [field]: value };
  host.identityError = null;
}

export function setIdentityDraftAvatarModel(
  host: AgentIdentityEditorHost,
  modelId: AssistantAvatarModelId | null,
) {
  host.identityDraft = { ...host.identityDraft, avatarModelId: modelId };
  host.identityError = null;
}

export function selectIdentityAvatar(host: AgentIdentityEditorHost, file: File) {
  const epoch = advanceAvatarSelectionEpoch(host);
  void fileToAvatarDataUrl(file).then((result) => {
    if (avatarSelectionEpochs.get(host) !== epoch) {
      return;
    }
    if (result.ok) {
      host.identityDraft = { ...host.identityDraft, avatar: result.dataUrl };
      host.identityError = null;
    } else {
      host.identityError = t(AVATAR_REJECTION_MESSAGE_KEYS[result.reason]);
    }
  });
}

/** Persist the draft via agents.update, then refresh the roster and the
    identity cache so the sidebar chip and page pick up the new identity. */
export async function saveIdentityDraft(params: {
  host: AgentIdentityEditorHost;
  expectedClient: GatewayBrowserClient;
  agentId: string;
  agents: ApplicationContext["agents"];
  agentIdentity: ApplicationContext["agentIdentity"];
  runtimeConfig: ApplicationContext["runtimeConfig"];
  canDispatch: () => boolean;
  isCurrent: () => boolean;
  onSaved: () => void;
}) {
  const { host, expectedClient, agentId, agents, agentIdentity, runtimeConfig } = params;
  const draft = host.identityDraft;
  // Text and image edits set/replace only. The catalogue model has a separate
  // tri-state so explicit null clears it while an untouched field is omitted.
  const name = draft.name?.trim();
  const emoji = draft.emoji?.trim();
  const avatar = draft.avatar ?? undefined;
  const avatarModelId = draft.avatarModelId;
  const hasAvatarModelChange = avatarModelId !== undefined;
  if ((draft.name !== null && !name) || (draft.emoji !== null && !emoji)) {
    return;
  }
  if (!name && !emoji && !avatar && !hasAvatarModelChange) {
    resetIdentityDraft(host);
    return;
  }
  host.identitySaving = true;
  host.identityError = null;
  try {
    const mutation = await runtimeConfig.runExternalMutation(
      (client) => {
        if (client !== expectedClient) {
          throw new Error("Connection changed before the agent identity update started.");
        }
        return updateAgentIdentity(client, {
          agentId,
          name,
          emoji,
          avatar,
          ...(hasAvatarModelChange ? { avatarModelId } : {}),
        });
      },
      {
        canDispatch: params.canDispatch,
        dispatchError: "Access changed before the agent identity update started.",
      },
    );
    if (!mutation.ok) {
      throw new Error(mutation.error);
    }
    // The mutation may have completed after the selected agent or Gateway
    // changed. Do not invalidate/refresh shared capabilities for stale work.
    if (!params.isCurrent()) {
      return;
    }
    const refreshErrors = mutation.refresh.ok ? [] : [mutation.refresh.error];
    agentIdentity.invalidate([agentId]);
    try {
      await agents.refreshList();
    } catch (error) {
      refreshErrors.push(
        `Agent identity was saved, but the agent list refresh failed: ${formatUiError(error)}`,
      );
    }
    if (!params.isCurrent()) {
      return;
    }
    try {
      await agentIdentity.ensure([agentId]);
    } catch (error) {
      refreshErrors.push(
        `Agent identity was saved, but the identity refresh failed: ${formatUiError(error)}`,
      );
    }
    if (params.isCurrent()) {
      resetIdentityDraft(host);
      params.onSaved();
      host.identityError = refreshErrors.length > 0 ? refreshErrors.join(" ") : null;
    }
  } catch (err) {
    if (params.isCurrent()) {
      host.identityError = formatUiError(err);
    }
  } finally {
    if (params.isCurrent()) {
      host.identitySaving = false;
    }
  }
}

/** Quick-switcher pin toggle; pins persist as browser-profile preferences. */
export function togglePinnedAgent(navigation: ApplicationNavigationPreferences, agentId: string) {
  const pinned = navigation.snapshot.pinnedAgentIds;
  const next = pinned.includes(agentId)
    ? pinned.filter((id) => id !== agentId)
    : [...pinned, agentId];
  navigation.update({ pinnedAgentIds: next });
}
