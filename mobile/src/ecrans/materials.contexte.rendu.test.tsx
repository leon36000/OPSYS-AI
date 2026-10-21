import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput } from "react-native";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { DepotOutboxMemoire } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
import { definirConfigurationAppel, definirPersonneConfirmee, obtenirSessionEnvoi } from "../protocole/configuration";
import { ecrireWctIdCompletion } from "../m4/wctIdCompletion";
import { creerVidangeur } from "../outbox/vidangeur";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionMateriauxLecture } from "../protocole/configuration";
import { lireBrouillonMateriaux, sauverBrouillonMateriaux } from "../terrain/brouillonMateriaux";
import { creerLigneVide } from "./materials";
import fr from "../i18n/locales/fr-CA";
import en from "../i18n/locales/en-CA";
import { lireContexteMateriaux } from "../m6/contexteMateriaux";
import captures from "../m6/fixturesContexteMateriaux.json";
let mockConnected = true, mockId = "", mockUUID = 0;
let mockKV: DepotCleValeurMemoire, mockOutbox: ReturnType<typeof avecProprietaire>;
const mockCharger = jest.fn(), mockVidanger = jest.fn();
let mockFetch: jest.Mock, mockNow=new Date(), mockFocus:()=>void|(()=>void), mockBlur:(()=>void)|void;
jest.mock("expo-router", () => ({ useRouter: () => ({push:jest.fn()}), useLocalSearchParams: () => ({ id: mockId }), useFocusEffect: (f: () => void | (() => void)) => require("react").useEffect(()=>{mockFocus=f;const cleanup=f();mockBlur=cleanup;return cleanup;}, [f]) }));
jest.mock("expo-crypto", () => ({ randomUUID: () => `00000000-0000-4000-8000-${String(++mockUUID).padStart(12,"0")}` }));
const mockT=(k:string,p?:Record<string,unknown>)=>{
  const lire=(locale:unknown):unknown=>k.split(".").reduce<unknown>((o,cle)=>o!==null&&typeof o==="object"?Reflect.get(o,cle):undefined,locale);
  for(const locale of [fr,en]){
    const message=lire(locale);expect(typeof message).toBe("string");
    if(typeof message==="string")expect([...message.matchAll(/{{([^}]+)}}/g)].map(m=>m[1]).sort()).toEqual(Object.keys(p??{}).sort());
  }
  return k+(p?JSON.stringify(p):"");
};
jest.mock("react-i18next", () => ({ useTranslation: () => ({ t: mockT }) }));
jest.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: mockConnected }) }));
jest.mock("../roles/contexte", () => ({ useSessionAppareil: () => ({ presente: true, role: "employee" }) }));
jest.mock("../stockage/service", () => ({ obtenirDepotLocal: async () => mockKV }));
jest.mock("../outbox/service", () => ({ obtenirDepot: async () => mockOutbox, declencherVidange: (...a: unknown[]) => mockVidanger(...a) }));
jest.mock("../terrain/contexteMateriaux", () => ({ chargerContexteMateriaux: (...a: unknown[]) => mockCharger(...a), actualiserConnectiviteContexteMateriaux: jest.fn() }));
jest.mock("@/ecrans/materials", () => jest.requireActual("./materials"), { virtual: true });
jest.mock("@/m6/materiaux", () => jest.requireActual("../m6/materiaux"), { virtual: true });
jest.mock("@/m6/contexteMateriaux", () => jest.requireActual("../m6/contexteMateriaux"), { virtual: true });
jest.mock("@/m4/wctIdCompletion", () => jest.requireActual("../m4/wctIdCompletion"), { virtual: true });
jest.mock("@/outbox/id", () => ({ genererMutationId: () => `00000000-0000-4000-8000-${String(++mockUUID).padStart(12,"0")}` }), { virtual: true });
jest.mock("@/outbox/mutation", () => jest.requireActual("../outbox/mutation"), { virtual: true });
jest.mock("@/outbox/service", () => ({ obtenirDepot: async () => mockOutbox, declencherVidange: (...a: unknown[]) => mockVidanger(...a) }), { virtual: true });
jest.mock("@/protocole/configuration", () => jest.requireActual("../protocole/configuration"), { virtual: true });
jest.mock("@/stockage/service", () => ({ obtenirDepotLocal: async () => mockKV }), { virtual: true });
jest.mock("@/roles/contexte", () => ({ useSessionAppareil: () => ({ presente: true, role: "employee" }) }), { virtual: true });
const Ecran = require("../../app/(employee)/job/[id]/materials").default;
const capture = captures.captures.find(c => c.phase === "m3-devis-accepte-texte-verifie")!;
const configuration = { urlBase: "http://127.0.0.1:0", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF" };
let arbre: ReactTestRenderer | undefined;
const texte = () => JSON.stringify(arbre!.toJSON());
const appuyer = async (cle: string) => { const b = arbre!.root.findAllByProps({accessibilityLabel:cle}).find(x=>typeof x.props.onPress==="function"); expect(b).toBeDefined(); expect(b!.props.disabled).not.toBe(true); await act(async () => b!.props.onPress()); };
beforeEach(async () => {
  jest.clearAllMocks(); mockConnected=true; mockUUID=0; mockId=capture.request.args.intervention_id;
  mockKV=new DepotCleValeurMemoire(); mockOutbox=avecProprietaire(new DepotOutboxMemoire(),()=>obtenirSessionEnvoi()?.personne??null,()=>obtenirSessionEnvoi()?.urlBase??null);
  definirConfigurationAppel(configuration); definirPersonneConfirmee({ ...configuration, personne:"EMPLOYEE-FICTIF",role:"employee" });
  await ecrireWctIdCompletion(mockKV,mockId,capture.request.args.wct_id);
  mockCharger.mockImplementation(async (i:string,w:string,d:number) => { const args={intervention_id:i,wct_id:w,decalage:d,limite:8}; const lu=lireContexteMateriaux(capture.response,args); if (!lu.ok) return {source:"aucune",raison:{code:lu.code,detail:lu.detail}}; return {source:"serveur",valeur:lu.value}; });
  mockNow=new Date("2026-10-08T17:00:00Z");
  mockFetch=jest.fn(async (_input:RequestInfo|URL,_init?:RequestInit)=>new Response(JSON.stringify({ok:true,result:{}}),{status:200}));
  const vidangeur=creerVidangeur({depot:mockOutbox,descripteurs:DESCRIPTEURS_MUTATION,appelerOutil:invoquerOutil,fetchImpl:mockFetch,session:obtenirSessionEnvoi,capturerGardeSession:()=>capturerSessionMateriauxLecture().courante,maintenant:()=>mockNow,verifierAvantEnvoi:async(_m,_s,courante)=>courante() && capturerSessionMateriauxLecture().courante()});
  mockVidanger.mockImplementation((garde?:()=>boolean)=>vidangeur.vidangerFileSortante(garde)); Reflect.set(globalThis,"IS_REACT_ACT_ENVIRONMENT",true);
});
afterEach(async()=>{ if(arbre) await act(async()=>arbre!.unmount()); arbre=undefined; definirConfigurationAppel(null);definirPersonneConfirmee(null); });
test("la vraie route offre une lecture explicite du contexte puis le préremplissage sans réel",async()=>{
  await act(async()=>{arbre=create(<Ecran/>);}); expect(texte()).toContain("materials.contexte.charger"); await appuyer("materials.contexte.charger");
  expect(mockCharger).toHaveBeenCalledWith(mockId,capture.request.args.wct_id,0);
  expect(texte()).toContain("materials.contexte.datePrevu"); await appuyer("materials.contexte.importer");
  const reels=arbre!.root.findAllByType(TextInput).filter(x=>x.props.accessibilityLabel==="materials.champQuantite");
  expect(reels.length).toBeGreaterThan(0); for(const r of reels)expect(r.props.value).toBe("");
  expect(texte()).toContain("materials.contexte.reelVide"); expect(await mockOutbox.lister()).toHaveLength(0);
});

const monter=async()=>{await act(async()=>{arbre=create(<Ecran/>);});};
const contexteEtImport=async()=>{await monter();await appuyer("materials.contexte.charger");await appuyer("materials.contexte.importer");};
const modifierReels=async(texteReel="1")=>{
  const n=arbre!.root.findAllByType(TextInput).filter(x=>x.props.accessibilityLabel==="materials.champQuantite").length;
  for(let i=0;i<n;i++)await act(async()=>{arbre!.root.findAllByType(TextInput).filter(x=>x.props.accessibilityLabel==="materials.champQuantite")[i].props.onChangeText(texteReel);});
};
const cible=()=>({urlBase:configuration.urlBase,appareilId:configuration.appareilId,personne:"EMPLOYEE-FICTIF",interventionId:mockId});
function serveurCapture(phase:string){
  const c=captures.captures.find(x=>x.phase===phase)!;const lu=lireContexteMateriaux(c.response,c.request.args);
  if(!lu.ok)throw new Error(`Fixture SQL positive illisible ${phase}`);return {source:"serveur",valeur:lu.value};
}
test("double clic et ACK inconnu : un UUID, cible chantier source, payload conservé et champs verrouillés",async()=>{
  await contexteEtImport();await modifierReels();
  const cb=arbre!.root.findAllByProps({accessibilityLabel:"materials.bouton"}).find(x=>typeof x.props.onPress==="function")!.props.onPress;
  await act(async()=>{cb();cb();});
  const rows=await mockOutbox.lister();expect(rows).toHaveLength(1);const m=rows[0];
  expect(m.statut).toBe("en_attente");expect(m.tentatives).toBe(1);expect(mockFetch).toHaveBeenCalledTimes(1);
  const body=JSON.parse(String(mockFetch.mock.calls[0][1]?.body));expect(body.idempotencyKey).toBe(m.id);expect(body.args).toEqual(m.payload);
  const lu=serveurCapture("m3-devis-accepte-texte-verifie");expect(body.args.formulaire.chantier_id).toBe(lu.valeur.chantier.chantier_id);
  expect(body.args.formulaire.chantier_id).not.toBe(mockId);expect(texte()).toContain("materials.contexte.intentionConservee");
  for(const r of arbre!.root.findAllByType(TextInput))expect(r.props.editable).toBe(false);
  await appuyer("materials.contexte.statut");expect(mockFetch).toHaveBeenCalledTimes(1);expect(await mockOutbox.lister()).toHaveLength(1);
});
test("confirmation fictive de forme canonique termine seulement via reçu persistant lié",async()=>{
  // Vecteur RAM fictif de transport, forme ACK déjà qualifiée SQL (pas une capture HTTP).
  mockFetch.mockImplementation(async (_u:RequestInfo|URL,init?:RequestInit)=>{
    const body=JSON.parse(String(init?.body)),f=body.args.formulaire;
    return new Response(JSON.stringify({ok:true,result:{ok:true,resultat:{accepte:true,resultat:{intervention_id:f.intervention_id,chantier_id:f.chantier_id,lignes_declarees:f.lignes_materiaux},registre:{taille:f.lignes_materiaux.length,hash_tete:"a".repeat(64)}}}}),{status:200});
  });
  await contexteEtImport();await modifierReels();await appuyer("materials.bouton");
  expect((await mockOutbox.lister())[0].statut).toBe("envoyee");expect(texte()).toContain("materials.succes");
  await act(async()=>arbre!.unmount());arbre=undefined;await monter();expect(texte()).toContain("materials.succes");expect(mockFetch).toHaveBeenCalledTimes(1);
});
test("brouillon sauvegardé/reprise mémoire garde l'intention et le recul avant renvoi de la même clé",async()=>{
  await contexteEtImport();await modifierReels("2");await appuyer("materials.bouton");const m=(await mockOutbox.lister())[0];
  const d=await lireBrouillonMateriaux(mockKV,cible());expect(d).toMatchObject({genre:"present",valeur:{intentionId:m.id,wctId:bodyWct()}});
  await act(async()=>arbre!.unmount());arbre=undefined;await monter();
  expect(texte()).toContain(m.id);await appuyer("materials.contexte.statut");expect(mockFetch).toHaveBeenCalledTimes(1);
  mockNow=new Date("2026-10-08T18:00:00Z");await appuyer("materials.contexte.statut");
  expect(mockFetch).toHaveBeenCalledTimes(2);expect(JSON.parse(String(mockFetch.mock.calls[1][1]?.body)).idempotencyKey).toBe(m.id);
  expect((await mockOutbox.lister())[0].payload).toEqual(m.payload);expect(await mockOutbox.lister()).toHaveLength(1);
});
const bodyWct=()=>capture.request.args.wct_id;
test("sauvegarde du brouillon échouée après insertion : reprise par outbox sans nouveau UUID",async()=>{
  await contexteEtImport();await modifierReels();
  const ecrire=jest.spyOn(mockKV,"ecrire").mockRejectedValue(new Error("échec fictif KV"));
  await appuyer("materials.bouton");const m=(await mockOutbox.lister())[0];expect(texte()).toContain("materials.contexte.stockage_echec");
  ecrire.mockRestore();await act(async()=>arbre!.unmount());arbre=undefined;await monter();
  expect(texte()).toContain(m.id);for(const r of arbre!.root.findAllByType(TextInput))expect(r.props.editable).toBe(false);
  expect(await mockOutbox.lister()).toHaveLength(1);await appuyer("materials.contexte.statut");expect(mockFetch).toHaveBeenCalledTimes(1);
});
test("ancien envoyé sans reçu lié reste conservé et ne libère pas une nouvelle déclaration",async()=>{
  await contexteEtImport();await modifierReels();await appuyer("materials.bouton");const m=(await mockOutbox.lister())[0];
  await mockOutbox.mettreAJour({...m,statut:"envoyee",resumeAccepte:{statut:"ok"}});
  await appuyer("materials.contexte.statut");expect(texte()).not.toContain("materials.succes");expect(texte()).toContain("materials.contexte.intentionConservee");
  expect(await mockOutbox.lister()).toHaveLength(1);expect(mockFetch).toHaveBeenCalledTimes(1);
});
test("ancien propriétaire inconnu reste en quarantaine sur cet objet, sans lecture du payload comme autorité",async()=>{
  await contexteEtImport();await modifierReels();await appuyer("materials.bouton");const m=(await mockOutbox.lister())[0];
  await mockOutbox.mettreAJour({...m,proprietaire:null});await act(async()=>arbre!.unmount());arbre=undefined;await monter();
  expect(texte()).toContain("materials.contexte.quarantaine");expect(texte()).not.toContain("materials.succes");
  await appuyer("materials.contexte.statut");expect(mockFetch).toHaveBeenCalledTimes(1);expect(await mockOutbox.lister()).toHaveLength(1);
});
test.each(["horsligne","role","jeton","navigation","saisie"])("réponse en vol %s fermée",async(mode)=>{
  let finir!:(v:unknown)=>void;mockCharger.mockImplementationOnce(()=>new Promise(r=>{finir=r;}));
  await monter();await appuyer("materials.contexte.charger");
  if(mode==="horsligne"){mockConnected=false;await act(async()=>arbre!.update(<Ecran/>));mockConnected=true;await act(async()=>arbre!.update(<Ecran/>));}
  if(mode==="role"){definirPersonneConfirmee({...configuration,personne:"EMPLOYEE-FICTIF",role:"seller"});await act(async()=>arbre!.update(<Ecran/>));}
  if(mode==="jeton"){definirConfigurationAppel({...configuration,jeton:"JETON-FICTIF-NOUVEAU"});await act(async()=>arbre!.update(<Ecran/>));}
  if(mode==="navigation"){const ancien=mockId;mockId="INTERVENTION-B-FICTIVE";await act(async()=>arbre!.update(<Ecran/>));mockId=ancien;await act(async()=>arbre!.update(<Ecran/>));}
  if(mode==="saisie")await appuyer("materials.ajouterLigne");
  await act(async()=>finir(serveurCapture("m3-devis-accepte-texte-verifie")));
  expect(texte()).not.toContain("materials.contexte.sourceM3");expect(mockFetch).not.toHaveBeenCalled();
});
test("ancien callback n'emprunte jamais l'autorité d'une nouvelle personne",async()=>{
  await monter();const cb=arbre!.root.findAllByProps({accessibilityLabel:"materials.contexte.charger"}).find(x=>typeof x.props.onPress==="function")!.props.onPress;
  definirPersonneConfirmee({...configuration,personne:"AUTRE-FICTIF",role:"employee"});await act(async()=>arbre!.update(<Ecran/>));await act(async()=>cb());
  expect(mockCharger).not.toHaveBeenCalled();expect(mockFetch).not.toHaveBeenCalled();
});
test("brouillon illisible signalé, jamais supprimé ni remplacé silencieusement",async()=>{
  await sauverBrouillonMateriaux(mockKV,cible(),{wctId:null,chantierId:null,sourcePrevu:null,positionsImportees:[],intentionId:null,lignes:[]});
  const key=mockKV.cles().find(k=>k.startsWith("brouillon.m6."))!;await mockKV.ecrire(key,"{illisible-fictif");
  const supprimer=jest.spyOn(mockKV,"supprimer"),ecrire=jest.spyOn(mockKV,"ecrire");await monter();
  expect(texte()).toContain("materials.contexte.stockage_illisible");expect(ecrire).not.toHaveBeenCalled();expect(supprimer).not.toHaveBeenCalled();expect(await mockKV.lire(key)).toBe("{illisible-fictif");
});
test("lecture du brouillon tardive ne remplace pas une saisie récente gardée au focus",async()=>{
  await contexteEtImport();await modifierReels("7");
  const rawKey=mockKV.cles().find(k=>k.startsWith("brouillon.m6."))!, brut=(await mockKV.lire(rawKey))!;
  const vieux=JSON.parse(brut);vieux.brouillon.lignes[0].quantiteTexte="3";
  let finir!:(v:string|null)=>void;const lire=mockKV.lire.bind(mockKV);
  jest.spyOn(mockKV,"lire").mockImplementation(k=>k===rawKey?new Promise(r=>{finir=r;}):lire(k));
  await act(async()=>{mockBlur?.();mockFocus();});await act(async()=>finir(JSON.stringify(vieux)));
  expect(arbre!.root.findAllByType(TextInput).filter(x=>x.props.accessibilityLabel==="materials.champQuantite")[0].props.value).toBe("7");
});
test("import répété et source changée ne réécrivent ni ne dupliquent la saisie",async()=>{
  await contexteEtImport();await modifierReels("4");const d=await lireBrouillonMateriaux(mockKV,cible());
  await appuyer("materials.contexte.importer");expect(texte()).toContain("page_deja_importee");expect(await lireBrouillonMateriaux(mockKV,cible())).toEqual(d);
  mockCharger.mockResolvedValueOnce(serveurCapture("m3-provisoire-remplace-page"));await appuyer("materials.contexte.charger");await appuyer("materials.contexte.importer");
  expect(texte()).toContain("cible_changee");expect(await lireBrouillonMateriaux(mockKV,cible())).toEqual(d);
  // Vecteur RAM fictif : les deux captures ci-dessus changent aussi la cible.
  const original=serveurCapture("m3-devis-accepte-texte-verifie");
  if(!original.valeur.prevu.source)throw new Error("Source requise pour ce vecteur");
  const nouvelle={...original.valeur,prevu:{...original.valeur.prevu,source:{...original.valeur.prevu.source,empreinte_snapshot:"d".repeat(64)}}};
  mockCharger.mockResolvedValueOnce({source:"serveur",valeur:nouvelle});await appuyer("materials.contexte.charger");await appuyer("materials.contexte.importer");
  expect(texte()).toContain("source_changee");expect(await lireBrouillonMateriaux(mockKV,cible())).toEqual(d);
});
test("hors ligne : brouillon lisible conservé, aucun DTO courant KV ni HTTP",async()=>{
  await contexteEtImport();await modifierReels("8");mockConnected=false;await act(async()=>arbre!.update(<Ecran/>));
  expect(texte()).toContain("materials.contexte.horsLigne");expect(texte()).not.toContain("materials.contexte.sourceM3");
  for(const key of mockKV.cles()){const raw=await mockKV.lire(key);expect(raw).not.toContain('"borne_caracteres"');expect(raw).not.toContain(configuration.jeton);}
  expect(arbre!.root.findAllByType(TextInput).filter(x=>x.props.accessibilityLabel==="materials.champQuantite")[0].props.value).toBe("8");expect(mockFetch).not.toHaveBeenCalled();
});
test("catalogues fr/en : mêmes clés et variables du contexte",()=>{
  expect(Object.keys(fr.materials.contexte).sort()).toEqual(Object.keys(en.materials.contexte).sort());
  for(const cle of Object.keys(fr.materials.contexte))expect(fr.materials.contexte[cle].match(/{{[^}]+}}/g)?.sort()??[]).toEqual(en.materials.contexte[cle].match(/{{[^}]+}}/g)?.sort()??[]);
});

