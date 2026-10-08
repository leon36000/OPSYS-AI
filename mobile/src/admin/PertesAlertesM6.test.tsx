import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { ActivityIndicator } from "react-native";
import { BoutonSecondaire } from "./composants";
import { presenterListeWctPertes, presenterPertesAlertesWct } from "../ecrans/pertesAlertesM6";
import frCA from "../i18n/locales/fr-CA";
import enCA from "../i18n/locales/en-CA";
import { STATUTS_HISTORIQUE_VARIANCE_M6 } from "../m6/pertesAlertes";
import type { ListeWctPertesM6, PaginationPertesM6, PertesAlertesWctM6, SlotHistoriqueVarianceM6, WctPertesM6 } from "../m6/pertesAlertes";

let mockEpoch = 0, mockAdmin = true;
let mockBlur: (() => void) | undefined;
const mockListe = jest.fn(), mockDetail = jest.fn(), mockReseau = jest.fn();
const mockT = (cle: string, args?: unknown) => cle + (args ? JSON.stringify(args) : "");
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));
jest.mock("expo-router", () => ({ useFocusEffect: (callback: () => () => void) => {
  const React = require("react");
  React.useEffect(() => { mockBlur = callback(); return mockBlur; }, [callback]);
} }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "admin-fictif" : "employee-fictif" }));
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const epoch = mockEpoch;
  return { session: mockAdmin ? { personne: "admin-fictif" } : null, courante: () => mockAdmin && epoch === mockEpoch };
} }));
jest.mock("./pertesAlertes", () => ({
  chargerWctsPertesM6: (...args: unknown[]) => mockListe(...args),
  chargerPertesAlertesWctM6: (...args: unknown[]) => mockDetail(...args),
  actualiserConnectivitePertesM6: (v: boolean) => mockReseau(v),
}));
const Ecran = require("./PertesAlertesM6").PertesAlertesM6;
// Données FICTIVES de rendu. Aucun DTO produit, parsing, HTTP, SQLite ou téléphone prouvé ici.
const wct = (id = "WCT-A-FICTIF", rang = 0): WctPertesM6 => ({ wct_id: id, intervention_id: `INTERVENTION-${id}`, devis_id: "DEVIS-FICTIF",
  horodatage_completion: "2026-10-08T07:00:00-04:00", reference_recu: { registre: "wct_recus", rang, empreinte_contenu: "a".repeat(64) },
  reference_bus: { type: "m4.travaux_termines", evenement_id: id } });
const pagination = (total = 2, decalage = 0, affichees = 2): PaginationPertesM6 => ({ decalage, limite: 8, affichees, total,
  suivant: total > decalage + affichees ? decalage + affichees : null as number | null,
  reste: Math.max(0, total - decalage - affichees), courante: true });
const listeFictive: ListeWctPertesM6 = { wcts: [wct(), wct("WCT-B-FICTIF", 1)], pagination: pagination(),
  couverture: { wcts: "recus_m6_rapproches_m4", plafond_lignes: 10000 }, borne_caracteres: 5400, taille_caracteres: 1500 };
const detailFictif = (id = "WCT-A-FICTIF", article = "ARTICLE-A-FICTIF"): PertesAlertesWctM6 => ({ wct: wct(id), chantier_id: "CHANTIER-FICTIF",
  declaration_presente: true, pertes_bris: [{ type_mouvement: "PERTE", chantier_id: "CHANTIER-FICTIF", materiau_id: article,
    quantite_signee: "-2.5", unite: null, horodatage: null, reference: { registre: "principal", index: 0, hash_maillon: "b".repeat(64) } }],
  historique_variance: STATUTS_HISTORIQUE_VARIANCE_M6.map((statut): SlotHistoriqueVarianceM6 => statut === "evaluee" ? { statut, presente: true,
    publication: { reference_bus: { type: "m6.variance_chantier", evenement_id: `m6-variance-${id}-evaluee` },
      chantier_id: "CHANTIER-FICTIF", signal_critique: true, seuil_pourcentage: 0.3,
      horodatage_completion: "2026-10-08T07:00:00-04:00", horodatage_publication: null } } : { statut, presente: false, publication: null }),
  evaluee_terminal: true, pagination: pagination(1, 0, 1), couverture: {
    mouvements: "PERTE_BRIS_WCT_exact", variances: "quatre_statuts_publies_ordre_fixe_sans_chronologie",
    hors_corpus: ["stock_courant", "reapprovisionnement", "couts", "responsables", "preuves_photos", "unites_reelles", "dates_perte_bris"],
    plafond_lignes: 10000 }, borne_caracteres: 5400, taille_caracteres: 2100 });
