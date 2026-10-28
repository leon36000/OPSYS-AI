import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";

export type ImapCursor = {
  mailbox: string;
  uidValidity: string;
  lastSeenUid: number;
  updatedAt: number;
};
export type ImapClaim = { accountId: string; uid: number; recordedAt: number };
export type ImapAttempt = { count: number; reason: string };
export type ImapMessageRing = { messageIds: string[] };

export function createImapState(runtime: OpenClawPluginApi["runtime"]) {
  return {
    cursors: runtime.state.openKeyedStore<ImapCursor>({
      namespace: "cursor",
      maxEntries: 256,
      overflowPolicy: "reject-new",
    }),
    claims: runtime.state.openKeyedStore<ImapClaim | ImapAttempt>({
      namespace: "dispatch-claim",
      maxEntries: 20_000,
      defaultTtlMs: 7 * 24 * 60 * 60 * 1_000,
    }),
    messageIds: runtime.state.openKeyedStore<ImapMessageRing>({
      namespace: "msgid-ring",
      maxEntries: 256,
      overflowPolicy: "reject-new",
    }),
    skips: runtime.state.openKeyedStore<{ count: number }>({
      namespace: "skip-count",
      maxEntries: 2_048,
    }),
  };
}

export type ImapWatcherState = ReturnType<typeof createImapState>;

function requireMailbox(mailbox: string, cursor?: ImapCursor): void {
  if (
    typeof mailbox !== "string" ||
    mailbox.length === 0 ||
    mailbox.length > 1024 ||
    /[\0\r\n]/u.test(mailbox) ||
    (cursor !== undefined && cursor.mailbox !== mailbox)
  ) {
    // Old cursors carry no mailbox. Never guess INBOX, overwrite or silently reset them.
    throw new Error("IMAP_CURSOR_MAILBOX_UNBOUND_OR_CHANGED");
  }
}

export function assertImapCursorSource(
  cursor: ImapCursor | undefined,
  mailbox: string,
  uidValidity?: string,
): asserts cursor is ImapCursor {
  if (cursor === undefined) {
    throw new Error("IMAP_CURSOR_MAILBOX_UNAVAILABLE");
  }
  requireMailbox(mailbox, cursor);
  if (uidValidity !== undefined && cursor.uidValidity !== uidValidity) {
    throw new Error("IMAP_CURSOR_UIDVALIDITY_CHANGED");
  }
}

export async function initializeImapCursor(
  state: ImapWatcherState,
  accountId: string,
  uidValidity: string,
  uidNext: number,
  mailbox: string,
): Promise<{ kind: "baseline" | "reset" | "resume"; cursor: ImapCursor }> {
  requireMailbox(mailbox);
  let existing = await state.cursors.lookup(accountId);
  if (existing === undefined) {
    const baseline = {
      mailbox,
      uidValidity,
      lastSeenUid: Math.max(0, uidNext - 1),
      updatedAt: Date.now(),
    };
    // Two initializers must not bind the same account to different mailboxes.
    if (await state.cursors.registerIfAbsent(accountId, baseline)) {
      return { kind: "baseline", cursor: baseline };
    }
    existing = await state.cursors.lookup(accountId);
    if (existing === undefined) {
      throw new Error("IMAP_CURSOR_MAILBOX_UNAVAILABLE");
    }
  }
  assertImapCursorSource(existing, mailbox);
  if (existing.uidValidity === uidValidity) {
    return { kind: "resume", cursor: existing };
  }
  const cursor = {
    mailbox,
    uidValidity,
    lastSeenUid: Math.max(0, uidNext - 1),
    updatedAt: Date.now(),
  };
  await state.cursors.register(accountId, cursor);
  return { kind: "reset", cursor };
}

export async function advanceImapCursor(
  state: ImapWatcherState,
  accountId: string,
  uidValidity: string,
  uid: number,
  mailbox: string,
): Promise<void> {
  const existing = await state.cursors.lookup(accountId);
  assertImapCursorSource(existing, mailbox, uidValidity);
  await state.cursors.register(accountId, {
    mailbox,
    uidValidity,
    lastSeenUid: uid,
    updatedAt: Date.now(),
  });
}

export async function rememberImapMessage(
  state: ImapWatcherState,
  accountId: string,
  messageId: string,
): Promise<boolean> {
  const ring = await state.messageIds.lookup(accountId);
  if (ring?.messageIds.includes(messageId)) {
    return false;
  }
  await state.messageIds.register(accountId, {
    messageIds: [...(ring?.messageIds ?? []), messageId].slice(-100),
  });
  return true;
}

export async function countImapSkip(
  state: ImapWatcherState,
  accountId: string,
  reason: string,
): Promise<void> {
  const key = `${accountId}:${reason}`;
  const current = await state.skips.lookup(key);
  await state.skips.register(key, { count: Math.min((current?.count ?? 0) + 1, 1_000_000) });
}

export async function recordImapAttempt(
  state: ImapWatcherState,
  messageKey: string,
  reason: string,
): Promise<number> {
  const key = `attempt:${messageKey}`;
  const previous = await state.claims.lookup(key);
  const count = (previous && "count" in previous ? previous.count : 0) + 1;
  await state.claims.register(key, { count, reason });
  return count;
}
