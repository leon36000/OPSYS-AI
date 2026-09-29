// `GET /opsys/identite` for a paired OPSYS device (OPSYS-AI PLAN T1.4-c5, docs/architecture/
// MOBILE.md "Identité de l'appareil").
//
// What is REAL here, like `tools-invoke-http.opsys-device-mcp.test.ts`: the HTTP handler; the
// device-token authentication (a real pairing and a real bearer, verified by the unmocked
// `checkGatewayHttpRequestAuth` chain inside `withOpenClawTestState`, which provides the shared-state
// admission a vitest worker needs); the identity read from the REAL `opsys/roles.json` and
// `opsys/appareils.json` fragments on disk, in the shape `src/opsys/openclaw.py` generates. Only the
// runtime config is fixed. The route mounting in the real gateway HTTP server is proven in
// `server-http.opsys-device-identity.test.ts`.
//
// Persons and devices below are fictional.
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken, revokeDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing } from "../infra/device-pairing.js";
import { withOpenClawTestState, type OpenClawTestState } from "../test-utils/openclaw-test-state.js";
import type { ResolvedGatewayAuth } from "./auth-resolve.js";
import { resetOpsysDeviceRolesCacheForTesting } from "./opsys-device-roles.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";

const SHARED_GATEWAY_TOKEN = "test-gateway-token-shared-1234567890";
const SHARED_GATEWAY_AUTH: ResolvedGatewayAuth = {
  mode: "token",
  token: SHARED_GATEWAY_TOKEN,
  password: undefined,
  allowTailscale: false,
};

let cfg: Record<string, unknown> = {};

vi.mock("../config/config.js", () => ({
  getRuntimeConfig: () => cfg,
}));

vi.mock("../config/io.js", () => ({
  getRuntimeConfig: () => cfg,
}));

const { handleOpsysDeviceIdentityHttpRequest } = await import("./opsys-device-identity-http.js");

let port = 0;
let server: ReturnType<typeof createServer> | undefined;

beforeAll(async () => {
  server = createServer((req, res) => {
    void (async () => {
      const handled = await handleOpsysDeviceIdentityHttpRequest(req, res, {
        auth: SHARED_GATEWAY_AUTH,
      });
      if (handled) {
        return;
      }
      res.statusCode = 404;
      res.end("not found");
    })().catch((err: unknown) => {
      res.statusCode = 500;
      res.end(String(err));
    });
  });
  await new Promise<void>((resolve, reject) => {
    server?.once("error", reject);
    server?.listen(0, "127.0.0.1", () => {
      const address = server?.address() as AddressInfo | null;
      port = address?.port ?? 0;
      resolve();
    });
  });
});

afterAll(async () => {
  if (!server) {
    return;
  }
  await new Promise<void>((resolve) => {
    server?.close(() => resolve());
  });
  server = undefined;
});

beforeEach(() => {
  cfg = {};
  resetOpsysDeviceRolesCacheForTesting();
});

const EMPLOYEE_DEVICE = "tel-employe-42";
const SELLER_DEVICE = "tel-vendeur-7";
const ADMIN_DEVICE = "tel-admin-1";
const UNATTRIBUTED_DEVICE = "tel-non-attribue";
const ORPHAN_ROLE_DEVICE = "tel-role-inconnu";

const ROLES_FRAGMENT = {
  roles: {
    employee: ["m4_pointer"],
    seller: ["m2_lire_leads"],
    admin: ["m2_lire_leads", "m4_pointer"],
  },
  serveurs: { m4_pointer: "opsys_m4", m2_lire_leads: "opsys_m2" },
};

const APPAREILS_FRAGMENT = {
  appareils: {
    [EMPLOYEE_DEVICE]: { personne: "jdupont", role: "employee" },
    [SELLER_DEVICE]: { personne: "mtremblay", role: "seller" },
    [ADMIN_DEVICE]: { personne: "nathan_owner", role: "admin" },
    // Attributed a role `roles.json` does not declare: no identity, not a default one.
    [ORPHAN_ROLE_DEVICE]: { personne: "jdupont", role: "operator" },
    // `UNATTRIBUTED_DEVICE` is deliberately absent: paired natively, `opsys appareils appairer` not run.
  },
};

