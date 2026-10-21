import { afterEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import robotExpressiveGlbUrl from "../../../../../assets/avatar-models/robotexpressive-quaternius-cc0-v1.glb?url";
import { setAvatarGatewayOrigin } from "../../../lib/identity-avatar-context.ts";
import { ChatAgent3DAvatar } from "./chat-agent-3d-avatar.ts";

afterEach(() => {
  document.body.replaceChildren();
  setAvatarGatewayOrigin(null);
  vi.restoreAllMocks();
});

it("parses and renders a local GLB in real WebGL after explicit user action", async () => {
  setAvatarGatewayOrigin(location.origin, ["fixture-token"], "/local");
  const fixtureUrl = new URL(robotExpressiveGlbUrl, location.origin);
  expect(fixtureUrl.origin).toBe(location.origin);
  const fixtureResponse = await fetch(fixtureUrl);
  expect(fixtureResponse.ok).toBe(true);
  const glb = await fixtureResponse.arrayBuffer();
  expect(glb.byteLength).toBe(463_988);
  const fixtureDigest = await crypto.subtle.digest("SHA-256", glb);
  expect(
    Array.from(new Uint8Array(fixtureDigest), (byte) => byte.toString(16).padStart(2, "0")).join(
      "",
    ),
  ).toBe("047f5e5fb3bb6d378bd1df16ca6137f2a596c99b3a1b5690b4020c05aaf6f319");
  const fetchResource = vi.spyOn(globalThis, "fetch").mockImplementation(
    async () =>
      new Response(glb.slice(0), {
        headers: { "content-type": "model/gltf-binary", "content-length": String(glb.byteLength) },
      }),
  );
  const avatar = new ChatAgent3DAvatar();
  avatar.agentId = "main";
  avatar.avatarModelId = "robotexpressive-quaternius-cc0-v1";
  avatar.connected = true;
  document.body.append(avatar);
  await avatar.updateComplete;

  expect(fetchResource).not.toHaveBeenCalled();
  avatar.shadowRoot?.querySelector("button")?.click();
  await vi.waitFor(() => {
    const candidate = avatar.shadowRoot?.querySelector("canvas");
    expect(candidate).not.toBeNull();
    expect(candidate?.hidden).toBe(false);
  });

  const canvas = avatar.shadowRoot?.querySelector("canvas");
  expect(canvas?.width).toBe(224);
  expect(canvas?.getContext("webgl2")).not.toBeNull();
  const screenshot = await page.elementLocator(canvas!).screenshot({
    base64: true,
    save: true,
  });
  const image = new Image();
  image.src = `data:image/png;base64,${screenshot.base64}`;
  await image.decode();
  const pixelsCanvas = document.createElement("canvas");
  pixelsCanvas.width = image.width;
  pixelsCanvas.height = image.height;
  const pixelsContext = pixelsCanvas.getContext("2d");
  expect(pixelsContext).not.toBeNull();
  pixelsContext?.drawImage(image, 0, 0);
  const pixels = pixelsContext?.getImageData(0, 0, image.width, image.height).data;
  let changedPixels = 0;
  if (pixels) {
    const background = [pixels[0]!, pixels[1]!, pixels[2]!];
    for (let offset = 0; offset < pixels.length; offset += 4) {
      const distance =
        Math.abs(pixels[offset]! - background[0]!) +
        Math.abs(pixels[offset + 1]! - background[1]!) +
        Math.abs(pixels[offset + 2]! - background[2]!);
      if (distance > 36) {
        changedPixels += 1;
      }
    }
  }
  expect(changedPixels).toBeGreaterThan(100);
  expect(fetchResource).toHaveBeenCalledWith(
    "/local/avatar-model/main",
    expect.objectContaining({
      credentials: "include",
      headers: { Authorization: "Bearer fixture-token" },
    }),
  );

  avatar.shadowRoot?.querySelector("button")?.click();
  await avatar.updateComplete;
  expect(avatar.shadowRoot?.querySelector("canvas")).toBeNull();

  setAvatarGatewayOrigin(location.origin, ["rotated-fixture-token"], "/local");
  await avatar.updateComplete;
  avatar.shadowRoot?.querySelector("button")?.click();
  await vi.waitFor(() => expect(fetchResource).toHaveBeenCalledTimes(2));
  expect(fetchResource).toHaveBeenLastCalledWith(
    "/local/avatar-model/main",
    expect.objectContaining({
      headers: { Authorization: "Bearer rotated-fixture-token" },
    }),
  );
  expect(
    fetchResource.mock.calls.map(
      ([input]) =>
        new URL(input instanceof Request ? input.url : String(input), location.origin).origin,
    ),
  ).toEqual([location.origin, location.origin]);
  avatar.agentId = "other";
  await avatar.updateComplete;
  expect(avatar.shadowRoot?.querySelector("canvas")).toBeNull();
});
