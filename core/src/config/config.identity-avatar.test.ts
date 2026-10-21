// Covers identity avatar config normalization and file-path handling.
import path from "node:path";
import { describe, expect, it } from "vitest";
import { withTempHome } from "./test-helpers.js";
import { validateConfigObject } from "./validation.js";

describe("identity avatar validation", () => {
  it("accepts workspace-relative avatar paths", async () => {
    await withTempHome(async (home) => {
      const workspace = path.join(home, "openclaw");
      const res = validateConfigObject({
        agents: {
          entries: {
            main: { default: true, workspace, identity: { avatar: "avatars/openclaw.png" } },
          },
        },
      });
      expect(res.ok).toBe(true);
    });
  });

  it("accepts http(s) and data avatars", async () => {
    await withTempHome(async (home) => {
      const workspace = path.join(home, "openclaw");
      const httpRes = validateConfigObject({
        agents: {
          entries: {
            main: {
              default: true,
              workspace,
              identity: { avatar: "https://example.com/avatar.png" },
            },
          },
        },
      });
      expect(httpRes.ok).toBe(true);

      const dataRes = validateConfigObject({
        agents: {
          entries: {
            main: {
              default: true,
              workspace,
              identity: { avatar: "data:image/png;base64,AAA" },
            },
          },
        },
      });
      expect(dataRes.ok).toBe(true);
    });
  });

  it("accepts only a model id from the shipped local avatar catalogue", async () => {
    await withTempHome(async (home) => {
      const workspace = path.join(home, "openclaw");
      const accepted = validateConfigObject({
        agents: {
          entries: {
            main: {
              default: true,
              workspace,
              identity: { avatarModelId: "robotexpressive-quaternius-cc0-v1" },
            },
          },
        },
      });
      expect(accepted.ok).toBe(true);

      const rejected = validateConfigObject({
        agents: {
          entries: {
            main: { default: true, workspace, identity: { avatarModelId: "../../private.glb" } },
          },
        },
      });
      expect(rejected.ok).toBe(false);
      if (!rejected.ok) {
        expect(rejected.issues[0]?.path).toBe("agents.entries.main.identity.avatarModelId");
      }
    });
  });

  it("rejects avatar paths outside workspace", async () => {
    await withTempHome(async (home) => {
      const workspace = path.join(home, "openclaw");
      const res = validateConfigObject({
        agents: {
          entries: {
            main: { default: true, workspace, identity: { avatar: "../oops.png" } },
          },
        },
      });
      expect(res.ok).toBe(false);
      if (!res.ok) {
        expect(res.issues[0]?.path).toBe("agents.entries.main.identity.avatar");
        expect(res.issues[0]?.pathSegments).toEqual([
          "agents",
          "entries",
          "main",
          "identity",
          "avatar",
        ]);
      }
    });
  });
});
