import { createHash } from "node:crypto";
import { stableStringify } from "@openclaw/normalization-core/stable-stringify";
import { describe, expect, it, vi } from "vitest";
import {
  OpsysCronPrivateClient,
  OpsysCronPrivateClientError,
  type CronDeclaration,
  type PrepareCronRetirement,
} from "./opsys-cron-private-client.js";

const TOKEN = "private-operator-token-that-is-not-the-mcp-bearer";
const INTENT = "a".repeat(64);
const PROFILE = "agent-a";
const DECLARATION: CronDeclaration = {
  name: "OPSYS profil agent-a",
  declarationKey: `opsys-profile:${INTENT}`,
  agentId: "opsys-agent-agent-a",
  sessionTarget: "isolated",
  wakeMode: "now",
  schedule: { kind: "cron", expr: "0 7 * * 1-5", tz: "America/Toronto" },
  payload: {
    kind: "agentTurn",
    message: "Exécute le mandat interne canonique du profil agent-a, révision 4.",
    timeoutSeconds: 120,
    toolsAllow: ["opsys_m3__m3_lire_devis"],
  },
  delivery: { mode: "none" },
};
const STATUS = {
  intention: INTENT,
  epoch: 1,
  lease_epoch: 1,
  etat: "preparation",
  job_id: null,
  config_revision: null,
  execute: false,
};

function response(result: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify({ ok: true, resultat: result }), {
    status: 200,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
    ...init,
  });
}

function clientFor(responder: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const fetchImpl = vi.fn<typeof fetch>(
    async (input, init) => await responder(String(input), init ?? {}),
  );
  return {
    client: new OpsysCronPrivateClient({
      healthUrl: "http://127.0.0.1:8765/sante",
      operatorToken: TOKEN,
      publicMcpToken: "public-mcp-token-that-is-not-the-operator-secret",
      fetchImpl,
    }),
    fetchImpl,
  };
}

