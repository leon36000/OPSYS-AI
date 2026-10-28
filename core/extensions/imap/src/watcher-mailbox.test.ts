import { createDeferred } from "openclaw/plugin-sdk/extension-shared";
import type { OpenClawPluginServiceContext } from "openclaw/plugin-sdk/plugin-entry";
import { describe, expect, it, vi } from "vitest";
import { resolveImapConfig } from "./config.js";
import { createImapTestRuntime } from "./imap-test-support.js";
import { ImapAccountWatcher } from "./watcher.js";

const transport = vi.hoisted(() => ({
  connect: vi.fn(async () => {}),
  close: vi.fn(),
  mailboxOpen: vi.fn(async () => ({ uidValidity: "17", uidNext: 8 })),
  fetch: vi.fn(),
}));

vi.mock("imapflow", () => ({
  ImapFlow: class {
    on() {
      return this;
    }
    once() {
      return this;
    }
    connect = transport.connect;
    close = transport.close;
    mailboxOpen = transport.mailboxOpen;
    fetch = transport.fetch;
    capabilities = new Set<string>();
  },
}));

describe("IMAP watcher mailbox refusal before reading messages (mocked transport)", () => {
  it.each(["Archive", undefined])(
    "preserves cursor mailbox %j without FETCH or model dispatch",
    async (mailbox) => {
      vi.clearAllMocks();
      const fixture = createImapTestRuntime();
      const previous = {
        ...(mailbox === undefined ? {} : { mailbox }),
        uidValidity: "17",
        lastSeenUid: 41,
        updatedAt: 0,
      };
      await fixture.state.cursors.register("fictif", previous as never);
      const refused = createDeferred<unknown>();
      const account = resolveImapConfig({
        accounts: {
          fictif: {
            host: "imap-fictif.example.test",
            user: "reader-fictif@example.test",
            password: "password-fictif",
            agentId: "mail_reader",
            mailbox: "INBOX",
            allowedSenders: ["sender-fictif@example.test"],
          },
        },
      }).accounts.fictif;
      if (!account) {
        throw new Error("Fictive account missing");
      }
      const context: OpenClawPluginServiceContext = {
        config: {},
        stateDir: "/unused-imap-fictif-test-state",
        logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
        serviceHealth: {
          clearFailure: vi.fn(),
          reportFailure: (error) => {
            refused.resolve(error);
          },
        },
      };
      const watcher = new ImapAccountWatcher({
        accountId: "fictif",
        account,
        state: fixture.state,
        runtime: fixture.runtime,
        context,
      });
      try {
        watcher.start();
        await expect(refused.promise).resolves.toMatchObject({
          message: "IMAP_CURSOR_MAILBOX_UNBOUND_OR_CHANGED",
        });
        expect(transport.mailboxOpen).toHaveBeenCalledExactlyOnceWith("INBOX", { readOnly: true });
        expect(transport.fetch).not.toHaveBeenCalled();
        expect(fixture.dispatchHookAgentTurn).not.toHaveBeenCalled();
        expect(await fixture.state.cursors.lookup("fictif")).toEqual(previous);
        expect(transport.close).toHaveBeenCalled();
      } finally {
        await watcher.stop();
      }
    },
  );
  it.each([
    ["Archive", "17"],
    [undefined, "17"],
    ["INBOX", "18"],
  ] as const)(
    "refuses cursor mailbox %j UIDVALIDITY %j changed after opening INBOX, before FETCH",
    async (mailbox, uidValidity) => {
      vi.clearAllMocks();
      const fixture = createImapTestRuntime();
      await fixture.state.cursors.register("fictif", {
        mailbox: "INBOX",
        uidValidity: "17",
        lastSeenUid: 41,
        updatedAt: 0,
      });
      const changed = {
        ...(mailbox === undefined ? {} : { mailbox }),
        uidValidity,
        lastSeenUid: 2,
        updatedAt: 1,
      };
      const done = createDeferred<string>();
      transport.fetch.mockImplementation(() => ({
        async *[Symbol.asyncIterator]() {
          /* No messages in the mocked transport. */
        },
      }));
      const account = resolveImapConfig({
        accounts: {
          fictif: {
            host: "imap-fictif.example.test",
            user: "reader-fictif@example.test",
            password: "password-fictif",
            agentId: "mail_reader",
            mailbox: "INBOX",
            allowedSenders: ["sender-fictif@example.test"],
          },
        },
      }).accounts.fictif;
      if (!account) {
        throw new Error("Fictive account missing");
      }
      const context: OpenClawPluginServiceContext = {
        config: {},
        stateDir: "/unused-imap-fictif-test-state",
        logger: {
          info: vi.fn(),
          warn: (message) => {
            done.resolve(message);
          },
          error: vi.fn(),
          debug: () => {
            done.resolve("sweep completed without refusal");
          },
        },
        serviceHealth: {
          reportFailure: vi.fn(),
          clearFailure: () => {
            void fixture.state.cursors.register("fictif", changed as never);
          },
        },
      };
      const watcher = new ImapAccountWatcher({
        accountId: "fictif",
        account,
        state: fixture.state,
        runtime: fixture.runtime,
        context,
      });
      try {
        watcher.start();
        await expect(done.promise).resolves.toContain(
          mailbox === "INBOX" ? "IMAP_CURSOR_UIDVALIDITY" : "IMAP_CURSOR_MAILBOX",
        );
        expect(transport.mailboxOpen).toHaveBeenCalledExactlyOnceWith("INBOX", { readOnly: true });
        expect(transport.fetch).not.toHaveBeenCalled();
        expect(fixture.dispatchHookAgentTurn).not.toHaveBeenCalled();
        expect(await fixture.state.cursors.lookup("fictif")).toEqual(changed);
      } finally {
        await watcher.stop();
      }
    },
  );
});
