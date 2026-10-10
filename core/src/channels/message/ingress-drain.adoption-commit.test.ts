// Fictitious native SQLite fixtures: successful adoption requires its own durable completion.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChannelIngressDrain } from "./ingress-drain.js";
import { createTestIngressQueue, withTempState } from "./ingress-drain.test-helpers.js";

type Lifecycle = Parameters<
  Parameters<typeof createChannelIngressDrain>[0]["dispatchClaimedEvent"]
>[1];

function gate() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

function observe(promise: void | Promise<void>) {
  const result = { state: "pending", error: undefined as unknown };
  const done = Promise.resolve(promise).then(
    () => {
      result.state = "fulfilled";
    },
    (error: unknown) => {
      result.state = "rejected";
      result.error = error;
    },
  );
  return { result, done };
}

describe("ingress adoption owns its completion outcome", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_700_000_000_000);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("concurrent adoption waits for the real commit and successful repeats do not write again", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-adopt", { text: "FICTIF" }, { laneKey: "one" });
      const pending = gate();
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let lifecycle!: Lifecycle;
      queue.complete = async (claim, options) => {
        calls += 1;
        await pending.promise;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (_claim, current) => {
          lifecycle = current;
          return { kind: "deferred" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        const first = observe(lifecycle.onAdopted());
        const second = observe(lifecycle.onAdopted());
        await vi.advanceTimersByTimeAsync(0);
        const secondBeforeCommit = second.result.state;
        expect((await queue.listClaims()).map((row) => row.id)).toEqual(["fictif-adopt"]);
        pending.release();
        await Promise.all([first.done, second.done]);
        await lifecycle.onAdopted();
        expect(secondBeforeCommit).toBe("pending");
        expect(first.result.state).toBe("fulfilled");
        expect(second.result.state).toBe("fulfilled");
        expect(calls).toBe(1);
        expect((await queue.enqueue("fictif-adopt", { text: "FICTIF" })).kind).toBe("completed");
      } finally {
        pending.release();
        drain.dispose();
      }
    });
  });

  it("keeps the exhausted IO rejection without an implicit retry or release", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-io", { text: "FICTIF" }, { laneKey: "one" });
      const failure = new Error("FICTIF complete IO failure");
      let calls = 0;
      let lifecycle!: Lifecycle;
      queue.complete = async () => {
        calls += 1;
        throw failure;
      };
      const drain = createChannelIngressDrain({
        queue,
        claimLeaseMs: 86_400_000,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          return { kind: "deferred" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        const original = (await queue.listClaims())[0]!;
        const first = observe(lifecycle.onAdopted());
        await vi.advanceTimersByTimeAsync(180_000);
        await first.done;
        const repeated = observe(lifecycle.onAdopted());
        await repeated.done;
        expect(first.result.error).toBe(failure);
        expect(repeated.result.error).toBe(failure);
        expect(calls).toBe(8);
        const held = (await queue.listClaims())[0]!;
        expect(held.claim).toEqual(original.claim);
        expect(drain.activeLaneKeys().has("one")).toBe(true);
        await queue.enqueue("fictif-tail", { text: "FICTIF tail" }, { laneKey: "one" });
        expect((await drain.drainOnce()).started).toBe(0);
      } finally {
        drain.dispose();
      }
    });
  });

  it("retains real reclaimed-token rejection for every later adoption", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-reclaim", { text: "FICTIF" }, { laneKey: "one" });
      const pending = gate();
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let lifecycle!: Lifecycle;
      queue.complete = async (claim, options) => {
        calls += 1;
        await pending.promise;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        claimLeaseMs: 86_400_000,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          return { kind: "deferred" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        const original = (await queue.listClaims())[0]!;
        const first = observe(lifecycle.onAdopted());
        await vi.advanceTimersByTimeAsync(0);
        await queue.release(original, { recordAttempt: false });
        const replacement = await queue.claim(original.id, { ownerId: "fictif-replacement" });
        expect(replacement!.claim.token).not.toBe(original.claim.token);
        pending.release();
        await first.done;
        const repeated = observe(lifecycle.onAdopted());
        await repeated.done;
        expect(first.result.error).toMatchObject({
          name: "IngressAdoptionLostError",
          code: "reclaimed",
        });
        expect(repeated.result.error).toBe(first.result.error);
        expect(calls).toBe(1);
        expect((await queue.listClaims())[0]!.claim).toEqual(replacement!.claim);
      } finally {
        pending.release();
        drain.dispose();
      }
    });
  });

  it("rejects first adoption after cancellation without converting pending into completed", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-cancel", { text: "FICTIF" });
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let lifecycle!: Lifecycle;
      queue.complete = async (claim, options) => {
        calls += 1;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          return { kind: "deferred" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        await lifecycle.onCancelled!();
        await expect(lifecycle.onAdopted()).rejects.toMatchObject({
          name: "IngressAdoptionLostError",
          code: "reclaimed",
        });
        expect(calls).toBe(0);
        expect((await queue.enqueue("fictif-cancel", { text: "FICTIF" })).kind).toBe("pending");
      } finally {
        drain.dispose();
      }
    });
  });

  it("does not mistake an in-flight cancellation release for its own completion", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-cancel-race", { text: "FICTIF" });
      const pending = gate();
      const release = queue.release.bind(queue);
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let lifecycle!: Lifecycle;
      queue.release = async (claim, options) => {
        await pending.promise;
        return release(claim, options);
      };
      queue.complete = async (claim, options) => {
        calls += 1;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          return { kind: "deferred" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        const cancellation = lifecycle.onCancelled!();
        const adoption = observe(lifecycle.onAdopted());
        pending.release();
        await cancellation;
        await adoption.done;
        expect(adoption.result.error).toMatchObject({
          name: "IngressAdoptionLostError",
          code: "reclaimed",
        });
        expect(calls).toBe(0);
        expect((await queue.enqueue("fictif-cancel-race", { text: "FICTIF" })).kind).toBe(
          "pending",
        );
      } finally {
        pending.release();
        drain.dispose();
      }
    });
  });

  it("installs adoption ownership before a reentrant completion callback", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-reenter", { text: "FICTIF" });
      const pending = gate();
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let lifecycle!: Lifecycle;
      let reentered!: ReturnType<typeof observe>;
      queue.complete = async (claim, options) => {
        calls += 1;
        reentered = observe(lifecycle.onAdopted());
        await pending.promise;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          return { kind: "deferred" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        const first = observe(lifecycle.onAdopted());
        await vi.advanceTimersByTimeAsync(0);
        const reenteredBeforeCommit = reentered.result.state;
        pending.release();
        await Promise.all([first.done, reentered.done]);
        expect(reenteredBeforeCommit).toBe("pending");
        expect(calls).toBe(1);
        expect((await queue.enqueue("fictif-reenter", { text: "FICTIF" })).kind).toBe("completed");
      } finally {
        pending.release();
        drain.dispose();
      }
    });
  });

  it("rejects default completion that joined a pending cancellation release", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-default-cancel", { text: "FICTIF" });
      const pending = gate();
      const release = queue.release.bind(queue);
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let lifecycle!: Lifecycle;
      let cancellation!: Promise<void>;
      queue.release = async (claim, options) => {
        await pending.promise;
        return release(claim, options);
      };
      queue.complete = async (claim, options) => {
        calls += 1;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          cancellation = Promise.resolve(current.onCancelled!());
          return { kind: "completed" };
        },
      });
      try {
        await drain.drainOnce();
        await vi.advanceTimersByTimeAsync(0);
        pending.release();
        await cancellation;
        await drain.waitForIdle();
        const repeated = observe(lifecycle.onAdopted());
        await repeated.done;
        expect(repeated.result.error).toMatchObject({
          name: "IngressAdoptionLostError",
          code: "reclaimed",
        });
        expect(calls).toBe(0);
        expect((await queue.enqueue("fictif-default-cancel", { text: "FICTIF" })).kind).toBe(
          "pending",
        );
      } finally {
        pending.release();
        drain.dispose();
      }
    });
  });

  it("shares the successful default completed fallback with a later explicit adoption", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-default", { text: "FICTIF" });
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let lifecycle!: Lifecycle;
      queue.complete = async (claim, options) => {
        calls += 1;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          return { kind: "completed" };
        },
      });
      try {
        await drain.drainOnce();
        await drain.waitForIdle();
        await lifecycle.onAdopted();
        expect(calls).toBe(1);
        expect((await queue.enqueue("fictif-default", { text: "FICTIF" })).kind).toBe("completed");
      } finally {
        drain.dispose();
      }
    });
  });

  it("shares the rejected default completed fallback without retrying on a later explicit call", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-default-io", { text: "FICTIF" });
      const failure = new Error("FICTIF fallback IO failure");
      let calls = 0;
      let lifecycle!: Lifecycle;
      queue.complete = async () => {
        calls += 1;
        throw failure;
      };
      const drain = createChannelIngressDrain({
        queue,
        claimLeaseMs: 86_400_000,
        dispatchClaimedEvent: (_c, current) => {
          lifecycle = current;
          return { kind: "completed" };
        },
      });
      try {
        await drain.drainOnce();
        await vi.advanceTimersByTimeAsync(180_000);
        await drain.waitForIdle();
        const repeated = observe(lifecycle.onAdopted());
        await repeated.done;
        expect(repeated.result.error).toBe(failure);
        expect(calls).toBe(8);
        expect((await queue.enqueue("fictif-default-io", { text: "FICTIF" })).kind).toBe("claimed");
      } finally {
        drain.dispose();
      }
    });
  });

  it("keeps default completion waiting for an explicit adoption still committing", async () => {
    await withTempState(async (stateDir) => {
      const queue = createTestIngressQueue(stateDir);
      await queue.enqueue("fictif-default-pending", { text: "FICTIF" });
      const pending = gate();
      const complete = queue.complete.bind(queue);
      let calls = 0;
      let explicit!: ReturnType<typeof observe>;
      queue.complete = async (claim, options) => {
        calls += 1;
        await pending.promise;
        return complete(claim, options);
      };
      const drain = createChannelIngressDrain({
        queue,
        dispatchClaimedEvent: (_c, current) => {
          explicit = observe(current.onAdopted());
          return { kind: "completed" };
        },
      });
      try {
        await drain.drainOnce();
        const idle = observe(drain.waitForIdle());
        await vi.advanceTimersByTimeAsync(0);
        const idleBeforeCommit = idle.result.state;
        pending.release();
        await Promise.all([idle.done, explicit.done]);
        expect(idleBeforeCommit).toBe("pending");
        expect(calls).toBe(1);
        expect((await queue.enqueue("fictif-default-pending", { text: "FICTIF" })).kind).toBe(
          "completed",
        );
      } finally {
        pending.release();
        drain.dispose();
      }
    });
  });
});