test.each(captures.captures.filter(c=>!c.phase.startsWith("refus-")&&c.request.args.decalage===0&&c.request.args.limite===8))("DTO SQL $phase : champs natifs sans recomposition",async(c)=>{
  mockCharger.mockResolvedValueOnce(serveurCapture(c.phase));await monter();await appuyer("materials.contexte.charger");
  const lu=lireContexteMateriaux(c.response,c.request.args);if(!lu.ok)throw new Error("DTO valide requis");
  const natif=lu.value;expect(texte()).toContain(natif.wct.horodatage_completion);expect(texte()).toContain(natif.wct.hash_maillon);
  for(const l of natif.lignes){expect(texte()).toContain(l.materiau_id);expect(texte()).toContain(l.quantite_estimee);}
  if(natif.prevu.source?.horodatage===null)expect(texte()).toContain("materials.contexte.datePrevuAbsente");
  if(natif.prevu.statut==="absent")expect(texte()).toContain("materials.contexte.prevuAbsent");
  expect(await mockOutbox.lister()).toHaveLength(0);expect(mockFetch).not.toHaveBeenCalled();
});
test.each(captures.captures.filter(c=>c.phase.startsWith("refus-")&&c.request.args.limite===8))("refus réel SQL $phase sans repli sur la lecture précédente",async(c)=>{
  await contexteEtImport();const lu=lireContexteMateriaux(c.response,c.request.args);if(lu.ok)throw new Error("Refus attendu");
  mockCharger.mockResolvedValueOnce({source:"refus",verdict:{code:lu.code,detail:lu.detail}});
  await appuyer("materials.contexte.charger");expect(texte()).toContain(lu.code);expect(texte()).toContain(lu.detail);
  expect(texte()).not.toContain("materials.contexte.sourceM3");expect(mockFetch).not.toHaveBeenCalled();
  const b=arbre!.root.findAllByProps({accessibilityLabel:"materials.bouton"}).find(x=>typeof x.props.onPress==="function")!;expect(b.props.disabled).toBe(true);
});

