export const FIXTURES_DOSSIER_M10 = {
  "fictif": true,
  "provenance": {
    "path": "qualification/m10-dossier-fixtures-r3-dossier.json",
    "sha256": "a1497b97a303a981c285561bde617a1a98ea1553bd78d63fdfc7350c06091aed",
    "scope": "HTTP/SQLite réel ; porte Core rejouée Python ; décisions M10, événement fixture",
    "source_sha256": {
      "departments/m10-memoire/src/m10_memoire/outils.py": "c5844913fcb351d3abb1dc317decdb97b4cb0169118cbc37bc250f95e6371f29",
      "departments/m10-memoire/src/m10_memoire/revision.py": "c5938c902bfe5f9d2a2bb884ad27837acebb3cf096c8d7f8aa0626a25f533d82",
      "departments/m10-memoire/src/m10_memoire/signaux.py": "094890a723b85746a17c1def5f39f884b4ffdd73586a23ba80b62d08184ee235",
      "departments/m10-memoire/src/m10_memoire/catalogue_references.py": "dd460e23487f154c9eac68a63300a828ed58f02dcb5de2334c14f42a1dbc6a59",
      "departments/m10-memoire/tests/test_catalogue_references.py": "1f709a1fe6b5e6717568a21a67eb1628b09fbf6622070c029e0ccc324788a1b2",
      "departments/m10-memoire/src/m10_memoire/dossier_revision.py": "442c26fdb24c0325d965445b6856f3251cbb531b8182ebab1feb2a81335a800f",
      "departments/m10-memoire/tests/test_dossier_revision.py": "5803e7d08d7c36d189379caa523a8ef370011453cbb5508ab2f013d7adab20a0",
      "tests/e2e/test_memoire_admin_appareil.py": "3df613aed30c664cf6092686e33909f9e8aebecb69a4761f6c02fe2b377435d8"
    }
  },
  "reponses": {
    "dossier_complet": {
      "outil": "m10_lire_revision",
      "args": {
        "revision_ligne_id": "8a3078cbf7a6d4f410f7804f45b7037ec16ce6d44d70beedbe902db788da078b"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "revision": {
              "genre": "revision",
              "revision_ligne_id": "8a3078cbf7a6d4f410f7804f45b7037ec16ce6d44d70beedbe902db788da078b",
              "statut": "en_attente",
              "signalee_le": "2026-09-15T14:00:00-04:00",
              "statut_le": "2026-09-15T14:00:00-04:00",
              "reference": {
                "ligne_id": "8a3078cbf7a6d4f410f7804f45b7037ec16ce6d44d70beedbe902db788da078b",
                "registre": "affaires",
                "hash_tete": "8a3078cbf7a6d4f410f7804f45b7037ec16ce6d44d70beedbe902db788da078b"
              },
              "reference_statut": {
                "ligne_id": "8a3078cbf7a6d4f410f7804f45b7037ec16ce6d44d70beedbe902db788da078b",
                "registre": "affaires",
                "hash_tete": "8a3078cbf7a6d4f410f7804f45b7037ec16ce6d44d70beedbe902db788da078b"
              },
              "reference_a": {
                "ligne_id": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35",
                "registre": "affaires",
                "hash_tete": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35"
              },
              "reference_b": {
                "ligne_id": "e91ce2ac8618987fb8834d91a5f95e346f988f29acca977f5d23d313873621e3",
                "registre": "affaires",
                "hash_tete": "e91ce2ac8618987fb8834d91a5f95e346f988f29acca977f5d23d313873621e3"
              }
            },
            "faits": [
              {
                "reference": {
                  "ligne_id": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35",
                  "registre": "affaires",
                  "hash_tete": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35"
                },
                "type_entree": "decision_enregistree",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "champs": {
                  "decision_id": "DEC-JOINTS-FICTIVE",
                  "raison": "Deux joints de gouttière repris après inspection (fictif).",
                  "statut": "proposee",
                  "options_ecartees": "Conserver l'installation initiale (fictif)."
                }
              },
              {
                "reference": {
                  "ligne_id": "e91ce2ac8618987fb8834d91a5f95e346f988f29acca977f5d23d313873621e3",
                  "registre": "affaires",
                  "hash_tete": "e91ce2ac8618987fb8834d91a5f95e346f988f29acca977f5d23d313873621e3"
                },
                "type_entree": "decision_enregistree",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "champs": {
                  "decision_id": "DEC-INSPECTION-FICTIVE",
                  "raison": "Inspection des deux joints après reprise satisfaisante (fictif).",
                  "statut": "proposee",
                  "options_ecartees": "Conserver l'installation initiale (fictif)."
                }
              }
            ]
          }
        }
      }
    },
    "dossier_inconnu": {
      "outil": "m10_lire_revision",
      "args": {
        "revision_ligne_id": "revision-inconnue-fictive"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-DOSSIER-REVISION-INCONNUE",
            "detail": "Aucun signalement réel de révision ne correspond à cette référence."
          }
        }
      }
    },
    "dossier_evenement_preuves": {
      "outil": "m10_lire_revision",
      "args": {
        "revision_ligne_id": "b5f6a6f63bff3291f90ddac76bd7bb5cc1944eb5b6584151cb2f4276da3a4965"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "revision": {
              "genre": "revision",
              "revision_ligne_id": "b5f6a6f63bff3291f90ddac76bd7bb5cc1944eb5b6584151cb2f4276da3a4965",
              "statut": "en_attente",
              "signalee_le": "2026-09-15T14:00:00-04:00",
              "statut_le": "2026-09-15T14:00:00-04:00",
              "reference": {
                "ligne_id": "b5f6a6f63bff3291f90ddac76bd7bb5cc1944eb5b6584151cb2f4276da3a4965",
                "registre": "affaires",
                "hash_tete": "b5f6a6f63bff3291f90ddac76bd7bb5cc1944eb5b6584151cb2f4276da3a4965"
              },
              "reference_statut": {
                "ligne_id": "b5f6a6f63bff3291f90ddac76bd7bb5cc1944eb5b6584151cb2f4276da3a4965",
                "registre": "affaires",
                "hash_tete": "b5f6a6f63bff3291f90ddac76bd7bb5cc1944eb5b6584151cb2f4276da3a4965"
              },
              "reference_a": {
                "ligne_id": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35",
                "registre": "affaires",
                "hash_tete": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35"
              },
              "reference_b": {
                "ligne_id": "c48a7f2c2bd4e4fcf5f1b0b60b3fce467599db9a0bb4728a74eb75bc0a1a4b26",
                "registre": "affaires",
                "hash_tete": "c48a7f2c2bd4e4fcf5f1b0b60b3fce467599db9a0bb4728a74eb75bc0a1a4b26"
              }
            },
            "faits": [
              {
                "reference": {
                  "ligne_id": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35",
                  "registre": "affaires",
                  "hash_tete": "9d09796043395dd23977e32cdc18b0ffb1948268a4f1d381d4972ac489eb9e35"
                },
                "type_entree": "decision_enregistree",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "champs": {
                  "decision_id": "DEC-JOINTS-FICTIVE",
                  "raison": "Deux joints de gouttière repris après inspection (fictif).",
                  "statut": "proposee",
                  "options_ecartees": "Conserver l'installation initiale (fictif)."
                }
              },
              {
                "reference": {
                  "ligne_id": "c48a7f2c2bd4e4fcf5f1b0b60b3fce467599db9a0bb4728a74eb75bc0a1a4b26",
                  "registre": "affaires",
                  "hash_tete": "c48a7f2c2bd4e4fcf5f1b0b60b3fce467599db9a0bb4728a74eb75bc0a1a4b26"
                },
                "type_entree": "evenement_memorise",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "champs": {
                  "evenement": "Inspection des joints (source fictive)",
                  "preuves": {
                    "photos": [
                      "photo-fictive-1"
                    ],
                    "mesure": {
                      "valeur": 2,
                      "unite": "joints"
                    },
                    "confirme": true,
                    "note": null
                  }
                }
              }
            ]
          }
        }
      }
    },
    "dossier_confidentialite": {
      "outil": "m10_lire_revision",
      "args": {
        "revision_ligne_id": "636ef2ecbc46f3f6660a6ecb54b76e0b532fc2ed34543811423592719d71495c"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-DOSSIER-REVISION-RETENU",
            "detail": "Une pièce est retenue par la confidentialité ; aucun fait n'est restitué."
          }
        }
      }
    },
    "dossier_hors_budget": {
      "outil": "m10_lire_revision",
      "args": {
        "revision_ligne_id": "a49e5b359ad3ffdad8ddeb8d0c389d90ae8aed3cdd65071c51e2415da97ccf24"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-DOSSIER-REVISION-BUDGET-DEPASSE",
            "detail": "Le dossier complet dépasse 5400 caractères ; aucun fait n'est coupé."
          }
        }
      }
    },
    "dossier_source_non_comparable": {
      "outil": "m10_lire_revision",
      "args": {
        "revision_ligne_id": "38598b798862ec440f1c91ef75db3d45c771ffba16bf2313fbb53a294b765e07"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-DOSSIER-REVISION-TYPE-FAIT-INTERDIT",
            "detail": "La source est un contrôle ou hors mémoire métier, non comparable."
          }
        }
      }
    },
    "dossier_identite_revoquee": {
      "outil": "m10_lire_revision",
      "args": {
        "revision_ligne_id": "8a3078cbf7a6d4f410f7804f45b7037ec16ce6d44d70beedbe902db788da078b"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "detail": "cette lecture exige une personne admin active confirmée en base"
          }
        }
      }
    }
  }
} as const;
