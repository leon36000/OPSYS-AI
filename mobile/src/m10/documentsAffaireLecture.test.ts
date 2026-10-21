import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import * as lectureDocumentaire from "./documentsAffaireLecture";
import { creerMutationDocumentM10, argumentsRpcDocumentM10 } from "./documentsAffaireOutbox";

type Lu = { ok: boolean; value?: any; code?: string };
type Codec = {
  lireIndexDocumentsAffaireM10: (v: unknown, args: unknown) => Lu;
  lireVersionDocumentAffaireM10: (v: unknown, args: unknown) => Lu;
  construireArgumentsIndexDocumentsAffaireM10: (id: unknown, off: unknown, limit: unknown) => unknown;
  construireArgumentsVersionDocumentAffaireM10: (id: unknown, root: unknown, source: unknown) => unknown;
};
function codec(): Codec {
  // Les appels mal typés ci-dessous sont des contre-exemples RAM explicites.
  return lectureDocumentaire as unknown as Codec;
}
// Capture Cap/SQLite fictive réelle, identité injectée : pas HTTP/DEVICE.
// RAW_CAPTURE reproduit exactement le fichier original, sans réécrire les frames.
const RAW_CAPTURE = "{\n  \"fictif\": true,\n  \"captures\": {\n    \"deposee\": {\n      \"detail\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"document_ref\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"version_source\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"statut\": \"DEPOSEE_NON_ACTIVEE\",\n            \"titre\": \"Note FICTIVE\",\n            \"methode\": \"utf8-exact-v1\",\n            \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n            \"taille_points\": 33,\n            \"taille_octets\": 37,\n            \"auteur\": {\n              \"personne\": \"admin_fictif\",\n              \"role\": \"admin\",\n              \"source\": \"appareil\"\n            },\n            \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n            \"activation_ref\": null,\n            \"corps\": \"CANARI_TRANSACTION_FICTIVE_A\u00e9\ud83d\ude00\\r\\nZ\"\n          }\n        }\n      },\n      \"index\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"decalage\": 0,\n            \"limite\": 1,\n            \"total_versions\": 1,\n            \"suivant_decalage\": null,\n            \"versions\": [\n              {\n                \"version_schema\": 1,\n                \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n                \"document_ref\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"version_source\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"statut\": \"DEPOSEE_NON_ACTIVEE\",\n                \"titre\": \"Note FICTIVE\",\n                \"methode\": \"utf8-exact-v1\",\n                \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n                \"taille_points\": 33,\n                \"taille_octets\": 37,\n                \"auteur\": {\n                  \"personne\": \"admin_fictif\",\n                  \"role\": \"admin\",\n                  \"source\": \"appareil\"\n                },\n                \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n                \"activation_ref\": null,\n                \"version_no\": 1,\n                \"version_precedente_attendue\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"activation_attendue\": null\n              }\n            ]\n          }\n        }\n      },\n      \"tables_observees\": 49\n    },\n    \"activee\": {\n      \"detail\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"document_ref\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"version_source\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"statut\": \"COURANTE\",\n            \"titre\": \"Note FICTIVE\",\n            \"methode\": \"utf8-exact-v1\",\n            \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n            \"taille_points\": 33,\n            \"taille_octets\": 37,\n            \"auteur\": {\n              \"personne\": \"admin_fictif\",\n              \"role\": \"admin\",\n              \"source\": \"appareil\"\n            },\n            \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n            \"activation_ref\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 1,\n              \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n            },\n            \"corps\": \"CANARI_TRANSACTION_FICTIVE_A\u00e9\ud83d\ude00\\r\\nZ\"\n          }\n        }\n      },\n      \"index\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"decalage\": 0,\n            \"limite\": 1,\n            \"total_versions\": 1,\n            \"suivant_decalage\": null,\n            \"versions\": [\n              {\n                \"version_schema\": 1,\n                \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n                \"document_ref\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"version_source\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"statut\": \"COURANTE\",\n                \"titre\": \"Note FICTIVE\",\n                \"methode\": \"utf8-exact-v1\",\n                \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n                \"taille_points\": 33,\n                \"taille_octets\": 37,\n                \"auteur\": {\n                  \"personne\": \"admin_fictif\",\n                  \"role\": \"admin\",\n                  \"source\": \"appareil\"\n                },\n                \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n                \"activation_ref\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 1,\n                  \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n                },\n                \"version_no\": 1,\n                \"version_precedente_attendue\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"activation_attendue\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 1,\n                  \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n                }\n              }\n            ]\n          }\n        }\n      },\n      \"tables_observees\": 49\n    },\n    \"seconde_deposee\": {\n      \"detail\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"document_ref\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"version_source\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"statut\": \"COURANTE\",\n            \"titre\": \"Note FICTIVE\",\n            \"methode\": \"utf8-exact-v1\",\n            \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n            \"taille_points\": 33,\n            \"taille_octets\": 37,\n            \"auteur\": {\n              \"personne\": \"admin_fictif\",\n              \"role\": \"admin\",\n              \"source\": \"appareil\"\n            },\n            \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n            \"activation_ref\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 1,\n              \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n            },\n            \"corps\": \"CANARI_TRANSACTION_FICTIVE_A\u00e9\ud83d\ude00\\r\\nZ\"\n          }\n        }\n      },\n      \"index\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"decalage\": 0,\n            \"limite\": 1,\n            \"total_versions\": 2,\n            \"suivant_decalage\": 1,\n            \"versions\": [\n              {\n                \"version_schema\": 1,\n                \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n                \"document_ref\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"version_source\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"statut\": \"COURANTE\",\n                \"titre\": \"Note FICTIVE\",\n                \"methode\": \"utf8-exact-v1\",\n                \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n                \"taille_points\": 33,\n                \"taille_octets\": 37,\n                \"auteur\": {\n                  \"personne\": \"admin_fictif\",\n                  \"role\": \"admin\",\n                  \"source\": \"appareil\"\n                },\n                \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n                \"activation_ref\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 1,\n                  \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n                },\n                \"version_no\": 1,\n                \"version_precedente_attendue\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 2,\n                  \"ligne_id\": \"435076b237016d07cc30f2f707e0d0017e34dd6853d3d4127d2813cc450bccab\"\n                },\n                \"activation_attendue\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 1,\n                  \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n                }\n              }\n            ]\n          }\n        }\n      },\n      \"tables_observees\": 49\n    },\n    \"retiree\": {\n      \"detail\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"document_ref\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"version_source\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 0,\n              \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n            },\n            \"statut\": \"RETIREE\",\n            \"titre\": \"Note FICTIVE\",\n            \"methode\": \"utf8-exact-v1\",\n            \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n            \"taille_points\": 33,\n            \"taille_octets\": 37,\n            \"auteur\": {\n              \"personne\": \"admin_fictif\",\n              \"role\": \"admin\",\n              \"source\": \"appareil\"\n            },\n            \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n            \"activation_ref\": {\n              \"registre\": \"documents_affaire\",\n              \"index\": 1,\n              \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n            }\n          }\n        }\n      },\n      \"index\": {\n        \"ok\": true,\n        \"resultat\": {\n          \"accepte\": true,\n          \"resultat\": {\n            \"version_schema\": 1,\n            \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n            \"decalage\": 0,\n            \"limite\": 1,\n            \"total_versions\": 2,\n            \"suivant_decalage\": 1,\n            \"versions\": [\n              {\n                \"version_schema\": 1,\n                \"affaire_id\": \"LEAD-DOCUMENT-FICTIF\",\n                \"document_ref\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"version_source\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 0,\n                  \"ligne_id\": \"28099ef499c64905153c9728c96af65aae9f07d94c2be4d02ec2d259f47852ec\"\n                },\n                \"statut\": \"RETIREE\",\n                \"titre\": \"Note FICTIVE\",\n                \"methode\": \"utf8-exact-v1\",\n                \"source_sha256\": \"64abac222c059d26c5cec960264c65e40222acb90b337756409266922c06a343\",\n                \"taille_points\": 33,\n                \"taille_octets\": 37,\n                \"auteur\": {\n                  \"personne\": \"admin_fictif\",\n                  \"role\": \"admin\",\n                  \"source\": \"appareil\"\n                },\n                \"horodatage\": \"2026-10-10T03:47:55+00:00\",\n                \"activation_ref\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 1,\n                  \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n                },\n                \"version_no\": 1,\n                \"version_precedente_attendue\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 2,\n                  \"ligne_id\": \"435076b237016d07cc30f2f707e0d0017e34dd6853d3d4127d2813cc450bccab\"\n                },\n                \"activation_attendue\": {\n                  \"registre\": \"documents_affaire\",\n                  \"index\": 1,\n                  \"ligne_id\": \"778215a323b42e1ffbb6478b883dd0ee774d0ec838a8b625a9b01757939cd900\"\n                }\n              }\n            ]\n          }\n        }\n      },\n      \"tables_observees\": 49\n    }\n  },\n  \"provenance\": {\n    \"source\": \"Actual Cap/SQLite F17 pytest capture, not RAM pure Source3 nor MCP transport capture\",\n    \"log\": \"lecture-cap-mcp-captures-r1.log\",\n    \"log_sha256\": \"4b90429a99c826e5d822d13d8cd28935b571d6a4e34415dde4506d4587ddc532\",\n    \"source4_files\": {\n      \"src/opsys/capacites.py\": \"4dc3ef91a297910aa85b4716d3aee3126b5a349b21e3747659a9200a26144f4a\",\n      \"src/opsys/serveur_mcp.py\": \"ac74a2f5b96bae1007e2d960540071567f11fbbfa596bf7650648c97a46159b2\",\n      \"tests/test_documents_affaire_lecture_cap_appareil.py\": \"6191af1ecf3e70b8ba4261dfdda28983fbbe41cbdde2e06b4f046010894aa277\",\n      \"tests/test_documents_affaire_lecture_mcp_appareil.py\": \"3fbc3b9b50315352e11b802bc9fad35cc8899d5fc33b7b7e4dfe2de4d0d0dfa9\"\n    },\n    \"sql_identity_injected\": true,\n    \"device_opaque_verified\": false,\n    \"phone_verified\": false\n  }\n}\n";
const CAP_SQL = JSON.parse(RAW_CAPTURE);
const CAPTURE_SHA256 = "1100ad5fb553b43acce4b5edd3be4cbb7047ef77680b95712836c4eb08f80828";
const CIBLE = "LEAD-DOCUMENT-FICTIF";
const COPIE = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const ARGS_INDEX = { affaire_id: CIBLE, decalage: 0, limite: 1 };
const DETAIL = CAP_SQL.captures.deposee.detail.resultat.resultat;
const ARGS_DETAIL = { affaire_id: CIBLE, document_ref: DETAIL.document_ref, version_source: DETAIL.version_source };

