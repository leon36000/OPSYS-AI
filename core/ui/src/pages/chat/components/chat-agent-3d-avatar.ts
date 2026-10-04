import { LitElement, css, html, nothing } from "lit";
import { customElement, property, query, state } from "lit/decorators.js";
import { buildControlUiResourcePath } from "../../../../../src/gateway/control-ui-resource-routes.js";
import {
  ASSISTANT_AVATAR_MODELS,
  isAssistantAvatarModelId,
} from "../../../../../src/shared/assistant-avatar-model-catalog.js";
import { t } from "../../../i18n/index.ts";
import {
  fetchGatewayContextResource,
  readAvatarGatewayContext,
  registerAvatarGatewayReset,
} from "../../../lib/identity-avatar-context.ts";

const MODEL_RESPONSE_LIMIT = 10 * 1024 * 1024;
const RESOURCE_TIMEOUT_MS = 15_000;

type AvatarStatus = "idle" | "loading" | "ready" | "unavailable";
type GatewayContext = ReturnType<typeof readAvatarGatewayContext>;

@customElement("openclaw-chat-agent-3d-avatar")
export class ChatAgent3DAvatar extends LitElement {
  static styles = css`
    :host {
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }

    .avatar-control {
      display: grid;
      justify-items: center;
      gap: 0.25rem;
    }

    button {
      color: var(--text-muted);
      background: transparent;
      border: 0;
      border-radius: var(--radius-sm);
      cursor: default;
      font: inherit;
      padding: 0.25rem 0.5rem;
    }

    button:hover {
      color: var(--text-primary);
      background: var(--surface-hover);
    }

    button:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }

    canvas {
      display: block;
      width: 7rem;
      height: 8rem;
      max-width: min(28vw, 12rem);
      border-radius: var(--radius-md);
    }

    canvas[hidden] {
      display: none;
    }

    .status {
      color: var(--text-muted);
      font-size: 0.75rem;
    }
  `;

  @property({ attribute: false }) agentId = "";
  @property({ attribute: false }) avatarModelId = "";
  @property({ type: Boolean }) connected = false;
  @state() private expanded = false;
  @state() private status: AvatarStatus = "idle";
  @query("canvas") private canvas?: HTMLCanvasElement;

  private generation = 0;
  private requestAbort?: AbortController;
  private unregisterGatewayReset?: () => void;
  private three?: typeof import("three");
  private renderer?: import("three").WebGLRenderer;
  private scene?: import("three").Scene;
  private camera?: import("three").PerspectiveCamera;
  private modelRoot?: import("three").Object3D;

  protected willUpdate(changed: Map<PropertyKey, unknown>) {
    if (changed.has("agentId") || changed.has("avatarModelId") || changed.has("connected")) {
      this.closeRenderer();
      this.expanded = false;
      this.status = "idle";
    }
  }

  override disconnectedCallback() {
    this.closeRenderer();
    this.expanded = false;
    this.status = "idle";
    this.unregisterGatewayReset?.();
    this.unregisterGatewayReset = undefined;
    super.disconnectedCallback();
  }

  override connectedCallback() {
    super.connectedCallback();
    this.unregisterGatewayReset = registerAvatarGatewayReset(() => {
      this.closeRenderer();
      this.expanded = false;
      this.status = "idle";
      this.requestUpdate();
    });
  }

  private isAvailable(): boolean {
    return (
      this.connected && Boolean(this.agentId.trim()) && isAssistantAvatarModelId(this.avatarModelId)
    );
  }

  private isCurrent(
    generation: number,
    agentId: string,
    modelId: string,
    gateway: GatewayContext,
  ): boolean {
    const currentGateway = readAvatarGatewayContext();
    return (
      this.isConnected &&
      this.connected &&
      this.expanded &&
      this.generation === generation &&
      !this.requestAbort?.signal.aborted &&
      this.agentId === agentId &&
      this.avatarModelId === modelId &&
      currentGateway.origin === gateway.origin &&
      currentGateway.resourceBasePath === gateway.resourceBasePath &&
      currentGateway.authTokens.length === gateway.authTokens.length &&
      currentGateway.authTokens.every((token, index) => token === gateway.authTokens[index])
    );
  }

  private async toggleAvatar() {
    if (!this.isAvailable()) {
      return;
    }
    if (this.expanded) {
      this.expanded = false;
      this.closeRenderer();
      this.status = "idle";
      return;
    }
    const requestedAgentId = this.agentId;
    const requestedModelId = this.avatarModelId;
    this.expanded = true;
    this.status = "loading";
    await this.updateComplete;
    if (
      !this.isConnected ||
      !this.connected ||
      !this.expanded ||
      this.agentId !== requestedAgentId ||
      this.avatarModelId !== requestedModelId
    ) {
      return;
    }
    await this.loadModel(requestedAgentId, requestedModelId);
  }

