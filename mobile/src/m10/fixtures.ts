// Captures natives fictives ; aucun remaniement des enveloppes.
export const FIXTURES_M10 = {
  "fictif": true,
  "provenance": [
    {
      "chemin": "m10-contract-fixtures-r4.json",
      "sha256": "c132302a61667c6c3ff38a83a4ec44c213b3b38024783b07acb6d0ccac987642",
      "preuve": "HTTP MCP/SQLite réel ; porte Core rejouée Python ; perte réponse simulée",
      "enveloppes_sha256": {
        "signaux_ouverts": "e5f3602cce173eda14a6f9806846c169ca46b1f2c50ca850e6cdda86afb5a9c1",
        "decision_proposee": "b09412ecf2936f23ce7bcddd9604b545f82ccb51af86e53808b3f637efe59900",
        "revision_en_attente": "88936bd3a0ea4cd3d9a837522bc99c45065d79cc29df16a7e3d16ec8b6af9ab3",
        "decision_inconnue": "0ce85aed15da230b35b8e0b6dc622198dde6394b7148dee2426bc47458f077d1",
        "revision_inconnue": "0ce85aed15da230b35b8e0b6dc622198dde6394b7148dee2426bc47458f077d1",
        "arbitrage_accepte": "5d281386b75fb7c515a7c1055bf93f0b6987b2c031fd806096f1766a99716632",
        "arbitrage_rejoue": "cc2b642182fad0820785b3e7d435231cfae4a3145c02c04c650075a097272b33",
        "revision_arbitree": "6fff7bf8589ac2099eaa82096883b64f5800d1023f655be7095bb2a180849fcd",
        "lecture_revoquee": "32d8b87b94c7fc864a6d373dbf60fe48f00111eb85d0c6234958503433feeb29"
      }
    },
    {
      "chemin": "m10-contract-fixtures-r4-volume.json",
      "sha256": "e5afad1a379df09985ec7c9b678410355183ca103b4a9675b42157792c4ec12c",
      "preuve": "fixtures volume via consommateurs M10 et traitements réels",
      "enveloppes_sha256": {
        "signaux_volume": "165ad724b4e7d78c8d9a9a9af5e82ab11018ed22beec805fc2745186ec0ea2e4"
      }
    },
    {
      "chemin": "m10-catalogue-fixtures-r2-catalogue.json",
      "sha256": "05ba078039ce81167542572902fcad4d6abf138542aef261b7eefc1ef4871463",
      "preuve": "HTTP MCP/SQLite réel ; porte Core rejouée Python ; catalogue des Affaires",
      "enveloppes_sha256": {
        "catalogue_page_1": "1528608511b455141525bdf0eb77db9e038c9e3c19bfa8b4062e64f396937411",
        "catalogue_page_2": "b791b241f9dbe4963eefa35cde15ff7fd43822db66ff3e70df594dc9a47600fb",
        "catalogue_hors_page": "68fbe2e8cf8979aaa4e26b29fec94209ecb588d6e6ae1a1a7e32d1be51bd8e60",
        "catalogue_pagination_invalide": "eb9c78d1dfe716a3354892ddfd55365eca7da749c8b3f9e13229c8298c940799",
        "catalogue_schema_invalide": "60981283a8321c2d3ded8a6e5ec0074981fd2901b9b3df5a2a3fbcb18c06e7cd",
        "catalogue_role_revoque": "32d8b87b94c7fc864a6d373dbf60fe48f00111eb85d0c6234958503433feeb29"
      }
    }
  ],
  "reponses": {
    "signaux_ouverts": {
      "outil": "m10_lister_signaux",
      "args": {
        "affaire_id": "LEAD-M10-CONTRAT-FICTIF-fictif"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "signaux": [
            {
              "signal_id": "m6-variance-6461b3d8bf255571e94a3ec140423c79ac2e0aaffd39d4ffbdd42aab1a4fb6a5-evaluee",
              "affaire_id": "LEAD-M10-CONTRAT-FICTIF-fictif",
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
    "decision_proposee": {
      "outil": "m10_statut_decision",
      "args": {
        "decision_id": "DEC-M10-ADMIN-FICTIF-1"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "statut": "proposee"
        }
      }
    },
    "revision_en_attente": {
      "outil": "m10_statut_revision",
      "args": {
        "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "statut": "en_attente"
        }
      }
    },
    "decision_inconnue": {
      "outil": "m10_statut_decision",
      "args": {
        "decision_id": "DEC-INCONNUE-FICTIVE"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "statut": null
        }
      }
    },
    "revision_inconnue": {
      "outil": "m10_statut_revision",
      "args": {
        "revision_ligne_id": "revision-inconnue-fictive"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "statut": null
        }
      }
    },
    "arbitrage_accepte": {
      "outil": "m10_arbitrer_revision",
      "args": {
        "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
        "statut": "distincts_confirmes",
        "horodatage": "2000-01-01T00:00:00Z"
      },
      "enveloppe": {
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
            "par": "gestionnaire.fictif",
            "role": "admin",
            "source_decision": "appareil",
            "ligne_id": "cfc951d4faeda9133bf6ade9b3020f544c428d09ee6ce378090708745c1f82e7",
            "precedent_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
          }
        },
        "rejoue": false
      }
    },
    "arbitrage_rejoue": {
      "outil": "m10_arbitrer_revision",
      "args": {
        "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3",
        "statut": "distincts_confirmes",
        "horodatage": "2000-01-01T00:00:00Z"
      },
      "enveloppe": {
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
            "par": "gestionnaire.fictif",
            "role": "admin",
            "source_decision": "appareil",
            "ligne_id": "cfc951d4faeda9133bf6ade9b3020f544c428d09ee6ce378090708745c1f82e7",
            "precedent_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
          }
        },
        "rejoue": true
      }
    },
    "revision_arbitree": {
      "outil": "m10_statut_revision",
      "args": {
        "revision_ligne_id": "f57a9234c7ea19d06ce10d41dbbdedec1047970d7afc6f67bd81614f877ae3e3"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "statut": "distincts_confirmes"
        }
      }
    },
    "lecture_revoquee": {
      "outil": "m10_lister_signaux",
      "args": {},
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
    },
    "signaux_volume": {
      "outil": "m10_lister_signaux",
      "args": {
        "affaire_id": "LEAD-VOLUME-FICTIF"
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "signaux": [
            {
              "signal_id": "EVT-VOLUME-FICTIF-049",
              "affaire_id": "LEAD-VOLUME-FICTIF",
              "horodatage": "2026-09-15T14:00:00-04:00",
              "etat": "pris_en_compte",
              "traite_par": "nathan",
              "traite_le": "2026-09-15T14:00:00-04:00",
              "motif": "Écart fictif expliqué : éééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé"
            },
            {
              "signal_id": "EVT-VOLUME-FICTIF-048",
              "affaire_id": "LEAD-VOLUME-FICTIF",
              "horodatage": "2026-09-15T14:00:00-04:00",
              "etat": "pris_en_compte",
              "traite_par": "nathan",
              "traite_le": "2026-09-15T14:00:00-04:00",
              "motif": "Écart fictif expliqué : éééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé"
            },
            {
              "signal_id": "EVT-VOLUME-FICTIF-047",
              "affaire_id": "LEAD-VOLUME-FICTIF",
              "horodatage": "2026-09-15T14:00:00-04:00",
              "etat": "pris_en_compte",
              "traite_par": "nathan",
              "traite_le": "2026-09-15T14:00:00-04:00",
              "motif": "Écart fictif expliqué : éééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé"
            },
            {
              "signal_id": "EVT-VOLUME-FICTIF-046",
              "affaire_id": "LEAD-VOLUME-FICTIF",
              "horodatage": "2026-09-15T14:00:00-04:00",
              "etat": "pris_en_compte",
              "traite_par": "nathan",
              "traite_le": "2026-09-15T14:00:00-04:00",
              "motif": "Écart fictif expliqué : éééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé"
            },
            {
              "signal_id": "EVT-VOLUME-FICTIF-045",
              "affaire_id": "LEAD-VOLUME-FICTIF",
              "horodatage": "2026-09-15T14:00:00-04:00",
              "etat": "pris_en_compte",
              "traite_par": "nathan",
              "traite_le": "2026-09-15T14:00:00-04:00",
              "motif": "Écart fictif expliqué : éééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé"
            },
            {
              "signal_id": "EVT-VOLUME-FICTIF-044",
              "affaire_id": "LEAD-VOLUME-FICTIF",
              "horodatage": "2026-09-15T14:00:00-04:00",
              "etat": "pris_en_compte",
              "traite_par": "nathan",
              "traite_le": "2026-09-15T14:00:00-04:00",
              "motif": "Écart fictif expliqué : éééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé"
            },
            {
              "signal_id": "EVT-VOLUME-FICTIF-043",
              "affaire_id": "LEAD-VOLUME-FICTIF",
              "horodatage": "2026-09-15T14:00:00-04:00",
              "etat": "pris_en_compte",
              "traite_par": "nathan",
              "traite_le": "2026-09-15T14:00:00-04:00",
              "motif": "Écart fictif expliqué : éééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé"
            }
          ],
          "nb_total": 50,
          "nb_omis": 43,
          "nb_ouverts": 0,
          "nb_pris_en_compte": 50,
          "nb_clos": 0
        }
      }
    },
    "catalogue_page_1": {
      "outil": "m10_lister_references",
      "args": {},
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "decisions": [
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-12",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "43e5662d99396fd413a85874c81279f6626cb45beafdaa0052b74ec48c0bfaf4",
                  "registre": "affaires",
                  "hash_tete": "43e5662d99396fd413a85874c81279f6626cb45beafdaa0052b74ec48c0bfaf4"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-11",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "a88e789c1c067f37c402057eb593933ac80016bd3e3e9cc7a975fa44207b778d",
                  "registre": "affaires",
                  "hash_tete": "a88e789c1c067f37c402057eb593933ac80016bd3e3e9cc7a975fa44207b778d"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-10",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "714bffed257fc22ed5f8b185a1623fd08ab87d978bee51d897d907aae5b65fbd",
                  "registre": "affaires",
                  "hash_tete": "714bffed257fc22ed5f8b185a1623fd08ab87d978bee51d897d907aae5b65fbd"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-09",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "7fe16f1e9d2c9f4878f83306f9d4704ee6a5bccde7865f6d6fa9053ce6c10824",
                  "registre": "affaires",
                  "hash_tete": "7fe16f1e9d2c9f4878f83306f9d4704ee6a5bccde7865f6d6fa9053ce6c10824"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-08",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "48bfad1b18d3e2aa36d048d0797142afab3e6aef4615180bf6d6c553ae56adb0",
                  "registre": "affaires",
                  "hash_tete": "48bfad1b18d3e2aa36d048d0797142afab3e6aef4615180bf6d6c553ae56adb0"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-07",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "b9c03e36b1ae736cef99819a1ec481569758b7759cb23a5f9add97a141de5574",
                  "registre": "affaires",
                  "hash_tete": "b9c03e36b1ae736cef99819a1ec481569758b7759cb23a5f9add97a141de5574"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-06",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "c225572bf0335b50dbd7e9769d87bd8cfe09c028c88b1841550fe071d0fcab8f",
                  "registre": "affaires",
                  "hash_tete": "c225572bf0335b50dbd7e9769d87bd8cfe09c028c88b1841550fe071d0fcab8f"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-05",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "f6cec2de83ab82e2b4201ebd69f538f4b8c930691b72fc15352238658196d3aa",
                  "registre": "affaires",
                  "hash_tete": "f6cec2de83ab82e2b4201ebd69f538f4b8c930691b72fc15352238658196d3aa"
                }
              }
            ],
            "revisions": [],
            "decalage": 0,
            "suivant": 8,
            "reste": 8,
            "total": 16,
            "affichees": 8,
            "limite": 8,
            "borne_caracteres": 5400,
            "taille_caracteres": 2918,
            "confidentialite": {
              "regle": "v1",
              "nb_retenus": 1
            }
          }
        }
      }
    },
    "catalogue_page_2": {
      "outil": "m10_lister_references",
      "args": {
        "decalage": 8
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "decisions": [
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-04",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "d7a9a8e4007293075dfa16ff2325de87ad82d220de72368e3cd99e89442c1aca",
                  "registre": "affaires",
                  "hash_tete": "d7a9a8e4007293075dfa16ff2325de87ad82d220de72368e3cd99e89442c1aca"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-03",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "8954081df07de8f58453975173e028d15a79b018d5a42a803ecca13c953f994b",
                  "registre": "affaires",
                  "hash_tete": "8954081df07de8f58453975173e028d15a79b018d5a42a803ecca13c953f994b"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-02",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "774d8c978227744db39d8b3a60a6d9fc04b5bef0a8046869826ee6deb78bbbee",
                  "registre": "affaires",
                  "hash_tete": "774d8c978227744db39d8b3a60a6d9fc04b5bef0a8046869826ee6deb78bbbee"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-01",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "e50e347d7227b712fdd25168087c282feee86ba0d1709ba00d05c118d7932b5a",
                  "registre": "affaires",
                  "hash_tete": "e50e347d7227b712fdd25168087c282feee86ba0d1709ba00d05c118d7932b5a"
                }
              },
              {
                "genre": "decision",
                "decision_id": "DEC-CATALOGUE-FICTIF-00",
                "statut": "proposee",
                "horodatage": "2026-09-15T14:00:00-04:00",
                "reference": {
                  "ligne_id": "25fa4d6a6c7b985668dd96702041f3382cf3ea6b034b91e0abb3a86e05a240f6",
                  "registre": "affaires",
                  "hash_tete": "25fa4d6a6c7b985668dd96702041f3382cf3ea6b034b91e0abb3a86e05a240f6"
                }
              },
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
            "decalage": 8,
            "suivant": null,
            "reste": 0,
            "total": 16,
            "affichees": 8,
            "limite": 8,
            "borne_caracteres": 5400,
            "taille_caracteres": 3620,
            "confidentialite": {
              "regle": "v1",
              "nb_retenus": 1
            }
          }
        }
      }
    },
    "catalogue_hors_page": {
      "outil": "m10_lister_references",
      "args": {
        "decalage": 999
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "decisions": [],
            "revisions": [],
            "decalage": 999,
            "suivant": null,
            "reste": 0,
            "total": 16,
            "affichees": 0,
            "limite": 8,
            "borne_caracteres": 5400,
            "taille_caracteres": 284,
            "confidentialite": {
              "regle": "v1",
              "nb_retenus": 1
            }
          }
        }
      }
    },
    "catalogue_pagination_invalide": {
      "outil": "m10_lister_references",
      "args": {
        "limite": 9
      },
      "enveloppe": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-CATALOGUE-PAGINATION-INVALIDE",
            "detail": "limite entière de 1 à 8 et décalage entier positif ou nul"
          }
        }
      }
    },
    "catalogue_schema_invalide": {
      "outil": "m10_lister_references",
      "args": {
        "domaine": "developpement"
      },
      "enveloppe": {
        "ok": false,
        "erreur": "arguments_invalides",
        "details": [
          "paramètre inconnu : domaine"
        ]
      }
    },
    "catalogue_role_revoque": {
      "outil": "m10_lister_references",
      "args": {},
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
