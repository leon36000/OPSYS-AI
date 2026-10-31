import { describe, expect, it, vi } from "vitest";
import { projectOperatorGrant } from "./device-pairing-binding.js";
import type { PairedDevice } from "./device-pairing.types.js";

function device(): PairedDevice {
  return {
    deviceId: "a",
    publicKey: "key",
    createdAtMs: 1,
    approvedAtMs: 1,
    role: "operator",
    approvedScopes: ["operator.read", "operator.write"],
    tokens: {
      operator: { token: "token-a", role: "operator", scopes: ["operator.read"], createdAtMs: 1 },
    },
  };
}
describe("operator grant projection", () => {
  it("ignores last-use and unrelated role metadata", () => {
    const a = device(),
      b = structuredClone(a);
    b.tokens!.operator!.lastUsedAtMs = 100;
    b.lastSeenAtMs = 100;
    b.tokens!.node = { token: "other", role: "node", scopes: [], createdAtMs: 2 };
    expect(projectOperatorGrant(b)).toEqual(projectOperatorGrant(a));
  });
  it("changes on revoke, replacement and approved scope reduction", () => {
    const original = device(),
      revoked = structuredClone(original),
      rotated = structuredClone(original),
      reduced = structuredClone(original);
    revoked.tokens!.operator!.revokedAtMs = 2;
    rotated.tokens!.operator!.token = "different";
    reduced.approvedScopes = [];
    expect(projectOperatorGrant(revoked)).toBeNull();
    expect(projectOperatorGrant(rotated)).not.toEqual(projectOperatorGrant(original));
    expect(projectOperatorGrant(reduced)).not.toEqual(projectOperatorGrant(original));
    expect(projectOperatorGrant(null)).toBeNull();
  });
});

import type { OpenClawStateDatabaseReadAdmission } from "../state/openclaw-state-db-async-lifecycle.js";
import { resolveOpenClawStateSqlitePath } from "../state/openclaw-state-db.paths.js";
import {
  captureDevicePairingPublication,
  capturePublishedOperatorGrant,
  getPublishedPairedDeviceBinding,
} from "./device-pairing-publication.js";

function makePublication(label: string) {
  const baseDir = `/tmp/operator-grant-private-test-${label}`;
  const path = resolveOpenClawStateSqlitePath({ ...process.env, OPENCLAW_STATE_DIR: baseDir });
  const admission: OpenClawStateDatabaseReadAdmission = {
    databasePath: path,
    identity: { key: path, canonicalPath: path },
    assertCurrent() {},
  };
  const publication = captureDevicePairingPublication(admission);
  const first = device(),
    second = {
      ...device(),
      deviceId: "b",
      tokens: { operator: { ...device().tokens!.operator!, token: "token-b" } },
    };
  const toRow = (item: PairedDevice) => ({
    deviceId: item.deviceId,
    binding: null,
    operatorGrant: projectOperatorGrant(item),
  });
  const rows: [ReturnType<typeof toRow>, ReturnType<typeof toRow>] = [toRow(first), toRow(second)];
  expect(publication.publish("before", rows, true)).toBe(true);
  return { publication: captureDevicePairingPublication(admission), admission, baseDir, rows };
}

