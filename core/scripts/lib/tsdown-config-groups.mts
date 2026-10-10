import {
  collectPluginDeclarationSourceEntries,
  collectSourceCheckoutPluginBuildEntries,
  createBundledPluginBuildInventory,
} from "./bundled-plugin-build-entries.mjs";

// Shared config names let the build wrapper isolate the large unified DTS graph.
export const TSDOWN_PACKAGE_CONFIG_GROUP = "openclaw-packages";
export const TSDOWN_UNIFIED_CONFIG_GROUP = "openclaw-unified";
export const TSDOWN_UNIFIED_DTS_CONFIG_GROUPS = [
  "openclaw-dts-base",
  "openclaw-dts-plugin-sdk-1",
  "openclaw-dts-plugin-sdk-2",
  "openclaw-dts-extensions-1",
  "openclaw-dts-extensions-2",
  "openclaw-dts-extensions-3",
  "openclaw-dts-extensions-4",
  "openclaw-dts-extensions-5",
] as const;

export const TSDOWN_PLUGIN_SDK_DTS_CONFIG_GROUPS = TSDOWN_UNIFIED_DTS_CONFIG_GROUPS.slice(1, 3);

export const TSDOWN_NON_SDK_DTS_CONFIG_GROUPS = TSDOWN_UNIFIED_DTS_CONFIG_GROUPS.filter(
  (group) => !TSDOWN_PLUGIN_SDK_DTS_CONFIG_GROUPS.includes(group),
);

export const DTS_PARTITION_ENV = "OPENCLAW_BUILD_DTS_PARTITION";
export function resolveDtsPartitionProfile(
  env: NodeJS.ProcessEnv = process.env,
): "legacy" | "per-plugin" {
  const value = env[DTS_PARTITION_ENV];
  if (value === undefined) {
    return "legacy";
  }
  if (value !== "per-plugin") {
    throw new Error("OPENCLAW_BUILD_DTS_PARTITION must be per-plugin when set");
  }
  return value;
}

export function resolveTsdownDtsGroups(params: { cwd?: string; env?: NodeJS.ProcessEnv } = {}): {
  profile: "legacy" | "per-plugin";
  all: readonly string[];
  nonSdk: readonly string[];
  pluginSdk: readonly string[];
  extensions: readonly { name: string; pluginId: string | null }[];
} {
  const env = params.env ?? process.env;
  const profile = resolveDtsPartitionProfile(env);
  if (profile === "legacy") {
    return {
      profile,
      all: TSDOWN_UNIFIED_DTS_CONFIG_GROUPS,
      nonSdk: TSDOWN_NON_SDK_DTS_CONFIG_GROUPS,
      pluginSdk: TSDOWN_PLUGIN_SDK_DTS_CONFIG_GROUPS,
      extensions: TSDOWN_UNIFIED_DTS_CONFIG_GROUPS.slice(3).map((name) => ({
        name,
        pluginId: null,
      })),
    };
  }
  const inventory = createBundledPluginBuildInventory(params.cwd ?? process.cwd());
  const extensions = collectSourceCheckoutPluginBuildEntries({ ...inventory, env })
    .filter(
      (plugin) =>
        !plugin.isolated &&
        collectPluginDeclarationSourceEntries(plugin.packageJson, plugin.sourceEntries).some(
          (source) => /\.[cm]?tsx?$/u.test(source),
        ),
    )
    .toSorted((left, right) => left.id.localeCompare(right.id))
    .map((plugin) => ({ name: `openclaw-dts-extension-plugin-${plugin.id}`, pluginId: plugin.id }));
  const all = [
    TSDOWN_UNIFIED_DTS_CONFIG_GROUPS[0],
    ...TSDOWN_PLUGIN_SDK_DTS_CONFIG_GROUPS,
    ...extensions.map((group) => group.name),
  ];
  return {
    profile,
    all,
    nonSdk: [TSDOWN_UNIFIED_DTS_CONFIG_GROUPS[0], ...extensions.map((group) => group.name)],
    pluginSdk: TSDOWN_PLUGIN_SDK_DTS_CONFIG_GROUPS,
    extensions,
  };
}
