import fs from "node:fs";
import path from "node:path";
import { interpreter } from "../admin/enveloppe";
import {
  lireBriefing,
  lireSuiteBriefing,
  lireAlertesM9,
  lireEtatConsolide,
  SECTIONS_BRIEFING,
} from "./briefing";
const fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures/reponses-moteur.json"), "utf8"),
);
const raw = (nom: string) => JSON.parse(JSON.stringify(fixture.reponses[nom].resultat));

test("les quatre contrats lisent les enveloppes directes réelles du moteur", () => {
  expect(fixture.fictif).toBe(true);
  expect(interpreter(fixture.reponses.briefing, "directe", lireBriefing).ok).toBe(true);
  expect(
    interpreter(fixture.reponses.suite_decisions_en_attente, "directe", (v) =>
      lireSuiteBriefing(
        v,
        "decisions_en_attente",
        fixture.appels.suite_decisions_en_attente.args.depart,
      ),
    ).ok,
  ).toBe(true);
  expect(interpreter(fixture.reponses.alertes, "directe", (v) => lireAlertesM9(v, 0)).ok).toBe(
    true,
  );
  expect(interpreter(fixture.reponses.etat, "directe", lireEtatConsolide).ok).toBe(true);
  expect(lireBriefing(raw("briefing"))?.ordre_sections).toEqual([
    ...SECTIONS_BRIEFING,
    "manques_pour_conclure",
  ]);
});

test.each([null, {}, { type: "BRIEFING_MATIN" }])(
  "une forme absente n'invente pas un briefing vide",
  (v) => {
    expect(lireBriefing(v)).toBeNull();
  },
);

test("compteurs et curseurs contradictoires sont illisibles", () => {
  const page = raw("suite_decisions_en_attente");
  expect(
    lireSuiteBriefing(
      { ...page, affiches: page.affiches + 1 },
      "decisions_en_attente",
      page.depart,
    ),
  ).toBeNull();
  expect(
    lireSuiteBriefing(
      { ...page, prochain_depart: page.depart },
      "decisions_en_attente",
      page.depart,
    ),
  ).toBeNull();
  expect(lireSuiteBriefing(page, "alertes_m8", page.depart)).toBeNull();
  expect(lireSuiteBriefing(page, "decisions_en_attente", page.depart + 1)).toBeNull();
  const alerts = raw("alertes");
  expect(lireAlertesM9({ ...alerts, total: true }, 0)).toBeNull();
  expect(lireAlertesM9({ ...alerts, reste: -1 }, 0)).toBeNull();
});

test("les preuves décimales restent texte et les faits non textuels ne sont pas devinés", () => {
  const alerts = lireAlertesM9(raw("alertes"), 0);
  expect(alerts?.alertes[0].preuve.valeur).toBe("100.00");
  const etat = raw("etat");
  etat.faits_par_module["m04-field-ops"].valeurs.m4_duree_reelle_minutes = 246;
  expect(lireEtatConsolide(etat)).toBeNull();
});

test("une sortie tronquée reste une sortie impossible à lire", () => {
  expect(
    interpreter({ ok: true, tronque: true, apercu: "{}" }, "directe", lireEtatConsolide),
  ).toMatchObject({ ok: false, genre: "technique" });
});

test("un module nommé __proto__ reste un fait propre du serveur", () => {
  const etat = raw("etat");
  const maillon = etat.faits_par_module["m04-field-ops"];
  const fichier = JSON.parse(
    JSON.stringify({
      ...etat,
      faits_par_module: { ["__proto__"]: { ...maillon, module_source: "__proto__" } },
    }),
  );
  const lu = lireEtatConsolide(fichier);
  expect(Object.keys(lu?.faits_par_module ?? {})).toEqual(["__proto__"]);
  expect(Object.prototype.hasOwnProperty.call(lu?.faits_par_module, "__proto__")).toBe(true);
});

test("les grands entiers arrondis ne rendent pas un compteur contradictoire cohérent", () => {
  const page = raw("suite_decisions_en_attente");
  const item = page.items[0];
  expect(
    lireSuiteBriefing(
      {
        ...page,
        depart: 0,
        items: [item],
        affiches: 1,
        total: 9007199254740992,
        reste: 9007199254740992,
        prochain_depart: 1,
      },
      "decisions_en_attente",
      0,
    ),
  ).toBeNull();
});
