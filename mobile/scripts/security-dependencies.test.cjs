// Forge regression vector adapted from digitalbazaar/forge PR #1152 (BSD-3-Clause).
// Only a public modulus and forged signature are stored; all test data is fictitious.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const { test } = require("node:test");
const root = path.resolve(__dirname, "..");
const requireMobile = createRequire(path.join(root, "package.json"));
const provenance = require(path.join(root, "vendor/PROVENANCE.json"));
const consumers = [["micromatch", "braces"], ["@expo/code-signing-certificates", "node-forge"], ["@expo/cli", "node-forge"]];
for (const [consumer, alias] of consumers) {
  test(`${consumer} resolves the qualified private ${alias} copy`, () => {
    const requireConsumer = createRequire(requireMobile.resolve(`${consumer}/package.json`));
    const pkg = requireConsumer(`${alias}/package.json`);
    assert.equal(pkg.name, `@opsys-ai/${alias}`);
    assert.equal(fs.realpathSync(requireConsumer.resolve(alias)), fs.realpathSync(requireMobile.resolve(alias)));
    for (const [file, sha256] of Object.entries(provenance.forks.find(f => f.alias === alias).files_sha256)) {
      const content = fs.readFileSync(path.join(root, "vendor", alias, file));
      assert.equal(crypto.createHash("sha256").update(content).digest("hex"), sha256, file);
    }
  });
}
const braces = requireMobile("braces");
const parse = requireMobile("braces/lib/parse");
for (const option of [NaN, Infinity, -Infinity, {}, new Number(1000), "1000", undefined, 1000]) {
  test(`malformed depth option cannot remove the 100-level limit (${typeof option}:${String(option)})`, () => {
    assert.throws(() => parse("{".repeat(101) + "a" + "}".repeat(101), { maxDepth: option }), /exceeds max depth/);
    for (const name of ["compile", "expand", "stringify"]) {
      let ast = { type: "text", value: "a" };
      for (let i = 0; i < 101; i++) ast = { type: "brace", nodes: [ast] };
      assert.throws(() => requireMobile(`braces/lib/${name}`)({ type: "root", nodes: [ast] }, { maxDepth: option }), /exceeds max depth/);
    }
  });
}
test("ordinary Metro patterns and exact depth boundary remain supported", () => {
  const match = requireMobile("micromatch");
  assert.deepEqual(match(["app/a.ts", "app/b.tsx", "app/c.md"], "app/*.{ts,tsx}"), ["app/a.ts", "app/b.tsx"]);
  assert.doesNotThrow(() => parse("{".repeat(100) + "a" + "}".repeat(100)));
  assert.throws(() => parse("{".repeat(101) + "a" + "}".repeat(101)), /exceeds max depth/);
  assert.deepEqual(braces.expand("{..a,b}"), ["..a", "b"]);
});
for (const name of ["compile", "expand", "stringify"]) test(`${name} rejects cyclic child nodes`, () => {
  const ast = { type: "brace", nodes: [] }; ast.nodes.push(ast);
  assert.throws(() => requireMobile(`braces/lib/${name}`)({ type: "root", nodes: [ast] }), /exceeds max depth/);
});
const forge = requireMobile("node-forge");
test("RSA rejects an extra nested DigestAlgorithm element (public upstream vector)", () => {
  const key = forge.pki.rsa.setPublicKey(new forge.jsbn.BigInteger("E932AC92252F585B3A80A4DD76A897C8B7652952FE788F6EC8DD640587A1EE5647670A8AD4C2BE0F9FA6E49C605ADF77B5174230AF7BD50E5D6D6D6D28CCF0A886A514CC72E51D209CC772A52EF419F6A953F3135929588EBE9B351FCA61CED78F346FE00DBB6306E5C2A4C6DFC3779AF85AB417371CF34D8387B9B30AE46D7A5FF5A655B8D8455F1B94AE736989D60A6F2FD5CADBFFBD504C5A756A2E6BB5CECC13BCA7503F6DF8B52ACE5C410997E98809DB4DC30D943DE4E812A47553DCE54844A78E36401D13F77DC650619FED88D8B3926E3D8E319C80C744779AC5D6ABE252896950917476ECE5E8FC27D5F053D6018D91B502C4787558A002B9283DA7", 16), new forge.jsbn.BigInteger("3"));
  const digest = forge.md.sha256.create(); digest.update("hello world!");
  const signature = forge.util.binary.hex.decode("a4ae63dd5e7712b78f4870d0f51e294df5503d4f16c5d27ae33370981fb57f0de49f50f3d6a04666774cd984cd13972db9bf8e12bd294ef0ddc916c7c86cbae63efd7b6b97885e69760c208a40f1aecc76a90d7af5145177efce1bb55807a8d05c20b1596753ba710642fc9acdde6c160232654662c77cc4466c8257a38edb49f894e8845d0fd987b857ced88f4b62505a080bd87ef700d35d392a6e8f6fde34250c50b86fae606cb551215e8f4813239b77651d5565ad453698c071d48c31e8e526fb4a37610f64b3e1fb8e5be5898e408ad08197a0947794a530b54f84485377ce4a7488ed485ce4e5e105dd89698a472f390c3b1b76bc16b73276c4d1c81d");
  assert.throws(() => key.verify(digest.digest().getBytes(), signature, undefined, { _parseAllDigestBytes: true, _skipPaddingChecks: true }), /ASN.1 object does not contain a valid RSASSA-PKCS1-v1_5 DigestInfo/);
});
test("valid SHA256 signatures and the Expo signing consumer remain supported", () => {
  const pair = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  const publicKey = forge.pki.publicKeyFromPem(pair.publicKey.export({ type: "spki", format: "pem" }));
  const content = Buffer.from("OPSYS fictitious build-tool regression");
  const signature = crypto.sign("sha256", content, pair.privateKey);
  const digest = forge.md.sha256.create(); digest.update(content.toString("binary"));
  assert.equal(publicKey.verify(digest.digest().getBytes(), signature.toString("binary")), true);
  const expo = requireMobile("@expo/code-signing-certificates");
  const forgePair = { publicKey, privateKey: forge.pki.privateKeyFromPem(pair.privateKey.export({ type: "pkcs1", format: "pem" })) };
  const certificate = forge.pki.createCertificate(); certificate.publicKey = publicKey;
  assert.equal(expo.signBufferRSASHA256AndVerify(forgePair.privateKey, certificate, content), signature.toString("base64"));
});

