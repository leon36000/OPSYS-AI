/** Real SQL row render plus fictive consumer callbacks. No Cap/HTTP mutation claim. */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput } from "react-native";
import { BoutonSecondaire } from "./composants";
import captures from "../m5/fixturesObligationsPrepareesSQL.json";
import { lireObligationsPreparees } from "../m5/obligationsPreparees";
const source = captures.captures.find(c => c.name === "lecture-courante")!;
const lu = lireObligationsPreparees(source.enveloppe, source.request!.arguments);
if (!lu.ok) throw new Error("SQL source refused");
const page = lu.value;
let mockEpoch = 0, mockAdmin = true, mockActif = true;
const mockCharger = jest.fn(), mockSoumettre = jest.fn(), mockIntention = jest.fn(), mockReprendre = jest.fn();
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => mockAdmin ? "admin-fictif" : "employee-fictif" }));
jest.mock("../protocole/configuration", () => ({ capturerSessionAdminLecture: () => {
  const n = mockEpoch; return { session: mockAdmin ? { personne: "admin-fictif" } : null, courante: () => mockAdmin && n === mockEpoch };
} }));
jest.mock("./obligationsPrepareesM5", () => ({ actualiserConnectiviteObligationsM5: jest.fn(), chargerObligationsM5: (...a: unknown[]) => mockCharger(...a),
 soumettreObligationM5: (...a: unknown[]) => mockSoumettre(...a), lireIntentionObligationM5: (...a: unknown[]) => mockIntention(...a), reprendreObligationM5: (...a: unknown[]) => mockReprendre(...a) }));
const api = () => require("./ObligationsPrepareesM5").ObligationsPrepareesM5;
let tree: ReactTestRenderer | undefined;
const boutons = (suffix: string) => tree!.root.findAllByType(BoutonSecondaire).filter(b => b.props.texte === `admin.obligationsM5.${suffix}`);
const press = async (suffix: string) => { await act(async () => boutons(suffix)[0].props.onPress()); };
const saisir = async (suffix: string, value: string) => { await act(async () => tree!.root.findAllByType(TextInput).find(v => v.props.accessibilityLabel === `admin.obligationsM5.${suffix}`)!.props.onChangeText(value)); };
const mount = async () => { const C = api(); await act(async () => { tree = create(<C connected autorisee={() => mockActif} />); }); };
const text = () => JSON.stringify(tree!.toJSON());
beforeEach(() => { mockEpoch++; mockAdmin = true; mockActif = true; jest.clearAllMocks(); Reflect.set(globalThis,"IS_REACT_ACT_ENVIRONMENT",true);
 mockCharger.mockResolvedValue({ source:"serveur",valeur:page,misAJourLe:"2026-10-09T12:00:00Z" });mockIntention.mockResolvedValue({genre:"aucune"});
 mockSoumettre.mockResolvedValue({genre:"en_attente"}); mockReprendre.mockResolvedValue({genre:"en_attente"}); });