  private async loadModel(agentId: string, modelId: string) {
    const gateway = readAvatarGatewayContext();
    const generation = ++this.generation;
    if (
      !this.isAvailable() ||
      !this.expanded ||
      this.agentId !== agentId ||
      this.avatarModelId !== modelId ||
      !isAssistantAvatarModelId(modelId) ||
      !gateway.origin
    ) {
      if (
        this.isConnected &&
        this.expanded &&
        this.agentId === agentId &&
        this.avatarModelId === modelId
      ) {
        this.status = "unavailable";
      }
      return;
    }
    const expectedAsset = ASSISTANT_AVATAR_MODELS[modelId];

    const abort = new AbortController();
    const deadline = AbortSignal.timeout(RESOURCE_TIMEOUT_MS);
    const operationSignal = AbortSignal.any([abort.signal, deadline]);
    this.requestAbort = abort;
    try {
      const url = buildControlUiResourcePath("agentAvatarModel", gateway.resourceBasePath, agentId);
      const response = await fetchGatewayContextResource(url, RESOURCE_TIMEOUT_MS, operationSignal);
      if (!response.ok) {
        await response.body?.cancel();
        throw new Error("MODEL_RESPONSE_REJECTED");
      }
      const mediaType = response.headers
        .get("content-type")
        ?.split(";", 1)[0]
        ?.trim()
        .toLowerCase();
      if (mediaType !== "model/gltf-binary") {
        await response.body?.cancel();
        throw new Error("MODEL_MEDIA_TYPE_REJECTED");
      }
      const bytes = await readBoundedBody(
        response,
        Math.min(MODEL_RESPONSE_LIMIT, expectedAsset.bytes),
        operationSignal,
      );
      if (bytes.byteLength !== expectedAsset.bytes) {
        throw new Error("MODEL_SIZE_REJECTED");
      }
      const digest = await withAbort(crypto.subtle.digest("SHA-256", bytes), operationSignal);
      const digestHex = Array.from(new Uint8Array(digest), (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("");
      if (digestHex !== expectedAsset.sha256) {
        throw new Error("MODEL_DIGEST_REJECTED");
      }
      if (operationSignal.aborted || !this.isCurrent(generation, agentId, modelId, gateway)) {
        return;
      }

      const [three, loaderModule] = await withAbort(
        Promise.all([import("three"), import("three/addons/loaders/GLTFLoader.js")]),
        operationSignal,
      );
      if (operationSignal.aborted || !this.isCurrent(generation, agentId, modelId, gateway)) {
        return;
      }
      const manager = new three.LoadingManager();
      manager.setURLModifier((resourceUrl) => {
        if (resourceUrl.startsWith("blob:") || resourceUrl.startsWith("data:")) {
          return resourceUrl;
        }
        throw new Error("MODEL_EXTERNAL_RESOURCE_REJECTED");
      });
      const gltf = await withAbort(
        new loaderModule.GLTFLoader(manager).parseAsync(bytes, ""),
        operationSignal,
        (lateGltf) => disposeModel(three, lateGltf.scene),
      );
      if (operationSignal.aborted || !this.isCurrent(generation, agentId, modelId, gateway)) {
        disposeModel(three, gltf.scene);
        return;
      }

      await this.updateComplete;
      if (operationSignal.aborted || !this.isCurrent(generation, agentId, modelId, gateway)) {
        disposeModel(three, gltf.scene);
        return;
      }
      const canvas = this.canvas;
      if (!canvas) {
        throw new Error("MODEL_CANVAS_UNAVAILABLE");
      }
      this.three = three;
      this.modelRoot = gltf.scene;
      const renderer = new three.WebGLRenderer({ canvas, alpha: true, antialias: false });
      this.renderer = renderer;
      const scene = new three.Scene();
      const camera = new three.PerspectiveCamera(32, 7 / 8, 0.1, 100);
      const bounds = new three.Box3().setFromObject(gltf.scene);
      const size = bounds.getSize(new three.Vector3());
      const center = bounds.getCenter(new three.Vector3());
      const extent = Math.max(size.x, size.y, size.z, 1);
      gltf.scene.position.sub(center);
      scene.add(new three.HemisphereLight(0xffffff, 0x777777, 2));
      const keyLight = new three.DirectionalLight(0xffffff, 2);
      keyLight.position.set(2, 4, 3);
      scene.add(keyLight, gltf.scene);
      camera.position.set(0, 0, extent * 2.8);
      camera.lookAt(0, 0, 0);
      renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 1.5));
      renderer.setSize(224, 256, false);
      renderer.setClearColor(0x000000, 0);
      renderer.render(scene, camera);

      this.scene = scene;
      this.camera = camera;
      this.modelRoot = gltf.scene;
      this.status = "ready";
    } catch {
      if (this.generation === generation) {
        this.closeRenderer();
        this.status = "unavailable";
      }
    } finally {
      if (this.requestAbort === abort) {
        this.requestAbort = undefined;
      }
    }
  }

