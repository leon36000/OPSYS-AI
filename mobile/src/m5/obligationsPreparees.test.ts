/** All examples in this file are fictive RAM contract vectors, never SQL/Cap/Gateway captures. */
const api: Record<string, (...args: any[]) => any> = (() => {
  try { return require("./obligationsPreparees"); }
  catch (error) { if (String(error).includes("Cannot find module './obligationsPreparees'")) return {}; throw error; }
})();
function fn(name: string) { expect(typeof api[name]).toBe("function"); return api[name]; }
beforeEach(() => {
  for (const name of ["construireArgumentsObligations", "construireArgumentsDeclarationObligation", "figerArgumentsDeclarationObligation",
    "lireObligationsPreparees", "lireAccuseObligationPreparee", "empreinteArgumentsObligation"]) expect(typeof api[name]).toBe("function");
});
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const H = "a".repeat(64), PREV = "b".repeat(64);
const ref = { registre: "obligations_preparees", index: 0, ligne_id: H, precedent_ligne_id: null };
const raw = { montant: "0001.00", source: " source fictive ", au: "2026-10-09", echeance: "2026-10-01", calendrier: null };
const args = { categorie: "paies", operation: "declarer", declaration: raw, revision_attendue: null, motif: "FICTIF Québec 🌧\t\r\n" };
const meta = { personne: "ADMIN-FICTIF", appareil_id: "DEVICE-FICTIF", intention_uuid: "4e1b7c25-918d-4b70-bcc5-885a2c6a7ab9", horodatage_appareil_declare: "2026-10-09T08:00:00.123456-04:00" };
function calendar(category = "paies", amount: string | null = raw.montant, source: string | null = "source fictive", au: string | null = raw.au) {
  return { id: category, nom: category === "paies" ? "Paies" : category === "das" ? "Déductions à la source (DAS)" : "Dettes déclarées",
    autorite: null, periode: { debut: null, fin: null }, echeance: category === "paies" ? raw.echeance : null,
    montant: amount, devise: amount === null ? null : "CAD", source_montant: { description: source, au },
    source_echeance: { description: null, consultee_le: null, applicable_du: null, applicable_jusqu_au: null },
    annee: null, version: null, montant_utilisable: amount, echeance_statut: category === "paies" ? "PASSEE_A_VERIFIER" : "NON_DECLAREE",
    statut: "INCOMPLETE", manque: [{ code: "REJ-CALENDRIER-PERIODE-SOURCE-ABSENTE", detail: "FICTIF : période inconnue" }] };
}
function row(category = "paies") {
  return category === "paies" ? { categorie: category, etat_declaration: "DECLAREE", declaration: clone(raw), reference: clone(ref), revision_precedente: null,
    auteur: { personne: meta.personne, role: "admin", source: "appareil" }, intention: { appareil_id: meta.appareil_id, intention_uuid: meta.intention_uuid, empreinte_arguments: H },
    enregistree_le: "2026-10-09T12:00:01.123456+00:00", horodatage_appareil_declare: meta.horodatage_appareil_declare, calendrier_preparatoire: calendar() } :
    { categorie: category, etat_declaration: "ABSENTE", declaration: null, reference: null, revision_precedente: null, auteur: null, intention: null,
      enregistree_le: null, horodatage_appareil_declare: null, calendrier_preparatoire: calendar(category, null, null, null) };
}
const readArgs = { aujourd_hui: "2026-10-09", decalage: 0, limite: 8 };
function page() { return { type: "DECLARATIONS_PREPARATOIRES_OBLIGATIONS", version_schema: 1,
  source_canonique: "REGISTRE_PREPARATOIRE_DURABLE", registre: "obligations_preparees", ...readArgs, total: 3, decalage_suivant: null,
  obligations: [row(), row("das"), row("dettes")], mention: "Analyse préparatoire IA", couverture: {
    categories: "paies_das_dettes_seulement", montants: "declares_non_attestes", source: "registre_preparatoire_sans_activation_YAML_cash_CFO",
    echeances: "a_verifier_sans_etat_paiement", pages: "courantes_non_figees", plafond_lignes: 10000 } }; }
