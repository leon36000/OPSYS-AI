import { presenterLectureStrategique, vueLectureStrategique } from "./lectureStrategique";
import { lireLectureStrategique } from "../m9/lectureStrategique";
import type { LectureStrategiqueM9 } from "../m9/lectureStrategique";
import capturesPures from "../m9/fixturesLectureStrategique.json";
type Mutable<T> = T extends readonly (infer U)[] ? Mutable<U>[] : T extends object ? { -readonly [K in keyof T]: Mutable<T[K]> } : T;
// Fixtures de modèle entièrement FICTIVES, issues du contrat Python lecture_strategique.py.
// Elles ne revendiquent ni Gateway, ni SQLite, ni appareil natif.
function fixture(): Mutable<LectureStrategiqueM9> {
 return {type:"LECTURE_STRATEGIQUE_M8",jour:"2026-10-08",periode:{du:"2026-10-05",au:"2026-10-08"},
 source:"m8.alerte_proposee (registre m09-strategic-intelligence/alertes_m8)",resume:"FICTIF : preuve M8 à examiner.",
 decision:{prise_par_m9:false,a_prendre_par:"nathan_owner",requise:true},preuves_m8:["m8_ecart_duree_pct"],
 par_metrique:[{metric_id:"m8_ecart_duree_pct",nb_alertes:1,nb_chantiers:1,a_qui:["m04-field-ops"]}],
 manques:{seuils_a_configurer:["m8_ecart_marge_pct"],alertes_de_qualite_non_relues:2},
 lectures:[{metric_id:"m8_ecart_duree_pct",version_definition:"ab".repeat(32),evenement_id:"m8-alerte-fictive",chantier:"WCT-fictif",
 valeur:"40.00",unite:"pourcentage",sens:"au_dessus",seuil:"30.00",regle:"FICTIF : règle fournie par M8.",
 a_qui:"m04-field-ops",action_proposee_par_m8:null,source:"M4 m4.travaux_termines ; M3 m3.devis_accepte",statut_decision:"en_attente_du_proprietaire"}],
 affichage:{borne_caracteres:5400,taille_caracteres:2345,n_lectures:3,depart:1,affichees:1,reste:1,prochain_depart:2,message:"FICTIF : une lecture non affichée."}};
}
function presenter(v=fixture()) {
 return presenterLectureStrategique(v,-240);
}
test("cite la preuve40.00, seuil30.00, version et WCT sans calcul ni décision locale",()=>{
 const v=fixture(),avant=JSON.stringify(v),vue=presenter(v);
 expect(vue.lignes).toContainEqual({cle:"admin.lectureStrategique.decisionNonPrise"});
 expect(vue.lignes).toContainEqual({cle:"admin.lectureStrategique.decideur",params:{personne:"nathan_owner"}});
 expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.mesure",params:{valeur:"40.00",unite:"pourcentage"}});
 expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.seuil",params:{seuil:"30.00",sens:"au_dessus"}});
 expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.version",params:{version:"ab".repeat(32)}});
 expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.chantier",params:{id:"WCT-fictif"}});
 expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.actionAbsente"});
 expect(JSON.stringify(vue)).not.toContain("lead_id");expect(JSON.stringify(v)).toBe(avant);
});
test("pagination et qualité reprennent les comptes natifs sans promettre exhaustivité",()=>{
 const vue=presenter();expect(vue.pagination).toContainEqual({cle:"admin.lectureStrategique.pagination",params:{total:3,depart:1,affichees:1,reste:1}});
 expect(vue.pagination).toContainEqual({cle:"admin.lectureStrategique.borne",params:{borne:5400,taille:2345}});
 expect(vue.pagination).toContainEqual({cle:"admin.lectureStrategique.prochain",params:{depart:2}});
 expect(vue.pagination).toContainEqual({cle:"admin.lectureStrategique.pageNonFigee"});
 expect(vue.manques).toContainEqual({cle:"admin.lectureStrategique.qualiteNonRelue",params:{nombre:2}});
 expect(vue.metriques[0].lignes).toContainEqual({cle:"admin.lectureStrategique.agregat",params:{alertes:1,chantiers:1}});
});
test("zéro, false et absence restent explicites plutôt qu'un avis favorable",()=>{
 const v=fixture();v.decision.requise=false;v.preuves_m8=[];v.par_metrique=[];v.lectures=[];
 v.manques={seuils_a_configurer:[],alertes_de_qualite_non_relues:0};
 v.affichage={...v.affichage,n_lectures:0,depart:0,affichees:0,reste:0,prochain_depart:null,message:null};
 const vue=presenter(v);expect(vue.lignes).toContainEqual({cle:"admin.lectureStrategique.decisionNonRequise"});
 expect(vue.preuves).toContainEqual({cle:"admin.lectureStrategique.aucunePreuve"});
 expect(vue.manques).toContainEqual({cle:"admin.lectureStrategique.qualiteNonRelue",params:{nombre:0}});
 expect(vue.pagination).toContainEqual({cle:"admin.lectureStrategique.finPage"});
});
test("jour et période civils ne changent pas selon fuseau ; source fermée remplace son chemin",()=>{
 const vue=presenter();expect(vue.lignes).toContainEqual({cle:"admin.lectureStrategique.jour",params:{jour:"2026-10-08"}});
 expect(vue.lignes).toContainEqual({cle:"admin.lectureStrategique.periode",params:{du:"2026-10-05",au:"2026-10-08"}});
 expect(vue.lignes).toContainEqual({cle:"admin.lectureStrategique.sourceAlertesM8"});expect(JSON.stringify(vue)).not.toContain("/alertes_m8");
});
test("texte dangereux masqué dans toutes les preuves sans élargir le filtre",()=>{
 const v=fixture();v.resume="Lire /srv/secret.yaml";v.source="m8.alerte_proposee (registre m09-strategic-intelligence/alertes_m8) EXTRA /srv/secret";
 v.decision.a_prendre_par="opsys-metier secret";v.preuves_m8=["/srv/metric"];
 v.par_metrique=[{metric_id:"/srv/metric",nb_alertes:1,nb_chantiers:1,a_qui:["$HOME"]}];v.manques.seuils_a_configurer=["/srv/metric"];
 const l=v.lectures[0];Object.assign(l,{metric_id:"/srv/metric",version_definition:"/srv/version",evenement_id:"$TOKEN",chantier:"/srv/WCT",valeur:"$SECRET",unite:"/srv/unit",seuil:"$SECRET",regle:"opsys-metier secret",a_qui:"$HOME",source:"/srv/source",action_proposee_par_m8:"cat /srv/secret"});
 const vue=presenter(v),texte=JSON.stringify(vue);for(const interdit of ["/srv","$HOME","$TOKEN","$SECRET","opsys-metier"])expect(texte).not.toContain(interdit);
 expect(texte).toContain("admin.lectureStrategique.detailMasque");
});
test("action M8 sûre transmise verbatim et statut n'autorise aucune action",()=>{
 const v=fixture();v.lectures[0].action_proposee_par_m8="FICTIF : examiner le temps enregistré.";
 const vue=presenter(v);expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.action",params:{action:"FICTIF : examiner le temps enregistré."}});
 expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.statutDecision",params:{statut:"en_attente_du_proprietaire"}});
});
test("wrapper conserve serveur, refus et absence de lecture",()=>{
 const vue=vueLectureStrategique({source:"serveur",valeur:fixture(),misAJourLe:"2026-10-08T14:00:00Z"},-240);
 expect(vue.genre).toBe("contenu");if(vue.genre!=="contenu")throw new Error("lecture fictive attendue");expect(vue.horsLigne).toBeNull();
 expect(vueLectureStrategique({source:"refus",verdict:{code:"REJ-FICTIF",detail:""}},-240).genre).toBe("refus");
 expect(vueLectureStrategique({source:"aucune",raison:{code:"hors_ligne",detail:""}},-240).genre).toBe("aucune");
});

