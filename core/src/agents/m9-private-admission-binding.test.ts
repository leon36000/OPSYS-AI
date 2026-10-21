import { describe, expect, it } from "vitest";
import {
  createAdmittedRunOperatorAuthority,
  createOperationalRunInstanceRef,
  getAdmittedRunDelegatedAuthority,
  resolveAdmittedRunActiveAssertion,
  type AdmittedRunOperatorAuthority,
} from "./admitted-run-context.js";
import { preparePrivateM9AdmissionBinding } from "./m9-private-admission-binding.js";

// Fictitious host fixtures; no M9 purpose, grant, model, provider or reservation authority.
function makeFixture(
  label: string,
  options: {
    assertSourceCurrent?: () => void;
    operatorAuthority?: AdmittedRunOperatorAuthority;
  } = {},
) {
  const controller = new AbortController();
  const runId = "fictitious-private-admission-" + label;
  const operationalRunInstance = createOperationalRunInstanceRef(runId);
  const binding = preparePrivateM9AdmissionBinding({
    cfg: {},
    facts: {
      runId,
      agentId: "fictitious-private-agent",
      ingress: { kind: "system", boundary: "private-admission-fixture", state: "present" },
    },
    operationalRunInstance,
    signal: controller.signal,
    ...options,
  });
  return { binding, controller, operationalRunInstance };
}

