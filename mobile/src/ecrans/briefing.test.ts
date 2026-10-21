import { presenterItemM9, presenterManqueM9 } from "./briefing";
import { lireBriefing, lireAlertesM9, lireEtatConsolide } from "../m9/briefing";
import frCA from "../i18n/locales/fr-CA";
import enCA from "../i18n/locales/en-CA";
import fixture from "../m9/fixtures/reponses-moteur.json";

function texte(cle: string, langue: unknown): string {
  const value = cle
    .split(".")
    .reduce<unknown>(
      (v, k) =>
        typeof v === "object" && v !== null ? (v as Record<string, unknown>)[k] : undefined,
      langue,
    );
  expect(typeof value).toBe("string");
  return value as string;
}

test("chaque donnée native conserve ses références, dates et messages traduits sans calcul financier", () => {
  const b = lireBriefing(fixture.reponses.briefing.resultat)!;
  const a = lireAlertesM9(fixture.reponses.alertes.resultat, 0)!;
  const e = lireEtatConsolide(fixture.reponses.etat.resultat)!;
  const lignes = [
    ...b.sections.decisions_en_attente.items.map((v) => presenterItemM9(v, -240)),
    ...a.alertes.map((v) => presenterItemM9(v, -240)),
    ...Object.values(e.faits_par_module).map((v) => presenterItemM9(v, -240)),
    ...b.sections.manques_pour_conclure.items.map(presenterManqueM9),
  ];
  for (const ligne of lignes)
    for (const msg of [ligne.titre, ...ligne.lignes])
      for (const langue of [frCA, enCA]) {
        const variables = [...texte(msg.cle, langue).matchAll(/\{\{(\w+)\}\}/g)]
          .map((m) => m[1])
          .sort();
        expect(Object.keys(msg.params ?? {}).sort()).toEqual(variables);
      }
  expect(lignes.some((l) => l.lignes.some((m) => m.params?.id === "wct-fictif-0"))).toBe(true);
});

test("un texte ou une référence interne ne quitte pas le serveur dans l'affichage", () => {
  const vue = presenterManqueM9({
    section: "faits_veille",
    constat: "Lire /srv/opsys/secret.yaml",
    verifie: "registre m09-strategic-intelligence/snapshots",
  });
  expect(vue.titre.cle).toBe("admin.briefing.detailNonAffiche");
  expect(vue.lignes[0].cle).toBe("admin.briefing.sourceFaits");
  expect(JSON.stringify(vue)).not.toContain("/srv/");
});

test.each(["__proto__", "constructor", "toString"])(
  "la source %s est un texte serveur et jamais une propriété héritée",
  (module) => {
    const vue = presenterItemM9(
      { module_source: module, horodatage: "2026-10-05T18:00:00Z", valeurs: {} },
      -240,
    );
    expect(vue.lignes[0]).toEqual({ cle: "admin.briefing.source", params: { source: module } });
  },
);

test("les références et modules qui ressemblent à un chemin sont également masqués", () => {
  const b = lireBriefing(fixture.reponses.briefing.resultat)!;
  const decision = presenterItemM9(
    {
      ...b.sections.decisions_en_attente.items[0],
      id: "/srv/opsys/interne.db",
      niveau: "/srv/opsys/role.yaml",
    },
    -240,
  );
  expect(JSON.stringify(decision)).not.toContain("/srv/");
});
