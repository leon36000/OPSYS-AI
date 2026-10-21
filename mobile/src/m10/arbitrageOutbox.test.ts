import { creerMutationArbitrageMemoire, construireArgumentsArbitrageMemoire, interpreterArbitrageMemoire, arbitragesMemoireEnFile } from "./arbitrageOutbox";
import { FIXTURES_M10 } from "./fixtures";
const natif = FIXTURES_M10.reponses.arbitrage_accepte.enveloppe;
const ack = natif.resultat.resultat;
const horloge = { maintenant: new Date("2026-09-16T15:10:00Z"), decalageMinutesUTC: -240 };
const mutation = () => ({ ...creerMutationArbitrageMemoire(ack.revision_ligne_id, "distincts_confirmes", () => "uuid-fictif-1", horloge), proprietaire: ack.par });

test("ACK natif11 lié à l’intention persistée, vecteur Python cfc951 et replay", () => {
  expect(ack.ligne_id).toBe("cfc951d4faeda9133bf6ade9b3020f544c428d09ee6ce378090708745c1f82e7");
  expect(interpreterArbitrageMemoire(natif, mutation())).toEqual({ accepte: true, resume: ack });
  expect(interpreterArbitrageMemoire(FIXTURES_M10.reponses.arbitrage_rejoue.enveloppe, mutation())).toEqual({ accepte: true, resume: ack });
});

test("l’intention soumise porte uniquement les trois arguments et le timestamp local stable", () => {
  const m = mutation();
  expect(m).toMatchObject({ type: "memory_revision_arbitration", statut: "en_attente", sequence: null,
    chantierId: `memoire_revision:${ack.revision_ligne_id}`, payload: {
      revision_ligne_id: ack.revision_ligne_id, statut: "distincts_confirmes", horodatage: "2026-09-16T11:10:00-04:00" } });
  expect(construireArgumentsArbitrageMemoire(m)).toEqual(m.payload);
  expect(arbitragesMemoireEnFile([m])).toEqual([{ id: m.id, revisionId: ack.revision_ligne_id,
    statut: "en_attente", personne: ack.par, choix: "distincts_confirmes" }]);
});

test.each([{ horodatage: "2026-09-16T15:11:00+00:00" }, { ligne_id: "a".repeat(64) }])(
  "un ACK altéré %p ne confirme pas l’intention malgré cible/statut/personne corrects", patch => {
    expect(interpreterArbitrageMemoire({ ok: true, resultat: { accepte: true, resultat: { ...ack, ...patch } } }, mutation()))
      .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  },
);

