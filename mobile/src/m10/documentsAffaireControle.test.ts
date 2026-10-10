import { creerControleDocumentsAffaireM10 } from "./documentsAffaireControle";
import { DepotOutboxMemoire } from "../outbox/depot";
import { creerMutationDocumentM10, argumentsRpcDocumentM10 } from "./documentsAffaireOutbox";
import type { SessionEnvoi } from "../protocole/configuration";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import { lireIndexDocumentsAffaireM10, lireVersionDocumentAffaireM10 } from "./documentsAffaireLecture";
const FIXTURES = {
  "deposee": {
    "index": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "decalage": 0,
      "limite": 1,
      "total_versions": 1,
      "suivant_decalage": null,
      "versions": [
        {
          "version_schema": 1,
          "affaire_id": "LEAD-DOCUMENT-FICTIF",
          "document_ref": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "version_source": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "statut": "DEPOSEE_NON_ACTIVEE",
          "titre": "Note FICTIVE",
          "methode": "utf8-exact-v1",
          "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
          "taille_points": 33,
          "taille_octets": 37,
          "auteur": {
            "personne": "admin_fictif",
            "role": "admin",
            "source": "appareil"
          },
          "horodatage": "2026-10-10T03:47:55+00:00",
          "activation_ref": null,
          "version_no": 1,
          "version_precedente_attendue": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "activation_attendue": null
        }
      ]
    },
    "detail": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "document_ref": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "version_source": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "statut": "DEPOSEE_NON_ACTIVEE",
      "titre": "Note FICTIVE",
      "methode": "utf8-exact-v1",
      "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
      "taille_points": 33,
      "taille_octets": 37,
      "auteur": {
        "personne": "admin_fictif",
        "role": "admin",
        "source": "appareil"
      },
      "horodatage": "2026-10-10T03:47:55+00:00",
      "activation_ref": null,
      "corps": "CANARI_TRANSACTION_FICTIVE_Aé😀\r\nZ"
    }
  },
  "activee": {
    "index": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "decalage": 0,
      "limite": 1,
      "total_versions": 1,
      "suivant_decalage": null,
      "versions": [
        {
          "version_schema": 1,
          "affaire_id": "LEAD-DOCUMENT-FICTIF",
          "document_ref": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "version_source": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "statut": "COURANTE",
          "titre": "Note FICTIVE",
          "methode": "utf8-exact-v1",
          "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
          "taille_points": 33,
          "taille_octets": 37,
          "auteur": {
            "personne": "admin_fictif",
            "role": "admin",
            "source": "appareil"
          },
          "horodatage": "2026-10-10T03:47:55+00:00",
          "activation_ref": {
            "registre": "documents_affaire",
            "index": 1,
            "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
          },
          "version_no": 1,
          "version_precedente_attendue": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "activation_attendue": {
            "registre": "documents_affaire",
            "index": 1,
            "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
          }
        }
      ]
    },
    "detail": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "document_ref": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "version_source": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "statut": "COURANTE",
      "titre": "Note FICTIVE",
      "methode": "utf8-exact-v1",
      "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
      "taille_points": 33,
      "taille_octets": 37,
      "auteur": {
        "personne": "admin_fictif",
        "role": "admin",
        "source": "appareil"
      },
      "horodatage": "2026-10-10T03:47:55+00:00",
      "activation_ref": {
        "registre": "documents_affaire",
        "index": 1,
        "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
      },
      "corps": "CANARI_TRANSACTION_FICTIVE_Aé😀\r\nZ"
    }
  },
  "seconde_deposee": {
    "index": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "decalage": 0,
      "limite": 1,
      "total_versions": 2,
      "suivant_decalage": 1,
      "versions": [
        {
          "version_schema": 1,
          "affaire_id": "LEAD-DOCUMENT-FICTIF",
          "document_ref": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "version_source": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "statut": "COURANTE",
          "titre": "Note FICTIVE",
          "methode": "utf8-exact-v1",
          "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
          "taille_points": 33,
          "taille_octets": 37,
          "auteur": {
            "personne": "admin_fictif",
            "role": "admin",
            "source": "appareil"
          },
          "horodatage": "2026-10-10T03:47:55+00:00",
          "activation_ref": {
            "registre": "documents_affaire",
            "index": 1,
            "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
          },
          "version_no": 1,
          "version_precedente_attendue": {
            "registre": "documents_affaire",
            "index": 2,
            "ligne_id": "435076b237016d07cc30f2f707e0d0017e34dd6853d3d4127d2813cc450bccab"
          },
          "activation_attendue": {
            "registre": "documents_affaire",
            "index": 1,
            "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
          }
        }
      ]
    },
    "detail": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "document_ref": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "version_source": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "statut": "COURANTE",
      "titre": "Note FICTIVE",
      "methode": "utf8-exact-v1",
      "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
      "taille_points": 33,
      "taille_octets": 37,
      "auteur": {
        "personne": "admin_fictif",
        "role": "admin",
        "source": "appareil"
      },
      "horodatage": "2026-10-10T03:47:55+00:00",
      "activation_ref": {
        "registre": "documents_affaire",
        "index": 1,
        "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
      },
      "corps": "CANARI_TRANSACTION_FICTIVE_Aé😀\r\nZ"
    }
  },
  "retiree": {
    "index": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "decalage": 0,
      "limite": 1,
      "total_versions": 2,
      "suivant_decalage": 1,
      "versions": [
        {
          "version_schema": 1,
          "affaire_id": "LEAD-DOCUMENT-FICTIF",
          "document_ref": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "version_source": {
            "registre": "documents_affaire",
            "index": 0,
            "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
          },
          "statut": "RETIREE",
          "titre": "Note FICTIVE",
          "methode": "utf8-exact-v1",
          "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
          "taille_points": 33,
          "taille_octets": 37,
          "auteur": {
            "personne": "admin_fictif",
            "role": "admin",
            "source": "appareil"
          },
          "horodatage": "2026-10-10T03:47:55+00:00",
          "activation_ref": {
            "registre": "documents_affaire",
            "index": 1,
            "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
          },
          "version_no": 1,
          "version_precedente_attendue": {
            "registre": "documents_affaire",
            "index": 2,
            "ligne_id": "435076b237016d07cc30f2f707e0d0017e34dd6853d3d4127d2813cc450bccab"
          },
          "activation_attendue": {
            "registre": "documents_affaire",
            "index": 1,
            "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
          }
        }
      ]
    },
    "detail": {
      "version_schema": 1,
      "affaire_id": "LEAD-DOCUMENT-FICTIF",
      "document_ref": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "version_source": {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec"
      },
      "statut": "RETIREE",
      "titre": "Note FICTIVE",
      "methode": "utf8-exact-v1",
      "source_sha256": "64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343",
      "taille_points": 33,
      "taille_octets": 37,
      "auteur": {
        "personne": "admin_fictif",
        "role": "admin",
        "source": "appareil"
      },
      "horodatage": "2026-10-10T03:47:55+00:00",
      "activation_ref": {
        "registre": "documents_affaire",
        "index": 1,
        "ligne_id": "778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900"
      }
    }
  }
} as const;
const session: SessionEnvoi = { personne: "admin_fictif", appareilId: "device_fictif", jeton: "token_fictif", urlBase: "https://fictif.local" };
const heure = () => ({ maintenant: new Date("2026-10-10T01:00:00Z"), decalageMinutesUTC: -240 });
const attente = <T,>() => { let resolve!: (v:T)=>void; const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve}; };
function harness() {
 let epoch=0, current:SessionEnvoi|null=session, online=true, counter=0;
 const base=new DepotOutboxMemoire();
 const deps={
  capturerSession:()=>{const e=epoch,s=current;return{session:s,courante:()=>s!==null&&current!==null&&e===epoch};},
  enLigne:()=>online, genererId:jest.fn(()=>`11111111-1111-4111-8111-${String(++counter).padStart(12,"0")}`), horloge:heure,
  obtenirDepot:jest.fn(async()=>base), vidanger:jest.fn(async()=>null),
  chargerIndex:jest.fn(async()=>({source:"serveur" as const,valeur:FIXTURES.deposee.index,misAJourLe:"2026-10-10T01:00:00Z"})),
  chargerVersion:jest.fn(async()=>({source:"serveur" as const,valeur:FIXTURES.deposee.detail,misAJourLe:"2026-10-10T01:00:00Z"})),
 };
 const c=creerControleDocumentsAffaireM10(deps);c.actualiserConnectivite(true);
 return{c,deps,base,revoke:()=>{epoch++;},ABA:()=>{epoch++;current={...session};},renouveler:()=>{epoch++;current={...session,jeton:"nouveau_token_fictif"};},autrePersonne:()=>{epoch++;current={...session,personne:"autre_admin"};},offline:()=>{online=false;c.actualiserConnectivite(false);},reconnect:()=>{online=true;c.actualiserConnectivite(true);}};
}
async function ouvert(h:ReturnType<typeof harness>) {await h.c.ouvrirAffaire(FIXTURES.deposee.index.affaire_id);h.c.modifierBrouillon("Titre exact","corps é\r\n😀");}
test("la page serveur ne génère aucune mutation ni stockage documentaire",async()=>{const h=harness();await ouvert(h);expect(h.c.etat().page?.source).toBe("serveur");expect(h.deps.genererId).not.toHaveBeenCalled();expect(await h.base.lister()).toEqual([]);});
test("hors ligne : pages et détail fermés, brouillon RAM conservé sans dépôt",async()=>{const h=harness();await ouvert(h);h.offline();expect(h.c.etat().page).toBeNull();expect(h.c.etat().brouillon.corps).toBe("corps é\r\n😀");expect(await h.c.soumettre("deposer")).toMatchObject({ok:false});expect(await h.base.lister()).toEqual([]);});
test("rafraîchissement courant ne détruit pas le brouillon",async()=>{const h=harness();await ouvert(h);await h.c.rafraichir();expect(h.c.etat().brouillon.corps).toBe("corps é\r\n😀");});
test("réponse de page tardive après révocation fermée",async()=>{const h=harness(),wait=attente<any>();h.deps.chargerIndex.mockImplementationOnce(()=>wait.promise);const pending=h.c.ouvrirAffaire(FIXTURES.deposee.index.affaire_id);await Promise.resolve();await Promise.resolve();h.revoke();wait.resolve({source:"serveur",valeur:FIXTURES.deposee.index,misAJourLe:"x"});await pending;expect(h.c.etat().page).toBeNull();expect(h.c.etat().brouillon.corps).toBe("");});
test("ABA même identité ne ressuscite pas une réponse",async()=>{const h=harness(),wait=attente<any>();h.deps.chargerIndex.mockImplementationOnce(()=>wait.promise);const pending=h.c.ouvrirAffaire(FIXTURES.deposee.index.affaire_id);await Promise.resolve();await Promise.resolve();h.ABA();wait.resolve({source:"serveur",valeur:FIXTURES.deposee.index,misAJourLe:"x"});await pending;expect(h.c.etat().page).toBeNull();});
test("perte de focus ferme les lectures sans perdre le brouillon RAM",async()=>{const h=harness();await ouvert(h);h.c.invaliderLectures();expect(h.c.etat().page).toBeNull();expect(h.c.etat().brouillon.titre).toBe("Titre exact");});
test("double pression : une seule intention créée avant premier await",async()=>{const h=harness();await ouvert(h);const wait=attente<any>();h.deps.obtenirDepot.mockImplementationOnce(()=>wait.promise);const first=h.c.soumettre("deposer"),second=h.c.soumettre("deposer");expect(h.deps.genererId).toHaveBeenCalledTimes(1);expect(await second).toMatchObject({ok:false});wait.resolve(h.base);await first;expect(await h.base.lister()).toHaveLength(1);});
test("intention inconnue reste même UUID et bloque toute activation",async()=>{const h=harness();await ouvert(h);await h.c.soumettre("deposer");const [one]=await h.base.lister();expect(one.statut).toBe("en_attente");expect(h.c.etat().intentionId).toBe(one.id);await h.c.soumettre("activer");expect(h.deps.genererId).toHaveBeenCalledTimes(1);await h.c.reprendre();expect(await h.base.lister()).toHaveLength(1);expect(h.deps.genererId).toHaveBeenCalledTimes(1);});
test("insertion ayant écrit puis levé : reprise récupère le même objet et UUID",async()=>{const h=harness();await ouvert(h);const insert=h.base.inserer.bind(h.base);jest.spyOn(h.base,"inserer").mockImplementationOnce(async m=>{await insert(m);throw new Error("stockage inconnu");});await h.c.soumettre("deposer");await h.c.reprendre();expect(await h.base.lister()).toHaveLength(1);expect(h.deps.genererId).toHaveBeenCalledTimes(1);});
test("intention dépose bytes originaux ; aucune activation automatique",async()=>{const h=harness();await ouvert(h);await h.c.soumettre("deposer");const [one]=await h.base.lister();expect(one.type).toBe("document_m10_depot");expect(argumentsRpcDocumentM10(one)).toMatchObject({corps:"corps é\r\n😀",document_ref:null,version_precedente:null,confidentialite:"INTERNAL"});});
test("page de cache refusée pour les gestes",async()=>{const h=harness();h.deps.chargerIndex.mockResolvedValueOnce({source:"cache",valeur:FIXTURES.deposee.index,misAJourLe:"x"}as any);await ouvert(h);expect(h.c.etat().page?.source).not.toBe("cache");expect(await h.c.soumettre("deposer")).toMatchObject({ok:false});expect(h.deps.genererId).not.toHaveBeenCalled();});
test("retrait affiché ferme corps et gestes de toute version",async()=>{const h=harness();h.deps.chargerIndex.mockResolvedValueOnce({source:"serveur",valeur:FIXTURES.retiree.index,misAJourLe:"x"}as any);await h.c.ouvrirAffaire(FIXTURES.retiree.index.affaire_id);await h.c.selectionner(FIXTURES.retiree.index.versions[0]);expect(h.deps.chargerVersion).not.toHaveBeenCalled();expect(await h.c.soumettre("activer")).toMatchObject({ok:false});expect(h.c.etat().detail).toBeNull();});
test("intention en échec permanent bloque la série de cette affaire",async()=>{const h=harness();const m=creerMutationDocumentM10("deposer",{affaire_id:FIXTURES.deposee.index.affaire_id,document_ref:null,version_precedente:null,titre:"ancien",corps:"ancien",confidentialite:"INTERNAL"},()=>"22222222-2222-4222-8222-222222222222",heure(),session);await h.base.inserer({...m,statut:"echec_permanent"});await ouvert(h);expect(await h.c.soumettre("deposer")).toMatchObject({ok:false});expect(h.deps.genererId).not.toHaveBeenCalled();});
test("confirmation envoyée sans ACK vérifiable reste bloquée",async()=>{const h=harness();const m=creerMutationDocumentM10("deposer",{affaire_id:FIXTURES.deposee.index.affaire_id,document_ref:null,version_precedente:null,titre:"ancien",corps:"ancien",confidentialite:"INTERNAL"},()=>"22222222-2222-4222-8222-222222222222",heure(),session);await h.base.inserer({...m,statut:"envoyee",resumeAccepte:{inventee:true}});await ouvert(h);expect(await h.c.soumettre("deposer")).toMatchObject({ok:false});});
test("ligne concurrente ajoutée après la lecture : aucun nouvel enregistrement ni vidange",async()=>{const h=harness();await ouvert(h);const m=creerMutationDocumentM10("deposer",{affaire_id:FIXTURES.deposee.index.affaire_id,document_ref:null,version_precedente:null,titre:"autre",corps:"autre",confidentialite:"INTERNAL"},()=>"22222222-2222-4222-8222-222222222222",heure(),session);await h.base.inserer(m);await h.c.soumettre("deposer");expect(await h.base.lister()).toHaveLength(1);expect(h.deps.vidanger).not.toHaveBeenCalled();});
test("la reprise verrouille avant son premier await même après remontage",async()=>{const h=harness();const m=creerMutationDocumentM10("deposer",{affaire_id:FIXTURES.deposee.index.affaire_id,document_ref:null,version_precedente:null,titre:"ancien",corps:"ancien",confidentialite:"INTERNAL"},()=>"22222222-2222-4222-8222-222222222222",heure(),session);await h.base.inserer(m);await ouvert(h);const wait=attente<any>();h.deps.obtenirDepot.mockImplementationOnce(()=>wait.promise);const first=h.c.reprendre();const second=h.c.reprendre();expect(await second).toMatchObject({ok:false,code:"action_indisponible"});wait.resolve(h.base);await first;});
test("brouillon d'une nouvelle version ne devient pas un nouveau document après perte réseau",async()=>{const h=harness();await ouvert(h);const ligne=FIXTURES.deposee.index.versions[0];await h.c.selectionner(ligne);h.c.modifierBrouillon("nouvelle version","version suivante");h.offline();h.reconnect();await h.c.rafraichir();expect(h.c.disponible("deposer")).toBe(false);expect(h.c.etat().brouillon.corps).toBe("version suivante");});
test("changer d'affaire ne masque pas l'intention encore incertaine",async()=>{const h=harness();await ouvert(h);await h.c.soumettre("deposer");const original=h.c.etat();await h.c.ouvrirAffaire("AUTRE-AFFAIRE");expect(h.c.etat().affaireId).toBe(original.affaireId);expect(h.c.etat().intentionId).toBe(original.intentionId);});
test("remontage hors ligne relit la file durable sans RPC ni nouveau UUID",async()=>{const h=harness();const m=creerMutationDocumentM10("deposer",{affaire_id:FIXTURES.deposee.index.affaire_id,document_ref:null,version_precedente:null,titre:"ancien",corps:"ancien",confidentialite:"INTERNAL"},()=>"22222222-2222-4222-8222-222222222222",heure(),session);await h.base.inserer(m);h.offline();await h.c.ouvrirAffaire(FIXTURES.deposee.index.affaire_id);expect(h.c.etat().intentions).toEqual([{id:m.id,statut:"en_attente"}]);expect(h.deps.chargerIndex).not.toHaveBeenCalled();expect(h.deps.genererId).not.toHaveBeenCalled();});
test("une file désormais illisible ne garde pas un ancien statut affiché",async()=>{const h=harness();const m=creerMutationDocumentM10("deposer",{affaire_id:FIXTURES.deposee.index.affaire_id,document_ref:null,version_precedente:null,titre:"ancien",corps:"ancien",confidentialite:"INTERNAL"},()=>"22222222-2222-4222-8222-222222222222",heure(),session);await h.base.inserer(m);await ouvert(h);expect(h.c.etat().intentions).toHaveLength(1);jest.spyOn(h.base,"lister").mockRejectedValueOnce(new Error("SQLite illisible"));await h.c.rafraichir();expect(h.c.etat().intentions).toEqual([]);expect(h.c.disponible("deposer")).toBe(false);});
test("nouveau jeton même destination : affaire et intention UNKNOWN réapparaissent sans nouvel UUID",async()=>{const h=harness();await ouvert(h);await h.c.soumettre("deposer");const [original]=await h.base.lister();h.renouveler();expect(h.c.etat().affaireId).toBeNull();await h.c.ouvrirAffaire(FIXTURES.deposee.index.affaire_id);expect(h.c.etat().affaireId).toBe(original.payload.commande && FIXTURES.deposee.index.affaire_id);expect(h.c.etat().intentionId).toBe(original.id);await h.c.reprendre();expect(await h.base.lister()).toHaveLength(1);expect(h.deps.genererId).toHaveBeenCalledTimes(1);});
test("nouvelle personne ne retrouve ni corps ni UUID d'une autre intention",async()=>{const h=harness();await ouvert(h);await h.c.soumettre("deposer");h.autrePersonne();h.c.etat();await h.c.ouvrirAffaire(FIXTURES.deposee.index.affaire_id);expect(h.c.etat().affaireId).toBeNull();expect(h.c.etat().intentionId).toBeNull();expect(h.c.etat().brouillon.corps).toBe("");const count=h.deps.vidanger.mock.calls.length;await h.c.reprendre();expect(h.deps.vidanger).toHaveBeenCalledTimes(count);});