describe("private M9 admission lifetime restriction", () => {
  it("publishes a real settled canonical context and releases its exact authority on close", async () => {
    const { binding, operationalRunInstance } = makeFixture("settled");
    let context: Awaited<ReturnType<typeof binding.admit>> | undefined;
    let receipt: ReturnType<typeof binding.claim> | undefined;
    let active: (() => void) | undefined;
    try {
      context = await binding.admit("gateway", "fictitious-runtime");
      expect(context.operationalRunInstance).toBe(operationalRunInstance);
      expect(Object.isFrozen(context)).toBe(true);
      expect(getAdmittedRunDelegatedAuthority(context)).toBeDefined();
      active = resolveAdmittedRunActiveAssertion(context);
      expect(active).toBeTypeOf("function");
      receipt = binding.claim(context);
      expect(Object.isFrozen(receipt)).toBe(true);
      expect(receipt.context).toBe(context);
      expect(receipt.assertCurrent).not.toThrow();
    } finally {
      binding.close();
    }
    if (!context || !receipt || !active) {
      throw new Error("settled fixture did not capture its canonical context and receipt");
    }
    expect(getAdmittedRunDelegatedAuthority(context)).toBeUndefined();
    expect(active).toThrow();
    expect(receipt.assertCurrent).toThrow();
    binding.close();
    expect(getAdmittedRunDelegatedAuthority(context)).toBeUndefined();
  });

  it("memoizes concurrent admission promises and contexts through one real prepared owner", async () => {
    let retains = 0;
    let releases = 0;
    const operatorAuthority = createAdmittedRunOperatorAuthority({
      profileId: "fictitious-empty-scope-profile",
      scopes: [],
      assertCurrent: () => {},
      retain: () => {
        retains += 1;
        return () => {
          releases += 1;
        };
      },
    });
    const { binding } = makeFixture("memoized", { operatorAuthority });
    const ownedAdmissions: ReturnType<typeof binding.admit>[] = [];
    try {
      expect(retains).toBe(1);
      const first = binding.admit("gateway", "fictitious-first-runtime");
      ownedAdmissions.push(first);
      const second = binding.admit("embedded", "fictitious-later-runtime");
      ownedAdmissions.push(second);
      expect(second).toBe(first);
      const contexts = await Promise.all([first, second]);
      expect(contexts[1]).toBe(contexts[0]);
      const repeated = binding.admit("gateway");
      ownedAdmissions.push(repeated);
      expect(repeated).toBe(first);
      expect(retains).toBe(1);
      expect(getAdmittedRunDelegatedAuthority(contexts[0])).toBeDefined();
    } finally {
      binding.close();
      binding.close();
      await Promise.allSettled(ownedAdmissions);
    }
    expect(releases).toBe(1);
  });

  it("rejects close immediately after admit before callback settlement with zero publication or reserve", async () => {
    const { binding } = makeFixture("close-pending");
    let publications = 0;
    let reservations = 0;
    const owned: Promise<unknown>[] = [];
    try {
      const pending = binding.admit("gateway");
      owned.push(pending);
      const observed = pending.then(
        (context) => {
          publications += 1;
          binding.claim(context);
          reservations += 1;
        },
        () => undefined,
      );
      owned.push(observed);
      binding.close();
      const results = await Promise.allSettled([pending, observed]);
      expect(results[0].status).toBe("rejected");
      expect(results[1].status).toBe("fulfilled");
      expect(publications).toBe(0);
      expect(reservations).toBe(0);
    } finally {
      binding.close();
      await Promise.allSettled(owned);
    }
  });

  it("rejects a structural clone and never rearms the mismatched binding", async () => {
    const { binding } = makeFixture("clone");
    try {
      const context = await binding.admit("gateway");
      expect(() => binding.claim({ ...context })).toThrow();
      expect(() => binding.claim(context)).toThrow();
    } finally {
      binding.close();
    }
  });

  it("rejects a foreign real context without spending the other binding", async () => {
    const first = makeFixture("foreign-target");
    try {
      const other = makeFixture("foreign-owner");
      try {
        const contexts = await Promise.all([
          first.binding.admit("gateway"),
          other.binding.admit("gateway"),
        ]);
        expect(() => first.binding.claim(contexts[1])).toThrow();
        expect(() => first.binding.claim(contexts[0])).toThrow();
        const receipt = other.binding.claim(contexts[1]);
        expect(receipt.context).toBe(contexts[1]);
        expect(receipt.assertCurrent).not.toThrow();
      } finally {
        other.binding.close();
      }
    } finally {
      first.binding.close();
    }
  });

  it("latches source refusal before admission and refuses thenable source assertions", async () => {
    let current = true;
    const sourceError = new Error("fictitious source revoked");
    const first = makeFixture("source-before", {
      assertSourceCurrent: () => {
        if (!current) {
          throw sourceError;
        }
      },
    });
    try {
      current = false;
      await expect(first.binding.admit("gateway")).rejects.toThrow();
      current = true;
      await expect(first.binding.admit("gateway")).rejects.toThrow();
    } finally {
      first.binding.close();
    }
    let returnThenable = false;
    const second = makeFixture("thenable-source", {
      assertSourceCurrent: () => {
        if (returnThenable) {
          return Promise.resolve();
        }
      },
    });
    try {
      returnThenable = true;
      await expect(second.binding.admit("gateway")).rejects.toThrow();
      returnThenable = false;
      await expect(second.binding.admit("gateway")).rejects.toThrow();
    } finally {
      second.binding.close();
    }
  });

  it("refuses an aborted signal before admission without a replacement generation", async () => {
    const { binding, controller } = makeFixture("abort-before");
    try {
      controller.abort(new Error("fictitious pre-admission abort"));
      await expect(binding.admit("gateway")).rejects.toThrow();
      await expect(binding.admit("embedded")).rejects.toThrow();
    } finally {
      binding.close();
    }
  });

  it("latches source revocation after settlement before any claim", async () => {
    let current = true;
    const { binding } = makeFixture("source-before-claim", {
      assertSourceCurrent: () => {
        if (!current) {
          throw new Error("fictitious source revoked before claim");
        }
      },
    });
    try {
      const context = await binding.admit("gateway");
      current = false;
      expect(() => binding.claim(context)).toThrow();
      current = true;
      expect(() => binding.claim(context)).toThrow();
    } finally {
      binding.close();
    }
  });

  it("revalidates a consumed receipt across an await and latches source revocation", async () => {
    let current = true;
    const { binding } = makeFixture("receipt-source", {
      assertSourceCurrent: () => {
        if (!current) {
          throw new Error("fictitious source revoked while result drains");
        }
      },
    });
    try {
      const context = await binding.admit("gateway");
      const receipt = binding.claim(context);
      expect(receipt.assertCurrent).not.toThrow();
      const ownedResult = Promise.resolve().then(() => receipt.assertCurrent());
      const drained = Promise.allSettled([ownedResult]);
      current = false;
      const results = await drained;
      expect(results[0].status).toBe("rejected");
      current = true;
      expect(receipt.assertCurrent).toThrow();
      expect(() => binding.claim(context)).toThrow();
    } finally {
      binding.close();
    }
  });

  it("rechecks the exact signal before claim and while a consumed receipt result drains", async () => {
    const beforeClaim = makeFixture("signal-before-claim");
    try {
      const context = await beforeClaim.binding.admit("gateway");
      beforeClaim.controller.abort(new Error("fictitious settled pre-claim abort"));
      expect(() => beforeClaim.binding.claim(context)).toThrow();
      expect(() => beforeClaim.binding.claim(context)).toThrow();
    } finally {
      beforeClaim.binding.close();
    }
    const { binding, controller } = makeFixture("receipt-abort");
    try {
      const context = await binding.admit("gateway");
      const receipt = binding.claim(context);
      expect(receipt.assertCurrent).not.toThrow();
      const ownedResult = Promise.resolve().then(() => receipt.assertCurrent());
      const drained = Promise.allSettled([ownedResult]);
      controller.abort(new Error("fictitious draining-result abort"));
      const results = await drained;
      expect(results[0].status).toBe("rejected");
      expect(receipt.assertCurrent).toThrow();
      expect(() => binding.claim(context)).toThrow();
    } finally {
      binding.close();
    }
  });

  it("spends one claim across concurrent and repeated callers while keeping the first receipt live", async () => {
    const { binding } = makeFixture("one-shot");
    try {
      const context = await binding.admit("gateway");
      const results = await Promise.allSettled([
        Promise.resolve().then(() => binding.claim(context)),
        Promise.resolve().then(() => binding.claim(context)),
      ]);
      expect(results[0].status).toBe("fulfilled");
      expect(results[1].status).toBe("rejected");
      const first = results[0];
      if (first.status !== "fulfilled") {
        throw new Error("the first synchronous claim did not produce its receipt");
      }
      expect(first.value.context).toBe(context);
      expect(() => binding.claim(context)).toThrow();
      expect(first.value.assertCurrent).not.toThrow();
    } finally {
      binding.close();
    }
  });

  it("never rearms a spent claim when the caller operation rejects", async () => {
    const { binding } = makeFixture("operation-failure");
    try {
      const context = await binding.admit("gateway");
      const receipt = binding.claim(context);
      const operationError = new Error("fictitious reserved operation failed");
      await expect(Promise.reject(operationError)).rejects.toBe(operationError);
      expect(() => binding.claim(context)).toThrow();
      expect(receipt.assertCurrent).not.toThrow();
      expect(getAdmittedRunDelegatedAuthority(context)).toBeDefined();
    } finally {
      binding.close();
    }
  });

  it("refuses a cloned duplicate claim without revoking the already spent receipt", async () => {
    const { binding } = makeFixture("spent-clone");
    try {
      const context = await binding.admit("gateway");
      const receipt = binding.claim(context);
      const heldReceipt = receipt;
      const heldAssertion = receipt.assertCurrent;
      const authority = getAdmittedRunDelegatedAuthority(context);
      expect(authority).toBeDefined();
      expect(() => binding.claim({ ...context })).toThrow();
      expect(receipt.assertCurrent).not.toThrow();
      expect(receipt).toBe(heldReceipt);
      expect(receipt.assertCurrent).toBe(heldAssertion);
      expect(receipt.context).toBe(context);
      expect(getAdmittedRunDelegatedAuthority(context)).toBe(authority);
      expect(() => binding.claim(context)).toThrow();
      expect(receipt.assertCurrent).not.toThrow();
    } finally {
      binding.close();
    }
  });

  it("refuses a foreign duplicate claim without revoking either exact live authority", async () => {
    const first = makeFixture("spent-foreign-target");
    try {
      const other = makeFixture("spent-foreign-owner");
      try {
        const contexts = await Promise.all([
          first.binding.admit("gateway"),
          other.binding.admit("gateway"),
        ]);
        const receipt = first.binding.claim(contexts[0]);
        const heldReceipt = receipt;
        const heldAssertion = receipt.assertCurrent;
        const firstAuthority = getAdmittedRunDelegatedAuthority(contexts[0]);
        const otherAuthority = getAdmittedRunDelegatedAuthority(contexts[1]);
        expect(firstAuthority).toBeDefined();
        expect(otherAuthority).toBeDefined();
        expect(() => first.binding.claim(contexts[1])).toThrow();
        expect(receipt.assertCurrent).not.toThrow();
        expect(receipt).toBe(heldReceipt);
        expect(receipt.assertCurrent).toBe(heldAssertion);
        expect(receipt.context).toBe(contexts[0]);
        expect(getAdmittedRunDelegatedAuthority(contexts[0])).toBe(firstAuthority);
        expect(getAdmittedRunDelegatedAuthority(contexts[1])).toBe(otherAuthority);
        expect(() => first.binding.claim(contexts[0])).toThrow();
        expect(receipt.assertCurrent).not.toThrow();
        const otherReceipt = other.binding.claim(contexts[1]);
        expect(otherReceipt.context).toBe(contexts[1]);
        expect(otherReceipt.assertCurrent).not.toThrow();
      } finally {
        other.binding.close();
      }
    } finally {
      first.binding.close();
    }
  });
});
