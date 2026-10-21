import { resolveTsdownDtsGroups } from "./lib/tsdown-config-groups.mts";
import { writeTsdownDeclarations } from "./lib/tsdown-declaration-writer.mts";
import { listReplaceableTsdownDeclarationOutputs } from "./tsdown-build.mts";

await writeTsdownDeclarations(
  resolveTsdownDtsGroups().nonSdk,
  "tsdown-unified",
  (root) => listReplaceableTsdownDeclarationOutputs({ cwd: root, roots: ["dist"] }),
  "scripts/write-unified-entry-dts.ts",
);
