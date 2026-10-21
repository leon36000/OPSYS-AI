import { construireArgumentsRechercheAffaire, lireRechercheAffaire, OUTIL_RECHERCHE_AFFAIRE } from "./rechercheAffaire";
import paquetsPurs from "./fixturesPaquetAffaire.json";
const FICTIF = true;
const affaire = "LEAD-FICTIF~opp~WCT-FICTIF";
test("requête littérale fictive : quatre arguments exacts NFC, sans trim ou autorité client", () => {
  expect(FICTIF).toBe(true); expect(OUTIL_RECHERCHE_AFFAIRE).toBe("m10_rechercher_affaire_appareil");
  expect(construireArgumentsRechercheAffaire(affaire, " e\u0301 ")).toEqual({ affaire_id: affaire, requete: " é ", decalage: 0, limite: 8 });
  expect(construireArgumentsRechercheAffaire(affaire, "")).toEqual({ affaire_id: affaire, requete: "", decalage: 0, limite: 8 });
});
test.each(["", "../lead", "lead\n", "L~opp~W~opp~W", "x".repeat(65)])("refuse affaire invalide %s", id => {
  expect(() => construireArgumentsRechercheAffaire(id, "")).toThrow();
});
test.each(["x".repeat(201), "\u0000", "\n", "\t", "\u007f", "\ud800"])("refuse texte invalide %s", q => {
  expect(() => construireArgumentsRechercheAffaire(affaire, q)).toThrow();
});
test("borne NFC en points de code, conserve emoji et recherche hostile littérale", () => {
  expect(construireArgumentsRechercheAffaire(affaire,"😀".repeat(200)).requete).toHaveLength(400);
  expect(construireArgumentsRechercheAffaire(affaire,"e\u0301".repeat(200)).requete).toBe("é".repeat(200));
  expect(construireArgumentsRechercheAffaire(affaire,"%_.*' OR 1=1 --").requete).toBe("%_.*' OR 1=1 --");
});
test.each([-1, 1.5, 10001, Infinity, NaN, Number.MAX_SAFE_INTEGER])("offset interdit %s", off => {
  expect(() => construireArgumentsRechercheAffaire(affaire,"",off)).toThrow();
});
test.each([0,9,1.5,Infinity,NaN])("limite interdite %s", n => {
  expect(() => construireArgumentsRechercheAffaire(affaire,"",0,n)).toThrow();
});
test("offset10000 et limite1 légaux ; enveloppe vide n'est jamais un résultat", () => {
  const args=construireArgumentsRechercheAffaire(affaire,"",10000,1);
  expect(args).toEqual({affaire_id:affaire,requete:"",decalage:10000,limite:1});
  expect(lireRechercheAffaire({ok:true,resultat:{}},args)).toMatchObject({ok:false,code:"reponse_illisible"});
});
test("refus natif explicite prioritaire à la troncature ; verdict malformé ne devient pas succès", () => {
  const args=construireArgumentsRechercheAffaire(affaire,"");
  const r={ok:true,tronque:true,resultat:{accepte:false,verdict:{code:"REJ-IDENTITE-APPAREIL-INVALIDE",detail:"fictif : rôle retiré"}}};
  expect(lireRechercheAffaire(r,args)).toEqual({ok:false,...r.resultat.verdict});
  expect(lireRechercheAffaire({ok:false,erreur:"REJ-RECHERCHE-AFFAIRE-BORNE-SOURCES",details:"fictif"},args))
    .toEqual({ok:false,code:"REJ-RECHERCHE-AFFAIRE-BORNE-SOURCES",detail:"fictif"});
  for(const v of [{ok:true,resultat:{accepte:false,verdict:{code:"fictif"}}}, {ok:false,erreur:"refus_metier",details:["fictif",{}]}, {ok:false,details:"fictif"}])
    expect(lireRechercheAffaire(v,args)).toMatchObject({ok:false,code:"reponse_illisible"});
});
test("la copie du JSON entier refuse getter sans lecture et nonJSON même sur refus", () => {
  const args=construireArgumentsRechercheAffaire(affaire,"");let appels=0;
  const v={ok:true,resultat:{accepte:false,verdict:{code:"fictif",detail:"fictif"}}};
  Object.defineProperty(v,"cache",{enumerable:true,get(){appels++;return "fictif";}});
  expect(lireRechercheAffaire(v,args)).toMatchObject({ok:false,code:"reponse_illisible"});expect(appels).toBe(0);
  for(const bad of [NaN,Infinity,()=>null,new Date(),undefined])
    expect(lireRechercheAffaire({ok:true,resultat:{accepte:false,verdict:{code:"fictif",detail:"fictif"}},bad},args)).toMatchObject({ok:false,code:"reponse_illisible"});
});
test("arguments copiés avant getters ; forme/prototype fermés, pas de normalisation tardive", () => {
  let lectures=0; const args=construireArgumentsRechercheAffaire(affaire,"");
  Object.defineProperty(args,"requete",{get(){lectures++;return "";},enumerable:true});
  expect(lireRechercheAffaire({},args)).toMatchObject({ok:false,code:"reponse_illisible"});expect(lectures).toBe(0);
  const avecPrototype=construireArgumentsRechercheAffaire(affaire,"");Object.setPrototypeOf(avecPrototype,{requete:"fictif"});
  expect(lireRechercheAffaire({},avecPrototype)).toMatchObject({ok:false,code:"reponse_illisible"});
  const nonNFC={affaire_id:affaire,requete:"e\u0301",decalage:0,limite:8};
  expect(lireRechercheAffaire({},nonNFC)).toMatchObject({ok:false,code:"reponse_illisible"});
});

