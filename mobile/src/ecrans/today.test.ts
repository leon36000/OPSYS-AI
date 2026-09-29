import enCA from "../i18n/locales/en-CA";
import frCA from "../i18n/locales/fr-CA";
import { ETATS_INTERVENTION_M4 } from "../m4/interventions";
import type { InterventionM4 } from "../m4/interventions";
import type { ResultatChargementChantiers } from "../today/orchestrateur";
import { vueChantiers } from "./today";

const I1: InterventionM4 = { intervention_id: "I1", statut: "planifiee", lead_id: "L1", type_travaux: "gouttieres", devis_id: null };
const I2: InterventionM4 = { intervention_id: "I2", statut: "en_route", lead_id: "L2", service: "revetement", devis_id: "D2" };
const T0 = "2026-09-28T12:00:00.000Z";

describe("vueChantiers : ce que l'écran des chantiers dit d'une lecture", () => {
  test("lue au serveur : les chantiers, aucun avis", () => {
    const resultat: ResultatChargementChantiers = { source: "serveur", items: [I2, I1], misAJourLe: T0 };
    expect(vueChantiers(resultat, true)).toEqual({ items: [I2, I1], avis: null, aucunChantier: false });
  });

  test("lue au serveur, et il n'y a rien : « aucun chantier » (le serveur le dit)", () => {
    expect(vueChantiers({ source: "serveur", items: [], misAJourLe: T0 }, true)).toEqual({ items: [], avis: null, aucunChantier: true });
  });

  test("« aucun chantier » n'est jamais dit avant la fin du premier chargement", () => {
    expect(vueChantiers({ source: "serveur", items: [], misAJourLe: T0 }, false).aucunChantier).toBe(false);
    expect(vueChantiers({ source: "cache", items: [], misAJourLe: T0, raisonHorsLigne: { code: "erreur_reseau", detail: "" } }, false).aucunChantier).toBe(false);
  });

  test("la liste gardée : marquée comme telle, avec sa date ; vide, elle dit « aucun chantier » (au jour du cache)", () => {
    const raison = { code: "erreur_reseau", detail: "Network request failed" };
    expect(vueChantiers({ source: "cache", items: [I1], misAJourLe: "2026-09-28T08:00:00.000Z", raisonHorsLigne: raison }, true)).toEqual({
      items: [I1],
      avis: { genre: "cache", misAJourLe: "2026-09-28T08:00:00.000Z" },
      aucunChantier: false,
    });
    expect(vueChantiers({ source: "cache", items: [], misAJourLe: T0, raisonHorsLigne: raison }, true)).toMatchObject({
      avis: { genre: "cache" },
      aucunChantier: true,
    });
  });

  test("une liste INCOMPLÈTE (le socle a coupé la réponse) : les chantiers lus, l'avis dit quels statuts, jamais « aucun chantier »", () => {
    const resultat: ResultatChargementChantiers = { source: "incomplet", items: [I2], groupesIncomplets: ["planifiee"], misAJourLe: T0 };
    expect(vueChantiers(resultat, true)).toEqual({ items: [I2], avis: { genre: "incomplet", statuts: ["planifiee"] }, aucunChantier: false });
  });

  test("incomplète et SANS chantier lu : l'avis seul — une liste qu'on n'a pas pu lire n'est pas une liste vide", () => {
    const resultat: ResultatChargementChantiers = { source: "incomplet", items: [], groupesIncomplets: ["en_route", "sur_site", "en_revue", "planifiee"], misAJourLe: T0 };
    expect(vueChantiers(resultat, true)).toEqual({
      items: [],
      avis: { genre: "incomplet", statuts: ["en_route", "sur_site", "en_revue", "planifiee"] },
      aucunChantier: false,
    });
  });

  test("un refus du serveur : son verdict, aucun chantier, jamais « aucun chantier » ni une liste gardée", () => {
    const verdict = { code: "tool_call_blocked", detail: "device_unknown" };
    expect(vueChantiers({ source: "refus", verdict }, true)).toEqual({ items: [], avis: { genre: "refus", verdict }, aucunChantier: false });
  });

  test("ni serveur ni cache : l'avis « aucune donnée », jamais « aucun chantier »", () => {
    expect(vueChantiers({ source: "aucune", raisonHorsLigne: { code: "erreur_reseau", detail: "" } }, true)).toEqual({
      items: [],
      avis: { genre: "aucune" },
      aucunChantier: false,
    });
  });

  test("aucune session (rien n'a été lu) : rien n'est dit, surtout pas « aucun chantier »", () => {
    expect(vueChantiers(null, true)).toEqual({ items: [], avis: null, aucunChantier: false });
  });
});

describe("les textes de l'écran des chantiers et de l'écran d'un chantier (fr-CA et en-CA)", () => {
  test.each([
    ["fr-CA", frCA],
    ["en-CA", enCA],
  ] as const)("(%s) chaque statut d'intervention a son texte, `a_planifier` compris", (_langue, ressources) => {
    expect(Object.keys(ressources.today.statut).sort()).toEqual([...ETATS_INTERVENTION_M4].sort());
    for (const statut of ETATS_INTERVENTION_M4) {
      expect(ressources.today.statut[statut].trim()).not.toBe("");
    }
  });

  test.each([
    ["fr-CA", frCA],
    ["en-CA", enCA],
  ] as const)("(%s) le refus dit le code et le détail du serveur, la liste incomplète nomme ses statuts", (_langue, ressources) => {
    for (const texte of [ressources.today.source.refus, ressources.job.source.refus]) {
      expect(texte).toContain("{{code}}");
      expect(texte).toContain("{{detail}}");
    }
    expect(ressources.today.source.incomplet).toContain("{{statuts}}");
  });
});