test.each(["reseau","role"])("garde %s changée pendant lister outbox : aucune nouvelle intention ni HTTP",async(mode)=>{
  await contexteEtImport();await modifierReels();let finir!:(rows:Awaited<ReturnType<typeof mockOutbox.lister>>)=>void;
  jest.spyOn(mockOutbox,"lister").mockImplementationOnce(()=>new Promise(r=>{finir=r;}));
  await appuyer("materials.bouton");
  if(mode==="reseau"){mockConnected=false;await act(async()=>arbre!.update(<Ecran/>));mockConnected=true;await act(async()=>arbre!.update(<Ecran/>));}
  else {definirPersonneConfirmee({...configuration,personne:"EMPLOYEE-FICTIF",role:"seller"});await act(async()=>arbre!.update(<Ecran/>));}
  await act(async()=>finir([]));expect(await mockOutbox.lister()).toHaveLength(0);expect(mockFetch).not.toHaveBeenCalled();
});

test("page courante remplacée et ancien bouton suivant fermé : vecteur RAM fictif de navigation",async()=>{
  const premiere=serveurCapture("page-reduite5400");mockCharger.mockResolvedValueOnce(premiere);await monter();await appuyer("materials.contexte.charger");
  const ancien=arbre!.root.findAllByProps({accessibilityLabel:"materials.contexte.suivante"}).find(x=>typeof x.props.onPress==="function")!.props.onPress;
  // Vecteur RAM indépendant de comportement ; aucune seconde capture HTTP/SQL fabriquée.
  const seconde={...premiere.valeur,lignes:[{position_source:6,materiau_id:"MAT-PAGE-SUIVANTE-FICTIF",unite:"pi",quantite_estimee:"1",origine_quantite:"nombre_m6_persiste" as const}],
    pagination:{decalage:6,limite:8,affichees:1,total:8,suivant:7,reste:1,courante:true as const}};
  mockCharger.mockResolvedValueOnce({source:"serveur",valeur:seconde});await appuyer("materials.contexte.suivante");
  expect(mockCharger).toHaveBeenLastCalledWith(mockId,bodyWct(),6);expect(texte()).toContain("MAT-PAGE-SUIVANTE-FICTIF");
  expect(texte()).not.toContain(premiere.valeur.lignes[0].materiau_id);const n=mockCharger.mock.calls.length;
  await act(async()=>ancien());expect(mockCharger).toHaveBeenCalledTimes(n);expect(await mockOutbox.lister()).toHaveLength(0);
});
test("grand texte natif affiché mais import non exact refusé sans altérer la saisie",async()=>{
  mockCharger.mockResolvedValueOnce(serveurCapture("quantite-grande-texte"));await monter();await appuyer("materials.contexte.charger");
  expect(texte()).toContain("materials.contexte.nonImportable");await appuyer("materials.contexte.importer");
  expect(texte()).toContain("raison_estimation_non_importable");expect(arbre!.root.findAllByType(TextInput)).toHaveLength(0);expect(await mockOutbox.lister()).toHaveLength(0);
});

