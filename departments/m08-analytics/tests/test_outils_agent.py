"""Capacités d'agent de M8 : contrat des outils et chaîne de rapport composée."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics.outils import outils, rapport_metriques

from opsys.departements import lire_manifeste
from opsys.outils import executer

_DEFINITION = {
    "id": "m_cpl",
    "nom": "Coût par lead",
    "definition": "Coût total marketing divisé par le nombre de leads.",
    "unite": "CAD/lead",
    "source_donnees": "module de test",
    "frequence": "mensuelle",
    "consommateur": "entrepôt M8",
}


def _dictionnaire(module_source="M-test-outils-agent"):
    return {module_source: {"m_cpl": _DEFINITION}}


def _snapshot(module_source, horodatage, valeur):
    return {"module_source": module_source, "horodatage": horodatage, "valeurs": {"m_cpl": valeur}}


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m8_rapport_metriques"
    assert all(nom.startswith("m8_") for nom in noms)


def test_rapport_metriques_complet_porte_provenance_et_aucun_signal_sous_le_seuil():
    module_source = "M-nominal"
    reponse = rapport_metriques(
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", "42.5"),
        metric_ids=["m_cpl"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=3,
    )

    assert reponse["etape"] == "complet" and reponse["accepte"] is True
    rapport = reponse["rapport"]
    assert rapport["metriques"][0]["metric_id"] == "m_cpl"
    assert rapport["metriques"][0]["valeur"] == 42.5
    assert rapport["metriques"][0]["n"] == 1
    # Un seul point d'historique < n_minimal=3 : le signal est DONNEES_INSUFFISANTES,
    # donc absent des signaux (m8_produire_digest_quotidien le filtrerait de toute façon).
    assert rapport["signaux"][0]["type_signal"] == "DONNEES_INSUFFISANTES"


def test_rapport_metriques_snapshot_refuse_bloque_avant_ecriture():
    module_source = "M-refuse"
    reponse = rapport_metriques(
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", 42.5),  # valeur NUMÉRIQUE
        metric_ids=["m_cpl"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=3,
    )

    assert reponse["etape"] == "validation" and reponse["accepte"] is False
    assert reponse["verdict"] == "REJ-SNAPSHOT-VALEUR-NON-TEXTE"


def test_rapport_metriques_metric_id_non_declare_est_bloque():
    module_source = "M-metric-inconnu"
    reponse = rapport_metriques(
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", "1"),
        metric_ids=["m_inconnu"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=3,
    )

    assert reponse["etape"] == "definition" and reponse["accepte"] is False
    assert "m_inconnu" in reponse["verdict"]


def test_rapport_metriques_detecte_un_signal_xmr_hors_limite_apres_plusieurs_ingestions():
    module_source = "M-xmr"
    dictionnaire = _dictionnaire(module_source)
    horodatages = [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
        "2026-01-04T00:00:00Z",
        "2026-01-05T00:00:00Z",
    ]
    # Même série que test_xmr.py::test_detecter_signal_retourne_signal_limite_superieure...
    # (4 points stables puis un saut) : moyenne=18, amplitude_moyenne=10,
    # limite_haute=18+2.66*10=44.6 < 50 → HORS_LIMITE_SUPERIEURE garanti.
    valeurs = ["10", "10", "10", "10", "50"]

    for horodatage, valeur in zip(horodatages[:-1], valeurs[:-1]):
        rapport_metriques(
            dictionnaire=dictionnaire,
            snapshot=_snapshot(module_source, horodatage, valeur),
            metric_ids=["m_cpl"],
            horodatage_reference=horodatage,
            n_minimal=3,
        )

    reponse = rapport_metriques(
        dictionnaire=dictionnaire,
        snapshot=_snapshot(module_source, horodatages[-1], valeurs[-1]),
        metric_ids=["m_cpl"],
        horodatage_reference=horodatages[-1],
        n_minimal=3,
    )

    signaux = reponse["rapport"]["signaux"]
    assert signaux and signaux[0]["type_signal"] == "HORS_LIMITE_SUPERIEURE"
    assert signaux[0]["n"] == 5


def test_rapport_metriques_role_sans_liste_est_refus_metier_via_executer():
    module_source = "M-role-refuse"
    outil = next(o for o in outils() if o.nom == "m8_rapport_metriques")

    reponse = executer(
        outil,
        {
            "dictionnaire": _dictionnaire(module_source),
            "snapshot": _snapshot(module_source, "2026-01-04T00:00:00Z", "1"),
            "metric_ids": ["m_cpl"],
            "horodatage_reference": "2026-01-04T00:00:00Z",
            "n_minimal": 1,
            "role": "terrain",
        },
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"


def test_snapshot_avec_devise_non_cad_refuse_par_le_dictionnaire_reel_et_par_l_outil():
    """Bout en bout, contre le dépôt réel : une devise non CAD compilée par
    m8_compiler_dictionnaire ne peut ensuite jamais être ingérée pour cette métrique
    (elle est absente du dictionnaire compilé, donc traitée comme non déclarée).
    """
    depart = Path(__file__).resolve().parents[2]  # departments/
    outil_dictionnaire = next(o for o in outils() if o.nom == "m8_compiler_dictionnaire")

    reponse = executer(outil_dictionnaire, {"racine_modules": str(depart)})

    assert reponse["ok"] is True
    dictionnaire_reel = reponse["resultat"]["dictionnaire"]
    metriques_m7 = dictionnaire_reel.get("M7-marketing", {})
    for metric_id, definition in metriques_m7.items():
        assert not definition["unite"].startswith("EUR/"), metric_id


def test_n_minimal_de_mauvais_type_refuse_par_le_schema():
    outil = next(o for o in outils() if o.nom == "m8_detecter_signal_xmr")
    reponse = executer(outil, {"metric_id": "m", "valeurs_historiques": [], "n_minimal": "trois"})
    assert reponse["erreur"] == "arguments_invalides"


def test_construire_rapport_role_sans_liste_via_executer_est_refus_metier():
    outil = next(o for o in outils() if o.nom == "m8_construire_rapport")
    reponse = executer(
        outil,
        {"metriques": [], "signaux": [], "role": "admin", "metric_ids_autorises": None},
    )
    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"
