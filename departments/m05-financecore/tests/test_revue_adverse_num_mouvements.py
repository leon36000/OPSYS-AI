"""Revue adverse (num) : un mouvement du registre de trésorerie a un montant BORNÉ et au cent.

Défaut trouvé : `valider_mouvement` n'exige qu'un `Decimal` fini ; ni l'ordre de grandeur ni l'échelle n'étaient
contrôlés. Un mouvement de `1E+100` faisait perdre à `calculer_solde` (contexte de 64 chiffres) tous les centimes
d'un solde de 12,34 $ (résultat `0E+37`) ; un mouvement de `1E+9999999` faisait lever `Overflow` à chaque lecture du
solde, définitivement (registre append-only). Les autres modules de M5 bornent à 999 999 999 999,99 $ ; celui-ci non.
Données fictives.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from m5_financecore import outils as module_outils
from m5_financecore import registre, soldes, validation
from m5_financecore.outils import outils

from opsys import stockage
from opsys.outils import executer

FICTIF = True
D = Decimal
H = "2026-10-15T10:00:00-04:00"
MAXIMUM = "999999999999.99"


def _mouvement(montant, type_mouvement="ENCAISSEMENT"):
    return {"montant": D(montant), "type_mouvement": type_mouvement, "horodatage": H,
            "classe_retention": "STANDARD", "source": "test"}


@pytest.mark.parametrize("montant, type_mouvement", [
    ("1E+100", "ENCAISSEMENT"), ("-1E+100", "DECAISSEMENT"), ("1E+9999999", "ENCAISSEMENT"),
    ("1000000000000.00", "ENCAISSEMENT"), ("-1000000000000.00", "DECAISSEMENT"), ("1E+12", "AJUSTEMENT"),
    ("0.0000001", "ENCAISSEMENT"), ("-0.0000001", "DECAISSEMENT"), ("1E-9999999", "AJUSTEMENT"),
    ("1E-999999999", "AJUSTEMENT"),
])
def test_un_montant_demesure_ou_d_echelle_demesuree_est_refuse(montant, type_mouvement):
    journal = registre.Registre()
    with pytest.raises(validation.MouvementInvalide) as erreur:
        registre.enregistrer_mouvement(_mouvement(montant, type_mouvement), journal)
    assert erreur.value.verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    assert journal.taille() == 0


@pytest.mark.parametrize("montant, type_mouvement", [
    (MAXIMUM, "ENCAISSEMENT"), ("-" + MAXIMUM, "DECAISSEMENT"), ("0.01", "ENCAISSEMENT"), ("-0.01", "DECAISSEMENT"),
    ("12.34", "PROVISION"), ("125", "ENCAISSEMENT"), ("1E+2", "ENCAISSEMENT"), ("-7.50", "AJUSTEMENT"),
    ("0.00", "AJUSTEMENT"), ("3.10", "AUTRE"),
    ("100.005", "ENCAISSEMENT"),  # le cash libre arrondit lui-même un demi-cent (test_cash_libre.py)
    ("0.000001", "ENCAISSEMENT"),
])
def test_les_montants_legitimes_restent_acceptes(montant, type_mouvement):
    journal = registre.Registre()
    registre.enregistrer_mouvement(_mouvement(montant, type_mouvement), journal)
    assert journal.taille() == 1


def test_le_solde_garde_ses_centimes_avec_des_montants_aux_extremes_permis():
    journal = registre.Registre()
    for montant, genre in (("12.34", "ENCAISSEMENT"), (MAXIMUM, "ENCAISSEMENT"), ("-" + MAXIMUM, "DECAISSEMENT"),
                           (MAXIMUM, "ENCAISSEMENT"), ("-" + MAXIMUM, "DECAISSEMENT")):
        registre.enregistrer_mouvement(_mouvement(montant, genre), journal)
    assert soldes.calculer_solde(journal) == D("12.34")


@pytest.fixture
def _base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-num.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    module_outils.utiliser_stockage_durable()
    yield
    stockage.liberer()


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def test_l_outil_refuse_un_montant_demesure_et_la_tresorerie_reste_lisible(_base_durable):
    outil = _outil("m5_enregistrer_mouvement")
    args = {"type_mouvement": "ENCAISSEMENT", "horodatage": H, "classe_retention": "STANDARD", "source": "test"}
    assert executer(outil, {**args, "montant": "12.34"})["resultat"]["accepte"] is True
    reponse = executer(outil, {**args, "montant": "1E+9999999"})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
    etat = executer(_outil("m5_etat_tresorerie"), {"autorise_couts": True})
    assert etat["ok"] is True
    assert D(etat["resultat"]["solde"]) == D("12.34")
