/* Reponses fictives natives uniquement ; aucun header, credential, config ou base inclus. */
export const FIXTURES_CORE_M1 = {
  "fictif": true,
  "provenance": {
    "proof_sha256": "72d80c090e2d17c683414ad07209619ee96b8dc7a9b7873d3c67f58d8bfb8897",
    "public_manifest_sha256": "c8c6dbf157e487015dd3e18386ec57b79e58e7fdced266cd954c4824635a89eb",
    "source_sha256": {
      "departments/m01-front-office/src/m1_front_office/outils.py": "310c27edf299042652bb3dbda88e957e7839f007d6e6064cf52dd08aeded1402",
      "departments/m01-front-office/src/m1_front_office/verdicts.py": "21a0b506833c0f84fc400cac1b0abca498cd3d0dc5725b4c5c972550e8d9acf0",
      "departments/m01-front-office/tests/test_garde_lectures_admin.py": "9740ce37eb49cc33693330e906abe7b8f3b9fa4400e95097218d39e61c199fdd",
      "tests/e2e/test_transferts_admin_appareil.py": "a249312541fc3fe5d069eb66a0669f991891a286c2b5e2851ce639490a18b02d"
    },
    "core_tree": "f9de21a913ee0e9a41d1d67825fc06ea9d9ba80c",
    "candidate_parent": "21ab50cd259bf46bdeca5039f9a98e74cee74c0c",
    "scope": "Gateway Node reelle -> HTTP MCP -> SQLite, appairage DEVICE opaque. Rejeu Jest des reponses capturees distinct du telephone, Expo SQLite et Hermes. Futur parent M10 non qualifie par cette capture."
  },
  "captures": [
    {
      "phase": "digest_direct",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "2026-09-15"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": "DIGEST - Période de référence : 2026-09-15\n- telephone: signal: 1\n- telephone: transition_phase: 0\n- telephone: lead_emis: 0\n- telephone: chiffrage_emis: 0\n- telephone: alerte: 0\n- courriel: signal: 0\n- courriel: transition_phase: 0\n- courriel: lead_emis: 0\n- courriel: chiffrage_emis: 0\n- courriel: alerte: 0\n- formulaire: signal: 0\n- formulaire: transition_phase: 0\n- formulaire: lead_emis: 0\n- formulaire: chiffrage_emis: 0\n- formulaire: alerte: 0\n- texte: signal: 2\n- texte: transition_phase: 0\n- texte: lead_emis: 0\n- texte: chiffrage_emis: 0\n- texte: alerte: 0\n- conversations ouvertes à suivre : 1\n- conversations sans suivi à l'échéance de leur fenêtre : 1\n- transferts à un humain ouverts : 3\n- dont urgences de sécurité : 1, plaintes : 1\n- appels importés : manque: 1\n- entrées non classées : 1"
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "transfert_couple_plainte",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-e52e03d12ced001a2928"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-e52e03d12ced001a2928",
              "statut": "ouvert",
              "type_transfert": "plainte",
              "niveau": "N4",
              "categories": [
                "insatisfaction",
                "degat"
              ],
              "termes": {
                "insatisfaction": [
                  "déçu"
                ],
                "degat": [
                  "après vos travaux"
                ]
              },
              "declenche_par": "regles",
              "canal": "texte",
              "conversation_id": "sms-ceede41455d35f3235a039d5",
              "ouvert_le": "2026-09-15T07:00:00-04:00",
              "destinataire": null,
              "verdict_destinataire": {
                "code": "REJ-DESTINATAIRE-NON-CONFIGURE",
                "detail": "destinataire à configurer pour le transfert de type 'plainte' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /home/pc6/Documents/Codex/2026-10-05/github-plugin-github-openai-curated-remote-4/work/qualification/m1-native-core-private-r2/backend-fictif/home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550142"
              },
              "lead_id": null,
              "resume": "Plainte. Ouvert par : les règles. Termes reconnus : insatisfaction (« déçu ») ; dégât (« après vos travaux »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "sms:native-plainte-fictive",
                  "recu_le": "2026-09-15T07:00:00-04:00",
                  "texte": "Mes gouttières à Laval fuient encore après vos travaux, je suis très déçu."
                }
              ],
              "messages_couverts_omis": 0,
              "messages_suivants": [],
              "messages_suivants_omis": 0,
              "client_retire_des_messages": false,
              "brouillon_reponse": "Bonjour, merci de nous avoir écrit. Nous comprenons que la situation que vous décrivez vous préoccupe. Votre message a été transmis à une personne de l'équipe.",
              "envoye": false,
              "gabarit": {
                "version": "v1",
                "statut_validation": "proposition"
              }
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "transfert_couple_urgence",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-311fd071bd1f72f3a193"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-311fd071bd1f72f3a193",
              "statut": "ouvert",
              "type_transfert": "urgence",
              "niveau": "N5",
              "categories": [
                "securite"
              ],
              "termes": {
                "securite": [
                  "fil électrique",
                  "fumée"
                ]
              },
              "declenche_par": "regles",
              "canal": "texte",
              "conversation_id": "sms-7f7ff3944812c2b1b4a289eb",
              "ouvert_le": "2026-09-15T07:00:00-04:00",
              "destinataire": null,
              "verdict_destinataire": {
                "code": "REJ-DESTINATAIRE-NON-CONFIGURE",
                "detail": "destinataire à configurer pour le transfert de type 'urgence' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /home/pc6/Documents/Codex/2026-10-05/github-plugin-github-openai-curated-remote-4/work/qualification/m1-native-core-private-r2/backend-fictif/home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550177"
              },
              "lead_id": null,
              "resume": "Urgence de sécurité. Ouvert par : les règles. Termes reconnus : sécurité (« fil électrique », « fumée »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "sms:native-urgence-fictive",
                  "recu_le": "2026-09-15T07:00:00-04:00",
                  "texte": "Il y a de la fumée qui sort du soffite et un fil électrique pend près de la porte."
                }
              ],
              "messages_couverts_omis": 0,
              "messages_suivants": [],
              "messages_suivants_omis": 0,
              "client_retire_des_messages": false,
              "brouillon_reponse": "Bonjour, merci de votre message. Nous l'avons signalé à une personne de l'équipe.",
              "envoye": false,
              "gabarit": {
                "version": "v1",
                "statut_validation": "proposition"
              }
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "transfert_couple_rappel",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-6273e44041ce691dfbc1"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-6273e44041ce691dfbc1",
              "statut": "ouvert",
              "type_transfert": "ventes",
              "niveau": "N3",
              "categories": [],
              "termes": {},
              "declenche_par": "regles",
              "canal": "telephone",
              "conversation_id": "sms-e5d047434026828f9eea3fc6",
              "ouvert_le": "2026-09-15T07:00:00-04:00",
              "destinataire": null,
              "verdict_destinataire": {
                "code": "REJ-DESTINATAIRE-NON-CONFIGURE",
                "detail": "destinataire à configurer pour le transfert de type 'ventes' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /home/pc6/Documents/Codex/2026-10-05/github-plugin-github-openai-curated-remote-4/work/qualification/m1-native-core-private-r2/backend-fictif/home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550188"
              },
              "lead_id": null,
              "resume": "Transfert aux ventes. Ouvert par : les règles. Canal : appel_manuel. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Contact : aucun connu. Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "appel-manuel:Journal PBX FICTIF:native-appel-event-fictif",
                  "recu_le": "2026-09-15T07:00:00-04:00",
                  "texte": "Appel manqué, rappel demandé."
                }
              ],
              "messages_couverts_omis": 0,
              "messages_suivants": [],
              "messages_suivants_omis": 0,
              "suivi_rappel": {
                "snapshot_suivi": "e803cc49e4a7f654a1644c26dc409193ac03b69f835045a68cbec5664f9a38dd",
                "responsable": null,
                "role": null,
                "pris_en_charge_le": null,
                "tentatives_sans_contact": 0,
                "derniere_tentative_le": null,
                "prochaine_tentative_le": null
              },
              "client_retire_des_messages": false
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "date_invalide_2026-02-30",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "2026-02-30"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-DIGEST-DATE-INVALIDE",
              "statut": "",
              "detail": "date_reference doit être une date calendaire YYYY-MM-DD"
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "date_invalide_20260915",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "20260915"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-DIGEST-DATE-INVALIDE",
              "statut": "",
              "detail": "date_reference doit être une date calendaire YYYY-MM-DD"
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "transfert_inconnu",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-00000000000000000000"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-TRANSFERT-INCONNU",
              "statut": "",
              "detail": "aucun transfert 'tr-00000000000000000000' au registre"
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "schema_source_console_refuse",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "2026-09-15",
          "source": "console"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": false,
          "erreur": "arguments_invalides",
          "details": [
            "paramètre inconnu : source"
          ]
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "profil_employee_m1_produire_digest",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "2026-09-15"
        }
      },
      "role": "employee",
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_produire_digest\" (tool_out_of_scope)."
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "profil_employee_m1_lire_transfert",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-e52e03d12ced001a2928"
        }
      },
      "role": "employee",
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_lire_transfert\" (tool_out_of_scope)."
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "profil_seller_m1_produire_digest",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "2026-09-15"
        }
      },
      "role": "seller",
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_produire_digest\" (tool_out_of_scope)."
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "profil_seller_m1_lire_transfert",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-e52e03d12ced001a2928"
        }
      },
      "role": "seller",
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_lire_transfert\" (tool_out_of_scope)."
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "body_device_id_usurpe",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-e52e03d12ced001a2928"
        },
        "deviceId": "9ced053cc668f3a68b1c9f8825449b1588eba23daca8d4d9d917bcfdcfdfeee0"
      },
      "role": "admin",
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "Request body deviceId does not match the authenticated device."
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "relecture_apres_backend_reboot",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-e52e03d12ced001a2928"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-e52e03d12ced001a2928",
              "statut": "ouvert",
              "type_transfert": "plainte",
              "niveau": "N4",
              "categories": [
                "insatisfaction",
                "degat"
              ],
              "termes": {
                "insatisfaction": [
                  "déçu"
                ],
                "degat": [
                  "après vos travaux"
                ]
              },
              "declenche_par": "regles",
              "canal": "texte",
              "conversation_id": "sms-ceede41455d35f3235a039d5",
              "ouvert_le": "2026-09-15T07:00:00-04:00",
              "destinataire": null,
              "verdict_destinataire": {
                "code": "REJ-DESTINATAIRE-NON-CONFIGURE",
                "detail": "destinataire à configurer pour le transfert de type 'plainte' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /home/pc6/Documents/Codex/2026-10-05/github-plugin-github-openai-curated-remote-4/work/qualification/m1-native-core-private-r2/backend-fictif/home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550142"
              },
              "lead_id": null,
              "resume": "Plainte. Ouvert par : les règles. Termes reconnus : insatisfaction (« déçu ») ; dégât (« après vos travaux »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "sms:native-plainte-fictive",
                  "recu_le": "2026-09-15T07:00:00-04:00",
                  "texte": "Mes gouttières à Laval fuient encore après vos travaux, je suis très déçu."
                }
              ],
              "messages_couverts_omis": 0,
              "messages_suivants": [],
              "messages_suivants_omis": 0,
              "client_retire_des_messages": false,
              "brouillon_reponse": "Bonjour, merci de nous avoir écrit. Nous comprenons que la situation que vous décrivez vous préoccupe. Votre message a été transmis à une personne de l'équipe.",
              "envoye": false,
              "gabarit": {
                "version": "v1",
                "statut_validation": "proposition"
              }
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "role_retire_m1_produire_digest",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "2026-09-15"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
              "statut": "",
              "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "role_retire_m1_lire_transfert",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-e52e03d12ced001a2928"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
              "statut": "",
              "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "inactive_m1_produire_digest",
      "request": {
        "tool": "m1_produire_digest",
        "args": {
          "date_reference": "2026-09-15"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
              "statut": "",
              "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    },
    {
      "phase": "inactive_m1_lire_transfert",
      "request": {
        "tool": "m1_lire_transfert",
        "args": {
          "transfert_id": "tr-e52e03d12ced001a2928"
        }
      },
      "role": "admin",
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
              "statut": "",
              "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
            }
          }
        }
      },
      "all_tables_unchanged_native": true
    }
  ]
} as const;
