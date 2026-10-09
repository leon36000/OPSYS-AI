import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput } from "react-native";
import { DepotOutboxMemoire } from "../outbox/depot";
import { BoutonSecondaire } from "./composants";
import cap from "../m4/fixturesRevueCompletionCapSQL.json";
import { lireDossierRevueCompletion } from "../m4/revueCompletionSources";
let mockEpoch = 0, mockAdmin = true, mockFocus = true, mockConnected = true;
const mockLire = jest.fn(), mockProposer = jest.fn(), mockDecider = jest.fn(), mockIntention = jest.fn(), mockOwner = jest.fn();
const mockDemandes = jest.fn(); let mockParentDepot = new DepotOutboxMemoire();
jest.mock("expo-router", () => ({ useFocusEffect: (f: () => void | (() => void)) => require("react").useEffect(f, [f]),
  Link: (p: unknown) => require("react").createElement("FictifLink", p) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("../approbations/service", () => ({ chargerDemandesApprobation: (...a: unknown[]) => mockDemandes(...a) }));
jest.mock("../outbox/service", () => ({ obtenirDepot: async () => mockParentDepot, declencherVidange: jest.fn(async () => null) }));
jest.mock("../outbox/declencheurs", () => ({ demarrerDeclencheursVidange: () => () => undefined }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "ADMIN-FICTIF" : "EMPLOYEE-FICTIF" }));
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const n = mockEpoch; return { session: mockAdmin ? { personne: "ADMIN-FICTIF" } : null, courante: () => mockAdmin && n === mockEpoch };
} }));
jest.mock("./revueCompletionSources", () => ({
  chargerDossierRevueCompletion: (...a: unknown[]) => mockLire(...a), proposerRevueCompletion: (...a: unknown[]) => mockProposer(...a),
  deciderRevueCompletion: (...a: unknown[]) => mockDecider(...a), lireIntentionRevueCompletion: (...a: unknown[]) => mockIntention(...a),
  chargerProprietaireRevueCompletion: (...a: unknown[]) => mockOwner(...a), actualiserConnectiviteRevueCompletion: jest.fn(),
}));
const lc = lireDossierRevueCompletion(cap.lectures[0].reponse, cap.lectures[0].arguments);
if (!lc.ok || lc.value.lecture !== "courante") throw new Error("capture courante SQL attendue");
const current = lc.value;
const lh = lireDossierRevueCompletion(cap.lectures[1].reponse, cap.lectures[1].arguments);
if (!lh.ok || lh.value.lecture !== "historique") throw new Error("capture historique SQL attendue");
const history = lh.value;
// Variante de rendu RAM : une demande en attente, aucun nouveau fait SQLite revendiqué.
const hist = { ...history, demande: {
  ...history.demande, statut: "en_attente", decide_par: null, decide_role: null, decide_le: null,
}, issue: null, preuve_completion: null };
const api = () => require("./RevueCompletionSourcesM4").RevueCompletionSourcesM4;
let tree: ReactTestRenderer | undefined;
const props = (demande: string | null = null) => ({ interventionId: current.intervention_id, demandeId: demande, connected: true, autorisee: () => mockFocus });
const button = (n: string) => tree!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === `admin.revueCompletion.${n}`)!;
const press = async (n: string) => { await act(async () => button(n).props.onPress()); };
const mount = async (demande: string | null = null) => { const C = api(); await act(async () => { tree = create(<C {...props(demande)} />); }); };
const text = () => JSON.stringify(tree!.toJSON());
beforeEach(() => { mockEpoch++; mockAdmin = true; mockFocus = true; mockConnected = true; mockParentDepot = new DepotOutboxMemoire(); jest.clearAllMocks(); Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  mockLire.mockResolvedValue({ source: "serveur", valeur: current, misAJourLe: "2026-10-09T12:00:00Z" });
  mockIntention.mockResolvedValue({ genre: "aucune" }); mockOwner.mockResolvedValue(false);
  mockProposer.mockResolvedValue({ genre: "en_attente", mutation: { id: "UUID-P-FICTIF" } });
  mockDecider.mockResolvedValue({ genre: "en_attente", mutation: { id: "UUID-D-FICTIF" } });
});
afterEach(async () => { if (tree) await act(async () => tree!.unmount()); tree = undefined; });
test("aucune décision/cause automatique ; P confirme une proposition puis retire sa page", async () => {
  await mount(); await press("lire"); expect(button("proposer").props.desactive).toBe(true);
  await press("correction"); await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : correction humaine"));
  expect(button("proposer").props.desactive).toBe(false); await press("proposer");
  expect(mockProposer.mock.calls[0].slice(0, 3)).toEqual([current, "correction", "FICTIF : correction humaine"]);
  expect(text()).not.toContain(current.sources.completion_ligne_id); expect(text()).toContain("admin.revueCompletion.enAttente");
  expect(mockDecider).not.toHaveBeenCalled();
});
test("historique immuable + owner serveur seulement pour D, absence de preuve demeure attente", async () => {
  mockLire.mockResolvedValue({ source: "serveur", valeur: hist, misAJourLe: "2026-10-09T12:00:00Z" }); mockOwner.mockResolvedValue(true);
  await mount(cap.decision.arguments.demande_id); await press("lire");
  expect(text()).toContain(hist.demande.arguments.motif); await press("approuver");
  expect(mockDecider.mock.calls[0].slice(0, 4)).toEqual([hist, "approuver", undefined, true]);
  expect(text()).toContain("admin.revueCompletion.enAttente"); expect(text()).not.toContain(hist.demande.arguments.motif);
});
test("admin non owner ne reçoit aucun bouton D", async () => {
  mockLire.mockResolvedValue({ source: "serveur", valeur: hist, misAJourLe: "2026-10-09T12:00:00Z" });
  await mount(cap.decision.arguments.demande_id); await press("lire");
  expect(button("approuver")).toBeUndefined(); expect(text()).toContain("admin.revueCompletion.ownerRequis");
});
test("A vers B vers A ferme l'ancien callback et n'adopte pas l'ancienne source", async () => {
  await mount(); await press("lire"); await press("correction");
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : A"));
  const old = button("proposer").props.onPress, C = api();
  await act(async () => tree!.update(<C {...props()} interventionId="INTERV-B-FICTIVE" />));
  await act(async () => tree!.update(<C {...props()} />)); await act(async () => old());
  expect(mockProposer).not.toHaveBeenCalled(); expect(text()).not.toContain(current.sources.completion_ligne_id);
});
test("ancien confirmer et réponse tardive fermés après saisie/role/focus", async () => {
  await mount(); await press("lire"); await press("correction");
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : original")); const old = button("proposer").props.onPress;
  await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF : autre")); await act(async () => old());
  expect(mockProposer).not.toHaveBeenCalled();
  let fin!: (v: unknown) => void; mockLire.mockImplementationOnce(() => new Promise(r => { fin = r; }));
  await press("lire"); mockFocus = false; mockEpoch++;
  await act(async () => fin({ source: "serveur", valeur: current, misAJourLe: "2026-10-09T12:00:00Z" }));
  expect(text()).not.toContain(current.sources.completion_ligne_id);
});
test("deux pressions synchrones n'enfilent qu'une seule proposition", async () => {
  await mount(); await press("lire"); await press("correction"); await act(async () => tree!.root.findByType(TextInput).props.onChangeText("FICTIF"));
  const cb = button("proposer").props.onPress; await act(async () => { cb(); cb(); }); expect(mockProposer).toHaveBeenCalledTimes(1);
});