// DTO synthétique de contrat en RAM, jamais présenté comme une capture HTTP/outil.
// Le fait lui-même vient de la fixture canonique pure M10, sans modification des champs projetés.
const faitPur=paquetsPurs.reponses.quatre_couches.enveloppe.resultat.couches[1].faits[0];
const argsPurs=construireArgumentsRechercheAffaire(paquetsPurs.reponses.quatre_couches.arguments.affaire_id,faitPur.identifiant);
function pagePure() {
  return {ok:true,resultat:{
    affaire_id:argsPurs.affaire_id,requete:argsPurs.requete,mode:"litteral_nfc_casefold_v1",corpus:"evenements_et_consolidations_affaire_v1",
    resultats:[{...faitPur,genre:"fait_consolide",affaire_id:argsPurs.affaire_id,
      reference:{ligne_id:faitPur.identifiant,registre:"affaires",hash_tete:faitPur.identifiant}}],
    affaire:paquetsPurs.reponses.quatre_couches.enveloppe.resultat.affaire,
    pagination:{decalage:0,limite:8,affichees:1,total:1,suivant:null,reste:0,courante:true},
    couverture:{projections:"resume_200_caracteres",sources_parcourues:"completes",historique_consolidations:"derniere_version_par_cle",
      hors_corpus:["decisions_globales","revisions","signaux_traitements","developpement","documents_generiques"],plafond_lignes:10000},
    confidentialite:{agent:null,regle:"v1",niveaux:["PUBLIC_INTERNAL","INTERNAL"]},borne_caracteres:5400,taille_caracteres:1000,
  }};
}
test("une consolidation conserve l'identifiant du vrai maillon cité, aucun alias inventé", () => {
  expect(paquetsPurs.fictif).toBe(true);
  const v=pagePure();expect(lireRechercheAffaire(v,argsPurs)).toMatchObject({ok:true});
  v.resultat.resultats[0].identifiant="b".repeat(64);
  expect(lireRechercheAffaire(v,argsPurs)).toMatchObject({ok:false,code:"reponse_illisible"});
});
const clonePure=()=>JSON.parse(JSON.stringify(pagePure()));
const illisible={ok:false,code:"reponse_illisible"};
test.each([
  ["autre affaire",(v:ReturnType<typeof clonePure>)=>v.resultat.affaire_id="autre-fictive"],
  ["autre requête",(v:ReturnType<typeof clonePure>)=>v.resultat.requete+=" "],
  ["mode inventé",(v:ReturnType<typeof clonePure>)=>v.resultat.mode="semantique"],
  ["corpus global",(v:ReturnType<typeof clonePure>)=>v.resultat.corpus="documents"],
  ["champ ajouté",(v:ReturnType<typeof clonePure>)=>v.resultat.score=0],
  ["corpus incomplet",(v:ReturnType<typeof clonePure>)=>v.resultat.couverture.sources_parcourues="partielles"],
  ["autre projection",(v:ReturnType<typeof clonePure>)=>v.resultat.couverture.projections="document_entier"],
  ["anciennes consolidations",(v:ReturnType<typeof clonePure>)=>v.resultat.couverture.historique_consolidations="toutes_versions"],
  ["hors corpus absent",(v:ReturnType<typeof clonePure>)=>v.resultat.couverture.hors_corpus.pop()],
  ["borne sources changée",(v:ReturnType<typeof clonePure>)=>v.resultat.couverture.plafond_lignes=10001],
  ["agent privé",(v:ReturnType<typeof clonePure>)=>v.resultat.confidentialite.agent="m03-estimation"],
  ["niveau financier",(v:ReturnType<typeof clonePure>)=>v.resultat.confidentialite.niveaux.push("FINANCIAL")],
  ["compteur privé",(v:ReturnType<typeof clonePure>)=>v.resultat.confidentialite.nb_retenus=1],
  ["taille dépassée",(v:ReturnType<typeof clonePure>)=>v.resultat.taille_caracteres=5401],
  ["taille nulle",(v:ReturnType<typeof clonePure>)=>v.resultat.taille_caracteres=0],
  ["taille NaN",(v:ReturnType<typeof clonePure>)=>v.resultat.taille_caracteres=NaN],
  ["taille infinie",(v:ReturnType<typeof clonePure>)=>v.resultat.taille_caracteres=Infinity],
  ["taille non entière",(v:ReturnType<typeof clonePure>)=>v.resultat.taille_caracteres=1000.5],
  ["borne inconnue",(v:ReturnType<typeof clonePure>)=>v.resultat.borne_caracteres=6000],
  ["offset différent",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.decalage=1],
  ["limite différente",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.limite=1],
  ["page non courante",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.courante=false],
  ["total sources impossible",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.total=10001],
  ["total négatif",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.total=-1],
  ["total unsafe",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.total=Number.MAX_SAFE_INTEGER+1],
  ["nombre affiché faux",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.affichees=0],
  ["reste inventé",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.reste=1],
  ["suivant inventé",(v:ReturnType<typeof clonePure>)=>v.resultat.pagination.suivant=8],
  ["ligne d'une autre affaire",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].affaire_id="autre-fictive"],
  ["genre inconnu",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].genre="decision"],
  ["mauvais registre",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].reference.registre="evenements"],
  ["référence sans preuve",(v:ReturnType<typeof clonePure>)=>delete v.resultat.resultats[0].reference.hash_tete],
  ["tête globale étrangère",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].reference.hash_tete="b".repeat(64)],
  ["hash newline",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].reference.ligne_id+="\n"],
  ["hash uppercase",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].reference.ligne_id="A".repeat(64)],
  ["source inventée",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].source="registre.global"],
  ["source financière non marquée",(v:ReturnType<typeof clonePure>)=>{const f=v.resultat.resultats[0];f.genre="evenement";f.reference.registre="evenements";f.source="m5.rentabilite_chantier";}],
  ["compagnon financier non marqué",(v:ReturnType<typeof clonePure>)=>{const f=v.resultat.resultats[0];f.genre="evenement";f.reference.registre="evenements";f.source="m3.devis_accepte.montants";}],
  ["résumé trop long Unicode",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].resume="😀".repeat(201)],
  ["instant impossible",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].horodatage="2026-02-30T12:00:00Z"],
  ["instant sans fuseau",(v:ReturnType<typeof clonePure>)=>v.resultat.resultats[0].horodatage="2026-10-01T12:00:00"],
  ["affaire inconnue avec hit",(v:ReturnType<typeof clonePure>)=>v.resultat.affaire=paquetsPurs.reponses.inconnue.enveloppe.resultat.affaire],
  ["origine étrangère",(v:ReturnType<typeof clonePure>)=>v.resultat.affaire.origine="m2.client_associe"],
  ["origine reçue avec verdict",(v:ReturnType<typeof clonePure>)=>v.resultat.affaire.verdict="AMONT-ORIGINE-NON-RECUE"],
  ["doublon cité",(v:ReturnType<typeof clonePure>)=>{v.resultat.resultats.push(v.resultat.resultats[0]);v.resultat.pagination.total=2;v.resultat.pagination.affichees=2;}],
])("ferme DTO fictif corrompu %s",(_,modifier)=>{const v=clonePure();modifier(v);expect(lireRechercheAffaire(v,argsPurs)).toMatchObject(illisible);});
test.each(["CLIENT_PRIVATE","FINANCIAL","SENSITIVE","SECRET_REF","LEGAL_LOCKED","inconnu",null])("ligne hors visibilité %s",c=>{
  const v=clonePure();v.resultat.resultats[0].confidentialite=c;expect(lireRechercheAffaire(v,argsPurs)).toMatchObject(illisible);
});
test("offset après total est légal, connu sans match reste connu ; aucune taille JSON reconstruite",()=>{
  const v=clonePure();v.resultat.resultats=[];v.resultat.pagination={decalage:10000,limite:1,affichees:0,total:1,suivant:null,reste:0,courante:true};
  const args=construireArgumentsRechercheAffaire(argsPurs.affaire_id,argsPurs.requete,10000,1);
  const r=lireRechercheAffaire(v,args);expect(r).toEqual({ok:true,value:v.resultat});
  expect(r.ok&&r.value.affaire.connue).toBe(true);
  const sansMatch=clonePure();sansMatch.resultat.resultats=[];sansMatch.resultat.pagination.total=0;sansMatch.resultat.pagination.affichees=0;
  expect(lireRechercheAffaire(sansMatch,argsPurs)).toEqual({ok:true,value:sansMatch.resultat});
});
test("page réduite par budget : suivant avance du nombre natif affiché, jamais du maximum8",()=>{
  const v=clonePure();v.resultat.pagination.total=3;v.resultat.pagination.reste=2;v.resultat.pagination.suivant=1;
  expect(lireRechercheAffaire(v,argsPurs)).toEqual({ok:true,value:v.resultat});
  v.resultat.pagination.suivant=8;expect(lireRechercheAffaire(v,argsPurs)).toMatchObject(illisible);
});
test("une ligne illisible ne produit pas une page partielle ; corps/couple tronqués fermés",()=>{
  const v=clonePure();const r=lireRechercheAffaire(v,argsPurs);expect(r).toMatchObject({ok:true});
  v.resultat.resultats[0].resume="modifié";expect(r.ok&&r.value.resultats[0].resume).toBe(faitPur.resume);
  const sparse=clonePure();delete sparse.resultat.resultats[0];expect(lireRechercheAffaire(sparse,argsPurs)).toMatchObject(illisible);
  const proto=clonePure();Object.setPrototypeOf(proto.resultat.resultats[0],{secret:"fictif"});expect(lireRechercheAffaire(proto,argsPurs)).toMatchObject(illisible);
  const sym=clonePure();sym[Symbol("fictif")]=1;expect(lireRechercheAffaire(sym,argsPurs)).toMatchObject(illisible);
  const cycle=clonePure();cycle.cycle=cycle;expect(lireRechercheAffaire(cycle,argsPurs)).toMatchObject(illisible);
  expect(lireRechercheAffaire({ok:true,resultat:{accepte:true,resultat:pagePure().resultat}},argsPurs)).toMatchObject(illisible);
  expect(lireRechercheAffaire({...pagePure(),tronque:true},argsPurs)).toMatchObject({ok:false,code:"reponse_tronquee"});
});

