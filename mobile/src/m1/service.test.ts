let mockEpoch = 0, mockAdmin = true;
const mockSession = { personne: "admin-fictif", appareilId: "appareil-fictif", jeton: "jeton-fictif", urlBase: "https://core.fictif" };
const mockInvoquer = jest.fn(), mockObtenirDepot = jest.fn();
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const epoch = mockEpoch;
  return { session: mockAdmin ? mockSession : null, courante: () => mockAdmin && epoch === mockEpoch };
} }));
jest.mock("../protocole/client", () => ({ invoquerOutil: (p: unknown) => mockInvoquer(p) }));
jest.mock("../stockage/service", () => ({ obtenirDepotLocal: () => mockObtenirDepot() }));
import { actualiserConnectiviteTransferts, chargerDigestReception, chargerTransfertReception } from "./service";
import { FIXTURES_M1 } from "./fixtures";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { ParametresAppelOutil } from "../protocole/client";
const f = FIXTURES_M1.reponses, date = f.digest_date.args.date_reference, id = f.plainte_ouverte.args.transfert_id;
let depot: DepotCleValeurMemoire;
beforeEach(() => {
  mockEpoch++; mockAdmin = true; mockInvoquer.mockReset(); mockObtenirDepot.mockReset();
  depot = new DepotCleValeurMemoire(); mockObtenirDepot.mockResolvedValue(depot);
  mockInvoquer.mockImplementation(async (p: ParametresAppelOutil) => ({ ok: true,
    result: p.requete.tool === "m1_produire_digest" ? f.digest_date.enveloppe : f.plainte_ouverte.enveloppe }));
  actualiserConnectiviteTransferts(true);
});
test("service natif : T0 minimaux avec session confirmée, aucune identité ni mutation dans les args", async () => {
  expect((await chargerDigestReception(date))?.source).toBe("serveur");
  expect((await chargerTransfertReception(id))?.source).toBe("serveur");
  expect(mockInvoquer.mock.calls.map(([p]) => p.requete)).toEqual([
    { tool: "m1_produire_digest", args: { date_reference: date } },
    { tool: "m1_lire_transfert", args: { transfert_id: id } },
  ]);
  for (const [p] of mockInvoquer.mock.calls) expect(p).toMatchObject({ urlBase: mockSession.urlBase, jeton: mockSession.jeton });
  expect(mockObtenirDepot).toHaveBeenCalledTimes(1);
});
test("aucun rôle admin : pas de HTTP ni de bootstrap SQLite", async () => {
  mockAdmin = false;
  expect(await chargerDigestReception(date)).toBeNull(); expect(await chargerTransfertReception(id)).toBeNull();
  expect(mockInvoquer).not.toHaveBeenCalled(); expect(mockObtenirDepot).not.toHaveBeenCalled();
});
test("connectivité NetInfo retirée : seul digest personnel/daté vient du cache", async () => {
  await chargerDigestReception(date); mockInvoquer.mockClear(); actualiserConnectiviteTransferts(false);
  expect((await chargerDigestReception(date))?.source).toBe("cache");
  expect(await chargerTransfertReception(id)).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(mockInvoquer).not.toHaveBeenCalled(); expect(depot.cles()).toHaveLength(1);
});
test("la fiche avec contacts/messages n'initialise jamais le cache", async () => {
  const lu = await chargerTransfertReception(id);
  expect(lu?.source).toBe("serveur"); expect(mockObtenirDepot).not.toHaveBeenCalled(); expect(depot.cles()).toHaveLength(0);
});
test("retrait des scopes pendant la réponse garde la fiche tardive invisible", async () => {
  let finir!: (v: unknown) => void;
  mockInvoquer.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const pending = chargerTransfertReception(id); mockEpoch++;
  finir({ ok: true, result: f.plainte_ouverte.enveloppe });
  expect(await pending).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(mockObtenirDepot).not.toHaveBeenCalled();
});
