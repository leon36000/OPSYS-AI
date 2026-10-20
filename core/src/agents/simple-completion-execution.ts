/** Executes an already-prepared model without importing model/auth preparation. */
import { reasoningTagTextPolicy } from "@openclaw/ai/internal/openai";
import { defaultApiRegistry } from "@openclaw/ai/internal/runtime";
import {
  prepareHeadersForSimpleCompletion,
  prepareModelForSimpleCompletion,
} from "@openclaw/ai/transports";
import type { StreamFn } from "openclaw/plugin-sdk/agent-core";
import type { ThinkLevel } from "../auto-reply/thinking.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import {
  bindModelLlmRuntime,
  getModelCompletionOwner,
  getModelCompletionTransport,
  getModelLlmRuntime,
} from "../llm/model-runtime-binding.js";
import { completeSimple } from "../llm/stream.js";
import type { AssistantMessage, Model, SimpleStreamOptions } from "../llm/types.js";
import type { ResolvedProviderAuth } from "./model-auth.js";

type SimpleCompletionModelOptions = {
  headers?: Record<string, string>;
  sessionId?: string;
  maxTokens?: number;
  temperature?: number;
  serviceTier?: SimpleStreamOptions["serviceTier"];
  reasoning?: ThinkLevel;
  strictReasoningTags?: boolean;
  signal?: AbortSignal;
};

type PreparedCompletionParams = {
  assertCurrent?: () => void;
  model: Model;
  auth: ResolvedProviderAuth;
  context: Parameters<typeof completeSimple>[1];
  cfg?: OpenClawConfig;
  options?: SimpleCompletionModelOptions;
};

export async function completeWithPreparedSimpleCompletionModel(
  params: PreparedCompletionParams,
): Promise<AssistantMessage> {
  const owner = getModelCompletionOwner(params.model);
  if (!owner) {
    return await completePreparedModel(params);
  }
  return await owner.run(() =>
    completePreparedModel({
      ...params,
      assertCurrent: () => {
        owner.assertCurrent();
        params.assertCurrent?.();
      },
    }),
  );
}

async function completePreparedModel(params: PreparedCompletionParams): Promise<AssistantMessage> {
  // Direct SDK calls prepare transport hooks before entering the stream facade.
  await import("./ai-transport-runtime-host.js");
  params.assertCurrent?.();
  params.options?.signal?.throwIfAborted();
  const runtime = getModelLlmRuntime(params.model);
  let completionModel =
    getModelCompletionTransport(params.model) ??
    prepareModelForSimpleCompletion({
      // Direct SDK callers that did not use the preparation helper keep the shipped
      // process-default behavior; all prepared host paths carry their lifecycle owner.
      apiRegistry: runtime?.registry ?? defaultApiRegistry,
      model: params.model,
      cfg: params.cfg,
    });
  if (runtime) {
    completionModel = bindModelLlmRuntime(completionModel, runtime);
  }
  const { reasoning: rawReasoning, strictReasoningTags, ...options } = params.options ?? {};
  const reasoning =
    rawReasoning === "adaptive" ? "medium" : rawReasoning === "ultra" ? "max" : rawReasoning;
  const headers = prepareHeadersForSimpleCompletion(completionModel, options);
  const completionOptions: SimpleStreamOptions = {
    ...options,
    ...(reasoning ? { reasoning } : {}),
    apiKey: params.auth.apiKey,
    ...(headers ? { headers } : {}),
  };
  if (strictReasoningTags) {
    reasoningTagTextPolicy.markStrict(completionOptions);
  }
  return await completeSimple(
    completionModel,
    params.context,
    completionOptions,
    params.assertCurrent,
  );
}

/** Internal strict stream seam. Its only caller owns admission, result and drainage. */
export async function withPreparedSimpleCompletionStream<T>(
  params: PreparedCompletionParams & { assertCurrent: () => void },
  consume: (
    start: StreamFn,
    model: Model,
    context: Parameters<StreamFn>[1],
    options: SimpleStreamOptions,
  ) => Promise<T>,
): Promise<T> {
  const model = params.model;
  const context = params.context;
  const runtime = getModelLlmRuntime(model);
  const completionModel = getModelCompletionTransport(model);
  const owner = getModelCompletionOwner(model);
  if (!runtime || !completionModel || !owner) {
    throw new Error("M9_PRIVATE_PREPARED_STREAM_BINDINGS_REQUIRED");
  }
  const sourceAssertion = params.assertCurrent;
  const apiKey = params.auth.apiKey;
  const { reasoning: rawReasoning, strictReasoningTags, ...options } = params.options ?? {};
  const assertCurrent = () => {
    owner.assertCurrent();
    sourceAssertion();
    options.signal?.throwIfAborted();
    if (
      getModelLlmRuntime(model) !== runtime ||
      getModelCompletionTransport(model) !== completionModel ||
      getModelCompletionOwner(model) !== owner
    ) {
      throw new Error("M9_PRIVATE_PREPARED_STREAM_BINDINGS_CHANGED");
    }
  };
  assertCurrent();
  return await owner.run(async () => {
    await import("./ai-transport-runtime-host.js");
    assertCurrent();
    const reasoning =
      rawReasoning === "adaptive" ? "medium" : rawReasoning === "ultra" ? "max" : rawReasoning;
    const headers = prepareHeadersForSimpleCompletion(completionModel, options);
    const completionOptions: SimpleStreamOptions = {
      ...options,
      ...(reasoning ? { reasoning } : {}),
      apiKey,
      transport: "sse",
      ...(headers ? { headers } : {}),
    };
    if (strictReasoningTags) {
      reasoningTagTextPolicy.markStrict(completionOptions);
    }
    let invoked = false;
    const start: StreamFn = (suppliedModel, suppliedContext, suppliedOptions) => {
      assertCurrent();
      if (
        invoked ||
        suppliedModel !== completionModel ||
        suppliedContext !== context ||
        suppliedOptions !== completionOptions
      ) {
        throw new Error("M9_PRIVATE_PREPARED_STREAM_EXACT_SINGLE_DISPATCH_REQUIRED");
      }
      invoked = true;
      return runtime.streamSimple(completionModel, context, completionOptions);
    };
    assertCurrent();
    return await consume(start, completionModel, context, completionOptions);
  });
}