  private closeRenderer() {
    this.generation += 1;
    this.requestAbort?.abort();
    this.requestAbort = undefined;
    if (this.three && this.modelRoot) {
      disposeModel(this.three, this.modelRoot);
    }
    this.renderer?.dispose();
    this.renderer = undefined;
    this.scene = undefined;
    this.camera = undefined;
    this.modelRoot = undefined;
    this.three = undefined;
  }

  protected render() {
    if (!this.isAvailable()) {
      return nothing;
    }
    const label = this.expanded ? t("chat.avatar3d.hide") : t("chat.avatar3d.show");
    return html`<div class="avatar-control">
      <button type="button" aria-expanded=${this.expanded} @click=${this.toggleAvatar}>
        ${label}
      </button>
      ${
        this.expanded
          ? html`${
                this.status === "loading" || this.status === "ready"
                  ? html`<canvas aria-hidden="true" ?hidden=${this.status !== "ready"}></canvas>`
                  : nothing
              }
              <span class="status" role="status" aria-live="polite">
                ${
                  this.status === "loading"
                    ? t("chat.avatar3d.loading")
                    : this.status === "unavailable"
                      ? t("chat.avatar3d.unavailable")
                      : nothing
                }
              </span>`
          : nothing
      }
    </div>`;
  }
}

async function readBoundedBody(
  response: Response,
  limit: number,
  signal: AbortSignal,
): Promise<ArrayBuffer> {
  const declared = response.headers.get("content-length");
  if (declared !== null) {
    const length = Number(declared);
    if (!Number.isSafeInteger(length) || length < 0 || length > limit) {
      await response.body?.cancel();
      throw new Error("MODEL_SIZE_REJECTED");
    }
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("MODEL_BODY_MISSING");
  }
  // The endpoint caps GLB responses at 10 MiB. One fixed allocation also
  // bounds per-chunk object overhead for a stream yielding one byte at a time.
  const bytes = new Uint8Array(limit);
  let total = 0;
  const cancelReader = () => {
    void reader.cancel(signal.reason).catch(() => undefined);
  };
  signal.addEventListener("abort", cancelReader, { once: true });
  try {
    while (true) {
      const next = await withAbort(reader.read(), signal);
      if (next.done) {
        break;
      }
      total += next.value.byteLength;
      if (total > limit) {
        await reader.cancel();
        throw new Error("MODEL_SIZE_REJECTED");
      }
      bytes.set(next.value, total - next.value.byteLength);
    }
  } finally {
    signal.removeEventListener("abort", cancelReader);
    reader.releaseLock();
  }
  return bytes.slice(0, total).buffer;
}

function withAbort<T>(
  promise: Promise<T>,
  signal: AbortSignal,
  disposeLate?: (value: T) => void,
): Promise<T> {
  if (signal.aborted) {
    void promise.then(disposeLate).catch(() => undefined);
    return Promise.reject(signal.reason);
  }
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const onAbort = () => {
      settled = true;
      reject(signal.reason);
    };
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        if (settled || signal.aborted) {
          try {
            disposeLate?.(value);
          } catch {
            // Cleanup from an obsolete parse must never revive that result.
          }
          return;
        }
        settled = true;
        resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", onAbort);
        if (!settled) {
          settled = true;
          reject(error);
        }
      },
    );
  });
}

function disposeModel(three: typeof import("three"), root: import("three").Object3D) {
  const materials = new Set<import("three").Material>();
  const textures = new Set<import("three").Texture>();
  root.traverse((node) => {
    if (!(node instanceof three.Mesh)) {
      return;
    }
    node.geometry.dispose();
    const meshMaterials = Array.isArray(node.material) ? node.material : [node.material];
    for (const material of meshMaterials) {
      materials.add(material);
      for (const value of Object.values(material)) {
        if (value instanceof three.Texture) {
          textures.add(value);
        }
      }
    }
  });
  for (const texture of textures) {
    texture.dispose();
  }
  for (const material of materials) {
    material.dispose();
  }
}
