import fs from "node:fs";
import path from "node:path";
import { lireCacheSection } from "./cache";
import { creerChargeurBriefing } from "./briefing";
import { config, echecHttp, transportHorsLigne } from "./donneesDeTest";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { synchroniserCaches } from "../identite/caches";
import { cacheRequiertPurge, capturerGardeLecture } from "../stockage/lecturesEnVol";
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

const departSuite = fixture.appels.suite_decisions_en_attente.args.depart;
function premierePage(chargeur: ReturnType<typeof creerChargeurBriefing>, frontiere: string) {
  return frontiere === "suite" ? chargeur.chargerBriefing(NOW) : chargeur.chargerAlertes();
}
function pageSuivante(chargeur: ReturnType<typeof creerChargeurBriefing>, frontiere: string) {
  return frontiere === "suite"
    ? chargeur.chargerSuite(NOW, "decisions_en_attente", departSuite)
    : chargeur.chargerAlertes(1);
}

describe("autorité de suite — cache de première page", () => {
  test.each([
    ["suite", 401, undefined, "réponse HTTP 401 inattendue"],
    ["alertes", 401, undefined, "réponse HTTP 401 inattendue"],
    ["suite", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_suite_briefing" (device_unknown).'],
    ["alertes", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_alertes_m8" (device_unknown).'],
    ["suite", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_suite_briefing" (role_unknown).'],
    ["alertes", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_alertes_m8" (role_unknown).'],
  ] as const)("%s / %i / %s ferme seulement sa copie liée", async (frontiere, status, type, detail) => {
    const depot = new DepotCleValeurMemoire();
    const initial = creerChargeurBriefing(config(good(), { depot }));
    await initial.chargerBriefing(NOW); await initial.chargerAlertes(); await initial.chargerEtat();
    const autre = creerChargeurBriefing(config(good(), { depot, personne: "autre-fictive" }));
    await premierePage(autre, frontiere);
    const copieEtat = await lireCacheSection(depot, "nathan", "etat_m9");
    const copieAutre = await lireCacheSection(depot, "autre-fictive", frontiere === "suite" ? `briefing_m9:${NOW.slice(0, 10)}` : "alertes_m9");
    const interdit = creerChargeurBriefing(config(jest.fn(async () => echecHttp(status, type, detail)), { depot }));
    expect(await pageSuivante(interdit, frontiere)).toMatchObject({ source: "refus", verdict: { detail } });
    const offline = creerChargeurBriefing({ ...config(transportHorsLigne(), { depot }), enLigne: () => false });
    expect((await premierePage(offline, frontiere)).source).toBe("aucune");
    expect((await premierePage(offline, frontiere === "suite" ? "alertes" : "suite")).source).toBe("cache");
    expect(await lireCacheSection(depot, "nathan", "etat_m9")).toEqual(copieEtat);
    expect(await lireCacheSection(depot, "autre-fictive", frontiere === "suite" ? `briefing_m9:${NOW.slice(0, 10)}` : "alertes_m9")).toEqual(copieAutre);
  });

  test.each([
    ["suite", 400, "invalid_request", "depart est au-delà de la page courante"],
    ["alertes", 400, "invalid_request", "depart est au-delà de la page courante"],
    ["suite", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_suite_briefing" (tool_out_of_scope).'],
    ["alertes", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_alertes_m8" (tool_out_of_scope).'],
  ] as const)("%s / %i / %s ne retire pas des droits à la première page", async (frontiere, status, type, detail) => {
    const depot = new DepotCleValeurMemoire();
    await premierePage(creerChargeurBriefing(config(good(), { depot })), frontiere);
    const interdit = creerChargeurBriefing(config(jest.fn(async () => echecHttp(status, type, detail)), { depot }));
    expect((await pageSuivante(interdit, frontiere)).source).toBe("refus");
    const offline = creerChargeurBriefing({ ...config(transportHorsLigne(), { depot }), enLigne: () => false });
    expect((await premierePage(offline, frontiere)).source).toBe("cache");
  });

  test.each(["suite", "alertes"])("%s ferme la première réponse déjà en vol sans écrire après son tombstone", async frontiere => {
    const depot = new DepotCleValeurMemoire();
    let entrer!: () => void, liberer!: (v: unknown) => void;
    const entree = new Promise<void>(resolve => { entrer = resolve; });
    const attente = new Promise(resolve => { liberer = resolve; });
    const ancien = creerChargeurBriefing(config(jest.fn(async () => { entrer(); return attente; }), { depot }));
    const pending = premierePage(ancien, frontiere);
    await entree;
    const interdit = creerChargeurBriefing(config(jest.fn(async () => echecHttp(401)), { depot }));
    expect((await pageSuivante(interdit, frontiere)).source).toBe("refus");
    liberer({ ok: true, result: native(frontiere === "suite" ? "briefing" : "alertes") });
    expect(await pending).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
    const offline = creerChargeurBriefing({ ...config(transportHorsLigne(), { depot }), enLigne: () => false });
    expect((await premierePage(offline, frontiere)).source).toBe("aucune");
  });

  test("suite ferme également une suite déjà en vol dans la même section", async () => {
    const depot = new DepotCleValeurMemoire();
    let entrer!: () => void, liberer!: (v: unknown) => void;
    const entree = new Promise<void>(resolve => { entrer = resolve; });
    const attente = new Promise(resolve => { liberer = resolve; });
    const ancien = creerChargeurBriefing(config(jest.fn(async () => { entrer(); return attente; }), { depot }));
    const pending = ancien.chargerSuite(NOW, "decisions_en_attente", departSuite);
    await entree;
    const interdit = creerChargeurBriefing(config(jest.fn(async () => echecHttp(401)), { depot }));
    expect((await interdit.chargerSuite(NOW, "decisions_en_attente", departSuite)).source).toBe("refus");
    liberer({ ok: true, result: native("suite_decisions_en_attente") });
    expect(await pending).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  });
});

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

test("refus acquis : les trois copies informatives ne réapparaissent pas hors ligne", async () => {
  const depot = new DepotCleValeurMemoire();
  const initial = creerChargeurBriefing(config(good(), { depot }));
  await initial.chargerBriefing(NOW); await initial.chargerAlertes(); await initial.chargerEtat();
  const interdit = creerChargeurBriefing(config(jest.fn(async () => echecHttp(403)), { depot }));
  for (const lu of [await interdit.chargerBriefing(NOW), await interdit.chargerAlertes(), await interdit.chargerEtat()])
    expect(lu.source).toBe("refus");
  const offline = creerChargeurBriefing({ ...config(transportHorsLigne(), { depot }), enLigne: () => false });
  for (const lu of [await offline.chargerBriefing(NOW), await offline.chargerAlertes(), await offline.chargerEtat()])
    expect(lu.source).toBe("aucune");
});

test("refus malformé combiné à panne passagère : aucune copie reprise, aucun getter exécuté", async () => {
  const depot = new DepotCleValeurMemoire(), initial = creerChargeurBriefing(config(good(), { depot }));
  await initial.chargerBriefing(NOW);
  const getter = jest.fn(() => "donnée-fictive"), brut = { ok: false, erreur: "budget_epuise", resultat: { accepte: false } };
  Object.defineProperty(brut, "extra", { get: getter });
  const refuse = creerChargeurBriefing(config(jest.fn(async () => ({ ok: true, result: brut })), { depot }));
  expect((await refuse.chargerBriefing(NOW)).source).toBe("refus");
  expect(getter).not.toHaveBeenCalled();
});
test("refus acquis prioritaire sur tronque : verdict natif conservé", async () => {
  const depot = new DepotCleValeurMemoire(), initial = creerChargeurBriefing(config(good(), { depot }));
  await initial.chargerBriefing(NOW);
  const brut = { ok: true, tronque: true, resultat: { accepte: false,
    verdict: { code: "REJ-ACCES-FICTIF", detail: "Refus fictif" } } };
  const refuse = creerChargeurBriefing(config(jest.fn(async () => ({ ok: true, result: brut })), { depot }));
  expect(await refuse.chargerBriefing(NOW)).toMatchObject({ source: "refus", verdict: { code: "REJ-ACCES-FICTIF" } });
  const offline = creerChargeurBriefing({ ...config(transportHorsLigne(), { depot }), enLigne: () => false });
  expect((await offline.chargerBriefing(NOW)).source).toBe("aucune");
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


describe("panne du tombstone — refus acquis et vraie identité", () => {
  test.each([
    ["suite", 401, undefined, "réponse HTTP 401 inattendue"],
    ["alertes", 401, undefined, "réponse HTTP 401 inattendue"],
    ["suite", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_suite_briefing" (role_unknown).'],
    ["alertes", 403, "tool_call_blocked", 'OPSYS device is not authorized to call "m9_lire_alertes_m8" (device_unknown).'],
  ] as const)("%s / %i garde le verdict malgré la panne d'écriture", async (frontiere, status, type, detail) => {
    class DepotEnPanne extends DepotCleValeurMemoire {
      tombstones = 0;
      override async ecrire(cle: string, valeur: string) {
        if (JSON.parse(valeur).resultat === null) {
          this.tombstones += 1;
          throw new Error("panne de stockage fictive");
        }
        return super.ecrire(cle, valeur);
      }
    }
    const depot = new DepotEnPanne();
    await premierePage(creerChargeurBriefing(config(good(), { depot })), frontiere);
    const interdit = creerChargeurBriefing(config(jest.fn(async () => echecHttp(status, type, detail)), { depot }));
    const resultat = await pageSuivante(interdit, frontiere);
    expect(depot.tombstones).toBe(1);
    expect(cacheRequiertPurge(depot)).toBe(true);
    const offline = creerChargeurBriefing({ ...config(transportHorsLigne(), { depot }), enLigne: () => false });
    expect((await premierePage(offline, frontiere)).source).toBe("aucune");
    expect(resultat).toEqual({ source: "refus", verdict: { code: status === 401 ? "http_401" : "tool_call_blocked", detail } });
  });

  test.each([["suite", true], ["alertes", true], ["suite", false], ["alertes", false]] as const)("%s remplace le refus si l'identité change pendant l'écriture (panne=%s)", async (frontiere, panne) => {
    let entrer!: () => void, rejeter!: (e: Error) => void, terminer!: () => void;
    const entree = new Promise<void>(resolve => { entrer = resolve; });
    const ecriture = new Promise<void>((resolve, reject) => { terminer = resolve; rejeter = reject; });
    class DepotEnAttente extends DepotCleValeurMemoire {
      override async ecrire(cle: string, valeur: string) {
        if (JSON.parse(valeur).resultat === null) {
          entrer();
          await ecriture;
        }
        return super.ecrire(cle, valeur);
      }
    }
    const depot = new DepotEnAttente();
    await premierePage(creerChargeurBriefing(config(good(), { depot })), frontiere);
    const garde = capturerGardeLecture(depot);
    const interdit = creerChargeurBriefing(config(jest.fn(async () => echecHttp(401)), { depot }));
    const pending = pageSuivante(interdit, frontiere);
    await entree;
    const purge = synchroniserCaches(depot, { genre: "erreur", motif: "jeton_refuse" });
    for (let i = 0; i < 10 && garde.courante(); i += 1) await Promise.resolve();
    expect(garde.courante()).toBe(false);
    if (panne) rejeter(new Error("panne de stockage fictive"));
    else terminer();
    expect(await pending).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
    await purge;
    expect(depot.cles()).toEqual([]);
  });
});
