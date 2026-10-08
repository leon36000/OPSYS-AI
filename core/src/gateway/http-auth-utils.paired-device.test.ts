import { expect, it, vi } from "vitest";
import { createDeferred } from "../../test/helpers/promise.js";
import { approveDevicePairing } from "../infra/device-pairing-approval.js";
import { ensureDeviceToken, revokeDeviceToken } from "../infra/device-pairing-tokens.js";
import { requestDevicePairing, withPairedDeviceRecords } from "../infra/device-pairing.js";
import { readJsonBodyWithLimit } from "../infra/http-body.js";
import { createSubsystemLogger } from "../logging/subsystem.js";
import { getPluginRuntimeGatewayRequestScope } from "../plugins/runtime/gateway-request-scope.js";
import { withOpenClawTestState } from "../test-utils/openclaw-test-state.js";
import { authorizeOperatorScopesForMethod } from "./method-scopes.js";
import {
  AUTH_TOKEN,
  createRequest,
  createResponse,
  dispatchRequest,
  sendRequest,
  withGatewayServer,
} from "./server-http.test-harness.js";
import { createGatewayTestRegistry } from "./server/__tests__/test-utils.js";
import { createGatewayPluginRequestHandler } from "./server/plugins-http.js";
import { resolveSharedGatewaySessionGeneration } from "./server/ws-shared-generation.js";

it.each(["operator.admin", "operator.read"])(
  "createGatewayHttpServer plugin PUT/POST revalidates paired %s authority after reading the body",
  async (scope) => {
    await withOpenClawTestState({ label: "plugin-device-auth" }, async () => {
      const scopes = [scope];
      const requested = await requestDevicePairing({
        deviceId: "browser",
        publicKey: "fixture-key",
        role: "operator",
        scopes,
        clientId: "openclaw-control-ui",
        clientMode: "webchat",
      });
      await approveDevicePairing(requested.request.requestId, { callerScopes: scopes });
      const token = await ensureDeviceToken({
        deviceId: "browser",
        role: "operator",
        scopes,
        issuer: {
          kind: "shared-gateway-auth",
          generation: resolveSharedGatewaySessionGeneration(AUTH_TOKEN, [])!,
        },
      });
      expect(token).not.toBeNull();
      const bodyStarted = createDeferred();
      let effects = 0;
      const handlePluginRequest = createGatewayPluginRequestHandler({
        registry: createGatewayTestRegistry({
          httpRoutes: [
            {
              pluginId: "profile",
              source: "fixture",
              path: "/profile",
              match: "exact",
              auth: "gateway",
              gatewayRuntimeScopeSurface: "trusted-operator",
              handler: async (req, res) => {
                const runtime = getPluginRuntimeGatewayRequestScope();
                const granted = runtime?.client?.connect.scopes ?? [];
                if (req.headers["content-type"] === "application/json") {
                  const body = readJsonBodyWithLimit(req, { maxBytes: 1024 });
                  bodyStarted.resolve();
                  expect((await body).ok).toBe(true);
                }
                await runtime?.revalidate?.();
                const allowed = authorizeOperatorScopesForMethod("set-heartbeats", granted).allowed;
                if (allowed) {
                  effects += 1;
                }
                res.statusCode = allowed ? 200 : 403;
                res.end(JSON.stringify({ scopes: granted }));
                return true;
              },
            },
          ],
        }),
        log: createSubsystemLogger("test/plugin-device-auth"),
      });
      await withGatewayServer({
        prefix: "plugin-device-auth-",
        resolvedAuth: AUTH_TOKEN,
        overrides: {
          handlePluginRequest,
          shouldEnforcePluginGatewayAuth: (path) => path.pathname === "/profile",
        },
        run: async (server) => {
          for (const method of ["PUT", "POST"]) {
            const response = await sendRequest(server, {
              path: "/profile",
              method,
              authorization: `Bearer ${token!.token}`,
              headers: { "x-openclaw-scopes": "operator.admin" },
            });
            expect(response.res.statusCode).toBe(scope === "operator.admin" ? 200 : 403);
            expect(JSON.parse(response.getBody())).toEqual({
              scopes:
                scope === "operator.admin"
                  ? ["operator.admin", "operator.read", "operator.write"]
                  : ["operator.read"],
            });
          }
          const pending = createRequest({
            path: "/profile",
            method: "PUT",
            authorization: `Bearer ${token!.token}`,
            headers: { "content-type": "application/json" },
          });
          const response = createResponse();
          Object.defineProperty(response.res, "writableEnded", {
            get: () => response.res.writableFinished,
          });
          const dispatch = dispatchRequest(server, pending, response.res);
          await bodyStarted.promise;
          const previousEffects = effects;
          await revokeDeviceToken({ deviceId: "browser", role: "operator" });
          pending.emit("data", Buffer.from("{}"));
          pending.emit("end");
          await dispatch;
          expect(response.res.statusCode).toBe(401);
          expect(JSON.parse(response.getBody())).toEqual({
            error: { message: "Unauthorized", type: "unauthorized" },
          });
          expect(effects).toBe(previousEffects);
          for (const credential of [token!.token, "wrong-token"]) {
            const rejected = await sendRequest(server, {
              path: "/profile",
              method: "PUT",
              authorization: `Bearer ${credential}`,
            });
            expect(rejected.res.statusCode).toBe(401);
            expect(JSON.parse(rejected.getBody())).toEqual({
              error: { message: "Unauthorized", type: "unauthorized" },
            });
          }
        },
      });
    });
  },
);

