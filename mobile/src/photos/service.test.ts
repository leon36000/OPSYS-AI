import { enregistrerPhotoCapturee, listerPhotosCapturees } from "./service";
import { definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import { obtenirDepot } from "../outbox/service";
import { File } from "expo-file-system";
import { DepotOutboxMemoire } from "../outbox/depot";
import { avecProprietaire } from "../outbox/proprietaire";
let continuer: (() => void) | null = null;
let mockCopie: Promise<void> = Promise.resolve();
const mockSupprimer = jest.fn();
jest.mock("expo-file-system",()=>({Paths:{document:{uri:"file:///document/"}},Directory:class {exists=true;uri="file:///document/opsys-photos/INTERV/apres";create(){}},File:class {uri="file:///document/opsys-photos/INTERV/apres/00000000-0000-4000-8000-000000000001.jpg";size=3;exists=true;async copy(){await mockCopie;}async bytes(){return new Uint8Array([1,2,3]);}delete(){mockSupprimer();}}}));
jest.mock("expo-crypto",()=>({CryptoDigestAlgorithm:{SHA256:"SHA256"},digest:async()=>new Uint8Array(32).buffer}));
jest.mock("../outbox/id",()=>({genererMutationId:()=>"00000000-0000-4000-8000-000000000001"}));
jest.mock("../outbox/service",()=>({obtenirDepot:jest.fn()}));
function session(personne="ANCIEN", role="employee",jeton="JETON"){definirConfigurationAppel({urlBase:"http://core-fictif",appareilId:"DEVICE",jeton});definirPersonneConfirmee({appareilId:"DEVICE",jeton,personne,role});}
beforeEach(()=>{session();mockSupprimer.mockClear();mockCopie=Promise.resolve();continuer=null;});
const params={uriTemporaire:"file:///cache/photo.jpg",largeur:1,hauteur:1,nature:"apres" as const,chantierId:"INTERV"};
test("la capture suspendue ne peut être attribuée à une nouvelle personne",async()=>{
 const brut=new DepotOutboxMemoire();jest.mocked(obtenirDepot).mockResolvedValue(avecProprietaire(brut,()=>"NOUVEAU"));
 mockCopie=new Promise<void>(r=>{continuer=r;});const promesse=enregistrerPhotoCapturee(params);session("NOUVEAU");continuer?.();
 await expect(promesse).rejects.toThrow();expect(await brut.lister()).toEqual([]);expect(mockSupprimer).toHaveBeenCalledTimes(1);
});
test("la capture nominale conserve explicitement son propriétaire original",async()=>{
 const brut=new DepotOutboxMemoire();jest.mocked(obtenirDepot).mockResolvedValue(avecProprietaire(brut,()=>"NOUVEAU"));
 expect((await enregistrerPhotoCapturee(params)).proprietaire).toBe("ANCIEN");expect(mockSupprimer).not.toHaveBeenCalled();
});
test("la lecture suspendue n'adopte pas une nouvelle session",async()=>{
 const brut=new DepotOutboxMemoire();let resolve!:()=>void;const attente=new Promise<void>(r=>{resolve=r;});jest.mocked(obtenirDepot).mockImplementation(async()=>{await attente;return brut;});
 const p=listerPhotosCapturees("INTERV");session("NOUVEAU");resolve();expect(await p).toEqual([]);
});
