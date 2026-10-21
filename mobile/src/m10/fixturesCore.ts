export const FIXTURES_CORE_M10 = {
  "fictif": true,
  "provenance": {
    "path": "qualification/m10-native-core-public-r1/native-proof-r5.json",
    "sha256": "1d95a319aafde60b9bdb974f9a2d2a5b95b66507f8b35c04228d59b8865045aa",
    "core_tree": "f9de21a913ee0e9a41d1d67825fc06ea9d9ba80c",
    "core_build": "inherited principal dist; no rebuild",
    "source_sha256": {
      "departments/m10-memoire/src/m10_memoire/outils.py": "c5844913fcb351d3abb1dc317decdb97b4cb0169118cbc37bc250f95e6371f29",
      "departments/m10-memoire/src/m10_memoire/revision.py": "c5938c902bfe5f9d2a2bb884ad27837acebb3cf096c8d7f8aa0626a25f533d82",
      "departments/m10-memoire/src/m10_memoire/signaux.py": "094890a723b85746a17c1def5f39f884b4ffdd73586a23ba80b62d08184ee235",
      "departments/m10-memoire/tests/test_garde_mobile_admin.py": "90eb9c70f666589b018fe457c320d9de991d3d37a23e7625ea3b97792a4a9f46",
      "departments/m10-memoire/tests/test_signaux.py": "bf8e310f2bc6aea24ead868b07eaf0724f4fde68d16f23a347257d9da41833b8",
      "departments/m10-memoire/tests/test_outils_agent.py": "fe2b9854ffabfe99fff632377c761de643c21c1f588383dd3049d3d06aecd065",
      "departments/m10-memoire/tests/test_ecritures_humaines.py": "fe4aaa95065baece12fbe7aa144a1437a18faffc9c3683817c639921aa7ebb32",
      "tests/e2e/test_memoire_admin_appareil.py": "3df613aed30c664cf6092686e33909f9e8aebecb69a4761f6c02fe2b377435d8",
      "departments/m10-memoire/src/m10_memoire/catalogue_references.py": "dd460e23487f154c9eac68a63300a828ed58f02dcb5de2334c14f42a1dbc6a59",
      "departments/m10-memoire/tests/test_catalogue_references.py": "1f709a1fe6b5e6717568a21a67eb1628b09fbf6622070c029e0ccc324788a1b2",
      "departments/m10-memoire/src/m10_memoire/dossier_revision.py": "442c26fdb24c0325d965445b6856f3251cbb531b8182ebab1feb2a81335a800f",
      "departments/m10-memoire/tests/test_dossier_revision.py": "5803e7d08d7c36d189379caa523a8ef370011453cbb5508ab2f013d7adab20a0"
    },
    "scope": "Captured real Node Gateway/pairedDEVICE/MCP/SQLite; replayed through mobile HTTP client in Jest, not native phone"
  },
  "cases": {
    "signaux": {
      "request": {
        "tool": "m10_lister_signaux",
        "args": {
          "affaire_id": "LEAD-M10-CORE-NATIF-FICTIF-fictif"
        }
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "signaux": [
              {
                "signal_id": "m6-variance-539e17743fba8cace72a209b157d6df98b699b6704ccb82c1112a761cb132c6f-evaluee",
                "affaire_id": "LEAD-M10-CORE-NATIF-FICTIF-fictif",
                "horodatage": "2026-09-16T15:00:00+00:00",
                "etat": "ouvert",
                "traite_par": null,
                "traite_le": null,
                "motif": null
              }
            ],
            "nb_total": 1,
            "nb_omis": 0,
            "nb_ouverts": 1,
            "nb_pris_en_compte": 0,
            "nb_clos": 0
          }
        }
      },
      "tables_unchanged": true
    },
    "catalogue": {
      "request": {
        "tool": "m10_lister_references",
        "args": {}
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "decisions": [
                {
                  "genre": "decision",
                  "decision_id": "DEC-M10-ADMIN-FICTIF-2",
                  "statut": "proposee",
                  "horodatage": "2026-09-15T14:00:00-04:00",
                  "reference": {
                    "ligne_id": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda",
                    "registre": "affaires",
                    "hash_tete": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda"
                  }
                },
                {
                  "genre": "decision",
                  "decision_id": "DEC-M10-ADMIN-FICTIF-1",
                  "statut": "proposee",
                  "horodatage": "2026-09-15T14:00:00-04:00",
                  "reference": {
                    "ligne_id": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2",
                    "registre": "affaires",
                    "hash_tete": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2"
                  }
                }
              ],
              "revisions": [
                {
                  "genre": "revision",
                  "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
                  "statut": "en_attente",
                  "signalee_le": "2026-09-15T14:00:00-04:00",
                  "statut_le": "2026-09-15T14:00:00-04:00",
                  "reference": {
                    "ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
                    "registre": "affaires",
                    "hash_tete": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
                  },
                  "reference_statut": {
                    "ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
                    "registre": "affaires",
                    "hash_tete": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
                  },
                  "reference_a": {
                    "ligne_id": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2",
                    "registre": "affaires",
                    "hash_tete": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2"
                  },
                  "reference_b": {
                    "ligne_id": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda",
                    "registre": "affaires",
                    "hash_tete": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda"
                  }
                }
              ],
              "decalage": 0,
              "suivant": null,
              "reste": 0,
              "total": 3,
              "affichees": 3,
              "limite": 8,
              "borne_caracteres": 5400,
              "taille_caracteres": 1969,
              "confidentialite": {
                "regle": "v1",
                "nb_retenus": 0
              }
            }
          }
        }
      },
      "tables_unchanged": true
    },
    "dossier": {
      "request": {
        "tool": "m10_lire_revision",
        "args": {
          "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
        }
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "revision": {
                "genre": "revision",
                "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
                "statut": "en_attente",
                "signalee_le": "2026-09-15T14:00:00-04:00",
                "statut_le": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
                  "registre": "affaires",
                  "hash_tete": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
                },
                "reference_statut": {
                  "ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
                  "registre": "affaires",
                  "hash_tete": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
                },
                "reference_a": {
                  "ligne_id": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2",
                  "registre": "affaires",
                  "hash_tete": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2"
                },
                "reference_b": {
                  "ligne_id": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda",
                  "registre": "affaires",
                  "hash_tete": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda"
                }
              },
              "faits": [
                {
                  "reference": {
                    "ligne_id": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2",
                    "registre": "affaires",
                    "hash_tete": "39c95d7fbc415f80f20ff3305aa292221269cd772fd483caf6ae5c35e29624a2"
                  },
                  "type_entree": "decision_enregistree",
                  "horodatage": "2026-09-15T14:00:00-04:00",
                  "champs": {
                    "decision_id": "DEC-M10-ADMIN-FICTIF-1",
                    "raison": "Révision chantier fictif attestée.",
                    "statut": "proposee",
                    "options_ecartees": "Ne rien faire"
                  }
                },
                {
                  "reference": {
                    "ligne_id": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda",
                    "registre": "affaires",
                    "hash_tete": "2026097dbe3f0cc122810bb3c214c45f1fea5ad851f95855e06cd13213616bda"
                  },
                  "type_entree": "decision_enregistree",
                  "horodatage": "2026-09-15T14:00:00-04:00",
                  "champs": {
                    "decision_id": "DEC-M10-ADMIN-FICTIF-2",
                    "raison": "Révision chantier fictif attestée.",
                    "statut": "proposee",
                    "options_ecartees": "Ne rien faire"
                  }
                }
              ]
            }
          }
        }
      },
      "tables_unchanged": true
    },
    "decision": {
      "request": {
        "tool": "m10_statut_decision",
        "args": {
          "decision_id": "DEC-M10-ADMIN-FICTIF-1"
        }
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "statut": "proposee"
          }
        }
      },
      "tables_unchanged": true
    },
    "revision": {
      "request": {
        "tool": "m10_statut_revision",
        "args": {
          "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
        }
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "statut": "en_attente"
          }
        }
      },
      "tables_unchanged": true
    },
    "role_employee": {
      "request": {
        "tool": "m10_lister_signaux",
        "args": {}
      },
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m10_lister_signaux\" (tool_out_of_scope)."
        }
      },
      "tables_unchanged": true
    },
    "role_seller": {
      "request": {
        "tool": "m10_lister_signaux",
        "args": {}
      },
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "OPSYS device is not authorized to call \"m10_lister_signaux\" (tool_out_of_scope)."
        }
      },
      "tables_unchanged": true
    },
    "body_device_id_usurpe": {
      "request": {
        "tool": "m10_lister_signaux",
        "args": {},
        "deviceId": "9ced053cc668f3a68b1c9f8825449b1588eba23daca8d4d9d917bcfdcfdfeee0"
      },
      "status": 403,
      "response": {
        "ok": false,
        "error": {
          "type": "tool_call_blocked",
          "message": "Request body deviceId does not match the authenticated device."
        }
      },
      "tables_unchanged": true
    },
    "arbitrage": {
      "request": {
        "tool": "m10_arbitrer_revision",
        "args": {
          "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
          "statut": "distincts_confirmes",
          "horodatage": "2000-01-01T00:00:00Z"
        },
        "idempotencyKey": "94f468cd-82ce-44cc-b50e-c5c6732c0155",
        "deviceTimestamp": "2000-01-01T00:00:00Z"
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "type_entree": "revision_signalee",
              "horodatage": "2026-09-16T15:10:00+00:00",
              "ligne_id_a": null,
              "ligne_id_b": null,
              "statut": "distincts_confirmes",
              "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
              "par": "nathan",
              "role": "admin",
              "source_decision": "appareil",
              "ligne_id": "2a22b5bcfe438c1c6f3600910ab0fff0792520bb20c962505313f2ae92d0549d",
              "precedent_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
            }
          },
          "rejoue": false
        }
      },
      "tables_unchanged": false
    },
    "rejeu": {
      "request": {
        "tool": "m10_arbitrer_revision",
        "args": {
          "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
          "statut": "distincts_confirmes",
          "horodatage": "2000-01-01T00:00:00Z"
        },
        "idempotencyKey": "94f468cd-82ce-44cc-b50e-c5c6732c0155",
        "deviceTimestamp": "2000-01-01T00:00:00Z"
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "type_entree": "revision_signalee",
              "horodatage": "2026-09-16T15:10:00+00:00",
              "ligne_id_a": null,
              "ligne_id_b": null,
              "statut": "distincts_confirmes",
              "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
              "par": "nathan",
              "role": "admin",
              "source_decision": "appareil",
              "ligne_id": "2a22b5bcfe438c1c6f3600910ab0fff0792520bb20c962505313f2ae92d0549d",
              "precedent_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
            }
          },
          "rejoue": true
        }
      },
      "tables_unchanged": true
    },
    "rejeu_apres_backend_reboot": {
      "request": {
        "tool": "m10_arbitrer_revision",
        "args": {
          "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
          "statut": "distincts_confirmes",
          "horodatage": "2000-01-01T00:00:00Z"
        },
        "idempotencyKey": "94f468cd-82ce-44cc-b50e-c5c6732c0155",
        "deviceTimestamp": "2000-01-01T00:00:00Z"
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": true,
            "resultat": {
              "type_entree": "revision_signalee",
              "horodatage": "2026-09-16T15:10:00+00:00",
              "ligne_id_a": null,
              "ligne_id_b": null,
              "statut": "distincts_confirmes",
              "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
              "par": "nathan",
              "role": "admin",
              "source_decision": "appareil",
              "ligne_id": "2a22b5bcfe438c1c6f3600910ab0fff0792520bb20c962505313f2ae92d0549d",
              "precedent_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
            }
          },
          "rejoue": true
        }
      },
      "tables_unchanged": true
    },
    "conflit_uuid": {
      "request": {
        "tool": "m10_arbitrer_revision",
        "args": {
          "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
          "statut": "obsolete_marquee",
          "horodatage": "2000-01-01T00:00:00Z"
        },
        "idempotencyKey": "94f468cd-82ce-44cc-b50e-c5c6732c0155",
        "deviceTimestamp": "2000-01-01T00:00:00Z"
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": false,
          "erreur": "mutation_conflit",
          "details": "clé '94f468cd-82ce-44cc-b50e-c5c6732c0155' de l'appareil '3969d05893983a7695918d89ad5f2c1b89f0ab27fd50dd1bcc1c4c3e866920c5' déjà utilisée pour d'autres arguments ('m10_arbitrer_revision')"
        }
      },
      "tables_unchanged": true
    },
    "role_retire_backend": {
      "request": {
        "tool": "m10_lire_revision",
        "args": {
          "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
        }
      },
      "status": 200,
      "response": {
        "ok": true,
        "result": {
          "ok": true,
          "resultat": {
            "accepte": false,
            "verdict": {
              "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
              "detail": "cette lecture exige une personne admin active confirmée en base"
            }
          }
        }
      },
      "tables_unchanged": true
    }
  }
} as const;
