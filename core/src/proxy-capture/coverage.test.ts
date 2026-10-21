// Proxy capture coverage tests cover capture coverage accounting and summaries.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { buildDebugProxyCoverageReport, maybeWarnAboutDebugProxyCoverage } from "./coverage.js";

describe("debug proxy coverage report", () => {
  it("summarizes captured and partial transport seams", () => {
    const report = buildDebugProxyCoverageReport();

    expect(report.summary.total).toBe(report.entries.length);
    expect(report.summary.captured).toBeGreaterThan(0);
    // Les deux seules entrées « proxy-only » (feishu-client-http/-ws) portaient sur une
    // extension élaguée (T0.6) ; les entrées restantes sont toutes « captured ».
    expect(report.summary.proxyOnly).toBe(0);
    const entryIds = new Set(report.entries.map((entry) => entry.id));
    expect(entryIds.has("provider-transport-fetch")).toBe(true);
    expect(entryIds.has("telegram-fetch")).toBe(true);
  });

  it("reports existing source modules for every transport seam", () => {
    for (const { id, modulePath } of buildDebugProxyCoverageReport().entries) {
      const sourcePath = fileURLToPath(new URL(`../../${modulePath}`, import.meta.url));
      expect(existsSync(sourcePath), `${id}: ${modulePath}`).toBe(true);
    }
  });

  it("warns about required capture gaps", () => {
    const warnings: string[] = [];
    // A fictitious, clearly-labelled fixture entry (fictif: true) exercises the warning's
    // message format for a real gap deterministically. The live roster (T0.6) has none: its
    // two former "proxy-only" entries were both for an extension this fork prunes, and
    // fabricating a gap in a still-kept extension's row would misreport it. See the note
    // above DEBUG_PROXY_COVERAGE_ENTRIES in coverage.ts.
    maybeWarnAboutDebugProxyCoverage(
      {
        blobDir: "/tmp/openclaw-debug-proxy-blobs",
        certDir: "/tmp/openclaw-debug-proxy-certs",
        dbPath: "/tmp/openclaw-debug-proxy.sqlite",
        enabled: true,
        proxyUrl: "http://127.0.0.1:8080",
        required: true,
        sessionId: "coverage-test",
        sourceProcess: "test",
      },
      (message) => warnings.push(message),
      [
        {
          id: "fictif-proxy-only-seam",
          label: "Fictitious proxy-only seam (fictif: true)",
          modulePath: "src/proxy-capture/coverage.ts",
          protocols: ["https"],
          status: "proxy-only",
          notes: "Test fixture only: not a claim about any real transport seam.",
        },
      ],
    );

    expect(warnings).toEqual([
      expect.stringContaining("debug proxy coverage"),
      expect.stringContaining("remaining gaps"),
    ]);
    expect(warnings[1]).toContain("fictif-proxy-only-seam");
  });
});
