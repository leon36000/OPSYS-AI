import { describe, expect, it } from "vitest";
import { upsertSessionEntryCore } from "../../config/sessions/session-accessor.js";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { withOpenClawTestState } from "../../test-utils/openclaw-test-state.js";
import { resolveSandboxContext } from "./context.js";
import {
  resolveSandboxRuntimeStatus,
  resolveSandboxRuntimeStatusesForPersistedSessions,
} from "./runtime-status.js";

describe("session sandbox override", () => {
  it("keeps OPSYS agent main and named sessions sandbox-required despite persisted opt-out", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const cfg: OpenClawConfig = {
        tools: { exec: { host: "sandbox" } },
        agents: {
          ownership: "explicit",
          defaults: {
            opsysIsolation: { exec: "sandbox-required" },
            sandbox: {
              mode: "all",
              backend: "docker",
              scope: "session",
              workspaceAccess: "none",
              docker: { network: "none", readOnlyRoot: true, capDrop: ["ALL"], binds: [] },
            },
          },
          entries: {
            main: {},
            "m03-estimation": { opsysIsolation: { exec: "sandbox-required" } },
          },
        },
      };
      const sessionKey = "agent:m03-estimation:main";
      await upsertSessionEntryCore(
        { agentId: "m03-estimation", sessionKey },
        { sessionId: "main", updatedAt: 1, sandboxMode: "off" },
      );

      expect(
        resolveSandboxRuntimeStatus({ cfg, sessionKey, agentId: "m03-estimation" }),
      ).toMatchObject({
        sandboxRequired: true,
        sandboxed: true,
        workspaceAccess: "none",
      });

      const mainSessionKey = "agent:main:main";
      await upsertSessionEntryCore(
        { agentId: "main", sessionKey: mainSessionKey },
        { sessionId: "main", updatedAt: 1, sandboxMode: "off" },
      );
      expect(
        resolveSandboxRuntimeStatus({ cfg, sessionKey: mainSessionKey, agentId: "main" }),
      ).toMatchObject({
        sandboxRequired: true,
        sandboxed: true,
      });
    });
  });

  it("fails closed when an OPSYS-required agent sandbox is downgraded", () => {
    const cfg: OpenClawConfig = {
      agents: {
        ownership: "explicit",
        defaults: { sandbox: { mode: "off" } },
        entries: { "m03-estimation": { opsysIsolation: { exec: "sandbox-required" } } },
      },
    };

    expect(() =>
      resolveSandboxRuntimeStatus({
        cfg,
        sessionKey: "agent:m03-estimation:main",
        agentId: "m03-estimation",
        preparedSessionEntry: null,
      }),
    ).toThrow(/OPSYS agent m03-estimation requires/);
  });

  it("refuses an OPSYS sandbox-required request without a canonical session key", () => {
    const cfg = {
      tools: { exec: { host: "sandbox" } },
      agents: {
        ownership: "explicit",
        defaults: {
          opsysIsolation: { exec: "sandbox-required" },
          sandbox: {
            mode: "all",
            backend: "docker",
            scope: "session",
            workspaceAccess: "none",
            docker: { network: "none", readOnlyRoot: true, capDrop: ["ALL"], binds: [] },
          },
        },
        entries: { main: {} },
      },
    } as OpenClawConfig;
    expect(() => resolveSandboxRuntimeStatus({ cfg, agentId: "main" })).toThrow(
      /OPSYS agent main requires a canonical session key/,
    );
  });

  it.each(["seccompProfile", "apparmorProfile"] as const)(
    "rejects custom %s under required OPSYS isolation",
    (profileKey) => {
      const docker = {
        network: "none",
        readOnlyRoot: true,
        capDrop: ["ALL"],
        binds: [],
        [profileKey]: "unconfined",
      };
      const cfg = {
        tools: { exec: { host: "sandbox" } },
        agents: {
          ownership: "explicit",
          defaults: {
            opsysIsolation: { exec: "sandbox-required" },
            sandbox: {
              mode: "all",
              backend: "docker",
              scope: "session",
              workspaceAccess: "none",
              docker,
            },
          },
          entries: { main: {} },
        },
      } as OpenClawConfig;
      expect(() =>
        resolveSandboxRuntimeStatus({
          cfg,
          agentId: "main",
          sessionKey: "agent:main:main",
          preparedSessionEntry: null,
        }),
      ).toThrow(/OPSYS agent main requires/);
    },
  );

  it.each([
    ["remote execution target", { tools: { exec: { host: "node" } } }],
    ["host execution target", { tools: { exec: { host: "gateway" } } }],
    [
      "network or bind override",
      {
        tools: { exec: { host: "sandbox" } },
        agents: {
          ownership: "explicit",
          defaults: {
            sandbox: {
              mode: "all",
              backend: "docker",
              scope: "session",
              workspaceAccess: "none",
              docker: {
                network: "bridge",
                readOnlyRoot: true,
                capDrop: ["ALL"],
                binds: ["/run/docker.sock:/run/docker.sock"],
              },
            },
          },
          entries: { "m03-estimation": { opsysIsolation: { exec: "sandbox-required" } } },
        },
      },
    ],
  ])("rejects OPSYS downgrade: %s", (_name, overrides) => {
    const cfg = Object.assign(
      {
        tools: { exec: { host: "sandbox" } },
        agents: {
          ownership: "explicit",
          defaults: {
            sandbox: {
              mode: "all",
              backend: "docker",
              scope: "session",
              workspaceAccess: "none",
              docker: { network: "none", readOnlyRoot: true, capDrop: ["ALL"], binds: [] },
            },
          },
          entries: { "m03-estimation": { opsysIsolation: { exec: "sandbox-required" } } },
        },
      },
      overrides,
    ) as OpenClawConfig;
    expect(() =>
      resolveSandboxRuntimeStatus({
        cfg,
        sessionKey: "agent:m03-estimation:main",
        agentId: "m03-estimation",
        preparedSessionEntry: null,
      }),
    ).toThrow(/OPSYS agent m03-estimation requires/);
  });

  it("uses canonical classification identity in exact, batch, and context resolution", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async (state) => {
      const cfg: OpenClawConfig = { agents: { defaults: { sandbox: { mode: "all" } } } };
      const optional = "agent:main:optional";
      const required = "agent:main:required";
      for (const sessionKey of [optional, required]) {
        await upsertSessionEntryCore(
          { agentId: "main", sessionKey },
          {
            sessionId: sessionKey,
            updatedAt: 1,
            sandboxMode: "off",
            ...(sessionKey === required ? { sandbox: "required" as const } : {}),
          },
        );
      }
      expect(resolveSandboxRuntimeStatus({ cfg, sessionKey: "optional" }).sandboxed).toBe(false);
      expect(
        resolveSandboxRuntimeStatus({
          cfg,
          sessionKey: optional,
          classificationSessionKey: required,
        }),
      ).toMatchObject({
        sandboxed: true,
        sandboxRequired: true,
      });
      expect(
        resolveSandboxRuntimeStatus({
          cfg,
          sessionKey: required,
          classificationSessionKey: optional,
        }),
      ).toMatchObject({
        sandboxed: false,
        sandboxRequired: false,
      });
      expect(
        resolveSandboxRuntimeStatusesForPersistedSessions([
          { cfg, agentId: "main", env: state.env, sessionKeys: [optional, required] },
        ])[0],
      ).toMatchObject([
        { sandboxed: false, sandboxRequired: false },
        { sandboxed: true, sandboxRequired: true },
      ]);
      // An opted-out session must not start or prepare any sandbox backend.
      await expect(
        resolveSandboxContext({
          config: cfg,
          sessionKey: optional,
          agentId: "main",
          workspaceDir: state.workspaceDir,
        }),
      ).resolves.toBeNull();
    });
  });

  it("classifies a trusted patch candidate without using the old row", async () => {
    await withOpenClawTestState({ scenario: "minimal" }, async () => {
      const cfg: OpenClawConfig = {
        agents: { defaults: { sandbox: { mode: "all", workspaceAccess: "rw" } } },
      };
      const sessionKey = "agent:main:candidate";
      await upsertSessionEntryCore(
        { agentId: "main", sessionKey },
        { sessionId: "candidate", updatedAt: 1 },
      );
      expect(resolveSandboxRuntimeStatus({ cfg, sessionKey }).sandboxed).toBe(true);
      expect(
        resolveSandboxRuntimeStatus({
          cfg,
          sessionKey,
          preparedSessionEntry: { sandboxMode: "off" },
        }).sandboxed,
      ).toBe(false);
      expect(
        resolveSandboxRuntimeStatus({ cfg, sessionKey, preparedSessionEntry: null }).sandboxed,
      ).toBe(true);
      expect(
        resolveSandboxRuntimeStatus({
          cfg,
          sessionKey,
          preparedSessionEntry: {
            sandbox: "required",
            sandboxMode: "off",
            createdActor: { type: "human", source: "profile", id: "creator" },
          },
        }),
      ).toMatchObject({
        sandboxed: true,
        sandboxRequired: true,
        isolationSubject: { kind: "profile", profileId: "creator" },
        workspaceAccess: "ro",
      });
    });
  });
});