test("fixture originale exacte UTF8/SHA, provenance Cap injectée seulement", () => {
  expect(bytesToHex(sha256(utf8ToBytes(RAW_CAPTURE)))).toBe(CAPTURE_SHA256);
  expect(CAP_SQL.fictif).toBe(true);
  expect(CAP_SQL.provenance.device_opaque_verified).toBe(false);
});

test.each(["deposee", "activee", "seconde_deposee", "retiree"])("interop Cap réelle %s index/détail fermés, copies indépendantes", key => {
  const c = codec(), input = CAP_SQL.captures[key];
  const index = c.lireIndexDocumentsAffaireM10(input.index, ARGS_INDEX);
  const body = c.lireVersionDocumentAffaireM10(input.detail, ARGS_DETAIL);
  expect(index).toMatchObject({ ok: true, value: input.index.resultat.resultat });
  expect(body).toMatchObject({ ok: true, value: input.detail.resultat.resultat });
  expect(index.value).not.toBe(input.index.resultat.resultat);
  expect(body.value.document_ref).not.toBe(input.detail.resultat.resultat.document_ref);
  expect(Object.keys(index.value.versions[0])).toHaveLength(16);
  expect(Object.hasOwn(index.value.versions[0], "corps")).toBe(false);
  expect(Object.keys(body.value)).toHaveLength(key === "retiree" ? 13 : 14);
});