const envelope = (p: unknown) => ({ ok: true, resultat: { accepte: true, resultat: p } });
function ack(a = args, m = meta) {
  const r: any = row(); const { calendrier_preparatoire: _calendar, ...persisted } = r;
  persisted.intention.empreinte_arguments = fn("empreinteArgumentsObligation")(a);
  persisted.intention.appareil_id = m.appareil_id; persisted.intention.intention_uuid = m.intention_uuid;
  persisted.horodatage_appareil_declare = m.horodatage_appareil_declare; persisted.auteur.personne = m.personne;
  return { ok: true, rejoue: false, resultat: { accepte: true, version_schema: 1, resultat: persisted, registre: "obligations_preparees" } };
}
test("builders preserve exact declared text and do not choose a business date or money", () => {
  expect(fn("construireArgumentsObligations")("2026-10-09")).toEqual({ ...readArgs, limite: 1 });
  expect(fn("construireArgumentsDeclarationObligation")("paies", "declarer", raw, null, args.motif)).toEqual(args);
  expect(fn("construireArgumentsDeclarationObligation")("das", "declarer", { ...raw, montant: null, source: null, au: null }, null, "").declaration.montant).toBeNull();
});
test.each(["2026-02-29", "2026-2-01", "2026-10-09T00:00:00Z", "0000-01-01", ""])("civil date %s is refused without repair", date => {
  expect(() => fn("construireArgumentsObligations")(date)).toThrow();
});
test.each([0, 9, 1.5, true, "8"])("page limit %s is strictly refused", n => {
  expect(() => fn("construireArgumentsObligations")("2026-10-09", 0, n)).toThrow();
});
test.each(["-1.00", "1e2", "+1", "1.001", "NaN", "Infinity", 0, true])("money %s is never converted or rounded", amount => {
  expect(() => fn("construireArgumentsDeclarationObligation")("paies", "declarer", { ...raw, montant: amount }, null, "")).toThrow();
});
test("absence and retirement stay explicit; declared zero keeps its source and date", () => {
  const a = fn("construireArgumentsDeclarationObligation")("paies", "declarer", { ...raw, montant: "0.00" }, null, "");
  expect(a.declaration).toEqual({ ...raw, montant: "0.00" });
  expect(fn("construireArgumentsDeclarationObligation")("paies", "retirer", null, ref, "FICTIF correction").declaration).toBeNull();
  expect(() => fn("construireArgumentsDeclarationObligation")("paies", "retirer", raw, ref, "FICTIF")).toThrow();
});
test("all maps closed and source snapshots getter-safe", () => {
  const getter = jest.fn(() => "secret-fictif"); const v = { ...raw };
  Object.defineProperty(v, "source", { get: getter, enumerable: true });
  expect(fn("figerArgumentsDeclarationObligation")({ ...args, declaration: v })).toBeNull(); expect(getter).not.toHaveBeenCalled();
  for (const bad of [{ ...args, role: "admin" }, { ...args, declaration: { ...raw, validee_par_cpa: true } }, { ...args, categorie: "reserves" },
    { ...args, revision_attendue: { ...ref, index: true } }]) expect(fn("figerArgumentsDeclarationObligation")(bad)).toBeNull();
});
test("current page preserves raw source independently of its normalized calendar projection", () => {
  const p = page(), lu = fn("lireObligationsPreparees")(envelope(p), readArgs);
  expect(lu.ok).toBe(true); expect(lu.value.obligations[0].declaration.source).toBe(" source fictive ");
  expect(lu.value.obligations[0].calendrier_preparatoire.source_montant.description).toBe("source fictive");
  expect(lu.value.obligations[0].calendrier_preparatoire.statut).toBe("INCOMPLETE");
  expect(lu.value.obligations[0].calendrier_preparatoire.montant_utilisable).toBe(raw.montant);
  expect(lu.value.obligations[1].declaration).toBeNull();
});
test("page replacement binds date/offset/limit and exact category order, including beyond total", () => {
  const p: any = page(); p.decalage = 1; p.limite = 1; p.decalage_suivant = 2; p.obligations = [row("das")];
  expect(fn("lireObligationsPreparees")(envelope(p), { ...readArgs, decalage: 1, limite: 1 }).ok).toBe(true);
  expect(fn("lireObligationsPreparees")(envelope(p), readArgs).ok).toBe(false);
  p.decalage = 10000; p.decalage_suivant = null; p.obligations = [];
  expect(fn("lireObligationsPreparees")(envelope(p), { ...readArgs, decalage: 10000, limite: 1 }).ok).toBe(true);
});
test.each(["foreign_category", "extra", "normalization", "missing_as_zero", "wrong_head", "rejoue_T0", "missing_mention"])("current DTO rejects %s without partial display", mode => {
  const p: any = page(); let e: any = envelope(p);
  if (mode === "foreign_category") p.obligations.reverse();
  if (mode === "extra") p.bank_attested = true;
  if (mode === "normalization") p.obligations[0].calendrier_preparatoire.source_montant.description = p.obligations[0].declaration.source;
  if (mode === "missing_as_zero") p.obligations[1].declaration = { ...raw, montant: "0.00" };
  if (mode === "wrong_head") p.registre = "principal";
  if (mode === "rejoue_T0") e = { ...e, rejoue: false };
  if (mode === "missing_mention") delete p.mention;
  expect(fn("lireObligationsPreparees")(e, readArgs).ok).toBe(false);
});
test("ACK contains only nine persisted fields, never a calendar with an invented today", () => {
  const a = ack(); const lu = fn("lireAccuseObligationPreparee")(a, args, meta);
  expect(lu.ok).toBe(true); expect(lu.value.declaration).toEqual(raw);
  expect(Object.keys(lu.value)).toHaveLength(9);
  const wrong: any = clone(a); wrong.resultat.resultat.calendrier_preparatoire = calendar();
  expect(fn("lireAccuseObligationPreparee")(wrong, args, meta).ok).toBe(false);
});
test.each(["UUID", "device", "person", "hash", "hour_microsecond", "target", "revision", "prefix"])("own ACK rejects altered %s", mode => {
  const a: any = ack(); const r = a.resultat.resultat;
  if (mode === "UUID") r.intention.intention_uuid = "f6106514-51d2-4c1a-964f-f7a080a290f1";
  if (mode === "device") r.intention.appareil_id += "-FOREIGN";
  if (mode === "person") r.auteur.personne += "-FOREIGN";
  if (mode === "hash") r.intention.empreinte_arguments = PREV;
  if (mode === "hour_microsecond") r.horodatage_appareil_declare = meta.horodatage_appareil_declare.replace("123456", "123457");
  if (mode === "target") r.categorie = "das";
  if (mode === "revision") r.revision_precedente = ref;
  if (mode === "prefix") a.resultat.registre = "principal";
  expect(fn("lireAccuseObligationPreparee")(a, args, meta).ok).toBe(false);
});
test("own replay is valid independently of newer current revision or category append", () => {
  const a = ack(); a.rejoue = true;
  expect(fn("lireAccuseObligationPreparee")(a, args, meta).ok).toBe(true);
});

