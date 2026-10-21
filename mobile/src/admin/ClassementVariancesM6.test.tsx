import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput } from "react-native";
import { BoutonSecondaire } from "./composants";
import captures from "../m6/fixturesClassementVariancesSQL.json";
import { lireVariancesClassables } from "../m6/classementVariance";
const cap = captures.captures.find(c => c.phase === "liste_initiale")!;
const parsed = lireVariancesClassables(cap.enveloppe, cap.request.arguments);
if (!parsed.ok) throw new Error("fixture producteur non reconnue");
const page = parsed.value, wct = page.wct.wct_id;
let mockEpoch = 0, mockAdmin = true, mockActif = true;
const mockListe = jest.fn(), mockHistorique = jest.fn(), mockSoumettre = jest.fn(), mockIntention = jest.fn();
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "admin-fictif" : "employee-fictif" }));
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const n = mockEpoch; return { session: mockAdmin ? { personne: "admin.contexte.fictif" } : null, courante: () => mockAdmin && n === mockEpoch };
} }));
jest.mock("./classementVariances", () => ({
  chargerVariancesClassablesM6: (...a: unknown[]) => mockListe(...a), chargerHistoriqueClassementsM6: (...a: unknown[]) => mockHistorique(...a),
  soumettreClassementVarianceM6: (...a: unknown[]) => mockSoumettre(...a), lireIntentionClassementM6: (...a: unknown[]) => mockIntention(...a),
  actualiserConnectiviteClassementM6: jest.fn(),
}));
const api = () => require("./ClassementVariancesM6").ClassementVariancesM6;
let tree: ReactTestRenderer | undefined;
const button = (suffix: string) => tree!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === `admin.classementVariances.${suffix}`)!;
const press = async (suffix: string) => { await act(async () => button(suffix).props.onPress()); };
const mount = async () => { const C = api(); await act(async () => { tree = create(<C wctId={wct} connected autorisee={() => mockActif} />); }); };
const text = () => JSON.stringify(tree!.toJSON());
beforeEach(() => {
  mockEpoch++; mockAdmin = true; mockActif = true; jest.clearAllMocks(); Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  mockListe.mockResolvedValue({ source: "serveur", valeur: page, misAJourLe: "2026-10-08T17:00:00Z" });
  mockIntention.mockResolvedValue({ genre: "aucune" }); mockSoumettre.mockResolvedValue({ genre: "en_attente", mutation: { id: "UUID-FICTIF" } });
});
afterEach(async () => { if (tree) await act(async () => tree!.unmount()); tree = undefined; });
test("cause jamais choisie automatiquement ; motif humain, source et révision attendue exacts", async () => {
  await mount(); await press("lire"); await press("choisir");
  expect(button("confirmer").props.desactive).toBe(true);
  await press("causes.waste"); await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : choix humain"));
  expect(button("confirmer").props.desactive).toBe(false); await press("confirmer");
  expect(mockSoumettre.mock.calls[0][0]).toEqual({ selection: page.lignes[0].selection, cause: "waste", motif: "FICTIF : choix humain", classement_attendu: null, references_pieces: [] });
  expect(text()).toContain("admin.classementVariances.enAttente"); expect(button("confirmer").props.desactive).toBe(true);
});
test("réseau interrompu cache la source et préserve le motif jusqu'à relecture courante", async () => {
  await mount(); await press("lire"); await press("choisir"); await press("causes.waste");
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : motif conservé"));
  const C = api(); await act(async () => tree!.update(<C wctId={null} connected={false} autorisee={() => mockActif} />));
  expect(text()).not.toContain(page.lignes[0].selection.materiau_id);
  await act(async () => tree!.update(<C wctId={wct} connected autorisee={() => mockActif} />));
  await press("lire"); await press("choisir");
  expect(tree!.root.findByType(TextInput).props.value).toBe("FICTIF : motif conservé");
});
test("rôle retiré ferme ancien callback et masque source/motif", async () => {
  await mount(); await press("lire"); const ancien = button("choisir").props.onPress;
  mockEpoch++; mockAdmin = false; const C = api(); await act(async () => tree!.update(<C wctId={wct} connected autorisee={() => mockActif} />));
  await act(async () => ancien()); expect(text()).not.toContain(page.lignes[0].selection.materiau_id);
  expect(mockSoumettre).not.toHaveBeenCalled();
});
test("réponse tardive après retrait de l'autorisation parent ne publie aucun ancien état", async () => {
  let terminer!: (v: unknown) => void; mockListe.mockImplementationOnce(() => new Promise(r => { terminer = r; }));
  await mount(); await press("lire"); mockActif = false;
  await act(async () => terminer({ source: "serveur", valeur: page, misAJourLe: "2026-10-08T17:00:00Z" }));
  expect(text()).not.toContain(page.lignes[0].selection.materiau_id);
});
test("ancien bouton confirmer de A fermé dès le choix de B", async () => {
  // Deuxième ligne FICTIVE de rendu seulement ; aucune nouvelle publication SQL n'est revendiquée.
  const b = { ...page.lignes[0], selection: { ...page.lignes[0].selection, position_ligne: 1, materiau_id: "MAT-B-RENDU-FICTIF" },
    source_ligne: { ...page.lignes[0].source_ligne, materiau: "MAT-B-RENDU-FICTIF" } };
  mockListe.mockResolvedValueOnce({ source: "serveur", valeur: { ...page, lignes: [page.lignes[0], b] }, misAJourLe: "2026-10-08T17:00:00Z" });
  await mount(); await press("lire"); await press("choisir"); await press("causes.waste");
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : cause A"));
  const ancien = button("confirmer").props.onPress;
  const choisirB = tree!.root.findAllByType(BoutonSecondaire).filter(v => v.props.texte === "admin.classementVariances.choisir")[1];
  await act(async () => choisirB.props.onPress()); await act(async () => ancien());
  expect(mockSoumettre).not.toHaveBeenCalled();
});
test("confirmation retire la page périmée jusqu'à relecture de la source", async () => {
  mockSoumettre.mockResolvedValueOnce({ genre: "confirmee", mutation: { id: "UUID-FICTIF" } });
  await mount(); await press("lire"); await press("choisir"); await press("causes.waste");
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : cause humaine"));
  await press("confirmer");
  expect(tree!.root.findAllByType(BoutonSecondaire).filter(v => v.props.texte === "admin.classementVariances.confirmer").length).toBe(0);
  expect(text()).toContain("admin.classementVariances.confirme");
});
test("ancien confirmer fermé dès la modification du motif humain", async () => {
  await mount(); await press("lire"); await press("choisir"); await press("causes.waste");
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : ancien motif"));
  const ancien = button("confirmer").props.onPress;
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : nouveau motif"));
  await act(async () => ancien()); expect(mockSoumettre).not.toHaveBeenCalled();
  await press("confirmer"); expect(mockSoumettre.mock.calls[0][0].motif).toBe("FICTIF : nouveau motif");
});