// Captures immuables du vrai executer_atomique Python / SQLite fictif, sans Gateway/HTTP.
// Source ../qualification/M10-recherche-affaire-backend-r1/dto-reels-r3.json SHA256 5061f1278a57fd5674dd94eac46ce27ab72d552ca745292016087963d6161cea. Champs jamais modifiés.
const CAPTURES_BACKEND = {
  "fictif": true,
  "scope": "Python executer_atomique/SQLite ; pas Gateway/HTTP/device opaque",
  "provenance": {
    "repo": "/home/pc6/Documents/Codex/2026-10-05/github-plugin-github-openai-curated-remote-4/work/OPSYS-AI-m2-notes-20261008",
    "head": "8541cccf0b2ec0c88a92c148a37e49d8f91a6665",
    "sources_sha256": {
      "departments/m10-memoire/src/m10_memoire/recherche_affaire.py": "38d09cc2a5c899d56b35a75b30b0fff85f5e805f768b9521eb7b2bc6c05a0117",
      "departments/m10-memoire/src/m10_memoire/outils.py": "010358cc51e363e3ce216bc28f6d74520cc66fcaf70c006679b9246bf28268d4",
      "departments/m10-memoire/tests/test_recherche_affaire_appareil.py": "f63d505453f4133b1187b23c5dfd455f5676c11e38761b420db908dd56b5278b",
      "tests/test_portees_appareil.py": "3fc600bbd0455c1aaa4279c959723f1b0a2438fb685c2ad6e7a65cc952a2083d",
      "docs/architecture/ROLES.md": "ef7b664248a5e3460cfd25aa01bf332e8ff19ba1e03e658eaf12b686fa080093"
    },
    "sources_owned_inchangees": true,
    "producer_module": "/home/pc6/Documents/Codex/2026-10-05/github-plugin-github-openai-curated-remote-4/work/OPSYS-AI-m2-notes-20261008/departments/m10-memoire/src/m10_memoire/recherche_affaire.py",
    "tool_module": "/home/pc6/Documents/Codex/2026-10-05/github-plugin-github-openai-curated-remote-4/work/OPSYS-AI-m2-notes-20261008/departments/m10-memoire/src/m10_memoire/outils.py"
  },
  "captures": [
    {
      "phase": "inconnue",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [],
          "affaire": {
            "connue": false,
            "origine_recue": false,
            "origine": null,
            "verdict": "AMONT-AFFAIRE-INCONNUE"
          },
          "pagination": {
            "decalage": 0,
            "limite": 8,
            "affichees": 0,
            "total": 0,
            "suivant": null,
            "reste": 0,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 849
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [],
        "affaire": {
          "connue": false,
          "origine_recue": false,
          "origine": null,
          "verdict": "AMONT-AFFAIRE-INCONNUE"
        },
        "pagination": {
          "decalage": 0,
          "limite": 8,
          "affichees": 0,
          "total": 0,
          "suivant": null,
          "reste": 0,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 849
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "evenement",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "WCT-FICTIF-0",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "WCT-FICTIF-0",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-0",
              "horodatage": "2026-10-01T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-0 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d",
                "registre": "evenements",
                "hash_tete": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d"
              }
            }
          ],
          "affaire": {
            "connue": true,
            "origine_recue": false,
            "origine": null,
            "verdict": "AMONT-ORIGINE-NON-RECUE"
          },
          "pagination": {
            "decalage": 0,
            "limite": 8,
            "affichees": 1,
            "total": 1,
            "suivant": null,
            "reste": 0,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 1315
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "WCT-FICTIF-0",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-0",
            "horodatage": "2026-10-01T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-0 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d",
              "registre": "evenements",
              "hash_tete": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d"
            }
          }
        ],
        "affaire": {
          "connue": true,
          "origine_recue": false,
          "origine": null,
          "verdict": "AMONT-ORIGINE-NON-RECUE"
        },
        "pagination": {
          "decalage": 0,
          "limite": 8,
          "affichees": 1,
          "total": 1,
          "suivant": null,
          "reste": 0,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 1315
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "page-premiere",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "limite": 2,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-8",
              "horodatage": "2026-10-09T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-8 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313",
                "registre": "evenements",
                "hash_tete": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-7",
              "horodatage": "2026-10-08T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-7 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c",
                "registre": "evenements",
                "hash_tete": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c"
              }
            }
          ],
          "affaire": {
            "connue": true,
            "origine_recue": false,
            "origine": null,
            "verdict": "AMONT-ORIGINE-NON-RECUE"
          },
          "pagination": {
            "decalage": 0,
            "limite": 2,
            "affichees": 2,
            "total": 9,
            "suivant": 2,
            "reste": 7,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 1755
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-8",
            "horodatage": "2026-10-09T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-8 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313",
              "registre": "evenements",
              "hash_tete": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-7",
            "horodatage": "2026-10-08T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-7 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c",
              "registre": "evenements",
              "hash_tete": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c"
            }
          }
        ],
        "affaire": {
          "connue": true,
          "origine_recue": false,
          "origine": null,
          "verdict": "AMONT-ORIGINE-NON-RECUE"
        },
        "pagination": {
          "decalage": 0,
          "limite": 2,
          "affichees": 2,
          "total": 9,
          "suivant": 2,
          "reste": 7,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 1755
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "page-suivante",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "limite": 2,
          "decalage": 2
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-6",
              "horodatage": "2026-10-07T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-6 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c",
                "registre": "evenements",
                "hash_tete": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-5",
              "horodatage": "2026-10-06T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-5 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b",
                "registre": "evenements",
                "hash_tete": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b"
              }
            }
          ],
          "affaire": {
            "connue": true,
            "origine_recue": false,
            "origine": null,
            "verdict": "AMONT-ORIGINE-NON-RECUE"
          },
          "pagination": {
            "decalage": 2,
            "limite": 2,
            "affichees": 2,
            "total": 9,
            "suivant": 4,
            "reste": 5,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 1755
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-6",
            "horodatage": "2026-10-07T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-6 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c",
              "registre": "evenements",
              "hash_tete": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-5",
            "horodatage": "2026-10-06T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-5 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b",
              "registre": "evenements",
              "hash_tete": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b"
            }
          }
        ],
        "affaire": {
          "connue": true,
          "origine_recue": false,
          "origine": null,
          "verdict": "AMONT-ORIGINE-NON-RECUE"
        },
        "pagination": {
          "decalage": 2,
          "limite": 2,
          "affichees": 2,
          "total": 9,
          "suivant": 4,
          "reste": 5,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 1755
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "page-hors-total",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "limite": 8,
          "decalage": 10000
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [],
          "affaire": {
            "connue": true,
            "origine_recue": false,
            "origine": null,
            "verdict": "AMONT-ORIGINE-NON-RECUE"
          },
          "pagination": {
            "decalage": 10000,
            "limite": 8,
            "affichees": 0,
            "total": 9,
            "suivant": null,
            "reste": 0,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 853
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [],
        "affaire": {
          "connue": true,
          "origine_recue": false,
          "origine": null,
          "verdict": "AMONT-ORIGINE-NON-RECUE"
        },
        "pagination": {
          "decalage": 10000,
          "limite": 8,
          "affichees": 0,
          "total": 9,
          "suivant": null,
          "reste": 0,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 853
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "consolidation",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "m10:consolidation",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "m10:consolidation",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [
            {
              "genre": "fait_consolide",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
              "horodatage": "2026-10-08T09:00:00-04:00",
              "source": "m10:consolidation",
              "resume": "2026-10-08 : 1 travaux terminés",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
                "registre": "affaires",
                "hash_tete": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469"
              }
            }
          ],
          "affaire": {
            "connue": true,
            "origine_recue": false,
            "origine": null,
            "verdict": "AMONT-ORIGINE-NON-RECUE"
          },
          "pagination": {
            "decalage": 0,
            "limite": 8,
            "affichees": 1,
            "total": 1,
            "suivant": null,
            "reste": 0,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 1366
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "m10:consolidation",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [
          {
            "genre": "fait_consolide",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
            "horodatage": "2026-10-08T09:00:00-04:00",
            "source": "m10:consolidation",
            "resume": "2026-10-08 : 1 travaux terminés",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
              "registre": "affaires",
              "hash_tete": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469"
            }
          }
        ],
        "affaire": {
          "connue": true,
          "origine_recue": false,
          "origine": null,
          "verdict": "AMONT-ORIGINE-NON-RECUE"
        },
        "pagination": {
          "decalage": 0,
          "limite": 8,
          "affichees": 1,
          "total": 1,
          "suivant": null,
          "reste": 0,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 1366
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "mixte",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-8",
              "horodatage": "2026-10-09T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-8 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313",
                "registre": "evenements",
                "hash_tete": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-7",
              "horodatage": "2026-10-08T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-7 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c",
                "registre": "evenements",
                "hash_tete": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c"
              }
            },
            {
              "genre": "fait_consolide",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
              "horodatage": "2026-10-08T09:00:00-04:00",
              "source": "m10:consolidation",
              "resume": "2026-10-08 : 1 travaux terminés",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
                "registre": "affaires",
                "hash_tete": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-6",
              "horodatage": "2026-10-07T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-6 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c",
                "registre": "evenements",
                "hash_tete": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-5",
              "horodatage": "2026-10-06T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-5 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b",
                "registre": "evenements",
                "hash_tete": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-4",
              "horodatage": "2026-10-05T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-4 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "b471755467bcf0b2a7687645f065618510b693eb7f77db56bb3152869904ec67",
                "registre": "evenements",
                "hash_tete": "b471755467bcf0b2a7687645f065618510b693eb7f77db56bb3152869904ec67"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-3",
              "horodatage": "2026-10-04T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-3 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "31d24d66dea462b2043c41e02e24993782e1b5fd3cfb1793f629fff59e19fd35",
                "registre": "evenements",
                "hash_tete": "31d24d66dea462b2043c41e02e24993782e1b5fd3cfb1793f629fff59e19fd35"
              }
            },
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-2",
              "horodatage": "2026-10-03T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-2 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "112854f54dbd4f804775e757ba4ff16d54fb882bb428ed3e0dbb8ecb862074db",
                "registre": "evenements",
                "hash_tete": "112854f54dbd4f804775e757ba4ff16d54fb882bb428ed3e0dbb8ecb862074db"
              }
            }
          ],
          "affaire": {
            "connue": true,
            "origine_recue": false,
            "origine": null,
            "verdict": "AMONT-ORIGINE-NON-RECUE"
          },
          "pagination": {
            "decalage": 0,
            "limite": 8,
            "affichees": 8,
            "total": 10,
            "suivant": 8,
            "reste": 2,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 4532
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-8",
            "horodatage": "2026-10-09T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-8 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313",
              "registre": "evenements",
              "hash_tete": "fb5c27c63664350f7c41179d14608ea22f9026591a2666b2109a1ad839f2f313"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-7",
            "horodatage": "2026-10-08T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-7 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c",
              "registre": "evenements",
              "hash_tete": "8ef85edc7b35d4a6d5e4f0bf02dc49e0377b3c96622e28413abd38bfa0cb855c"
            }
          },
          {
            "genre": "fait_consolide",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
            "horodatage": "2026-10-08T09:00:00-04:00",
            "source": "m10:consolidation",
            "resume": "2026-10-08 : 1 travaux terminés",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469",
              "registre": "affaires",
              "hash_tete": "cd1699a6fadd8e9afc9dd1784542a725495dbb351f9740a891f4a9587efb3469"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-6",
            "horodatage": "2026-10-07T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-6 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c",
              "registre": "evenements",
              "hash_tete": "ec935eebab21359b123b2de4ae8ebbe144d7534fab9f7db8ec1c27773178c08c"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-5",
            "horodatage": "2026-10-06T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-5 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b",
              "registre": "evenements",
              "hash_tete": "df12ba8171fbcc21bf8a28623d348a3b0ab971c94a171893a8ac4f137a23409b"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-4",
            "horodatage": "2026-10-05T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-4 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "b471755467bcf0b2a7687645f065618510b693eb7f77db56bb3152869904ec67",
              "registre": "evenements",
              "hash_tete": "b471755467bcf0b2a7687645f065618510b693eb7f77db56bb3152869904ec67"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-3",
            "horodatage": "2026-10-04T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-3 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "31d24d66dea462b2043c41e02e24993782e1b5fd3cfb1793f629fff59e19fd35",
              "registre": "evenements",
              "hash_tete": "31d24d66dea462b2043c41e02e24993782e1b5fd3cfb1793f629fff59e19fd35"
            }
          },
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-2",
            "horodatage": "2026-10-03T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-2 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "112854f54dbd4f804775e757ba4ff16d54fb882bb428ed3e0dbb8ecb862074db",
              "registre": "evenements",
              "hash_tete": "112854f54dbd4f804775e757ba4ff16d54fb882bb428ed3e0dbb8ecb862074db"
            }
          }
        ],
        "affaire": {
          "connue": true,
          "origine_recue": false,
          "origine": null,
          "verdict": "AMONT-ORIGINE-NON-RECUE"
        },
        "pagination": {
          "decalage": 0,
          "limite": 8,
          "affichees": 8,
          "total": 10,
          "suivant": 8,
          "reste": 2,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 4532
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "origine-visible",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "lead",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "lead",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "LEAD-RECHERCHE-FICTIF",
              "horodatage": "2026-10-08T09:00:00-04:00",
              "source": "m1.lead_qualifie",
              "resume": "Lead qualifié : service gouttieres, canal texte, urgence non déclarée",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "6ce53aab7c7e4c32cb64c5ff5efa0540dc97f03d60e5927e537ca9bbacc0bdfb",
                "registre": "evenements",
                "hash_tete": "6ce53aab7c7e4c32cb64c5ff5efa0540dc97f03d60e5927e537ca9bbacc0bdfb"
              }
            }
          ],
          "affaire": {
            "connue": true,
            "origine_recue": true,
            "origine": "m1.lead_qualifie",
            "verdict": null
          },
          "pagination": {
            "decalage": 0,
            "limite": 8,
            "affichees": 1,
            "total": 1,
            "suivant": null,
            "reste": 0,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 1336
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "lead",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "LEAD-RECHERCHE-FICTIF",
            "horodatage": "2026-10-08T09:00:00-04:00",
            "source": "m1.lead_qualifie",
            "resume": "Lead qualifié : service gouttieres, canal texte, urgence non déclarée",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "6ce53aab7c7e4c32cb64c5ff5efa0540dc97f03d60e5927e537ca9bbacc0bdfb",
              "registre": "evenements",
              "hash_tete": "6ce53aab7c7e4c32cb64c5ff5efa0540dc97f03d60e5927e537ca9bbacc0bdfb"
            }
          }
        ],
        "affaire": {
          "connue": true,
          "origine_recue": true,
          "origine": "m1.lead_qualifie",
          "verdict": null
        },
        "pagination": {
          "decalage": 0,
          "limite": 8,
          "affichees": 1,
          "total": 1,
          "suivant": null,
          "reste": 0,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 1336
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "query-casefold-echo",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "WCT-fictif-0",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "WCT-fictif-0",
          "mode": "litteral_nfc_casefold_v1",
          "corpus": "evenements_et_consolidations_affaire_v1",
          "resultats": [
            {
              "genre": "evenement",
              "affaire_id": "LEAD-RECHERCHE-FICTIF",
              "identifiant": "WCT-FICTIF-0",
              "horodatage": "2026-10-01T09:00:00-04:00",
              "source": "m4.travaux_termines",
              "resume": "WCT WCT-FICTIF-0 : durée réelle 90 min",
              "confidentialite": "INTERNAL",
              "reference": {
                "ligne_id": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d",
                "registre": "evenements",
                "hash_tete": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d"
              }
            }
          ],
          "affaire": {
            "connue": true,
            "origine_recue": true,
            "origine": "m1.lead_qualifie",
            "verdict": null
          },
          "pagination": {
            "decalage": 0,
            "limite": 8,
            "affichees": 1,
            "total": 1,
            "suivant": null,
            "reste": 0,
            "courante": true
          },
          "couverture": {
            "projections": "resume_200_caracteres",
            "sources_parcourues": "completes",
            "historique_consolidations": "derniere_version_par_cle",
            "hors_corpus": [
              "decisions_globales",
              "revisions",
              "signaux_traitements",
              "developpement",
              "documents_generiques"
            ],
            "plafond_lignes": 10000
          },
          "confidentialite": {
            "agent": null,
            "regle": "v1",
            "niveaux": [
              "PUBLIC_INTERNAL",
              "INTERNAL"
            ]
          },
          "borne_caracteres": 5400,
          "taille_caracteres": 1307
        }
      },
      "envelope": {
        "affaire_id": "LEAD-RECHERCHE-FICTIF",
        "requete": "WCT-fictif-0",
        "mode": "litteral_nfc_casefold_v1",
        "corpus": "evenements_et_consolidations_affaire_v1",
        "resultats": [
          {
            "genre": "evenement",
            "affaire_id": "LEAD-RECHERCHE-FICTIF",
            "identifiant": "WCT-FICTIF-0",
            "horodatage": "2026-10-01T09:00:00-04:00",
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF-0 : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {
              "ligne_id": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d",
              "registre": "evenements",
              "hash_tete": "0d4039ea439bed6cc9653ee5b7fea6851d61e03238de980d0e3f143fb330658d"
            }
          }
        ],
        "affaire": {
          "connue": true,
          "origine_recue": true,
          "origine": "m1.lead_qualifie",
          "verdict": null
        },
        "pagination": {
          "decalage": 0,
          "limite": 8,
          "affichees": 1,
          "total": 1,
          "suivant": null,
          "reste": 0,
          "courante": true
        },
        "couverture": {
          "projections": "resume_200_caracteres",
          "sources_parcourues": "completes",
          "historique_consolidations": "derniere_version_par_cle",
          "hors_corpus": [
            "decisions_globales",
            "revisions",
            "signaux_traitements",
            "developpement",
            "documents_generiques"
          ],
          "plafond_lignes": 10000
        },
        "confidentialite": {
          "agent": null,
          "regle": "v1",
          "niveaux": [
            "PUBLIC_INTERNAL",
            "INTERNAL"
          ]
        },
        "borne_caracteres": 5400,
        "taille_caracteres": 1307
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "refus-borne-limite",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "limite": 9,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-RECHERCHE-AFFAIRE-ARGUMENTS-INVALIDES",
            "detail": "les arguments sortent du contrat de recherche par affaire"
          }
        }
      },
      "envelope": {
        "accepte": false,
        "verdict": {
          "code": "REJ-RECHERCHE-AFFAIRE-ARGUMENTS-INVALIDES",
          "detail": "les arguments sortent du contrat de recherche par affaire"
        }
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "refus-argument-canonique",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "../INVALIDE",
          "requete": "",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-RECHERCHE-AFFAIRE-ARGUMENTS-INVALIDES",
            "detail": "les arguments sortent du contrat de recherche par affaire"
          }
        }
      },
      "envelope": {
        "accepte": false,
        "verdict": {
          "code": "REJ-RECHERCHE-AFFAIRE-ARGUMENTS-INVALIDES",
          "detail": "les arguments sortent du contrat de recherche par affaire"
        }
      },
      "tables_integrales_inchangees": 49
    },
    {
      "phase": "refus-registre",
      "request": {
        "toolName": "m10_rechercher_affaire_appareil",
        "args": {
          "affaire_id": "LEAD-RECHERCHE-FICTIF",
          "requete": "",
          "limite": 8,
          "decalage": 0
        }
      },
      "response": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-RECHERCHE-AFFAIRE-REGISTRE-INVALIDE",
            "detail": "un registre métier ne satisfait pas son contrat d'intégrité"
          }
        }
      },
      "envelope": {
        "accepte": false,
        "verdict": {
          "code": "REJ-RECHERCHE-AFFAIRE-REGISTRE-INVALIDE",
          "detail": "un registre métier ne satisfait pas son contrat d'intégrité"
        }
      },
      "tables_integrales_inchangees": 49
    }
  ]
} as const;

