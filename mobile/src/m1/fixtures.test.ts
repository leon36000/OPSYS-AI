import { sha256 } from "@noble/hashes/sha2.js";
import { utf8ToBytes } from "@noble/hashes/utils.js";
import { encoderHex } from "../appairage/base64url";
import { invoquerOutil } from "../protocole/client";
import { lireDigestM1, lireTransfertM1 } from "./contrat";
import { FIXTURES_M1 } from "./fixtures";

test("20 corps JSON fictifs et leurs empreintes natives sont conservés", () => {
  expect(FIXTURES_M1.fictif).toBe(true);
  expect(FIXTURES_M1.provenance.sha256).toBe("ef67584018818940c90267f3ddadf35dc17aa14c1d0b4fd5ac0c03442689e696");
  expect(Object.keys(FIXTURES_M1.reponses)).toHaveLength(20);
  for (const c of Object.values(FIXTURES_M1.reponses)) {
    expect(encoderHex(sha256(utf8ToBytes(JSON.stringify(c.corps))))).toBe(c.sha256_corps_json_utf8);
    expect(c.enveloppe).toEqual(c.corps.ok ? c.corps.result : null);
  }
});
test("captures → invoquerOutil → Response.json natif cross-realm → lecteurs, sans mutation ni acteur ajouté", async () => {
  let realmsDifferents = 0;
  for (const c of Object.values(FIXTURES_M1.reponses)) {
    const response = new Response(JSON.stringify(c.corps), { status: c.statut_http });
    const json = response.json.bind(response);
    response.json = async () => {
      const body = await json(); if (Object.getPrototypeOf(body) !== Object.prototype) realmsDifferents++; return body;
    };
    const fetchImpl = jest.fn<ReturnType<typeof fetch>, Parameters<typeof fetch>>(async () => response);
    const lu = await invoquerOutil({ fetchImpl, urlBase: "https://fictif.local", jeton: "jeton-fictif",
      requete: { tool: c.outil, args: c.args } });
    const init = fetchImpl.mock.calls[0]?.[1]; if (typeof init?.body !== "string") throw new Error("requête JSON attendue");
    expect(JSON.parse(init.body)).toEqual({ tool: c.outil, args: c.args });
    if (c.statut_http === 403) { expect(lu.ok).toBe(false); continue; }
    expect(lu.ok).toBe(true); if (!lu.ok) throw new Error(lu.echec.message);
    const r = c.outil === "m1_lire_transfert" ? lireTransfertM1(lu.result) : lireDigestM1(lu.result);
    const metier = c.enveloppe && "resultat" in c.enveloppe ? c.enveloppe.resultat : undefined;
    if (typeof metier === "string" || metier && "accepte" in metier && metier.accepte === true) expect(r.ok).toBe(true);
    else expect(r.ok).toBe(false);
  }
  expect(realmsDifferents).toBeGreaterThan(0);
});