// GHSA-pqg4-j6r4-53mv: resolve the dependency through its actual React DevTools consumer.
const requireReactDevtools = createRequire(requireMobile.resolve("react-devtools-core/package.json"));
const shellQuote = requireReactDevtools("shell-quote");
for (const terminator of ["\n", "\r", "\u2028", "\u2029"]) {
  test(`shell-quote rejects a line terminator after a comment (${terminator.codePointAt(0)})`, () => {
    assert.throws(() => shellQuote.quote(["echo", "fictif", { comment: "commentaire fictif" }, `a${terminator}echo fictif;#`]), TypeError);
  });
}
test("shell-quote retains ordinary quoted arguments and comments", () => {
  assert.deepEqual(shellQuote.parse(shellQuote.quote(["echo", "argument fictif avec espaces"])), ["echo", "argument fictif avec espaces"]);
  assert.doesNotThrow(() => shellQuote.quote(["echo", { comment: "fictif" }, "fin fictive sans retour"]));
});

// GHSA-vcc3-ghjq-m6fr / GHSA-qr28-fpjm-wq7f : decode-uri-component <=0.5.0, chargé par query-string 7 (expo-router).
// La release corrigée 0.5.1 n'existe qu'en ESM ; query-string 7 l'appelle via require() : copie CommonJS privée.
{
  const requireQueryString = createRequire(requireMobile.resolve("query-string/package.json"));
  const decode = requireQueryString("decode-uri-component");
  test("query-string resolves the qualified private decode-uri-component copy", () => {
    const pkg = requireQueryString("decode-uri-component/package.json");
    assert.equal(pkg.name, "@opsys-ai/decode-uri-component");
    assert.equal(fs.realpathSync(requireQueryString.resolve("decode-uri-component")), fs.realpathSync(requireMobile.resolve("decode-uri-component")));
    assert.equal(typeof decode, "function");
    for (const [file, sha256] of Object.entries(provenance.forks.find(f => f.alias === "decode-uri-component").files_sha256)) {
      const content = fs.readFileSync(path.join(root, "vendor", "decode-uri-component", file));
      assert.equal(crypto.createHash("sha256").update(content).digest("hex"), sha256, file);
    }
  });
  test("decode-uri-component keeps ordinary and lenient decoding", () => {
    assert.equal(decode("st%C3%A5le"), "ståle");
    assert.equal(decode("a%20b%2"), "a b%2");
    assert.equal(decode("%E0%A4%A"), "%E0%A4%A");
    assert.equal(decode("%C2"), "�");
    assert.throws(() => decode(1), TypeError);
  });
  for (const [name, input] of [["invalid lead bytes", n => "%C0".repeat(n) + "%"], ["truncated sequences", n => "%E0%A4".repeat(n) + "%"], ["BOM pairs", n => "%FE%FF".repeat(n) + "%"]]) {
    test(`decode-uri-component stays linear on malformed input (${name})`, () => {
      const start = process.hrtime.bigint();
      assert.equal(typeof decode(input(20000)), "string");
      assert.ok(Number(process.hrtime.bigint() - start) / 1e6 < 2000);
    });
  }
  test("query-string 7 parses malformed values through the private copy", () => {
    assert.deepEqual({ ...requireMobile("query-string").parse("a=%E0%A4%A&b=%C3%A5") }, { a: "%E0%A4%A", b: "å" });
  });
}

