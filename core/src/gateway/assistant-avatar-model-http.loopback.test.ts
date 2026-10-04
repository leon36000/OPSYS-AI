import { createHash } from "node:crypto";
import fs from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoCleanupTempDirTracker } from "../../test/helpers/temp-dir.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import * as boundaryFileRead from "../infra/boundary-file-read.js";
import { closeStateDatabaseForTest } from "../test-utils/database-cleanup.js";
import type { ResolvedGatewayAuth } from "./auth.js";
import { handleControlUiAvatarRequest } from "./control-ui.js";

const TEST_TOKEN = "avatar-loopback-shared-token";
const MODEL_ID = "robotexpressive-quaternius-cc0-v1";
const EXPECTED_SHA256 = "047f5e5fb3bb6d378bd1df16ca6137f2a596c99b3a1b5690b4020c05aaf6f319";
const EXPECTED_BYTES = fs.readFileSync(
  new URL("../../assets/avatar-models/robotexpressive-quaternius-cc0-v1.glb", import.meta.url),
);
const tempDirs = useAutoCleanupTempDirTracker(afterEach);

type ModelResponse = {
  status: number;
  headers: Headers;
  body: Buffer;
};

describe("authenticated assistant avatar model over loopback HTTP", () => {
  let server: Server;
  let origin: string;
  let runtimeConfig: OpenClawConfig;
  let runtimeAuth: ResolvedGatewayAuth;

  beforeAll(async () => {
    server = createServer((req, res) => {
      void handleControlUiAvatarRequest(req, res, {
        config: runtimeConfig,
        cfg: runtimeConfig,
        auth: runtimeAuth,
        getRuntimeConfig: () => runtimeConfig,
        getResolvedAuth: () => runtimeAuth,
      }).catch(() => {
        if (!res.writableEnded && !res.destroyed) {
          res.statusCode = 500;
          res.end("Request failed");
        }
      });
    });
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    const address = server.address() as AddressInfo;
    origin = `http://127.0.0.1:${address.port}`;
  });

  beforeEach(() => {
    vi.stubEnv("OPENCLAW_STATE_DIR", tempDirs.make("avatar-model-loopback-"));
    runtimeConfig = {
      agents: {
        list: [{ id: "main", identity: { avatarModelId: MODEL_ID } }],
      },
    };
    runtimeAuth = { mode: "token", token: TEST_TOKEN, allowTailscale: false };
  });

  afterEach(async () => {
    await closeStateDatabaseForTest();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  afterAll(async () => {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  });

  async function send(
    method: "GET" | "HEAD",
    agentId = "main",
    token?: string,
  ): Promise<ModelResponse> {
    const response = await fetch(`${origin}/avatar-model/${agentId}`, {
      method,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return {
      status: response.status,
      headers: response.headers,
      body: Buffer.from(await response.arrayBuffer()),
    };
  }

  function expectNoModelRepresentation(response: ModelResponse) {
    expect(response.body).not.toEqual(EXPECTED_BYTES);
    expect(response.headers.get("content-length")).not.toBe(String(EXPECTED_BYTES.length));
    expect(response.headers.get("content-type")).not.toBe("model/gltf-binary");
  }

  it("serves the exact pinned GLB only to the valid bearer token", async () => {
    const response = await send("GET", "main", TEST_TOKEN);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("model/gltf-binary");
    expect(response.headers.get("content-length")).toBe(String(EXPECTED_BYTES.length));
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("vary")).toContain("Authorization");
    expect(response.headers.get("vary")).toContain("Cookie");
    expect(createHash("sha256").update(response.body).digest("hex")).toBe(EXPECTED_SHA256);
    expect(response.body).toEqual(EXPECTED_BYTES);
  });

  it("preserves the representation length for authorized HEAD without returning bytes", async () => {
    const response = await send("HEAD", "main", TEST_TOKEN);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-length")).toBe(String(EXPECTED_BYTES.length));
    expect(response.headers.get("content-type")).toBe("model/gltf-binary");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.body).toHaveLength(0);
  });

  it.each([
    { method: "GET" as const, token: undefined, credential: "missing" },
    { method: "HEAD" as const, token: undefined, credential: "missing" },
    { method: "GET" as const, token: "wrong-loopback-token", credential: "invalid" },
    { method: "HEAD" as const, token: "wrong-loopback-token", credential: "invalid" },
  ])("rejects $method with $credential bearer credentials", async ({ method, token }) => {
    const response = await send(method, "main", token);

    expect(response.status).toBe(401);
    expectNoModelRepresentation(response);
  });

  it.each(["GET", "HEAD"] as const)(
    "returns a generic not-found for an unknown agent on %s despite a valid token",
    async (method) => {
      const response = await send(method, "ghost", TEST_TOKEN);

      expect(response.status).toBe(404);
      expectNoModelRepresentation(response);
    },
  );

  it("withholds model bytes if the operator grant policy changes during the file read", async () => {
    let enteredRead!: () => void;
    let releaseRead!: () => void;
    const entered = new Promise<void>((resolve) => {
      enteredRead = resolve;
    });
    const blocked = new Promise<void>((resolve) => {
      releaseRead = resolve;
    });
    const originalRead = boundaryFileRead.readFileDescriptorBounded;
    vi.spyOn(boundaryFileRead, "readFileDescriptorBounded").mockImplementation(async (...args) => {
      const bytes = await originalRead(...args);
      enteredRead();
      await blocked;
      return bytes;
    });

    const pending = send("GET", "main", TEST_TOKEN);
    await Promise.race([
      entered,
      pending.then(() => {
        throw new Error("response completed before the controlled file read");
      }),
    ]);
    runtimeConfig = { ...runtimeConfig, gateway: { roles: { definitions: {} } } };
    releaseRead();
    const response = await pending;

    expect(response.status).toBe(401);
    expectNoModelRepresentation(response);
  });

  it("withholds model bytes if the current config removes its assignment during the read", async () => {
    let enteredRead!: () => void;
    let releaseRead!: () => void;
    const entered = new Promise<void>((resolve) => {
      enteredRead = resolve;
    });
    const blocked = new Promise<void>((resolve) => {
      releaseRead = resolve;
    });
    const originalRead = boundaryFileRead.readFileDescriptorBounded;
    vi.spyOn(boundaryFileRead, "readFileDescriptorBounded").mockImplementation(async (...args) => {
      const bytes = await originalRead(...args);
      enteredRead();
      await blocked;
      return bytes;
    });

    const pending = send("GET", "main", TEST_TOKEN);
    await Promise.race([
      entered,
      pending.then(() => {
        throw new Error("response completed before the controlled file read");
      }),
    ]);
    runtimeConfig = { agents: { list: [{ id: "main", identity: {} }] } };
    releaseRead();
    const response = await pending;

    expect(response.status).toBe(404);
    expectNoModelRepresentation(response);
  });
});
