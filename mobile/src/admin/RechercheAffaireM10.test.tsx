import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput, ActivityIndicator } from "react-native";
import { BoutonSecondaire } from "./composants";
let mockEpoch = 0, mockAdmin = true;
const mockRechercher = jest.fn();
const mockT = (cle: string, args?: unknown) => cle + (args ? JSON.stringify(args) : "");
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "admin-fictif" : "employee-fictif" }));
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
 const epoch = mockEpoch; return { session: mockAdmin ? { personne: "admin-fictif" } : null,
 courante: () => epoch === mockEpoch && mockAdmin };
} }));
jest.mock("../m10/service", () => ({ rechercherAffaireMemoire: (...args: unknown[]) => mockRechercher(...args) }));
const Recherche = require("./RechercheAffaireM10").RechercheAffaireM10;
// Données de rendu FICTIVES en RAM ; aucune prétention de capture/native/type-validation.
const valeur = { affaire_id: "LEAD-FICTIF", requete: "", mode: "litteral_nfc_casefold_v1", corpus: "evenements_et_consolidations_affaire_v1",
 resultats: [{ genre: "evenement", affaire_id: "LEAD-FICTIF", identifiant: "WCT-FICTIF", horodatage: "2026-10-08T06:00:00-04:00",
 source: "m4.travaux_termines", resume: "FICTIF : travaux terminés", confidentialite: "INTERNAL",
 reference: { ligne_id: "a".repeat(64), registre: "evenements", hash_tete: "a".repeat(64) } }],
 affaire: { connue: true, origine_recue: false, origine: null, verdict: "AMONT-ORIGINE-NON-RECUE" },
 pagination: { decalage: 0, limite: 8, affichees: 1, total: 2, suivant: 1 as number | null, reste: 1, courante: true },
 couverture: {}, confidentialite: {}, borne_caracteres: 5400, taille_caracteres: 1500 };
const serveur = (v = valeur) => ({ source: "serveur", valeur: v, misAJourLe: "2026-10-08T10:00:00Z" });
let arbre: ReactTestRenderer | undefined;
const ouvrir = jest.fn(), invalider = jest.fn();
const props = () => ({ connected: true, bloque: false, autorisee: () => mockAdmin, onOuvrir: ouvrir, onInvalider: invalider });
const texte = () => JSON.stringify(arbre!.toJSON());
const bouton = (cle: string) => arbre!.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === cle)!;
const saisir = async (affaire = "LEAD-FICTIF", requete = "") => { await act(async () => {
 const champs = arbre!.root.findAllByType(TextInput); champs[0].props.onChangeText(affaire); champs[1].props.onChangeText(requete);
}); };
beforeEach(() => { mockEpoch++; mockAdmin = true; jest.clearAllMocks(); mockRechercher.mockResolvedValue(serveur()); Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true); });
afterEach(async () => { if (arbre) await act(async () => arbre!.unmount()); arbre = undefined; });
test("saisie et lecture courante avec provenance, ouverture de l’affaire serveur seule", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir();
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress());
 expect(mockRechercher).toHaveBeenCalledWith("LEAD-FICTIF", "", 0);
 expect(texte()).toContain("FICTIF : travaux terminés"); expect(texte()).toContain("2026-10-08T06:00:00-04:00");
 expect(texte()).toContain("admin.rechercheAffaire.pagesCourantes"); expect(texte()).toContain("a".repeat(64));
 await act(async () => bouton("admin.paquetAffaire.ouvrir").props.onPress()); expect(ouvrir).toHaveBeenCalledWith("LEAD-FICTIF");
});
test("la page suivante remplace la page précédente et transmet l’offset natif", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir();
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress());
 const seconde = { ...valeur, resultats: [{ ...valeur.resultats[0], identifiant: "SECONDE-FICTIVE", resume: "FICTIF : seconde page" }],
 pagination: { ...valeur.pagination, decalage: 1, suivant: null, reste: 0 } };
 mockRechercher.mockResolvedValueOnce(serveur(seconde));
 await act(async () => bouton("admin.rechercheAffaire.suite").props.onPress());
 expect(mockRechercher).toHaveBeenLastCalledWith("LEAD-FICTIF", "", 1);
 expect(texte()).not.toContain("FICTIF : travaux terminés"); expect(texte()).toContain("FICTIF : seconde page");
});
test("la sélection A→B→A ferme l’ancienne réponse même si le texte redevient identique", async () => {
 let finir!: (v: unknown) => void; mockRechercher.mockImplementationOnce(() => new Promise(r => { finir = r; }));
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir();
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress());
 await saisir("AUTRE-FICTIF"); await saisir(); await act(async () => finir(serveur()));
 expect(texte()).not.toContain("FICTIF : travaux terminés"); expect(arbre!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
});
test("déconnexion puis reconnexion pendant arbitrage ferme la réponse, conserve les intentions ailleurs", async () => {
 let finir!: (v: unknown) => void; mockRechercher.mockImplementationOnce(() => new Promise(r => { finir = r; }));
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir();
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress());
 await act(async () => arbre!.update(<Recherche {...props()} connected={false} bloque />));
 await act(async () => arbre!.update(<Recherche {...props()} bloque />)); await act(async () => finir(serveur()));
 expect(texte()).not.toContain("FICTIF : travaux terminés"); expect(ouvrir).not.toHaveBeenCalled();
});
test("révocation de rôle ferme aussi le contenu déjà affiché et la lecture tardive", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir();
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress());
 mockEpoch++; mockAdmin = false; await act(async () => arbre!.update(<Recherche {...props()} />));
 expect(texte()).not.toContain("FICTIF : travaux terminés"); expect(bouton("admin.rechercheAffaire.rechercher").props.desactive).toBe(true);
});
test("refus et exception n’affichent ni zéro ni ancienne page", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir();
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress());
 mockRechercher.mockResolvedValueOnce({ source: "refus", verdict: { code: "REJ-FICTIF", detail: "" } });
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress()); expect(texte()).not.toContain("FICTIF : travaux terminés");
 mockRechercher.mockRejectedValueOnce(new Error("fictif"));
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress()); expect(texte()).not.toContain("FICTIF : travaux terminés");
 expect(arbre!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
});

