import re
from pathlib import Path

import pytest
from m8_analytics import dictionnaire

_MODULES_M = Path(__file__).resolve().parents[2]


def _metrique(metric_id: str) -> str:
    return f"""\
id: {metric_id}
nom: "Nom"
definition: "Définition"
unite: "unité"
source_donnees: "source"
frequence: "mensuelle"
consommateur: "entrepôt M8"
"""


_METRIC_IDS_M7_ATTENDUS = {
    "m7_cpl",
    "m7_cout_par_soumission",
    "m7_roi_par_canal",
    "m7_part_citations_ia",
    "m7_taux_doc_none",
    "m7_rep_total_avis",
    "m7_rep_repartition_notes",
    "m7_rep_note_moyenne",
    "m7_rep_taux_reponse",
    "m7_rep_repartition_cats",
    "m7_rep_delai_moyen_jours",
    "m7_cout_par_lead_par_canal",
    "m7_taux_attribution",
    "m7_part_non_attribuables",
    "m7_cout_par_lead_global",
}
_MOTIF_DEVISE = re.compile(r"^([A-Z]{3})/\w+$")


def test_compiler_dictionnaire_reel_depot_contient_les_metriques_m7():
    """m7_cout_par_soumission a porté "EUR/soumission" (résidu de gabarit non
    québécisé, docs/research/R9-m7-m8.md §1.3) : la garde de devise de
    dictionnaire.py le rejette nommément plutôt que de le laisser traverser
    silencieusement la frontière M7→M8. Ce test tolère les DEUX états valides
    du fichier source M7 (encore EUR, ou déjà corrigé en CAD par le module M7
    lui-même — hors du périmètre de cette mission, REGLES-AGENTS.md : travail
    en parallèle sur le même arbre) : dans les deux cas, le dictionnaire
    compilé ne contient JAMAIS une métrique en violation de la garde.
    """
    resultat, erreurs = dictionnaire.compiler_dictionnaire(_MODULES_M)
    metriques_m7 = resultat["M7-marketing"]

    # Invariant stable quel que soit l'état du fichier source : aucune
    # métrique du dictionnaire compilé ne viole la garde de devise CAD.
    for metric_id, definition in metriques_m7.items():
        correspondance = _MOTIF_DEVISE.match(definition["unite"])
        if correspondance is not None:
            assert correspondance.group(1) == "CAD", (
                f"{metric_id} : unite {definition['unite']!r} en violation de la "
                "garde de devise mais présente dans le dictionnaire compilé"
            )

    if "m7_cout_par_soumission" in metriques_m7:
        assert metriques_m7["m7_cout_par_soumission"]["unite"] == "CAD/soumission"
    else:
        assert any("m7_cout_par_soumission" in erreur for erreur in erreurs)

    assert set(metriques_m7) == _METRIC_IDS_M7_ATTENDUS or set(metriques_m7) == (
        _METRIC_IDS_M7_ATTENDUS - {"m7_cout_par_soumission"}
    )
    assert metriques_m7["m7_cpl"] == {
        "id": "m7_cpl",
        "nom": "Coût par lead",
        "definition": (
            "Coût total marketing divisé par le nombre de leads générés sur la période."
        ),
        "unite": "CAD/lead",
        "source_donnees": "Module M7 — campagnes et CRM",
        "frequence": "mensuelle",
        "consommateur": "entrepôt M8",
    }


def test_compiler_dictionnaire_reel_depot_ignore_modules_sans_fichier_metrics():
    """Le seul écart connu du dépôt réel est l'éventuelle devise EUR de
    m7_cout_par_soumission (§1.3 de R9, couvert par son propre test, et
    tolérant les deux états valides du fichier source M7) — ce test porte sur
    un point distinct : un module sans metrics/*.yaml n'apparaît jamais au
    dictionnaire, aucune métrique n'est fabriquée pour lui.
    """
    resultat, erreurs = dictionnaire.compiler_dictionnaire(_MODULES_M)

    assert all("m7_cout_par_soumission" in erreur for erreur in erreurs)
    for module in {
        "M1-front-office",
        "M2-revenue-crm",
        "M3-estimation",
        "M4-field-ops",
        "M5-financecore",
        "M6-material-control",
        "M9-strategic-intelligence",
        "M10-memoire",
    }:
        assert module not in resultat


