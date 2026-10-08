/** Captures HTTP MCP/SQLite exactes et fictives, extraites de qualification/m7-contract-fixtures-r2.json.
 * La file reste volatile ; aucun Core natif, téléphone, envoi ou publication n’est prouvé ici. */
export const FIXTURES_LECTURES_ADMIN_M7 = {
  "fictif": true,
  "source": "HTTP MCP réel sur SQLite migrée ; porte Core rejouée en Python ; aucun téléphone/Core natif",
  "capture_sha256": "3d40a740721d23702808269cd1a2bfb80cafd72a2c52afb799c7451e44f8f9ec",
  "head_capture": "47ae120066c1bbe4fa6c97c9b885703525fd0ab0",
  "sources_sha256": {
    "departments/m07-marketing/src/m7_marketing/outils.py": "b5608010f51a0c05a3774d75f1971da6b0ac408ac3b26258c60f570b50fc8cf1",
    "departments/m07-marketing/src/m7_marketing/usine/service.py": "0386e12ab0bf8de06ec3d97598c59d9adb872e2b03f360db1ec7cce98bbc161a",
    "tests/e2e/test_marketing_admin_appareil.py": "952814cb662646aa50511cf09a5731f11f6fb0d05e793f7309816a3cd8fd43bc",
    "tests/fixtures/harnais_e2e.py": "b8d501122b4de8faa4478b787822606cb2eb610b3f6888cf4eb08d479cd0e978"
  },
  "captures": {
    "file_propose": {
      "outil": "m7_lister_file_approbation",
      "args": {
        "statut": "PROPOSE"
      },
      "enveloppe": {
        "ok": true,
        "resultat": [
          {
            "id": "e3385511-8f42-5495-ab8b-87598cdc11e6",
            "version": "1.0.0",
            "brand_ref": "2c987a2d88c41c582c56ac6ce823aeaa1880649ab74a027fa6cd4bc170ace469",
            "seo_knowledge_ref": "857df716db9f90d1547d705d291274f8941bec409ea6300da4727b584967da8b",
            "surface": "google_aio",
            "pillar": "social",
            "type": "post_social",
            "title": "Gouttières et Revêtements Synergy (fictif) - Gouttières à Repentigny (fictif)",
            "body": "Rénovation extérieure au Québec, sans surprise\nPréparation de travaux fictifs.",
            "tactics_applied": [
              {
                "tactique": "Crawlabilité des bots IA autorisée",
                "statut": "candidat_a_verifier",
                "source": "D-013 / position Google AIO"
              },
              {
                "tactique": "Rendu côté serveur",
                "statut": "valide",
                "source": "D-013 / position Google AIO"
              },
              {
                "tactique": "Requêtes fan-out",
                "statut": "valide",
                "source": "D-013 / position Google AIO"
              },
              {
                "tactique": "Fraîcheur et autorité du contenu",
                "statut": "valide",
                "source": "D-013 / position Google AIO"
              }
            ],
            "timestamp": "2026-09-15T07:00:00-04:00",
            "approval_status": "PROPOSE",
            "approver": "",
            "approval_timestamp": "",
            "brand_revision": 1,
            "proposer": "agent",
            "propose_timestamp": "2026-10-07T22:42:11.231014+00:00"
          }
        ]
      }
    },
    "avis": {
      "outil": "m7_lister_demandes_avis",
      "args": {
        "limite": 8
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "total": 1,
          "demandes": [
            {
              "id": "2f52398a-f9f0-590d-8a5d-abb837ae86d2",
              "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
              "nature_travaux": "renovation totale",
              "ville": null,
              "texte": "Bonjour,\n\nMerci d'avoir fait confiance à notre équipe pour vos travaux (renovation totale). Si vous le souhaitez, vous pouvez partager un avis honnête sur votre expérience. Tous les commentaires nous aident à nous améliorer et aident les autres clients à faire un choix éclairé.\n\nCordialement,\nL'équipe",
              "approval_status": "PROPOSE",
              "avertissements": [],
              "consentement": {
                "recueilli_par": "etienne",
                "recueilli_le": "2026-09-15T15:05:00+00:00",
                "version_texte": "consentement-client-fr-CA-v1-fictif"
              }
            }
          ],
          "reste": 0
        }
      }
    },
    "identite_revoquee_0": {
      "outil": "m7_lister_file_approbation",
      "args": {},
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "detail": "lecture marketing réservée à une personne active portant le rôle admin confirmé en base"
          }
        }
      }
    },
    "identite_revoquee_1": {
      "outil": "m7_lister_demandes_avis",
      "args": {},
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "detail": "lecture marketing réservée à une personne active portant le rôle admin confirmé en base"
          }
        }
      }
    }
  }
} as const;
