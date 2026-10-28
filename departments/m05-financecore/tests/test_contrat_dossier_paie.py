"""Le contrat versionné du dossier de paie décrit exactement ce que le code fait (pas de dérive documentaire)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from m5_financecore import dossier_paie_preparatoire as d
from m5_financecore import journal_dossiers_paie as journal

sys.path.insert(0, str(Path(__file__).resolve().parent))
FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
CONTRAT = yaml.safe_load((RACINE / "contracts" / "dossier_paie_preparatoire.v1.yaml").read_text(encoding="utf-8"))
SOURCES = [
    RACINE / "src" / "m5_financecore" / f"{nom}.py"
    for nom in (
        "dossier_paie_preparatoire",
        "cotisations_employeur_2026",
        "journal_dossiers_paie",
        "service_dossier_paie",
        "export_paie_preparatoire",
        "outils_paie_dossier",
    )
]


def test_codes_de_verdict_utilises_par_le_code_sont_tous_dans_le_contrat():
    utilises = set()
    for fichier in SOURCES:
        texte = fichier.read_text(encoding="utf-8")
        utilises |= set(re.findall(r'(?:refus|_lever|_refus|JournalErreur)\(\s*"([A-Z][A-Z-]+)"', texte))
    assert utilises, "aucun code détecté : le motif de recherche est périmé"
    assert utilises <= set(CONTRAT["verdicts"]["codes"]), sorted(utilises - set(CONTRAT["verdicts"]["codes"]))
    assert CONTRAT["verdicts"]["prefixe"] == "REJ-DOSSIER-PAIE-"


def test_schemas_modes_et_domaine_alignes_sur_le_code():
    assert CONTRAT["schemas"]["entrees"] == d.SCHEMA_ENTREES
    assert CONTRAT["schemas"]["version"] == d.SCHEMA_VERSION and CONTRAT["schemas"]["calcul"] == d.SCHEMA_CALCUL
    assert CONTRAT["statut"] == d.MODE and CONTRAT["qualification_regles"] == d.QUALIFICATION
    assert CONTRAT["domaine"]["annee"] == d.ANNEE and CONTRAT["domaine"]["periodes_annuelles"] == d.PERIODES_ANNUELLES
    assert CONTRAT["domaine"]["jours_par_periode"] == d.JOURS_PERIODE
    assert set(CONTRAT["etats_calcul"]) == set(d._ETATS_CALCUL)
    assert set(CONTRAT["etats_poste"]) == {"CALCULE", "DECLARE", "NON_APPLICABLE", "INCONNU"}
    assert set(CONTRAT["separation_des_donnees"]["cumuls"].split("origines ")[1].split(" (")[0].split(", ")) == set(
        d._ORIGINES_CUMUL
    )


def test_evenements_types_et_decisions_alignes_sur_le_journal():
    assert set(CONTRAT["evenements_journal"]) == set(journal._TYPES)
    assert set(CONTRAT["types_version"]) == set(journal._TYPES_VERSION)
    assert set(CONTRAT["decisions_revue"]) == set(journal._DECISIONS_REVUE)


def test_totaux_conditionnels_alignes_sur_la_matrice():
    from fixtures_dossier_paie import ADMISSION_OK, entrees

    valides, _ = d.valider_entrees(entrees())
    calcul = d.composer(valides, {"brut_brouillon": "1002.00"}, ADMISSION_OK)
    assert set(CONTRAT["totaux_conditionnels"]) == set(calcul["totaux"])
    assert {p["etat"] for p in calcul["matrice"]} <= set(CONTRAT["etats_poste"])


def test_statuts_http_du_contrat_alignes_sur_la_console():
    from opsys.console import paie_dossier_ui

    declares = {}
    for statut, codes in CONTRAT["statuts_http"].items():
        for code in [codes] if isinstance(codes, str) else codes:
            declares[code] = statut
    assert declares == paie_dossier_ui._STATUTS
