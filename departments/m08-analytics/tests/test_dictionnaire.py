import re
import sys
from pathlib import Path

import pytest

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


def test_compiler_dictionnaire_accepte_une_unite_monetaire_en_cad(tmp_path):
    resultat, erreurs = dictionnaire.compiler_dictionnaire(
        _fichier_metrique_unite(tmp_path, "CAD/lead")
    )

    assert erreurs == []
    assert "x_metric" in resultat["X"]


@pytest.mark.parametrize("unite", ["EUR/soumission", "USD/lead", "GBP/lead"])
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
    ["ratio", "pourcentage", "entier", "dict {note: entier}", "float (jours)", "ratio (0.0–1.0)"],
)
def test_compiler_dictionnaire_accepte_les_unites_non_monetaires(tmp_path, unite):
    resultat, erreurs = dictionnaire.compiler_dictionnaire(
        _fichier_metrique_unite(tmp_path, unite)
    )

    assert erreurs == []
    assert "x_metric" in resultat["X"]


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
