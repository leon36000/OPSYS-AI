import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire } from "./composants";
import captures from "../m1/fixturesRappelsSQL.json";
import { lireRappelsM1 } from "../m1/rappelsAppareil";
const c = captures.captures.find(c => c.phase === "page_premiere")!, lu = lireRappelsM1(c.response, c.request.arguments);
if (!lu.ok) throw new Error("capture producteur refusée");
const page = lu.value;
let mockEpoch = 0, mockAdmin = true, mockActif = true;
const mockCharger = jest.fn(), mockSoumettre = jest.fn(), mockIntention = jest.fn(), mockReprendre = jest.fn();
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
jest.mock("expo-router", () => ({ Link: ({ children }: { children: React.ReactNode }) => children }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "admin-fictif" : "employee-fictif" }));
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const n = mockEpoch; return { session: mockAdmin ? { personne: "admin-rappel-fictif" } : null, courante: () => mockAdmin && n === mockEpoch };
} }));
jest.mock("./rappelsM1", () => ({ actualiserConnectiviteRappelsM1: jest.fn(), chargerRappelsM1: (...a: unknown[]) => mockCharger(...a),
  soumettrePriseRappelM1: (...a: unknown[]) => mockSoumettre(...a), lireIntentionRappelM1: (...a: unknown[]) => mockIntention(...a), reprendrePriseRappelM1: (...a: unknown[]) => mockReprendre(...a) }));
const api = () => require("./RappelsM1").RappelsM1;
let tree: ReactTestRenderer | undefined;
const boutons = (suffix: string) => tree!.root.findAllByType(BoutonSecondaire).filter(b => b.props.texte === `admin.rappelsM1.${suffix}`);
const press = async (suffix: string, position = 0) => { await act(async () => boutons(suffix)[position].props.onPress()); };
const mount = async () => { const C = api(); await act(async () => { tree = create(<C connected autorisee={() => mockActif} />); }); };
const text = () => JSON.stringify(tree!.toJSON());
beforeEach(() => { mockEpoch++; mockAdmin = true; mockActif = true; jest.clearAllMocks(); Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  mockCharger.mockResolvedValue({ source: "serveur", valeur: page, misAJourLe: "2026-10-09T04:00:00Z" }); mockIntention.mockResolvedValue({ genre: "aucune" });
  mockSoumettre.mockResolvedValue({ genre: "en_attente" }); mockReprendre.mockResolvedValue({ genre: "en_attente" }); });
afterEach(async () => { if (tree) await act(async () => tree!.unmount()); tree = undefined; });
test("une prise est explicitement choisie et conserve les deux args source exacts", async () => {
  await mount(); expect(mockCharger).not.toHaveBeenCalled(); await press("lire");
  expect(mockCharger).toHaveBeenCalledWith(null, 8); expect(text()).toContain(page.rappels[0].derniere_source.ligne_id);
  expect(mockSoumettre).not.toHaveBeenCalled(); await press("choisir"); await press("prendre");
  expect(mockSoumettre.mock.calls[0][0]).toEqual({ transfert_id: page.rappels[0].transfert_id, snapshot_attendu: page.rappels[0].suivi_rappel.snapshot_suivi });
  expect(text()).toContain("admin.rappelsM1.enAttente"); expect(boutons("prendre")[0].props.desactive).toBe(true);
});
test("page suivante remplace, première relit sans concaténation ni snapshot fixe", async () => {
  await mount(); await press("lire"); await press("suite"); expect(mockCharger).toHaveBeenLastCalledWith(page.page.apres_suivant, 8);
  const other = { ...page, rappels: [page.rappels[1]], page: { ...page.page, apres_suivant: null } }; mockCharger.mockResolvedValue({ source: "serveur", valeur: other });
  await press("lire"); expect(text()).not.toContain(page.rappels[0].transfert_id); expect(text()).toContain(page.rappels[1].transfert_id);
});
test("ancien prendre fermé dès nouvelle sélection même si callback conservé", async () => {
  await mount(); await press("lire"); await press("choisir", 0); const ancien = boutons("prendre")[0].props.onPress;
  await press("choisir", 1); await act(async () => ancien()); expect(mockSoumettre).not.toHaveBeenCalled();
});
test.each(["confirmee", "refusee"])("après %s la page est retirée jusqu'à relecture", async genre => {
  mockSoumettre.mockResolvedValue({ genre }); await mount(); await press("lire"); await press("choisir"); await press("prendre");
  expect(text()).not.toContain(page.rappels[0].derniere_source.ligne_id); expect(boutons("choisir")).toHaveLength(0);
});
test("offline/role/focus masque la page et ferme les anciennes actions", async () => {
  await mount(); await press("lire"); await press("choisir"); const ancien = boutons("prendre")[0].props.onPress;
  const C = api(); await act(async () => tree!.update(<C connected={false} autorisee={() => mockActif} />));
  expect(text()).not.toContain(page.rappels[0].derniere_source.ligne_id); await act(async () => ancien()); expect(mockSoumettre).not.toHaveBeenCalled();
  mockActif = false; mockEpoch++; await act(async () => tree!.update(<C connected autorisee={() => mockActif} />));
  await act(async () => ancien()); expect(mockSoumettre).not.toHaveBeenCalled();
});
test("lecture en retard après retrait admin n'expose aucun résultat", async () => {
  let terminer!: (v: unknown) => void; mockCharger.mockImplementationOnce(() => new Promise(resolve => { terminer = resolve; }));
  await mount(); await act(async () => { boutons("lire")[0].props.onPress(); }); mockAdmin = false; mockEpoch++;
  await act(async () => { terminer({ source: "serveur", valeur: page }); }); expect(text()).not.toContain(page.rappels[0].derniere_source.ligne_id);
});
test("quarantaine bloque prise et reprise sans créer de nouvelle intention", async () => {
  mockIntention.mockResolvedValue({ genre: "quarantaine" }); await mount(); await press("lire"); await press("choisir");
  expect(text()).toContain("admin.rappelsM1.quarantaine"); expect(boutons("prendre")[0].props.desactive).toBe(true);
  await press("prendre"); expect(mockSoumettre).not.toHaveBeenCalled(); expect(mockReprendre).not.toHaveBeenCalled();
});