afterEach(async () => { if(tree)await act(async()=>tree!.unmount());tree=undefined; });
async function choisir() { await saisir("aujourdHui","2026-10-09");await press("lire");await press("choisir"); }
test("no amount/date/source or operation is selected automatically; read is explicit", async()=> {
 await mount(); expect(mockCharger).not.toHaveBeenCalled();expect(mockSoumettre).not.toHaveBeenCalled();
 expect(tree!.root.findAllByType(TextInput).every(v=>v.props.value==="")).toBe(true);
 await choisir();expect(mockCharger).toHaveBeenCalledWith("2026-10-09",0,1);
 for(const n of ["montant","source","au","echeance","motif"]) expect(tree!.root.findAllByType(TextInput).find(v=>v.props.accessibilityLabel===`admin.obligationsM5.${n}`)!.props.value).toBe("");
 expect(text()).toContain(page.obligations[0].reference!.ligne_id);expect(text()).toContain("000.10");
});
test("explicit partial declaration keeps unknown fields and expected revision without bank/payment claim",async()=> {
 await mount();await choisir();await saisir("source"," source FICTIVE ");await saisir("motif","FICTIF");await press("declarer");
 expect(mockSoumettre.mock.calls[0][0]).toEqual({categorie:"paies",operation:"declarer",declaration:{montant:null,source:" source FICTIVE ",au:null,echeance:null,calendrier:null},revision_attendue:page.obligations[0].reference,motif:"FICTIF"});
 expect(text()).toContain("admin.obligationsM5.enAttente");expect(boutons("declarer")).toHaveLength(0);
});
test("retirement requires an explicit reason and never rewrites declaration as zero",async()=> {
 await mount();await choisir();expect(boutons("retirer")[0].props.desactive).toBe(true);await press("retirer");expect(mockSoumettre).not.toHaveBeenCalled();
 await saisir("motif","Retrait FICTIF");await press("retirer");expect(mockSoumettre.mock.calls[0][0]).toEqual({categorie:"paies",operation:"retirer",declaration:null,revision_attendue:page.obligations[0].reference,motif:"Retrait FICTIF"});
});
test("current pages replace and a changed explicit today invalidates old callbacks",async()=> {
 await mount();await choisir();const old=boutons("declarer")[0].props.onPress;
 await saisir("aujourdHui","2026-10-10");await act(async()=>old());expect(mockSoumettre).not.toHaveBeenCalled();expect(text()).not.toContain(page.obligations[0].reference!.ligne_id);
 await press("lire");await press("suite");expect(mockCharger).toHaveBeenLastCalledWith("2026-10-10",page.decalage_suivant,1);
});
test("confirmation removes current page until explicit reread",async()=> {
 mockSoumettre.mockResolvedValue({genre:"confirmee"});await mount();await choisir();await press("declarer");expect(text()).not.toContain(page.obligations[0].reference!.ligne_id);
});
test("offline, role and focus invalidate old decision callbacks without deleting a local intention",async()=> {
 await mount();await choisir();await press("declarer");const old=boutons("reprendre")[0].props.onPress;
 const C=api();await act(async()=>tree!.update(<C connected={false} autorisee={()=>mockActif}/>));await act(async()=>old());expect(mockReprendre).not.toHaveBeenCalled();
 expect(text()).not.toContain(page.obligations[0].reference!.ligne_id);expect(text()).toContain("admin.obligationsM5.enAttente");
 mockActif=false;mockEpoch++;await act(async()=>tree!.update(<C connected autorisee={()=>mockActif}/>));await act(async()=>old());expect(mockReprendre).not.toHaveBeenCalled();
});
test("double press creates one request; old completion is masked after session changes",async()=> {
 let finish!:(v:unknown)=>void;mockSoumettre.mockImplementationOnce(()=>new Promise(r=>{finish=r;}));await mount();await choisir();
 const callback=boutons("declarer")[0].props.onPress;await act(async()=>{callback();callback();});expect(mockSoumettre).toHaveBeenCalledTimes(1);
 mockAdmin=false;mockEpoch++;const C=api();await act(async()=>tree!.update(<C connected autorisee={()=>mockActif}/>));await act(async()=>finish({genre:"confirmee"}));expect(text()).not.toContain("admin.obligationsM5.confirmee");
});
test("foreign local intention remains quarantined and blocks another declaration",async()=> {
 mockIntention.mockResolvedValue({genre:"quarantaine"});await mount();await choisir();await press("declarer");expect(mockSoumettre).not.toHaveBeenCalled();expect(text()).toContain("admin.obligationsM5.quarantaine");
});

test("a saved submit callback cannot adopt an edited source or send the previous body",async()=> {
 await mount();await choisir();const old=boutons("declarer")[0].props.onPress;await saisir("source","nouvelle source FICTIVE");
 await act(async()=>old());expect(mockSoumettre).not.toHaveBeenCalled();await press("declarer");expect(mockSoumettre.mock.calls[0][0].declaration.source).toBe("nouvelle source FICTIVE");
});
test("calendar metadata remains empty until explicitly provided; no implicit year or authority",async()=> {
 await mount();await choisir();await press("calendrier");for(const n of ["autorite","periode_debut","periode_fin","annee","version"])expect(tree!.root.findAllByType(TextInput).find(v=>v.props.accessibilityLabel===`admin.obligationsM5.${n}`)!.props.value).toBe("");
 await press("declarer");expect(mockSoumettre.mock.calls[0][0].declaration.calendrier).toEqual({autorite:null,periode_debut:null,periode_fin:null,echeance_source:null,source_consultee_le:null,source_applicable_du:null,source_applicable_jusqu_au:null,annee:null,version:null});
});

