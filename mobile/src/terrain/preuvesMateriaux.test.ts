import { figerPreuvesMateriaux, listerCapturesPreuves } from "./preuvesMateriaux";
import { creerLigneVide, evaluerPreparationFormulaire } from "../ecrans/materials";
const ligne=(id:string)=>({...creerLigneVide(id),typeLigne:"perte" as const,materiauId:"SKU-FICTIF",quantiteTexte:"2",unite:"pi"});
test("deux pertes même SKU, IDs stables puis positions finales après réordre, notes conservées",()=>{
 const ls=[ligne("L-B"),ligne("L-A")],f=evaluerPreparationFormulaire("W-FICTIF","I-FICTIF","C-FICTIF",ls);if(!f.pret)throw new Error("Formulaire fictif invalide");
 const p=figerPreuvesMateriaux(ls,f.formulaire,[{ligneId:"L-A",note:"Note A fictive",captureIds:[]},{ligneId:"L-B",note:"Note B fictive",captureIds:[]}],[]);
 expect(p.args.preuves_lignes).toEqual([{position_ligne:0,note:"Note B fictive",photos:[]},{position_ligne:1,note:"Note A fictive",photos:[]}]);
});
test("capture indisponible ne crée ni référence ni faux zéro",()=>{const ls=[ligne("L-A")],f=evaluerPreparationFormulaire("W-FICTIF","I-FICTIF","C-FICTIF",ls);if(!f.pret)throw new Error();expect(()=>figerPreuvesMateriaux(ls,f.formulaire,[{ligneId:"L-A",note:"Fictif",captureIds:["ABSENTE"]}],[])).toThrow("capture_indisponible");expect(listerCapturesPreuves([],"EMPLOYEE-FICTIF","I-FICTIF")).toEqual([]);});
test("getters des notes fermés avant exécution",()=>{const ls=[ligne("L-A")],f=evaluerPreparationFormulaire("W-FICTIF","I-FICTIF","C-FICTIF",ls);if(!f.pret)throw new Error();let n=0;const p={ligneId:"L-A",note:"FICTIF",captureIds:[]};Object.defineProperty(p,"note",{enumerable:true,get:()=>{n++;return "FICTIF";}});expect(()=>figerPreuvesMateriaux(ls,f.formulaire,[p],[])).toThrow("preuves_invalides");expect(n).toBe(0);});
