import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import {
  buildAudioTranscriptionFormData,
  readProviderJsonObjectResponse,
  requireTranscriptionText,
} from "openclaw/plugin-sdk/provider-http";
import type {
  RealtimeTranscriptionProviderPlugin,
  RealtimeTranscriptionSession,
  RealtimeTranscriptionSessionCreateRequest,
} from "openclaw/plugin-sdk/realtime-transcription";
import { mulawToPcm } from "openclaw/plugin-sdk/realtime-voice-provider";
import {
  GuardedFetchRedirectError,
  ssrfPolicyFromHttpBaseUrlAllowedOrigin,
} from "openclaw/plugin-sdk/ssrf-runtime";
import { fetchConfiguredLocalOriginWithSsrFGuard } from "openclaw/plugin-sdk/ssrf-runtime-internal";

export const LOCAL_ASR_TRANSCRIPTION_PROVIDER_ID = "voice-call-local-clip";
const MAX_CLIP_BYTES = 240_000;
const MAX_RESPONSE_BYTES = 8 * 1024;
const MAX_TIMEOUT_MS = 4_000;
const DEFAULT_TIMEOUT_MS = 4_000;

type LocalAsrConfig = {
  baseUrl: string;
  model: string;
  language: string;
  timeoutMs: number;
};

const ERROR_CODES = {
  configInvalid: "LOCAL_ASR_CONFIG_INVALID",
  clipTooLarge: "LOCAL_ASR_CLIP_TOO_LARGE",
  requestTimeout: "LOCAL_ASR_REQUEST_TIMEOUT",
  redirectRejected: "LOCAL_ASR_REDIRECT_REJECTED",
  httpRejected: "LOCAL_ASR_HTTP_REJECTED",
  responseInvalid: "LOCAL_ASR_RESPONSE_INVALID",
  emptyTranscript: "LOCAL_ASR_EMPTY_TRANSCRIPT",
  transportFailed: "LOCAL_ASR_TRANSPORT_FAILED",
} as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeLocalBaseUrl(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length > 256 || value.trim() !== value) {
    return undefined;
  }
  if (!value.startsWith("http://")) {
    return undefined;
  }
  const authorityStart = "http://".length;
  const rawSuffixStart = [
    value.indexOf("/", authorityStart),
    value.indexOf("?", authorityStart),
    value.indexOf("#", authorityStart),
  ]
    .filter((index) => index >= 0)
    .reduce((minimum, index) => Math.min(minimum, index), value.length);
  const rawAuthority = value.slice(authorityStart, rawSuffixStart);
  const rawAuthorityMatch = /^(127\.0\.0\.1|\[::1\]):(\d{1,5})$/.exec(rawAuthority);
  if (!rawAuthorityMatch) {
    return undefined;
  }
  const portNumber = Number(rawAuthorityMatch[2]);
  if (portNumber < 1 || portNumber > 65_535) {
    return undefined;
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return undefined;
  }
  const suffixStart = [value.indexOf("?", authorityStart), value.indexOf("#", authorityStart)]
    .filter((index) => index >= 0)
    .reduce((minimum, index) => Math.min(minimum, index), value.length);
  const pathStart = value.indexOf("/", authorityStart);
  const rawPath =
    pathStart >= 0 && pathStart < suffixStart ? value.slice(pathStart, suffixStart) : "";
  const authorityEnd = pathStart >= 0 && pathStart < suffixStart ? pathStart : suffixStart;
  const authority = value.slice(authorityStart, authorityEnd);
  if (
    authority !== rawAuthority ||
    url.protocol !== "http:" ||
    (url.hostname !== "127.0.0.1" && url.hostname !== "[::1]") ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.port !== "" &&
      (!/^\d+$/.test(url.port) || Number(url.port) < 1 || Number(url.port) > 65535))
  ) {
    return undefined;
  }
  const path = url.pathname.replace(/\/$/, "");
  if (
    path.length > 64 ||
    rawPath.includes("%") ||
    rawPath.includes("\\") ||
    rawPath.includes("//") ||
    rawPath.split("/").some((part) => part === "." || part === "..") ||
    (path !== "" && !/^\/(?:[A-Za-z0-9_-]+)(?:\/[A-Za-z0-9_-]+)*$/.test(path))
  ) {
    return undefined;
  }
  url.pathname = path || "/";
  return url.toString().replace(/\/$/, "");
}

