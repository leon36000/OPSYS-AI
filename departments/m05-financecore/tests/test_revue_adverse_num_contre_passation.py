"""Revue adverse (num) : une contre-passation mal datée ou mal motivée se REPREND.

Défaut trouvé : la clé d'idempotence d'une contre-passation était `contre_passation:<écriture>` seule. Un brouillon
proposé avec une mauvaise date (ou un motif fautif) ne pouvait ni se supprimer (registre append-only), ni se valider
sans erreur de date, ni se remplacer : proposer la bonne date donnait `REJ-GL-PIECE-CONFLIT` (« contre-passer ou citer
une autre pièce », deux gestes impossibles ici : un brouillon ne se contre-passe pas et la pièce est dictée). La clé
porte maintenant la date et l'empreinte du motif : le même geste reste idempotent, un geste corrigé est un autre
brouillon, et la validation de l'un rend l'autre non validable (`REJ-GL-DEJA-CONTRE-PASSEE`). Données fictives.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import grand_livre, plan_comptable
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]
H = "2026-10-15T10:00:00-04:00"
HUMAIN = {"par": "nathan", "role": "nathan_owner", "voie": "approbation"}


@pytest.fixture
def plan():
    base, refus = plan_comptable.charger_plan(_M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None
    return base


@pytest.fixture
def reg():
    return registre_module.Registre()


@pytest.fixture
def originale(reg, plan):
    lignes = [{"compte": "5600", "debit": "1000.00", "credit": None},
              {"compte": "1010", "debit": None, "credit": "1000.00"}]
    proposee, refus = grand_livre.proposer_ecriture(
        reg, plan, cle_piece="saisie:manuelle:M-1", piece={"type": "manuelle", "reference": "M-1"}, nature="saisie",
        date_effet="2026-10-01", libelle="Loyer d'octobre (fictif)", lignes_brutes=lignes, horodatage=H,
        origine="saisie")
    assert refus is None, refus
    ident = proposee["ecriture"]["ecriture_id"]
    assert grand_livre.valider_ecriture(reg, plan, ecriture_id=ident, humain=HUMAIN, horodatage=H)[1] is None
    return ident


def _contre(reg, plan, ident, date_effet="2026-10-05", motif="loyer saisi au mauvais compte (fictif)"):
    return grand_livre.proposer_contre_passation(
        reg, plan, ecriture_id=ident, date_effet=date_effet, motif=motif, horodatage=H)


def test_le_meme_geste_rejoue_reste_idempotent(reg, plan, originale):
    premiere, refus = _contre(reg, plan, originale)
    assert refus is None and premiere["statut"] == "proposee"
    seconde, refus = _contre(reg, plan, originale)
    assert refus is None and seconde["statut"] == "deja_proposee"
    assert seconde["ecriture"]["ecriture_id"] == premiere["ecriture"]["ecriture_id"]
    assert len([e for e in grand_livre.etat_grand_livre(reg.lire())["ecritures"].values() if e["contre_passe"]]) == 1


@pytest.mark.parametrize("corrige", [
    {"date_effet": "2026-10-06"}, {"motif": "erreur de compte : 5600 au lieu de 5700"},
])
def test_une_contre_passation_corrigee_est_un_autre_brouillon_pas_un_conflit(reg, plan, originale, corrige):
    erronee, refus = _contre(reg, plan, originale)
    assert refus is None
    reprise, refus = _contre(reg, plan, originale, **corrige)
    assert refus is None, refus
    assert reprise["statut"] == "proposee"
    assert reprise["ecriture"]["ecriture_id"] != erronee["ecriture"]["ecriture_id"]
    assert reprise["ecriture"]["contre_passe"] == originale


def test_valider_la_bonne_rend_l_ancienne_non_validable_et_la_balance_s_annule(reg, plan, originale):
    erronee, _ = _contre(reg, plan, originale, date_effet="2026-10-05")
    bonne, _ = _contre(reg, plan, originale, date_effet="2026-10-06")
    valide, refus = grand_livre.valider_ecriture(
        reg, plan, ecriture_id=bonne["ecriture"]["ecriture_id"], humain=HUMAIN, horodatage=H)
    assert refus is None and valide["ecriture"]["statut"] == "DEFINITIVE"
    tard, refus = grand_livre.valider_ecriture(
        reg, plan, ecriture_id=erronee["ecriture"]["ecriture_id"], humain=HUMAIN, horodatage=H)
    assert tard is None and refus["code"] == "REJ-GL-DEJA-CONTRE-PASSEE"
    etat = grand_livre.etat_grand_livre(reg.lire())
    balance, refus = grand_livre.balance_verification(etat, plan, "2026-10-31")
    assert refus is None and balance["equilibree"] and all(c["solde"] == "0.00" for c in balance["comptes"])
    # Une fois la bonne validée, on n'en propose plus aucune pour la même écriture.
    encore, refus = _contre(reg, plan, originale, date_effet="2026-10-07")
    assert encore is None and refus["code"] == "REJ-GL-DEJA-CONTRE-PASSEE"