const serveur = (valeur: unknown) => ({ source: "serveur", valeur, misAJourLe: "2026-10-08T11:00:00Z" });
let arbre: ReactTestRenderer | undefined;
const texte = () => JSON.stringify(arbre!.toJSON());
const boutons = (cle: string) => arbre!.root.findAllByType(BoutonSecondaire).filter(b => b.props.texte === `admin.pertesAlertes.${cle}`);
const presser = async (cle: string, index = 0) => { await act(async () => { boutons(cle)[index].props.onPress(); }); };
const monter = async () => { await act(async () => { arbre = create(<Ecran connected />); }); };
beforeEach(() => {
  mockEpoch++; mockAdmin = true; jest.clearAllMocks(); mockBlur = undefined;
  mockListe.mockResolvedValue(serveur(listeFictive)); mockDetail.mockResolvedValue(serveur(detailFictif()));
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
});
afterEach(async () => { if (arbre) await act(async () => arbre!.unmount()); arbre = undefined; });

test("le premier bouton monte avec une génération vivante ; sélection WCT exact et références source", async () => {
  await monter(); expect(boutons("lister")[0].props.desactive).toBe(false); await presser("lister");
  expect(mockListe).toHaveBeenCalledWith(0); expect(boutons("choisir")).toHaveLength(2);
  await presser("choisir"); expect(mockDetail).toHaveBeenCalledWith("WCT-A-FICTIF", 0);
  expect(texte()).toContain("ARTICLE-A-FICTIF"); expect(texte()).toContain("b".repeat(64));
  expect(texte()).toContain("admin.pertesAlertes.uniteInconnue"); expect(texte()).toContain("admin.pertesAlertes.dateInconnue");
  expect(texte()).toContain("admin.pertesAlertes.ordreHistorique"); expect(texte()).toContain("admin.pertesAlertes.dateDistincte");
});
test("la page suivante de liste remplace ses WCT et ferme le détail précédent", async () => {
  mockListe.mockResolvedValueOnce(serveur({ ...listeFictive, pagination: pagination(3) }));
  await monter(); await presser("lister"); await presser("choisir");
  mockListe.mockResolvedValueOnce(serveur({ ...listeFictive, wcts: [wct("WCT-C-FICTIF", 2)], pagination: pagination(3, 2, 1) }));
  await presser("suiteListe"); expect(mockListe).toHaveBeenLastCalledWith(2);
  expect(texte()).toContain("WCT-C-FICTIF"); expect(texte()).not.toContain("WCT-A-FICTIF");
  expect(texte()).not.toContain("ARTICLE-A-FICTIF");
});
test("la page suivante de détail remplace les mouvements, avec offset serveur exact", async () => {
  const premier = detailFictif(); mockDetail.mockResolvedValueOnce(serveur({ ...premier, pagination: pagination(2, 0, 1) }));
  await monter(); await presser("lister"); await presser("choisir");
  mockDetail.mockResolvedValueOnce(serveur({ ...detailFictif("WCT-A-FICTIF", "ARTICLE-DEUX-FICTIF"), pagination: pagination(2, 1, 1) }));
  await presser("suiteDetail"); expect(mockDetail).toHaveBeenLastCalledWith("WCT-A-FICTIF", 1);
  expect(texte()).not.toContain("ARTICLE-A-FICTIF"); expect(texte()).toContain("ARTICLE-DEUX-FICTIF");
});
test("sélection A→B→A : la première réponse A ne remplace jamais la seconde", async () => {
  let finir!: (v: unknown) => void; mockDetail.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); await presser("lister"); await presser("choisir", 0);
  mockDetail.mockResolvedValueOnce(serveur(detailFictif("WCT-B-FICTIF", "ARTICLE-B-FICTIF"))); await presser("choisir", 1);
  mockDetail.mockResolvedValueOnce(serveur(detailFictif("WCT-A-FICTIF", "ARTICLE-NOUVEAU-A-FICTIF"))); await presser("choisir", 0);
  await act(async () => finir(serveur(detailFictif("WCT-A-FICTIF", "ARTICLE-ANCIEN-A-FICTIF"))));
  expect(texte()).toContain("ARTICLE-NOUVEAU-A-FICTIF"); expect(texte()).not.toContain("ARTICLE-ANCIEN-A-FICTIF");
});
test("un ancien callback de sélection est fermé après refresh ou nouveau jeton", async () => {
  await monter(); await presser("lister"); const ancien = boutons("choisir")[0].props.onPress;
  await presser("lister"); await act(async () => ancien()); expect(mockDetail).not.toHaveBeenCalled();
  const autreAncien = boutons("choisir")[0].props.onPress;
  mockEpoch++; await act(async () => arbre!.update(<Ecran connected />));
  await act(async () => autreAncien()); expect(mockDetail).not.toHaveBeenCalled();
  expect(texte()).not.toContain("WCT-A-FICTIF");
});
test("rôle retiré masque immédiatement liste, détail et action", async () => {
  await monter(); await presser("lister"); await presser("choisir");
  mockEpoch++; mockAdmin = false; await act(async () => arbre!.update(<Ecran connected />));
  expect(texte()).not.toContain("ARTICLE-A-FICTIF"); expect(texte()).not.toContain("WCT-A-FICTIF");
  expect(boutons("lister")[0].props.desactive).toBe(true);
});
test("réseau A→B→A invalide une réponse encore en vol, sans copie hors ligne", async () => {
  let finir!: (v: unknown) => void; mockDetail.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); await presser("lister"); await presser("choisir");
  await act(async () => arbre!.update(<Ecran connected={false} />));
  expect(texte()).toContain("admin.pertesAlertes.horsLigne"); expect(texte()).not.toContain("WCT-A-FICTIF");
  await act(async () => arbre!.update(<Ecran connected />)); await act(async () => finir(serveur(detailFictif())));
  expect(texte()).not.toContain("ARTICLE-A-FICTIF"); expect(arbre!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
});
test("un refus connu purge aussi la liste précédente et ne devient pas zéro pertes", async () => {
  await monter(); await presser("lister"); await presser("choisir");
  mockDetail.mockResolvedValueOnce({ source: "refus", verdict: { code: "REJ-IDENTITE-FICTIVE", detail: "Refus fictif" } });
  await presser("choisir"); expect(texte()).toContain("Refus fictif");
  expect(texte()).not.toContain("ARTICLE-A-FICTIF"); expect(texte()).not.toContain("WCT-A-FICTIF");
  expect(texte()).not.toContain("admin.pertesAlertes.aucunePerteConnue");
});
test("erreur ou retour cache inattendu ne répare pas le détail", async () => {
  await monter(); await presser("lister"); await presser("choisir");
  mockDetail.mockRejectedValueOnce(new Error("fictif")); await presser("choisir"); expect(texte()).not.toContain("ARTICLE-A-FICTIF");
  mockDetail.mockResolvedValueOnce({ ...serveur(detailFictif()), source: "cache", raisonHorsLigne: { code: "fictif" } });
  await presser("choisir"); expect(texte()).not.toContain("ARTICLE-A-FICTIF"); expect(texte()).toContain("lecture_indisponible");
});
test("quitter l’écran ferme les callbacks et lectures tardives", async () => {
  let finir!: (v: unknown) => void; mockListe.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  await monter(); const ancien = boutons("lister")[0].props.onPress; await presser("lister");
  await act(async () => mockBlur!()); await act(async () => finir(serveur(listeFictive)));
  await act(async () => ancien()); expect(mockListe).toHaveBeenCalledTimes(1); expect(texte()).not.toContain("WCT-A-FICTIF");
});