test("v2 déposée garde v1 active et CAS courant séparé", () => {
  const parsed = codec().lireIndexDocumentsAffaireM10(CAP_SQL.captures.seconde_deposee.index, ARGS_INDEX);
  expect(parsed.ok).toBe(true);
  const row = parsed.value.versions[0];
  expect(row.statut).toBe("COURANTE");
  expect(row.version_no).toBe(1);
  expect(row.version_precedente_attendue.index).toBeGreaterThan(row.version_source.index);
  expect(row.activation_ref).toEqual(row.activation_attendue);
});

test.each([
  (v: any) => { v.rejoue = false; },
  (v: any) => { v.resultat.resultat.versions[0].corps = "CANARI_RAM_FICTIF"; },
  (v: any) => { v.resultat.resultat.versions[0].confidentialite = "INTERNAL"; },
  (v: any) => { v.resultat.resultat.versions[0].version_no = true; },
  (v: any) => { v.resultat.resultat.versions[0].version_source.index = 512; },
  (v: any) => { v.resultat.resultat.suivant_decalage = 1; },
  (v: any) => { v.resultat.resultat.affaire_id = "AUTRE-FICTIF"; },
  (v: any) => { v.resultat.resultat.versions[0].affaire_id = "AUTRE-FICTIF"; },
  (v: any) => { v.resultat.resultat.versions[0].taille_points = Number.MAX_SAFE_INTEGER + 1; },
])("contre-exemple RAM index malformé : aucune projection reconstruite", modifier => {
  const v = COPIE(CAP_SQL.captures.deposee.index); modifier(v);
  expect(codec().lireIndexDocumentsAffaireM10(v, ARGS_INDEX).ok).toBe(false);
});

