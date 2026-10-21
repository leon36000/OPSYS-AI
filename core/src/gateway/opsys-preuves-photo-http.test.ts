// Fictitious photos and bridge responses. Real device pairing, HTTP sockets and sidecar files;
// this does not execute the Python bridge, CAS, mobile runtime or a production server.
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import { createServer, request, type Server } from "node:http";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDeferred } from "../../test/helpers/promise.js";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken, revokeDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing } from "../infra/device-pairing.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import { AUTH_TOKEN } from "./server-http.test-harness.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";

const route = "/opsys/m6/preuves/photo";
const tool = "m6_lire_preuves_pertes_wct_appareil";
const selection = {
  wct_id: "a".repeat(64),
  preuve: { index: 0, hash_maillon: "b".repeat(64) },
  position_photo: 0,
};
const png = Buffer.concat([Buffer.from("89504e470d0a1a0a", "hex"), Buffer.alloc(70000, 7)]);
const sha = createHash("sha256").update(png).digest("hex");
const privateToken = "fictif-private-bridge-token";
const nativeFetch = globalThis.fetch;

let cfg = {};
vi.mock("../config/io.js", () => ({ getRuntimeConfig: () => cfg }));
vi.mock("../config/config.js", () => ({ getRuntimeConfig: () => cfg }));
afterEach(() => {
  cfg = {};
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", resolve);
  });
  const a = server.address();
  if (!a || typeof a === "string") {
    throw new Error("Missing listener");
  }
  return `http://127.0.0.1:${a.port}`;
}
async function close(server: Server): Promise<void> {
  server.closeAllConnections();
  await new Promise<void>((resolve, reject) => {
    server.close((e) => (e ? reject(e) : resolve()));
  });
}

type Fixture = {
  token: string;
  origin: string;
  dir: string;
  calls: { path: string; body: unknown }[];
  image: Buffer;
  hash: string;
  mime: string;
  length: string;
  encoding?: string;
  finished: Promise<void>;
  imageClosed: Promise<void>;
  closedResponses: number;
  imageStatus: number;
  revalidationStatus: number;
  metadataChange: boolean;
  onImage: () => Promise<void>;
  onRevalidate: (count: number) => Promise<void>;
};
async function withFixture(
  run: (f: Fixture) => Promise<void>,
  scopes = ["operator.read"],
): Promise<void> {
  await withOpenClawTestState({ label: "opsys-photo-http" }, async (state) => {
    const dir = path.join(path.dirname(state.configPath), "opsys");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, "appareils.json"),
      JSON.stringify({ appareils: { photo: { personne: "nathan_owner", role: "admin" } } }),
    );
    fs.writeFileSync(
      path.join(dir, "roles.json"),
      JSON.stringify({ roles: { admin: [tool] }, serveurs: { [tool]: "opsys_m6" } }),
    );
    const pair = await requestDevicePairing({
      deviceId: "photo",
      publicKey: randomUUID(),
      role: "operator",
      scopes,
    });
    await approveDevicePairing(pair.request.requestId, { callerScopes: scopes });
    const token = await ensureDeviceToken({
      deviceId: "photo",
      role: "operator",
      scopes,
      issuer: {
        kind: "shared-gateway-auth",
        generation: resolveSharedGatewaySessionGeneration(AUTH_TOKEN, [])!,
      },
    });
    if (!token) {
      throw new Error("Pairing token unavailable");
    }
    const finished = createDeferred();
    const imageClosed = createDeferred();
    const f: Fixture = {
      token: token.token,
      origin: "",
      dir,
      calls: [],
      image: png,
      hash: sha,
      mime: "image/png",
      length: String(png.length),
      imageStatus: 200,
      revalidationStatus: 200,
      closedResponses: 0,
      finished: finished.promise,
      imageClosed: imageClosed.promise,
      metadataChange: false,
      onImage: async () => {},
      onRevalidate: async () => {},
    };
    let checks = 0;
    const bridge = createServer((req, res) => {
      res.once("close", () => {
        f.closedResponses += 1;
      });
      void (async () => {
        expect(req.headers["accept-encoding"]).toBe("identity");
        expect(req.headers.authorization).toBe(`Bearer ${privateToken}`);
        const buffers = [];
        for await (const c of req) {
          buffers.push(c);
        }
        const body = JSON.parse(Buffer.concat(buffers).toString());
        f.calls.push({ path: req.url!, body });
        if (req.url?.endsWith("/revalider")) {
          await f.onRevalidate(++checks);
          res.writeHead(f.revalidationStatus, { "content-type": "application/json" });
          res.end(
            JSON.stringify(
              f.revalidationStatus === 200
                ? {
                    ok: true,
                    resultat: {
                      accepte: true,
                      reference: `fichier:sha256:${sha}`,
                      empreinte_sha256: f.metadataChange ? "c".repeat(64) : sha,
                      type_mime: "image/png",
                      taille_octets: png.length,
                      autorite: { personne: "nathan_owner", role: "admin", source: "appareil" },
                    },
                  }
                : { ok: false, erreur: "photo_autorite_retiree" },
            ),
          );
        } else {
          res.once("close", () => imageClosed.resolve());
          await f.onImage();
          if (f.imageStatus !== 200) {
            res.writeHead(f.imageStatus, { "content-type": "application/json" });
            res.end('{"ok":false,"erreur":"photo_indisponible"}');
            return;
          }
          res.writeHead(200, {
            "content-type": f.mime,
            "content-length": f.length,
            "x-opsys-sha256": f.hash,
            etag: `"${f.hash}"`,
            ...(f.encoding ? { "content-encoding": f.encoding } : {}),
          });
          res.end(f.image);
        }
      })().catch(() => res.destroy());
    });
    vi.stubEnv("OPSYS_M6_PREUVES_BRIDGE_URL", `${await listen(bridge)}/mcp/fichiers/m6-preuves`);
    vi.stubEnv("OPSYS_M6_PREUVES_BRIDGE_JETON", privateToken);
    const module = await import("./opsys-preuves-photo-http.js");
    const gateway = createServer((req, res) => {
      void (async () => {
        if (await module.handleOpsysPreuvesPhotoHttpRequest(req, res, { auth: AUTH_TOKEN })) {
          return;
        }
        res.writeHead(404);
        res.end();
      })()
        .catch(() => res.destroy())
        .finally(() => finished.resolve());
    });
    f.origin = await listen(gateway);
    try {
      await run(f);
    } finally {
      await close(gateway);
      await close(bridge);
    }
  });
}
const call = (f: Fixture, body: unknown = selection, suffix = "") =>
  nativeFetch(f.origin + route + suffix, {
    method: "POST",
    headers: { authorization: `Bearer ${f.token}`, "content-type": "application/json" },
    body: JSON.stringify(body),
  });