describe("OpsysCronPrivateClient", () => {
  it("fails closed on non-loopback URLs and missing or colliding operator secrets", () => {
    const base = {
      operatorToken: TOKEN,
      publicMcpToken: "public-mcp-token-that-is-not-the-operator-secret",
    };
    for (const healthUrl of [
      "http://example.test:8765/sante",
      "http://127.0.0.1:8765/sante?x=1",
      "http://127.0.0.1:8765/sante#fragment",
      "http://user@127.0.0.1:8765/sante",
      "https://127.0.0.1:8765/sante",
    ]) {
      expect(() => new OpsysCronPrivateClient({ ...base, healthUrl })).toThrow(
        OpsysCronPrivateClientError,
      );
    }
    expect(
      () =>
        new OpsysCronPrivateClient({
          ...base,
          healthUrl: "http://localhost:8765/sante",
          publicMcpToken: TOKEN,
        }),
    ).toThrow(OpsysCronPrivateClientError);
    expect(
      () =>
        new OpsysCronPrivateClient({
          ...base,
          healthUrl: "http://[::1]:8765/sante",
          operatorToken: "short",
        }),
    ).toThrow(OpsysCronPrivateClientError);
    expect(
      () => new OpsysCronPrivateClient({ ...base, healthUrl: "http://[::1]:8765/sante" }),
    ).not.toThrow();
  });

  it("lists only the exact owner metadata and carries the private bearer over no-store POST", async () => {
    const { client, fetchImpl } = clientFor((url, init) => {
      expect(url).toBe(`http://127.0.0.1:8765/cron-operateur/v1/${PROFILE}/lire`);
      expect(init.method).toBe("POST");
      expect(init.redirect).toBe("error");
      expect(init.cache).toBe("no-store");
      expect(new Headers(init.headers).get("authorization")).toBe(`Bearer ${TOKEN}`);
      expect(init.body).toBe("{}");
      return response({
        total: 1,
        retournes: 1,
        omis: 0,
        items: [
          {
            intention_id: INTENT,
            etat: "a_declarer",
            revision_profil: 4,
            fuseau: "America/Toronto",
          },
        ],
      });
    });
    await expect(client.list(PROFILE)).resolves.toEqual({
      total: 1,
      retournes: 1,
      omis: 0,
      items: [
        { intention_id: INTENT, etat: "a_declarer", revision_profil: 4, fuseau: "America/Toronto" },
      ],
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("accepts all sixteen owner intentions within the bounded response", async () => {
    const items = Array.from({ length: 16 }, (_, index) => ({
      intention_id: index.toString(16).padStart(64, "0"),
      etat: "a_declarer",
      revision_profil: 4,
      fuseau: "é".repeat(32),
    }));
    const body = { total: 16, retournes: 16, omis: 0, items };
    expect(Buffer.byteLength(JSON.stringify({ ok: true, resultat: body }), "utf8")).toBeLessThan(
      20 * 1024,
    );
    const { client } = clientFor(() => response(body));
    await expect(client.list(PROFILE)).resolves.toEqual(body);
  });

  it("refuses overflow, incomplete lists, duplicate identities and oversized UTF-8 metadata", async () => {
    const item = { intention_id: INTENT, etat: "a_declarer", revision_profil: 4, fuseau: "UTC" };
    for (const body of [
      { total: 17, retournes: 17, omis: 0, items: Array.from({ length: 17 }, () => item) },
      { total: 16, retournes: 10, omis: 6, items: Array.from({ length: 10 }, () => item) },
      { total: 2, retournes: 2, omis: 0, items: [item, item] },
      { total: 1, retournes: 1, omis: 0, items: [{ ...item, fuseau: "é".repeat(33) }] },
    ]) {
      const { client } = clientFor(() => response(body));
      await expect(client.list(PROFILE)).rejects.toMatchObject({ kind: "unavailable" });
    }
  });

  it("validates all audiences uniformly and refuses every pair collision", () => {
    const base = {
      healthUrl: "http://127.0.0.1:8765/sante",
      operatorToken: "o".repeat(24),
      publicMcpToken: "p".repeat(24),
      contextToken: "c".repeat(24),
    };
    for (const audience of ["operatorToken", "publicMcpToken", "contextToken"] as const) {
      for (const invalid of [
        null,
        42,
        {},
        "",
        "x".repeat(23),
        "x".repeat(4097),
        "x".repeat(24) + " ",
        "x".repeat(24) + "\n",
        "x".repeat(24) + "\u0000",
        "x".repeat(24) + "\u00a0",
      ]) {
        const options = { ...base };
        Object.defineProperty(options, audience, { value: invalid });
        expect(() => new OpsysCronPrivateClient(options)).toThrow(OpsysCronPrivateClientError);
      }
    }
    for (const options of [
      { ...base, operatorToken: base.publicMcpToken },
      { ...base, contextToken: base.operatorToken },
      { ...base, contextToken: base.publicMcpToken },
    ]) {
      expect(() => new OpsysCronPrivateClient(options)).toThrow(OpsysCronPrivateClientError);
    }
    expect(() => new OpsysCronPrivateClient({ ...base, contextToken: undefined })).not.toThrow();
    expect(
      () =>
        new OpsysCronPrivateClient({
          ...base,
          operatorToken: "o".repeat(4096),
          publicMcpToken: "p".repeat(4096),
          contextToken: "c".repeat(4096),
        }),
    ).not.toThrow();
  });

  it("closes outbound and configuration property-getter diagnostics", async () => {
    const options = {
      healthUrl: "http://127.0.0.1:8765/sante",
      operatorToken: TOKEN,
      publicMcpToken: "public-mcp-token-that-is-not-the-operator-secret",
    };
    Object.defineProperty(options, "operatorToken", {
      get: () => {
        throw new Error(TOKEN);
      },
    });
    let constructorError: unknown;
    try {
      new OpsysCronPrivateClient(options);
    } catch (error) {
      constructorError = error;
    }
    expect(constructorError).toMatchObject({
      kind: "configuration",
      message: expect.not.stringContaining(TOKEN),
    });
    const { client, fetchImpl } = clientFor(() => response({}));
    const input = {
      capabilityFingerprint: "c".repeat(64),
      declaration: DECLARATION,
      expectedEpoch: 0,
      expectedNativeRevision: null,
      leaseSeconds: 30,
    };
    Object.defineProperty(input, "capabilityFingerprint", {
      get: () => {
        throw new Error(TOKEN);
      },
    });
    await expect(client.prepare(PROFILE, INTENT, input)).rejects.toMatchObject({
      kind: "configuration",
      message: expect.not.stringContaining(TOKEN),
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("projects either a validated native cron.add or the explicit removal result", async () => {
    const native = { method: "cron.add", params: DECLARATION };
    const first = clientFor(() =>
      response({ intention: INTENT, etat: "a_declarer", execute: false, native }),
    );
    await expect(first.client.project(PROFILE, INTENT)).resolves.toMatchObject({ native });
    const removed = clientFor(() =>
      response({
        intention: INTENT,
        etat: "a_retirer",
        execute: false,
        declaration_key: `opsys-profile:${INTENT}`,
        reconciliation: "rechercher_id_natif_puis_retirer",
        native: null,
      }),
    );
    await expect(removed.client.project(PROFILE, INTENT)).resolves.toMatchObject({
      etat: "a_retirer",
      native: null,
    });
    const falseKey = clientFor(() =>
      response({
        intention: INTENT,
        etat: "a_retirer",
        execute: false,
        declaration_key: `opsys-profile:${PROFILE}`,
        reconciliation: "rechercher_id_natif_puis_retirer",
        native: null,
      }),
    );
    await expect(falseKey.client.project(PROFILE, INTENT)).rejects.toMatchObject({
      kind: "unavailable",
    });
    await expect(first.client.project(PROFILE, "../other-profile")).rejects.toMatchObject({
      kind: "configuration",
    });
  });

  it("prepares with a fingerprint and rejects an epoch or canonical declaration mismatch", async () => {
    const { client, fetchImpl } = clientFor((_url, init) => {
      expect(JSON.parse(String(init.body))).toEqual({
        intention_id: INTENT,
        empreinte_capacite: "c".repeat(64),
        declaration: DECLARATION,
        epoch_attendue: 0,
        revision_native_attendue: null,
        lease_secondes: 30,
      });
      return response({
        ...STATUS,
        lease_until: "2026-10-03T12:00:30+00:00",
        revision_native_attendue: null,
        native: { method: "cron.add", params: { ...DECLARATION } },
      });
    });
    const prepared = await client.prepare(PROFILE, INTENT, {
      capabilityFingerprint: "c".repeat(64),
      declaration: DECLARATION,
      expectedEpoch: 0,
      expectedNativeRevision: null,
      leaseSeconds: 30,
    });
    expect(prepared.epoch).toBe(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const bad = clientFor(() =>
      response({
        ...STATUS,
        epoch: 2,
        lease_until: "2026-10-03T12:00:30+00:00",
        revision_native_attendue: null,
        native: { method: "cron.add", params: DECLARATION },
      }),
    );
    await expect(
      bad.client.prepare(PROFILE, INTENT, {
        capabilityFingerprint: "c".repeat(64),
        declaration: DECLARATION,
        expectedEpoch: 0,
        expectedNativeRevision: null,
        leaseSeconds: 30,
      }),
    ).rejects.toMatchObject({ kind: "unavailable" });
  });

  it("acknowledges, validates, and renews only exact owner statuses", async () => {
    const jobId = "job-123";
    const configRevision = "sha256:" + "A".repeat(43);
    const { client } = clientFor((_url, init) => {
      const body = JSON.parse(String(init.body)) as { intention_id: string };
      if (body.intention_id === INTENT) {
        const operation = String(_url).split("/").at(-1);
        if (operation === "accuser")
          return response({
            ...STATUS,
            etat: "remise",
            job_id: jobId,
            config_revision: configRevision,
          });
        if (operation === "valider") return response({ valide: true });
        if (operation === "renouveler")
          return response({ ...STATUS, lease_epoch: 2, lease_until: "2026-10-03T12:00:30+00:00" });
      }
      return response({});
    });
    const grant = {
      intentionId: INTENT,
      capability: "d".repeat(64),
      epoch: 1,
      jobId,
      configRevision,
      declaration: DECLARATION,
    };
    await expect(client.acknowledge(PROFILE, { ...grant, leaseEpoch: 1 })).resolves.toMatchObject({
      etat: "remise",
      job_id: jobId,
    });
    await expect(client.validate(PROFILE, grant)).resolves.toBeUndefined();
    await expect(
      client.renew(PROFILE, { ...grant, leaseEpoch: 1, leaseSeconds: 30 }),
    ).resolves.toMatchObject({ lease_epoch: 2 });
  });

  it("hides remote error bodies and rejects duplicate JSON fields and unexpected response fields", async () => {
    const refusal = clientFor(() => new Response(TOKEN, { status: 409 }));
    await expect(refusal.client.list(PROFILE)).rejects.toMatchObject({
      kind: "refused",
      message: expect.not.stringContaining(TOKEN),
    });
    const duplicate = clientFor(
      () =>
        new Response('{"ok":true,"ok":false,"resultat":{}}', {
          status: 200,
          headers: { "content-type": "application/json", "cache-control": "no-store" },
        }),
    );
    await expect(duplicate.client.list(PROFILE)).rejects.toMatchObject({ kind: "unavailable" });
    const extra = clientFor(() =>
      response({ total: 0, retournes: 0, omis: 0, items: [], secret: TOKEN }),
    );
    await expect(extra.client.list(PROFILE)).rejects.toMatchObject({ kind: "unavailable" });
  });

  it("turns transport failures into a generic error without surfacing the bearer", async () => {
    const { client } = clientFor(() => {
      throw new Error(`connect failed: ${TOKEN}`);
    });
    await expect(client.list(PROFILE)).rejects.toMatchObject({
      name: "OpsysCronPrivateClientError",
      kind: "unavailable",
      message: expect.not.stringContaining(TOKEN),
    });
  });

  it("refuses throwing getters, root toJSON arrays, cycles and BigInt without leaking or fetching", async () => {
    const getter = { ...DECLARATION };
    Object.defineProperty(getter, "secretGetter", {
      enumerable: true,
      get: () => {
        throw new Error(TOKEN);
      },
    });
    const rootArray = { ...DECLARATION };
    Object.defineProperty(rootArray, "toJSON", { value: () => [TOKEN] });
    const throwingJson = { ...DECLARATION };
    Object.defineProperty(throwingJson, "toJSON", {
      value: () => {
        throw new Error(TOKEN);
      },
    });
    const cycle: Record<string, unknown> = { ...DECLARATION };
    cycle.cycle = cycle;
    for (const raw of [getter, rootArray, throwingJson, cycle, { ...DECLARATION, bigint: 1n }]) {
      const { client, fetchImpl } = clientFor(() => response({}));
      await expect(
        client.prepare(PROFILE, INTENT, {
          capabilityFingerprint: "c".repeat(64),
          declaration: raw as CronDeclaration,
          expectedEpoch: 0,
          expectedNativeRevision: null,
          leaseSeconds: 30,
        }),
      ).rejects.toMatchObject({
        kind: "configuration",
        message: expect.not.stringContaining(TOKEN),
      });
      expect(fetchImpl).not.toHaveBeenCalled();
    }
  });

  it("compares preparation with the JSON wire snapshot despite input mutation during fetch", async () => {
    const declaration: CronDeclaration = {
      ...DECLARATION,
      payload: { kind: "agentTurn", message: "Mandat fictif initial" },
    };
    const { client } = clientFor((_url, init) => {
      const sent = JSON.parse(String(init.body)) as { declaration: CronDeclaration };
      declaration.payload = { kind: "agentTurn", message: "Modification fictive après émission" };
      return response({
        ...STATUS,
        lease_until: "2026-10-03T12:00:30+00:00",
        revision_native_attendue: null,
        native: { method: "cron.add", params: sent.declaration },
      });
    });
    const result = await client.prepare(PROFILE, INTENT, {
      capabilityFingerprint: "c".repeat(64),
      declaration,
      expectedEpoch: 0,
      expectedNativeRevision: null,
      leaseSeconds: 30,
    });
    expect(result.native.params.payload).toEqual({
      kind: "agentTurn",
      message: "Mandat fictif initial",
    });
  });

  it("compares prepare and ACK with every scalar sent before HTTP, despite later mutation and getters", async () => {
    const preparation = {
      capabilityFingerprint: "c".repeat(64),
      declaration: DECLARATION,
      expectedEpoch: 0,
      expectedNativeRevision: null,
      leaseSeconds: 30,
    };
    const first = clientFor((_url, init) => {
      expect(JSON.parse(String(init.body))).toEqual({
        intention_id: INTENT,
        empreinte_capacite: "c".repeat(64),
        declaration: DECLARATION,
        epoch_attendue: 0,
        revision_native_attendue: null,
        lease_secondes: 30,
      });
      preparation.capabilityFingerprint = "e".repeat(64);
      preparation.expectedEpoch = 99;
      preparation.leaseSeconds = 1;
      Object.defineProperty(preparation, "expectedNativeRevision", {
        get: () => {
          throw new Error(TOKEN);
        },
      });
      return response({
        ...STATUS,
        lease_until: "2026-10-03T12:00:30+00:00",
        revision_native_attendue: null,
        native: { method: "cron.add", params: DECLARATION },
      });
    });
    await expect(first.client.prepare(PROFILE, INTENT, preparation)).resolves.toMatchObject({
      epoch: 1,
    });
    const nativeRevision = "sha256:" + "A".repeat(43);
    const grant = {
      intentionId: INTENT,
      capability: "d".repeat(64),
      epoch: 1,
      leaseEpoch: 1,
      jobId: "job-before-http",
      configRevision: nativeRevision,
      declaration: DECLARATION,
    };
    const second = clientFor((_url, init) => {
      expect(JSON.parse(String(init.body))).toEqual({
        intention_id: INTENT,
        capabilite: "d".repeat(64),
        epoch: 1,
        lease_epoch: 1,
        job_id: "job-before-http",
        config_revision: nativeRevision,
        declaration: DECLARATION,
      });
      grant.intentionId = "b".repeat(64);
      grant.capability = "e".repeat(64);
      grant.epoch = 9;
      grant.leaseEpoch = 9;
      grant.configRevision = "sha256:" + "B".repeat(42) + "A";
      Object.defineProperty(grant, "jobId", {
        get: () => {
          throw new Error(TOKEN);
        },
      });
      return response({
        ...STATUS,
        etat: "remise",
        job_id: "job-before-http",
        config_revision: nativeRevision,
      });
    });
    await expect(second.client.acknowledge(PROFILE, grant)).resolves.toMatchObject({
      intention: INTENT,
      epoch: 1,
      lease_epoch: 1,
      job_id: "job-before-http",
      config_revision: nativeRevision,
    });
  });

  it("stops validation before fetch or during an outstanding fetch, without exposing the abort reason", async () => {
    const grant = {
      intentionId: INTENT,
      capability: "d".repeat(64),
      epoch: 1,
      jobId: "job-abort",
      configRevision: "sha256:" + "A".repeat(43),
      declaration: DECLARATION,
    };
    const alreadyAborted = new AbortController();
    alreadyAborted.abort(new Error(TOKEN));
    const first = clientFor(() => response({ valide: true }));
    await expect(
      first.client.validate(PROFILE, grant, { signal: alreadyAborted.signal }),
    ).rejects.toMatchObject({
      kind: "unavailable",
      message: expect.not.stringContaining(TOKEN),
    });
    expect(first.fetchImpl).not.toHaveBeenCalled();
    const controller = new AbortController();
    let requestSignal: AbortSignal | null | undefined;
    let markStarted!: () => void;
    const started = new Promise<void>((resolve) => {
      markStarted = resolve;
    });
    const second = clientFor(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          requestSignal = init.signal;
          requestSignal?.addEventListener("abort", () => reject(requestSignal?.reason), {
            once: true,
          });
          markStarted();
        }),
    );
    const validation = second.client.validate(PROFILE, grant, { signal: controller.signal });
    const refused = expect(validation).rejects.toMatchObject({
      kind: "unavailable",
      message: expect.not.stringContaining(TOKEN),
    });
    await started;
    controller.abort(new Error(TOKEN));
    await refused;
    expect(requestSignal?.aborted).toBe(true);
    expect(second.fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("cancels an outstanding response body when validation is aborted after HTTP headers", async () => {
    const controller = new AbortController();
    let markBodyRead!: () => void;
    const bodyRead = new Promise<void>((resolve) => {
      markBodyRead = resolve;
    });
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>(
      {
        pull() {
          markBodyRead();
        },
        cancel,
      },
      { highWaterMark: 0 },
    );
    const { client, fetchImpl } = clientFor(
      () =>
        new Response(body, {
          status: 200,
          headers: { "content-type": "application/json", "cache-control": "no-store" },
        }),
    );
    const validation = client.validate(
      PROFILE,
      {
        intentionId: INTENT,
        capability: "d".repeat(64),
        epoch: 1,
        jobId: "job-abort",
        configRevision: "sha256:" + "A".repeat(43),
        declaration: DECLARATION,
      },
      { signal: controller.signal },
    );
    const refused = expect(validation).rejects.toMatchObject({
      kind: "unavailable",
      message: expect.not.stringContaining(TOKEN),
    });
    await bodyRead;
    controller.abort(new Error(TOKEN));
    await refused;
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects malformed native SHA and oversized or invalid UTF-8 responses", async () => {
    const { client, fetchImpl } = clientFor(() => response({}));
    await expect(
      client.prepare(PROFILE, INTENT, {
        capabilityFingerprint: "c".repeat(64),
        declaration: DECLARATION,
        expectedEpoch: 0,
        expectedNativeRevision: "sha256:" + "A".repeat(42) + "B",
        leaseSeconds: 30,
      }),
    ).rejects.toMatchObject({ kind: "configuration" });
    expect(fetchImpl).not.toHaveBeenCalled();
    for (const body of ["x".repeat(20 * 1024 + 1), new Uint8Array([0xff])]) {
      const malformed = clientFor(
        () =>
          new Response(body, {
            headers: { "content-type": "application/json", "cache-control": "no-store" },
          }),
      );
      await expect(malformed.client.list(PROFILE)).rejects.toMatchObject({ kind: "unavailable" });
    }
  });
});

// Fictif: true. Transport contract only; the native integration tests use real job SHA values.
function retirementInput(): PrepareCronRetirement {
  return {
    intentionId: INTENT,
    capability: "31".repeat(32),
    epoch: 1,
    jobId: "retirement-job-fictif",
    nativeRevision: `sha256:${"a".repeat(42)}A`,
    declaration: structuredClone(DECLARATION),
  };
}

function preparedRetirement(input: PrepareCronRetirement) {
  const proof = {
    version: 1 as const,
    intention: input.intentionId,
    source_hash: "c".repeat(64),
    epoch: input.epoch,
    job_id: input.jobId,
    native_revision: input.nativeRevision,
    declaration_hash: createHash("sha256").update(stableStringify(input.declaration)).digest("hex"),
    declaration_key: `opsys-profile:${input.intentionId}`,
  };
  return {
    ...proof,
    receipt_id: createHash("sha256").update(stableStringify(proof)).digest("hex"),
    execute: false as const,
  };
}

function clientTestRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

describe("OpsysCronPrivateClient terminal cleanup", () => {
  it("uses the private cleanup audience and binds both replies to the disabled native SHA", async () => {
    const input = retirementInput();
    const proof = preparedRetirement(input);
    const { client, fetchImpl } = clientFor((url, init) => {
      expect(new Headers(init.headers).get("authorization")).toBe(`Bearer ${TOKEN}`);
      const body: unknown = JSON.parse(String(init.body));
      if (!clientTestRecord(body)) throw new Error("expected cleanup request object");
      expect(body.native_revision).toBe(input.nativeRevision);
      expect(body.config_revision).toBeUndefined();
      if (url.endsWith("/preparer-retrait")) return response(proof);
      expect(url.endsWith("/accuser-retrait")).toBe(true);
      expect(body.receipt_id).toBe(proof.receipt_id);
      return response({
        intention: INTENT,
        receipt_id: proof.receipt_id,
        source_hash: proof.source_hash,
        epoch: 1,
        job_id: input.jobId,
        etat: "retiree",
        execute: false,
      });
    });
    expect(await client.prepareRetirement(PROFILE, input)).toEqual(proof);
    const ack = await client.acknowledgeRetirement(PROFILE, {
      ...input,
      receiptId: proof.receipt_id,
      sourceHash: proof.source_hash,
    });
    expect(ack.etat).toBe("retiree");
    expect(JSON.stringify(ack)).not.toContain(input.capability);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it.each([
    "native_revision",
    "job_id",
    "declaration_hash",
    "source_hash",
    "receipt_id",
    "execute",
    "extra",
  ])("rejects an altered preparation %s without accepting a receipt", async (field) => {
    const input = retirementInput();
    const altered = {
      ...preparedRetirement(input),
      [field]: field === "execute" ? true : "altered-fictif",
    };
    const { client } = clientFor(() => response(altered));
    await expect(client.prepareRetirement(PROFILE, input)).rejects.toMatchObject({
      kind: "unavailable",
    });
  });

  it("snapshots all preparation and ACK scalars before fetch can mutate the host input", async () => {
    const input = { ...retirementInput() };
    const proof = preparedRetirement(input);
    const ackInput = { ...input, receiptId: proof.receipt_id, sourceHash: proof.source_hash };
    const { client } = clientFor((url) => {
      if (url.endsWith("/preparer-retrait")) {
        input.jobId = "mutated-job-fictif";
        input.nativeRevision = `sha256:${"b".repeat(42)}A`;
        input.epoch = 2;
        return response(proof);
      }
      const reply = {
        intention: ackInput.intentionId,
        receipt_id: ackInput.receiptId,
        source_hash: ackInput.sourceHash,
        epoch: ackInput.epoch,
        job_id: ackInput.jobId,
        etat: "retiree",
        execute: false,
      };
      ackInput.receiptId = "d".repeat(64);
      ackInput.sourceHash = "e".repeat(64);
      ackInput.epoch = 2;
      ackInput.jobId = "mutated-ack-job-fictif";
      return response(reply);
    });
    expect(await client.prepareRetirement(PROFILE, input)).toEqual(proof);
    const ack = await client.acknowledgeRetirement(PROFILE, ackInput);
    expect(ack.receipt_id).toBe(proof.receipt_id);
    expect(ack.epoch).toBe(1);
    expect(ack.job_id).toBe(proof.job_id);
  });

  it("closes getter errors and refuses non-SHA cleanup revisions before HTTP", async () => {
    const { client, fetchImpl } = clientFor(() => response({}));
    const input = { ...retirementInput() };
    Reflect.set(input, "nativeRevision", 1);
    await expect(client.prepareRetirement(PROFILE, input)).rejects.toMatchObject({
      kind: "configuration",
    });
    Object.defineProperty(input, "nativeRevision", {
      get() {
        throw new Error(TOKEN);
      },
    });
    await expect(client.prepareRetirement(PROFILE, input)).rejects.toThrow(
      OpsysCronPrivateClientError,
    );
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each(["epoch", "receipt_id", "job_id"])("rejects an ACK with divergent %s", async (field) => {
    const input = retirementInput();
    const proof = preparedRetirement(input);
    const reply = {
      intention: INTENT,
      receipt_id: proof.receipt_id,
      source_hash: proof.source_hash,
      epoch: 1,
      job_id: input.jobId,
      etat: "retiree",
      execute: false,
      [field]: field === "epoch" ? 2 : "divergent-fictif",
    };
    const { client } = clientFor(() => response(reply));
    await expect(
      client.acknowledgeRetirement(PROFILE, {
        ...input,
        receiptId: proof.receipt_id,
        sourceHash: proof.source_hash,
      }),
    ).rejects.toMatchObject({ kind: "unavailable" });
  });
});
