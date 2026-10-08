import React from "react";
import { ActivityIndicator } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import type { EtatMemoire } from "../m10/controle";
import { BoutonSecondaire } from "../admin/composants";
import { FIXTURES_DOSSIER_M10 } from "../m10/fixturesDossier";
import { lireDossierRevisionM10 } from "../m10/dossier";
import adminFr from "../i18n/locales/admin.fr-CA";
import adminEn from "../i18n/locales/admin.en-CA";

let mockGeneration = 0, mockConnected = true;
let mockSession = { presente: true, role: "admin" };
let mockState: EtatMemoire;
const mockT = (k: string, p?: unknown) => k + (p ? JSON.stringify(p) : "");
jest.mock("expo-router", () => ({ useFocusEffect: (f: () => void | (() => void)) => { require("react").useEffect(f, [f]); } }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => mockSession }), { virtual: true });
jest.mock("@/protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const epoch = mockGeneration;
  return { session: mockSession.role === "admin" ? { personne: "admin-fictif", jeton: "fictif" } : null,
    courante: () => epoch === mockGeneration && mockSession.role === "admin" };
} }), { virtual: true });
jest.mock("@/m10/service", () => ({ controleMemoire: {
  etat: jest.fn(() => mockState), charger: jest.fn(async () => undefined), chargerSuite: jest.fn(async () => undefined),
  ouvrirRevision: jest.fn(async () => undefined), lireDecision: jest.fn(async () => undefined),
  arbitrer: jest.fn(async () => undefined), peutArbitrer: jest.fn(() => false), invalider: jest.fn(), actualiserConnectivite: jest.fn(),
} }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
const control = require("@/m10/service").controleMemoire;
const Ecran = require("../../app/(admin)/memoire").default;
const serveur = <T,>(valeur: T) => ({ source: "serveur" as const, valeur, misAJourLe: "2026-10-07T12:00:00Z" });
const dossier = lireDossierRevisionM10(FIXTURES_DOSSIER_M10.reponses.dossier_complet.enveloppe);
if (!dossier.ok) throw new Error("Dossier natif illisible");
const natif = dossier.value;
let arbre: ReactTestRenderer | undefined;
beforeEach(() => {
  jest.clearAllMocks(); mockGeneration = 0; mockConnected = true; mockSession = { presente: true, role: "admin" };
  control.peutArbitrer.mockReturnValue(false); control.arbitrer.mockResolvedValue(undefined);
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  mockState = { statut: "pret", enLigne: true, signaux: serveur({ signaux: [], nb_total: 50, nb_omis: 50, nb_ouverts: 50, nb_pris_en_compte: 0, nb_clos: 0 }),
    catalogue: serveur({ decisions: [], revisions: [natif.revision], decalage: 0, suivant: 8, reste: 10, total: 11, affichees: 1, limite: 8,
      borne_caracteres: 5400, taille_caracteres: 1700, confidentialite: { regle: "v1", nb_retenus: 3 } }),
    dossier: null, statutDecision: null, statutRevision: null, decisionId: null, revisionId: null,
    intentions: [], messageCode: null, message: null, sourceDate: null };
});
afterEach(async () => { if (arbre) await act(async () => arbre!.unmount()); arbre = undefined; });
const texte = () => JSON.stringify(arbre!.toJSON());
const bouton = (cle: string) => arbre!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === cle)!;

test("sections, omissions et pages courantes restent explicites ; aucune décision métier créée", async () => {
  expect(FIXTURES_DOSSIER_M10.fictif).toBe(true);
  await act(async () => { arbre = create(<Ecran />); });
  expect(texte()).toContain("admin.memoire.signaux"); expect(texte()).toContain("admin.memoire.decisions");
  expect(texte()).toContain("admin.memoire.revisions"); expect(texte()).toContain('\\"omis\\":50');
  expect(texte()).toContain("admin.memoire.pagesCourantes"); expect(control.arbitrer).not.toHaveBeenCalled();
  await act(async () => bouton("admin.memoire.suite").props.onPress());
  expect(control.chargerSuite).toHaveBeenCalledTimes(1);
});
test("les deux faits exacts précèdent les quatre choix ; le choix en cours bloque rafraîchir", async () => {
  mockState = { ...mockState, dossier: serveur(natif), statutRevision: serveur({ statut: natif.revision.statut }), revisionId: natif.revision.revision_ligne_id };
  control.peutArbitrer.mockReturnValue(true);
  let finir!: () => void;
  control.arbitrer.mockImplementationOnce(() => {
    mockState = { ...mockState, statut: "arbitrage_en_cours" }; control.peutArbitrer.mockReturnValue(false);
    return new Promise<void>(r => { finir = r; });
  });
  await act(async () => { arbre = create(<Ecran />); });
  for (const fait of natif.faits) {
    expect(texte()).toContain(fait.reference.ligne_id);
    for (const v of Object.values(fait.champs)) if (typeof v === "string") expect(texte()).toContain(v);
  }
  expect(arbre!.root.findAllByType(BoutonSecondaire).filter(b => b.props.texte.startsWith("admin.memoire.choix."))).toHaveLength(4);
  await act(async () => bouton("admin.memoire.choix.distincts_confirmes").props.onPress());
  expect(control.arbitrer).toHaveBeenCalledWith("distincts_confirmes");
  const lectures = control.charger.mock.calls.length;
  await act(async () => bouton("admin.commun.rafraichir").props.onPress());
  expect(control.charger).toHaveBeenCalledTimes(lectures);
  await act(async () => finir());
});
test("cache informatif et intention inconnue n'affichent aucun choix d'arbitrage", async () => {
  const catalogue = mockState.catalogue;
  if (catalogue?.source !== "serveur") throw new Error("Fixture invalide");
  mockState = { ...mockState, catalogue: { ...catalogue, source: "cache", raisonHorsLigne: { code: "hors_ligne", detail: "" } },
    intentions: [{ id: "uuid-fictif", revisionId: natif.revision.revision_ligne_id, personne: "admin-fictif", choix: "distincts_confirmes", statut: "en_attente" }] };
  mockConnected = false;
  await act(async () => { arbre = create(<Ecran />); });
  expect(texte()).toContain("admin.memoire.attente"); expect(texte()).toContain("uuid-fictif");
  expect(arbre!.root.findAllByType(BoutonSecondaire).filter(b => b.props.texte.startsWith("admin.memoire.choix."))).toHaveLength(0);
  expect(bouton("admin.memoire.ouvrirRevision").props.desactive).toBe(true);
});
test("perte réseau avec révision sélectionnée dit la relecture nécessaire sans chargement infini", async () => {
  mockConnected = false;
  mockState = { ...mockState, statut: "hors_ligne", enLigne: false, revisionId: natif.revision.revision_ligne_id, dossier: null, statutRevision: null };
  await act(async () => { arbre = create(<Ecran />); });
  expect(texte()).toContain("admin.memoire.messages.connexion");
  expect(arbre!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
  expect(control.ouvrirRevision).not.toHaveBeenCalled();
});
test("retrait du rôle avec personne identique masque faits et intentions avant une réponse tardive", async () => {
  let finir!: () => void;
  control.ouvrirRevision.mockImplementationOnce(() => new Promise<void>(r => { finir = r; }));
  await act(async () => { arbre = create(<Ecran />); });
  await act(async () => bouton("admin.memoire.ouvrirRevision").props.onPress());
  mockGeneration++; mockSession = { presente: true, role: "employee" };
  await act(async () => arbre!.update(<Ecran />));
  mockState = { ...mockState, dossier: serveur(natif), revisionId: natif.revision.revision_ligne_id };
  await act(async () => finir());
  expect(texte()).not.toContain(natif.faits[0].reference.ligne_id);
  expect(texte()).not.toContain("admin.memoire.comptesSignaux"); expect(texte()).toContain("admin.commun.sansSession");
  expect(control.invalider).toHaveBeenCalled();
});
test("catalogues bilingues M10 ont les mêmes clés et variables", () => {
  function verifier(a: unknown, b: unknown) {
    if (typeof a === "string") {
      expect(typeof b).toBe("string"); expect(a.match(/{{[^}]+}}/g)?.sort() ?? []).toEqual((b as string).match(/{{[^}]+}}/g)?.sort() ?? []); return;
    }
    expect(Object.keys(a as object).sort()).toEqual(Object.keys(b as object).sort());
    for (const k of Object.keys(a as object)) verifier(Reflect.get(a as object, k), Reflect.get(b as object, k));
  }
  verifier(adminFr.memoire, adminEn.memoire);
});
