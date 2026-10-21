// DEVICE-only M6 photo read. Verify the bounded image before committing client headers;
// SQL authority is rechecked through the private bridge before each client fragment.
import { createHash } from "node:crypto";
import { request as requestHttp, type IncomingMessage, type ServerResponse } from "node:http";
import { request as requestHttps } from "node:https";
import {
  authorizePairedDeviceGatewayHttpRequestOrReply,
  getBearerToken,
} from "./http-auth-utils.js";
import {
  readJsonBodyOrError,
  sendJson,
  sendMethodNotAllowed,
  watchClientDisconnect,
} from "./http-common.js";
import type { GatewayHttpRequestAuthOptions } from "./http-request-authority.js";
import {
  authorizeOpsysDeviceToolFresh,
  type OpsysDeviceAuthorization,
} from "./opsys-device-roles.js";

export const OPSYS_PREUVES_PHOTO_PATH = "/opsys/m6/preuves/photo";
const TOOL = "m6_lire_preuves_pertes_wct_appareil";
const MAX_PHOTO = 10 * 1024 * 1024;
const FRAGMENT = 64 * 1024;
const DEADLINE_MS = 120_000;
const SHA = /^[a-f0-9]{64}$/;
const REFUSALS = new Set([
  "photo_autorite_absente",
  "photo_corps_invalide",
  "photo_corps_trop_volumineux",
  "photo_service_indisponible",
  "photo_indisponible",
  "photo_autorite_retiree",
  "photo_delai_depasse",
]);

type Selection = {
  wct_id: string;
  preuve: { index: number; hash_maillon: string };
  position_photo: number;
};
type Attribution = Extract<OpsysDeviceAuthorization, { ok: true }>;
type PrivateResponse = { status: number; headers: Headers; body: IncomingMessage };
type Metadata = { hash: string; mime: string; size: number };
class PhotoRefusal extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}
function closed(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((k) => Object.hasOwn(value, k))
  );
}
function text(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    [...value].length <= 256 &&
    ![...value].some((c) => {
      const cp = c.codePointAt(0);
      return cp === undefined || cp < 32 || (cp >= 0xd800 && cp <= 0xdfff);
    })
  );
}
function selection(value: unknown): Selection | null {
  if (
    !closed(value, ["wct_id", "preuve", "position_photo"]) ||
    !text(value.wct_id) ||
    !Number.isInteger(value.position_photo) ||
    typeof value.position_photo !== "number" ||
    value.position_photo < 0 ||
    value.position_photo > 2 ||
    !closed(value.preuve, ["index", "hash_maillon"]) ||
    typeof value.preuve.index !== "number" ||
    !Number.isInteger(value.preuve.index) ||
    value.preuve.index < 0 ||
    value.preuve.index > 10000 ||
    typeof value.preuve.hash_maillon !== "string" ||
    !SHA.test(value.preuve.hash_maillon)
  ) {
    return null;
  }
  return {
    wct_id: value.wct_id,
    preuve: { index: value.preuve.index, hash_maillon: value.preuve.hash_maillon },
    position_photo: value.position_photo,
  };
}
function bridgeConfiguration(
  publicToken: string | undefined,
  auth: GatewayHttpRequestAuthOptions["auth"],
): { url: URL; token: string } | null {
  const token = process.env.OPSYS_M6_PREUVES_BRIDGE_JETON;
  if (
    !token ||
    /\s/u.test(token) ||
    [...token].some((c) => {
      const cp = c.codePointAt(0);
      return cp === undefined || cp < 32 || cp === 127;
    }) ||
    [
      publicToken,
      auth.token,
      auth.password,
      process.env.OPSYS_MCP_JETON,
      process.env.OPSYS_CONTEXT_MCP_JETON,
      process.env.OPSYS_CRON_OPERATEUR_JETON,
    ].includes(token)
  ) {
    return null;
  }
  try {
    const url = new URL(process.env.OPSYS_M6_PREUVES_BRIDGE_URL ?? "");
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.pathname !== "/mcp/fichiers/m6-preuves"
    ) {
      return null;
    }
    return { url, token };
  } catch {
    return null;
  }
}
function unchanged(current: OpsysDeviceAuthorization, admitted: Attribution): boolean {
  return (
    current.ok &&
    current.personne === admitted.personne &&
    current.role === admitted.role &&
    current.serveur === admitted.serveur
  );
}
function metadata(response: PrivateResponse): Metadata {
  const mime = response.headers.get("content-type");
  const length = response.headers.get("content-length") ?? "";
  const hash = response.headers.get("x-opsys-sha256") ?? "";
  const encoding = response.headers.get("content-encoding");
  if (
    (mime !== "image/jpeg" && mime !== "image/png") ||
    !/^[1-9]\d{0,7}$/.test(length) ||
    Number(length) > MAX_PHOTO ||
    !SHA.test(hash) ||
    response.headers.get("etag") !== `"${hash}"` ||
    (encoding !== null && encoding !== "identity")
  ) {
    throw new PhotoRefusal(502, "photo_reponse_invalide");
  }
  return { hash, mime, size: Number(length) };
}
async function readBounded(
  response: PrivateResponse,
  maximum: number,
  guard: () => Promise<void>,
  exact?: number,
): Promise<Buffer> {
  if (
    !response.body ||
    (response.headers.get("content-encoding") &&
      response.headers.get("content-encoding") !== "identity")
  ) {
    throw new PhotoRefusal(502, "photo_reponse_invalide");
  }
  const reader = response.body[Symbol.asyncIterator]();
  // Image allocation is permitted only after its mandatory Content-Length was validated.
  const buffer = Buffer.alloc(exact ?? maximum);
  let offset = 0;
  try {
    while (true) {
      const item = await reader.next();
      await guard();
      if (item.done) {
        break;
      }
      if (item.value.byteLength > buffer.length - offset) {
        throw new PhotoRefusal(502, "photo_reponse_invalide");
      }
      buffer.set(item.value, offset);
      offset += item.value.byteLength;
    }
    if (exact !== undefined && offset !== exact) {
      throw new PhotoRefusal(502, "photo_reponse_invalide");
    }
    return buffer.subarray(0, offset);
  } finally {
    response.body.destroy();
  }
}
async function privateRefusal(
  response: PrivateResponse,
  guard: () => Promise<void>,
): Promise<never> {
  const bytes = await readBounded(response, 4096, guard);
  let body: unknown;
  try {
    body = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new PhotoRefusal(502, "photo_reponse_invalide");
  }
  if (
    ![400, 401, 403, 409, 413, 503, 504].includes(response.status) ||
    !closed(body, ["ok", "erreur"]) ||
    body.ok !== false ||
    typeof body.erreur !== "string" ||
    !REFUSALS.has(body.erreur)
  ) {
    throw new PhotoRefusal(502, "photo_reponse_invalide");
  }
  throw new PhotoRefusal(response.status, body.erreur);
}
function validRevalidation(body: unknown, image: Metadata, identity: Attribution): boolean {
  if (
    !closed(body, ["ok", "resultat"]) ||
    body.ok !== true ||
    !closed(body.resultat, [
      "accepte",
      "reference",
      "empreinte_sha256",
      "type_mime",
      "taille_octets",
      "autorite",
    ])
  ) {
    return false;
  }
  const r = body.resultat;
  return (
    r.accepte === true &&
    r.reference === `fichier:sha256:${image.hash}` &&
    r.empreinte_sha256 === image.hash &&
    r.type_mime === image.mime &&
    r.taille_octets === image.size &&
    closed(r.autorite, ["personne", "role", "source"]) &&
    r.autorite.personne === identity.personne &&
    r.autorite.role === identity.role &&
    r.autorite.source === "appareil"
  );
}

