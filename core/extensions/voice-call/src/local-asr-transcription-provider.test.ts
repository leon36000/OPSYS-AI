import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import { describe, expect, it, vi } from "vitest";
import {
  createLocalAsrTranscriptionProvider,
  LOCAL_ASR_TRANSCRIPTION_PROVIDER_ID,
} from "./local-asr-transcription-provider.js";

type HttpHandler = (
  request: IncomingMessage,
  response: ServerResponse,
  body: Buffer,
) => void | Promise<void>;

async function startServer(handler: HttpHandler): Promise<{
  server: Server;
  baseUrl: string;
  requests: () => number;
}> {
  let requestCount = 0;
  const server = createServer((request, response) => {
    requestCount += 1;
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    request.on("end", () => {
      void handler(request, response, Buffer.concat(chunks));
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("expected an HTTP server address");
  }
  return { server, baseUrl: `http://127.0.0.1:${address.port}`, requests: () => requestCount };
}

async function stopServer(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => {
      if (error) {
        reject(error);
      } else {
        resolve();
      }
    });
  });
}

function runtimeConfig(provider = LOCAL_ASR_TRANSCRIPTION_PROVIDER_ID): OpenClawConfig {
  return {
    plugins: {
      entries: {
        "voice-call": { config: { streaming: { provider } } },
      },
    },
  } as OpenClawConfig;
}

function createSession(
  baseUrl: string,
  callbacks: { onTranscript?: (text: string) => void; onError?: (error: Error) => void } = {},
  options: { cfg?: OpenClawConfig; model?: string; timeoutMs?: number } = {},
) {
  return createLocalAsrTranscriptionProvider().createSession({
    providerConfig: {
      baseUrl,
      model: options.model ?? "whisper-local",
      ...(options.timeoutMs ? { timeoutMs: options.timeoutMs } : {}),
    },
    cfg: options.cfg ?? runtimeConfig(),
    ...callbacks,
  });
}

