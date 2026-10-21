// `opsys metier <command>` and the retired spellings of the Python engine's commands (OPSYS-AI
// PLAN T0.7 lot 2): what the entry point recognizes before Commander, the config or the plugins.
import { describe, expect, it } from "vitest";
import {
  OPSYS_METIER_COMMAND,
  OPSYS_METIER_MOVED_COMMANDS,
  resolveOpsysMetierInvocation,
} from "./opsys-metier-argv.js";

const argv = (...args: string[]) => ["node", "openclaw", ...args];

describe("resolveOpsysMetierInvocation", () => {
  it("hands everything after `metier` to the engine, flags and help included, untouched", () => {
    expect(
      resolveOpsysMetierInvocation(
        argv("metier", "personnes", "creer", "alice.fictive", "--nom", "Alice Fictive", "--help"),
      ),
    ).toStrictEqual({
      kind: "metier",
      args: ["personnes", "creer", "alice.fictive", "--nom", "Alice Fictive", "--help"],
    });
  });

  it("recognizes a bare `metier`, which the engine answers with its own usage", () => {
    expect(resolveOpsysMetierInvocation(argv("metier"))).toStrictEqual({ kind: "metier", args: [] });
  });

  it("accepts root options before `metier` and keeps the ones that come after it for the engine", () => {
    expect(
      resolveOpsysMetierInvocation(argv("--no-color", "--log-level", "debug", "metier", "base", "etat")),
    ).toStrictEqual({ kind: "metier", args: ["base", "etat"] });
    expect(
      resolveOpsysMetierInvocation(argv("metier", "instance", "exporter", "--log-level", "x")),
    ).toStrictEqual({ kind: "metier", args: ["instance", "exporter", "--log-level", "x"] });
  });

  it.each(OPSYS_METIER_MOVED_COMMANDS)("says the new spelling of the retired `opsys %s`", (command) => {
    expect(resolveOpsysMetierInvocation(argv(command, "une-action", "--option", "valeur"))).toStrictEqual({
      kind: "moved",
      command,
      args: ["une-action", "--option", "valeur"],
    });
  });

  it("answers a retired name typed with a help flag too, instead of a Commander error", () => {
    expect(resolveOpsysMetierInvocation(argv("verifier", "--help"))).toStrictEqual({
      kind: "moved",
      command: "verifier",
      args: ["--help"],
    });
  });

  it.each([
    { title: "no command", args: [] },
    { title: "root help", args: ["--help"] },
    { title: "root version", args: ["--version"] },
    { title: "a core command", args: ["status", "--json"] },
    { title: "a core command group", args: ["gateway", "run"] },
    { title: "the help command aimed at metier", args: ["help", "metier"] },
    { title: "a word that only contains a retired name", args: ["personnes-x"] },
    { title: "a retired name typed in capitals", args: ["PERSONNES", "lister"] },
  ])("leaves $title to Commander", ({ args }) => {
    expect(resolveOpsysMetierInvocation(argv(...args))).toBeNull();
  });

  it("leaves an unknown option before the command to Commander, which refuses it", () => {
    expect(resolveOpsysMetierInvocation(argv("--inconnue", "metier", "base", "etat"))).toBeNull();
  });
});

describe("OPSYS_METIER_MOVED_COMMANDS", () => {
  it("lists each retired name once, and never `metier` itself", () => {
    expect(new Set(OPSYS_METIER_MOVED_COMMANDS).size).toBe(OPSYS_METIER_MOVED_COMMANDS.length);
    expect(OPSYS_METIER_MOVED_COMMANDS).not.toContain(OPSYS_METIER_COMMAND);
  });
});