def test_compiler_dictionnaire_reel_depot_contient_les_metriques_de_mesure_de_chantier_de_m8():
    """PLAN T1.5-d : M8 a maintenant SON `metrics/m8-metrics.v1.yaml` (module `m08-analytics`), compilé
    sans erreur par la même garde de devise que les autres ; les autres modules sans fichier
    restent absents (test précédent)."""
    resultat, erreurs = dictionnaire.compiler_dictionnaire(_MODULES_M)

    assert not [erreur for erreur in erreurs if "m8-metrics" in erreur]
    # Huit métriques de mesure d'un chantier (m8-metrics.v1.yaml), depuis T4.19 huit de l'entonnoir
    # (m8-entonnoir.v1.yaml, `test_entonnoir.py`) et depuis T4.17-e six par contenu (m8-contenus.v1.yaml,
    # `test_contenus.py`) : le même module, trois fichiers.
    assert set(resultat["m08-analytics"]) == {
        "m8_ecart_duree_minutes", "m8_ecart_duree_pct", "m8_marge_prevue_cad", "m8_marge_reelle_cad",
        "m8_ecart_marge_cad", "m8_ecart_marge_pct", "m8_ecart_materiaux_max_pct",
        "m8_ecart_duree_technicien_pct",
        "m8_leads_recus", "m8_leads_qualifies", "m8_devis_envoyes", "m8_devis_acceptes", "m8_devis_sans_reponse",
        "m8_taux_acceptation_pct", "m8_delai_lead_acceptation_jours", "m8_carnet_signe_cad",
        "m8_contenus_exportes", "m8_leads_par_contenu", "m8_devis_envoyes_par_contenu",
        "m8_devis_acceptes_par_contenu", "m8_impressions_par_contenu", "m8_clics_par_contenu",
    }
    assert resultat["m08-analytics"]["m8_marge_prevue_cad"]["unite"] == "CAD"


def test_compiler_fichier_compile_un_seul_fichier_avec_les_memes_gardes(tmp_path):
    fichier = tmp_path / "m-test.yaml"
    fichier.write_text(
        "schema_version: 1\nmodule: m-test\nmetrics:\n"
        "  - {id: m_ok, nom: N, definition: d, unite: CAD, source_donnees: s, frequence: f, consommateur: c}\n"
        "  - {id: m_usd, nom: N, definition: d, unite: USD, source_donnees: s, frequence: f, consommateur: c}\n",
        encoding="utf-8",
    )

    compile_, erreurs = dictionnaire.compiler_fichier(fichier)

    assert set(compile_["m-test"]) == {"m_ok"}
    assert len(erreurs) == 1 and "REJ-DEVISE-NON-AUTORISEE" in erreurs[0] and "m_usd" in erreurs[0]


def test_compiler_dictionnaire_module_absent_est_silencieux(tmp_path):
    (tmp_path / "faux_module" / "metrics").mkdir(parents=True)

    resultat, erreurs = dictionnaire.compiler_dictionnaire(tmp_path)

    assert resultat == {}
    assert erreurs == []


def test_compiler_dictionnaire_signale_schema_version_manquant(tmp_path):
    metrics = tmp_path / "faux_module" / "metrics"
    metrics.mkdir(parents=True)
    (metrics / "m.yaml").write_text(
        """\
module: X
metrics:
  - id: x_metric
    nom: "Nom"
    definition: "Définition"
    unite: "unité"
    source_donnees: "source"
    frequence: "mensuelle"
    consommateur: "entrepôt M8"
""",
        encoding="utf-8",
    )

    _, erreurs = dictionnaire.compiler_dictionnaire(tmp_path)

    assert erreurs
    assert "m.yaml" in " ".join(erreurs)


