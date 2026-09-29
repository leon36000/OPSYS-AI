import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { ecrireCacheSection, lireCacheSection } from "./cache";

const T0 = "2026-09-29T18:00:00.000Z";

/** Un dépôt qui dit sous quelles clés il a écrit. */
function depotEspion(): DepotCleValeur & { readonly cles: string[] } {
  const interne = new DepotCleValeurMemoire();
  const cles: string[] = [];
  return {
    cles,
    lire: (cle) => interne.lire(cle),
    ecrire: async (cle, valeur) => {
      cles.push(cle);
      await interne.ecrire(cle, valeur);
    },
  };
}

describe("cache de section du profil admin", () => {
  test("écrit puis relu : la même enveloppe, la même date de lecture", async () => {
    const depot = new DepotCleValeurMemoire();
    const enveloppe = { ok: true, resultat: { solde: "20000.00", liste: [1, 2, 3] } };

    await ecrireCacheSection(depot, "nathan", "tresorerie", enveloppe, T0);

    expect(await lireCacheSection(depot, "nathan", "tresorerie")).toEqual({ resultat: enveloppe, misAJourLe: T0 });
  });

  test("la clé porte la personne, le nom et une version : `admin:<personne>:<nom>_v1`", async () => {
    const depot = depotEspion();
    await ecrireCacheSection(depot, "nathan", "vue_executive", { ok: true }, T0);
    await ecrireCacheSection(depot, "nathan", "interventions:planifiee", { ok: true }, T0);
    expect(depot.cles).toEqual(["admin:nathan:vue_executive_v1", "admin:nathan:interventions:planifiee_v1"]);
  });

  test("UNE CLÉ PAR PERSONNE : ce que Nathan a gardé n'est jamais relu pour une autre personne du même téléphone", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "tresorerie", { ok: true, resultat: { solde: "20000.00" } }, T0);

    expect(await lireCacheSection(depot, "sophie", "tresorerie")).toBeNull();
    expect(await lireCacheSection(depot, "nathan", "tresorerie")).not.toBeNull();
  });

  test("une personne dont l'identifiant contient « : » ne partage la clé de personne d'autre", async () => {
    const depot = depotEspion();
    await ecrireCacheSection(depot, "a:b", "tresorerie", { ok: true, resultat: 1 }, T0);
    await ecrireCacheSection(depot, "a", "b:tresorerie", { ok: true, resultat: 2 }, T0);

    expect(depot.cles[0]).toBe("admin:a%3Ab:tresorerie_v1");
    expect(depot.cles[0]).not.toBe(depot.cles[1]);
    expect((await lireCacheSection(depot, "a:b", "tresorerie"))?.resultat).toEqual({ ok: true, resultat: 1 });
    expect((await lireCacheSection(depot, "a", "b:tresorerie"))?.resultat).toEqual({ ok: true, resultat: 2 });
    expect(await lireCacheSection(depot, "a", "tresorerie")).toBeNull();
  });

  test("une section par nom : le cache d'une section n'est jamais servi pour une autre", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireCacheSection(depot, "nathan", "prevision", { ok: true, resultat: 1 }, T0);
    expect(await lireCacheSection(depot, "nathan", "echeances")).toBeNull();
    expect(await lireCacheSection(depot, "nathan", "interventions:planifiee")).toBeNull();
  });

  test("rien de gardé : null", async () => {
    expect(await lireCacheSection(new DepotCleValeurMemoire(), "nathan", "tresorerie")).toBeNull();
  });

  test.each([
    ["du texte qui n'est pas du JSON", "pas du json"],
    ["du JSON qui n'est pas un objet", "[1,2]"],
    ["un nombre", "42"],
    ["sans enveloppe", JSON.stringify({ misAJourLe: T0 })],
    ["une enveloppe nulle", JSON.stringify({ resultat: null, misAJourLe: T0 })],
    ["sans date", JSON.stringify({ resultat: { ok: true } })],
    ["une date qui n'est pas un texte", JSON.stringify({ resultat: { ok: true }, misAJourLe: 1759168800000 })],
    ["une date illisible", JSON.stringify({ resultat: { ok: true }, misAJourLe: "hier" })],
  ])("une valeur gardée corrompue (%s) est « pas de cache », jamais une valeur devinée", async (_nom, brut) => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("admin:nathan:tresorerie_v1", brut);
    expect(await lireCacheSection(depot, "nathan", "tresorerie")).toBeNull();
  });

  test("une valeur écrite sous une autre version de clé n'est pas relue", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("admin:nathan:tresorerie_v0", JSON.stringify({ resultat: { ok: true }, misAJourLe: T0 }));
    await depot.ecrire("admin:nathan:tresorerie", JSON.stringify({ resultat: { ok: true }, misAJourLe: T0 }));
    expect(await lireCacheSection(depot, "nathan", "tresorerie")).toBeNull();
  });
});
