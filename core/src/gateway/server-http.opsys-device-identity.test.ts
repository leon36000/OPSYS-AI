// `GET /opsys/identite` is mounted on the real Gateway HTTP server (OPSYS-AI PLAN T1.4-c5), behind the
// gateway authentication. The handler itself, with a real device pairing and the real OPSYS fragments,
// is proven in `opsys-device-identity-http.test.ts`; this file proves only that the route exists in
// `createGatewayHttpServer` (a route that was never mounted answers 404, not 401 or 403), that it
// asks for authentication, and that the shared secret is not an identity.
import { describe, expect, it } from "vitest";
import { AUTH_TOKEN, withGatewayServer } from "./server-http.test-harness.js";

async function withListeningGateway(run: (origin: string) => Promise<void>): Promise<void> {
  await withGatewayServer({
    prefix: "opsys-device-identity-route",
    resolvedAuth: AUTH_TOKEN,
    run: async (server) => {
      await new Promise<void>((resolve) => {
        server.listen(0, "127.0.0.1", resolve);
      });
      try {
        const address = server.address();
        if (!address || typeof address === "string") {
          throw new Error("Expected an HTTP listener address");
        }
        await run(`http://127.0.0.1:${address.port}`);
      } finally {
        await new Promise<void>((resolve, reject) => {
          server.close((error) => (error ? reject(error) : resolve()));
        });
      }
    },
  });
}

describe("gateway HTTP route /opsys/identite", () => {
  it("is mounted and requires authentication: no bearer gives 401, not 404", async () => {
    await withListeningGateway(async (origin) => {
      const res = await fetch(`${origin}/opsys/identite`, { method: "GET" });

      expect(res.status).toBe(401);
    });
  });

  it("refuses a bearer that is not a device token (the shared secret) with 403 and no identity", async () => {
    await withListeningGateway(async (origin) => {
      const res = await fetch(`${origin}/opsys/identite?deviceId=tel-employe-42`, {
        method: "GET",
        headers: { authorization: "Bearer test-token" },
      });

      expect(res.status).toBe(403);
      const body = (await res.json()) as { ok: boolean; error?: { reason?: string } };
      expect(body.ok).toBe(false);
      expect(body.error?.reason).toBe("device_required");
      expect(body).not.toHaveProperty("identite");
    });
  });

  it("answers GET only", async () => {
    await withListeningGateway(async (origin) => {
      const res = await fetch(`${origin}/opsys/identite`, {
        method: "POST",
        headers: { authorization: "Bearer test-token" },
      });

      expect(res.status).toBe(405);
      expect(res.headers.get("allow")).toBe("GET");
    });
  });
});

describe("gateway HTTP route /opsys/m6/preuves/photo", () => {
  it("mounts the protected photo route before generic fallthrough", async () => {
    await withListeningGateway(async (origin) => {
      const res = await fetch(`${origin}/opsys/m6/preuves/photo`, { method: "POST" });
      expect(res.status).toBe(401);
    });
  });
});
