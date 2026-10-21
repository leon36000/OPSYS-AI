import { construireArgumentsRetardsIncidents, lireRetardsIncidents } from "./retardsIncidents";
import { retardsIncidentsFictifs as source, varianteFictive } from "./fixturesDispatch";
test("retards native DTO : âges serveur, origine, référence et non_mesurable conservés",()=>{
 expect(construireArgumentsRetardsIncidents(source.reference)).toEqual({horodatage_reference:source.reference});
 const v=lireRetardsIncidents(source,source.reference)!;expect(v).toEqual(source);expect(v).not.toBe(source);
 expect(v.reports.liste[0].heures_ecoulees).toBe(29);expect(v.retard_sur_cedule.statut).toBe("non_mesurable");
});
test("âge null et zéro ne sont pas confondus, origine appelant explicite",()=>{
 for(const age of [0,null]){const v=varianteFictive(source) as any;v.reports.liste[0].heures_ecoulees=age;v.reports.liste[0].origine_heure="appelant";v.incidents.liste[0].heures_ecoulees=age;v.incidents.liste[0].bloquee=false;v.incidents.bloques=0;
 expect(lireRetardsIncidents(v,v.reference)?.reports.liste[0].heures_ecoulees).toBe(age);}
});
test("omissions et suite exactes ; les incidents bloqués omis restent comptés",()=>{
 const v=varianteFictive(source);v.reports.total=2;v.reports.reste=1;v.reports.par_motif.meteo=1;v.reports.suite="1 de plus, du moins ancien au plus récent : m4_lister_interventions (statut reportee) les rend tous" as any;
 v.incidents.total=2;v.incidents.reste=1;v.incidents.par_type.anomalie_pointage=1;v.incidents.bloques=2;v.incidents.suite="1 de plus, du moins ancien au plus récent : m4_lister_pending_review les rend tous" as any;
 expect(lireRetardsIncidents(v,v.reference)?.incidents.bloques).toBe(2);
});
test.each([
 ["référence",(v:any)=>{v.reference="2026-10-07T12:00:00-04:00";}],
 ["total",(v:any)=>{v.reports.total=2;}],
 ["ventilation",(v:any)=>{v.reports.par_motif.meteo=1;}],
 ["suite",(v:any)=>{v.reports.suite="aller page suivante";}],
 ["heure sans fuseau",(v:any)=>{v.reports.liste[0].depuis="2026-10-05T11:00:00";}],
 ["âge négatif",(v:any)=>{v.reports.liste[0].heures_ecoulees=-1;}],
 ["origine inconnue",(v:any)=>{v.reports.liste[0].origine_heure="app";}],
 ["bloqué malgré âge",(v:any)=>{v.incidents.liste[0].bloquee=false;}],
 ["bloqués",(v:any)=>{v.incidents.bloques=2;}],
 ["raison perdue",(v:any)=>{v.retard_sur_cedule.manque="";}],
 ["retard inventé",(v:any)=>{v.retard_sur_cedule.statut="aucun";}],
 ["donnée contact",(v:any)=>{v.reports.liste[0].telephone="FICTIF";}],
 ["tableau creux",(v:any)=>{delete v.incidents.liste[0];}],
])("relevé illisible : %s",(_,modifier)=>{const v=varianteFictive(source);modifier(v);expect(lireRetardsIncidents(v,source.reference)).toBeNull();});
test("ni double déballage ni mutation, ancien relevé jamais recalculé",()=>{
 expect(lireRetardsIncidents({accepte:true,resultat:source},source.reference)).toBeNull();
 expect(lireRetardsIncidents(source,"2026-10-07T12:00:00-04:00")).toBeNull();
 expect(source.reports.liste[0].heures_ecoulees).toBe(29);
});
test("ordre et unicité des incidents ; champs supplémentaires du transport refusés",()=>{
 const v=varianteFictive(source);v.incidents.liste.push({...v.incidents.liste[0]});v.incidents.total=2;v.incidents.affiches=2;v.incidents.bloques=2;v.incidents.par_type.ecart_metier=2;
 expect(lireRetardsIncidents(v,v.reference)).toBeNull();
 const q=varianteFictive(source) as any;q.incidents.liste[0].depuis="2026-02-30T11:00:00+00:00";expect(lireRetardsIncidents(q,q.reference)).toBeNull();
});
test("ordre Python à la microseconde, distinct de l'âge serveur et de l'ordre des IDs",()=>{
 const v=varianteFictive(source);v.incidents.liste=[{...v.incidents.liste[0],demande_id:"b".repeat(64),depuis:"2026-10-05T11:00:00.000001+00:00"},{...v.incidents.liste[0],demande_id:"a".repeat(64),depuis:"2026-10-05T11:00:00.000002+00:00"}];
 v.incidents.total=2;v.incidents.affiches=2;v.incidents.par_type.ecart_metier=2;v.incidents.bloques=2;
 expect(lireRetardsIncidents(v,v.reference)?.incidents.liste).toEqual(v.incidents.liste);
 v.incidents.liste.reverse();expect(lireRetardsIncidents(v,v.reference)).toBeNull();
});