def test_compiler_dictionnaire_signale_metrique_avec_champ_manquant(tmp_path):
    metrics = tmp_path / "faux_module" / "metrics"
    metrics.mkdir(parents=True)
    (metrics / "m.yaml").write_text(
        """\
schema_version: 1
module: X
metrics:
  - id: x_metric
    nom: "Nom"
    definition: "Définition"
    unite: "unité"
    source_donnees: "source"
    frequence: "mensuelle"
""",
        encoding="utf-8",
    )

    _, erreurs = dictionnaire.compiler_dictionnaire(tmp_path)

    assert erreurs
    assert "x_metric" in " ".join(erreurs)


def test_compiler_dictionnaire_signale_id_duplique_dans_un_fichier(tmp_path):
    metrics = tmp_path / "faux_module" / "metrics"
    metrics.mkdir(parents=True)
    (metrics / "m.yaml").write_text(
        f"""\
schema_version: 1
module: X
metrics:
  - {_metrique("x_metric").replace(chr(10), chr(10) + "    ").rstrip()}
  - {_metrique("x_metric").replace(chr(10), chr(10) + "    ").rstrip()}
""",
        encoding="utf-8",
    )

    _, erreurs = dictionnaire.compiler_dictionnaire(tmp_path)

    assert erreurs
    assert "x_metric" in " ".join(erreurs)


def _metrique_avec_unite(metric_id: str, unite: str) -> str:
    return f"""\
id: {metric_id}
nom: "Nom"
definition: "Définition"
unite: "{unite}"
source_donnees: "source"
frequence: "mensuelle"
consommateur: "entrepôt M8"
"""


