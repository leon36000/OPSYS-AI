import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { BoutonSecondaire } from "../admin/composants";
import { definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import type { ListeWctPertesM6, PertesAlertesWctM6, WctPertesM6 } from "../m6/pertesAlertes";
import { STATUTS_HISTORIQUE_VARIANCE_M6 } from "../m6/pertesAlertes";
import { disponibiliteFictive, digestFictif } from "../m6/fixturesStock";

let mockConnected = true;
const mockLireWcts = jest.fn(), mockLirePertes = jest.fn(), mockConnectivite = jest.fn();
jest.mock("expo-router", () => ({ useFocusEffect: (callback: () => void | (() => void)) => {
  const React = require("react"); React.useEffect(callback, [callback]);
} }));
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: (cle: string, args?: unknown) => cle + (args ? JSON.stringify(args) : ""),
  i18n: { language: "fr-CA" } }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => "admin-fictif" }));
jest.mock("../admin/pertesAlertes", () => ({
  chargerWctsPertesM6: (...args: unknown[]) => mockLireWcts(...args),
  chargerPertesAlertesWctM6: (...args: unknown[]) => mockLirePertes(...args),
  actualiserConnectivitePertesM6: (v: boolean) => mockConnectivite(v),
}));
jest.mock("@/admin/service", () => ({ chargerDisponibiliteM6: jest.fn(), chargerDigestM6: jest.fn() }), { virtual: true });
// Le child, ses modèles et ses gardes de configuration sont réellement composés par la route.
jest.mock("@/admin/PertesAlertesM6", () => jest.requireActual("../admin/PertesAlertesM6"), { virtual: true });
jest.mock("@/admin/ReapprovisionnementM6", () => ({ ReapprovisionnementM6: () => null }), { virtual: true });
jest.mock("@/admin/composants", () => jest.requireActual("../admin/composants"), { virtual: true });
jest.mock("@/ecrans/adminCommun", () => jest.requireActual("./adminCommun"), { virtual: true });
jest.mock("@/ecrans/stock", () => jest.requireActual("./stock"), { virtual: true });
jest.mock("@/identite/BandeauIdentite", () => ({ BandeauIdentite: () => null }), { virtual: true });
jest.mock("@/protocole/configuration", () => jest.requireActual("../protocole/configuration"), { virtual: true });
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => "admin-fictif" }), { virtual: true });
const EcranStock = require("../../app/(admin)/stock").default;
const serviceGlobal = require("@/admin/service") as Record<string, jest.Mock>;
const config = { urlBase: "http://127.0.0.1:0", jeton: "jeton-stock-fictif", appareilId: "appareil-stock-fictif" };
const identite = { jeton: config.jeton, appareilId: config.appareilId, personne: "admin-stock-fictif", role: "admin" };
const serveur = (valeur: unknown) => ({ source: "serveur", valeur, misAJourLe: "2026-10-08T12:00:00Z" });
// Fixtures FICTIVES de composition uniquement ; pas de capture backend ou HTTP.
const wct: WctPertesM6 = { wct_id: "WCT-STOCK-FICTIF", intervention_id: "INTERVENTION-STOCK-FICTIVE", devis_id: "DEVIS-STOCK-FICTIF",
  horodatage_completion: "2026-10-08T08:00:00-04:00", reference_recu: { registre: "wct_recus", rang: 0, empreinte_contenu: "a".repeat(64) },
  reference_bus: { type: "m4.travaux_termines", evenement_id: "WCT-STOCK-FICTIF" } };
const liste: ListeWctPertesM6 = { wcts: [wct], pagination: { decalage: 0, limite: 8, affichees: 1, total: 1, suivant: null, reste: 0, courante: true },
  couverture: { wcts: "recus_m6_rapproches_m4", plafond_lignes: 10000 }, borne_caracteres: 5400, taille_caracteres: 900 };
const detail: PertesAlertesWctM6 = { wct, chantier_id: "CHANTIER-STOCK-FICTIF", declaration_presente: true,
  pertes_bris: [{ type_mouvement: "BRIS", chantier_id: "CHANTIER-STOCK-FICTIF", materiau_id: "ARTICLE-BRIS-STOCK-FICTIF",
    quantite_signee: "-3", unite: null, horodatage: null, reference: { registre: "principal", index: 0, hash_maillon: "b".repeat(64) } }],
  historique_variance: STATUTS_HISTORIQUE_VARIANCE_M6.map(statut => ({ statut, presente: false, publication: null })), evaluee_terminal: false,
  pagination: { ...liste.pagination }, couverture: { mouvements: "PERTE_BRIS_WCT_exact", variances: "quatre_statuts_publies_ordre_fixe_sans_chronologie",
    hors_corpus: ["stock_courant", "reapprovisionnement", "couts", "responsables", "preuves_photos", "unites_reelles", "dates_perte_bris"], plafond_lignes: 10000 },
  borne_caracteres: 5400, taille_caracteres: 1500 };