// Nouveaux vecteurs RAM : corps et métadonnées dérivés, aucune capture SQL alléguée.
function lectureCoherenteRAM(affaireId = FIXTURES.deposee.index.affaire_id as string) {
 const page = JSON.parse(JSON.stringify(FIXTURES.deposee.index));
 const detail = JSON.parse(JSON.stringify(FIXTURES.deposee.detail));
 detail.affaire_id = affaireId; page.affaire_id = affaireId;
 detail.corps = "Texte FICTIF é😀\r\n";
 detail.source_sha256 = bytesToHex(sha256(utf8ToBytes(detail.corps)));
 detail.taille_points = [...detail.corps].length; detail.taille_octets = utf8ToBytes(detail.corps).length;
 const { corps: _corps, ...metadata } = detail;
 Object.assign(page.versions[0], JSON.parse(JSON.stringify(metadata)));
 return { page, detail };
}
function verifierFramesRAM(page: any, detail: any) {
 expect(lireIndexDocumentsAffaireM10({ok:true,resultat:{accepte:true,resultat:page}},
  {affaire_id:page.affaire_id,decalage:0,limite:1}).ok).toBe(true);
 expect(lireVersionDocumentAffaireM10({ok:true,resultat:{accepte:true,resultat:detail}},
  {affaire_id:detail.affaire_id,document_ref:detail.document_ref,version_source:detail.version_source}).ok).toBe(true);
}
test.each(["titre", "empreinte", "taille_points", "taille_octets", "auteur", "horodatage"])(
 "mêmes références : métadonnée immuable contradictoire %s fermée", async champ => {
  const h=harness(), {page,detail}=lectureCoherenteRAM();
  if(champ==="titre") detail.titre="Autre titre FICTIF";
  if(champ==="empreinte") {detail.corps="Autre corps FICTIF";detail.source_sha256=bytesToHex(sha256(utf8ToBytes(detail.corps)));
   detail.taille_points=[...detail.corps].length;detail.taille_octets=utf8ToBytes(detail.corps).length;}
  if(champ==="taille_points") {page.versions[0].taille_points++;page.versions[0].taille_octets=page.versions[0].taille_points*4;}
  if(champ==="taille_octets") page.versions[0].taille_octets++;
  if(champ==="auteur") detail.auteur.personne="autre_admin_fictif";
  if(champ==="horodatage") detail.horodatage="2026-10-10T04:00:00.123456+00:00";
  verifierFramesRAM(page,detail); // Chaque trame seule est valide ; leur relation ne l'est pas.
  h.deps.chargerIndex.mockResolvedValueOnce({source:"serveur",valeur:page} as any);
  h.deps.chargerVersion.mockResolvedValueOnce({source:"serveur",valeur:detail} as any);
  await h.c.ouvrirAffaire(page.affaire_id);await h.c.selectionner(page.versions[0]);
  expect(h.c.etat().detail?.source).toBe("aucune");expect(h.c.etat().detail).not.toHaveProperty("valeur");
  expect(h.deps.genererId).not.toHaveBeenCalled();expect(await h.base.lister()).toEqual([]);
 });
