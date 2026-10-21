import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
const mockEnregistrer=jest.fn(async(..._a:unknown[])=>({})),mockPrendre=jest.fn();let mockId="I-FICTIVE";
let mockBlur:(()=>void)|void;
jest.mock("expo-router",()=>({useLocalSearchParams:()=>({id:mockId}),useFocusEffect:(f:()=>void|(()=>void))=>require("react").useEffect(()=>{mockBlur=f();return mockBlur;},[f])}));
jest.mock("expo-camera",()=>{const R=require("react");return {useCameraPermissions:()=>[{granted:true},async()=>({granted:true})],CameraView:R.forwardRef((_p:unknown,ref:unknown)=>{R.useImperativeHandle(ref,()=>({takePictureAsync:mockPrendre,getAvailablePictureSizesAsync:async()=>[]}));return null;})};});
jest.mock("@/protocole/configuration",()=>jest.requireActual("../protocole/configuration"),{virtual:true});
jest.mock("@/roles/contexte",()=>({useSessionAppareil:()=>({presente:true,role:"employee"})}),{virtual:true});
jest.mock("react-i18next",()=>({useTranslation:()=>({t:(k:string)=>k})}));
jest.mock("@/photos/service",()=>({enregistrerPhotoCapturee:(...a:unknown[])=>mockEnregistrer(...a),listerPhotosCapturees:async()=>[]}),{virtual:true});
jest.mock("@/photos/taille",()=>jest.requireActual("../photos/taille"),{virtual:true});
jest.mock("@/photos/types",()=>jest.requireActual("../photos/types"),{virtual:true});
const Ecran=require("../../app/(employee)/job/[id]/photos").default;
let arbre:ReactTestRenderer;
function session(personne="ANCIEN",role="employee"){definirConfigurationAppel({urlBase:"https://core-fictif.invalid",appareilId:"D-FICTIF",jeton:"J-FICTIF"});definirPersonneConfirmee({appareilId:"D-FICTIF",jeton:"J-FICTIF",personne,role});}
beforeEach(()=>{jest.clearAllMocks();mockId="I-FICTIVE";session();Reflect.set(globalThis,"IS_REACT_ACT_ENVIRONMENT",true);});
afterEach(async()=>{await act(async()=>arbre?.unmount());});
test.each(["personne","rôle","focus","cible"])("%s changé pendant caméra : aucune copie/persistance",async genre=>{
 let resolve!:(v:unknown)=>void;mockPrendre.mockImplementation(()=>new Promise(r=>{resolve=r;}));
 await act(async()=>{arbre=create(<Ecran/>);});
 await act(async()=>{arbre.root.findAll(n=>typeof n.props.onPress==="function").at(-1)!.props.onPress();});
 let attente:Promise<void>;
 await act(async()=>{attente=arbre.root.findAll(n=>typeof n.props.onPress==="function").at(-1)!.props.onPress();});
 if(genre==="personne")session("NOUVEAU");if(genre==="rôle")session("ANCIEN","seller");if(genre==="focus")mockBlur?.();
 if(genre==="cible"){mockId="AUTRE";await act(async()=>arbre.update(<Ecran/>));}
 await act(async()=>{resolve({uri:"file:///cache/FICTIF.jpg",width:1,height:1});await attente;});
 expect(mockEnregistrer).not.toHaveBeenCalled();
});

test.each(["personne","focus"])("ancien callback rendu A après %s B ne rouvre pas la caméra",async genre=>{
 await act(async()=>{arbre=create(<Ecran/>);});
 const ancien=arbre.root.findAll(n=>typeof n.props.onPress==="function").at(-1)!.props.onPress;
 if(genre==="personne")session("NOUVEAU");else mockBlur?.();
 await act(async()=>arbre.update(<Ecran/>));
 await act(async()=>ancien());
 expect(arbre.root.findAllByProps({facing:"back"})).toHaveLength(0);
});