let arbre: ReactTestRenderer | undefined;
const texte = () => JSON.stringify(arbre!.toJSON());
const bouton = (cle: string) => arbre!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === cle)!;
const presser = async (cle: string) => { await act(async () => { bouton(cle).props.onPress(); }); };
beforeEach(() => {
  jest.clearAllMocks(); mockConnected = true; Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  definirConfigurationAppel(config); definirPersonneConfirmee(identite);
  serviceGlobal.chargerDisponibiliteM6.mockResolvedValue(serveur(disponibiliteFictive));
  serviceGlobal.chargerDigestM6.mockResolvedValue(serveur(digestFictif));
  mockLireWcts.mockResolvedValue(serveur(liste)); mockLirePertes.mockResolvedValue(serveur(detail));
});
afterEach(async () => {
  if (arbre) await act(async () => arbre!.unmount()); arbre = undefined;
  definirConfigurationAppel(null); definirPersonneConfirmee(null);
});
test("Stock compose les trois lectures, et la sélection ouvre le WCT exact dans le vrai composant", async () => {
  await act(async () => { arbre = create(<EcranStock />); });
  expect(texte()).toContain("admin.stock.disponibilite"); expect(texte()).toContain("admin.stock.historique");
  expect(texte()).toContain("admin.pertesAlertes.titre");
  await presser("admin.pertesAlertes.lister"); await presser("admin.pertesAlertes.choisir");
  expect(mockLireWcts).toHaveBeenCalledWith(0); expect(mockLirePertes).toHaveBeenCalledWith("WCT-STOCK-FICTIF", 0);
  expect(texte()).toContain("ARTICLE-BRIS-STOCK-FICTIF"); expect(texte()).toContain("admin.pertesAlertes.bris");
  expect(texte()).toContain("admin.pertesAlertes.uniteInconnue"); expect(texte()).toContain("admin.pertesAlertes.dateInconnue");
  expect(serviceGlobal.chargerDigestM6).toHaveBeenCalledTimes(1);
});
test("le raccord NetInfo de la route ferme la lecture WCT en vol au cycle hors ligne/en ligne", async () => {
  let finir!: (v: unknown) => void; mockLirePertes.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await act(async () => { arbre = create(<EcranStock />); });
  await presser("admin.pertesAlertes.lister"); await presser("admin.pertesAlertes.choisir");
  mockConnected = false; await act(async () => arbre!.update(<EcranStock />));
  expect(texte()).toContain("admin.pertesAlertes.horsLigne");
  mockConnected = true; await act(async () => arbre!.update(<EcranStock />)); await act(async () => finir(serveur(detail)));
  expect(texte()).not.toContain("ARTICLE-BRIS-STOCK-FICTIF"); expect(mockConnectivite).toHaveBeenCalledWith(false);
});
test("le changement d'autorité confirmé ferme aussi les deux lectures globales de Stock", async () => {
  await act(async () => { arbre = create(<EcranStock />); }); await presser("admin.pertesAlertes.lister");
  const ancien = bouton("admin.pertesAlertes.choisir").props.onPress;
  definirPersonneConfirmee({ ...identite, role: "employee" }); await act(async () => arbre!.update(<EcranStock />));
  expect(texte()).not.toContain("WCT-STOCK-FICTIF");
  expect(texte()).not.toContain("admin.stock.historique");
  await act(async () => ancien()); expect(mockLirePertes).not.toHaveBeenCalled();
  expect(bouton("admin.pertesAlertes.lister").props.desactive).toBe(true);
});
test("une session confirmée ne devient pas 'sans session' pendant le chargement global", async () => {
  serviceGlobal.chargerDisponibiliteM6.mockReturnValueOnce(new Promise(() => {}));
  serviceGlobal.chargerDigestM6.mockReturnValueOnce(new Promise(() => {}));
  await act(async () => { arbre = create(<EcranStock />); });
  expect(texte()).not.toContain("admin.commun.sansSession");
});
test("l'ancien bouton global ne prend pas l'autorité d'une nouvelle personne", async () => {
  await act(async () => { arbre = create(<EcranStock />); });
  const ancien = bouton("admin.commun.rafraichir").props.onPress;
  definirPersonneConfirmee({ ...identite, personne: "autre-admin-stock-fictif" });
  await act(async () => arbre!.update(<EcranStock />)); await act(async () => ancien());
  expect(serviceGlobal.chargerDisponibiliteM6).toHaveBeenCalledTimes(1);
  expect(serviceGlobal.chargerDigestM6).toHaveBeenCalledTimes(1);
});
