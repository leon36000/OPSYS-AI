// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDeferred } from "../../../../../test/helpers/promise.js";
import { setAvatarGatewayOrigin } from "../../../lib/identity-avatar-context.ts";
import { ChatAgent3DAvatar } from "./chat-agent-3d-avatar.ts";

afterEach(() => {
  document.body.replaceChildren();
  setAvatarGatewayOrigin(null);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function createAvatar(modelId = "robotexpressive-quaternius-cc0-v1") {
  const element = new ChatAgent3DAvatar();
  element.agentId = "main";
  element.avatarModelId = modelId;
  element.connected = true;
  document.body.append(element);
  return element;
}

describe("chat 3D avatar control", () => {
  it("does not render or fetch without a catalogued model", async () => {
    setAvatarGatewayOrigin(window.location.origin, ["private-token"]);
    const fetchResource = vi.spyOn(globalThis, "fetch");
    const element = createAvatar("unknown-model");
    await element.updateComplete;

    expect(element.shadowRoot?.querySelector("button")).toBeNull();
    expect(fetchResource).not.toHaveBeenCalled();
  });

  it("loads only after the explicit control and rejects an unexpected content type", async () => {
    setAvatarGatewayOrigin(window.location.origin, ["private-token"], "/opsys");
    const fetchResource = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("not a GLB", { headers: { "content-type": "text/plain" } }));
    const element = createAvatar();
    await element.updateComplete;

    expect(fetchResource).not.toHaveBeenCalled();
    const button = element.shadowRoot?.querySelector("button");
    expect(button?.getAttribute("aria-expanded")).toBe("false");
    button?.click();
    await vi.waitFor(() => expect(fetchResource).toHaveBeenCalledOnce());
    await vi.waitFor(() =>
      expect(element.shadowRoot?.textContent).toContain("3D avatar unavailable"),
    );

    expect(fetchResource).toHaveBeenCalledWith(
      "/opsys/avatar-model/main",
      expect.objectContaining({
        credentials: "include",
        headers: { Authorization: "Bearer private-token" },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(element.shadowRoot?.querySelector("canvas")).toBeNull();
  });

  it("rejects a streamed model above the byte cap without rendering a canvas", async () => {
    setAvatarGatewayOrigin(window.location.origin, ["private-token"]);
    const oversized = new Uint8Array(10 * 1024 * 1024 + 1);
    const fetchResource = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new ReadableStream({ start: (controller) => controller.enqueue(oversized) }), {
        headers: { "content-type": "model/gltf-binary" },
      }),
    );
    const element = createAvatar();
    await element.updateComplete;
    element.shadowRoot?.querySelector("button")?.click();
    await vi.waitFor(() =>
      expect(element.shadowRoot?.textContent).toContain("3D avatar unavailable"),
    );

    expect(fetchResource).toHaveBeenCalledOnce();
    expect(element.shadowRoot?.querySelector("canvas")).toBeNull();
  });

  it("rejects same-size GLB bytes that do not match the pinned catalogue digest", async () => {
    setAvatarGatewayOrigin(window.location.origin, ["private-token"]);
    const corrupted = new Uint8Array(463_988);
    const fetchResource = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(corrupted, {
        headers: {
          "content-type": "model/gltf-binary",
          "content-length": String(corrupted.byteLength),
        },
      }),
    );
    const element = createAvatar();
    await element.updateComplete;
    element.shadowRoot?.querySelector("button")?.click();
    await vi.waitFor(() =>
      expect(element.shadowRoot?.textContent).toContain("3D avatar unavailable"),
    );

    expect(fetchResource).toHaveBeenCalledOnce();
    expect(element.shadowRoot?.querySelector("canvas")).toBeNull();
  });

  it("aborts the old request and ignores its response when the active agent changes", async () => {
    setAvatarGatewayOrigin(window.location.origin, ["private-token"]);
    const started = createDeferred<void>();
    let requestSignal: AbortSignal | null | undefined;
    const fetchResource = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      requestSignal = init?.signal;
      started.resolve();
      return new Promise((_resolve, reject) => {
        if (!requestSignal) {
          reject(new Error("Missing request signal"));
          return;
        }
        requestSignal.addEventListener("abort", () => reject(requestSignal?.reason), {
          once: true,
        });
      });
    });
    const element = createAvatar();
    await element.updateComplete;
    element.shadowRoot?.querySelector("button")?.click();
    await started.promise;

    element.agentId = "other";
    await element.updateComplete;

    expect(requestSignal?.aborted).toBe(true);
    expect(fetchResource).toHaveBeenCalledOnce();
    expect(element.shadowRoot?.querySelector("canvas")).toBeNull();
    expect(element.shadowRoot?.textContent).not.toContain("Loading avatar");
  });

  it("aborts an in-flight request when the component disconnects", async () => {
    setAvatarGatewayOrigin(window.location.origin, ["private-token"]);
    const started = createDeferred<void>();
    let requestSignal: AbortSignal | null | undefined;
    const fetchResource = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      requestSignal = init?.signal;
      started.resolve();
      return new Promise((_resolve, reject) => {
        requestSignal?.addEventListener("abort", () => reject(requestSignal?.reason), {
          once: true,
        });
      });
    });
    const element = createAvatar();
    await element.updateComplete;
    element.shadowRoot?.querySelector("button")?.click();
    await started.promise;

    element.remove();

    expect(requestSignal?.aborted).toBe(true);
    expect(fetchResource).toHaveBeenCalledOnce();
  });

  it("aborts and closes the view when the Gateway auth context resets", async () => {
    setAvatarGatewayOrigin(window.location.origin, ["private-token"]);
    const started = createDeferred<void>();
    let requestSignal: AbortSignal | null | undefined;
    const fetchResource = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      requestSignal = init?.signal;
      started.resolve();
      return new Promise((_resolve, reject) => {
        requestSignal?.addEventListener("abort", () => reject(requestSignal?.reason), {
          once: true,
        });
      });
    });
    const element = createAvatar();
    await element.updateComplete;
    element.shadowRoot?.querySelector("button")?.click();
    await started.promise;

    setAvatarGatewayOrigin(window.location.origin, ["rotated-token"]);
    await element.updateComplete;

    expect(requestSignal?.aborted).toBe(true);
    expect(fetchResource).toHaveBeenCalledOnce();
    expect(element.shadowRoot?.querySelector("canvas")).toBeNull();
    expect(element.shadowRoot?.textContent).not.toContain("Loading avatar");
  });
});
