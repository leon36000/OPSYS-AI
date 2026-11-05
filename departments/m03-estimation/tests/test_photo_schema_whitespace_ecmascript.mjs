import assert from "node:assert/strict";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const { pattern, cases } = JSON.parse(input);

for (const flags of ["", "u"]) {
  const expression = new RegExp(pattern, flags);
  for (const { value, expected } of cases) {
    assert.equal(expression.test(value), expected, `flags=${flags}, codepoint=${[...value].map(c => `U+${c.codePointAt(0).toString(16).toUpperCase()}`).join(" ")}`);
  }
}
