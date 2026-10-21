"""Le budget du répartiteur public borne les effets du vrai consommateur M8.

Une base privée, deux WCT fictifs et le département M8 canonique lu sans
modification. La CLI utilise ce manifeste par OPSYS_DEPARTMENTS.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from m8_analytics import registre
from sqlalchemy import event, func, select

from opsys import cli, evenements, stockage
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_RECUS

DEPARTEMENT = "m08-analytics"
ZERO = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}


def _wct(ident):
    return {
        "wct_id": ident, "intervention_id": "intervention-fictive",
        "lead_id": "lead-fictif", "technicien_id": "technicien-fictif",
        "horodatage_completion": "2026-10-14T12:00:00Z", "fix_gps_completion": {},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "a" * 64, "consommateurs_cibles": ["M8"],
        "devis_id": None, "statut": "completed_verified",
    }


@pytest.fixture
def base_et_departement(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    racine = tmp_path / "departments"
    dossier = racine / DEPARTEMENT
    racine.mkdir()
    origine = Path(__file__).resolve().parents[1] / "departments" / DEPARTEMENT
    # Le manifeste exige ses skills : utiliser la Source complète immuable,
    # plutôt qu'une copie partielle qui perd ces dépendances déclarées.
    dossier.symlink_to(origine, target_is_directory=True)
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine))
    stockage.migrer()
    for ident in ("budget-wct-fictif-1", "budget-wct-fictif-2"):
        evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(ident), evenement_id=ident)
    yield charger_departements()
    stockage.liberer()


def _etat_natif():
    with stockage.transaction() as cnx:
        recus = cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS)).scalar_one()
    chaine = registre.RegistreSnapshots(stockage.maillons(DEPARTEMENT, "snapshots"))
    assert chaine.valider_chaine() == (True, "")
    return {
        "recus": recus, "snapshots": len(chaine.lire()),
        "faits": len(stockage.maillons(DEPARTEMENT, "faits_chantier")),
    }


def _sans_sql(appel):
    moteur = stockage.moteur()
    instructions = []

    def observer(cnx, curseur, instruction, parametres, contexte, executemany):
        instructions.append(instruction)

    event.listen(moteur, "before_cursor_execute", observer)
    try:
        resultat = appel()
    finally:
        event.remove(moteur, "before_cursor_execute", observer)
    assert instructions == [], "budget nul/invalide a accédé à la base"
    return resultat


@pytest.mark.parametrize("par_cli", [False, True], ids=["api", "cli"])
def test_budget_zero_ne_livre_ne_lit_et_ne_modifie_rien(base_et_departement, par_cli, capsys):
    def appeler():
        if par_cli:
            assert cli.main(["evenements", "repartir", "--limite", "0"]) == 0
            return json.loads(capsys.readouterr().out)
        return evenements.repartir(base_et_departement, limite=0)

    assert _sans_sql(appeler) == ZERO
    stockage.liberer()
    assert _etat_natif() == {"recus": 0, "snapshots": 0, "faits": 0}
    assert evenements.charge_publiee("m4.travaux_termines", "budget-wct-fictif-1") == _wct("budget-wct-fictif-1")


@pytest.mark.parametrize(
    "limite", [-1, 1.5, True, None, "1"],
    ids=["negative", "fraction", "booleen", "absence", "texte"],
)
def test_budget_invalide_refuse_avant_sql_et_consommateurs(base_et_departement, monkeypatch, limite):
    dep = base_et_departement[DEPARTEMENT]

    def chargement_interdit(self):
        pytest.fail("budget invalide a chargé les consommateurs")

    monkeypatch.setattr(type(dep), "charger_consommateurs", chargement_interdit)

    def appeler():
        with pytest.raises(ValueError, match="limite.*entier"):
            evenements.repartir(base_et_departement, limite=limite)

    _sans_sql(appeler)
    stockage.liberer()
    assert _etat_natif() == {"recus": 0, "snapshots": 0, "faits": 0}


def test_budget_cli_negatif_refuse_sans_effets(base_et_departement):
    def appeler():
        with pytest.raises(ValueError, match="limite.*entier"):
            cli.main(["evenements", "repartir", "--limite", "-1"])

    _sans_sql(appeler)
    stockage.liberer()
    assert _etat_natif() == {"recus": 0, "snapshots": 0, "faits": 0}


@pytest.mark.parametrize("par_cli", [False, True], ids=["api", "cli"])
def test_budget_un_livre_un_puis_reprend_sans_doublon(base_et_departement, par_cli, capsys):
    def appeler():
        if par_cli:
            assert cli.main(["evenements", "repartir", "--limite", "1"]) == 0
            return json.loads(capsys.readouterr().out)
        return evenements.repartir(base_et_departement, limite=1)

    for total in (1, 2):
        reponse = appeler()
        assert reponse["livres"] == reponse["traites"] == 1
        assert reponse["echecs"] == 0
        stockage.liberer()
        assert _etat_natif() == {"recus": total, "snapshots": total, "faits": total}
    assert appeler() == ZERO