test("contradiction RAM COURANTE sans activation dernière est refusée", () => {
  const v = COPIE(CAP_SQL.captures.activee.index);
  v.resultat.resultat.versions[0].activation_attendue = null;
  expect(codec().lireIndexDocumentsAffaireM10(v, ARGS_INDEX).ok).toBe(false);
});

test.each([
  (v: any) => { v.resultat.resultat.corps += "X"; },
  (v: any) => { v.resultat.resultat.source_sha256 = "0".repeat(64); },
  (v: any) => { v.resultat.resultat.taille_octets += 1; },
  (v: any) => { v.resultat.resultat.taille_points += 1; },
  (v: any) => { v.resultat.resultat.corps = "\ud800"; },
  (v: any) => { v.resultat.resultat.version_source.ligne_id = "0".repeat(64); },
  (v: any) => { v.resultat.resultat.horodatage = "2026-02-30T01:00:00Z"; },
])("contre-exemple RAM détail : bytehash/tailles/ref/heure inadmissibles", modifier => {
  const v = COPIE(CAP_SQL.captures.deposee.detail); modifier(v);
  expect(codec().lireVersionDocumentAffaireM10(v, ARGS_DETAIL).ok).toBe(false);
});

test("RETIREE n'admet aucun corps et hors retrait corps obligatoire", () => {
  const c = codec(), removed = COPIE(CAP_SQL.captures.retiree.detail);
  removed.resultat.resultat.corps = "CANARI_RAM_FICTIF";
  expect(c.lireVersionDocumentAffaireM10(removed, ARGS_DETAIL).ok).toBe(false);
  const visible = COPIE(CAP_SQL.captures.deposee.detail); delete visible.resultat.resultat.corps;
  expect(c.lireVersionDocumentAffaireM10(visible, ARGS_DETAIL).ok).toBe(false);
});

test("vecteur RAM Unicode/CRLF/microsecondes exacts, pas NFC ni Date.parse", () => {
  const v = COPIE(CAP_SQL.captures.deposee.detail), s = v.resultat.resultat;
  s.corps = "e\u0301😀\r\nZ"; s.source_sha256 = bytesToHex(sha256(utf8ToBytes(s.corps)));
  s.taille_points = [...s.corps].length; s.taille_octets = utf8ToBytes(s.corps).length;
  s.horodatage = "2026-10-10T04:00:00.123456+00:00";
  const parsed = codec().lireVersionDocumentAffaireM10(v, ARGS_DETAIL);
  expect(parsed.ok).toBe(true); expect(parsed.value.corps).toBe(s.corps);
  expect(parsed.value.horodatage).toBe(s.horodatage);
});