test.each(CAPTURES_BACKEND.captures.map(c=>[c.phase,c] as const))("DTO réellement exécuté %s", (_,c)=> {
  expect(CAPTURES_BACKEND.fictif).toBe(true);expect(c.tables_integrales_inchangees).toBe(49);
  expect(c.request.toolName).toBe(OUTIL_RECHERCHE_AFFAIRE);
  const a=c.request.args;
  if(c.phase==="refus-borne-limite"||c.phase==="refus-argument-canonique") {
    expect(()=>construireArgumentsRechercheAffaire(a.affaire_id,a.requete,a.decalage,a.limite)).toThrow();
    expect(lireRechercheAffaire(c.response,a)).toMatchObject({ok:false,code:"reponse_illisible"});
    // Ces requêtes du harnais backend sont volontairement illégales pour le mobile.
    expect(c.response.resultat).toMatchObject({accepte:false,verdict:{code:"REJ-RECHERCHE-AFFAIRE-ARGUMENTS-INVALIDES"}});
  } else if(c.phase==="refus-registre") {
    expect(lireRechercheAffaire(c.response,a)).toEqual({ok:false,...c.response.resultat.verdict});
  } else {
    expect(construireArgumentsRechercheAffaire(a.affaire_id,a.requete,a.decalage,a.limite)).toEqual(a);
    expect(lireRechercheAffaire(c.response,a)).toEqual({ok:true,value:c.response.resultat});
  }
});
test("références des événements et consolidations capturées gardent leurs genres sans convertir l'identifiant public",()=>{
  const e=CAPTURES_BACKEND.captures.find(c=>c.phase==="evenement")!;
  const c=CAPTURES_BACKEND.captures.find(c=>c.phase==="consolidation")!;
  const re=lireRechercheAffaire(e.response,e.request.args),rc=lireRechercheAffaire(c.response,c.request.args);
  if(!re.ok||!rc.ok)throw new Error("captures Python réelles illisibles");
  expect(re.value.resultats[0]).toMatchObject({genre:"evenement",identifiant:"WCT-FICTIF-0",reference:{registre:"evenements"}});
  expect(re.value.resultats[0].reference.ligne_id).not.toBe(re.value.resultats[0].identifiant);
  expect(rc.value.resultats[0].identifiant).toBe(rc.value.resultats[0].reference.ligne_id);
});