describe("synchronous grant publication", () => {
  it("blocks the targeted grant before commit, until a delayed commit receipt installs revocation", () => {
    const { publication, baseDir, rows } = makePublication("delayed-commit");
    const a = capturePublishedOperatorGrant(
        "a",
        "token-a",
        projectOperatorGrant(device()),
        baseDir,
      ),
      b = capturePublishedOperatorGrant(
        "b",
        "token-b",
        projectOperatorGrant({
          ...device(),
          deviceId: "b",
          tokens: { operator: { ...device().tokens!.operator!, token: "token-b" } },
        }),
        baseDir,
      );
    expect(a()).toBe(true);
    expect(b()).toBe(true);
    const mutation = publication.beginMutation();
    mutation.stageOperatorChanges(["a"]);
    expect(a()).toBe(false);
    expect(b()).toBe(true);
    mutation.publish({
      kind: "devicePairing",
      operatorGrantVersion: 1,
      beforeRevision: "before",
      revision: "after",
      changed: [{ ...rows[0], operatorGrant: null }],
    });
    mutation.finish(true);
    expect(a()).toBe(false);
    expect(b()).toBe(true);
  });
  it("restores only after a known rollback and stays blocked on unknown outcome", () => {
    const { publication, baseDir } = makePublication("rollback");
    const a = capturePublishedOperatorGrant(
        "a",
        "token-a",
        projectOperatorGrant(device()),
        baseDir,
      ),
      b = capturePublishedOperatorGrant(
        "b",
        "token-b",
        projectOperatorGrant({
          ...device(),
          deviceId: "b",
          tokens: { operator: { ...device().tokens!.operator!, token: "token-b" } },
        }),
        baseDir,
      );
    const rollback = publication.beginMutation();
    rollback.stageOperatorChanges(["a"]);
    expect(a()).toBe(false);
    expect(b()).toBe(true);
    rollback.finish(true);
    expect(a()).toBe(true);
    const unknown = publication.beginMutation();
    unknown.stageOperatorChanges(["a"]);
    unknown.finish(false);
    expect(a()).toBe(false);
    expect(b()).toBe(true);
  });
  it("does not invalidate a grant on a same-security last-used update", () => {
    const { publication, baseDir, rows } = makePublication("last-used");
    const a = capturePublishedOperatorGrant(
      "a",
      "token-a",
      projectOperatorGrant(device()),
      baseDir,
    );
    const mutation = publication.beginMutation();
    mutation.publish({
      kind: "devicePairing",
      operatorGrantVersion: 1,
      beforeRevision: "before",
      revision: "after",
      changed: [rows[0]],
    });
    mutation.finish(true);
    expect(a()).toBe(true);
  });
  it("keeps an operator handle through a node-role-only receipt", () => {
    const { publication, baseDir, rows } = makePublication("node-only");
    const a = capturePublishedOperatorGrant(
      "a",
      "token-a",
      projectOperatorGrant(device()),
      baseDir,
    );
    const mutation = publication.beginMutation();
    expect(a()).toBe(true);
    mutation.publish({
      kind: "devicePairing",
      operatorGrantVersion: 1,
      beforeRevision: "before",
      revision: "after",
      changed: [rows[0]],
    });
    mutation.finish(true);
    expect(a()).toBe(true);
  });
  it("installs legacy node bindings independently while refusing unknown operator facts", () => {
    const { publication, baseDir } = makePublication("legacy-node");
    const a = capturePublishedOperatorGrant(
      "a",
      "token-a",
      projectOperatorGrant(device()),
      baseDir,
    );
    const mutation = publication.beginMutation();
    mutation.publish({
      kind: "devicePairing",
      beforeRevision: "before",
      revision: "after",
      changed: [{ deviceId: "a", binding: { identity: "legacy-node-binding" } }],
    });
    mutation.finish(true);
    expect(a()).toBe(false);
    expect(getPublishedPairedDeviceBinding("a", baseDir)).toEqual({
      identity: "legacy-node-binding",
    });
  });
  it("refuses legacy unversioned committed facts", () => {
    const { publication, baseDir } = makePublication("legacy");
    const a = capturePublishedOperatorGrant(
      "a",
      "token-a",
      projectOperatorGrant(device()),
      baseDir,
    );
    const mutation = publication.beginMutation();
    mutation.publish({
      kind: "devicePairing",
      beforeRevision: "before",
      revision: "after",
      changed: [],
    });
    mutation.finish(true);
    expect(a()).toBe(false);
  });
});

describe("operator snapshot ordering", () => {
  it("refuses a stale reader after a committed rotation and does not revive its prior handle", () => {
    const { publication, admission, baseDir, rows } = makePublication("stale-reader");
    const staleReader = captureDevicePairingPublication(admission);
    expect(staleReader.isCurrent()).toBe(true);
    const old = capturePublishedOperatorGrant(
      "a",
      "token-a",
      projectOperatorGrant(device()),
      baseDir,
    );
    const mutation = publication.beginMutation();
    mutation.stageOperatorChanges(["a"]);
    const rotated = device();
    rotated.tokens!.operator!.token = "token-new";
    mutation.publish({
      kind: "devicePairing",
      operatorGrantVersion: 1,
      beforeRevision: "before",
      revision: "after",
      changed: [{ ...rows[0], operatorGrant: projectOperatorGrant(rotated) }],
    });
    mutation.finish(true);
    expect(staleReader.isCurrent()).toBe(false);
    expect(staleReader.publish("before", rows, true)).toBe(false);
    expect(old()).toBe(false);
    expect(
      capturePublishedOperatorGrant("a", "token-new", projectOperatorGrant(rotated), baseDir)(),
    ).toBe(true);
  });
  it("fails closed when a legacy read has no operator facts", () => {
    const baseDir = "/tmp/operator-grant-private-test-legacy-read";
    const path = resolveOpenClawStateSqlitePath({ ...process.env, OPENCLAW_STATE_DIR: baseDir });
    const admission: OpenClawStateDatabaseReadAdmission = {
      databasePath: path,
      identity: { key: path, canonicalPath: path },
      assertCurrent() {},
    };
    const publication = captureDevicePairingPublication(admission);
    expect(publication.publish("before", [{ deviceId: "a", binding: null }], true)).toBe(true);
    expect(
      capturePublishedOperatorGrant("a", "token-a", projectOperatorGrant(device()), baseDir)(),
    ).toBe(false);
  });
});

