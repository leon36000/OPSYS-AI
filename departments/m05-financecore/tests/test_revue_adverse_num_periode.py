"""Revue adverse (num) : une période comptable ne s'écrit qu'en `AAAA-MM` ASCII, exactement.

Défaut trouvé : `fin_de_periode` utilisait `^(\\d{4})-(\\d{2})$` avec `.match` : `$` accepte un « \\n » final et `\\d`
accepte les chiffres Unicode (« ２０２６-０１ »). La clôture stockait la chaîne BRUTE (« 2026-01\\n »), et les
opérations de
période (`ouvrir_periode`, `preclore_periode`) l'utilisent comme clé d'idempotence et la comparent par égalité de
texte à celle des jugements et ouvertures : deux orthographes d'un même mois donnaient deux « mois » distincts.
Les dates `AAAA-MM-JJ` n'ont pas ce défaut (`date.fromisoformat` les refuse), mais le test les garde. Données fictives.
"""

from __future__ import annotations

from datetime import date

import pytest
from m5_financecore import grand_livre
from m5_financecore import registre as registre_module

FICTIF = True
H = "2026-10-15T10:00:00-04:00"
HUMAIN = {"par": "nathan", "role": "nathan_owner", "voie": "approbation"}


@pytest.mark.parametrize("periode", [
    "2026-01\n", "２０２６-０１", "2026-０１", "٢٠٢٦-٠١", "2026-01 ", " 2026-01", "2026-1", "2026-13", "2026-00",
    "1899-12",
    "2026-01\r", "2026-01\x00", None, 202601, b"2026-01",
])
def test_une_periode_mal_ecrite_n_a_pas_de_fin(periode):
    assert grand_livre.fin_de_periode(periode) is None


@pytest.mark.parametrize("periode, fin", [
    ("2026-01", date(2026, 1, 31)), ("2026-02", date(2026, 2, 28)), ("2028-02", date(2028, 2, 29)),
    ("2026-12", date(2026, 12, 31)), ("1900-01", date(1900, 1, 31)),
])
def test_une_periode_ascii_exacte_reste_lue(periode, fin):
    assert grand_livre.fin_de_periode(periode) == fin


@pytest.mark.parametrize("periode", ["2026-01\n", "２０２６-０１"])
def test_la_cloture_refuse_une_periode_mal_ecrite_et_n_ecrit_rien(periode):
    reg = registre_module.Registre()
    resultat, refus = grand_livre.clore_periode(reg, periode=periode, humain=HUMAIN, horodatage=H)
    assert resultat is None and refus["code"] == "REJ-GL-PERIODE-INVALIDE"
    assert reg.taille() == 0


@pytest.mark.parametrize("date_effet", ["2026-01-01\n", "２０２６-０１-０１", "20260101", "2026-1-1", " 2026-01-01"])
def test_une_date_mal_ecrite_reste_refusee(date_effet):
    assert grand_livre._date(date_effet) is None


@pytest.mark.parametrize("periode", ["2026-10\n", "２０２６-１０"])
def test_les_operations_de_periode_refusent_une_periode_mal_ecrite(periode):
    from m5_financecore import operations_periodes as op
    from m5_financecore import operations_registre as ore

    ops, gl = registre_module.Registre(), registre_module.Registre()
    etat_gl = grand_livre.etat_grand_livre(gl.lire())
    ouverture, refus = op.ouvrir_periode(ops, ore.etat_operations(ops.lire()), etat_gl, periode=periode, horodatage=H)
    assert ouverture is None and refus["code"] == "REJ-OPS-PERIODE-INVALIDE"
    preclotures, refus = op.preclore_periode(
        ops, ore.etat_operations(ops.lire()), etat_gl, periode=periode, factures_clients=[],
        factures_fournisseurs=[], controle_taxes=None, horodatage=H)
    assert preclotures is None and refus["code"] == "REJ-OPS-PERIODE-INVALIDE"
    assert ops.taille() == 0
