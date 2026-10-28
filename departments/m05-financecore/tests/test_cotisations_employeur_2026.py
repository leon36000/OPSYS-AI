"""Postes employeur 2026 : oracles indépendants (Fraction, jamais le code testé) et refus fail-closed."""

from __future__ import annotations

import sys
from decimal import Decimal, getcontext, setcontext
from fractions import Fraction
from pathlib import Path

import pytest
from m5_financecore import cotisations_employeur_2026 as ce
from m5_financecore import dossier_paie_preparatoire as d

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures_dossier_paie import entrees, parametres_employeur  # noqa: E402

FICTIF = True


def _cents_demi_haut(valeur: Fraction) -> str:
    """Arrondi au cent, demi vers le haut, en arithmétique exacte (oracle indépendant)."""
    centimes = valeur * 100
    plancher = centimes.numerator // centimes.denominator
    reste = centimes - plancher
    if reste >= Fraction(1, 2):
        plancher += 1
    return f"{plancher // 100}.{plancher % 100:02d}"


def _w_autres(masse: Fraction) -> Fraction:
    s = min(max(masse / 1_000_000, Fraction(1)), Fraction("7.8"))
    return Fraction("1.2662") + Fraction("0.3838") * s


def _w_primaire(masse: Fraction) -> Fraction:
    s = min(max(masse / 1_000_000, Fraction(1)), Fraction("7.8"))
    return Fraction("0.8074") + Fraction("0.4426") * s


def _postes(brut="1002.00", cumul="0.00", params=None, date_paie="2026-01-15", disponible=True):
    cumuls = dict.fromkeys(d.CHAMPS_CUMULS, "0.00")
    cumuls["salaire_rrq_cumul_avant"] = cumul
    return {
        p["id"]: p
        for p in ce.evaluer_postes_employeur(
            rrq_employe="54.65",
            rqap_employeur="6.03",
            ae_employeur="18.24",
            brut_cad=brut,
            cumuls_avant=cumuls,
            parametres_employeur=params,
            date_paie=date_paie,
            composition_disponible=disponible,
            raison_blocage="composition non exécutée",
        )
    }


@pytest.mark.parametrize(
    ("masse", "attendu_pct"),
    [
        ("0.00", Fraction("1.65")),
        ("1000000.00", Fraction("1.65")),
        ("500000.00", Fraction("1.65")),
        ("7800000.00", None),
        ("9000000.00", None),
    ],
)
def test_taux_fss_autres_bornes_et_continuite(masse, attendu_pct):
    w = Fraction(ce.taux_fss_pct("AUTRES", Decimal(masse)))
    attendu = attendu_pct if attendu_pct is not None else _w_autres(Fraction(masse))
    assert w == attendu
    if masse in {"7800000.00", "9000000.00"}:
        assert abs(float(w) - 4.26) < 0.0002  # borne haute officielle 4,26 % (continuité de la formule)


@pytest.mark.parametrize("masse", ["1500000.00", "3333333.33", "7799999.99"])
def test_taux_fss_interpole_entre_les_bornes(masse):
    for secteur, oracle in (("AUTRES", _w_autres), ("PRIMAIRE_MANUFACTURIER", _w_primaire)):
        assert Fraction(ce.taux_fss_pct(secteur, Decimal(masse))) == oracle(Fraction(masse))


def test_fss_secteur_public_4_26_peu_importe_la_masse():
    assert ce.taux_fss_pct("SECTEUR_PUBLIC", Decimal("1.00")) == Decimal("4.26")
    assert ce.taux_fss_pct("SECTEUR_PUBLIC", Decimal("50000000.00")) == Decimal("4.26")


@pytest.mark.parametrize(
    ("brut", "masse"),
    [("1002.00", "500000.00"), ("0.01", "500000.00"), ("2345.67", "2750000.00"), ("999999.99", "7800000.00")],
)
def test_fss_par_periode_arrondi_demi_haut(brut, masse):
    params = parametres_employeur()
    params["fss"]["masse_salariale_estimative_cad"] = masse
    poste = _postes(brut=brut, params=params)["fss"]
    assert poste["etat"] == "CALCULE"
    assert poste["montant"] == _cents_demi_haut(Fraction(brut) * _w_autres(Fraction(masse)) / 100)


def test_cnesst_normes_et_plafond_annuel_103000():
    params = parametres_employeur()
    # Cumul à 102 900 $ : seuls 100 $ restent assurables sous le maximum 2026 (103 000 $).
    postes = _postes(brut="1002.00", cumul="102900.00", params=params)
    assert postes["cnesst"]["montant"] == _cents_demi_haut(Fraction(100) * Fraction("1.54") / 100)
    assert postes["normes_travail"]["montant"] == _cents_demi_haut(Fraction(100) * Fraction("0.06") / 100)
    # Cumul au maximum : plus rien d'assurable.
    atteint = _postes(brut="1002.00", cumul="103000.00", params=params)
    assert atteint["cnesst"]["montant"] == "0.00" and atteint["normes_travail"]["montant"] == "0.00"
    # Cumul supérieur au maximum (donnée incohérente) ne produit jamais un montant négatif.
    assert _postes(brut="1002.00", cumul="150000.00", params=params)["cnesst"]["montant"] == "0.00"


