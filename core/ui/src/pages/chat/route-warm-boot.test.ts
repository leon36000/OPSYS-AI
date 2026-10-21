// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { createDeferred } from "../../../../test/helpers/promise.js";
import type { GatewaySessionRow } from "../../api/types.ts";
import type { ApplicationContext } from "../../app/context.ts";
import { SESSION_FACE_PREFERENCE_PARAM } from "../../lib/sessions/route-navigation.ts";
import { loadChatRoute } from "./route-loader.ts";
import {
  createSessionRouteContext,
  createSessionRouteRow,
  installShortSessionResolver,
  sessionRouteListResult,
} from "./route-resolution.test-support.ts";
import { renderChatRoute } from "./route-view.ts";

function warmRoute(scope: "per-sender" | "global" = "per-sender") {
  const fixture = createSessionRouteContext();
  const { context } = fixture;
  const connectedClient = context.gateway.snapshot.client;
  const listeners = new Set<Parameters<ApplicationContext["gateway"]["subscribe"]>[0]>();
  context.gateway.snapshot.phase = "connecting";
  context.gateway.snapshot.client = null;
  context.gateway.subscribe = vi.fn((listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  });
  context.agents.state.agentsList = {
    defaultId: "roboclaw",
    mainKey: "workspace",
    scope,
    agents: [{ id: "roboclaw" }],
  };
  context.agents.state.agentsListCached = true;
  const refreshList = vi.fn(async () => {
    context.agents.state.agentsListCached = false;
    return context.agents.state.agentsList;
  });
  context.agents.refreshList = refreshList;
  const cache = createDeferred();
  context.sessions.whenCachedRosterSettled = vi.fn(() => cache.promise);
  return {
    ...fixture,
    cache,
    refreshList,
    connect(this: void) {
      context.gateway.snapshot.phase = "connected";
      context.gateway.snapshot.client = connectedClient;
      for (const listener of listeners) {
        listener(context.gateway.snapshot);
      }
    },
    installResolver: (rows: GatewaySessionRow[]) => {
      context.gateway.snapshot.client = connectedClient;
      const request = installShortSessionResolver(context, rows);
      context.gateway.snapshot.client = null;
      return request;
    },
  };
}

