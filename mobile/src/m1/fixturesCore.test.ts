import { FIXTURES_CORE_M1 } from "./fixturesCore";
import { invoquerOutil } from "../protocole/client";
import { lireDigestM1, lireTransfertM1 } from "./contrat";
test.each(FIXTURES_CORE_M1.captures)("capture Gateway réelle $phase → client et lecteur M1", async capture => {
  expect(FIXTURES_CORE_M1.fictif).toBe(true); expect(capture.all_tables_unchanged_native).toBe(true);
  const fetchImpl = jest.fn(async (_url: Parameters<typeof fetch>[0], init?: RequestInit) => {
    expect(JSON.parse(String(init?.body))).toEqual(capture.request);
    return new Response(JSON.stringify(capture.response), { status: capture.status });
  });
  const lu = await invoquerOutil({ urlBase: "https://gateway.fictif.local", jeton: "jeton-fictif", requete: capture.request, fetchImpl });
  if (capture.status === 403) {
    expect(lu.ok).toBe(false); return;
  }
  if (!lu.ok) throw new Error("Capture HTTP200 attendue comme reponse native");
  const args = capture.request.args as Readonly<Record<string, unknown>>;
  const r = capture.request.tool === "m1_produire_digest" ? lireDigestM1(lu.result, args.date_reference as string) :
    lireTransfertM1(lu.result, args.transfert_id as string);
  if (["digest_direct", "transfert_couple_plainte", "transfert_couple_urgence", "transfert_couple_rappel", "relecture_apres_backend_reboot"].includes(capture.phase)) {
    expect(r.ok).toBe(true);
    if (r.ok && typeof r.value !== "string") expect(r.value.transfert_id).toBe(args.transfert_id);
  } else {
    const code = capture.phase.startsWith("date_invalide_") ? "REJ-DIGEST-DATE-INVALIDE" :
      capture.phase === "transfert_inconnu" ? "REJ-TRANSFERT-INCONNU" :
      capture.phase === "schema_source_console_refuse" ? "arguments_invalides" : "REJ-IDENTITE-APPAREIL-INVALIDE";
    expect(r).toMatchObject({ ok: false, code });
  }
  expect(fetchImpl).toHaveBeenCalledTimes(1);
});
