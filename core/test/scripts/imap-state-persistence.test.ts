import { closeSync, openSync, readSync } from "node:fs";
import path from "node:path";
import { createPluginStateSyncKeyedStore } from "openclaw/plugin-sdk/plugin-state-store-runtime";
import { createPluginRuntimeMock } from "openclaw/plugin-sdk/plugin-test-runtime";
import { createOpenClawTestState, type OpenClawTestState } from "openclaw/plugin-sdk/test-state";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  advanceImapCursor,
  createImapState,
  initializeImapCursor,
  type ImapCursor,
} from "../../extensions/imap/api.js";
import { withStateDatabaseCoordinatorRuntimeDirectory } from "../../src/infra/state-database-coordinator.js";
import { closePluginStateDatabase } from "../../src/plugin-state/plugin-state-store.sqlite.js";
import { resolveOpenClawStateSqlitePath } from "../../src/state/openclaw-state-db.paths.js";

let home: OpenClawTestState;
beforeAll(async () => {
  home = await createOpenClawTestState({ label: "imap-mailbox-fictif" });
});
afterAll(async () => {
  closePluginStateDatabase();
  await home?.cleanup();
});

function nativeState() {
  return createImapState(
    createPluginRuntimeMock({
      state: {
        openKeyedStore: (options) => createPluginStateSyncKeyedStore("imap", options),
      },
    }),
  );
}

function assertNativeSqliteFile() {
  const pathname = resolveOpenClawStateSqlitePath();
  expect(pathname.startsWith(home.root + path.sep)).toBe(true);
  const file = openSync(pathname, "r");
  try {
    const header = Buffer.alloc(16);
    expect(readSync(file, header, 0, 16, 0)).toBe(16);
    expect(header.toString("ascii")).toBe("SQLite format 3\0");
  } finally {
    closeSync(file);
  }
}

function withPrivateCoordinator(operation: () => Promise<void>) {
  return withStateDatabaseCoordinatorRuntimeDirectory(home.path("coordinator"), operation);
}

describe("IMAP mailbox cursor with native SQLite persistence (fictive)", () => {
  it("reopens the exact bound cursor and rejects another mailbox without overwriting it", () =>
    withPrivateCoordinator(async () => {
      const first = nativeState();
      await initializeImapCursor(first, "account-fictif", "17", 42, "INBOX");
      await advanceImapCursor(first, "account-fictif", "17", 45, "INBOX");
      const before = await first.cursors.lookup("account-fictif");
      assertNativeSqliteFile();
      closePluginStateDatabase();
      const reopened = nativeState();
      expect(await initializeImapCursor(reopened, "account-fictif", "17", 46, "INBOX")).toEqual({
        kind: "resume",
        cursor: before,
      });
      await expect(
        initializeImapCursor(reopened, "account-fictif", "17", 8, "Archive"),
      ).rejects.toThrow("IMAP_CURSOR_MAILBOX");
      closePluginStateDatabase();
      expect(await nativeState().cursors.lookup("account-fictif")).toEqual(before);
    }));

  it("preserves a persisted legacy cursor after refusal and another reopen", () =>
    withPrivateCoordinator(async () => {
      const legacy = { uidValidity: "17", lastSeenUid: 41, updatedAt: 0 };
      createPluginStateSyncKeyedStore<ImapCursor>("imap", {
        namespace: "cursor",
        maxEntries: 256,
        overflowPolicy: "reject-new",
      }).register("legacy-fictif", legacy as never);
      assertNativeSqliteFile();
      closePluginStateDatabase();
      const reopened = nativeState();
      await expect(
        initializeImapCursor(reopened, "legacy-fictif", "17", 42, "INBOX"),
      ).rejects.toThrow("IMAP_CURSOR_MAILBOX");
      closePluginStateDatabase();
      expect(await nativeState().cursors.lookup("legacy-fictif")).toEqual(legacy);
    }));
});