// GHSA-mrhx-c7xc-m3w5 : zod <4.6.6, requis par @expo/cli (schémas des plugins DevTools, serveur de développement uniquement).
// @expo/cli 57 déclare zod ^3.25.76 ; l'override ^4.6.6 est qualifié sur les deux modules qui l'utilisent réellement.
{
  const cliDir = path.dirname(requireMobile.resolve("@expo/cli/package.json"));
  const requireCli = createRequire(path.join(cliDir, "package.json"));
  const server = file => require(path.join(cliDir, "build/src/start/server", file));
  const plugin = { packageName: "p", packageRoot: "/r", bannerTitle: true, cliExtensions: { description: "d", entryPoint: "e", commands: [{ name: "go", title: "Go", environments: ["cli", "mcp"], parameters: [{ name: "x", type: "number" }] }] } };
  test("@expo/cli resolves a patched zod", () => {
    const [major, minor, patch] = requireCli("zod/package.json").version.split(".").map(Number);
    assert.ok(major > 4 || (major === 4 && (minor > 6 || (minor === 6 && patch >= 6))));
  });
  test("@expo/cli DevTools plugin schemas keep their behavior under zod 4", () => {
    const { PluginSchema, DevToolsPluginOutputSchema } = server("DevToolsPlugin.schema.js");
    assert.equal(PluginSchema.safeParse(plugin).success, true);
    assert.equal(PluginSchema.safeParse({ ...plugin, packageName: "" }).success, false);
    assert.equal(PluginSchema.safeParse({ ...plugin, cliExtensions: { ...plugin.cliExtensions, commands: [] } }).success, false);
    assert.equal(DevToolsPluginOutputSchema.safeParse([{ type: "text", text: "t", level: "info" }, { type: "image", url: "https://exemple.invalid/a.png" }]).success, true);
    assert.equal(DevToolsPluginOutputSchema.safeParse([{ type: "image", url: "pas une url" }]).success, false);
  });
  test("@expo/cli MCP extension schema stays strict under zod 4", () => {
    const schema = server("createMCPDevToolsExtensionSchema.js").createMCPDevToolsExtensionSchema(plugin);
    assert.equal(schema.safeParse({ command: "go", x: 1 }).success, true);
    assert.equal(schema.safeParse({ command: "inconnue" }).success, false);
    assert.equal(schema.safeParse({ command: "go", extra: 1 }).success, false);
    assert.equal(schema.safeParse({ command: "go", x: "a" }).success, false);
  });
}
