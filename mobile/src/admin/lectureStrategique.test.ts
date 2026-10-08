import fixture from "../m9/fixturesLectureStrategique.json";
import { creerChargeurBriefing } from "./briefing";
import { config, echecHttp } from "./donneesDeTest";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { synchroniserCaches } from "../identite/caches";

const NOW = fixture.maintenant;
const enveloppe = (nom: keyof typeof fixture.reponses) => JSON.parse(JSON.stringify(fixture.reponses[nom].enveloppe));
function harnais(nom: keyof typeof fixture.reponses = "mesure", connectee = true) {
  const depot = new DepotCleValeurMemoire();
  const transport = jest.fn(async (_params: unknown) => ({ ok: true, result: enveloppe(nom) }));
  const lire = jest.spyOn(depot, "lire"), ecrire = jest.spyOn(depot, "ecrire");
  return { depot, transport, lire, ecrire, chargeur: creerChargeurBriefing({ ...config(transport, { depot }), enLigne: () => connectee }) };
}
test.each(Object.entries(fixture.reponses))("lecture native %s : arguments exacts, aucun cache", async (_nom, reponse) => {
  expect(fixture.fictif).toBe(true);
  const h = harnais(); h.transport.mockResolvedValue({ ok: true, result: reponse.enveloppe });
  const lu = await h.chargeur.chargerLectureStrategique(reponse.arguments.maintenant, reponse.arguments.depart);
  expect(lu).toMatchObject({ source: "serveur", valeur: { decision: { prise_par_m9: false }, affichage: { depart: reponse.arguments.depart } } });
  expect((h.transport.mock.calls[0][0] as { requete: unknown }).requete).toEqual({ tool: "m9_produire_lecture_strategique", args: reponse.arguments });
  expect(h.lire).not.toHaveBeenCalled(); expect(h.ecrire).not.toHaveBeenCalled();
});
test("hors ligne connu : zéro HTTP et zéro cache, aucune preuve locale supposée", async () => {
  const h = harnais("mesure", false);
  expect(await h.chargeur.chargerLectureStrategique(NOW)).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(h.transport).not.toHaveBeenCalled(); expect(h.lire).not.toHaveBeenCalled(); expect(h.ecrire).not.toHaveBeenCalled();
});
test.each(["2026-02-30T07:00:00-04:00", "2026-10-08", ""])("référence %s invalide : zéro HTTP", async maintenant => {
  const h = harnais(); expect(await h.chargeur.chargerLectureStrategique(maintenant)).toMatchObject({ source: "aucune" });
  expect(h.transport).not.toHaveBeenCalled();
});
test.each([-1, 1.5, Number.MAX_SAFE_INTEGER + 1])("départ %s invalide : zéro HTTP", async depart => {
  const h = harnais(); expect(await h.chargeur.chargerLectureStrategique(NOW, depart)).toMatchObject({ source: "aucune" });
  expect(h.transport).not.toHaveBeenCalled();
});
test("refus HTTP ferme la page sans lire ni écrire de cache", async () => {
  const h = harnais(); h.transport.mockResolvedValue(echecHttp(403) as never);
  expect(await h.chargeur.chargerLectureStrategique(NOW)).toMatchObject({ source: "refus" });
  expect(h.lire).not.toHaveBeenCalled(); expect(h.ecrire).not.toHaveBeenCalled();
});
test("getter enveloppe ignoré sans exécution ni cache", async () => {
  const h = harnais(), getter = jest.fn(() => "fictif-prive");
  const v = enveloppe("mesure"); Object.defineProperty(v, "extra", { get: getter });
  h.transport.mockResolvedValue({ ok: true, result: v });
  expect(await h.chargeur.chargerLectureStrategique(NOW)).toMatchObject({ source: "aucune" });
  expect(getter).not.toHaveBeenCalled(); expect(h.lire).not.toHaveBeenCalled(); expect(h.ecrire).not.toHaveBeenCalled();
});
test("jour/départ supplantés par le serveur : aucune donnée affichable", async () => {
  const h = harnais(); const v = enveloppe("mesure"); v.resultat.jour = "2026-10-09";
  h.transport.mockResolvedValue({ ok: true, result: v });
  expect(await h.chargeur.chargerLectureStrategique(NOW)).toMatchObject({ source: "aucune" });
  h.transport.mockResolvedValue({ ok: true, result: enveloppe("suite") });
  expect(await h.chargeur.chargerLectureStrategique(NOW, 0)).toMatchObject({ source: "aucune" });
});
test("réponse tardive après purge : aucune donnée et aucun cache", async () => {
  const h = harnais(); let terminer!: (v: { ok: boolean; result: unknown }) => void, commencer!: () => void;
  const demarre = new Promise<void>(r => { commencer = r; });
  h.transport.mockImplementation(() => { commencer(); return new Promise(r => { terminer = r; }); });
  const pending = h.chargeur.chargerLectureStrategique(NOW); await demarre;
  await synchroniserCaches(h.depot, { genre: "erreur", motif: "jeton_refuse" });
  terminer({ ok: true, result: enveloppe("mesure") });
  expect(await pending).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});
