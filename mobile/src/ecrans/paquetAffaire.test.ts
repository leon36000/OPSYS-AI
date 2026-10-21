import { presenterPaquetAffaire, vuePaquetAffaire } from "./paquetAffaire";
import { lirePaquetAffaire } from "../m10/paquetAffaire";
import capturesPures from "../m10/fixturesPaquetAffaire.json";
import capturesAppareil from "../m10/fixturesPaquetAffaireNative.json";
import type { PaquetAffaireM10 } from "../m10/paquetAffaire";
// Toutes les données de ce gabarit sont FICTIVES ; pas une capture HTTP ou une ingestion.
type Mutable<T> = T extends readonly (infer U)[] ? Mutable<U>[] : T extends object ? { -readonly [K in keyof T]: Mutable<T[K]> } : T;
function fixture(): Mutable<PaquetAffaireM10> {return {
 affaire_id:"LEAD-PAQUET-FICTIF",horodatage:"2026-10-08T10:00:00-04:00",budget_caracteres:4000,caracteres_utilises:2300,
 couches:[
  {nom:"regles_entreprise",vide:false,tronque:false,nb_total:1,nb_inclus:1,nb_omis:0,caracteres:300,
   faits:[{identifiant:"REGLE-FICTIVE",horodatage:"2026-10-07T10:00:00-04:00",source:"m10:decision",resume:"FICTIF : règle approuvée.",confidentialite:"INTERNAL"}]},
  {nom:"faits_affaire",vide:true,tronque:false,nb_total:0,nb_inclus:0,nb_omis:0,caracteres:0,faits:[]},
  {nom:"evenements_recents",vide:false,tronque:true,nb_total:6,nb_inclus:1,nb_omis:5,caracteres:1700,
   faits:[{identifiant:"WCT-FICTIF",horodatage:"2026-10-08T09:00:00-04:00",source:"m4.travaux_termines",resume:"WCT FICTIF : durée réelle100min",confidentialite:"INTERNAL"}]},
  {nom:"signaux_non_resolus",vide:false,tronque:false,nb_total:1,nb_inclus:1,nb_omis:0,caracteres:300,
   faits:[{identifiant:"SIGNAL-FICTIF",horodatage:"2026-10-08T09:05:00-04:00",source:"m6.variance_chantier",resume:"FICTIF : variance reçue.",confidentialite:"INTERNAL",etat:"ouvert",traite_par:null,traite_le:null}]},
 ],signaux:{nb_ouverts:2,nb_pris_en_compte:1,nb_clos:3},confidentialite:{agent:null,regle:"v1",nb_retenus:4},
 affaire:{connue:true,origine_recue:true,origine:"m1.lead_qualifie",verdict:null},
 consolidation:{a_consolider:[{affaire_id:"LEAD-PAQUET-FICTIF",jour:"2026-10-06"}],nb_a_consolider:2}
};}
function presenter(v=fixture(),decalage=-240){return presenterPaquetAffaire(v,decalage);}
test("reprend quatre couches dans l'ordre natif, leurs compteurs et le budget faits seuls",()=>{
 const v=fixture(),avant=JSON.stringify(v),vue=presenter(v);
 expect(vue.couches.map(c=>c.nom)).toEqual(["regles_entreprise","faits_affaire","evenements_recents","signaux_non_resolus"]);
 expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.budgetFaits",params:{budget:4000,utilises:2300}});
 expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.budgetCadreExclu"});
 expect(vue.couches[2].lignes).toContainEqual({cle:"admin.paquetAffaire.coucheCaracteres",params:{caracteres:1700}});
 expect(vue.couches[2].lignes).toContainEqual({cle:"admin.paquetAffaire.coucheComptes",params:{total:6,inclus:1,omis:5}});
 expect(vue.couches[2].lignes).toContainEqual({cle:"admin.paquetAffaire.coucheTronquee"});
 expect(vue.couches[1].lignes).toContainEqual({cle:"admin.paquetAffaire.coucheVide"});
 expect(JSON.stringify(v)).toBe(avant);
});
test("origine, confidentialité et signaux natifs ne se déduisent pas des faits visibles",()=>{
 const vue=presenter();expect(vue.etatAffaire).toContainEqual({cle:"admin.paquetAffaire.connue"});
 expect(vue.etatAffaire).toContainEqual({cle:"admin.paquetAffaire.origineRecue"});
 expect(vue.confidentialite).toContainEqual({cle:"admin.paquetAffaire.confidentialite",params:{regle:"v1",retenus:4}});
 expect(vue.confidentialite).toContainEqual({cle:"admin.paquetAffaire.vueRestrictive"});
 expect(vue.signaux).toContainEqual({cle:"admin.paquetAffaire.signaux",params:{ouverts:2,pris:1,clos:3}});
 expect(vue.couches[3].faits[0].lignes).toContainEqual({cle:"admin.paquetAffaire.etatSignal",params:{etat:"ouvert"}});
 expect(vue.couches[3].faits[0].lignes).toContainEqual({cle:"admin.paquetAffaire.traitementInconnu"});
});
test("affaire inconnue et origine manquante restent explicites, aucun avis favorable",()=>{
 const v=fixture();v.affaire={connue:false,origine_recue:false,origine:null,verdict:"AMONT-AFFAIRE-INCONNUE"};
 const vue=presenter(v);expect(vue.etatAffaire).toContainEqual({cle:"admin.paquetAffaire.inconnue"});
 expect(vue.etatAffaire).toContainEqual({cle:"admin.paquetAffaire.origineManquante"});
 expect(vue.etatAffaire).toContainEqual({cle:"admin.paquetAffaire.origineInconnue"});
 expect(vue.etatAffaire).toContainEqual({cle:"admin.paquetAffaire.verdict",params:{code:"AMONT-AFFAIRE-INCONNUE"}});
});
test("jour de consolidation informatif sans conversion ni nouvelle action",()=>{
 const vue=presenter(fixture(),600);expect(vue.consolidation).toContainEqual({cle:"admin.paquetAffaire.consolidationTotal",params:{nombre:2}});
 expect(vue.consolidation).toContainEqual({cle:"admin.paquetAffaire.consolidationJour",params:{affaire:"LEAD-PAQUET-FICTIF",jour:"2026-10-06"}});
 expect(vue.consolidation).toContainEqual({cle:"admin.paquetAffaire.consolidationInformative"});
 expect(JSON.stringify(vue)).not.toContain("m10_consolider_affaire");
});
test("affaire opportunité validée reste entière, sans découpage ni lien inventé",()=>{
 const v=fixture();v.affaire_id="LEAD-FICTIF~opp~WCT-FICTIF";v.consolidation.a_consolider[0].affaire_id=v.affaire_id;
 const vue=presenter(v);expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.identification",params:{affaire:"LEAD-FICTIF~opp~WCT-FICTIF"}});
 expect(vue.consolidation).toContainEqual({cle:"admin.paquetAffaire.consolidationJour",params:{affaire:"LEAD-FICTIF~opp~WCT-FICTIF",jour:"2026-10-06"}});
 expect(JSON.stringify(vue)).not.toContain("lead_id");expect(JSON.stringify(vue)).not.toContain("navigation");
});
test("sources fermées exactes remplacées par labels sourcés sans accepter leurs extensions",()=>{
 const vue=presenter();expect(vue.couches[0].faits[0].lignes).toContainEqual({cle:"admin.paquetAffaire.sourceDecision"});
 expect(vue.couches[2].faits[0].lignes).toContainEqual({cle:"admin.paquetAffaire.sourceWct"});
 const v=fixture();v.couches[0].faits[0].source="m10:decision /srv/secret";
 expect(JSON.stringify(presenter(v))).not.toContain("/srv/secret");
});
test("tous textes et références dangereux sont masqués, exception affaire bornée seulement",()=>{
 const v=fixture();v.affaire_id="/srv/secret";v.affaire.origine="/srv/origine";v.affaire.verdict="opsys-metier secret";
 for(const c of v.couches)for(const f of c.faits)Object.assign(f,{identifiant:"$TOKEN",resume:"cat /srv/secret",source:"/srv/source"});
 v.consolidation.a_consolider[0].affaire_id="LEAD~opp~WCT~opp~AUTRE";
 const vue=presenter(v),texte=JSON.stringify(vue);for(const s of ["/srv/","$TOKEN","opsys-metier","~opp~AUTRE"])expect(texte).not.toContain(s);
 expect(texte).toContain("admin.paquetAffaire.detailMasque");
});
test("zéro et absence de consolidation sont dits sans inventer une réussite mémoire",()=>{
 const v=fixture();v.consolidation={a_consolider:[],nb_a_consolider:0};v.signaux={nb_ouverts:0,nb_pris_en_compte:0,nb_clos:0};
 const vue=presenter(v);expect(vue.consolidation).toContainEqual({cle:"admin.paquetAffaire.aucuneConsolidationListee"});
 expect(vue.signaux).toContainEqual({cle:"admin.paquetAffaire.signaux",params:{ouverts:0,pris:0,clos:0}});
 expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.paquetPartiel"});
});
test("wrapper distingue donnée serveur, refus et indisponibilité",()=>{
 expect(vuePaquetAffaire({source:"serveur",valeur:fixture(),misAJourLe:"2026-10-08T14:00:00Z"},-240).genre).toBe("contenu");
 expect(vuePaquetAffaire({source:"refus",verdict:{code:"REJ-FICTIF",detail:""}},-240).genre).toBe("refus");
 expect(vuePaquetAffaire({source:"aucune",raison:{code:"hors_ligne",detail:""}},-240).genre).toBe("aucune");
});