function parseConfig(value: unknown): LocalAsrConfig | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  const allowed = new Set(["baseUrl", "model", "language", "timeoutMs"]);
  if (Object.keys(value).some((key) => !allowed.has(key))) {
    return undefined;
  }
  const baseUrl = normalizeLocalBaseUrl(value.baseUrl);
  const model = typeof value.model === "string" ? value.model.trim() : "";
  const language = value.language === undefined ? "fr" : value.language;
  const timeoutMs = value.timeoutMs === undefined ? DEFAULT_TIMEOUT_MS : value.timeoutMs;
  if (
    !baseUrl ||
    !model ||
    model.length > 128 ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(model) ||
    typeof language !== "string" ||
    !/^[a-z]{2,3}(?:-[A-Z]{2})?$/.test(language) ||
    typeof timeoutMs !== "number" ||
    !Number.isInteger(timeoutMs) ||
    timeoutMs < 1 ||
    timeoutMs > MAX_TIMEOUT_MS
  ) {
    return undefined;
  }
  return { baseUrl, model, language, timeoutMs };
}

function hasExplicitSelection(cfg: OpenClawConfig | undefined): boolean {
  const entries = cfg?.plugins?.entries;
  const entry: unknown = entries?.["voice-call"];
  if (!isRecord(entry) || !isRecord(entry.config) || !isRecord(entry.config.streaming)) {
    return false;
  }
  return entry.config.streaming.provider === LOCAL_ASR_TRANSCRIPTION_PROVIDER_ID;
}

function toWave(pcm: Buffer): Buffer {
  const wave = Buffer.allocUnsafe(44 + pcm.length);
  wave.write("RIFF", 0, "ascii");
  wave.writeUInt32LE(36 + pcm.length, 4);
  wave.write("WAVE", 8, "ascii");
  wave.write("fmt ", 12, "ascii");
  wave.writeUInt32LE(16, 16);
  wave.writeUInt16LE(1, 20);
  wave.writeUInt16LE(1, 22);
  wave.writeUInt32LE(8_000, 24);
  wave.writeUInt32LE(16_000, 28);
  wave.writeUInt16LE(2, 32);
  wave.writeUInt16LE(16, 34);
  wave.write("data", 36, "ascii");
  wave.writeUInt32LE(pcm.length, 40);
  pcm.copy(wave, 44);
  return wave;
}

function errorCode(error: unknown, timedOut: boolean): string {
  if (timedOut) {
    return ERROR_CODES.requestTimeout;
  }
  if (error instanceof GuardedFetchRedirectError) {
    return ERROR_CODES.redirectRejected;
  }
  return ERROR_CODES.transportFailed;
}