test("RAM corps blanc canonique accepté par writer existant et lu verbatim", () => {
  const corps = "  ";
  const commande = {affaire_id:CIBLE,document_ref:null,version_precedente:null,titre:"Note FICTIVE",corps,confidentialite:"INTERNAL"};
  const intention = creerMutationDocumentM10("deposer",commande,()=>"10000000-0000-4000-8000-000000000001",
    {maintenant:new Date("2026-10-10T04:40:00Z"),decalageMinutesUTC:0},
    {personne:"admin_fictif",appareilId:"device-fictif",urlBase:"https://core.fictif.test"});
  expect(argumentsRpcDocumentM10(intention)).toEqual(commande);
  // Métadonnées modifiées en RAM : ne pas appeler ceci une nouvelle capture Cap/SQL.
  const frame = COPIE(CAP_SQL.captures.deposee.detail), dto = frame.resultat.resultat;
  dto.corps=corps;dto.taille_points=2;dto.taille_octets=2;
  dto.source_sha256="6c179f21e6f62b629055d8ab40f454ed02e48b68563913473b857d3638e23b28";
  expect(bytesToHex(sha256(utf8ToBytes(corps)))).toBe(dto.source_sha256);
  const lu = codec().lireVersionDocumentAffaireM10(frame,ARGS_DETAIL);
  expect(lu.ok).toBe(true);expect(lu.value.corps).toBe(corps);
});

test("JSON getters/prototypes ne sont pas exécutés", () => {
  let calls = 0;
  const v = COPIE(CAP_SQL.captures.deposee.detail);
  Object.defineProperty(v.resultat.resultat, "corps", { enumerable: true, get: () => { calls++; return "CANARI"; } });
  expect(codec().lireVersionDocumentAffaireM10(v, ARGS_DETAIL).ok).toBe(false); expect(calls).toBe(0);
  const fake = Object.create({ ok: true }); fake.resultat = CAP_SQL.captures.deposee.detail.resultat;
  expect(codec().lireVersionDocumentAffaireM10(fake, ARGS_DETAIL).ok).toBe(false);
});

test("builders trois args explicites, bool/unsafe/getter refusés et références copiées", () => {
  const c = codec(); expect(c.construireArgumentsIndexDocumentsAffaireM10(CIBLE, 0, 1)).toEqual(ARGS_INDEX);
  for (const [offset,limit] of [[true,1],[0,true],[65,1],[0,9],[0,0],[Number.MAX_SAFE_INTEGER + 1,1]]) {
    expect(() => c.construireArgumentsIndexDocumentsAffaireM10(CIBLE, offset, limit)).toThrow();
  }
  const root = COPIE(DETAIL.document_ref), source = COPIE(DETAIL.version_source);
  const args: any = c.construireArgumentsVersionDocumentAffaireM10(CIBLE, root, source);
  expect(args).toEqual(ARGS_DETAIL); expect(args.document_ref).not.toBe(root);
  let calls = 0; const getter = { ...root };
  Object.defineProperty(getter, "index", { enumerable: true, get: () => { calls++; return 0; } });
  expect(() => c.construireArgumentsVersionDocumentAffaireM10(CIBLE, getter, source)).toThrow();
  expect(calls).toBe(0);
});

function pageDeuxRAM() {
  // Construction contrefactuelle RAM depuis une capture : aucun nouvel événement SQL allégué.
  const frame = COPIE(CAP_SQL.captures.seconde_deposee.index), dto = frame.resultat.resultat;
  dto.limite = 2; dto.suivant_decalage = null;
  const seconde = COPIE(dto.versions[0]);
  seconde.version_source = COPIE(seconde.version_precedente_attendue);
  seconde.version_no = 2; seconde.statut = "DEPOSEE_NON_ACTIVEE"; seconde.activation_ref = null;
  dto.versions.push(seconde);
  return frame;
}
test("page RAM deux versions ordonnées avec CAS commun, pas d'égalité dépôt/activation inventée", () => {
  const frame = pageDeuxRAM();
  expect(codec().lireIndexDocumentsAffaireM10(frame, { ...ARGS_INDEX, limite: 2 }).ok).toBe(true);
});
test.each(["ordre", "identite_ref", "CAS_document"])("page RAM contradiction %s rejetée", cas => {
  const frame = pageDeuxRAM(), rows = frame.resultat.resultat.versions;
  if (cas === "ordre") rows.reverse();
  if (cas === "identite_ref") rows[1].document_ref.ligne_id = "0".repeat(64);
  if (cas === "CAS_document") rows[1].activation_attendue = null;
  expect(codec().lireIndexDocumentsAffaireM10(frame, { ...ARGS_INDEX, limite: 2 }).ok).toBe(false);
});