// Ces8captures ont été produites par le module Python pur, pas par HTTP/Gateway.
test.each(Object.entries(capturesPures.reponses))("capture pure native %s conserve ses limites et preuves",(_nom,capture)=>{
 expect(capturesPures.fictif).toBe(true);
 const dto=lireLectureStrategique(capture.enveloppe.resultat,capture.arguments.maintenant,capture.arguments.depart);
 expect(dto).not.toBeNull();const v=dto!,vue=presenterLectureStrategique(v,-240);
 expect(vue.lectures).toHaveLength(v.lectures.length);
 expect(vue.pagination).toContainEqual({cle:"admin.lectureStrategique.pagination",params:{total:v.affichage.n_lectures,depart:v.affichage.depart,affichees:v.affichage.affichees,reste:v.affichage.reste}});
 for(let i=0;i<v.lectures.length;i++){
  expect(vue.lectures[i].lignes).toContainEqual({cle:"admin.lectureStrategique.mesure",params:{valeur:v.lectures[i].valeur,unite:v.lectures[i].unite}});
  expect(vue.lectures[i].lignes).toContainEqual({cle:"admin.lectureStrategique.version",params:{version:v.lectures[i].version_definition}});
 }
 expect(JSON.stringify(vue)).not.toContain("registre m09-strategic-intelligence/");
});

// Enveloppes HTTP MCP réelles sur données fictives ; cette consommation reste un test de vue pur.
test.each(Object.entries(capturesPures.capturesHttp.lectures))("capture HTTP native %s montre les preuves fournies, sans nouvelle décision",(nom,capture)=>{
 expect(capture.fictif).toBe(true);expect(capture.all_entire_tables_unchanged).toBe(true);
 const dto=lireLectureStrategique(capture.enveloppe.resultat,capture.arguments.maintenant,capture.arguments.depart);
 expect(dto).not.toBeNull();const v=dto!,vue=presenterLectureStrategique(v,-240);
 expect(vue.lignes).toContainEqual({cle:"admin.lectureStrategique.decisionNonPrise"});
 expect(vue.pagination).toContainEqual({cle:"admin.lectureStrategique.borne",params:{borne:v.affichage.borne_caracteres,taille:v.affichage.taille_caracteres}});
 expect(vue.lectures).toHaveLength(v.lectures.length);expect(JSON.stringify(vue)).not.toContain("/alertes_m8");
 if(nom==="ordinaire-40-30"){
  expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.mesure",params:{valeur:"40.00",unite:"pourcentage"}});
  expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.seuil",params:{seuil:"30.00",sens:"au_dessus"}});
  expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.chantier",params:{id:"e36d9748d1f4806da4e15fc08bce3939dcc10e3247d921b281fdd091f198498e"}});
  expect(vue.lectures[0].lignes).toContainEqual({cle:"admin.lectureStrategique.version",params:{version:"db98dea358392c834b1261bde2d416deae2df826c8060dd5eb8daa089e9f8200"}});
 }
});
