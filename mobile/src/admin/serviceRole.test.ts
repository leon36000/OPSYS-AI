import { definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { reponse } from "./donneesDeTest";

jest.mock("../stockage/service", () => ({ obtenirDepotLocal: jest.fn() }));
jest.mock("../protocole/client", () => ({ invoquerOutil: jest.fn() }));
const { obtenirDepotLocal } = require("../stockage/service") as { obtenirDepotLocal: jest.Mock };
const { invoquerOutil } = require("../protocole/client") as { invoquerOutil: jest.Mock };
const { chargerVueExecutive } = require("./service");
beforeEach(() => {
  jest.clearAllMocks();
  definirConfigurationAppel({ urlBase: "https://fictif.exemple.ca", jeton: "jeton-fictif", appareilId: "device-fictif" });
  obtenirDepotLocal.mockResolvedValue(new DepotCleValeurMemoire());
  invoquerOutil.mockResolvedValue({ ok: true, result: reponse("vue_executive_vide") });
});
afterEach(() => { definirPersonneConfirmee(null); definirConfigurationAppel(null); });
test.each(["seller", "employee", undefined])("rôle %s : zéro dépôt et zéro HTTP du service admin", async role => {
  definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: "device-fictif", personne: "personne-fictive", role });
  expect(await chargerVueExecutive()).toBeNull();
  expect(obtenirDepotLocal).not.toHaveBeenCalled(); expect(invoquerOutil).not.toHaveBeenCalled();
});
test("admin retiré pendant l'ouverture du dépôt : aucun HTTP", async () => {
  definirPersonneConfirmee({ jeton: "jeton-fictif", appareilId: "device-fictif", personne: "personne-fictive", role: "admin" });
  obtenirDepotLocal.mockImplementation(async () => { definirPersonneConfirmee(null); return new DepotCleValeurMemoire(); });
  expect(await chargerVueExecutive()).toBeNull(); expect(invoquerOutil).not.toHaveBeenCalled();
});