test("absence de déclaration, zéro connu et page vide restent trois lectures distinctes", () => {
  const base = detailFictif();
  const lire = (v: PertesAlertesWctM6) => JSON.stringify(presenterPertesAlertesWct(v));
  expect(lire({ ...base, declaration_presente: false, chantier_id: null, pertes_bris: [], pagination: pagination(0, 0, 0),
    historique_variance: base.historique_variance.map(slot => ({ ...slot, presente: false, publication: null })), evaluee_terminal: false })).toContain("pertesNonDocumentees");
  expect(lire({ ...base, pertes_bris: [], pagination: pagination(0, 0, 0) })).toContain("aucunePerteConnue");
  expect(lire({ ...base, pertes_bris: [], pagination: pagination(1, 2, 0) })).toContain("aucunePertePage");
});
test.each([frCA, enCA])("les messages des deux vues existent avec exactement leurs variables", ressources => {
  const messages = [...presenterListeWctPertes(listeFictive).lignes,
    ...presenterPertesAlertesWct(detailFictif()).lignes,
    ...presenterPertesAlertesWct(detailFictif()).mouvements.flatMap(m => m.lignes),
    ...presenterPertesAlertesWct(detailFictif()).historique.flatMap(h => h.lignes)];
  for (const m of messages) {
    const valeur = m.cle.split(".").reduce<unknown>((o, c) => typeof o === "object" && o !== null ? (o as Record<string, unknown>)[c] : undefined, ressources);
    expect(typeof valeur).toBe("string");
    const noms = ((valeur as string).match(/\{\{\w+\}\}/g) ?? []).map(v => v.slice(2, -2)).sort();
    expect(noms).toEqual(Object.keys(m.params ?? {}).sort());
  }
});