/** What `opsys openclaw configurer` and `opsys appareils appairer` write next to openclaw.json. */
function writeOpsysFragments(
  state: OpenClawTestState,
  fragments: { roles: unknown; appareils: unknown },
): void {
  const dir = path.join(path.dirname(state.configPath), "opsys");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "roles.json"), JSON.stringify(fragments.roles));
  fs.writeFileSync(path.join(dir, "appareils.json"), JSON.stringify(fragments.appareils));
}

/** A real approved "operator"-role paired device in an isolated OpenClaw test state (the pairing and
 * token issuance the mobile appairage flow uses), with the OPSYS fragments on disk. */
async function withPairedDevice<T>(
  deviceId: string,
  fn: (
    deviceToken: string,
    ctx: { state: OpenClawTestState; revoke: () => Promise<void> },
  ) => Promise<T>,
): Promise<T> {
  return await withOpenClawTestState({ label: "opsys-device-identity" }, async (state) => {
    writeOpsysFragments(state, { roles: ROLES_FRAGMENT, appareils: APPAREILS_FRAGMENT });
    const scopes = ["operator.read", "operator.write"];
    const requested = await requestDevicePairing({
      deviceId,
      publicKey: `test-public-key-${randomUUID()}`,
      role: "operator",
      scopes,
    });
    const approved = await approveDevicePairing(requested.request.requestId, {
      callerScopes: scopes,
    });
    if (approved?.status !== "approved") {
      throw new Error(`pairing approval failed: ${approved?.status}`);
    }
    const generation = resolveSharedGatewaySessionGeneration(SHARED_GATEWAY_AUTH, []);
    if (!generation) {
      throw new Error("no shared gateway session generation for the test auth");
    }
    const issued = await ensureDeviceToken({
      deviceId,
      role: "operator",
      scopes,
      issuer: { kind: "shared-gateway-auth", generation },
    });
    if (!issued?.token) {
      throw new Error("no operator device token issued");
    }
    return await fn(issued.token, {
      state,
      revoke: async () => {
        const revoked = await revokeDeviceToken({ deviceId, role: "operator" });
        if (revoked.ok !== true) {
          throw new Error(`revoke failed: ${JSON.stringify(revoked)}`);
        }
      },
    });
  });
}

type IdentityBody = {
  ok: boolean;
  identite?: { appareilId: string; personne: string; role: string };
  error?: { type: string; reason: string; message: string };
};

/** The request the app sends (`mobile/src/identite/client.ts`): a GET with the device token. */
async function readIdentity(
  token: string | undefined,
  search = "",
  headers: Record<string, string> = {},
) {
  return await fetch(`http://127.0.0.1:${port}/opsys/identite${search}`, {
    method: "GET",
    headers: { ...(token ? { authorization: `Bearer ${token}` } : {}), ...headers },
  });
}