def test_rrq_employeur_est_egale_a_la_retenue_employe_sans_deuxieme_calcul():
    poste = _postes(params=parametres_employeur())["rrq_employeur"]
    assert poste["etat"] == "CALCULE" and poste["montant"] == "54.65"
    assert poste["source"]["sections"] == "p. 7; partie 3.2 p. 40"


def test_parametres_absents_laissent_inconnus_sans_taux_par_defaut():
    postes = _postes(params=None)
    for ident in ("fss", "cnesst", "normes_travail", "fdrcmo"):
        assert postes[ident]["etat"] == "INCONNU" and postes[ident]["montant"] is None
        assert postes[ident]["manque"]
    assert "aucun taux par défaut" in postes["cnesst"]["manque"][0]


def test_fdrcmo_seuil_strictement_superieur_a_2_millions():
    params = parametres_employeur()
    params["fdrcmo"]["masse_salariale_annee_cad"] = "2000000.00"
    assert _postes(params=params)["fdrcmo"]["etat"] == "NON_APPLICABLE"
    params["fdrcmo"]["masse_salariale_annee_cad"] = "2000000.01"
    audessus = _postes(params=params)["fdrcmo"]
    assert audessus["etat"] == "INCONNU" and audessus["montant"] is None
    assert "dépenses de formation" in audessus["manque"][0]


def test_cnesst_base_hebdomadaire_non_transcrite_reste_inconnue():
    params = parametres_employeur()
    params["cnesst"]["base_excedent"] = "HEBDOMADAIRE"
    poste = _postes(params=params)["cnesst"]
    assert poste["etat"] == "INCONNU" and "hebdomadaire" in poste["manque"][0]


@pytest.mark.parametrize("date_paie", ["2025-12-31", "2027-01-01"])
def test_aucune_reconduction_hors_2026(date_paie):
    postes = _postes(params=parametres_employeur(), date_paie=date_paie)
    for ident in ("rrq_employeur", "rqap_employeur", "ae_employeur", "fss", "cnesst", "normes_travail", "fdrcmo"):
        assert postes[ident]["etat"] == "INCONNU", ident
        assert "2026" in postes[ident]["manque"][0]


def test_sans_composition_aucun_poste_calcule():
    postes = _postes(params=parametres_employeur(), disponible=False)
    assert all(p["etat"] == "INCONNU" for p in postes.values())


def test_contexte_decimal_hostile_ne_change_pas_les_postes():
    normal = _postes(brut="2345.67", params=parametres_employeur())
    ancien = getcontext().copy()
    try:
        hostile = getcontext().copy()
        hostile.prec = 3
        hostile.rounding = "ROUND_DOWN"
        setcontext(hostile)
        sous_hostile = _postes(brut="2345.67", params=parametres_employeur())
    finally:
        setcontext(ancien)
    assert {k: v["montant"] for k, v in sous_hostile.items()} == {k: v["montant"] for k, v in normal.items()}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.pop("fss"),
        lambda p: p.update(extra=None),
        lambda p: p["fss"].update(secteur="CONSTRUCTION"),
        lambda p: p["fss"].update(masse_salariale_estimative_cad="500000"),
        lambda p: p["cnesst"].update(taux_versement_pour_100="1,54"),
        lambda p: p["cnesst"].update(taux_versement_pour_100=1.54),
        lambda p: p["normes_travail"].update(assujetti="oui"),
        lambda p: p["fdrcmo"].update(reference="../etc/passwd"),
    ],
)
def test_parametres_employeur_mal_formes_refuses(mutation):
    params = parametres_employeur()
    mutation(params)
    ok, verdict = ce.valider_parametres_employeur(params)
    assert ok is False and verdict["code"] == "REJ-DOSSIER-PAIE-STRUCTURE-INVALIDE"


def test_snapshot_de_parametres_hache_et_sources_datees():
    assert len(ce.HASH_PARAMETRES) == 64
    ids = {s["id"] for s in ce.PARAMETRES["sources"]}
    assert {"rq_tp1015f_rrq_employeur", "rq_tp1015f_fss", "cnesst_salaire_max_2026", "rq_tp1015g_normes"} <= ids
    assert all(s["edition"] and s["sections"] and s["lecture"] for s in ce.PARAMETRES["sources"])
    assert ce.PARAMETRES["statut_source"] == "TEXTE_OFFICIEL_LU_SANS_CAPTURE_BINAIRE"
    _ = entrees  # fabrique partagée importée pour garder la même fixture que les autres tests
