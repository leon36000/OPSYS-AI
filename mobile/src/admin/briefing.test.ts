import fs from "node:fs";
import path from "node:path";
import { lireCacheSection } from "./cache";
import { creerChargeurBriefing } from "./briefing";
import { config, echecHttp, transportHorsLigne } from "./donneesDeTest";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { synchroniserCaches } from "../identite/caches";
const fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../m9/fixtures/reponses-moteur.json"), "utf8"),
);
const NOW = fixture.maintenant;
const native = (nom: string) => JSON.parse(JSON.stringify(fixture.reponses[nom]));
const good = () =>
  jest.fn(async (params) => ({
    ok: true as const,
    result: native(
      params.requete.tool === "m9_produire_briefing_matin"
        ? "briefing"
        : params.requete.tool === "m9_lire_alertes_m8"
          ? "alertes"
          : params.requete.tool === "m9_lire_etat_consolide"
            ? "etat"
            : "suite_decisions_en_attente",
    ),
  }));

test("les quatre noms nus et arguments exacts, aucun rôle/personne dans la requête", async () => {
  const transport = good();
  const chargeur = creerChargeurBriefing(config(transport));
  await chargeur.chargerBriefing(NOW);
  await chargeur.chargerSuite(
    NOW,
    "decisions_en_attente",
    fixture.appels.suite_decisions_en_attente.args.depart,
  );
  await chargeur.chargerAlertes();
  await chargeur.chargerEtat();
  expect(transport.mock.calls.map(([p]) => p.requete)).toEqual([
    { tool: "m9_produire_briefing_matin", args: { maintenant: NOW } },
    { tool: "m9_lire_suite_briefing", args: fixture.appels.suite_decisions_en_attente.args },
    { tool: "m9_lire_alertes_m8", args: { depart: 0 } },
    { tool: "m9_lire_etat_consolide", args: {} },
  ]);
});

test("hors ligne les premières lectures personnelles sont marquées cache ; un refus ne les remplace jamais", async () => {
  const depot = new DepotCleValeurMemoire();
  const premiere = creerChargeurBriefing(config(good(), { depot }));
  await premiere.chargerBriefing(NOW);
  await premiere.chargerAlertes();
  await premiere.chargerEtat();
  const horsLigne = creerChargeurBriefing(config(transportHorsLigne(), { depot }));
  expect((await horsLigne.chargerBriefing(NOW)).source).toBe("cache");
  expect((await horsLigne.chargerEtat()).source).toBe("cache");
  expect(
    (
      await creerChargeurBriefing(
        config(transportHorsLigne(), { depot, personne: "autre-fictive" }),
      ).chargerBriefing(NOW)
    ).source,
  ).toBe("aucune");
  const keys = depot.cles();
  const refuse = creerChargeurBriefing(
    config(
      jest.fn(async () => echecHttp(403, "tool_call_blocked", "rôle retiré")),
      { depot },
    ),
  );
  expect((await refuse.chargerBriefing(NOW)).source).toBe("refus");
  expect((await refuse.chargerAlertes()).source).toBe("refus");
  expect((await refuse.chargerEtat()).source).toBe("refus");
  expect(depot.cles()).toEqual(keys);
});

test("une suite courante ne lit et n'écrit aucun cache ; une page incohérente est écartée", async () => {
  const depot = new DepotCleValeurMemoire();
  const lire = jest.spyOn(depot, "lire"),
    ecrire = jest.spyOn(depot, "ecrire");
  const depart = fixture.appels.suite_decisions_en_attente.args.depart;
  const chargeur = creerChargeurBriefing(config(good(), { depot }));
  expect((await chargeur.chargerSuite(NOW, "decisions_en_attente", depart)).source).toBe("serveur");
  expect(lire).not.toHaveBeenCalled();
  expect(ecrire).not.toHaveBeenCalled();
  expect((await chargeur.chargerSuite(NOW, "decisions_en_attente", depart + 1)).source).toBe(
    "aucune",
  );
});

test("un chargeur conservé après purge n'appelle plus les outils", async () => {
  const depot = new DepotCleValeurMemoire();
  const transport = good();
  const chargeur = creerChargeurBriefing(config(transport, { depot }));
  await synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
  expect((await chargeur.chargerBriefing(NOW)).source).toBe("aucune");
  expect((await chargeur.chargerSuite(NOW, "decisions_en_attente", 0)).source).toBe("aucune");
  expect((await chargeur.chargerAlertes()).source).toBe("aucune");
  expect((await chargeur.chargerEtat()).source).toBe("aucune");
  expect(transport).not.toHaveBeenCalled();
});

test.each(["briefing", "alertes", "etat", "suite_decisions_en_attente"])(
  "une réponse %s tardive après purge ne devient ni donnée ni cache",
  async (nom) => {
    let commencer!: () => void, resoudre!: (v: unknown) => void;
    const started = new Promise<void>((resolve) => {
      commencer = resolve;
    });
    const reply = new Promise((resolve) => {
      resoudre = resolve;
    });
    const transport = jest.fn(async () => {
      commencer();
      return reply;
    });
    const depot = new DepotCleValeurMemoire();
    const chargeur = creerChargeurBriefing(config(transport, { depot }));
    const pending =
      nom === "briefing"
        ? chargeur.chargerBriefing(NOW)
        : nom === "alertes"
          ? chargeur.chargerAlertes()
          : nom === "etat"
            ? chargeur.chargerEtat()
            : chargeur.chargerSuite(
                NOW,
                "decisions_en_attente",
                fixture.appels.suite_decisions_en_attente.args.depart,
              );
    await started;
    await synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
    resoudre({ ok: true, result: native(nom) });
    expect(await pending).toMatchObject({
      source: "aucune",
      raison: { code: "lecture_remplacee" },
    });
    expect(depot.cles()).toEqual([]);
  },
);

test("le cache retire la preuve M8 non affichée tout en restant lisible hors ligne", async () => {
  const depot = new DepotCleValeurMemoire();
  await creerChargeurBriefing(config(good(), { depot })).chargerAlertes();
  const gardee = await lireCacheSection(depot, "nathan", "alertes_m9");
  const raw = gardee?.resultat as { resultat: { alertes: { preuve: Record<string, unknown> }[] } };
  expect(Object.keys(raw.resultat.alertes[0].preuve)).toEqual(["wct_id"]);
  const relue = await creerChargeurBriefing(
    config(transportHorsLigne(), { depot }),
  ).chargerAlertes();
  expect(relue.source).toBe("cache");
  if (relue.source === "cache") expect(relue.valeur.alertes[0].preuve.wct_id).toBeDefined();
});
