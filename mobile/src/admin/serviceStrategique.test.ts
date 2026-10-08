import { definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import fixture from "../m9/fixturesLectureStrategique.json";
jest.mock("../stockage/service", () => ({ obtenirDepotLocal: jest.fn() }));
jest.mock("../protocole/client", () => ({ invoquerOutil: jest.fn() }));
const { obtenirDepotLocal } = require("../stockage/service") as { obtenirDepotLocal: jest.Mock };
const { invoquerOutil } = require("../protocole/client") as { invoquerOutil: jest.Mock };
const { chargerLectureStrategiqueM9, actualiserConnectiviteBriefingM9 } = require("./service");
const admin = (role = "admin") => definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: "device-fictif", personne: "personne-fictive", role });
beforeEach(() => {
  jest.clearAllMocks(); definirConfigurationAppel({ urlBase: "https://fictif.exemple.ca", jeton: "jeton-fictif", appareilId: "device-fictif" });
  admin(); actualiserConnectiviteBriefingM9(true);
  obtenirDepotLocal.mockResolvedValue(new DepotCleValeurMemoire());
  invoquerOutil.mockResolvedValue({ ok: true, result: fixture.reponses.mesure.enveloppe });
});
afterEach(() => { definirPersonneConfirmee(null); definirConfigurationAppel(null); });
test.each(["seller", "employee"])("rôle %s : aucun dépôt ni HTTP", async role => {
  admin(role); expect(await chargerLectureStrategiqueM9(fixture.maintenant)).toBeNull();
  expect(obtenirDepotLocal).not.toHaveBeenCalled(); expect(invoquerOutil).not.toHaveBeenCalled();
});
test("admin retiré pendant ouverture : zéro HTTP", async () => {
  obtenirDepotLocal.mockImplementation(async () => { admin("employee"); return new DepotCleValeurMemoire(); });
  expect(await chargerLectureStrategiqueM9(fixture.maintenant)).toBeNull(); expect(invoquerOutil).not.toHaveBeenCalled();
});
test("hors ligne : aucune requête native ni preuve gardée", async () => {
  actualiserConnectiviteBriefingM9(false);
  expect(await chargerLectureStrategiqueM9(fixture.maintenant)).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(invoquerOutil).not.toHaveBeenCalled();
});
test("lecture supplantée : le résultat ancien est fermé même si HTTP réussit", async () => {
  let finir!: (v: unknown) => void, debut!: () => void;
  const commence = new Promise<void>(r => { debut = r; });
  invoquerOutil.mockImplementationOnce(() => { debut(); return new Promise(r => { finir = r; }); });
  const ancienne = chargerLectureStrategiqueM9(fixture.maintenant); await commence;
  expect(await chargerLectureStrategiqueM9(fixture.maintenant)).toMatchObject({ source: "serveur" });
  finir({ ok: true, result: fixture.reponses.mesure.enveloppe });
  expect(await ancienne).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});
