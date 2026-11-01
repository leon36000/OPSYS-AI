"""M7 -> M5 : un relevé de dépense publicitaire devient un BROUILLON d'écriture de charge, jamais une écriture validée.

Bus réel, consommateur réel de M5, grand livre réel (registre `grand_livre` de M5). Cas négatifs : taxes incluses,
révision,
montant nul, période close, période illisible, pièce déclarée (jamais prétendue vérifiée). Données fictives.
"""

from __future__ import annotations

from decimal import Decimal

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m5_financecore import charges_marketing_recues as cmr

from opsys import evenements

FICTIF = True
M5, M7 = "m05-financecore", "m07-marketing"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M5, M7))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _publier(charge, ident):
    evenements.publier("m7.depenses_marketing_constatees", M7, charge, evenement_id=ident)


def _journal(monde):
    return monde.registre(M5, cmr.REGISTRE)


def _gl(monde):
    return monde.registre(M5, "grand_livre")


def test_releve_hors_taxes_donne_un_brouillon_equilibre_au_compte_marketing_du_plan(monde):
    _publier(ch.depense_marketing(montant="125.40"), "d1")
    monde.repartir()
    (ligne,) = _journal(monde)
    assert ligne["issue"] == cmr.BROUILLON_PROPOSE and "CPA" in ligne["mention"]
    (ecriture,) = _gl(monde)
    assert ecriture["type_entree"] == "gl_ecriture_proposee"
    assert ecriture["origine"] == "evenement_m7"
    assert ecriture["piece"] == {
        "type": "manuelle",
        "reference": "m7:releve-google-2026-10-27:r1",
        "verification": "declaree_non_verifiee",
    }
    debit = {ligne["compte"]: ligne["debit"] for ligne in ecriture["lignes"]}
    credit = {ligne["compte"]: ligne["credit"] for ligne in ecriture["lignes"]}
    assert debit["5950"] == Decimal("125.40") and credit["2100"] == Decimal("125.40")
    assert ecriture["date_effet"] == "2026-10-27"
    assert ecriture["plan_comptable_version"]


def test_jamais_une_ecriture_validee_ni_un_mouvement(monde):
    _publier(ch.depense_marketing(), "d1")
    monde.repartir()
    assert {m["type_entree"] for m in _gl(monde)} == {"gl_ecriture_proposee"}  # aucune validation, aucune clôture
    assert monde.registre(M5, "principal") == []  # le registre des mouvements d'argent n'est pas touché


def test_taxes_incluses_aucun_brouillon_a_completer(monde):
    _publier(ch.depense_marketing(base="TAXES_INCLUSES"), "d1")
    monde.repartir()
    assert [m["issue"] for m in _journal(monde)] == [cmr.A_COMPLETER_TAXES]
    assert _gl(monde) == []


def test_revision_ulterieure_ne_cree_pas_un_second_brouillon(monde):
    _publier(ch.depense_marketing(revision=1, montant="100.00"), "d1")
    monde.repartir()
    _publier(ch.depense_marketing(revision=2, montant="130.00"), "d2")
    monde.repartir()
    issues = [(m["revision"], m["issue"]) for m in _journal(monde)]
    assert issues == [(1, cmr.BROUILLON_PROPOSE), (2, cmr.A_REVOIR_REVISION)]
    assert len(_gl(monde)) == 1  # la charge n'est pas doublée
    assert _journal(monde)[1]["revision_deja_proposee"] == 1


def test_montant_nul_aucun_brouillon(monde):
    _publier(ch.depense_marketing(montant="0.00"), "d1")
    monde.repartir()
    assert [m["issue"] for m in _journal(monde)] == [cmr.MONTANT_NUL] and _gl(monde) == []


def test_periode_close_refusee_et_rangee_sans_retenter(monde):
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(), evenement_id="d0")
    monde.repartir()
    # Une période close jusqu'au 30 octobre : un relevé du 27 ne peut plus entrer.
    _cloturer_jusqu_au(monde, "2026-10")
    _publier(ch.depense_marketing(releve_id="releve-tardif", jour="2026-10-29"), "d2")
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    refus = [m for m in _journal(monde) if m["releve_id"] == "releve-tardif"]
    assert refus and refus[0]["issue"] == cmr.REFUSE and refus[0]["code"] == "REJ-GL-PERIODE-CLOSE"


def _cloturer_jusqu_au(monde, periode):
    """Clôture RÉELLE d'un mois par la fonction du grand livre, sous l'identité d'un humain de test."""
    from m5_financecore import grand_livre, outils

    registre_gl, _plan = outils._contexte_grand_livre()[0]
    humain = {"par": "nathan.fictif", "role": "nathan_owner", "voie": "test"}
    resultat, refus = grand_livre.clore_periode(
        registre_gl, periode=periode, humain=humain, horodatage="2026-11-02T09:00:00-05:00"
    )
    assert refus is None, refus


def test_horodatage_sans_fuseau_refus_deterministe_range(monde):
    charge = ch.depense_marketing(releve_le="2026-10-28T06:00:00")  # sans fuseau
    _publier(charge, "d1")
    resume = monde.repartir()
    assert resume["quarantaines"] == 0
    assert _journal(monde)[0]["issue"] == cmr.REFUSE and _journal(monde)[0]["code"] == "REJ-GL-CHAMP-INVALIDE"


def test_pas_de_compte_marketing_au_plan_refus_rangé_jamais_un_compte_suppose(monde, monkeypatch):
    from m5_financecore import plan_comptable

    original = plan_comptable.compte_de_charge
    monkeypatch.setattr(
        plan_comptable,
        "compte_de_charge",
        lambda plan, *, po_id, categorie: (None, {"code": "REJ-GL-CATEGORIE-SANS-COMPTE", "detail": "x"}),
    )
    _publier(ch.depense_marketing(), "d1")
    monde.repartir()
    assert _journal(monde)[0]["issue"] == cmr.REFUSE and _gl(monde) == []
    monkeypatch.setattr(plan_comptable, "compte_de_charge", original)


def test_decision_pure():
    base = ch.depense_marketing()
    assert cmr.decision(base, {}) is None
    assert cmr.decision({**base, "base_taxes": "TAXES_INCLUSES"}, {}) == cmr.A_COMPLETER_TAXES
    assert cmr.decision({**base, "revision": 2}, {}) == cmr.A_REVOIR_REVISION
    assert cmr.decision(base, {base["releve_id"]: 1}) == cmr.A_REVOIR_REVISION
    assert cmr.decision({**base, "montant_cad": "0"}, {}) == cmr.MONTANT_NUL
    assert cmr.cle(base) == "releve-google-2026-10-27|r1"