test("invalid amount and civil date are refused locally instead of rounded or repaired",async()=> {
 await mount();await choisir();await saisir("montant","1.001");expect(boutons("declarer")[0].props.desactive).toBe(true);await press("declarer");expect(mockSoumettre).not.toHaveBeenCalled();
 await saisir("montant","0001.00");await saisir("au","2026-02-29");expect(boutons("declarer")[0].props.desactive).toBe(true);await press("declarer");expect(mockSoumettre).not.toHaveBeenCalled();
 await saisir("au","2026-10-09");await press("declarer");expect(mockSoumettre.mock.calls[0][0].declaration.montant).toBe("0001.00");
});

test("the read visibly separates normalized calendar provenance from the raw declaration",async()=> {
 await mount();await choisir();expect(text()).toContain("admin.obligationsM5.sourceMontantNormalisee");expect(text()).toContain("admin.obligationsM5.sourceEcheanceNormalisee");expect(text()).toContain("admin.obligationsM5.autorite");expect(text()).toContain("admin.obligationsM5.source_applicable_jusqu_au");
});

test("an unknown mutation invalidates the old current page but retains category and exact retry",async()=> {
 await mount();await choisir();await press("declarer");expect(text()).not.toContain(page.obligations[0].reference!.ligne_id);expect(boutons("declarer")).toHaveLength(0);expect(boutons("reprendre")).toHaveLength(1);
 await press("reprendre");expect(mockReprendre.mock.calls[0][0]).toBe("paies");expect(text()).toContain("admin.obligationsM5.enAttente");expect(text()).not.toContain(page.obligations[0].reference!.ligne_id);
});

test("an old date callback before selection cannot erase a newer draft or current page",async()=> {
 await mount();await saisir("aujourdHui","2026-10-09");await press("lire");
 const old=tree!.root.findAllByType(TextInput).find(v=>v.props.accessibilityLabel==="admin.obligationsM5.aujourdHui")!.props.onChangeText;
 await press("choisir");await saisir("source","source nouvelle FICTIVE");await saisir("montant","0001.00");
 await act(async()=>old("2026-10-10"));
 expect(tree!.root.findAllByType(TextInput).find(v=>v.props.accessibilityLabel==="admin.obligationsM5.aujourdHui")!.props.value).toBe("2026-10-09");
 expect(tree!.root.findAllByType(TextInput).find(v=>v.props.accessibilityLabel==="admin.obligationsM5.source")!.props.value).toBe("source nouvelle FICTIVE");
 expect(tree!.root.findAllByType(TextInput).find(v=>v.props.accessibilityLabel==="admin.obligationsM5.montant")!.props.value).toBe("0001.00");
 expect(text()).toContain(page.obligations[0].reference!.ligne_id);expect(mockCharger).toHaveBeenCalledTimes(1);expect(mockSoumettre).not.toHaveBeenCalled();
});
test("the current date callback stays editable offline without reading or dispatching",async()=> {
 await mount();const C=api();await act(async()=>tree!.update(<C connected={false} autorisee={()=>mockActif}/>));
 await saisir("aujourdHui","2026-10-10");expect(tree!.root.findAllByType(TextInput).find(v=>v.props.accessibilityLabel==="admin.obligationsM5.aujourdHui")!.props.value).toBe("2026-10-10");
 expect(mockCharger).not.toHaveBeenCalled();expect(mockSoumettre).not.toHaveBeenCalled();
});

test("UI first and next current pages request exactly one category",async()=> {
 await mount();await choisir();expect(mockCharger).toHaveBeenLastCalledWith("2026-10-09",0,1);
 await press("suite");expect(mockCharger).toHaveBeenLastCalledWith("2026-10-09",page.decalage_suivant,1);
});
