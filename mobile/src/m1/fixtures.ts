/* Captures fictives natives HTTP MCP/SQLite ; provenance et port Core Python décrits dans la donnée. */
export const FIXTURES_M1 = {
  "fictif": true,
  "date": "2026-10-07T21:36:26-04:00",
  "provenance": {
    "scope": "Vrai HTTP MCP/uvicorn + SQLite éphémère, outils M1 canoniques ; porte appareil Core rejouée Python, pas Gateway TypeScript ni téléphone natif.",
    "source_sha256": {
      "departments/m01-front-office/src/m1_front_office/outils.py": "310c27edf299042652bb3dbda88e957e7839f007d6e6064cf52dd08aeded1402",
      "departments/m01-front-office/src/m1_front_office/verdicts.py": "21a0b506833c0f84fc400cac1b0abca498cd3d0dc5725b4c5c972550e8d9acf0",
      "departments/m01-front-office/tests/test_garde_lectures_admin.py": "9740ce37eb49cc33693330e906abe7b8f3b9fa4400e95097218d39e61c199fdd",
      "tests/e2e/test_transferts_admin_appareil.py": "a249312541fc3fe5d069eb66a0669f991891a286c2b5e2851ce639490a18b02d"
    },
    "runtime": "3.12.3 (main, Aug 31 2026, 10:18:26) [GCC 13.3.0]",
    "hash_rule": "SHA256 du corps JSON exact après décodage HTTP, reserialisé UTF8 ensure_ascii=False séparateurs compacts ; pas une empreinte des octets originaux du transport.",
    "no_business_mutation": "Chaque lecture compare toutes les tables META avant/après.",
    "client_limit": "Client non appairable dans ROLES_APPAREIL ; refus testé nativement, pas présenté comme appareil HTTP appairé.",
    "path": "qualification/m1-transferts-native-20261007/m1-transferts-fixtures-r1.json",
    "sha256": "ef67584018818940c90267f3ddadf35dc17aa14c1d0b4fd5ac0c03442689e696"
  },
  "reponses": {
    "digest_vide": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-09-15"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": "Absence d'activité enregistrée pour la période de référence 2026-09-15."
        }
      },
      "enveloppe": {
        "ok": true,
        "resultat": "Absence d'activité enregistrée pour la période de référence 2026-09-15."
      },
      "sha256_corps_json_utf8": "f6c47e6ed23ba47a656bb6da5b1252df3c92ad5d061198c495eb2dc3ccd1a7cc"
    },
    "plainte_ouverte": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-7e02bf257cd5259aec2c"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-7e02bf257cd5259aec2c",
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
                "detail": "destinataire à configurer pour le transfert de type 'plainte' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550142"
              },
              "lead_id": null,
              "resume": "Plainte. Ouvert par : les règles. Termes reconnus : insatisfaction (« déçu ») ; dégât (« après vos travaux »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "sms:plainte-fictive",
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "transfert_id": "tr-7e02bf257cd5259aec2c",
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
              "detail": "destinataire à configurer pour le transfert de type 'plainte' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
            },
            "contact": {
              "telephone": "+15145550142"
            },
            "lead_id": null,
            "resume": "Plainte. Ouvert par : les règles. Termes reconnus : insatisfaction (« déçu ») ; dégât (« après vos travaux »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
            "resume_origine": "code",
            "messages_couverts": [
              {
                "signal_id": "sms:plainte-fictive",
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
      },
      "sha256_corps_json_utf8": "132ed1346635ae03343b13b9801c1f84dc1ea9615d66b880141930c04123bb34"
    },
    "urgence_ouverte": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-484e244add7d80ba3012"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-484e244add7d80ba3012",
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
                "detail": "destinataire à configurer pour le transfert de type 'urgence' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550177"
              },
              "lead_id": null,
              "resume": "Urgence de sécurité. Ouvert par : les règles. Termes reconnus : sécurité (« fil électrique », « fumée »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "sms:urgence-fictive",
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "transfert_id": "tr-484e244add7d80ba3012",
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
              "detail": "destinataire à configurer pour le transfert de type 'urgence' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
            },
            "contact": {
              "telephone": "+15145550177"
            },
            "lead_id": null,
            "resume": "Urgence de sécurité. Ouvert par : les règles. Termes reconnus : sécurité (« fil électrique », « fumée »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
            "resume_origine": "code",
            "messages_couverts": [
              {
                "signal_id": "sms:urgence-fictive",
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
      },
      "sha256_corps_json_utf8": "c5d8bd20e1571be7ce7f27778b8c86921493ad74eb9be55a4166804a8c5650b7"
    },
    "rappel_non_assigne": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-f3cf48d7104012ebd27f"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-f3cf48d7104012ebd27f",
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
                "detail": "destinataire à configurer pour le transfert de type 'ventes' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550188"
              },
              "lead_id": null,
              "resume": "Transfert aux ventes. Ouvert par : les règles. Canal : appel_manuel. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Contact : aucun connu. Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "appel-manuel:Journal PBX FICTIF:appel-event-fictif",
                  "recu_le": "2026-09-15T07:00:00-04:00",
                  "texte": "Appel manqué, rappel demandé."
                }
              ],
              "messages_couverts_omis": 0,
              "messages_suivants": [],
              "messages_suivants_omis": 0,
              "suivi_rappel": {
                "snapshot_suivi": "c60477c4d93332531353982605c6c28880b439f3f33c8fab1142045c075eecf9",
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "transfert_id": "tr-f3cf48d7104012ebd27f",
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
              "detail": "destinataire à configurer pour le transfert de type 'ventes' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
            },
            "contact": {
              "telephone": "+15145550188"
            },
            "lead_id": null,
            "resume": "Transfert aux ventes. Ouvert par : les règles. Canal : appel_manuel. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Contact : aucun connu. Les messages du client se lisent avec `m1_lire_transfert`.",
            "resume_origine": "code",
            "messages_couverts": [
              {
                "signal_id": "appel-manuel:Journal PBX FICTIF:appel-event-fictif",
                "recu_le": "2026-09-15T07:00:00-04:00",
                "texte": "Appel manqué, rappel demandé."
              }
            ],
            "messages_couverts_omis": 0,
            "messages_suivants": [],
            "messages_suivants_omis": 0,
            "suivi_rappel": {
              "snapshot_suivi": "c60477c4d93332531353982605c6c28880b439f3f33c8fab1142045c075eecf9",
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
      },
      "sha256_corps_json_utf8": "bf8eab9d6b3bb3e4eaa6998026a01a0de4cec3c932cf09015e180cb3d25675f0"
    },
    "rappel_assigne": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-f3cf48d7104012ebd27f"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-f3cf48d7104012ebd27f",
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
                "detail": "destinataire à configurer pour le transfert de type 'ventes' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550188"
              },
              "lead_id": null,
              "resume": "Transfert aux ventes. Ouvert par : les règles. Canal : appel_manuel. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Contact : aucun connu. Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "appel-manuel:Journal PBX FICTIF:appel-event-fictif",
                  "recu_le": "2026-09-15T07:00:00-04:00",
                  "texte": "Appel manqué, rappel demandé."
                }
              ],
              "messages_couverts_omis": 0,
              "messages_suivants": [],
              "messages_suivants_omis": 0,
              "suivi_rappel": {
                "snapshot_suivi": "5623f1f163c3f995b92dae90e159477cd41ef073834ef072e13f43b184427e0a",
                "responsable": "nathan",
                "role": "nathan_owner",
                "pris_en_charge_le": "2026-10-08T01:36:24.345259+00:00",
                "tentatives_sans_contact": 0,
                "derniere_tentative_le": null,
                "prochaine_tentative_le": null
              },
              "client_retire_des_messages": false
            }
          }
        }
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "transfert_id": "tr-f3cf48d7104012ebd27f",
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
              "detail": "destinataire à configurer pour le transfert de type 'ventes' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
            },
            "contact": {
              "telephone": "+15145550188"
            },
            "lead_id": null,
            "resume": "Transfert aux ventes. Ouvert par : les règles. Canal : appel_manuel. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Contact : aucun connu. Les messages du client se lisent avec `m1_lire_transfert`.",
            "resume_origine": "code",
            "messages_couverts": [
              {
                "signal_id": "appel-manuel:Journal PBX FICTIF:appel-event-fictif",
                "recu_le": "2026-09-15T07:00:00-04:00",
                "texte": "Appel manqué, rappel demandé."
              }
            ],
            "messages_couverts_omis": 0,
            "messages_suivants": [],
            "messages_suivants_omis": 0,
            "suivi_rappel": {
              "snapshot_suivi": "5623f1f163c3f995b92dae90e159477cd41ef073834ef072e13f43b184427e0a",
              "responsable": "nathan",
              "role": "nathan_owner",
              "pris_en_charge_le": "2026-10-08T01:36:24.345259+00:00",
              "tentatives_sans_contact": 0,
              "derniere_tentative_le": null,
              "prochaine_tentative_le": null
            },
            "client_retire_des_messages": false
          }
        }
      },
      "sha256_corps_json_utf8": "42517e7036198cd3a41a5d3d943b53764114153c4f2bfaeaa96e9971161eca24"
    },
    "transfert_omissions": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-8b65d833252fb9016450"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-8b65d833252fb9016450",
              "statut": "ouvert",
              "type_transfert": "technique",
              "niveau": "N3",
              "categories": [],
              "termes": {},
              "declenche_par": "agent",
              "canal": "texte",
              "conversation_id": "sms-0af1292643012da3a55a89ef",
              "ouvert_le": "2026-09-15T07:05:00-04:00",
              "destinataire": null,
              "verdict_destinataire": {
                "code": "REJ-DESTINATAIRE-NON-CONFIGURE",
                "detail": "destinataire à configurer pour le transfert de type 'technique' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550199"
              },
              "lead_id": null,
              "resume": "Transfert technique. Ouvert par : l'agent. Canal : sms. Messages du client rassemblés : 6, du 2026-09-15T07:00:00-04:00 au 2026-09-15T07:05:00-04:00. Aucun lead n'est ouvert pour cette conversation. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "sms:couvert-fictif-2",
                  "recu_le": "2026-09-15T07:02:00-04:00",
                  "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
                },
                {
                  "signal_id": "sms:couvert-fictif-3",
                  "recu_le": "2026-09-15T07:03:00-04:00",
                  "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
                },
                {
                  "signal_id": "sms:couvert-fictif-4",
                  "recu_le": "2026-09-15T07:04:00-04:00",
                  "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
                },
                {
                  "signal_id": "sms:couvert-fictif-5",
                  "recu_le": "2026-09-15T07:05:00-04:00",
                  "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
                }
              ],
              "messages_couverts_omis": 2,
              "messages_suivants": [
                {
                  "signal_id": "sms:suivant-fictif-2",
                  "recu_le": "2026-09-15T07:12:00-04:00",
                  "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
                },
                {
                  "signal_id": "sms:suivant-fictif-3",
                  "recu_le": "2026-09-15T07:13:00-04:00",
                  "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
                },
                {
                  "signal_id": "sms:suivant-fictif-4",
                  "recu_le": "2026-09-15T07:14:00-04:00",
                  "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
                },
                {
                  "signal_id": "sms:suivant-fictif-5",
                  "recu_le": "2026-09-15T07:15:00-04:00",
                  "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
                }
              ],
              "messages_suivants_omis": 2,
              "client_retire_des_messages": false
            }
          }
        }
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "transfert_id": "tr-8b65d833252fb9016450",
            "statut": "ouvert",
            "type_transfert": "technique",
            "niveau": "N3",
            "categories": [],
            "termes": {},
            "declenche_par": "agent",
            "canal": "texte",
            "conversation_id": "sms-0af1292643012da3a55a89ef",
            "ouvert_le": "2026-09-15T07:05:00-04:00",
            "destinataire": null,
            "verdict_destinataire": {
              "code": "REJ-DESTINATAIRE-NON-CONFIGURE",
              "detail": "destinataire à configurer pour le transfert de type 'technique' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
            },
            "contact": {
              "telephone": "+15145550199"
            },
            "lead_id": null,
            "resume": "Transfert technique. Ouvert par : l'agent. Canal : sms. Messages du client rassemblés : 6, du 2026-09-15T07:00:00-04:00 au 2026-09-15T07:05:00-04:00. Aucun lead n'est ouvert pour cette conversation. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
            "resume_origine": "code",
            "messages_couverts": [
              {
                "signal_id": "sms:couvert-fictif-2",
                "recu_le": "2026-09-15T07:02:00-04:00",
                "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
              },
              {
                "signal_id": "sms:couvert-fictif-3",
                "recu_le": "2026-09-15T07:03:00-04:00",
                "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
              },
              {
                "signal_id": "sms:couvert-fictif-4",
                "recu_le": "2026-09-15T07:04:00-04:00",
                "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
              },
              {
                "signal_id": "sms:couvert-fictif-5",
                "recu_le": "2026-09-15T07:05:00-04:00",
                "texte": "Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour, voici un message factuel supplémentaire pour votre équipe. Bonjour,…"
              }
            ],
            "messages_couverts_omis": 2,
            "messages_suivants": [
              {
                "signal_id": "sms:suivant-fictif-2",
                "recu_le": "2026-09-15T07:12:00-04:00",
                "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
              },
              {
                "signal_id": "sms:suivant-fictif-3",
                "recu_le": "2026-09-15T07:13:00-04:00",
                "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
              },
              {
                "signal_id": "sms:suivant-fictif-4",
                "recu_le": "2026-09-15T07:14:00-04:00",
                "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
              },
              {
                "signal_id": "sms:suivant-fictif-5",
                "recu_le": "2026-09-15T07:15:00-04:00",
                "texte": "Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre précision factuelle pour votre équipe. Voici une autre pré…"
              }
            ],
            "messages_suivants_omis": 2,
            "client_retire_des_messages": false
          }
        }
      },
      "sha256_corps_json_utf8": "316069ca6aa8726a2521795b5659c2243f213c8fd33524ef1901e4a06a64734e"
    },
    "plainte_stop": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-7e02bf257cd5259aec2c"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "transfert_id": "tr-7e02bf257cd5259aec2c",
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
                "detail": "destinataire à configurer pour le transfert de type 'plainte' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
              },
              "contact": {
                "telephone": "+15145550142"
              },
              "lead_id": null,
              "resume": "Plainte. Ouvert par : les règles. Termes reconnus : insatisfaction (« déçu ») ; dégât (« après vos travaux »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
              "resume_origine": "code",
              "messages_couverts": [
                {
                  "signal_id": "sms:plainte-fictive",
                  "recu_le": "2026-09-15T07:00:00-04:00",
                  "texte": "Mes gouttières à Laval fuient encore après vos travaux, je suis très déçu."
                }
              ],
              "messages_couverts_omis": 0,
              "messages_suivants": [],
              "messages_suivants_omis": 0,
              "client_retire_des_messages": true,
              "brouillon_reponse": null,
              "envoye": false,
              "gabarit": {
                "version": "v1",
                "statut_validation": "proposition"
              },
              "sans_brouillon": "retrait_consentement"
            }
          }
        }
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "transfert_id": "tr-7e02bf257cd5259aec2c",
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
              "detail": "destinataire à configurer pour le transfert de type 'plainte' : déclare le rôle qui le reçoit (nathan_owner, admin, finance, manager, seller, employee) dans /tmp/pytest-of-pc6/pytest-207/test_captures_plainte_urgence_0/opsys-home/entreprise.yaml (clé 'destinataires_transfert') ; M1 ne choisit jamais une personne à la place du propriétaire"
            },
            "contact": {
              "telephone": "+15145550142"
            },
            "lead_id": null,
            "resume": "Plainte. Ouvert par : les règles. Termes reconnus : insatisfaction (« déçu ») ; dégât (« après vos travaux »). Canal : sms. Un message du client, reçu le 2026-09-15T07:00:00-04:00. Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2. Contact : celui du correspondant, vérifié par le canal (porté à part). Les messages du client se lisent avec `m1_lire_transfert`.",
            "resume_origine": "code",
            "messages_couverts": [
              {
                "signal_id": "sms:plainte-fictive",
                "recu_le": "2026-09-15T07:00:00-04:00",
                "texte": "Mes gouttières à Laval fuient encore après vos travaux, je suis très déçu."
              }
            ],
            "messages_couverts_omis": 0,
            "messages_suivants": [],
            "messages_suivants_omis": 0,
            "client_retire_des_messages": true,
            "brouillon_reponse": null,
            "envoye": false,
            "gabarit": {
              "version": "v1",
              "statut_validation": "proposition"
            },
            "sans_brouillon": "retrait_consentement"
          }
        }
      },
      "sha256_corps_json_utf8": "591f74e6f43884659cb0b198e32d432cba16724f0665e6e0ce0029b1da261a37"
    },
    "digest_date": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-09-15"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": "DIGEST - Période de référence : 2026-09-15\n- telephone: signal: 1\n- telephone: transition_phase: 0\n- telephone: lead_emis: 0\n- telephone: chiffrage_emis: 0\n- telephone: alerte: 0\n- courriel: signal: 0\n- courriel: transition_phase: 0\n- courriel: lead_emis: 0\n- courriel: chiffrage_emis: 0\n- courriel: alerte: 0\n- formulaire: signal: 0\n- formulaire: transition_phase: 0\n- formulaire: lead_emis: 0\n- formulaire: chiffrage_emis: 0\n- formulaire: alerte: 0\n- texte: signal: 15\n- texte: transition_phase: 0\n- texte: lead_emis: 0\n- texte: chiffrage_emis: 0\n- texte: alerte: 1\n- conversations ouvertes à suivre : 1\n- conversations sans suivi à l'échéance de leur fenêtre : 1\n- transferts à un humain ouverts : 4\n- dont urgences de sécurité : 1, plaintes : 1\n- appels importés : manque: 1\n- entrées non classées : 1"
        }
      },
      "enveloppe": {
        "ok": true,
        "resultat": "DIGEST - Période de référence : 2026-09-15\n- telephone: signal: 1\n- telephone: transition_phase: 0\n- telephone: lead_emis: 0\n- telephone: chiffrage_emis: 0\n- telephone: alerte: 0\n- courriel: signal: 0\n- courriel: transition_phase: 0\n- courriel: lead_emis: 0\n- courriel: chiffrage_emis: 0\n- courriel: alerte: 0\n- formulaire: signal: 0\n- formulaire: transition_phase: 0\n- formulaire: lead_emis: 0\n- formulaire: chiffrage_emis: 0\n- formulaire: alerte: 0\n- texte: signal: 15\n- texte: transition_phase: 0\n- texte: lead_emis: 0\n- texte: chiffrage_emis: 0\n- texte: alerte: 1\n- conversations ouvertes à suivre : 1\n- conversations sans suivi à l'échéance de leur fenêtre : 1\n- transferts à un humain ouverts : 4\n- dont urgences de sécurité : 1, plaintes : 1\n- appels importés : manque: 1\n- entrées non classées : 1"
      },
      "sha256_corps_json_utf8": "e01c5359c9f2dc7aaed1b2de49bcfd81d4e1478fe2f038d22318e8819930dddd"
    },
    "digest_autre_jour": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2024-02-29"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": "DIGEST - Période de référence : 2024-02-29\n- telephone: signal: 0\n- telephone: transition_phase: 0\n- telephone: lead_emis: 0\n- telephone: chiffrage_emis: 0\n- telephone: alerte: 0\n- courriel: signal: 0\n- courriel: transition_phase: 0\n- courriel: lead_emis: 0\n- courriel: chiffrage_emis: 0\n- courriel: alerte: 0\n- formulaire: signal: 0\n- formulaire: transition_phase: 0\n- formulaire: lead_emis: 0\n- formulaire: chiffrage_emis: 0\n- formulaire: alerte: 0\n- texte: signal: 0\n- texte: transition_phase: 0\n- texte: lead_emis: 0\n- texte: chiffrage_emis: 0\n- texte: alerte: 0\n- conversations ouvertes à suivre : 0\n- conversations sans suivi à l'échéance de leur fenêtre : 0\n- transferts à un humain ouverts : 0\n- dont urgences de sécurité : 0, plaintes : 0\n- entrées non classées : 0"
        }
      },
      "enveloppe": {
        "ok": true,
        "resultat": "DIGEST - Période de référence : 2024-02-29\n- telephone: signal: 0\n- telephone: transition_phase: 0\n- telephone: lead_emis: 0\n- telephone: chiffrage_emis: 0\n- telephone: alerte: 0\n- courriel: signal: 0\n- courriel: transition_phase: 0\n- courriel: lead_emis: 0\n- courriel: chiffrage_emis: 0\n- courriel: alerte: 0\n- formulaire: signal: 0\n- formulaire: transition_phase: 0\n- formulaire: lead_emis: 0\n- formulaire: chiffrage_emis: 0\n- formulaire: alerte: 0\n- texte: signal: 0\n- texte: transition_phase: 0\n- texte: lead_emis: 0\n- texte: chiffrage_emis: 0\n- texte: alerte: 0\n- conversations ouvertes à suivre : 0\n- conversations sans suivi à l'échéance de leur fenêtre : 0\n- transferts à un humain ouverts : 0\n- dont urgences de sécurité : 0, plaintes : 0\n- entrées non classées : 0"
      },
      "sha256_corps_json_utf8": "1c1d49d9716e8fca06c7fa219d4b0580063b114d10503f462e3faaa456365819"
    },
    "transfert_inconnu": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-inconnu-fictif"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-TRANSFERT-INCONNU",
              "statut": "",
              "detail": "aucun transfert 'tr-inconnu-fictif' au registre"
            }
          }
        }
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-TRANSFERT-INCONNU",
            "statut": "",
            "detail": "aucun transfert 'tr-inconnu-fictif' au registre"
          }
        }
      },
      "sha256_corps_json_utf8": "e6c78483f7ee8b550618ff821cdc2992592f409867e43d6f870a60603e96bc42"
    },
    "digest_date_invalide": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-02-30"
      },
      "statut_http": 200,
      "corps": {
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-DIGEST-DATE-INVALIDE",
            "statut": "",
            "detail": "date_reference doit être une date calendaire YYYY-MM-DD"
          }
        }
      },
      "sha256_corps_json_utf8": "03bfcaacc8303ea864aa7f8b88df6b0c59109ee564d901b969feec7b6838bffa"
    },
    "digest_argument_source_refuse": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-09-15",
        "source": "console"
      },
      "statut_http": 200,
      "corps": {
        "ok": true,
        "result": {
          "ok": false,
          "erreur": "arguments_invalides",
          "details": [
            "paramètre inconnu : source"
          ]
        }
      },
      "enveloppe": {
        "ok": false,
        "erreur": "arguments_invalides",
        "details": [
          "paramètre inconnu : source"
        ]
      },
      "sha256_corps_json_utf8": "a68eba19e93a49aec8e88b9c59811f3aaf291edc4cf3b135b2417e3c1e2f56b0"
    },
    "employee_m1_lire_transfert_refuse": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-inconnu-fictif"
      },
      "statut_http": 403,
      "corps": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_lire_transfert\" (tool_out_of_scope)."
        }
      },
      "enveloppe": null,
      "sha256_corps_json_utf8": "eac59fb2a28b9e5367e4c8e92881a7b18be9c083e0f00c3847d647f71a7f11a8"
    },
    "employee_m1_produire_digest_refuse": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-09-15"
      },
      "statut_http": 403,
      "corps": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_produire_digest\" (tool_out_of_scope)."
        }
      },
      "enveloppe": null,
      "sha256_corps_json_utf8": "3c002faff415a884f6e07626ff9baebef0bf1afbafa6c2a9ac62685dfa9009fa"
    },
    "seller_m1_lire_transfert_refuse": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-inconnu-fictif"
      },
      "statut_http": 403,
      "corps": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_lire_transfert\" (tool_out_of_scope)."
        }
      },
      "enveloppe": null,
      "sha256_corps_json_utf8": "eac59fb2a28b9e5367e4c8e92881a7b18be9c083e0f00c3847d647f71a7f11a8"
    },
    "seller_m1_produire_digest_refuse": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-09-15"
      },
      "statut_http": 403,
      "corps": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m1_produire_digest\" (tool_out_of_scope)."
        }
      },
      "enveloppe": null,
      "sha256_corps_json_utf8": "3c002faff415a884f6e07626ff9baebef0bf1afbafa6c2a9ac62685dfa9009fa"
    },
    "role_retire_m1_lire_transfert": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-fdc8b917e27bba2c0d0f"
      },
      "statut_http": 200,
      "corps": {
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "statut": "",
            "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
          }
        }
      },
      "sha256_corps_json_utf8": "5b38b131a2b58e64e71990ae48b26c82fbd4633e30e243be66d18a62d1b4a5e3"
    },
    "role_retire_m1_produire_digest": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-09-15"
      },
      "statut_http": 200,
      "corps": {
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "statut": "",
            "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
          }
        }
      },
      "sha256_corps_json_utf8": "5b38b131a2b58e64e71990ae48b26c82fbd4633e30e243be66d18a62d1b4a5e3"
    },
    "inactive_m1_lire_transfert": {
      "outil": "m1_lire_transfert",
      "args": {
        "transfert_id": "tr-fdc8b917e27bba2c0d0f"
      },
      "statut_http": 200,
      "corps": {
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "statut": "",
            "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
          }
        }
      },
      "sha256_corps_json_utf8": "5b38b131a2b58e64e71990ae48b26c82fbd4633e30e243be66d18a62d1b4a5e3"
    },
    "inactive_m1_produire_digest": {
      "outil": "m1_produire_digest",
      "args": {
        "date_reference": "2026-09-15"
      },
      "statut_http": 200,
      "corps": {
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
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "statut": "",
            "detail": "lecture réservée à une personne admin active ou au propriétaire confirmé de la console"
          }
        }
      },
      "sha256_corps_json_utf8": "5b38b131a2b58e64e71990ae48b26c82fbd4633e30e243be66d18a62d1b4a5e3"
    }
  }
} as const;
