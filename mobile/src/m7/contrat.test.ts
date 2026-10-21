import { lireListeM7 } from "./contrat";

/** FICTIF : projection de usine/service.py::_ligne_contenu et lister_contenus_chantier,
 * exécutée dans l'enveloppe directe de opsys.outils.executer. Capture HTTP ajoutée ensuite. */
const FICTIF = true;
const marque = { source: "brand_profiles", revision: 3, sha256: "a".repeat(64) } as const;
const contenu = {
  contenu_id: "contenu-fictif-revision-2", wct_id: "wct-fictif-1", plateforme: "instagram", revision: 2,
  approval_status: "PROPOSE", exporte: false, marque_source: marque, fraicheur_marque: "courante",
  texte: "Chantier fictif terminé : remplacement des gouttières.", origine_texte: "gabarit",
  mots_clics: ["#chantierfictif"], lien_utm: null, avertissements: [], decision: null,
  consentement: { recueilli_par: "etienne.fictif", recueilli_le: "2026-10-07T12:00:00Z", version_texte: "v1-fictif" },
} as const;
const page = { total: 1, marque_courante: marque, contenus: [contenu], decalage: 0, suivant: null, reste: 0 };
const directe = (value: unknown) => ({ ok: true, resultat: value });

test("la liste native DIRECTE est lisible, sans couche accepte/resultat inventée", () => {
  expect(FICTIF).toBe(true);
  expect(lireListeM7(directe(page))).toEqual({ ok: true, value: {
    items: [contenu], total: 1, decalage: 0, suivant: null, reste: 0, marqueCourante: marque,
  } });
  expect(lireListeM7({ ok: true, resultat: { accepte: true, resultat: page } }).ok).toBe(false);
});

test("une page réduite par le budget garde le texte intégral et avance du nombre effectivement livré", () => {
  const long = { ...contenu, texte: "Contenu fictif complet. ".repeat(120) };
  const lu = lireListeM7(directe({ ...page, total: 8, contenus: [long], suivant: 1, reste: 7 }));
  expect(lu).toEqual({ ok: true, value: {
    items: [long], total: 8, decalage: 0, suivant: 1, reste: 7, marqueCourante: marque,
  } });
});

test("page finale, vide et decalage au-delà de la fin suivent le contrat natif", () => {
  for (const decalage of [1, 9]) {
    expect(lireListeM7(directe({ ...page, contenus: [], decalage }))).toEqual({ ok: true, value: {
      items: [], total: 1, decalage, suivant: null, reste: 0, marqueCourante: marque,
    } });
  }
  expect(lireListeM7(directe({ ...page, total: 0, contenus: [], marque_courante: null }))).toEqual({ ok: true, value: {
    items: [], total: 0, decalage: 0, suivant: null, reste: 0, marqueCourante: null,
  } });
});

test.each([-1, 1.5, NaN, Infinity, "1", null, undefined, 2 ** 53])("compteurs non sûrs %p fermés", valeur => {
  for (const champ of ["total", "decalage", "reste", "suivant"] as const) {
    if (champ === "suivant" && valeur === null) continue;
    expect(lireListeM7(directe({ ...page, [champ]: valeur })).ok).toBe(false);
  }
});

test("cohérence de page : ni curseur à la fin, ni page vide intérieure, ni somme unsafe", () => {
  for (const invalide of [
    { ...page, suivant: 1 }, { ...page, suivant: 9 }, { ...page, reste: 1 },
    { ...page, total: 2, suivant: null, reste: 1 },
    { ...page, contenus: [], total: 2, suivant: null, reste: 2 },
    { ...page, decalage: Number.MAX_SAFE_INTEGER, total: Number.MAX_SAFE_INTEGER },
  ]) expect(lireListeM7(directe(invalide)).ok).toBe(false);
});