describe("targeted security change matrix", () => {
  it.each(["revoke", "rotate", "scope-reduction", "remove-role", "remove-device"] as const)(
    "invalidates the matching operator on %s",
    (action) => {
      const { publication, baseDir, rows } = makePublication(`matrix-${action}`);
      const a = capturePublishedOperatorGrant(
          "a",
          "token-a",
          projectOperatorGrant(device()),
          baseDir,
        ),
        b = capturePublishedOperatorGrant(
          "b",
          "token-b",
          projectOperatorGrant({
            ...device(),
            deviceId: "b",
            tokens: { operator: { ...device().tokens!.operator!, token: "token-b" } },
          }),
          baseDir,
        );
      const next = device();
      if (action === "revoke") {
        next.tokens!.operator!.revokedAtMs = 9;
      }
      if (action === "rotate") {
        next.tokens!.operator!.token = "replacement";
      }
      if (action === "scope-reduction") {
        next.tokens!.operator!.scopes = [];
      }
      if (action === "remove-role") {
        delete next.tokens!.operator;
      }
      const projection = action === "remove-device" ? null : projectOperatorGrant(next);
      const mutation = publication.beginMutation();
      mutation.stageOperatorChanges(["a"]);
      expect(a()).toBe(false);
      expect(b()).toBe(true);
      mutation.publish({
        kind: "devicePairing",
        operatorGrantVersion: 1,
        beforeRevision: "before",
        revision: "after",
        changed: [{ ...rows[0], operatorGrant: projection }],
      });
      mutation.finish(true);
      expect(a()).toBe(false);
      expect(b()).toBe(true);
    },
  );
});

describe("snapshot and token verification boundary", () => {
  it("refuses stale observed scopes if the same token was reduced before capture", () => {
    const { publication, baseDir, rows } = makePublication("verified-scope-race");
    const admitted = projectOperatorGrant(device());
    const reduced = device();
    reduced.tokens!.operator!.scopes = [];
    const mutation = publication.beginMutation();
    mutation.stageOperatorChanges(["a"]);
    mutation.publish({
      kind: "devicePairing",
      operatorGrantVersion: 1,
      beforeRevision: "before",
      revision: "after",
      changed: [{ ...rows[0], operatorGrant: projectOperatorGrant(reduced) }],
    });
    mutation.finish(true);
    expect(capturePublishedOperatorGrant("a", "token-a", admitted, baseDir)()).toBe(false);
  });
});

import { assertOperatorGrantProtocol } from "./device-pairing-worker-contract.js";

describe("operator grant worker protocol order", () => {
  it("refuses a legacy empty first transaction before either grant or business callback", () => {
    const grant = vi.fn(),
      business = vi.fn();
    let negotiated = false;
    const admit = (stage: "transaction" | "commit", facts: unknown[]) => {
      const first = !negotiated;
      negotiated = assertOperatorGrantProtocol(stage, facts, negotiated);
      for (const fact of facts) {
        if (!first) {
          business(fact);
        }
      }
      grant();
    };
    expect(() => admit("transaction", [])).toThrow(/protocol v1 required/);
    expect(grant).not.toHaveBeenCalled();
    expect(business).not.toHaveBeenCalled();
    expect(() => admit("commit", [])).toThrow(/protocol v1 required/);
    expect(grant).not.toHaveBeenCalled();
    expect(business).not.toHaveBeenCalled();
  });
  it("admits the v1 marker before grant without leaking it to business callbacks", () => {
    const grant = vi.fn(),
      business = vi.fn();
    let negotiated = false;
    const admit = (stage: "transaction" | "commit", facts: unknown[]) => {
      const first = !negotiated;
      negotiated = assertOperatorGrantProtocol(stage, facts, negotiated);
      for (const fact of facts) {
        if (!first) {
          business(fact);
        }
      }
      grant();
    };
    admit("transaction", [{ kind: "operator-grant-protocol-v1" }]);
    expect(grant).toHaveBeenCalledTimes(1);
    expect(business).not.toHaveBeenCalled();
    const fact = { kind: "pairing-token-issuance" };
    admit("transaction", [fact]);
    admit("commit", [fact]);
    expect(grant).toHaveBeenCalledTimes(3);
    expect(business).toHaveBeenCalledTimes(2);
    expect(() => admit("transaction", [{ kind: "operator-grant-protocol-v1" }])).toThrow(
      /marker repeated/,
    );
    expect(grant).toHaveBeenCalledTimes(3);
  });
});
