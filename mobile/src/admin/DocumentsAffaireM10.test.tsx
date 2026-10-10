import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput } from "react-native";
import { BoutonSecondaire } from "./composants";
import { creerControleDocumentsAffaireM10 } from "../m10/documentsAffaireControle";
import { DepotOutboxMemoire } from "../outbox/depot";
import type { SessionEnvoi } from "../protocole/configuration";
let mockEpoch = 0, mockAdmin = true, mockFocused = true;
const mockT = (key: string, args?: unknown) => key + (args ? JSON.stringify(args) : "");
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));
jest.mock("expo-router", () => ({ useFocusEffect: (fn: () => (() => void)) => {
  const React = require("react"); React.useEffect(() => mockFocused ? fn() : undefined, [fn, mockFocused]);
} }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "admin-fictif" : "employee-fictif" }));
const mockCapture = () => { const e = mockEpoch; return { session: mockAdmin ? session : null, courante: () => mockAdmin && e === mockEpoch }; };
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => mockCapture() }));
let mockControle: ReturnType<typeof creerControleDocumentsAffaireM10>;
jest.mock("../m10/documentsAffaireControleService", () => ({ creerControleDocumentsAffaireService: () => mockControle }), { virtual: true });
const mockChargerPaquet = jest.fn(), mockRechargerMemoire = jest.fn(async () => undefined);
const mockRecherche = jest.fn((..._args: unknown[]) => null);
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockOnline }) }));
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "admin-fictif" : "employee-fictif" }), { virtual: true });
jest.mock("@/protocole/configuration", () => ({ capturerSessionAdminLecture: () => mockCapture() }), { virtual: true });
jest.mock("@/m10/service", () => ({ chargerPaquetAffaireMemoire: (...args: unknown[]) => mockChargerPaquet(...args), controleMemoire: {
  etat: () => ({ statut: "pret", signaux: null, catalogue: null, decisionId: null, revisionId: null, intentions: [] }),
  charger: () => mockRechargerMemoire(), invalider: jest.fn(), actualiserConnectivite: jest.fn(),
} }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("./composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("../ecrans/adminCommun"), { virtual: true });
jest.mock("@/ecrans/paquetAffaire", () => jest.requireActual("../ecrans/paquetAffaire"), { virtual: true });
jest.mock("@/m10/paquetAffaire", () => jest.requireActual("../m10/paquetAffaire"), { virtual: true });
jest.mock("@/admin/RechercheAffaireM10", () => ({ RechercheAffaireM10: (...args: unknown[]) => mockRecherche(...args) }), { virtual: true });
jest.mock("@/admin/DocumentsAffaireM10", () => jest.requireActual("./DocumentsAffaireM10"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
const mockInvoquer = jest.fn();
jest.mock("../protocole/client", () => ({ invoquerOutil: (...args: unknown[]) => mockInvoquer(...args) }));
jest.mock("../outbox/service", () => ({ obtenirDepot: async () => mockDepot,
  declencherVidange: (...args: unknown[]) => mockVidange(...args) }));
const Documents = require("./DocumentsAffaireM10").DocumentsAffaireM10;
const session: SessionEnvoi = { urlBase: "http://fictif.invalid", jeton: "jeton-fictif", personne: "admin_fictif", appareilId: "appareil-fictif" };
// Fixtures FICTIVES de rendu. Contrôleur et dépôt RAM réels ; transport et focus contrôlés, aucun téléphone.
const ref = { registre: "documents_affaire" as const, index: 0, ligne_id: "a".repeat(64) };
const ligne = { version_schema: 1 as const, affaire_id: "LEAD-FICTIF", document_ref: ref, version_source: ref,
  statut: "DEPOSEE_NON_ACTIVEE" as const, titre: "Titre serveur FICTIF", methode: "utf8-exact-v1" as const,
  source_sha256: "b".repeat(64), taille_points: 12, taille_octets: 12,
  auteur: { personne: "auteur_fictif", role: "admin" as const, source: "appareil" as const }, horodatage: "2026-10-10T00:00:00Z", activation_ref: null,
  version_no: 1, version_precedente_attendue: ref, activation_attendue: null };
const index = { version_schema: 1 as const, affaire_id: "LEAD-FICTIF", decalage: 0, limite: 1, total_versions: 1, suivant_decalage: null as number | null, versions: [ligne] };
const detail = { ...ligne, corps: "CORPS FICTIF" };
const serveur = <T,>(valeur: T) => ({ source: "serveur" as const, valeur });
let arbre: ReactTestRenderer | undefined, mockDepot: DepotOutboxMemoire, mockOnline: boolean;
const mockIndex = jest.fn(), mockVersion = jest.fn(), mockVidange = jest.fn(), mockId = jest.fn();
const props = () => ({ affaireId: "LEAD-FICTIF", ouverture: 1, connected: mockOnline });
const text = () => JSON.stringify(arbre!.toJSON());
const button = (key: string) => arbre!.root.findAllByType(BoutonSecondaire).find(v => v.props.texte === `admin.documentsAffaire.${key}`)!;
const click = async (key: string) => { await act(async () => button(key).props.onPress()); };
const mount = async () => { await act(async () => { arbre = create(<Documents {...props()} />); }); };
const saisir = async (titre = "Brouillon FICTIF", corps = "Aé😀\r\nZ") => { await act(async () => {
  arbre!.root.findAllByType(TextInput)[0].props.onChangeText(titre);
}); await act(async () => arbre!.root.findAllByType(TextInput)[1].props.onChangeText(corps)); };
beforeEach(() => {
  jest.clearAllMocks(); mockEpoch++; mockAdmin = true; mockFocused = true; mockOnline = true; mockDepot = new DepotOutboxMemoire();
  mockChargerPaquet.mockResolvedValue({ source: "aucune", raison: { code: "fictif", detail: "" } });
  mockIndex.mockResolvedValue(serveur(index)); mockVersion.mockResolvedValue(serveur(detail)); mockVidange.mockResolvedValue(null); mockId.mockReturnValue("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  mockControle = creerControleDocumentsAffaireM10({ capturerSession: mockCapture, enLigne: () => mockOnline,
    chargerIndex: mockIndex, chargerVersion: mockVersion, obtenirDepot: async () => mockDepot,
    vidanger: mockVidange, genererId: mockId, horloge: () => ({ maintenant: new Date("2026-10-10T01:00:00Z"), decalageMinutesUTC: 0 }) });
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
});
afterEach(async () => { if (arbre) await act(async () => arbre!.unmount()); arbre = undefined; });
test("l’index courant ne charge aucun corps ; la sélection explicite lit la version exacte", async () => {
  await mount(); expect(mockIndex).toHaveBeenCalledWith("LEAD-FICTIF", 0, 1); expect(mockVersion).not.toHaveBeenCalled();
  expect(text()).toContain("Titre serveur FICTIF"); expect(text()).toContain("admin.documentsAffaire.pagesCourantes");
  await click("lireVersion"); expect(mockVersion).toHaveBeenCalledWith("LEAD-FICTIF", ref, ref);
  expect(text()).toContain("CORPS FICTIF"); expect(text()).toContain("auteur_fictif"); expect(text()).toContain("2026-10-10T00:00:00Z");
});
test("le brouillon RAM conserve ses octets hors ligne et au retour sans envoi automatique", async () => {
  await mount(); await saisir(); mockOnline = false; await act(async () => arbre!.update(<Documents {...props()} />));
  expect(arbre!.root.findAllByType(TextInput).map(v => v.props.value)).toEqual(["Brouillon FICTIF", "Aé😀\r\nZ"]);
  expect(button("deposer").props.desactive).toBe(true); expect(mockVidange).not.toHaveBeenCalled();
  mockOnline = true; await act(async () => arbre!.update(<Documents {...props()} />));
  expect(arbre!.root.findAllByType(TextInput)[1].props.value).toBe("Aé😀\r\nZ"); expect(mockVidange).not.toHaveBeenCalled();
});
test("déposer persiste une seule intention, sans activation ; reprendre conserve son UUID", async () => {
  await mount(); await saisir(); await click("deposer");
  expect((await mockDepot.lister()).map(v => v.type)).toEqual(["document_m10_depot"]); expect(mockId).toHaveBeenCalledTimes(1);
  expect(text()).toContain("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"); expect(text()).toContain("admin.documentsAffaire.messages.intention_incertaine");
  await click("reprendre"); expect(mockId).toHaveBeenCalledTimes(1); expect(await mockDepot.lister()).toHaveLength(1);
  expect(button("deposer").props.desactive).toBe(true);
});
test("une version retirée n’offre ni corps ni geste de mutation", async () => {
  mockIndex.mockResolvedValue(serveur({ ...index, versions: [{ ...ligne, statut: "RETIREE" }] }));
  await mount(); await click("lireVersion"); expect(mockVersion).not.toHaveBeenCalled();
  expect(button("deposer").props.desactive).toBe(true); expect(button("activer").props.desactive).toBe(true); expect(button("retirer").props.desactive).toBe(true);
});
test("blur invalide le détail tardif et focus relit seulement l’index", async () => {
  let fin!: (v: unknown) => void; mockVersion.mockImplementationOnce(() => new Promise(r => { fin = r; }));
  await mount(); await click("lireVersion"); mockFocused = false; await act(async () => arbre!.update(<Documents {...props()} />));
  await act(async () => fin(serveur(detail))); expect(text()).not.toContain("CORPS FICTIF");
  mockFocused = true; await act(async () => arbre!.update(<Documents {...props()} />)); expect(mockIndex).toHaveBeenCalledTimes(2); expect(mockVidange).not.toHaveBeenCalled();
});
test("la révocation masque titre, corps et brouillon ; un ancien callback ne les ressuscite pas", async () => {
  await mount(); await saisir(); await click("lireVersion"); const ancien = button("activer").props.onPress;
  mockEpoch++; mockAdmin = false; await act(async () => arbre!.update(<Documents {...props()} />));
  expect(text()).not.toContain("Titre serveur FICTIF"); expect(text()).not.toContain("CORPS FICTIF"); expect(text()).not.toContain("Brouillon FICTIF");
  await act(async () => ancien()); expect(mockId).not.toHaveBeenCalled(); expect(await mockDepot.lister()).toHaveLength(0);
});
test("le modèle garde les limites 120/2000 sans tronquer ou normaliser la saisie", async () => {
  await mount(); await saisir("é".repeat(121), "😀".repeat(2001));
  expect(arbre!.root.findAllByType(TextInput)[0].props.value).toHaveLength(121);
  expect(arbre!.root.findAllByType(TextInput)[1].props.value).toBe("😀".repeat(2001));
  expect(button("deposer").props.desactive).toBe(true); await click("deposer"); expect(mockId).not.toHaveBeenCalled();
});

test("un ancien bouton d’activation ne décide pas pour une nouvelle sélection", async () => {
  await mount(); await click("lireVersion"); const ancien = button("activer").props.onPress;
  await click("nouveau"); await act(async () => ancien());
  expect(await mockDepot.lister()).toHaveLength(0); expect(mockId).not.toHaveBeenCalled();
});
test("la suite remplace l’index et ferme le corps, sans écraser le brouillon", async () => {
  mockIndex.mockResolvedValueOnce(serveur({ ...index, total_versions: 2, suivant_decalage: 1 }));
  await mount(); await click("lireVersion"); await saisir();
  mockIndex.mockResolvedValueOnce(serveur({ ...index, decalage: 1, total_versions: 2, versions: [{ ...ligne, titre: "SECONDE FICTIVE" }] }));
  await click("suite"); expect(mockIndex).toHaveBeenLastCalledWith("LEAD-FICTIF", 1, 1);
  expect(text()).not.toContain("Titre serveur FICTIF"); expect(text()).not.toContain("CORPS FICTIF"); expect(text()).toContain("SECONDE FICTIVE");
  expect(arbre!.root.findAllByType(TextInput)[0].props.value).toBe("Brouillon FICTIF"); expect(button("deposer").props.desactive).toBe(true);
});
test("refus de la nouvelle page ne reprend jamais l’ancien corps", async () => {
  await mount(); await click("lireVersion"); mockIndex.mockResolvedValueOnce({ source: "refus", verdict: { code: "REFUS-FICTIF", detail: "CANARI-TECHNIQUE" } });
  await click("rafraichir"); expect(text()).not.toContain("CORPS FICTIF"); expect(text()).not.toContain("Titre serveur FICTIF");
  expect(text()).not.toContain("CANARI-TECHNIQUE"); expect(text()).toContain("admin.documentsAffaire.refus"); expect(button("activer").props.desactive).toBe(true);
});

test("redémarrage hors ligne sans affaire choisie : les intentions durables sont visibles, aucun RPC", async () => {
  const { creerMutationDocumentM10 } = require("../m10/documentsAffaireOutbox");
  await mockDepot.inserer(creerMutationDocumentM10("deposer", { affaire_id: "LEAD-FICTIF", document_ref: null, version_precedente: null,
    titre: "Intention FICTIVE", corps: "Texte FICTIF", confidentialite: "INTERNAL" }, () => "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    { maintenant: new Date("2026-10-10T01:00:00Z"), decalageMinutesUTC: 0 }, session));
  mockOnline = false;
  await act(async () => { arbre = create(<Documents {...props()} affaireId={null} />); });
  expect(text()).toContain("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"); expect(button("reprendre").props.desactive).toBe(true);
  expect(mockIndex).not.toHaveBeenCalled(); expect(mockVersion).not.toHaveBeenCalled(); expect(mockVidange).not.toHaveBeenCalled();
});
test("un jeton remplacé masque le brouillon et ferme le détail différé à personne/rôle égaux", async () => {
  let fin!: (v: unknown) => void; mockVersion.mockImplementationOnce(() => new Promise(r => { fin = r; }));
  await mount(); await click("lireVersion"); await saisir();
  const callback = arbre!.root.findAllByType(TextInput)[0].props.onChangeText;
  mockEpoch++; await act(async () => arbre!.update(<Documents {...props()} />));
  await act(async () => { fin(serveur(detail)); callback("ANCIEN SECRET FICTIF"); });
  expect(text()).not.toContain("Brouillon FICTIF"); expect(text()).not.toContain("CORPS FICTIF"); expect(text()).not.toContain("ANCIEN SECRET FICTIF");
  expect(mockVidange).not.toHaveBeenCalled();
});
test("le retour tardif d’un envoi ne montre pas l’UUID après retrait du rôle", async () => {
  let fin!: () => void; mockVidange.mockImplementationOnce(() => new Promise<void>(r => { fin = r; }));
  await mount(); await saisir(); await click("deposer"); expect(await mockDepot.lister()).toHaveLength(1);
  mockEpoch++; mockAdmin = false; await act(async () => arbre!.update(<Documents {...props()} />));
  await act(async () => fin()); expect(text()).not.toContain("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  expect(mockId).toHaveBeenCalledTimes(1);
});

test.each(["envoyee", "echec_permanent"] as const)("intention %s : statut local explicitement borné, reprise sans nouvel UUID", async statut => {
  const { creerMutationDocumentM10 } = require("../m10/documentsAffaireOutbox");
  const m = creerMutationDocumentM10("deposer", { affaire_id: "LEAD-FICTIF", document_ref: null, version_precedente: null,
    titre: "Intention FICTIVE", corps: "Texte FICTIF", confidentialite: "INTERNAL" }, () => "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    { maintenant: new Date("2026-10-10T01:00:00Z"), decalageMinutesUTC: 0 }, session);
  await mockDepot.inserer({ ...m, statut, resumeAccepte: { fictif: true, invalide: true } });
  await mount(); expect(text()).toContain(`admin.documentsAffaire.etatsFile.${statut}`);
  expect(button("deposer").props.desactive).toBe(true); await click("reprendre");
  expect(mockId).not.toHaveBeenCalled(); expect(mockVidange).not.toHaveBeenCalled();
  expect(text()).toContain("cccccccc-cccc-4ccc-8ccc-cccccccccccc");
});

test("la route garde le brouillon documentaire quand recherche et rafraîchissement effacent le paquet", async () => {
  const EcranMemoire = require("../../app/(admin)/memoire").default;
  await act(async () => { arbre = create(<EcranMemoire />); });
  const recherche = () => mockRecherche.mock.calls.at(-1)![0] as { onOuvrir: (id: string) => void; onInvalider: () => void };
  await act(async () => recherche().onOuvrir("LEAD-FICTIF"));
  expect(mockChargerPaquet).toHaveBeenCalledWith("LEAD-FICTIF", expect.any(String));
  expect(mockIndex).toHaveBeenCalledWith("LEAD-FICTIF", 0, 1);
  await saisir(); await act(async () => recherche().onInvalider());
  const actualiser = arbre!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === "admin.commun.rafraichir")!;
  await act(async () => actualiser.props.onPress());
  expect(arbre!.root.findAllByType(TextInput).map(v => v.props.value)).toEqual(["Brouillon FICTIF", "Aé😀\r\nZ"]);
  expect(mockVidange).not.toHaveBeenCalled(); expect(mockId).not.toHaveBeenCalled();
});

test.each(["activer", "retirer"] as const)("le geste %s soumet seulement la commande sélectionnée", async operation => {
  await mount(); await click("lireVersion"); expect(await mockDepot.lister()).toHaveLength(0);
  await click(operation); const file = await mockDepot.lister();
  expect(file).toHaveLength(1); expect(file[0].type).toBe(operation === "activer" ? "document_m10_activation" : "document_m10_retrait");
  expect(file[0].payload.commande).toEqual(operation === "activer" ?
    { affaire_id: "LEAD-FICTIF", document_ref: ref, version_source: ref, activation_attendue: null } :
    { affaire_id: "LEAD-FICTIF", document_ref: ref, activation_attendue: null, code_motif: "RETRAIT_ACCES" });
  expect(mockId).toHaveBeenCalledTimes(1); expect(mockVidange).toHaveBeenCalledTimes(1);
});

test("le service de contrôle appelle le vrai binding T0 sans horloge ni cache, et relit la connectivité", async () => {
  // Enveloppe FICTIVE, pas une capture native. Seul le transport est substitué ici.
  mockInvoquer.mockResolvedValue({ ok: true, result: { ok: true, resultat: { accepte: true, resultat: index } } });
  const service = jest.requireActual("../m10/documentsAffaireControleService") as typeof import("../m10/documentsAffaireControleService");
  const c = service.creerControleDocumentsAffaireService(() => mockOnline);
  c.actualiserConnectivite(true); await c.ouvrirAffaire("LEAD-FICTIF");
  expect(c.etat().page).toEqual({ source: "serveur", valeur: index });
  expect(mockInvoquer.mock.calls.map(v => v[0].requete)).toEqual([
    { tool: "m10_lister_documents_affaire_appareil", args: { affaire_id: "LEAD-FICTIF", decalage: 0, limite: 1 } },
  ]);
  mockOnline = false; c.actualiserConnectivite(false); await c.rafraichir();
  expect(c.etat().page).toBeNull(); expect(mockInvoquer).toHaveBeenCalledTimes(1); expect(mockVidange).not.toHaveBeenCalled();
});

test("le retour d’envoi après blur et nouveau focus libère l’indicateur sans adopter une réponse tardive", async () => {
  let fin!: () => void; mockVidange.mockImplementationOnce(() => new Promise<void>(r => { fin = r; }));
  await mount(); await saisir(); await click("deposer");
  mockFocused = false; await act(async () => arbre!.update(<Documents {...props()} />));
  mockFocused = true; await act(async () => arbre!.update(<Documents {...props()} />));
  expect(button("rafraichir").props.desactive).toBe(true);
  await act(async () => fin());
  expect(button("rafraichir").props.desactive).toBe(false);
  expect(mockId).toHaveBeenCalledTimes(1); expect(text()).toContain("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  expect(mockVersion).not.toHaveBeenCalled();
});
