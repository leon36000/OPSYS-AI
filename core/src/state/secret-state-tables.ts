/** Redaction policy surface: Git snapshots may omit these credential-bearing tables. */
export const STATE_SECRET_TABLE_NAMES = [
  "audit_identity_keys",
  "apns_registrations",
  "channel_ingress_events",
  "channel_pairing_requests",
  "clawhub_promotion_claims",
  // These keys decrypt application payloads persisted in otherwise generic tables.
  "cles_chiffrement",
  "config_revision_keys",
  "cron_job_runtime_authorities",
  // Retirement ciphertext still contains the old private capability needed for crash recovery.
  "cron_job_runtime_retirements",
  "device_auth_tokens",
  "device_bootstrap_tokens",
  "device_identities",
  "device_pairing_join_codes",
  "device_pairing_paired",
  "gateway_origin_device_tokens",
  "mcp_oauth_pending_authorizations",
  "mcp_oauth_stores",
  "native_hook_relay_bridges",
  "secret_store_entries",
  "web_push_subscriptions",
  "worker_environment_credentials",
] as const;

/** Secret-redacted Git backups must never carry machine-state values under these prefixes. */
export const STATE_SECRET_CONFIG_STATE_KEY_PREFIXES = [
  "authProfiles.",
  "nodeHost.",
  "webPush.vapidKeys",
] as const;

/** Redaction policy surface for credential-bearing per-agent database tables. */
export const AGENT_SECRET_TABLE_NAMES = [
  "auth_profile_state",
  "auth_profile_store",
  "session_suggestions",
] as const;