/** Byte-exact SQL façade captures: injected fictive identity/Meta, never Cap or HTTP. */
const sql = require("./fixturesObligationsPrepareesSQL.json");
const sqlCases: [string, any][] = sql.captures.filter((v: any) => !v.proof_only).map((c: any) => [c.name, c]);
test("the real SQL container is copied byte-exact and every response keeps its original JSON bytes", () => {
  const { createHash } = require("node:crypto"), { readFileSync } = require("node:fs");
  expect(createHash("sha256").update(readFileSync(require.resolve("./fixturesObligationsPrepareesSQL.json"))).digest("hex"))
    .toBe("9ba5924635bac3520956ff633e7bed502f4f40b926589e9fdf94b93b0692a5be");
  for (const c of sql.captures.filter((v: any) => !v.proof_only)) {
    expect(createHash("sha256").update(c.body_utf8, "utf8").digest("hex")).toBe(c.body_sha256);
    expect(JSON.parse(c.body_utf8)).toEqual(c.enveloppe);
  }
  expect(sql.captures.filter((v: any) => v.proof_only)).toHaveLength(1);
});
test.each(sqlCases)("real SQL %s is admitted only under its exact request and persisted identity", (_name, c) => {
  const a = c.request.arguments;
  if (c.request.outil === "m5_lire_obligations_preparees_appareil") {
    expect(fn("lireObligationsPreparees")(c.enveloppe, a).ok).toBe(true);
  } else if (c.enveloppe.resultat.accepte === true) {
    const r = c.enveloppe.resultat.resultat;
    const m = { personne: r.auteur.personne, appareil_id: r.intention.appareil_id, intention_uuid: r.intention.intention_uuid, horodatage_appareil_declare: r.horodatage_appareil_declare };
    expect(fn("lireAccuseObligationPreparee")(c.enveloppe, a, m).ok).toBe(true);
    expect(fn("lireAccuseObligationPreparee")(c.enveloppe, a, { ...m, intention_uuid: m.intention_uuid + "-foreign" }).ok).toBe(false);
  } else expect(fn("lireAccuseObligationPreparee")(c.enveloppe, a, meta).ok).toBe(false);
});