export async function handleOpsysPreuvesPhotoHttpRequest(
  req: IncomingMessage,
  res: ServerResponse,
  opts: GatewayHttpRequestAuthOptions,
): Promise<boolean> {
  let url: URL;
  try {
    url = new URL(req.url ?? "/", "http://localhost");
  } catch {
    return false;
  }
  if (url.pathname !== OPSYS_PREUVES_PHOTO_PATH) {
    return false;
  }
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.method !== "POST") {
    sendMethodNotAllowed(res, "POST");
    return true;
  }
  if (url.search) {
    sendJson(res, 400, { ok: false, erreur: "photo_corps_invalide" });
    return true;
  }
  const raw = req.rawHeaders
    .filter((_, index) => index % 2 === 0)
    .filter((k) => k.toLowerCase() === "authorization");
  if (
    raw.length > 1 ||
    typeof req.headers.authorization !== "string" ||
    !/^Bearer [^\s,]+$/i.test(req.headers.authorization)
  ) {
    sendJson(res, 401, { ok: false, erreur: "photo_autorite_absente" });
    return true;
  }
  const requestAuth = await authorizePairedDeviceGatewayHttpRequestOrReply({ ...opts, req, res });
  if (!requestAuth || !requestAuth.deviceId) {
    return true;
  }
  const deviceId = requestAuth.deviceId;
  const identity = authorizeOpsysDeviceToolFresh(deviceId, TOOL);
  if (!identity.ok || identity.role !== "admin" || !text(identity.personne) || !text(deviceId)) {
    sendJson(res, 403, { ok: false, erreur: "photo_autorite_retiree" });
    return true;
  }
  const configured = bridgeConfiguration(getBearerToken(req), opts.auth);
  if (!configured) {
    sendJson(res, 503, { ok: false, erreur: "photo_service_indisponible" });
    return true;
  }
  const abort = new AbortController();
  const stopDisconnect = watchClientDisconnect(req, res, abort);
  const deadline = setTimeout(
    () => abort.abort(new PhotoRefusal(504, "photo_delai_depasse")),
    DEADLINE_MS,
  );
  const assertLocal = () => {
    if (abort.signal.aborted) {
      throw abort.signal.reason;
    }
    requestAuth.assertCurrent();
    if (!unchanged(authorizeOpsysDeviceToolFresh(deviceId, TOOL), identity)) {
      throw new PhotoRefusal(403, "photo_autorite_retiree");
    }
    const current = bridgeConfiguration(getBearerToken(req), opts.getResolvedAuth?.() ?? opts.auth);
    if (
      !current ||
      current.url.href !== configured.url.href ||
      current.token !== configured.token
    ) {
      throw new PhotoRefusal(503, "photo_service_indisponible");
    }
  };
  const guard = async () => {
    await requestAuth.revalidate();
    assertLocal();
  };
  try {
    const body = selection(await readJsonBodyOrError(req, res, 4096));
    if (res.writableEnded || res.destroyed) {
      return true;
    }
    await guard();
    if (!body) {
      throw new PhotoRefusal(400, "photo_corps_invalide");
    }
    const privateBody = JSON.stringify({
      selection: body,
      identite: { personne: identity.personne, role: identity.role },
      appareil_id: deviceId,
    });
    const fetchPrivate = async (target: URL) => {
      // Native HTTP returns raw bytes: no automatic decompression or redirect following.
      const response = await new Promise<PrivateResponse>((resolve, reject) => {
        const upstream = (target.protocol === "https:" ? requestHttps : requestHttp)(
          target,
          {
            method: "POST",
            signal: abort.signal,
            headers: {
              authorization: `Bearer ${configured.token}`,
              "content-type": "application/json",
              "content-length": Buffer.byteLength(privateBody),
              "accept-encoding": "identity",
            },
          },
          (incoming) => {
            const headers = new Headers();
            for (const [key, value] of Object.entries(incoming.headers)) {
              if (value !== undefined) {
                headers.set(key, Array.isArray(value) ? value.join(",") : value);
              }
            }
            resolve({ status: incoming.statusCode ?? 502, headers, body: incoming });
          },
        );
        upstream.on("error", reject);
        upstream.end(privateBody);
      });
      await guard();
      if (response.status !== 200) {
        await privateRefusal(response, guard);
      }
      return response;
    };
    const response = await fetchPrivate(configured.url);
    const image = metadata(response);
    const bytes = await readBounded(response, MAX_PHOTO, guard, image.size);
    if (
      createHash("sha256").update(bytes).digest("hex") !== image.hash ||
      !(image.mime === "image/png"
        ? bytes.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex"))
        : bytes.subarray(0, 3).equals(Buffer.from("ffd8ff", "hex")))
    ) {
      throw new PhotoRefusal(502, "photo_reponse_invalide");
    }
    const revalidate = async () => {
      await guard();
      const fresh = await fetchPrivate(new URL(`${configured.url.href}/revalider`));
      const json = await readBounded(fresh, 4096, guard);
      let value: unknown;
      try {
        value = JSON.parse(json.toString("utf8"));
      } catch {
        throw new PhotoRefusal(502, "photo_reponse_invalide");
      }
      if (!validRevalidation(value, image, identity)) {
        throw new PhotoRefusal(403, "photo_autorite_retiree");
      }
      await guard();
    };
    for (let offset = 0; offset < bytes.length; offset += FRAGMENT) {
      await revalidate();
      assertLocal();
      if (offset === 0) {
        res.statusCode = 200;
        res.setHeader("Content-Type", image.mime);
        res.setHeader("Content-Length", image.size);
        res.setHeader("X-Opsys-Sha256", image.hash);
        res.setHeader("ETag", `"${image.hash}"`);
      }
      // No asynchronous work between the last guard and this privileged byte write.
      if (!res.write(bytes.subarray(offset, offset + FRAGMENT))) {
        await new Promise<void>((resolve, reject) => {
          const cleanup = () => {
            res.off("drain", drain);
            abort.signal.removeEventListener("abort", cancelled);
          };
          const drain = () => {
            cleanup();
            resolve();
          };
          const cancelled = () => {
            cleanup();
            reject(abort.signal.reason);
          };
          res.once("drain", drain);
          abort.signal.addEventListener("abort", cancelled, { once: true });
          if (abort.signal.aborted) {
            cancelled();
          }
        });
        await guard();
      }
    }
    await revalidate();
    assertLocal();
    res.end();
  } catch (error) {
    abort.abort(error);
    if (res.headersSent) {
      res.destroy();
    } else if (!res.destroyed && !res.writableEnded) {
      const reason = abort.signal.reason;
      const failure =
        reason instanceof PhotoRefusal
          ? reason
          : error instanceof PhotoRefusal
            ? error
            : new PhotoRefusal(502, "photo_service_indisponible");
      sendJson(res, failure.status, { ok: false, erreur: failure.code });
    }
  } finally {
    clearTimeout(deadline);
    stopDisconnect();
    abort.abort();
  }
  return true;
}
