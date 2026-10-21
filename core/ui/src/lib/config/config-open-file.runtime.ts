import { t } from "../../i18n/index.ts";
import { formatUiError, formatUiExternalText } from "../format-error.ts";
import { showToast } from "../toast.ts";
import {
  isCurrentConfigConnection,
  type ConfigGatewayClient,
  type RuntimeConfigState,
} from "./config-state-model.ts";

export async function openConfigFile(
  state: RuntimeConfigState,
  client: ConfigGatewayClient,
  connectionEpoch: number,
  canDispatch: () => boolean,
): Promise<void> {
  const isCurrent = () =>
    isCurrentConfigConnection(state, client, connectionEpoch) && canDispatch();
  if (!isCurrent()) {
    return;
  }
  const publishFailure = async (error: string, path?: string | null) => {
    if (!isCurrent()) {
      return;
    }
    let message = error;
    if (path) {
      let copied = false;
      try {
        const { copyToClipboard } = await import("../clipboard.ts");
        if (!isCurrent()) {
          return;
        }
        copied = await copyToClipboard(path, isCurrent);
      } catch {
        // Copying is optional; a chunk or transport failure must preserve the gateway error and path.
      }
      message += copied ? `\n\nFile path copied to clipboard: ${path}` : `\n\nFile path: ${path}`;
    }
    if (isCurrent()) {
      state.lastError = formatUiExternalText(message);
      showToast({ message: state.lastError });
    }
  };
  try {
    const res = await client.request<{ ok: boolean; path?: string; error?: string }>(
      "config.openFile",
      {},
    );
    if (!isCurrent()) {
      return;
    }
    if (!res.ok) {
      await publishFailure(
        formatUiExternalText(res.error, "Failed to open config file"),
        res.path || state.configSnapshot?.path,
      );
      return;
    }
    showToast({ message: t("configView.fileOpenedOnGateway") });
  } catch (err) {
    await publishFailure(formatUiError(err), state.configSnapshot?.path);
  }
}