test("limite huit, listes propres et ligne illisible ferment toute la page", () => {
  for (const contenus of [Array(1), [null], [contenu, {}], Array(9).fill(contenu)]) {
    expect(lireListeM7(directe({ ...page, contenus, total: contenus.length })).ok).toBe(false);
  }
  for (const champ of ["contenu_id", "wct_id", "plateforme", "origine_texte"] as const) {
    expect(lireListeM7(directe({ ...page, contenus: [{ ...contenu, [champ]: "" }] })).ok).toBe(false);
  }
  expect(lireListeM7(directe({ ...page, contenus: [{ ...contenu, mots_clics: Array(1) }] })).ok).toBe(false);
  expect(lireListeM7(directe({ ...page, contenus: [{ ...contenu, texte: "x".repeat(6001) }] })).ok).toBe(false);
});

test("la dernière révision conserve son propre ID ; aucune confusion avec un historique du même canal", () => {
  const lu = lireListeM7(directe(page));
  expect(lu.ok && lu.value.items[0].contenu_id).toBe(contenu.contenu_id);
  const ancien = { ...contenu, contenu_id: "ancien-contenu-fictif", revision: 1 };
  expect(lireListeM7(directe({ ...page, total: 2, contenus: [contenu, ancien] })).ok).toBe(false);
  expect(lireListeM7(directe({ ...page, total: 2, contenus: [contenu, contenu] })).ok).toBe(false);
});

test("preuve de marque, statut et décision lus exactement, sans autorité ajoutée", () => {
  for (const malforme of [
    { ...contenu, approval_status: "APPROUVE" }, { ...contenu, fraicheur_marque: "actuelle" },
    { ...contenu, marque_source: { ...marque, revision: 0 } },
    { ...contenu, marque_source: { ...marque, sha256: "z".repeat(64) } },
    { ...contenu, consentement: { ...contenu.consentement, recueilli_par: undefined } },
    { ...contenu, decision: { decision: "APPROVED", par: "owner.fictif" } },
  ]) expect(lireListeM7(directe({ ...page, contenus: [malforme] })).ok).toBe(false);
  expect(lireListeM7(directe({ ...page, marque_courante: { source: "yaml_legacy", revision: null, sha256: "b".repeat(64) },
    contenus: [{ ...contenu, marque_source: null, fraicheur_marque: "preuve_absente" }] })).ok).toBe(true);
});