// Sorties du module Python pur, agentNone : aucune attestation HTTP ou révocation native.
test.each(Object.entries(capturesPures.reponses))("capture pure %s conserve les faits et limites natives",(_nom,capture)=>{
 expect(capturesPures.fictif).toBe(true);const r=lirePaquetAffaire(capture.enveloppe,capture.arguments.affaire_id,capture.arguments.horodatage);
 if(!r.ok)throw new Error("capture pure fictive refusée : "+r.code);
 const v=r.value,vue=presenterPaquetAffaire(v,-240);
 expect(vue.couches.map(c=>c.nom)).toEqual(["regles_entreprise","faits_affaire","evenements_recents","signaux_non_resolus"]);
 expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.identification",params:{affaire:capture.arguments.affaire_id}});
 expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.budgetFaits",params:{budget:4000,utilises:v.caracteres_utilises}});
 for(let i=0;i<v.couches.length;i++){
  const c=v.couches[i];expect(vue.couches[i].faits).toHaveLength(c.faits.length);
  expect(vue.couches[i].lignes).toContainEqual({cle:"admin.paquetAffaire.coucheComptes",params:{total:c.nb_total,inclus:c.nb_inclus,omis:c.nb_omis}});
 }
});

// Candidate DEVICE réelle, distincte des fixtures pures et de la route Core privée.
// Ce consommateur ne simule ni le Gateway ni une nouvelle ingestion/révocation.
test.each(Object.entries(capturesAppareil.positives))("capture candidate DEVICE %s conserve dossier et omissions natifs",(_nom,capture)=>{
 expect(capturesAppareil.fictif).toBe(true);
 const r=lirePaquetAffaire(capture.enveloppe,capture.arguments.affaire_id,capture.arguments.horodatage);
 if(!r.ok)throw new Error("capture candidate fictive refusée : "+r.code);
 const v=r.value,vue=presenterPaquetAffaire(v,-240);
 expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.identification",params:{affaire:capture.arguments.affaire_id}});
 expect(vue.lignes).toContainEqual({cle:"admin.paquetAffaire.budgetCadreExclu"});
 expect(vue.etatAffaire).toContainEqual({cle:v.affaire.connue?"admin.paquetAffaire.connue":"admin.paquetAffaire.inconnue"});
 expect(vue.etatAffaire).toContainEqual({cle:v.affaire.origine_recue?"admin.paquetAffaire.origineRecue":"admin.paquetAffaire.origineManquante"});
 expect(vue.confidentialite).toContainEqual({cle:"admin.paquetAffaire.vueRestrictive"});
 expect(vue.confidentialite).toContainEqual({cle:"admin.paquetAffaire.confidentialite",params:{regle:"v1",retenus:v.confidentialite.nb_retenus}});
 expect(vue.signaux).toContainEqual({cle:"admin.paquetAffaire.signaux",params:{ouverts:v.signaux.nb_ouverts,pris:v.signaux.nb_pris_en_compte,clos:v.signaux.nb_clos}});
 expect(vue.consolidation).toContainEqual({cle:"admin.paquetAffaire.consolidationTotal",params:{nombre:v.consolidation.nb_a_consolider}});
 for(let i=0;i<v.couches.length;i++){
  const c=v.couches[i];expect(vue.couches[i].faits).toHaveLength(c.faits.length);
  expect(vue.couches[i].lignes).toContainEqual({cle:"admin.paquetAffaire.coucheComptes",params:{total:c.nb_total,inclus:c.nb_inclus,omis:c.nb_omis}});
 }
});