async function interruptedPhoto(f: Fixture, first: () => void): Promise<void> {
  const res = await call(f);
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type")).toBe("image/png");
  if (!res.body) {
    throw new Error("Missing photo stream");
  }
  const reader = res.body.getReader();
  const parts: Buffer[] = [];
  let total = 0;
  let error: unknown;
  try {
    while (true) {
      const item = await reader.read();
      if (item.done) {
        break;
      }
      parts.push(Buffer.from(item.value));
      total += item.value.length;
      if (total === 65536) {
        first();
      }
    }
  } catch (e) {
    error = e;
  }
  expect(error).toBeDefined();
  const prefix = Buffer.concat(parts);
  expect(prefix).toEqual(png.subarray(0, 65536));
  expect(prefix.toString("utf8")).not.toContain('"error"');
  expect(prefix.toString("utf8")).not.toContain('"ok":false');
  await f.finished;
  await f.imageClosed;
  expect(f.closedResponses).toBe(f.calls.length);
}

describe("protected M6 photo bytes", () => {
  it("verifies all bytes, then revalidates each 64 KiB fragment and final end", async () => {
    await withFixture(async (f) => {
      const res = await call(f);
      expect(res.status).toBe(200);
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(res.headers.get("x-content-type-options")).toBe("nosniff");
      expect(res.headers.get("x-opsys-sha256")).toBe(sha);
      expect(Buffer.from(await res.arrayBuffer())).toEqual(png);
      await f.finished;
      expect(f.calls.map((c) => c.path)).toEqual([
        "/mcp/fichiers/m6-preuves",
        ...Array(3).fill("/mcp/fichiers/m6-preuves/revalider"),
      ]);
      for (const c of f.calls) {
        expect(c.body).toEqual({
          selection,
          identite: { personne: "nathan_owner", role: "admin" },
          appareil_id: "photo",
        });
      }
    });
  });
  it.each([
    { ...selection, personne: "other" },
    { ...selection, reference: `fichier:sha256:${sha}` },
    { ...selection, preuve: { ...selection.preuve, url: "https://fictif.invalid" } },
    { ...selection, position_photo: -1 },
    { ...selection, preuve: { index: 0, hash_maillon: "b".repeat(63) } },
  ])("rejects forged or malformed selection before bridge access %j", async (body) => {
    await withFixture(async (f) => {
      expect((await call(f, body)).status).toBe(400);
      expect(f.calls).toHaveLength(0);
    });
  });
  it("rejects a final-newline hash before contacting the bridge", async () => {
    await withFixture(async (f) => {
      expect(
        (
          await call(f, {
            ...selection,
            preuve: { ...selection.preuve, hash_maillon: selection.preuve.hash_maillon + "\n" },
          })
        ).status,
      ).toBe(400);
      expect(f.calls).toHaveLength(0);
    });
  });
  it.each(["?token=fictif", "?deviceId=photo"])("rejects query authority %s", async (suffix) => {
    await withFixture(async (f) => {
      expect((await call(f, selection, suffix)).status).toBe(400);
      expect(f.calls).toHaveLength(0);
    });
  });
  it("requires a DEVICE token, not shared authority", async () => {
    await withFixture(async (f) => {
      const res = await nativeFetch(f.origin + route, {
        method: "POST",
        headers: { authorization: "Bearer test-token" },
        body: JSON.stringify(selection),
      });
      expect(res.status).toBe(403);
      expect(f.calls).toHaveLength(0);
    });
  });
  it("requires the paired operator.read scope", async () => {
    await withFixture(
      async (f) => {
        expect((await call(f)).status).toBe(401);
        expect(f.calls).toHaveLength(0);
      },
      ["operator.approvals"],
    );
  });
  it.each(["employee", "seller"])("refuses named %s before upstream access", async (role) => {
    await withFixture(async (f) => {
      fs.writeFileSync(
        path.join(f.dir, "appareils.json"),
        JSON.stringify({ appareils: { photo: { personne: "fictif", role } } }),
      );
      expect((await call(f)).status).toBe(403);
      expect(f.calls).toHaveLength(0);
    });
  });
  it.each(["token", "person", "scope", "runtime"])(
    "rechecks %s after upstream await",
    async (kind) => {
      await withFixture(async (f) => {
        f.onImage = async () => {
          if (kind === "token") {
            await revokeDeviceToken({ deviceId: "photo", role: "operator" });
          }
          if (kind === "person") {
            fs.writeFileSync(
              path.join(f.dir, "appareils.json"),
              JSON.stringify({ appareils: { photo: { personne: "other", role: "admin" } } }),
            );
          }
          if (kind === "scope") {
            fs.writeFileSync(
              path.join(f.dir, "roles.json"),
              JSON.stringify({ roles: { admin: [] }, serveurs: { [tool]: "opsys_m6" } }),
            );
          }
          if (kind === "runtime") {
            cfg = { gateway: { trustedProxies: ["127.0.0.1"] } };
          }
        };
        const res = await call(f);
        expect([401, 403]).toContain(res.status);
        expect(res.headers.get("content-type")).toContain("application/json");
        expect(f.calls).toHaveLength(1);
      });
    },
  );
  it.each(["hash", "mime", "length", "encoding"])(
    "never emits unverified image with invalid %s",
    async (kind) => {
      await withFixture(async (f) => {
        if (kind === "hash") {
          f.hash = "c".repeat(64);
        }
        if (kind === "mime") {
          f.mime = "image/svg+xml";
        }
        if (kind === "length") {
          f.length = String(10 * 1024 * 1024 + 1);
        }
        if (kind === "encoding") {
          f.encoding = "gzip";
        }
        const res = await call(f);
        expect(res.status).toBe(502);
        expect(res.headers.get("content-type")).toContain("application/json");
        expect(f.calls).toHaveLength(1);
      });
    },
  );
  it.each(["credentials", "query", "path", "public_token"])(
    "refuses invalid private configuration %s",
    async (kind) => {
      await withFixture(async (f) => {
        const url = new URL(process.env.OPSYS_M6_PREUVES_BRIDGE_URL!);
        if (kind === "credentials") {
          url.username = "fictif";
        }
        if (kind === "query") {
          url.search = "?hash=fictif";
        }
        if (kind === "path") {
          url.pathname = "/arbitrary";
        }
        vi.stubEnv("OPSYS_M6_PREUVES_BRIDGE_URL", url.href);
        if (kind === "public_token") {
          vi.stubEnv("OPSYS_M6_PREUVES_BRIDGE_JETON", f.token);
        }
        expect((await call(f)).status).toBe(503);
        expect(f.calls).toHaveLength(0);
      });
    },
  );
  it("returns closed refusal before pixels, interrupts after pixels without JSON", async () => {
    await withFixture(async (f) => {
      f.imageStatus = 409;
      const res = await call(f);
      expect(res.status).toBe(409);
      expect(await res.json()).toEqual({ ok: false, erreur: "photo_indisponible" });
    });
    await withFixture(async (f) => {
      const first = createDeferred();
      f.onRevalidate = async (count) => {
        if (count === 2) {
          await first.promise;
          f.revalidationStatus = 403;
        }
      };
      await interruptedPhoto(f, () => first.resolve());
    });
  });
  it("does not emit bytes when private revalidation metadata changed", async () => {
    await withFixture(async (f) => {
      f.metadataChange = true;
      const res = await call(f);
      expect(res.status).toBe(403);
      expect(res.headers.get("content-type")).toContain("application/json");
    });
  });
  it("aborts the actual upstream socket when the client disconnects", async () => {
    await withFixture(async (f) => {
      const reached = createDeferred();
      const release = createDeferred();
      f.onImage = async () => {
        reached.resolve();
        await release.promise;
      };
      const req = request(f.origin + route, {
        method: "POST",
        headers: { authorization: `Bearer ${f.token}`, "content-type": "application/json" },
      });
      req.on("error", () => {});
      req.end(JSON.stringify(selection));
      await reached.promise;
      req.destroy();
      try {
        await f.imageClosed;
        expect(f.calls).toHaveLength(1);
      } finally {
        release.resolve();
      }
      await f.finished;
    });
  });
  it("enforces the configured deadline by aborting the pending upstream socket", async () => {
    await withFixture(async (f) => {
      const reached = createDeferred();
      const release = createDeferred();
      f.onImage = async () => {
        reached.resolve();
        await release.promise;
      };
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
      const pending = call(f);
      await reached.promise;
      try {
        await vi.advanceTimersByTimeAsync(120_000);
        const res = await pending;
        expect(res.status).toBe(504);
        expect(await res.json()).toEqual({ ok: false, erreur: "photo_delai_depasse" });
        await f.imageClosed;
      } finally {
        vi.useRealTimers();
        release.resolve();
      }
      await f.finished;
    });
  });

  it("rejects duplicate Authorization headers instead of picking one credential", async () => {
    await withFixture(async (f) => {
      const status = await new Promise<number | undefined>((resolve, reject) => {
        const req = request(
          f.origin + route,
          {
            method: "POST",
            headers: [
              "host",
              new URL(f.origin).host,
              "content-length",
              String(Buffer.byteLength(JSON.stringify(selection))),
              "authorization",
              `Bearer ${f.token}`,
              "authorization",
              "Bearer test-token",
              "content-type",
              "application/json",
            ],
          },
          (res) => {
            res.resume();
            resolve(res.statusCode);
          },
        );
        req.on("error", reject);
        req.end(JSON.stringify(selection));
      });
      expect(status).toBe(401);
      expect(f.calls).toHaveLength(0);
    });
  });
  it.each(["token", "person", "scope", "runtime"])(
    "interrupts without JSON when %s changes before a later fragment",
    async (kind) => {
      await withFixture(async (f) => {
        const first = createDeferred();
        f.onRevalidate = async (count) => {
          if (count !== 2) {
            return;
          }
          await first.promise;
          if (kind === "runtime") {
            cfg = { gateway: { trustedProxies: ["127.0.0.1"] } };
          }
          if (kind === "token") {
            await revokeDeviceToken({ deviceId: "photo", role: "operator" });
          }
          if (kind === "person") {
            fs.writeFileSync(
              path.join(f.dir, "appareils.json"),
              JSON.stringify({ appareils: { photo: { personne: "other", role: "admin" } } }),
            );
          }
          if (kind === "scope") {
            fs.writeFileSync(
              path.join(f.dir, "roles.json"),
              JSON.stringify({ roles: { admin: [] }, serveurs: { [tool]: "opsys_m6" } }),
            );
          }
        };
        await interruptedPhoto(f, () => first.resolve());
        expect(f.calls).toHaveLength(3);
      });
    },
  );
});
