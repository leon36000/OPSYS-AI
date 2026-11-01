"""Journal append-only hash-chaîné du site et de la vision (M3.2, M3.3, M3.5). Données fictives."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import journal_site  # noqa: E402

FICTIF = True


def _journal(n=3):
    j = journal_site.JournalSite()
    for i in range(n):
        j.ajouter(journal_site.TYPE_CONTEXTE, {"lead_id": f"lead-{i}", "version": 1})
    return j


def test_la_chaine_est_intacte_et_chaque_maillon_cite_son_predecesseur():
    j = _journal()
    maillons = j.lire()
    assert j.valider_chaine() == (True, "")
    assert maillons[0]["hash_precedent"] == journal_site.HASH_INITIAL
    assert maillons[1]["hash_precedent"] == maillons[0]["hash_maillon"]
    assert j.hash_tete() == maillons[-1]["hash_maillon"]


def test_une_alteration_au_milieu_est_localisee_au_rang_fautif():
    j = _journal()
    j._maillons[1]["charge"]["lead_id"] = "lead-falsifie"
    assert j.valider_chaine() == (False, "rang 1")


def test_la_suppression_d_un_maillon_central_est_detectee():
    j = _journal(4)
    del j._maillons[1]
    assert j.valider_chaine()[0] is False


def test_la_copie_lue_n_est_pas_une_reference_vivante():
    j = _journal(1)
    j.lire()[0]["charge"]["lead_id"] = "autre"
    assert j.valider_chaine() == (True, "")


@pytest.mark.parametrize("charge", [{"v": 1.5}, {"v": Decimal("1")}, {"v": {1: "x"}}, {"v": {"a": {"b": object()}}}])
def test_un_flottant_ou_un_type_non_json_n_entre_jamais_au_journal(charge):
    j = journal_site.JournalSite()
    with pytest.raises(ValueError):
        j.ajouter(journal_site.TYPE_CONTEXTE, charge)
    assert len(j.lire()) == 0


def test_type_de_maillon_inconnu_et_charge_non_objet_sont_refuses():
    j = journal_site.JournalSite()
    with pytest.raises(ValueError):
        j.ajouter("autre_type", {})
    with pytest.raises(ValueError):
        j.ajouter(journal_site.TYPE_CONTEXTE, ["pas", "un", "objet"])  # type: ignore[arg-type]


def test_une_charge_trop_profonde_est_refusee_sans_recursion_infinie():
    charge: dict = {}
    courant = charge
    for _ in range(40):
        courant["x"] = {}
        courant = courant["x"]
    with pytest.raises(ValueError):
        journal_site.JournalSite().ajouter(journal_site.TYPE_CONTEXTE, charge)


def test_filtre_par_type_et_empreinte_canonique_injective():
    j = journal_site.JournalSite()
    j.ajouter(journal_site.TYPE_CONTEXTE, {"a": 1})
    j.ajouter(journal_site.TYPE_CANDIDAT, {"a": 2})
    assert [m["type_entree"] for m in j.lire(journal_site.TYPE_CANDIDAT)] == ["candidat_vision"]
    # deux suites de valeurs différentes ne partagent jamais une forme canonique
    assert journal_site.empreinte_canonique("ab", "c") != journal_site.empreinte_canonique("a", "bc")
    assert journal_site.empreinte_canonique({"a": 1, "b": 2}) == journal_site.empreinte_canonique({"b": 2, "a": 1})


def test_un_maillon_au_format_ou_aux_cles_alteres_invalide_la_chaine():
    j = _journal(2)
    j._maillons[0]["format"] = "autre/v9"
    assert j.valider_chaine()[0] is False
    j = _journal(2)
    j._maillons[1]["extra"] = 1
    assert j.valider_chaine()[0] is False
