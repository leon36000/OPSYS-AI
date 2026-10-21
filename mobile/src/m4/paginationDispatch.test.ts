import { runInNewContext } from "node:vm";
import { copierJsonDispatch, JSON_DISPATCH_INVALIDE } from "./dispatch";
import { construireArgumentsPageDispatch, lirePageDispatch } from "./paginationDispatch";
import { pageDispatchFictive as source, pageSuivanteFictive, varianteFictive } from "./fixturesDispatch";
const args = construireArgumentsPageDispatch("planifiee", null, 8);
test("page native DIRECT filtrée et suivante : curseur opaque, sans accumulation", () => {
  const page = lirePageDispatch(source,args)!;
  expect(page.interventions).toHaveLength(8); expect(page.illisibles).toBe(0);
  expect(page.page).toEqual(source.page);
  expect(page.interventions[4].travaux).toEqual({genre:"service",valeur:"ravalement"});
  const suivante=lirePageDispatch(pageSuivanteFictive,construireArgumentsPageDispatch("planifiee",page.page.curseur_suivant,8))!;
  expect(suivante.interventions).toHaveLength(8); expect(suivante.page.reste).toBe(20);
  expect(page.interventions[0].interventionId).not.toBe(suivante.interventions[0].interventionId);
});
test("arguments natifs null par défaut ; fin vide après un curseur conserve le total",()=>{
  expect(construireArgumentsPageDispatch("planifiee")).toEqual({statut:"planifiee",curseur:null,taille_page:null});
  const v=varianteFictive(source); v.interventions=[]; Object.assign(v.page,{curseur:"f".repeat(64),taille:0,reste:0,curseur_suivant:null});
  expect(lirePageDispatch(v,construireArgumentsPageDispatch("planifiee","f".repeat(64),8))?.page.total).toBe(36);
  const d=varianteFictive(source) as any; d.page.taille_demandee=null; d.page.borne_atteinte=true;
  expect(lirePageDispatch(d,construireArgumentsPageDispatch("planifiee"))).not.toBeNull();
});
test.each([
 ["statut",(v:any)=>{v.interventions[0].statut="reportee";}],
 ["curseur",(v:any)=>{v.page.curseur="a".repeat(64);}],
 ["taille demandée",(v:any)=>{v.page.taille_demandee=9;}],
 ["taille",(v:any)=>{v.page.taille=7;}],
 ["total",(v:any)=>{v.page.total=35;}],
 ["reste",(v:any)=>{v.page.reste=-1;}],
 ["suivant",(v:any)=>{v.page.curseur_suivant="a".repeat(64);}],
 ["ordre",(v:any)=>{v.interventions.reverse();}],
 ["doublon",(v:any)=>{v.interventions[1]=v.interventions[0];}],
 ["clé",(v:any)=>{v.page.snapshot=true;}],
 ["nature double",(v:any)=>{v.interventions[0].service="gouttieres";}],
 ["borne non booléenne",(v:any)=>{v.page.borne_atteinte=0;}],
 ["id",(v:any)=>{v.interventions[0].intervention_id="nonhash";}],
 ["tableau creux",(v:any)=>{delete v.interventions[0];}],
])("page illisible entière : %s",(_,modifier)=>{const v=varianteFictive(source);modifier(v);expect(lirePageDispatch(v,args)).toBeNull();});
test("borne de texte vraie, pas de promesse d'un snapshot",()=>{
 const v=varianteFictive(source);v.interventions=v.interventions.slice(0,2);Object.assign(v.page,{taille:2,reste:34,curseur_suivant:v.interventions[1].intervention_id,borne_atteinte:true});
 expect(lirePageDispatch(v,args)?.page.borne_atteinte).toBe(true);
});
test("snapshot du transport : getters jamais lus, prototype/cycle/profondeur/symboles/numériques refusés",()=>{
 let appels=0;const getter=Object.defineProperty({},"ok",{enumerable:true,get(){appels++;return true;}});
 expect(copierJsonDispatch(getter)).toBe(JSON_DISPATCH_INVALIDE);expect(appels).toBe(0);
 class Objet { ok=true; } const cycle:any={};cycle.self=cycle;
 for(const v of [new Objet(),Object.create({ok:true}),cycle,{a:NaN},{a:Infinity},{a:Number.MAX_SAFE_INTEGER+1},{[Symbol()]:true},[,1]]) expect(copierJsonDispatch(v)).toBe(JSON_DISPATCH_INVALIDE);
 expect(copierJsonDispatch({a:{b:1}},1)).toBe(JSON_DISPATCH_INVALIDE);
 expect(copierJsonDispatch({zero:0,non:false,vide:null,decimal:1.25})).toEqual({zero:0,non:false,vide:null,decimal:1.25});
});
test("JSON Response.json d'un autre realm et copie indépendante",()=>{
 const v=runInNewContext(`JSON.parse(${JSON.stringify(JSON.stringify(source))})`);
 expect(lirePageDispatch(v,args)?.page).toEqual(source.page);
 const snapshot=copierJsonDispatch(source) as unknown as typeof source; expect(snapshot).not.toBe(source);
 expect(snapshot.interventions).not.toBe(source.interventions);
});
test("borne_atteinte doit expliquer toute page plus courte que le plafond natif",()=>{
 const v=varianteFictive(source) as any;v.interventions=v.interventions.slice(0,2);Object.assign(v.page,{taille:2,reste:34,curseur_suivant:v.interventions[1].intervention_id,borne_atteinte:false});
 expect(lirePageDispatch(v,args)).toBeNull();v.page.taille_demandee=null;
 expect(lirePageDispatch(v,construireArgumentsPageDispatch("planifiee"))).toBeNull();
});
test.each([0,51,true,1.5])("taille_page invalide %s et arguments hérités refusés",taille=>{
 expect(lirePageDispatch(source,{...args,taille_page:taille} as any)).toBeNull();
 expect(lirePageDispatch(source,Object.create(args))).toBeNull();
});
test("les arrays/classes renommées et prototypes falsifiés ne sont pas JSON",()=>{
 class ObjetFaux { valeur=1; } Object.defineProperty(ObjetFaux,"name",{value:"Object"});Object.setPrototypeOf(ObjetFaux.prototype,null);
 class TableauFaux extends Array {} Object.defineProperty(TableauFaux,"name",{value:"Array"});Object.setPrototypeOf(TableauFaux.prototype,Object.prototype);
 for(const v of [new ObjetFaux(),new TableauFaux()])expect(copierJsonDispatch(v)).toBe(JSON_DISPATCH_INVALIDE);
 const a:any[]=[];Object.defineProperty(a,"extra",{value:1});expect(copierJsonDispatch(a)).toBe(JSON_DISPATCH_INVALIDE);
 const objet=Object.defineProperty({},"cache",{value:1});expect(copierJsonDispatch(objet)).toBe(JSON_DISPATCH_INVALIDE);
});
