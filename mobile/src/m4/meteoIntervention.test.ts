import { construireArgumentsMeteoIntervention, lireMeteoIntervention } from "./meteoIntervention";
import { meteoInterventionFictive as source, varianteFictive, meteoCapturesFictives } from "./fixturesDispatch";
const args=construireArgumentsMeteoIntervention(source.intervention_id,"2026-10-06");
test("météo native DTO après COUPLE, citation/émission et false conservés",()=>{
 const v=lireMeteoIntervention(source,args)!;expect(v).toEqual(source);expect(v).not.toBe(source);
 expect(v.creneaux[0].plan_perime).toBe(false);expect(v.creneaux[0].prevision?.emise_le).toBe("2026-10-04T18:00:00-04:00");
 expect(construireArgumentsMeteoIntervention(source.intervention_id)).toEqual({intervention_id:source.intervention_id,date:null});
});
test("date absente reste inconnue, cause explicite, aucune date de calendrier inventée",()=>{
 const v=varianteFictive(source) as any;v.statut="inconnu";Object.assign(v.creneaux[0],{date:null,statut:"inconnu",prevision:null,cause:{code:"REJ-CHAMP-MANQUANT",detail:"Date à fournir (FICTIF)"},regles:[]});
 expect(lireMeteoIntervention(v,construireArgumentsMeteoIntervention(source.intervention_id))?.creneaux[0].date).toBeNull();
 const p=varianteFictive(v);p.plan_id=null;p.creneaux=[];p.cause={code:"REJ-CHAMP-MANQUANT",detail:"Pas de plan FICTIF"};
 expect(lireMeteoIntervention(p,args)?.cause).toEqual(p.cause);
});
test("tous risques explicitement sans objet : ok avec prévision nulle",()=>{
 const v=varianteFictive(source) as any;Object.assign(v.creneaux[0],{regles:[],prevision:null,sans_objet:["vent","pluie","gel","verglas","chaleur"]});
 expect(lireMeteoIntervention(v,args)?.statut).toBe("ok");v.creneaux[0].sans_objet.pop();expect(lireMeteoIntervention(v,args)).toBeNull();
});
test("sévérité native : bloquant avant inconnus et validation_requise",()=>{
 for(const statut of ["bloquant","validation_requise"]){const v=varianteFictive(source) as any;v.statut=statut;v.creneaux[0].statut=statut;v.creneaux[0].regles[0].statut=statut;v.creneaux[0].regles[1].statut="inconnu";expect(lireMeteoIntervention(v,args)?.statut).toBe(statut);}
});
test.each([
 ["date différente",(v:any)=>{v.creneaux[0].date="2026-10-07";}],
 ["date impossible",(v:any)=>{v.creneaux[0].date="2026-02-30";}],
 ["cible",(v:any)=>{v.intervention_id="a".repeat(64);}],
 ["cible créneau",(v:any)=>{v.creneaux[0].intervention_id="a".repeat(64);}],
 ["état",(v:any)=>{v.creneaux[0].statut_intervention="en_route";}],
 ["statut",(v:any)=>{v.creneaux[0].statut="bloquant";}],
 ["ok sans prévision",(v:any)=>{v.creneaux[0].prevision=null;}],
 ["ok avec cause",(v:any)=>{v.creneaux[0].cause={code:"REJ",detail:"manque"};}],
 ["numérique",(v:any)=>{v.creneaux[0].debut_min=-1;}],
 ["créneau inversé",(v:any)=>{v.creneaux[0].fin_min=1;}],
 ["émission sans fuseau",(v:any)=>{v.creneaux[0].prevision.emise_le="2026-10-04T18:00:00";}],
 ["mesures inventées",(v:any)=>{v.creneaux[0].prevision.temperature=12;}],
 ["clé inattendue",(v:any)=>{v.calendar=true;}],
 ["risque inventé",(v:any)=>{v.creneaux[0].regles[0].risque="neige";}],
 ["profil à configurer et ok",(v:any)=>{v.creneaux[0].a_configurer=["seuil FICTIF"]; }],
])("météo illisible : %s",(_,modifier)=>{const v=varianteFictive(source);modifier(v);expect(lireMeteoIntervention(v,args)).toBeNull();});
test("aucun double déballage ni getter",()=>{
 expect(lireMeteoIntervention({accepte:true,resultat:source},args)).toBeNull();
 let n=0;const v=varianteFictive(source);Object.defineProperty(v,"creneaux",{get(){n++;return [];}});expect(lireMeteoIntervention(v,args)).toBeNull();expect(n).toBe(0);
 expect(lireMeteoIntervention(source,construireArgumentsMeteoIntervention(source.intervention_id))).toBeNull();
});
test.each(["bloquant","validation_requise"])("%s sans prévision n'est pas une évaluation native",statut=>{
 const v=varianteFictive(source) as any;v.statut=statut;Object.assign(v.creneaux[0],{statut,prevision:null});v.creneaux[0].regles[0].statut=statut;
 expect(lireMeteoIntervention(v,args)).toBeNull();
});
test("source/licence/forfait et attribution distinctes sont conservés",()=>{
 const v=varianteFictive(source) as any;v.creneaux[0].prevision={source:"open_meteo",emise_le:"2026-10-04T18:00:00-04:00",heure_type:"heure_de_reception",licence:"CC BY 4.0",forfait:"fictif"};v.attributions=[{source:"open_meteo",attribution:"Attribution FICTIVE"}];
 expect(lireMeteoIntervention(v,args)).toEqual(v);
});

test.each(meteoCapturesFictives)("fidélité native $phase",capture=>{expect(lireMeteoIntervention(capture.dto,capture.args)).toEqual(capture.dto);});