const demandeParent = (outil: string, id: string) => ({ id, outil, departement: "m04-field-ops", departementNom: null,
  niveau: "N4", depuis: "2026-10-09T12:00:00Z", motifDemande: null, descriptionOutil: null,
  arguments: { intervention_id: current.intervention_id }, decidable: true, lectureSeule: null });
function listeParent() { return { source: "serveur", liste: { demandes: [demandeParent("m4_resoudre_revue_completion_sources", "APP-TYPED-FICTIVE"),
  demandeParent("m4_resoudre_revue_completion", "APP-LEGACY-FICTIVE")], proprietaire: true, totalEnAttente: 2, affichees: 2, reste: 0, illisibles: 0,
  attentes: { items: [{ id: current.intervention_id, departement: "m04-field-ops", departementNom: null, type: "completion_en_revue", niveau: "N4",
    resume: "FICTIF : attente M4", depuis: "2026-10-09T12:00:00Z", actionProposee: null }], total: 1, reste: 0, decalage: 0, suivant: null, illisibles: 0, departementsIllisibles: [] } } }; }
const parentButtons = (key: string) => tree!.root.findAll(n => typeof n.props.onPress === "function" &&
  n.findAll(t => t.props.children === key || Array.isArray(t.props.children) && t.props.children.includes(key)).length > 0)
  .filter((n, i, a) => a.findIndex(x => x.props.onPress === n.props.onPress) === i);
const parentButton = (key: string) => parentButtons(key)[0];
test("Approbations parent : attente ouvre le courant, P ouvre l'historique, anciens boutons legacy conservés", async () => {
  mockDemandes.mockResolvedValue(listeParent()); const C = require("../../app/(admin)/approvals").default;
  await act(async () => { tree = create(<C />); });
  const liens = tree!.root.findAll(n => String(n.type) === "FictifLink");
  expect(liens.map(n => n.props.href)).toEqual(expect.arrayContaining([
    { pathname: "/revue-completion", params: { intervention: current.intervention_id } },
    { pathname: "/revue-completion", params: { intervention: current.intervention_id, demande: "APP-TYPED-FICTIVE" } },
  ]));
  expect(parentButtons("approvals.approuver")).toHaveLength(1);
});
test("Approbations parent : ancien confirmer fermé après nouvelle personne, aucune intention insérée", async () => {
  mockDemandes.mockResolvedValue(listeParent()); const C = require("../../app/(admin)/approvals").default;
  await act(async () => { tree = create(<C />); });
  await act(async () => parentButton("approvals.approuver").props.onPress());
  const old = parentButton("approvals.confirmerApprouver").props.onPress;
  const inserer = jest.spyOn(mockParentDepot, "inserer"); mockEpoch++; mockAdmin = false;
  await act(async () => { tree!.update(<C />); }); await act(async () => old());
  expect(inserer).not.toHaveBeenCalled(); expect(text()).not.toContain("APP-LEGACY-FICTIVE"); inserer.mockRestore();
});

test("décision legacy vue en ligne puis confirmée hors ligne conserve une mise en file, sans D typée", async () => {
  mockDemandes.mockResolvedValue(listeParent()); const C = require("../../app/(admin)/approvals").default;
  await act(async () => { tree = create(<C />); });
  await act(async () => parentButton("approvals.approuver").props.onPress());
  const confirmer = parentButton("approvals.confirmerApprouver").props.onPress;
  mockConnected = false; await act(async () => tree!.update(<C />)); await act(async () => confirmer());
  const file = await mockParentDepot.lister(); expect(file).toHaveLength(1);
  expect(file[0]).toMatchObject({ type: "approval_decision", chantierId: "approbations", statut: "en_attente",
    proprietaire: "ADMIN-FICTIF", payload: { demande_id: "APP-LEGACY-FICTIVE", decision: "approuver" } });
  expect(mockDecider).not.toHaveBeenCalled();
});