test("Python strip emptiness keeps FEFF but rejects whitespace-only source", () => {
 expect(fn("construireArgumentsDeclarationObligation")("paies","declarer",{...raw,source:"\uFEFF"},null,"").declaration.source).toBe("\uFEFF");
 expect(()=>fn("construireArgumentsDeclarationObligation")("paies","declarer",{...raw,source:"\u001c"},null,"")).toThrow();
});

/** RAM vectors from actual Python encoder; no SQL/Cap effect is asserted for variants.
 * Q python-args-vectors-r1.json SHA a137828c24b336c2165b2639b2b34fd54c4b4266e6337fd9d84a784a38d756fd. */
const pythonVectors = [
  {
    "name": "original SQL args / original",
    "arguments": {
      "categorie": "paies",
      "operation": "declarer",
      "declaration": {
        "montant": null,
        "source": null,
        "au": null,
        "echeance": null,
        "calendrier": null
      },
      "revision_attendue": null,
      "motif": "FICTIF é 😀\t\r\n"
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":null,\"calendrier\":null,\"echeance\":null,\"montant\":null,\"source\":null},\"motif\":\"FICTIF é 😀\\t\\r\\n\",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "f21fc46294e67e8eaadc3a88f59de966998861ab34c80d0c922ac63a8ca60464"
  },
  {
    "name": "original SQL args / permuted deep",
    "arguments": {
      "motif": "FICTIF é 😀\t\r\n",
      "revision_attendue": null,
      "declaration": {
        "calendrier": null,
        "echeance": null,
        "au": null,
        "source": null,
        "montant": null
      },
      "operation": "declarer",
      "categorie": "paies"
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":null,\"calendrier\":null,\"echeance\":null,\"montant\":null,\"source\":null},\"motif\":\"FICTIF é 😀\\t\\r\\n\",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "f21fc46294e67e8eaadc3a88f59de966998861ab34c80d0c922ac63a8ca60464"
  },
  {
    "name": "RAM unicode controls / original",
    "arguments": {
      "categorie": "paies",
      "operation": "declarer",
      "declaration": {
        "montant": null,
        "source": null,
        "au": null,
        "echeance": null,
        "calendrier": null
      },
      "revision_attendue": null,
      "motif": "FICTIF Québec 😀\t\r\n "
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":null,\"calendrier\":null,\"echeance\":null,\"montant\":null,\"source\":null},\"motif\":\"FICTIF Québec 😀\\t\\r\\n \",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "954d0d350d4a821373eaaa04bb8f7d7c3b0e214358298b42e5281084f5ff0be3"
  },
  {
    "name": "RAM unicode controls / permuted deep",
    "arguments": {
      "motif": "FICTIF Québec 😀\t\r\n ",
      "revision_attendue": null,
      "declaration": {
        "calendrier": null,
        "echeance": null,
        "au": null,
        "source": null,
        "montant": null
      },
      "operation": "declarer",
      "categorie": "paies"
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":null,\"calendrier\":null,\"echeance\":null,\"montant\":null,\"source\":null},\"motif\":\"FICTIF Québec 😀\\t\\r\\n \",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "954d0d350d4a821373eaaa04bb8f7d7c3b0e214358298b42e5281084f5ff0be3"
  },
  {
    "name": "RAM 500 nonBMP / original",
    "arguments": {
      "categorie": "paies",
      "operation": "declarer",
      "declaration": {
        "montant": null,
        "source": null,
        "au": null,
        "echeance": null,
        "calendrier": null
      },
      "revision_attendue": null,
      "motif": "😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀"
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":null,\"calendrier\":null,\"echeance\":null,\"montant\":null,\"source\":null},\"motif\":\"😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀\",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "b78f4e23b716f8fb878917e293493dc8def49d2366bdac116adce35e38b22755"
  },
  {
    "name": "RAM 500 nonBMP / permuted deep",
    "arguments": {
      "motif": "😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀",
      "revision_attendue": null,
      "declaration": {
        "calendrier": null,
        "echeance": null,
        "au": null,
        "source": null,
        "montant": null
      },
      "operation": "declarer",
      "categorie": "paies"
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":null,\"calendrier\":null,\"echeance\":null,\"montant\":null,\"source\":null},\"motif\":\"😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀\",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "b78f4e23b716f8fb878917e293493dc8def49d2366bdac116adce35e38b22755"
  },
  {
    "name": "RAM deep calendar / original",
    "arguments": {
      "categorie": "paies",
      "operation": "declarer",
      "declaration": {
        "montant": "0001.00",
        "source": " source FICTIVE ",
        "au": "2026-10-09",
        "echeance": "2026-10-01",
        "calendrier": {
          "autorite": " autorité FICTIVE ",
          "periode_debut": "2026-01-01",
          "periode_fin": "2026-12-31",
          "echeance_source": " source FICTIVE ",
          "source_consultee_le": "2026-10-09",
          "source_applicable_du": "2026-01-01",
          "source_applicable_jusqu_au": "2026-12-31",
          "annee": 2026,
          "version": " FICTIF v1 "
        }
      },
      "revision_attendue": null,
      "motif": "FICTIF é 😀\t\r\n"
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":\"2026-10-09\",\"calendrier\":{\"annee\":2026,\"autorite\":\" autorité FICTIVE \",\"echeance_source\":\" source FICTIVE \",\"periode_debut\":\"2026-01-01\",\"periode_fin\":\"2026-12-31\",\"source_applicable_du\":\"2026-01-01\",\"source_applicable_jusqu_au\":\"2026-12-31\",\"source_consultee_le\":\"2026-10-09\",\"version\":\" FICTIF v1 \"},\"echeance\":\"2026-10-01\",\"montant\":\"0001.00\",\"source\":\" source FICTIVE \"},\"motif\":\"FICTIF é 😀\\t\\r\\n\",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "1f27f00b1e8cb47e6041d408777068ee273d58bbf95e7c6543f4929980b9ee6a"
  },
  {
    "name": "RAM deep calendar / permuted deep",
    "arguments": {
      "motif": "FICTIF é 😀\t\r\n",
      "revision_attendue": null,
      "declaration": {
        "calendrier": {
          "version": " FICTIF v1 ",
          "annee": 2026,
          "source_applicable_jusqu_au": "2026-12-31",
          "source_applicable_du": "2026-01-01",
          "source_consultee_le": "2026-10-09",
          "echeance_source": " source FICTIVE ",
          "periode_fin": "2026-12-31",
          "periode_debut": "2026-01-01",
          "autorite": " autorité FICTIVE "
        },
        "echeance": "2026-10-01",
        "au": "2026-10-09",
        "source": " source FICTIVE ",
        "montant": "0001.00"
      },
      "operation": "declarer",
      "categorie": "paies"
    },
    "canonical_utf8": "{\"categorie\":\"paies\",\"declaration\":{\"au\":\"2026-10-09\",\"calendrier\":{\"annee\":2026,\"autorite\":\" autorité FICTIVE \",\"echeance_source\":\" source FICTIVE \",\"periode_debut\":\"2026-01-01\",\"periode_fin\":\"2026-12-31\",\"source_applicable_du\":\"2026-01-01\",\"source_applicable_jusqu_au\":\"2026-12-31\",\"source_consultee_le\":\"2026-10-09\",\"version\":\" FICTIF v1 \"},\"echeance\":\"2026-10-01\",\"montant\":\"0001.00\",\"source\":\" source FICTIVE \"},\"motif\":\"FICTIF é 😀\\t\\r\\n\",\"operation\":\"declarer\",\"revision_attendue\":null}",
    "sha256": "1f27f00b1e8cb47e6041d408777068ee273d58bbf95e7c6543f4929980b9ee6a"
  }
] as const;
test.each(pythonVectors)("Python canonical args SHA matches $name verbatim",v=> {
 expect(fn("empreinteArgumentsObligation")(v.arguments)).toBe(v.sha256);
});

/** Actual Cap/SQLite source, injected fictive identity/Meta, no HTTP/Gateway/token authentication. */
const cap = require("./fixturesObligationsPrepareesCapSQL.json");
const capCases: [string, any][] = cap.captures.map((c: any) => [c.name, c]);
test("all 20 Cap original UTF8 bodies and fixture bytes remain exact",()=> {
 const { createHash }=require("node:crypto"),{readFileSync}=require("node:fs");
 expect(createHash("sha256").update(readFileSync(require.resolve("./fixturesObligationsPrepareesCapSQL.json"))).digest("hex")).toBe("d95636b81188f9f829e8c45fd020675e010d63c3d7bf61c72e4d2bd55e6fba45");expect(cap.captures).toHaveLength(20);
 for(const c of cap.captures){expect(createHash("sha256").update(c.body_utf8,"utf8").digest("hex")).toBe(c.body_sha256);expect(JSON.parse(c.body_utf8)).toEqual(c.enveloppe);expect(Object.keys(c.tables_before)).toHaveLength(49);expect(Object.keys(c.tables_after)).toHaveLength(49);}
});
test.each(capCases)("real Cap %s binds its request, original actor and exact device hour",(_name,c)=> {
 const a=c.request.arguments,e=c.enveloppe,accepted=e.ok===true&&e.resultat?.accepte===true;
 if(c.request.outil==="m5_lire_obligations_preparees_appareil")expect(fn("lireObligationsPreparees")(e,a).ok).toBe(accepted);
 else {const m=c.request.meta,own={personne:c.request.identite_injectee.personne,appareil_id:m.appareil,intention_uuid:m.cle,horodatage_appareil_declare:m.horodatage_appareil};
 expect(fn("lireAccuseObligationPreparee")(e,a,own).ok).toBe(accepted);
 if(accepted)for(const k of ["personne","appareil_id","intention_uuid","horodatage_appareil_declare"] as const)expect(fn("lireAccuseObligationPreparee")(e,a,{...own,[k]:own[k]+"-foreign"}).ok).toBe(false);}
});

/** Actual Root Cap/SQLite incomplete calendar; actor/Meta injected, no Gateway or fiscal validation. */
const calendarSQL = require("./fixturesObligationsPrepareesCalendarSQL.json");
const calendarAck = calendarSQL.captures.find((v:any)=>v.name==="declaration-annee-incoherente");
const calendarRead = calendarSQL.captures.find((v:any)=>v.name==="lecture-annee-incoherente");
test("calendar incomplete capture remains byte-exact with both original UTF8 bodies",()=> {
 const {createHash}=require("node:crypto"),{readFileSync}=require("node:fs");expect(createHash("sha256").update(readFileSync(require.resolve("./fixturesObligationsPrepareesCalendarSQL.json"))).digest("hex")).toBe("0cfbccc553bc36ed6bfb44bf0f4a04ef446228569d45d73b5ac84960a74e5f7a");
 for(const c of calendarSQL.captures){expect(createHash("sha256").update(c.body_utf8,"utf8").digest("hex")).toBe(c.body_sha256);expect(JSON.parse(c.body_utf8)).toEqual(c.enveloppe);expect(c.tables_count).toBe(49);}
});
test("builder preserves the declared year instead of certifying or rewriting its consistency",()=> {
 const a=calendarAck.request.arguments;expect(fn("construireArgumentsDeclarationObligation")(a.categorie,a.operation,a.declaration,a.revision_attendue,a.motif)).toEqual(a);
});
test("OwnACK admits actual persisted inconsistent-year declaration with exact original Meta",()=> {
 const c=calendarAck,m=c.request.meta;const own={personne:c.request.identite_injectee.personne,appareil_id:m.appareil,intention_uuid:m.cle,horodatage_appareil_declare:m.horodatage_appareil};
 const r=fn("lireAccuseObligationPreparee")(c.enveloppe,c.request.arguments,own);expect(r.ok).toBe(true);expect(r.value.declaration.calendrier.annee).toBe(2025);expect(r.value.declaration.calendrier.periode_fin).toBe("2026-10-31");
});
test("read retains INCOMPLETE and the server year/version missing reason, not DOCUMENTEE_A_VALIDER",()=> {
 const c=calendarRead,r=fn("lireObligationsPreparees")(c.enveloppe,c.request.arguments);expect(r.ok).toBe(true);const row=r.value.obligations[0];
 expect(row.declaration.calendrier.annee).toBe(2025);expect(row.calendrier_preparatoire.annee).toBe(2025);expect(row.calendrier_preparatoire.statut).toBe("INCOMPLETE");
 expect(row.calendrier_preparatoire.manque.map((v:any)=>v.code)).toEqual(["REJ-CALENDRIER-PAIES-ANNEE-VERSION-INVALIDE"]);
});

test("default read size is one while an explicit eight stays exactly eight",()=> {
 expect(fn("construireArgumentsObligations")("2026-10-09")).toEqual({aujourd_hui:"2026-10-09",decalage:0,limite:1});
 expect(fn("construireArgumentsObligations")("2026-10-09",0,8)).toEqual({aujourd_hui:"2026-10-09",decalage:0,limite:8});
});
