/** Administrative transport declarations; local-looking hosts never imply consent. */
export type McpTransportSecurity = {
  readonly insecureHttpOrigin?: string;
  readonly httpsRedirectOrigins?: readonly string[];
};

export function isCanonicalMcpOrigin(value: string, protocol: "http:" | "https:"): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === protocol &&
      url.origin === value &&
      !url.hostname.includes("*") &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}

/** Validate untyped runtime inputs too, and capture a copy before any transport await. */
export function captureMcpTransportSecurity(value: unknown): McpTransportSecurity | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid MCP transportSecurity declaration");
  }
  if (
    Object.keys(value).some((key) => key !== "insecureHttpOrigin" && key !== "httpsRedirectOrigins")
  ) {
    throw new Error("Unrecognized MCP transportSecurity declaration");
  }
  const http = "insecureHttpOrigin" in value ? value.insecureHttpOrigin : undefined;
  const redirects = "httpsRedirectOrigins" in value ? value.httpsRedirectOrigins : undefined;
  if (http !== undefined && (typeof http !== "string" || !isCanonicalMcpOrigin(http, "http:"))) {
    throw new Error("MCP insecureHttpOrigin must be an exact canonical HTTP origin");
  }
  const redirectOrigins: string[] = [];
  if (redirects !== undefined) {
    if (!Array.isArray(redirects)) {
      throw new Error("MCP httpsRedirectOrigins must contain exact canonical HTTPS origins");
    }
    for (const origin of redirects) {
      if (typeof origin !== "string" || !isCanonicalMcpOrigin(origin, "https:")) {
        throw new Error("MCP httpsRedirectOrigins must contain exact canonical HTTPS origins");
      }
      redirectOrigins.push(origin);
    }
  }
  return Object.freeze({
    ...(http !== undefined ? { insecureHttpOrigin: http } : {}),
    ...(redirects !== undefined ? { httpsRedirectOrigins: Object.freeze(redirectOrigins) } : {}),
  });
}