test("un changement de session purge aussi les champs saisis avant le nouveau rôle", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir("LEAD-FICTIF", "CLIENT-FICTIF");
 mockEpoch++; mockAdmin = false; await act(async () => arbre!.update(<Recherche {...props()} />));
 expect(arbre!.root.findAllByType(TextInput).map(v => v.props.value)).toEqual(["", ""]);
 mockAdmin = true; await act(async () => arbre!.update(<Recherche {...props()} />));
 expect(arbre!.root.findAllByType(TextInput).map(v => v.props.value)).toEqual(["", ""]);
 expect(bouton("admin.rechercheAffaire.rechercher").props.desactive).toBe(true); expect(mockRechercher).not.toHaveBeenCalled();
});

test("le changement de jeton à rôle égal ne ressuscite pas l’ancien autre champ", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir("LEAD-ANCIEN-FICTIF", "CLIENT-ANCIEN-FICTIF");
 mockEpoch++; await act(async () => arbre!.update(<Recherche {...props()} />));
 expect(arbre!.root.findAllByType(TextInput).map(v => v.props.value)).toEqual(["", ""]);
 await act(async () => arbre!.root.findAllByType(TextInput)[1].props.onChangeText("nouvelle recherche fictive"));
 expect(arbre!.root.findAllByType(TextInput).map(v => v.props.value)).toEqual(["", "nouvelle recherche fictive"]);
 expect(bouton("admin.rechercheAffaire.rechercher").props.desactive).toBe(true); expect(mockRechercher).not.toHaveBeenCalled();
});

test("une affaire connue sans correspondance conserve l’ouverture du paquet courant", async () => {
 const sansHit = { ...valeur, resultats: [], pagination: { ...valeur.pagination, affichees: 0, total: 0, suivant: null, reste: 0 } };
 mockRechercher.mockResolvedValueOnce(serveur(sansHit));
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir();
 await act(async () => bouton("admin.rechercheAffaire.rechercher").props.onPress());
 const lire = bouton("admin.paquetAffaire.ouvrir"); expect(lire).toBeDefined();
 await act(async () => lire.props.onPress()); expect(ouvrir).toHaveBeenCalledWith("LEAD-FICTIF");
});

test("un ancien callback de saisie ne peut adopter la nouvelle session", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir("LEAD-ANCIEN-FICTIF", "");
 const ancienneSaisie = arbre!.root.findAllByType(TextInput)[1].props.onChangeText;
 mockEpoch++; await act(async () => arbre!.update(<Recherche {...props()} />));
 await act(async () => ancienneSaisie("CLIENT-ANCIEN-FICTIF"));
 expect(arbre!.root.findAllByType(TextInput).map(v => v.props.value)).toEqual(["", ""]);
 expect(mockRechercher).not.toHaveBeenCalled();
});
test("un ancien bouton ne relance pas une requête qui a été remplacée", async () => {
 await act(async () => { arbre = create(<Recherche {...props()} />); }); await saisir("LEAD-FICTIF", "ancienne recherche");
 const ancienBouton = bouton("admin.rechercheAffaire.rechercher").props.onPress;
 await saisir("LEAD-FICTIF", "nouvelle recherche"); await act(async () => ancienBouton());
 expect(mockRechercher).not.toHaveBeenCalled();
});