test.each([undefined, {}, { ok: true, resultat: ack }, { ok: true, resultat: { accepte: true, resultat: { ...ack, role: "nathan_owner" } } },
  { ok: true, resultat: { accepte: true, resultat: { ...ack, par: "autre.personne" } } },
  { ok: true, resultat: { accepte: true, resultat: { ...ack, source_decision: "approbation" } } },
  { ok: true, resultat: { accepte: true, resultat: { ...ack, type_entree: "decision_enregistree" } } },
  { ok: true, resultat: { accepte: true, resultat: { ...ack, ligne_id_a: ack.revision_ligne_id } } },
  { ok: true, resultat: { accepte: true, resultat: { ...ack, horodatage: "2026-02-30T00:00:00Z" } } },
])("ACK sans autorité/binding natif %p garde l’intention", brut => {
  expect(interpreterArbitrageMemoire(brut, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});

test("legacy8 sans acteur, propriété étrangère, getter et propriétaire absent restent invalides", () => {
  const { par: _par, role: _role, source_decision: _source, ...legacy } = ack;
  expect(interpreterArbitrageMemoire({ ok: true, resultat: { accepte: true, resultat: legacy } }, mutation()).accepte).toBe(false);
  expect(interpreterArbitrageMemoire(natif).accepte).toBe(false);
  expect(interpreterArbitrageMemoire(natif, { ...mutation(), proprietaire: null }).accepte).toBe(false);
  expect(interpreterArbitrageMemoire({ ok: true, resultat: { accepte: true, resultat: { ...ack, motif: "interdit" } } }, mutation()).accepte).toBe(false);
  const getter = jest.fn(() => ack);
  const resultat = Object.defineProperty({ accepte: true }, "resultat", { get: getter, enumerable: true });
  expect(interpreterArbitrageMemoire({ ok: true, resultat }, mutation()).accepte).toBe(false);
  expect(getter).not.toHaveBeenCalled();
});

test("payload corrompu ne fait pas deviner les arguments et projection garde toute ligne", () => {
  const m = mutation();
  for (const patch of [{ payload: { ...m.payload, par: "acteur.client" } }, { chantierId: "memoire_revision:autre" },
    { payload: { ...m.payload, horodatage: "2026-09-17T11:10:00-04:00" } }, { payload: {} }]) {
    expect(construireArgumentsArbitrageMemoire({ ...m, ...patch })).toBeNull();
  }
  const rows = [m, { ...m, id: "illisible", chantierId: "", payload: {}, proprietaire: null },
    { ...m, id: "terminale", statut: "envoyee" as const }];
  expect(arbitragesMemoireEnFile(rows)).toHaveLength(3);
  expect(arbitragesMemoireEnFile(rows)[1]).toEqual({ id: "illisible", revisionId: null, statut: "en_attente", personne: null, choix: null });
});

test.each(["", "a", "A".repeat(64)])("revision invalide %s refuse avant UUID", revisionId => {
  const id = jest.fn(() => "uuid");
  expect(() => creerMutationArbitrageMemoire(revisionId, "distincts_confirmes", id, horloge)).toThrow();
  expect(id).not.toHaveBeenCalled();
});

test("clock invalide refuse avant UUID, ID vide refusé", () => {
  const id = jest.fn(() => "uuid");
  expect(() => creerMutationArbitrageMemoire(ack.revision_ligne_id, "en_attente", id, { ...horloge, maintenant: new Date(NaN) })).toThrow();
  expect(id).not.toHaveBeenCalled();
  expect(() => creerMutationArbitrageMemoire(ack.revision_ligne_id, "en_attente", () => "", horloge)).toThrow();
});

test.each(["REJ-REVISION-SIGNALEMENT-INTROUVABLE", "REJ-REVISION-STATUT-INCONNU", "REJ-HUMAIN-REQUIS", "REJ-IDENTITE-APPAREIL-INVALIDE"])(
  "refus nominal natif string ou structuré %s préservé", code => {
    expect(interpreterArbitrageMemoire({ ok: true, resultat: { accepte: false, verdict: code } }, mutation()))
      .toEqual({ accepte: false, verdict: { code, detail: "" } });
    expect(interpreterArbitrageMemoire({ ok: true, resultat: { accepte: false, verdict: { code, detail: "Détail natif fictif" } } }, mutation()))
      .toEqual({ accepte: false, verdict: { code, detail: "Détail natif fictif" } });
  },
);

test.each([{ ok: false, erreur: "inconnue" }, { ok: true, resultat: { accepte: false, verdict: "inconnu" } },
  { ok: true, resultat: { accepte: false, verdict: { code: "REJ-HUMAIN-REQUIS", detail: 42 } } },
  { ...natif, tronque: true }])("réponse inconnue/corrompue %p n’est pas un refus terminal", brut => {
  expect(interpreterArbitrageMemoire(brut, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});

test("arguments_invalides natif avec liste de détails préservée sans accéder aux getters", () => {
  expect(interpreterArbitrageMemoire({ ok: false, erreur: "arguments_invalides", details: ["Champ interdit", "Statut inconnu"] }, mutation()))
    .toEqual({ accepte: false, verdict: { code: "arguments_invalides", detail: "Champ interdit ; Statut inconnu" } });
});

test("une cible hash terminée par newline n’est pas un hash canonique et ne crée aucun UUID", () => {
  const id = jest.fn(() => "uuid");
  expect(() => creerMutationArbitrageMemoire(`${ack.revision_ligne_id}\n`, "distincts_confirmes", id, horloge)).toThrow();
  expect(id).not.toHaveBeenCalled();
});

test("les détails natifs corrompus/sparse/getter ne deviennent pas un refus connu", () => {
  const getter = jest.fn(() => "détail deviné");
  const details = Object.defineProperty(new Array(1), "0", { get: getter, enumerable: true });
  for (const mauvaiseListe of [details, new Array(1), [42]]) {
    expect(interpreterArbitrageMemoire({ ok: false, erreur: "arguments_invalides", details: mauvaiseListe }, mutation()))
      .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  }
  expect(getter).not.toHaveBeenCalled();
});
