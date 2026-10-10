// Sms API module exposes the plugin public contract.
export { getSmsRuntime, setSmsRuntime } from "./src/runtime.js";
export { verifyTwilioSignature } from "./src/twilio.js";
export {
  installOpsysSmsHostBridge,
  getOpsysSmsHostBridge,
  type OpsysSmsHostBridgeEntry,
} from "./src/opsys-host-bridge.js";