describe("GET /opsys/identite: the device is told who it is, by the server", () => {
  it.each([
    [EMPLOYEE_DEVICE, "jdupont", "employee"],
    [SELLER_DEVICE, "mtremblay", "seller"],
    [ADMIN_DEVICE, "nathan_owner", "admin"],
  ])("gives device %s its OPSYS person %s and named role %s, read from appareils.json", async (deviceId, personne, role) => {
    await withPairedDevice(deviceId, async (deviceToken) => {
      const res = await readIdentity(deviceToken);

      expect(res.status).toBe(200);
      expect(res.headers.get("cache-control")).toBe("no-store");
      const body = (await res.json()) as IdentityBody;
      expect(body).toEqual({ ok: true, identite: { appareilId: deviceId, personne, role } });
    });
  });

  it("reads nothing the app sends: a query, headers and scope claims cannot name another device, person or role", async () => {
    await withPairedDevice(EMPLOYEE_DEVICE, async (deviceToken) => {
      const res = await readIdentity(
        deviceToken,
        `?deviceId=${ADMIN_DEVICE}&appareilId=${ADMIN_DEVICE}&personne=nathan_owner&role=admin`,
        {
          "x-opsys-personne": "nathan_owner",
          "x-opsys-role": "admin",
          "x-openclaw-scopes": "operator.admin",
        },
      );

      expect(res.status).toBe(200);
      const body = (await res.json()) as IdentityBody;
      expect(body).toEqual({
        ok: true,
        identite: { appareilId: EMPLOYEE_DEVICE, personne: "jdupont", role: "employee" },
      });
    });
  });

  it("gives no identity to a paired device that is not attributed yet (native approval done, `opsys appareils appairer` not run)", async () => {
    await withPairedDevice(UNATTRIBUTED_DEVICE, async (deviceToken) => {
      const res = await readIdentity(deviceToken);

      expect(res.status).toBe(403);
      const body = (await res.json()) as IdentityBody;
      expect(body.ok).toBe(false);
      expect(body.error?.type).toBe("forbidden");
      expect(body.error?.reason).toBe("device_unknown");
      expect(body).not.toHaveProperty("identite");
    });
  });

  it("gives no identity to a device attributed a role roles.json does not declare", async () => {
    await withPairedDevice(ORPHAN_ROLE_DEVICE, async (deviceToken) => {
      const res = await readIdentity(deviceToken);

      expect(res.status).toBe(403);
      const body = (await res.json()) as IdentityBody;
      expect(body.error?.reason).toBe("role_unknown");
      expect(body).not.toHaveProperty("identite");
    });
  });

  it("stops giving the identity as soon as the attribution is revoked, without any new pairing", async () => {
    await withPairedDevice(EMPLOYEE_DEVICE, async (deviceToken, ctx) => {
      expect((await readIdentity(deviceToken)).status).toBe(200);

      // `opsys appareils revoquer` regenerates appareils.json without the device (the file shrinks on purpose:
      // the cache keys on mtime and size).
      writeOpsysFragments(ctx.state, { roles: ROLES_FRAGMENT, appareils: { appareils: {} } });

      const res = await readIdentity(deviceToken);
      expect(res.status).toBe(403);
      const body = (await res.json()) as IdentityBody;
      expect(body.error?.reason).toBe("device_unknown");
      expect(body).not.toHaveProperty("identite");
    });
  });

  it("follows a re-attribution: the next read gives the new person and role", async () => {
    await withPairedDevice(EMPLOYEE_DEVICE, async (deviceToken, ctx) => {
      const before = (await (await readIdentity(deviceToken)).json()) as IdentityBody;
      expect(before.identite?.personne).toBe("jdupont");

      writeOpsysFragments(ctx.state, {
        roles: ROLES_FRAGMENT,
        appareils: { appareils: { [EMPLOYEE_DEVICE]: { personne: "mtremblay", role: "seller" } } },
      });

      const body = (await (await readIdentity(deviceToken)).json()) as IdentityBody;
      expect(body.identite).toEqual({
        appareilId: EMPLOYEE_DEVICE,
        personne: "mtremblay",
        role: "seller",
      });
    });
  });

  it("rejects a revoked device token with 401 and no identity", async () => {
    await withPairedDevice(EMPLOYEE_DEVICE, async (deviceToken, ctx) => {
      await ctx.revoke();

      const res = await readIdentity(deviceToken);

      expect(res.status).toBe(401);
      expect(await res.text()).not.toContain("jdupont");
    });
  });

  it("rejects a bearer that matches no paired device, and a request with no bearer, with 401", async () => {
    await withPairedDevice(EMPLOYEE_DEVICE, async () => {
      const unknownToken = "un-jeton-invente-qui-ne-correspond-a-aucun-appareil";
      expect((await readIdentity(unknownToken)).status).toBe(401);
      expect((await readIdentity(undefined)).status).toBe(401);
    });
  });

  it("gives the shared secret no identity: it proves the gateway secret, not a device", async () => {
    await withPairedDevice(EMPLOYEE_DEVICE, async () => {
      const res = await readIdentity(SHARED_GATEWAY_TOKEN, `?deviceId=${EMPLOYEE_DEVICE}`);

      expect(res.status).toBe(403);
      const body = (await res.json()) as IdentityBody;
      expect(body.error?.reason).toBe("device_required");
      expect(body).not.toHaveProperty("identite");
    });
  });

  it("answers GET only", async () => {
    await withPairedDevice(EMPLOYEE_DEVICE, async (deviceToken) => {
      const res = await fetch(`http://127.0.0.1:${port}/opsys/identite`, {
        method: "POST",
        headers: { authorization: `Bearer ${deviceToken}` },
      });

      expect(res.status).toBe(405);
      expect(res.headers.get("allow")).toBe("GET");
    });
  });

  it("leaves every other path to the other routes", async () => {
    const res = await fetch(`http://127.0.0.1:${port}/opsys/autre`, { method: "GET" });

    expect(res.status).toBe(404);
  });
});