describe("voice-call local clip transcription provider", () => {
  it("requires a valid loopback config and explicit server selection", () => {
    const provider = createLocalAsrTranscriptionProvider();
    const baseConfig = { baseUrl: "http://127.0.0.1:9000", model: "whisper-local" };
    expect(provider.isConfigured({ cfg: runtimeConfig(), providerConfig: baseConfig })).toBe(true);
    expect(
      provider.isConfigured({
        cfg: runtimeConfig(""),
        providerConfig: baseConfig,
      }),
    ).toBe(false);
    for (const baseUrl of [
      "http://localhost:9000",
      "http://127.0.0.1",
      "http://192.168.1.2:9000",
      "http://2130706433:9000",
      "http://0177.0.0.1:9000",
      "http://0x7f000001:9000",
      "http://127.1:9000",
      "http://127.0.0.1\\@192.168.1.2:9000",
      "http://[0:0:0:0:0:0:0:1]:9000",
      "http://127.0.0.1:9000?x=1",
      "http://user:pass@127.0.0.1:9000",
      "http://127.0.0.1:9000/a/../b",
      "https://127.0.0.1:9000",
    ]) {
      expect(
        provider.isConfigured({ cfg: runtimeConfig(), providerConfig: { ...baseConfig, baseUrl } }),
      ).toBe(false);
    }
    expect(
      provider.isConfigured({
        cfg: runtimeConfig(),
        providerConfig: { ...baseConfig, baseUrl: "http://[::1]:9000" },
      }),
    ).toBe(true);
    expect(
      provider.isConfigured({
        cfg: runtimeConfig(),
        providerConfig: { ...baseConfig, extra: true },
      }),
    ).toBe(false);
  });

  it("connects without network access, sends a valid WAV multipart clip once, and closes idempotently", async () => {
    let body = Buffer.alloc(0);
    const server = await startServer((_request, response, requestBody) => {
      body = requestBody;
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ text: "  Québec local  " }));
    });
    try {
      const transcript = vi.fn();
      const failure = vi.fn();
      const session = createSession(server.baseUrl, { onTranscript: transcript, onError: failure });
      await session.connect();
      expect(server.requests()).toBe(0);
      session.sendAudio(Buffer.from([0xff, 0x7f, 0x00]));
      session.close();
      expect(session.isConnected()).toBe(false);
      session.close();
      await vi.waitFor(() => expect(transcript).toHaveBeenCalledOnce());
      expect(transcript).toHaveBeenCalledWith("Québec local");
      expect(failure).not.toHaveBeenCalled();
      expect(server.requests()).toBe(1);
      expect(body.toString("latin1")).toContain('name="model"');
      expect(body.toString("latin1")).toContain("whisper-local");
      expect(body.toString("latin1")).toContain('name="language"');
      expect(body.toString("latin1")).toContain('filename="dictation.wav"');
      const wavHeader = body.indexOf(Buffer.from("RIFF"));
      expect(wavHeader).toBeGreaterThanOrEqual(0);
      expect(body.subarray(wavHeader + 8, wavHeader + 12).toString("ascii")).toBe("WAVE");
      expect(body.readUInt32LE(wavHeader + 24)).toBe(8_000);
      expect(body.readUInt16LE(wavHeader + 34)).toBe(16);
      expect(body.readUInt32LE(wavHeader + 40)).toBe(6);
    } finally {
      await stopServer(server.server);
    }
  });

  it("emits a fixed configuration code when an invalid session is forced", async () => {
    const failure = vi.fn();
    const session = createSession(
      "http://2130706433:9000",
      { onError: failure },
      { cfg: runtimeConfig() },
    );
    await session.connect();
    expect(failure).toHaveBeenCalledOnce();
    expect(failure.mock.calls[0]?.[0].message).toBe("LOCAL_ASR_CONFIG_INVALID");
  });

  it("rejects cumulative clips over thirty seconds without posting any prefix", async () => {
    const server = await startServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ text: "should not be used" }));
    });
    try {
      const failure = vi.fn();
      const session = createSession(server.baseUrl, { onError: failure });
      await session.connect();
      session.sendAudio(Buffer.alloc(120_001));
      session.sendAudio(Buffer.alloc(120_000));
      expect(session.isConnected()).toBe(false);
      session.close();
      await vi.waitFor(() => expect(failure).toHaveBeenCalledOnce());
      expect(failure.mock.calls[0]?.[0].message).toBe("LOCAL_ASR_CLIP_TOO_LARGE");
      expect(server.requests()).toBe(0);
    } finally {
      await stopServer(server.server);
    }
  });

  it("does not reconnect after close and reports only a fixed timeout code", async () => {
    let markStarted!: () => void;
    const started = new Promise<void>((resolve) => {
      markStarted = resolve;
    });
    const server = await startServer((_request, _response) => {
      markStarted();
    });
    try {
      const idleSession = createSession(server.baseUrl);
      await idleSession.connect();
      idleSession.close();
      expect(idleSession.isConnected()).toBe(false);
      await idleSession.connect();
      idleSession.sendAudio(Buffer.from([0xff]));
      idleSession.close();
      expect(server.requests()).toBe(0);

      const failure = vi.fn();
      const session = createSession(server.baseUrl, { onError: failure }, { timeoutMs: 50 });
      await session.connect();
      session.sendAudio(Buffer.from([0xff]));
      session.close();
      await started;
      await vi.waitFor(() => expect(failure).toHaveBeenCalledOnce(), { timeout: 1_000 });
      expect(failure).toHaveBeenCalledOnce();
      expect(failure.mock.calls[0]?.[0].message).toBe("LOCAL_ASR_REQUEST_TIMEOUT");
    } finally {
      await stopServer(server.server);
    }
  });

  it("reports a timeout when response headers arrive but the JSON body stalls", async () => {
    let markStarted!: () => void;
    const started = new Promise<void>((resolve) => {
      markStarted = resolve;
    });
    const server = await startServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.flushHeaders();
      response.write('{"text":"unfinished');
      markStarted();
    });
    try {
      const failure = vi.fn();
      const transcript = vi.fn();
      const session = createSession(
        server.baseUrl,
        { onError: failure, onTranscript: transcript },
        { timeoutMs: 50 },
      );
      await session.connect();
      session.sendAudio(Buffer.from([0xff]));
      session.close();
      await started;
      await vi.waitFor(() => expect(failure).toHaveBeenCalledOnce(), { timeout: 1_000 });

      expect(failure.mock.calls[0]?.[0].message).toBe("LOCAL_ASR_REQUEST_TIMEOUT");
      expect(transcript).not.toHaveBeenCalled();
    } finally {
      await stopServer(server.server);
    }
  });

  it("cancels before commit without posting and ignores close after cancellation", async () => {
    const server = await startServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ text: "discarded" }));
    });
    try {
      const transcript = vi.fn();
      const failure = vi.fn();
      const session = createSession(server.baseUrl, { onTranscript: transcript, onError: failure });
      await session.connect();
      session.sendAudio(Buffer.from([0xff, 0x7f]));
      session.cancel?.();
      session.cancel?.();
      session.close();
      expect(server.requests()).toBe(0);
      expect(transcript).not.toHaveBeenCalled();
      expect(failure).not.toHaveBeenCalled();
    } finally {
      await stopServer(server.server);
    }
  });

  it("rejects redirects and never follows the redirect target", async () => {
    const target = await startServer((_request, response) => response.end("must not be called"));
    const server = await startServer((_request, response) => {
      response.writeHead(302, { location: target.baseUrl });
      response.end();
    });
    try {
      const failure = vi.fn();
      const session = createSession(server.baseUrl, { onError: failure });
      await session.connect();
      session.sendAudio(Buffer.from([0xff]));
      session.close();
      await vi.waitFor(() => expect(failure).toHaveBeenCalledOnce());
      expect(failure.mock.calls[0]?.[0].message).toBe("LOCAL_ASR_REDIRECT_REJECTED");
      expect(target.requests()).toBe(0);
    } finally {
      await Promise.all([stopServer(server.server), stopServer(target.server)]);
    }
  });

  it.each([
    [413, JSON.stringify({ detail: "private response details" }), "LOCAL_ASR_HTTP_REJECTED"],
    [200, JSON.stringify({ text: "" }), "LOCAL_ASR_EMPTY_TRANSCRIPT"],
    [200, "{".padEnd(9 * 1024, "x"), "LOCAL_ASR_RESPONSE_INVALID"],
  ])(
    "maps HTTP/response failures to fixed codes without sensitive details",
    async (status, payload, code) => {
      const server = await startServer((_request, response) => {
        response.writeHead(status, { "content-type": "application/json" });
        response.end(payload);
      });
      try {
        const failure = vi.fn();
        const session = createSession(server.baseUrl, { onError: failure });
        await session.connect();
        session.sendAudio(Buffer.from("private-audio"));
        session.close();
        await vi.waitFor(() => expect(failure).toHaveBeenCalledOnce());
        expect(failure.mock.calls[0]?.[0].message).toBe(code);
        expect(failure.mock.calls[0]?.[0].message).not.toContain(server.baseUrl);
        expect(failure.mock.calls[0]?.[0].message).not.toContain("private response details");
        expect(failure.mock.calls[0]?.[0].message).not.toContain("private-audio");
      } finally {
        await stopServer(server.server);
      }
    },
  );

  it("aborts an in-flight upload and suppresses its late transcript after cancel", async () => {
    let markStarted!: () => void;
    let releaseResponse!: () => void;
    let markClosed!: () => void;
    const started = new Promise<void>((resolve) => {
      markStarted = resolve;
    });
    const responseReleased = new Promise<void>((resolve) => {
      releaseResponse = resolve;
    });
    const responseClosed = new Promise<void>((resolve) => {
      markClosed = resolve;
    });
    const server = await startServer(async (_request, response) => {
      response.once("close", markClosed);
      markStarted();
      await responseReleased;
      if (!response.destroyed) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ text: "too late" }));
      }
    });
    try {
      const transcript = vi.fn();
      const failure = vi.fn();
      const session = createSession(server.baseUrl, { onTranscript: transcript, onError: failure });
      await session.connect();
      session.sendAudio(Buffer.from([0xff, 0x7f]));
      session.close();
      await started;
      session.cancel?.();
      releaseResponse();
      await responseClosed;
      expect(server.requests()).toBe(1);
      expect(transcript).not.toHaveBeenCalled();
      expect(failure).not.toHaveBeenCalled();
    } finally {
      await stopServer(server.server);
    }
  });
});