describe("cached session route startup", () => {
  it("resolves an explicit main route before connecting with per-sender defaults", async () => {
    const { context, request, refreshList } = warmRoute();

    await expect(
      loadChatRoute(
        context,
        { pathname: "/chat/roboclaw", search: "", hash: "" },
        "chat",
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ kind: "session", sessionKey: "agent:roboclaw:workspace" });

    expect(context.gateway.subscribe).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
    expect(refreshList).not.toHaveBeenCalled();
  });

  it("waits for a live roster before rejecting an agent missing from the cache", async () => {
    const { context, request, refreshList, connect } = warmRoute();

    const pending = loadChatRoute(
      context,
      { pathname: "/chat/retired", search: "", hash: "" },
      "chat",
      new AbortController().signal,
    );
    await vi.waitFor(() => expect(context.gateway.subscribe).toHaveBeenCalledOnce());
    expect(refreshList).not.toHaveBeenCalled();
    connect();
    const route = await pending;

    expect(route).toMatchObject({ kind: "route-error", message: "Agent unavailable" });
    expect(refreshList).toHaveBeenCalledOnce();
    expect(request).not.toHaveBeenCalled();
    const view = renderChatRoute(route);
    expect(view).toHaveProperty("strings");
    const templateSource = (view as { strings: readonly string[] }).strings.join("");
    expect(templateSource).not.toContain("openclaw-chat-page");
  });

  it("keeps an explicit route when refresh finds an agent absent from the cache", async () => {
    const { context, refreshList, connect } = warmRoute();
    const cached = context.agents.state.agentsList!;
    refreshList.mockImplementation(async () => {
      const refreshed = {
        ...cached,
        agents: [...cached.agents, { id: "new-agent" }],
      };
      context.agents.state.agentsList = refreshed;
      context.agents.state.agentsListCached = false;
      return refreshed;
    });
    connect();

    await expect(
      loadChatRoute(
        context,
        { pathname: "/chat/new-agent", search: "", hash: "" },
        "chat",
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ kind: "session", sessionKey: "agent:new-agent:workspace" });
    expect(refreshList).toHaveBeenCalledOnce();
  });

  it("rejects an absent agent from an already live roster without refreshing again", async () => {
    const { context, refreshList } = warmRoute();
    context.agents.state.agentsListCached = false;

    await expect(
      loadChatRoute(
        context,
        { pathname: "/chat/retired", search: "", hash: "" },
        "chat",
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ kind: "route-error", message: "Agent unavailable" });
    expect(refreshList).not.toHaveBeenCalled();
  });

  it.each(["null roster without loader", "malformed roster"])(
    "fails closed for an %s",
    async (invalid) => {
      const { context } = warmRoute();
      if (invalid === "null roster without loader") {
        context.agents.state.agentsList = null;
        context.agents.state.agentsListCached = false;
        const incomplete = context.agents as unknown as {
          ensureList?: unknown;
          refreshList?: unknown;
        };
        delete incomplete.ensureList;
        delete incomplete.refreshList;
      } else {
        context.agents.state.agentsList = { mainKey: "workspace", agents: null } as never;
      }

      await expect(
        loadChatRoute(
          context,
          { pathname: "/chat/retired", search: "", hash: "" },
          "chat",
          new AbortController().signal,
        ),
      ).resolves.toMatchObject({
        kind: "route-error",
        message: "Agent status is unavailable. Reconnect and try again.",
      });
    },
  );

  it("does not label an unknown cached agent absent when a live roster request fails", async () => {
    const { context, refreshList, connect } = warmRoute();
    refreshList.mockResolvedValue(null);
    connect();

    await expect(
      loadChatRoute(
        context,
        { pathname: "/chat/retired", search: "", hash: "" },
        "chat",
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({
      kind: "route-error",
      message: "Agent status is unavailable. Reconnect and try again.",
    });
  });

  it("does not label an agent absent when the refreshed roster contains an invalid entry", async () => {
    const { context, refreshList, connect } = warmRoute();
    const malformed = {
      ...context.agents.state.agentsList!,
      agents: [{ id: null }],
    } as never;
    refreshList.mockImplementation(async () => {
      context.agents.state.agentsList = malformed;
      context.agents.state.agentsListCached = false;
      return malformed;
    });
    connect();

    await expect(
      loadChatRoute(
        context,
        { pathname: "/chat/retired", search: "", hash: "" },
        "chat",
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({
      kind: "route-error",
      message: "Agent status is unavailable. Reconnect and try again.",
    });
  });

  it("keeps a global main route waiting for hello", async () => {
    const { context, connect } = warmRoute("global");
    const completed = vi.fn();
    const pending = loadChatRoute(
      context,
      { pathname: "/chat/roboclaw", search: "", hash: "" },
      "chat",
      new AbortController().signal,
    ).then(completed);

    await vi.waitFor(() => expect(context.gateway.subscribe).toHaveBeenCalledOnce());
    expect(completed).not.toHaveBeenCalled();
    connect();
    await pending;
    expect(completed).toHaveBeenCalledWith(expect.objectContaining({ kind: "session" }));
  });

  it("resolves a global-scope literal route once hello makes its defaults authoritative", async () => {
    const { context, connect, installResolver } = warmRoute("global");
    const row = createSessionRouteRow({ key: "agent:roboclaw:thread" });
    const request = installResolver([row]);
    const completed = vi.fn();
    const pending = loadChatRoute(
      context,
      { pathname: "/chat/roboclaw/thread", search: "", hash: "" },
      "chat",
      new AbortController().signal,
    ).then(completed);

    await vi.waitFor(() => expect(context.gateway.subscribe).toHaveBeenCalledOnce());
    expect(completed).not.toHaveBeenCalled();
    connect();
    await pending;
    expect(completed).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "session", sessionKey: row.key }),
    );
    expect(request).toHaveBeenCalledOnce();
  });

  it("waits for the cached roster and resolves a unique short route before hello", async () => {
    const { context, cache, request } = warmRoute();
    const row = createSessionRouteRow({ displayName: "Cached conversation" });
    const completed = vi.fn();
    const pending = loadChatRoute(
      context,
      { pathname: "/chat/roboclaw/cached-conversation-12345678", search: "", hash: "" },
      "chat",
      new AbortController().signal,
    ).then(completed);

    await vi.waitFor(() => expect(context.sessions.whenCachedRosterSettled).toHaveBeenCalledOnce());
    expect(completed).not.toHaveBeenCalled();
    context.sessions.state.result = sessionRouteListResult([row]);
    context.sessions.state.resultCached = true;
    cache.resolve();
    await pending;

    expect(completed).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "session",
        sessionKey: row.key,
      }),
    );
    expect(context.gateway.subscribe).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });

  it.each(["missing", "ambiguous", "global", "preference"] as const)(
    "keeps %s cached short resolution on the Gateway path",
    async (scenario) => {
      const { context, cache, connect, installResolver } = warmRoute(
        scenario === "global" ? "global" : "per-sender",
      );
      const row = createSessionRouteRow({ displayName: "Cached conversation" });
      const duplicate = createSessionRouteRow({
        key: "agent:roboclaw:thread:12345678-0aaa-4000-8000-000000000001",
        displayName: "Cached conversation",
      });
      context.sessions.state.result = sessionRouteListResult(
        scenario === "missing" ? [] : scenario === "ambiguous" ? [row, duplicate] : [row],
      );
      const request = installResolver([row]);
      cache.resolve();
      const completed = vi.fn();
      const pending = loadChatRoute(
        context,
        {
          pathname: "/chat/roboclaw/cached-conversation-12345678",
          search: scenario === "preference" ? `?${SESSION_FACE_PREFERENCE_PARAM}=1` : "",
          hash: "",
        },
        "chat",
        new AbortController().signal,
      ).then(completed);

      await vi.waitFor(() => expect(context.gateway.subscribe).toHaveBeenCalled());
      expect(completed).not.toHaveBeenCalled();
      expect(request).not.toHaveBeenCalled();
      connect();
      await pending;
      expect(completed).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "session",
          sessionKey: row.key,
        }),
      );
      expect(request).toHaveBeenCalledOnce();
    },
  );
});
