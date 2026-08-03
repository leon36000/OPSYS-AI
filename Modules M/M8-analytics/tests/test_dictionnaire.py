import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

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


def test_compiler_dictionnaire_reel_depot_contient_les_metriques_m7():
    resultat, erreurs = dictionnaire.compiler_dictionnaire(_MODULES_M)

    assert erreurs == []
    assert set(resultat["M7-marketing"]) == {
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
    assert resultat["M7-marketing"]["m7_cpl"] == {
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
    resultat, erreurs = dictionnaire.compiler_dictionnaire(_MODULES_M)

    assert erreurs == []
    for module in {
        "M1-front-office",
        "M2-revenue-crm",
        "M3-estimation",
        "M4-field-ops",
        "M5-financecore",
        "M6-material-control",
        "M8-analytics",
        "M9-strategic-intelligence",
        "M10-memoire",
    }:
        assert module not in resultat


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