test("troncature et refus restent fermés et conservent leur code", () => {
  expect(lireListeM7({ ...directe(page), tronque: true })).toMatchObject({ ok: false, code: "reponse_tronquee" });
  expect(lireListeM7({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-IDENTITE", detail: "fictif" } } }))
    .toEqual({ ok: false, code: "REJ-IDENTITE", detail: "fictif" });
  expect(lireListeM7({ ok: false, erreur: "arguments_invalides", details: ["fictif"] }))
    .toEqual({ ok: false, code: "arguments_invalides", detail: "fictif" });
});

test("héritage et getters ne remplacent pas une propriété native ; prototype nul lisible", () => {
  expect(lireListeM7(Object.create(directe(page))).ok).toBe(false);
  expect(lireListeM7(directe(Object.create(page))).ok).toBe(false);
  const getter = jest.fn(() => contenu.texte);
  const ligne = { ...contenu };
  Object.defineProperty(ligne, "texte", { get: getter, enumerable: true });
  expect(lireListeM7(directe({ ...page, contenus: [ligne] })).ok).toBe(false);
  expect(getter).not.toHaveBeenCalled();
  expect(lireListeM7(directe(Object.assign(Object.create(null), page))).ok).toBe(true);
});

// Sous-ensemble inchangé des captures natives de la liste, après parcours public M4 -> M7.
const PROVENANCE_HTTP = {
  "fictif": true,
  "capture": "work/qualification/m7-contract-fixtures-r2.json",
  "capture_sha256": "3d40a740721d23702808269cd1a2bfb80cafd72a2c52afb799c7451e44f8f9ec",
  "head": "47ae120066c1bbe4fa6c97c9b885703525fd0ab0",
  "source": "HTTP MCP réel sur SQLite migrée ; porte Core rejouée en Python ; aucun téléphone/Core natif",
  "sources_sha256": {
    "departments/m07-marketing/src/m7_marketing/outils.py": "b5608010f51a0c05a3774d75f1971da6b0ac408ac3b26258c60f570b50fc8cf1",
    "departments/m07-marketing/src/m7_marketing/usine/service.py": "0386e12ab0bf8de06ec3d97598c59d9adb872e2b03f360db1ec7cce98bbc161a",
    "tests/e2e/test_marketing_admin_appareil.py": "952814cb662646aa50511cf09a5731f11f6fb0d05e793f7309816a3cd8fd43bc",
    "tests/fixtures/harnais_e2e.py": "b8d501122b4de8faa4478b787822606cb2eb610b3f6888cf4eb08d479cd0e978"
  }
} as const;
const CAPTURES_LISTE_NATIVE = {
  "contenus": {
    "outil": "m7_lister_contenus_chantier",
    "args": {
      "limite": 8
    },
    "enveloppe": {
      "ok": true,
      "resultat": {
        "total": 5,
        "marque_courante": {
          "source": "brand_profiles",
          "revision": 1,
          "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
        },
        "contenus": [
          {
            "contenu_id": "9fbe357b-71d3-58ba-aa7b-0d8b40ce20bd",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "demande_temoignage",
            "revision": 1,
            "approval_status": "PROPOSE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Bonjour,\n\nMerci d'avoir confié à Gouttières et Revêtements Synergy (fictif) vos travaux de renovation totale. Accepteriez-vous de nous écrire deux ou trois phrases sur votre expérience ? Nous ne publierons rien sans votre accord explicite.\n\nCordialement,\nL'équipe de Gouttières et Revêtements Synergy (fictif)",
            "origine_texte": "gabarit",
            "mots_clics": [],
            "lien_utm": null,
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          },
          {
            "contenu_id": "678ff211-85b1-52d3-9824-a3376ca88c37",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "video_courte",
            "revision": 1,
            "approval_status": "PROPOSE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Accroche : « Chantier terminé : renovation totale. »\nScène 1 : plan large du résultat final (photo du chantier terminé).\nScène 2 : détail du travail terminé (deuxième photo du chantier).\nScène 3 : le nom Gouttières et Revêtements Synergy (fictif) à l'écran.\nAppel à l'action : « Gouttières et Revêtements Synergy (fictif) : demandez votre soumission. »",
            "origine_texte": "gabarit",
            "mots_clics": [
              "#renovationtotale"
            ],
            "lien_utm": "https://synergy-fictif.example/?utm_source=tiktok&utm_medium=social&utm_campaign=contenu-renovation-totale-2026&utm_content=video_courte-b030027eee60e3c1",
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          },
          {
            "contenu_id": "1d7c42ba-1a42-565c-a0dc-acb559ce5f8b",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "fiche_google",
            "revision": 1,
            "approval_status": "PROPOSE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Nouveau chantier terminé : renovation totale. Rénovation extérieure au Québec, sans surprise. Contactez Gouttières et Revêtements Synergy (fictif) pour demander une soumission.",
            "origine_texte": "gabarit",
            "mots_clics": [
              "#renovationtotale"
            ],
            "lien_utm": "https://synergy-fictif.example/?utm_source=gbp&utm_medium=social&utm_campaign=contenu-renovation-totale-2026&utm_content=fiche_google-6de94d0676e58345",
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          },
          {
            "contenu_id": "fd523882-8508-5c1f-bbeb-5fd671acc59b",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "instagram",
            "revision": 1,
            "approval_status": "PROPOSE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Renovation totale : projet terminé par l'équipe de Gouttières et Revêtements Synergy (fictif).\n\nRénovation extérieure au Québec, sans surprise.\n\nUn projet semblable en tête ? Le lien pour demander une soumission est dans notre bio.",
            "origine_texte": "gabarit",
            "mots_clics": [
              "#renovationtotale"
            ],
            "lien_utm": "https://synergy-fictif.example/?utm_source=instagram&utm_medium=social&utm_campaign=contenu-renovation-totale-2026&utm_content=instagram-029a1630e64b676e",
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          }
        ],
        "decalage": 0,
        "suivant": 4,
        "reste": 1
      }
    }
  },
  "contenus_suite": {
    "outil": "m7_lister_contenus_chantier",
    "args": {
      "limite": 8,
      "decalage": 4
    },
    "enveloppe": {
      "ok": true,
      "resultat": {
        "total": 5,
        "marque_courante": {
          "source": "brand_profiles",
          "revision": 1,
          "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
        },
        "contenus": [
          {
            "contenu_id": "65697c36-ab61-5bae-a427-6cd4452683d1",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "facebook",
            "revision": 1,
            "approval_status": "PROPOSE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Chantier terminé : renovation totale.\n\nRénovation extérieure au Québec, sans surprise.\n\nL'équipe de Gouttières et Revêtements Synergy (fictif) vient de terminer ce projet. Vous avez un projet semblable ? Écrivez-nous pour demander une soumission.",
            "origine_texte": "gabarit",
            "mots_clics": [
              "#renovationtotale"
            ],
            "lien_utm": "https://synergy-fictif.example/?utm_source=facebook&utm_medium=social&utm_campaign=contenu-renovation-totale-2026&utm_content=facebook-b10bb28278e6d2b3",
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          }
        ],
        "decalage": 4,
        "suivant": null,
        "reste": 0
      }
    }
  },
  "consentement_retire": {
    "outil": "m7_lister_contenus_chantier",
    "args": {
      "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
      "statut": "CONSENTEMENT_RETIRE",
      "limite": 8
    },
    "enveloppe": {
      "ok": true,
      "resultat": {
        "total": 5,
        "marque_courante": {
          "source": "brand_profiles",
          "revision": 1,
          "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
        },
        "contenus": [
          {
            "contenu_id": "9fbe357b-71d3-58ba-aa7b-0d8b40ce20bd",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "demande_temoignage",
            "revision": 1,
            "approval_status": "CONSENTEMENT_RETIRE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Bonjour,\n\nMerci d'avoir confié à Gouttières et Revêtements Synergy (fictif) vos travaux de renovation totale. Accepteriez-vous de nous écrire deux ou trois phrases sur votre expérience ? Nous ne publierons rien sans votre accord explicite.\n\nCordialement,\nL'équipe de Gouttières et Revêtements Synergy (fictif)",
            "origine_texte": "gabarit",
            "mots_clics": [],
            "lien_utm": null,
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          },
          {
            "contenu_id": "678ff211-85b1-52d3-9824-a3376ca88c37",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "video_courte",
            "revision": 1,
            "approval_status": "CONSENTEMENT_RETIRE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Accroche : « Chantier terminé : renovation totale. »\nScène 1 : plan large du résultat final (photo du chantier terminé).\nScène 2 : détail du travail terminé (deuxième photo du chantier).\nScène 3 : le nom Gouttières et Revêtements Synergy (fictif) à l'écran.\nAppel à l'action : « Gouttières et Revêtements Synergy (fictif) : demandez votre soumission. »",
            "origine_texte": "gabarit",
            "mots_clics": [
              "#renovationtotale"
            ],
            "lien_utm": "https://synergy-fictif.example/?utm_source=tiktok&utm_medium=social&utm_campaign=contenu-renovation-totale-2026&utm_content=video_courte-b030027eee60e3c1",
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          },
          {
            "contenu_id": "1d7c42ba-1a42-565c-a0dc-acb559ce5f8b",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "fiche_google",
            "revision": 1,
            "approval_status": "CONSENTEMENT_RETIRE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Nouveau chantier terminé : renovation totale. Rénovation extérieure au Québec, sans surprise. Contactez Gouttières et Revêtements Synergy (fictif) pour demander une soumission.",
            "origine_texte": "gabarit",
            "mots_clics": [
              "#renovationtotale"
            ],
            "lien_utm": "https://synergy-fictif.example/?utm_source=gbp&utm_medium=social&utm_campaign=contenu-renovation-totale-2026&utm_content=fiche_google-6de94d0676e58345",
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          },
          {
            "contenu_id": "fd523882-8508-5c1f-bbeb-5fd671acc59b",
            "wct_id": "b6638aeee462131d517e97e44bfde75556b69bbb990bd100f3beeb66889adcc6",
            "plateforme": "instagram",
            "revision": 1,
            "approval_status": "CONSENTEMENT_RETIRE",
            "exporte": false,
            "marque_source": {
              "source": "brand_profiles",
              "revision": 1,
              "sha256": "e8a4baf1710e05452062f1dae88b7dcfe49b76d23eddee119eb5a199f087de4f"
            },
            "fraicheur_marque": "courante",
            "texte": "Renovation totale : projet terminé par l'équipe de Gouttières et Revêtements Synergy (fictif).\n\nRénovation extérieure au Québec, sans surprise.\n\nUn projet semblable en tête ? Le lien pour demander une soumission est dans notre bio.",
            "origine_texte": "gabarit",
            "mots_clics": [
              "#renovationtotale"
            ],
            "lien_utm": "https://synergy-fictif.example/?utm_source=instagram&utm_medium=social&utm_campaign=contenu-renovation-totale-2026&utm_content=instagram-029a1630e64b676e",
            "avertissements": [
              "ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local"
            ],
            "decision": null,
            "consentement": {
              "recueilli_par": "etienne",
              "recueilli_le": "2026-09-15T15:05:00+00:00",
              "version_texte": "consentement-client-fr-CA-v1-fictif"
            }
          }
        ],
        "decalage": 0,
        "suivant": 4,
        "reste": 1
      }
    }
  },
  "identite_revoquee_2": {
    "outil": "m7_lister_contenus_chantier",
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
} as const;

test.each(["contenus", "contenus_suite", "consentement_retire"] as const)(
  "capture HTTP MCP native %s directement lisible, texte et IDs exacts", nom => {
    expect(PROVENANCE_HTTP.fictif).toBe(true);
    expect(PROVENANCE_HTTP.capture_sha256).toMatch(/^[0-9a-f]{64}$/);
    const capture = CAPTURES_LISTE_NATIVE[nom];
    const r = capture.enveloppe.resultat;
    const lu = lireListeM7(JSON.parse(JSON.stringify(capture.enveloppe)));
    expect(lu).toEqual({ ok: true, value: { items: r.contenus, total: r.total, decalage: r.decalage,
      suivant: r.suivant, reste: r.reste, marqueCourante: r.marque_courante } });
  },
);
test("capture HTTP : budget natif donne 4/5, page suivante exacte, refus identité fermé", () => {
  const page = CAPTURES_LISTE_NATIVE.contenus.enveloppe;
  const suite = CAPTURES_LISTE_NATIVE.contenus_suite.enveloppe;
  expect(page.resultat.contenus).toHaveLength(4);
  expect(page.resultat.suivant).toBe(4);
  expect(suite.resultat.decalage).toBe(4);
  expect(suite.resultat.contenus).toHaveLength(1);
  expect(suite.resultat.suivant).toBeNull();
  const refusal = CAPTURES_LISTE_NATIVE.identite_revoquee_2.enveloppe;
  expect(lireListeM7(refusal)).toEqual({ ok: false, code: refusal.resultat.verdict.code,
    detail: refusal.resultat.verdict.detail });
});

test("lecture d'une capture native gelée, sans mutation ni dépendance à un objet modifiable", () => {
  const enveloppe = CAPTURES_LISTE_NATIVE.contenus.enveloppe;
  const avant = JSON.stringify(enveloppe);
  Object.freeze(enveloppe);
  Object.freeze(enveloppe.resultat);
  Object.freeze(enveloppe.resultat.contenus);
  for (const ligne of enveloppe.resultat.contenus) Object.freeze(ligne);
  expect(lireListeM7(enveloppe).ok).toBe(true);
  expect(JSON.stringify(enveloppe)).toBe(avant);
});