test("statut et activation peuvent changer entre index et détail courants",async()=>{
 const h=harness(),{page,detail}=lectureCoherenteRAM();detail.statut="COURANTE";
 detail.activation_ref={registre:"documents_affaire",index:1,ligne_id:"2".repeat(64)};
 verifierFramesRAM(page,detail);
 h.deps.chargerIndex.mockResolvedValueOnce({source:"serveur",valeur:page} as any);
 h.deps.chargerVersion.mockResolvedValueOnce({source:"serveur",valeur:detail} as any);
 await h.c.ouvrirAffaire(page.affaire_id);await h.c.selectionner(page.versions[0]);
 expect(h.c.etat().detail).toMatchObject({source:"serveur",valeur:{statut:"COURANTE",corps:detail.corps}});
});
test("autre admin lit une autre affaire sans exposer ni remplacer l'intention retenue",async()=>{
 const h=harness();await ouvert(h);await h.c.soumettre("deposer");const [original]=await h.base.lister();
 const envois=h.deps.vidanger.mock.calls.length;h.autrePersonne();
 const {page,detail}=lectureCoherenteRAM("AUTRE-AFFAIRE");verifierFramesRAM(page,detail);
 h.deps.chargerIndex.mockResolvedValueOnce({source:"serveur",valeur:page} as any);
 h.deps.chargerVersion.mockResolvedValueOnce({source:"serveur",valeur:detail} as any);
 await h.c.ouvrirAffaire("AUTRE-AFFAIRE");expect(h.c.etat().affaireId).toBe("AUTRE-AFFAIRE");
 await h.c.selectionner(page.versions[0]);expect(h.c.etat().detail).toMatchObject({source:"serveur",valeur:{corps:detail.corps}});
 expect(h.c.etat().intentionId).toBeNull();expect(h.c.etat().intentions).toEqual([]);expect(h.c.etat().brouillon.corps).toBe("");
 for(const op of ["deposer","activer","retirer"] as const) expect(await h.c.soumettre(op)).toMatchObject({ok:false});
 await h.c.reprendre();expect(h.deps.vidanger).toHaveBeenCalledTimes(envois);expect(h.deps.genererId).toHaveBeenCalledTimes(1);
 expect(await h.base.lister()).toEqual([original]);
 h.renouveler();await h.c.ouvrirAffaire(FIXTURES.deposee.index.affaire_id);expect(h.c.etat().intentionId).toBe(original.id);
 await h.c.reprendre();expect(await h.base.lister()).toHaveLength(1);expect(h.deps.genererId).toHaveBeenCalledTimes(1);
});
test("reprise après reset sans affaire affichée vérifie la série originale avant insertion",async()=>{
 const h=harness();await ouvert(h);h.deps.obtenirDepot.mockRejectedValueOnce(new Error("dépôt temporairement illisible"));
 await h.c.soumettre("deposer");expect(await h.base.lister()).toEqual([]);
 const bloqueur=creerMutationDocumentM10("deposer",{affaire_id:FIXTURES.deposee.index.affaire_id,document_ref:null,
  version_precedente:null,titre:"Autre FICTIF",corps:"Autre FICTIF",confidentialite:"INTERNAL"},
  ()=>"22222222-2222-4222-8222-222222222222",heure(),session);
 await h.base.inserer(bloqueur);const envois=h.deps.vidanger.mock.calls.length;
 h.renouveler();expect(h.c.etat().affaireId).toBeNull();await h.c.reprendre();
 expect(await h.base.lister()).toHaveLength(1);expect(h.deps.vidanger).toHaveBeenCalledTimes(envois);
 expect(h.deps.genererId).toHaveBeenCalledTimes(1);
});