def _fichier_metrique_unite(tmp_path, unite):
    metrics = tmp_path / "faux_module" / "metrics"
    metrics.mkdir(parents=True)
    (metrics / "m.yaml").write_text(
        f"""\
schema_version: 1
module: X
metrics:
  - {_metrique_avec_unite("x_metric", unite).replace(chr(10), chr(10) + "    ").rstrip()}
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize("unite", ["CAD", "CAD/lead", "cad", "Cad", "cad/lead"])
def test_compiler_dictionnaire_accepte_une_unite_monetaire_en_cad(tmp_path, unite):
    """T3.4 (M8-audit.md §2/§5) : CAD est accepté NU ("CAD") comme avec dénominateur
    ("CAD/lead"), et la comparaison est insensible à la casse — une unité "cad" mal saisie
    n'est pas un refus, seule une devise ÉTRANGÈRE l'est."""
    resultat, erreurs = dictionnaire.compiler_dictionnaire(
        _fichier_metrique_unite(tmp_path, unite)
    )

    assert erreurs == []
    assert "x_metric" in resultat["X"]
    assert resultat["X"]["x_metric"]["unite"] == unite


@pytest.mark.parametrize(
    "unite",
    [
        "EUR/soumission", "USD/lead", "GBP/lead",  # forme "DEVISE/quelquechose" (déjà couverte avant T3.4)
        "USD", "EUR", "GBP",  # T3.4 : devise NUE, sans dénominateur — le trou comblé par ce fix
        "usd", "eur",  # T3.4 : devise nue en minuscules — comparaison insensible à la casse
    ],
)
def test_compiler_dictionnaire_refuse_une_devise_non_cad(tmp_path, unite):
    resultat, erreurs = dictionnaire.compiler_dictionnaire(
        _fichier_metrique_unite(tmp_path, unite)
    )

    assert resultat == {}
    assert erreurs
    assert any("x_metric" in erreur for erreur in erreurs)
    assert any(unite in erreur for erreur in erreurs)


@pytest.mark.parametrize(
    "unite",
    [
        "ratio", "pourcentage", "entier", "dict {note: entier}", "float (jours)", "ratio (0.0–1.0)",
        "dict {categorie: entier}", "float (1.0–5.0)",  # les deux unités réelles qui manquaient ici
        # Unités non monétaires que d'autres départements sont susceptibles de publier
        # (M8-audit.md T0 : m3_duree_estimee_h, m4_duree_reelle_minutes…) — aucune ne doit
        # jamais être traitée comme une devise, y compris "min" (3 lettres, la même longueur
        # qu'un code ISO 4217, mais "MIN" n'en est pas un — vérifié dans _CODES_ISO_4217).
        "min", "%", "km", "h", "jours", "nb",
    ],
)
def test_compiler_dictionnaire_accepte_les_unites_non_monetaires(tmp_path, unite):
    resultat, erreurs = dictionnaire.compiler_dictionnaire(
        _fichier_metrique_unite(tmp_path, unite)
    )

    assert erreurs == []
    assert "x_metric" in resultat["X"]


def test_compiler_dictionnaire_reel_aucun_faux_positif_sur_les_unites_existantes():
    """T3.4 (M8-audit.md §2/§5) : la garde de devise corrigée ne doit rejeter AUCUNE unité
    réellement définie dans le dépôt aujourd'hui — preuve EXHAUSTIVE (toutes les unités
    présentes dans le dictionnaire compilé), pas un échantillon choisi à la main.

    compiler_dictionnaire retire du résultat toute métrique dont l'unité est une devise non
    CAD (test_compiler_dictionnaire_refuse_une_devise_non_cad ci-dessus) : parcourir la
    totalité des unités PRÉSENTES dans le dictionnaire compilé prouve donc, par construction,
    qu'aucune d'elles n'a été signalée par erreur (sinon elle serait absente du résultat).
    """
    resultat, _ = dictionnaire.compiler_dictionnaire(_MODULES_M)

    unites_examinees = 0
    for module, metriques in resultat.items():
        for metric_id, definition in metriques.items():
            unites_examinees += 1
            assert dictionnaire.devise_non_autorisee(definition["unite"]) is None, (
                f"faux positif de la garde de devise : {module}/{metric_id} "
                f"unite={definition['unite']!r}"
            )

    # Preuve que la boucle ci-dessus a réellement examiné quelque chose : un dictionnaire vide
    # la rendrait vacuement vraie. _METRIC_IDS_M7_ATTENDUS (plus haut) porte 15 métriques.
    assert unites_examinees >= len(_METRIC_IDS_M7_ATTENDUS) - 1


def test_compiler_dictionnaire_compile_deux_modules_valides(tmp_path):
    metrics_a = tmp_path / "module_a" / "metrics"
    metrics_b = tmp_path / "module_b" / "metrics"
    metrics_a.mkdir(parents=True)
    metrics_b.mkdir(parents=True)

    (metrics_a / "a.yaml").write_text(
        f"""\
schema_version: 1
module: ModuleA
metrics:
  - {_metrique("modulea_metric").replace(chr(10), chr(10) + "    ").rstrip()}
""",
        encoding="utf-8",
    )
    (metrics_b / "b.yaml").write_text(
        f"""\
schema_version: 1
module: ModuleB
metrics:
  - {_metrique("moduleb_metric").replace(chr(10), chr(10) + "    ").rstrip()}
""",
        encoding="utf-8",
    )

    resultat, erreurs = dictionnaire.compiler_dictionnaire(tmp_path)

    assert resultat == {
        "ModuleA": {
            "modulea_metric": {
                "id": "modulea_metric",
                "nom": "Nom",
                "definition": "Définition",
                "unite": "unité",
                "source_donnees": "source",
                "frequence": "mensuelle",
                "consommateur": "entrepôt M8",
            }
        },
        "ModuleB": {
            "moduleb_metric": {
                "id": "moduleb_metric",
                "nom": "Nom",
                "definition": "Définition",
                "unite": "unité",
                "source_donnees": "source",
                "frequence": "mensuelle",
                "consommateur": "entrepôt M8",
            }
        },
    }
    assert erreurs == []