it("paired byte authority rejects a revoked token on every revalidation", async () => {
  await withOpenClawTestState({ label: "opsys-photo-byte-auth" }, async () => {
    const scopes = ["operator.read"];
    const requested = await requestDevicePairing({
      deviceId: "photo-device",
      publicKey: "fictif-key",
      role: "operator",
      scopes,
    });
    await approveDevicePairing(requested.request.requestId, { callerScopes: scopes });
    const token = await ensureDeviceToken({
      deviceId: "photo-device",
      role: "operator",
      scopes,
      issuer: {
        kind: "shared-gateway-auth",
        generation: resolveSharedGatewaySessionGeneration(AUTH_TOKEN, [])!,
      },
    });
    expect(token).not.toBeNull();
    const helpers = await import("./http-auth-utils.js");
    const authorize = helpers.authorizePairedDeviceGatewayHttpRequestOrReply;
    const req = createRequest({
      path: "/opsys/m6/preuves/photo",
      method: "POST",
      authorization: `Bearer ${token!.token}`,
    });
    const response = createResponse();
    const admitted = await authorize({ req, res: response.res, auth: AUTH_TOKEN });
    expect(admitted?.deviceId).toBe("photo-device");
    if (!admitted) {
      throw new Error("Missing device authority");
    }
    await admitted.revalidate();
    await revokeDeviceToken({ deviceId: "photo-device", role: "operator" });
    await expect(admitted.revalidate()).rejects.toThrow("Unauthorized");
    expect(response.res.statusCode).toBe(401);
  });
});

it("paired byte authority never adopts another device which now holds the same bearer", async () => {
  await withOpenClawTestState({ label: "opsys-photo-device-binding" }, async () => {
    const scopes = ["operator.read"];
    const pair = await requestDevicePairing({
      deviceId: "before",
      publicKey: "fictif-key",
      role: "operator",
      scopes,
    });
    await approveDevicePairing(pair.request.requestId, { callerScopes: scopes });
    const token = await ensureDeviceToken({
      deviceId: "before",
      role: "operator",
      scopes,
      issuer: {
        kind: "shared-gateway-auth",
        generation: resolveSharedGatewaySessionGeneration(AUTH_TOKEN, [])!,
      },
    });
    if (!token) {
      throw new Error("Missing token");
    }
    const helpers = await import("./http-auth-utils.js");
    const req = createRequest({
      path: "/opsys/m6/preuves/photo",
      method: "POST",
      authorization: `Bearer ${token.token}`,
    });
    const { res } = createResponse();
    const admitted = await helpers.authorizePairedDeviceGatewayHttpRequestOrReply({
      req,
      res,
      auth: AUTH_TOKEN,
    });
    if (!admitted) {
      throw new Error("Missing admitted authority");
    }
    expect(admitted.deviceId).toBe("before");
    // A real persisted migration/tampering fixture, not a mocked verifier result.
    await withPairedDeviceRecords(undefined, (records) => {
      const before = records.before;
      if (!before) {
        throw new Error("Missing paired record");
      }
      records.after = { ...before, deviceId: "after" };
      delete records.before;
      return { value: undefined, persist: true };
    });
    const current = await helpers.checkGatewayHttpRequestAuth({ req, auth: AUTH_TOKEN }, true);
    expect(current.ok).toBe(true);
    if (!current.ok) {
      throw new Error("The persisted bearer no longer authenticates");
    }
    expect(current.requestAuth.deviceId).toBe("after");
    await expect(admitted.revalidate()).rejects.toThrow("Unauthorized");
    expect(res.statusCode).toBe(401);
  });
});

it("paired byte authority never calls response callbacks after image headers", async () => {
  await withOpenClawTestState({ label: "opsys-photo-post-header" }, async () => {
    const scopes = ["operator.read"];
    const pair = await requestDevicePairing({
      deviceId: "photo",
      publicKey: "fictif-key",
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
      throw new Error("Missing token");
    }
    const helpers = await import("./http-auth-utils.js");
    let cfg = {};
    const req = createRequest({
      path: "/opsys/m6/preuves/photo",
      method: "POST",
      authorization: `Bearer ${token.token}`,
    });
    const response = createResponse();
    const admitted = await helpers.authorizePairedDeviceGatewayHttpRequestOrReply({
      req,
      res: response.res,
      auth: AUTH_TOKEN,
      cfg,
      getRuntimeConfig: () => cfg,
    });
    if (!admitted) {
      throw new Error("Missing authority");
    }
    Object.defineProperty(response.res, "headersSent", { value: true });
    const destroy = vi.fn();
    Object.defineProperty(response.res, "destroy", { value: destroy });
    cfg = { gateway: { trustedProxies: ["127.0.0.1"] } };
    await expect(admitted.revalidate()).rejects.toThrow("Unauthorized");
    // Response observer only; paired credentials and policy revalidation above are real.
    expect(response.end).not.toHaveBeenCalled();
    expect(response.setHeader).not.toHaveBeenCalled();
    expect(response.getBody()).toBe("");
    expect(destroy).toHaveBeenCalledOnce();
  });
});