test("le focus conserve un refus connu du contexte jusqu'à une nouvelle lecture positive",async()=>{
  await contexteEtImport();await modifierReels();
  const c=captures.captures.find(x=>x.phase==="refus-admin-revoque")!,lu=lireContexteMateriaux(c.response,c.request.args);if(lu.ok)throw new Error("Refus natif requis");
  mockCharger.mockResolvedValueOnce({source:"refus",verdict:{code:lu.code,detail:lu.detail}});await appuyer("materials.contexte.charger");
  await act(async()=>{mockBlur?.();mockFocus();});
  const b=arbre!.root.findAllByProps({accessibilityLabel:"materials.bouton"}).find(x=>typeof x.props.onPress==="function")!;expect(b.props.disabled).toBe(true);
  expect(mockFetch).not.toHaveBeenCalled();await appuyer("materials.contexte.charger");
  expect(arbre!.root.findAllByProps({accessibilityLabel:"materials.bouton"}).find(x=>typeof x.props.onPress==="function")!.props.disabled).toBe(false);
});

test("perte : note durable par ligne, réel inchangé et intention inconnue verrouillée",async()=>{
 const ligne={...creerLigneVide("L-PERTE-FICTIVE"),typeLigne:"perte" as const,materiauId:"SKU-FICTIF",quantiteTexte:"2",unite:"pi"};
 await sauverBrouillonMateriaux(mockKV,cible(),{wctId:capture.request.args.wct_id,chantierId:"CH-FICTIF",sourcePrevu:null,positionsImportees:[],intentionId:null,lignes:[ligne],preuves:[]});
 await monter();const note=arbre!.root.findAllByProps({testID:"note-L-PERTE-FICTIVE"}).find(n=>typeof n.props.onChangeText==="function")!;
 await act(async()=>note.props.onChangeText("FICTIF dommage observé"));
 expect((await lireBrouillonMateriaux(mockKV,cible()))).toMatchObject({genre:"present",valeur:{preuves:[{ligneId:ligne.id,note:"FICTIF dommage observé",captureIds:[]}],lignes:[{quantiteTexte:"2"}]}});
 await appuyer("materials.bouton");const file=await mockOutbox.lister();expect(file).toHaveLength(1);expect(file[0].type).toBe("materials_submit_with_proofs");expect(file[0].payload).toMatchObject({preuves_lignes:[{position_ligne:0,note:"FICTIF dommage observé",photos:[]}]});
 expect(arbre!.root.findAllByProps({testID:"note-L-PERTE-FICTIVE"}).find(n=>typeof n.props.onChangeText==="function")!.props.editable).toBe(false);
 await appuyer("materials.contexte.statut");expect(await mockOutbox.lister()).toHaveLength(1);
});
