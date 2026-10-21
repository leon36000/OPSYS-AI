"""Calendrier préparatoire M5 : déclarations explicites, sources périmées et lecture sans effet métier."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from m5_financecore import calendrier_obligations
from m5_financecore import outils as m5_outils

_RACINE_M5 = Path(__file__).resolve().parents[1]
_OPSYS_SRC = _RACINE_M5.parents[1] / "src"
if str(_OPSYS_SRC) not in sys.path:
    sys.path.insert(0, str(_OPSYS_SRC))

from opsys import stockage  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

AUJOURD_HUI = "2026-09-30"
FICTIF = True


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'calendrier-obligations.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    yield url
    stockage.liberer()


def _configuration(*, echeance_paies="2026-10-09", source_fin="2026-12-31"):
    return {
        "fiscal": {
            "frequence_tps_tvq": "trimestrielle",
            "mois_fin_exercice": 12,
            "taxes_remises_jusqu_au": "2026-06-30",
        },
        "obligations_declarees": {
            cle: {"montant": montant, "source": f"Déclaration fictive du {cle}", "au": AUJOURD_HUI}
            for cle, montant in (("paies", "5000.00"), ("das", "1200.00"), ("dettes", "900.00"))
        },
        "prevision": {
            "echeances_obligations": {
                "paies": echeance_paies,
                "das": "2026-10-15",
                "dettes": "2026-10-31",
            }
        },
        "calendrier_obligations": {
            cle: {
                "autorite": f"Autorité déclarée pour {cle} (fictive)",
                "periode_debut": "2026-09-01",
                "periode_fin": "2026-09-30",
                "echeance_source": f"Pièce source fictive {cle}",
                "source_consultee_le": "2026-09-29",
                "source_applicable_du": "2026-01-01",
                "source_applicable_jusqu_au": source_fin,
                "annee": 2026,
                "version": "2026-test-v1",
            }
            for cle in ("paies", "das", "dettes")
        },
    }


def _outil():
    return next(outil for outil in m5_outils.outils() if outil.nom == "m5_lire_calendrier_obligations")


def test_obligations_sans_declarations_restent_visibles_et_non_calculables():
    resultat = calendrier_obligations.lire_obligations_documentees(AUJOURD_HUI, None, None, None)
    assert len(resultat["obligations"]) == 3
    for ligne in resultat["obligations"]:
        assert ligne["statut"] == "INCOMPLETE"
        assert ligne["montant"] is None and ligne["echeance"] is None
        assert ligne["echeance_statut"] == "NON_DECLAREE"
        assert ligne["manque"]


def test_calendrier_fiscal_et_obligations_reutilisent_les_sources_declares(base_durable, monkeypatch):
    configuration = _configuration()
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: configuration)
    outil = _outil()
    reponse = executer_atomique(outil, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True})
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]["resultat"]
    par_id = {ligne["id"]: ligne for ligne in resultat["obligations"]}
    assert par_id["paies"]["statut"] == "DOCUMENTEE_A_VALIDER"
    assert par_id["paies"]["montant"] == "5000.00"
    assert par_id["paies"]["montant_utilisable"] == "5000.00"
    assert par_id["paies"]["echeance"] == "2026-10-09"
    assert par_id["paies"]["autorite"].startswith("Autorité déclarée")
    assert par_id["paies"]["version"] == "2026-test-v1"
    assert resultat["echeances_tps_tvq"]["statut"] == "DOCUMENTE_A_VALIDER"
    assert resultat["echeances_tps_tvq"]["versions"]["2026"] == "2026-v1"
    assert resultat["mention"] and "aucune formule de paie" in " ".join(resultat["limites"])
    # Le nouveau calendrier est T0; aucun registre dérivé ou mouvement n'est créé par cette lecture.
    assert len(stockage.maillons("m05-financecore", "constats_cash_libre")) == 0
    assert len(stockage.maillons("m05-financecore", "mouvements")) == 0


def test_source_qui_ne_couvre_pas_la_periode_est_perimee_sans_utiliser_son_montant(base_durable, monkeypatch):
    configuration = _configuration(source_fin="2026-08-31")
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: configuration)
    reponse = executer_atomique(_outil(), {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True})
    assert reponse["ok"] is True, reponse
    paies = next(ligne for ligne in reponse["resultat"]["resultat"]["obligations"] if ligne["id"] == "paies")
    assert paies["statut"] == "SOURCE_PERIMEE"
    assert paies["montant"] == "5000.00" and paies["montant_utilisable"] is None
    assert any(manque["code"] == "REJ-CALENDRIER-PAIES-SOURCE-PERIMEE" for manque in paies["manque"])


def test_echeance_passee_est_a_verifier_et_non_un_paiement_manquant(base_durable, monkeypatch):
    configuration = _configuration(echeance_paies="2026-09-15")
    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lambda: configuration)
    reponse = executer_atomique(_outil(), {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True})
    paies = next(ligne for ligne in reponse["resultat"]["resultat"]["obligations"] if ligne["id"] == "paies")
    assert paies["statut"] == "ECHEANCE_PASSEE_A_VERIFIER"
    assert paies["montant_utilisable"] == "5000.00"
    assert any("ne sait pas si elle a été payée" in limite for limite in reponse["resultat"]["resultat"]["limites"])


def test_le_contrat_du_nouveau_outil_est_lecture_seule_et_scellee():
    outil = _outil()
    assert outil.autonomie.value == "T0"
    assert outil.roles_appareil == frozenset({"admin"})
    assert outil.parametres["required"] == ["aujourd_hui"]
    assert outil.parametres["additionalProperties"] is False
    with pytest.raises(ValueError, match="date AAAA-MM-JJ"):
        calendrier_obligations.lire_obligations_documentees("demain", None, None, None)
