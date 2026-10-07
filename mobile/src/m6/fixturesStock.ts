/** Fixtures FICTIVES dérivées des dix captures natives HTTP MCP ; aucune réponse inventée. */
export const FICTIF = true;
export const provenanceStock = {
  "fictif": true,
  "capture": "work/qualification/stock-contract-fixtures-r1.json",
  "capture_sha256": "0e85744d54a2240532760708aa3079d5024ad95bd2a3b1a5d371d4a0a2d71122",
  "trajet": "HTTP MCP réel ; porte Core simulée en Python ; SQLite temporaire ; aucun téléphone",
  "source_sha256": {
    "tests/e2e/test_stock_admin_appareil.py": "3964da1d23167a49725955df3fa8f3f568d3bfd8791afd30464fb5f6148565fb",
    "tests/fixtures/harnais_e2e.py": "b8d501122b4de8faa4478b787822606cb2eb610b3f6888cf4eb08d479cd0e978",
    "departments/m06-material-control/src/m6_material_control/outils.py": "ca9a7b19cc1eb016d39df8222fadde328d7900c5b2effdd2d7674ae8b401033a",
    "departments/m06-material-control/src/m6_material_control/digest.py": "febc0c7c35d7271e80978985e029d784f62686a15ac1beb6f36bf00d9694429e",
    "departments/m06-material-control/src/m6_material_control/stock.py": "36d5923883bf232ea02a764fa95a63e2d7b32da09eb79c27ee4fac5b1d33c014",
    "departments/m06-material-control/src/m6_material_control/reservations.py": "d38b8e01899b3fc7d2c04cba9ced34ad270cea79f34c0faae1e115a8ae71fea2",
    "departments/m06-material-control/src/m6_material_control/emplacements.py": "e83e0a87ff8c121dcaaf2b1614e29c317b9d9e91308152ff52989ab5a34e2218"
  }
} as const;
export const CAPTURES_STOCK = {
  "reservation_manque_hors_selection_fictif": {
    "nom": "reservation_manque_hors_selection_fictif",
    "outil": "m6_lire_disponibilite",
    "args": {
      "materiau_ids": [
        "gouttiere-5po-fictif"
      ]
    },
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "articles": [
              {
                "materiau_id": "gouttiere-5po-fictif",
                "stock_theorique": "0",
                "hors_main": "0",
                "en_main": "0",
                "reserve": "0",
                "disponible": "0",
                "par_emplacement": {
                  "inconnu": "0"
                }
              }
            ],
            "tronque": false,
            "reservations_actives": [
              {
                "devis_id": "DEVIS-E2E-MP-1",
                "chantier_id": "CHANTIER-E2E-MP-1",
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "gouttiere-5po-fictif",
                    "unite": "pi",
                    "quantite_besoin": "100",
                    "quantite_reservee": "0",
                    "quantite_manquante": "100"
                  },
                  {
                    "materiau_id": "vis-inox-fictif",
                    "unite": "boite",
                    "quantite_besoin": "20",
                    "quantite_reservee": "0",
                    "quantite_manquante": "20"
                  }
                ]
              }
            ],
            "reservations_tronquees": false
          }
        }
      }
    }
  },
  "disponibilite_fictif": {
    "nom": "disponibilite_fictif",
    "outil": "m6_lire_disponibilite",
    "args": {
      "materiau_ids": [
        "gouttiere-5po-fictif"
      ]
    },
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "articles": [
              {
                "materiau_id": "gouttiere-5po-fictif",
                "stock_theorique": "100",
                "hors_main": "30",
                "en_main": "70",
                "reserve": "70",
                "disponible": "0",
                "par_emplacement": {
                  "rebut": "30",
                  "inconnu": "70"
                }
              }
            ],
            "tronque": false,
            "reservations_actives": [
              {
                "devis_id": "DEVIS-E2E-MP-1",
                "chantier_id": "CHANTIER-E2E-MP-1",
                "statut": "partiel",
                "lignes_manquantes": [
                  {
                    "materiau_id": "gouttiere-5po-fictif",
                    "unite": "pi",
                    "quantite_besoin": "100",
                    "quantite_reservee": "70",
                    "quantite_manquante": "30"
                  }
                ]
              }
            ],
            "reservations_tronquees": false
          }
        }
      }
    }
  },
  "digest_sans_seuil_fictif": {
    "nom": "digest_sans_seuil_fictif",
    "outil": "m6_produire_digest",
    "args": {},
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "type": "DIGEST_MATERIEL",
          "nb_variances_stock": 1,
          "nb_reorders_suggeres": 0,
          "variances_significatives": [
            {
              "chantier_id": "CHANTIER-DEPOT",
              "materiau_id": "gouttiere-5po-fictif",
              "verdict_variance": "STOCK_INFERIEUR_AU_THEORIQUE",
              "ecart": -2.0
            }
          ],
          "reorders": [],
          "hash_digest": "5866b5bd46be202afe93034bea6effa29b9e37ca572755de8285acbb1fee4282"
        }
      }
    }
  },
  "digest_seuil_fourni_fictif": {
    "nom": "digest_seuil_fourni_fictif",
    "outil": "m6_produire_digest",
    "args": {
      "seuils_reorder": [
        {
          "chantier_id": "CHANTIER-DEPOT",
          "materiau_id": "gouttiere-5po-fictif",
          "seuil_quantite": 120.0
        }
      ]
    },
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "type": "DIGEST_MATERIEL",
          "nb_variances_stock": 1,
          "nb_reorders_suggeres": 1,
          "variances_significatives": [
            {
              "chantier_id": "CHANTIER-DEPOT",
              "materiau_id": "gouttiere-5po-fictif",
              "verdict_variance": "STOCK_INFERIEUR_AU_THEORIQUE",
              "ecart": -2.0
            }
          ],
          "reorders": [
            {
              "chantier_id": "CHANTIER-DEPOT",
              "materiau_id": "gouttiere-5po-fictif",
              "quantite_suggeree": 20.0
            }
          ],
          "hash_digest": "63bfee543603ce712e57e9efc7a4145cb00edba968d79f84efbf82db9caf5481"
        }
      }
    }
  },
  "refus_admin_desactive_m6_lire_disponibilite_fictif": {
    "nom": "refus_admin_desactive_m6_lire_disponibilite_fictif",
    "outil": "m6_lire_disponibilite",
    "args": {},
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "detail": "personne 'nathan' inconnue, inactive, ou ne porte plus le rôle 'admin' porté par le jeton d'appareil (ou identité non vérifiable hors transaction)"
          }
        }
      }
    }
  },
  "refus_admin_desactive_m6_produire_digest_fictif": {
    "nom": "refus_admin_desactive_m6_produire_digest_fictif",
    "outil": "m6_produire_digest",
    "args": {},
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": false,
          "verdict": {
            "code": "REJ-IDENTITE-APPAREIL-INVALIDE",
            "detail": "personne 'nathan' inconnue, inactive, ou ne porte plus le rôle 'admin' porté par le jeton d'appareil (ou identité non vérifiable hors transaction)"
          }
        }
      }
    }
  },
  "articles_15_fictif": {
    "nom": "articles_15_fictif",
    "outil": "m6_lire_disponibilite",
    "args": {},
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "articles": [
              {
                "materiau_id": "mat-fictif-00",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-01",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-02",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-03",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-04",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-05",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-06",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-07",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-08",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-09",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-10",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-11",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-12",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-13",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-14",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              }
            ],
            "tronque": false,
            "reservations_actives": [],
            "reservations_tronquees": false
          }
        }
      }
    }
  },
  "articles_16_fictif": {
    "nom": "articles_16_fictif",
    "outil": "m6_lire_disponibilite",
    "args": {},
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "articles": [
              {
                "materiau_id": "mat-fictif-00",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-01",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-02",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-03",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-04",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-05",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-06",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-07",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-08",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-09",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-10",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-11",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-12",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-13",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              },
              {
                "materiau_id": "mat-fictif-14",
                "stock_theorique": "1",
                "hors_main": "0",
                "en_main": "1",
                "reserve": "0",
                "disponible": "1",
                "par_emplacement": {
                  "inconnu": "1"
                }
              }
            ],
            "tronque": true,
            "reservations_actives": [],
            "reservations_tronquees": false
          }
        }
      }
    }
  },
  "reservations_10_fictif": {
    "nom": "reservations_10_fictif",
    "outil": "m6_lire_disponibilite",
    "args": {},
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "articles": [
              {
                "materiau_id": "mat-fictif",
                "stock_theorique": "0",
                "hors_main": "0",
                "en_main": "0",
                "reserve": "0",
                "disponible": "0",
                "par_emplacement": {
                  "inconnu": "0"
                }
              }
            ],
            "tronque": false,
            "reservations_actives": [
              {
                "devis_id": "df-fictif-00",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-01",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-02",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-03",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-04",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-05",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-06",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-07",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-08",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-09",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              }
            ],
            "reservations_tronquees": false
          }
        }
      }
    }
  },
  "reservations_11_fictif": {
    "nom": "reservations_11_fictif",
    "outil": "m6_lire_disponibilite",
    "args": {},
    "http_statut": 200,
    "corps": {
      "ok": true,
      "result": {
        "ok": true,
        "resultat": {
          "accepte": true,
          "resultat": {
            "articles": [
              {
                "materiau_id": "mat-fictif",
                "stock_theorique": "0",
                "hors_main": "0",
                "en_main": "0",
                "reserve": "0",
                "disponible": "0",
                "par_emplacement": {
                  "inconnu": "0"
                }
              }
            ],
            "tronque": false,
            "reservations_actives": [
              {
                "devis_id": "df-fictif-00",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-01",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-02",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-03",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-04",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-05",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-06",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-07",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-08",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              },
              {
                "devis_id": "df-fictif-09",
                "chantier_id": null,
                "statut": "a_commander",
                "lignes_manquantes": [
                  {
                    "materiau_id": "mat-fictif",
                    "unite": "pi",
                    "quantite_besoin": "1",
                    "quantite_reservee": "0",
                    "quantite_manquante": "1"
                  }
                ]
              }
            ],
            "reservations_tronquees": true
          }
        }
      }
    }
  }
} as const;
export type NomCaptureStock = keyof typeof CAPTURES_STOCK;
export const disponibiliteFictive = CAPTURES_STOCK.disponibilite_fictif.corps.result.resultat.resultat;
export const digestFictif = CAPTURES_STOCK.digest_sans_seuil_fictif.corps.result.resultat;
/** Copie indépendante de l’enveloppe moteur, sous corps.result comme invoquerOutil. */
export function reponseStock(nom: NomCaptureStock): Record<string, unknown> {
  return JSON.parse(JSON.stringify(CAPTURES_STOCK[nom].corps.result));
}