function createLocalAsrSession(
  request: RealtimeTranscriptionSessionCreateRequest,
): RealtimeTranscriptionSession {
  const config = parseConfig(request.providerConfig);
  const selected = hasExplicitSelection(request.cfg);
  const chunks: Buffer[] = [];
  let byteLength = 0;
  let connected = false;
  let closed = false;
  let cancelled = false;
  let failed = false;
  let uploadStarted = false;
  let controller: AbortController | undefined;

  const report = (code: string) => {
    if (!cancelled && !failed) {
      failed = true;
      request.onError?.(new Error(code));
    }
  };

  const upload = async (): Promise<void> => {
    if (!config || !selected) {
      report(ERROR_CODES.configInvalid);
      return;
    }
    if (byteLength === 0 || cancelled) {
      return;
    }
    const pcMu = Buffer.concat(chunks, byteLength);
    chunks.length = 0;
    byteLength = 0;
    const wave = toWave(mulawToPcm(pcMu));
    const url = `${config.baseUrl}/audio/transcriptions`;
    const policy = ssrfPolicyFromHttpBaseUrlAllowedOrigin(config.baseUrl);
    if (!policy) {
      report(ERROR_CODES.configInvalid);
      return;
    }
    const abort = new AbortController();
    controller = abort;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      abort.abort();
    }, config.timeoutMs);
    timeout.unref?.();
    let guarded: Awaited<ReturnType<typeof fetchConfiguredLocalOriginWithSsrFGuard>> | undefined;
    try {
      const form = buildAudioTranscriptionFormData({
        buffer: wave,
        fileName: "dictation.wav",
        mime: "audio/wav",
        fields: { model: config.model, language: config.language },
      });
      guarded = await fetchConfiguredLocalOriginWithSsrFGuard({
        url,
        init: { method: "POST", body: form, signal: abort.signal, redirect: "manual" },
        signal: abort.signal,
        timeoutMs: config.timeoutMs,
        maxRedirects: 0,
        policy,
        configuredLocalOriginBaseUrl: config.baseUrl,
        auditContext: "voice-call-local-clip transcription",
      });
      if (!guarded.response.ok) {
        report(
          guarded.response.status >= 300 && guarded.response.status < 400
            ? ERROR_CODES.redirectRejected
            : ERROR_CODES.httpRejected,
        );
        return;
      }
      const payload = await readProviderJsonObjectResponse(
        guarded.response,
        "local transcription response",
        { maxBytes: MAX_RESPONSE_BYTES },
      ).catch(() => {
        report(timedOut ? ERROR_CODES.requestTimeout : ERROR_CODES.responseInvalid);
        return undefined;
      });
      if (timedOut || abort.signal.aborted) {
        report(ERROR_CODES.requestTimeout);
        return;
      }
      if (!payload || cancelled) {
        return;
      }
      const text = typeof payload.text === "string" ? payload.text.trim() : "";
      if (!text) {
        report(ERROR_CODES.emptyTranscript);
        return;
      }
      request.onTranscript?.(requireTranscriptionText(text, ERROR_CODES.emptyTranscript));
    } catch (error) {
      if (!cancelled) {
        report(errorCode(error, timedOut));
      }
    } finally {
      clearTimeout(timeout);
      controller = undefined;
      if (guarded) {
        await guarded.response.body?.cancel().catch(() => undefined);
        await guarded.release().catch(() => undefined);
      }
    }
  };

  return {
    async connect() {
      if (closed || cancelled || failed) {
        return;
      }
      if (!config || !selected) {
        report(ERROR_CODES.configInvalid);
        return;
      }
      connected = true;
    },
    sendAudio(audio) {
      if (closed || cancelled || failed || !connected) {
        return;
      }
      if (byteLength + audio.length > MAX_CLIP_BYTES) {
        chunks.length = 0;
        byteLength = 0;
        report(ERROR_CODES.clipTooLarge);
        return;
      }
      if (audio.length > 0) {
        chunks.push(Buffer.from(audio));
        byteLength += audio.length;
      }
    },
    close() {
      if (closed || cancelled || uploadStarted) {
        return;
      }
      closed = true;
      uploadStarted = true;
      void upload();
    },
    cancel() {
      if (cancelled) {
        return;
      }
      cancelled = true;
      closed = true;
      chunks.length = 0;
      byteLength = 0;
      controller?.abort();
    },
    isConnected() {
      return connected && !closed && !cancelled && !failed;
    },
  };
}

export function createLocalAsrTranscriptionProvider(): RealtimeTranscriptionProviderPlugin {
  return {
    id: LOCAL_ASR_TRANSCRIPTION_PROVIDER_ID,
    label: "Local clip transcription",
    isConfigured: ({ cfg, providerConfig }) =>
      hasExplicitSelection(cfg) && parseConfig(providerConfig) !== undefined,
    createSession: createLocalAsrSession,
  };
}
