"""PLAN T1.5-d : coût réel et rentabilité d'un chantier (`cout_reel.py`, module pur).

Le module ne lit rien : ces tests lui passent les pièces que `outils.py` lit à la source (WCT reçu, signal
de variance de M6, livre de prix de M6, taux configuré, facture, devis accepté) et vérifient ce qu'il en tire :
un calcul en Decimal, arrondi `ROUND_HALF_UP`, ou un manque nommé, jamais une valeur par défaut. Fixtures
fictives (AGENTS.md).
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import cout_reel, encodage, validation

FICTIF = True
MATERIAU = "gouttiere-alu-5po-fictif"


def _wct(**surcharges):
    base = {"wct_id": "WCT-1", "intervention_id": "INT-1", "devis_id": "DEVIS-1",
            "horodatage_completion": "2026-09-15T15:00:00+00:00", "duree_reelle_minutes": 180}
    return {**base, **surcharges}


def _ligne(materiau=MATERIAU, unite="pi", reelle="42.0", **surcharges):
    base = {"materiau": materiau, "unite": unite, "quantite_prevue": "40.0", "quantite_reelle": reelle,
            "ecart_pourcentage": "0.05", "critique": False}
    return {**base, **surcharges}


_PAR_DEFAUT = object()


def _signal(lignes=_PAR_DEFAUT, statut="evaluee", **surcharges):
    if lignes is _PAR_DEFAUT:
        lignes = [_ligne()] if statut == "evaluee" else None
    base = {"wct_id": "WCT-1", "chantier_id": "CH-1", "statut_variance": statut, "signal_critique": False,
            "horodatage_completion": "2026-09-15T15:00:00+00:00", "lignes": lignes}
    return {**base, **surcharges}


def _prix(materiau=MATERIAU, fournisseur="gentek-fictif", prix=8.0, devise="CAD", **surcharges):
    base = {"materiau_id": materiau, "fournisseur_id": fournisseur, "prix_unitaire": prix, "devise": devise,
            "date_effet": "2026-09-01", "source_document": None}
    return {**base, **surcharges}


def _facture(statut="BROUILLON", montant="600.00"):
    return {"facture_id": "fac-DEVIS-1", "statut": statut, "montant_avant_taxes": Decimal(montant)}


def _devis(**surcharges):
    base = {"devis_id": "DEVIS-1", "chantier_id": "CH-1", "cout_total": "480.00", "prix_total": "600.00",
            "taux_marge": "0.25"}
    return {**base, **surcharges}


def _cout(wct=None, signal=None, livre=None, taux="50.00"):
    return cout_reel.calculer_cout_reel(
        _wct() if wct is None else wct,
        _signal() if signal is None else signal,
        [_prix()] if livre is None else livre,
        taux,
    )


def _rentabilite(cout=None, facture="defaut", devis="defaut"):
    return cout_reel.calculer_rentabilite(
        _cout() if cout is None else cout,
        _facture() if facture == "defaut" else facture,
        _devis() if devis == "defaut" else devis,
        devis_id="DEVIS-1", chantier_id="CH-1",
    )


def _codes(entrees):
    return [e["code"] for e in entrees["manque"]]


def _tous_les_montants(valeur):
    """Toutes les valeurs numériques de la structure : chacune doit être un Decimal, jamais un float."""
    if isinstance(valeur, dict):
        for sous in valeur.values():
            yield from _tous_les_montants(sous)
    elif isinstance(valeur, (list, tuple)):
        for sous in valeur:
            yield from _tous_les_montants(sous)
    elif isinstance(valeur, (int, float, Decimal)) and not isinstance(valeur, bool):
        yield valeur


# =========================================================================================
# 1. Le cas complet : chaque chiffre vient d'une source, le calcul est exact
# =========================================================================================
def test_cout_complet_materiaux_et_main_d_oeuvre():
    cout = _cout()

    assert cout["complet"] is True and cout["manque"] == []
    (ligne,) = cout["materiaux"]["lignes"]
    assert (ligne["materiau"], ligne["statut"]) == (MATERIAU, "PRIX_LIVRE")
    assert ligne["quantite_reelle"] == Decimal("42.0") and ligne["prix_unitaire"] == Decimal("8.0")
    assert ligne["cout"] == Decimal("336.00")  # 42 pi x 8,00 $
    assert cout["materiaux"]["statut"] == "complet" and cout["materiaux"]["cout_connu"] == Decimal("336.00")
    mo = cout["main_d_oeuvre"]
    assert (mo["minutes"], mo["taux_horaire"], mo["cout"]) == (180, Decimal("50.00"), Decimal("150.00"))
    assert cout["cout_total"] == cout["cout_total_connu"] == Decimal("486.00")
    assert cout["devise"] == "CAD"


def test_le_signal_critique_de_m6_reste_visible_a_cote_du_cout():
    cout = _cout(signal=_signal(signal_critique=True))

    assert cout["materiaux"]["source_quantites"] == {
        "evenement": "m6.variance_chantier", "statut_variance": "evaluee", "signal_critique": True}


def test_aucun_montant_n_est_un_float():
    resultat = _rentabilite()

    montants = list(_tous_les_montants({cle: valeur for cle, valeur in resultat.items() if cle != "version_entrees"}))
    assert montants, "le test ne passe pas à vide"
    assert not [m for m in montants if isinstance(m, float)]


def test_rentabilite_prix_moins_cout_marge_reelle_contre_prevue():
    r = _rentabilite()

    assert r["verdict"] == "CALCULEE" and r["manque"] == []
    assert r["prix_facture"] == Decimal("600.00")  # avant taxes : la TPS et la TVQ ne sont pas un revenu
    assert r["marge_reelle"] == Decimal("114.00") and r["marge_reelle_pct_du_prix"] == Decimal("0.1900")
    assert r["cout_prevu"] == Decimal("480.00") and r["marge_prevue"] == Decimal("120.00")
    assert r["marge_prevue_pct_du_prix"] == Decimal("0.2000") and r["taux_marge_devis"] == "0.25"
    assert r["ecart_marge"] == Decimal("-6.00") and r["ecart_marge_points"] == Decimal("-0.0100")
    assert r["en_perte"] is False
    assert r["marge_partielle_plafond"] is None
    assert (r["devis_id"], r["chantier_id"], r["wct_id"]) == ("DEVIS-1", "CH-1", "WCT-1")


def test_un_chantier_a_perte_est_dit_a_perte():
    r = _rentabilite(cout=_cout(taux="200.00"), facture=_facture(montant="600.00"))  # 336 + 600 = 936 > 600

    assert r["marge_reelle"] == Decimal("-336.00") and r["en_perte"] is True


def test_le_prix_provisoire_d_un_brouillon_n_est_pas_definitif():
    assert _rentabilite(facture=_facture("BROUILLON"))["prix_definitif"] is False
    assert _rentabilite(facture=_facture("ENVOYEE"))["prix_definitif"] is True
    assert _rentabilite(facture=_facture("PAYEE"))["prix_definitif"] is True


# =========================================================================================
# 2. L'arrondi : ROUND_HALF_UP, jamais l'arrondi du banquier
# =========================================================================================
def test_ligne_de_materiau_arrondie_half_up_au_cent():
    cout = _cout(signal=_signal([_ligne(reelle="1")]), livre=[_prix(prix=0.125)])

    assert cout["materiaux"]["lignes"][0]["cout"] == Decimal("0.13")  # 0,125 : half-even donnerait 0,12


def test_main_d_oeuvre_arrondie_une_seule_fois_half_up():
    cout = _cout(wct=_wct(duree_reelle_minutes=1), signal=_signal([]), taux="0.30")

    assert cout["main_d_oeuvre"]["cout"] == Decimal("0.01")  # 1 min x 0,30 $/h = 0,005 $ : half-even donnerait 0,00


def test_la_somme_des_lignes_arrondies_fait_le_cout_des_materiaux():
    livre = [_prix("a", prix=0.125), _prix("b", prix=0.125)]
    signal = _signal([_ligne("a", reelle="1"), _ligne("b", reelle="1")])

    cout = _cout(signal=signal, livre=livre)

    assert cout["materiaux"]["cout_connu"] == Decimal("0.26")  # 0,13 + 0,13, comme deux lignes de facture


def test_pourcentage_de_marge_arrondi_half_up_a_quatre_decimales():
    cout = _cout(signal=_signal([]), taux="31.00", wct=_wct(duree_reelle_minutes=60))  # coût 31,00 $

    r = _rentabilite(cout=cout, facture=_facture(montant="32.00"))

    assert r["marge_reelle"] == Decimal("1.00")
    assert r["marge_reelle_pct_du_prix"] == Decimal("0.0313")  # 1/32 = 0,03125 : half-even donnerait 0,0312


def test_un_prix_nul_ne_donne_aucun_pourcentage_jamais_une_division_par_zero():
    cout = _cout(signal=_signal([]), taux="1.00", wct=_wct(duree_reelle_minutes=60))

    r = _rentabilite(cout=cout, facture=_facture(montant="0.00"))

    assert r["marge_reelle"] == Decimal("-1.00") and r["marge_reelle_pct_du_prix"] is None


# =========================================================================================
# 3. Fail-closed sur les matériaux : un prix absent est dit absent
# =========================================================================================
def test_prix_absent_du_livre_donne_une_ligne_prix_non_disponible_et_un_cout_partiel():
    cout = _cout(livre=[])

    (ligne,) = cout["materiaux"]["lignes"]
    assert ligne["statut"] == "PRIX_NON_DISPONIBLE" and ligne["prix_unitaire"] is None and ligne["cout"] is None
    assert cout["complet"] is False and cout["cout_total"] is None  # jamais une somme partielle prise pour un total
    assert cout["cout_total_connu"] == Decimal("150.00")  # la main-d'oeuvre seule, dite connue
    assert cout["materiaux"]["statut"] == "partiel"
    (manque,) = cout["manque"]
    assert manque["code"] == "REJ-COUT-PRIX-NON-DISPONIBLE" and manque["materiau"] == MATERIAU


def test_le_prix_d_un_autre_materiau_n_est_jamais_utilise():
    cout = _cout(livre=[_prix("autre-materiau-fictif", prix=99.0)])

    assert cout["materiaux"]["lignes"][0]["statut"] == "PRIX_NON_DISPONIBLE"


def test_deux_fournisseurs_aux_prix_differents_donnent_un_prix_ambigu_jamais_une_moyenne():
    livre = [_prix(fournisseur="gentek-fictif", prix=8.0), _prix(fournisseur="kaycan-fictif", prix=9.0)]

    cout = _cout(livre=livre)

    ligne = cout["materiaux"]["lignes"][0]
    assert ligne["statut"] == "PRIX_AMBIGU" and ligne["prix_unitaire"] is None and ligne["cout"] is None
    assert [s["fournisseur_id"] for s in ligne["sources_prix"]] == ["gentek-fictif", "kaycan-fictif"]
    assert _codes(cout) == ["REJ-COUT-PRIX-AMBIGU"] and cout["complet"] is False


def test_deux_fournisseurs_au_meme_prix_donnent_ce_prix():
    livre = [_prix(fournisseur="gentek-fictif", prix=8.0), _prix(fournisseur="kaycan-fictif", prix=8)]

    cout = _cout(livre=livre)

    assert cout["materiaux"]["lignes"][0]["cout"] == Decimal("336.00") and cout["complet"] is True


def test_le_dernier_prix_ecrit_d_un_fournisseur_fait_foi():
    livre = [_prix(prix=7.0), _prix(prix=8.0)]  # même fournisseur : la seconde entrée remplace la première

    assert _cout(livre=livre)["materiaux"]["lignes"][0]["prix_unitaire"] == Decimal("8.0")


@pytest.mark.parametrize("entree", [
    pytest.param(_prix(prix=0), id="prix_nul"),
    pytest.param(_prix(prix=-3.5), id="prix_negatif"),
    pytest.param(_prix(prix="huit"), id="prix_illisible"),
    pytest.param(_prix(prix=True), id="prix_booleen"),
    pytest.param(_prix(prix=float("nan")), id="prix_nan"),
    pytest.param(_prix(devise="USD"), id="devise_etrangere"),
    pytest.param(_prix(devise=None), id="devise_absente"),
])
def test_une_entree_de_livre_inutilisable_n_est_jamais_prise_pour_un_prix(entree):
    cout = _cout(livre=[entree])

    assert cout["materiaux"]["lignes"][0]["statut"] == "PRIX_NON_DISPONIBLE"
    assert cout["complet"] is False


def test_la_devise_cad_est_reconnue_sans_egard_a_la_casse():
    assert _cout(livre=[_prix(devise=" cad ")])["complet"] is True


def test_un_prix_du_livre_en_texte_decimal_reste_exact():
    cout = _cout(livre=[_prix(prix="8.10")], signal=_signal([_ligne(reelle="3")]))

    assert cout["materiaux"]["lignes"][0]["cout"] == Decimal("24.30")


@pytest.mark.parametrize(("statut", "lignes"), [
    pytest.param("declaration_absente", None, id="declaration_absente"),
    pytest.param("prevu_absent", None, id="prevu_absent"),
    pytest.param("seuil_absent", None, id="seuil_absent"),
])
def test_variance_non_evaluee_les_materiaux_reels_sont_inconnus(statut, lignes):
    cout = _cout(signal=_signal(lignes, statut=statut))

    assert cout["materiaux"]["statut"] == "non_disponible" and cout["materiaux"]["lignes"] == []
    assert "REJ-COUT-MATERIAUX-REELS-ABSENTS" in _codes(cout)
    assert statut in cout["manque"][0]["detail"] and cout["complet"] is False
    assert cout["cout_total"] is None and cout["cout_total_connu"] == Decimal("150.00")


def test_aucun_signal_de_variance_recu_les_materiaux_reels_sont_inconnus():
    cout = cout_reel.calculer_cout_reel(_wct(), None, [_prix()], "50.00")

    assert "REJ-COUT-MATERIAUX-REELS-ABSENTS" in _codes(cout) and cout["materiaux"]["source_quantites"] is None


def test_signal_evalue_sans_detail_par_materiau_est_dit_sans_detail():
    cout = _cout(signal=_signal(None, statut="evaluee"))  # maillon écrit avant T1.5-d

    assert "REJ-COUT-MATERIAUX-REELS-ABSENTS" in _codes(cout)
    assert "sans le détail" in next(e["detail"] for e in cout["manque"])


def test_evaluee_sans_aucune_ligne_est_un_cout_de_materiaux_nul_et_complet():
    cout = _cout(signal=_signal([]))

    assert cout["materiaux"]["statut"] == "complet" and cout["materiaux"]["cout_connu"] == Decimal("0")
    assert cout["complet"] is True and cout["cout_total"] == Decimal("150.00")


@pytest.mark.parametrize("ligne", [
    pytest.param(_ligne(unite=None), id="unite_incoherente"),
    pytest.param(_ligne(unite=""), id="unite_vide"),
    pytest.param(_ligne(reelle="beaucoup"), id="quantite_illisible"),
    pytest.param(_ligne(reelle="-2.0"), id="quantite_negative"),
    pytest.param(_ligne(reelle=None), id="quantite_absente"),
    pytest.param(_ligne(reelle="NaN"), id="quantite_nan"),
    pytest.param(_ligne(materiau=""), id="materiau_vide"),
    pytest.param(None, id="ligne_nulle"),
    pytest.param(7, id="ligne_numerique"),
])
def test_une_ligne_de_variance_indeterminee_n_est_jamais_chiffree(ligne):
    cout = _cout(signal=_signal([ligne]))

    assert cout["materiaux"]["lignes"][0]["statut"] == "LIGNE_INDETERMINEE"
    assert cout["materiaux"]["lignes"][0]["cout"] is None
    assert _codes(cout) == ["REJ-COUT-LIGNE-INDETERMINEE"] and cout["complet"] is False


def test_une_ligne_a_quantite_nulle_coute_zero_c_est_un_materiau_prevu_non_utilise():
    cout = _cout(signal=_signal([_ligne(reelle="0.0")]))

    assert cout["materiaux"]["lignes"][0]["cout"] == Decimal("0.00") and cout["complet"] is True


def test_un_manque_de_ligne_n_empeche_pas_de_chiffrer_les_autres_lignes():
    livre = [_prix("a", prix=2.0)]
    signal = _signal([_ligne("a", reelle="10"), _ligne("b", reelle="5")])

    cout = _cout(signal=signal, livre=livre)

    assert cout["materiaux"]["cout_connu"] == Decimal("20.00") and cout["complet"] is False
    assert [(e["code"], e["materiau"]) for e in cout["manque"]] == [("REJ-COUT-PRIX-NON-DISPONIBLE", "b")]


# =========================================================================================
# 4. Fail-closed sur la main-d'oeuvre : le taux et le temps viennent de sources, sinon manque
# =========================================================================================
@pytest.mark.parametrize("taux", [
    pytest.param(None, id="absent"),
    pytest.param(0, id="nul"),
    pytest.param("0.00", id="zero_texte"),
    pytest.param(-5, id="negatif"),
    pytest.param("cinquante", id="illisible"),
    pytest.param(True, id="booleen"),
    pytest.param([50], id="liste"),
    pytest.param(float("inf"), id="infini"),
])
def test_taux_horaire_absent_ou_invalide_donne_le_verdict_taux_a_configurer(taux):
    cout = _cout(taux=taux)

    assert cout["main_d_oeuvre"]["statut"] == "non_disponible" and cout["main_d_oeuvre"]["cout"] is None
    assert cout["main_d_oeuvre"]["taux_horaire"] is None
    assert _codes(cout) == ["REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]
    assert cout["complet"] is False and cout["cout_total"] is None
    assert cout["cout_total_connu"] == Decimal("336.00")  # les matériaux, eux, sont chiffrés


@pytest.mark.parametrize(("brut", "attendu"), [
    pytest.param("85.50", Decimal("85.50"), id="texte"),
    pytest.param(55, Decimal("55"), id="entier"),
    pytest.param(55.5, Decimal("55.5"), id="nombre_yaml"),
])
def test_taux_horaire_valide_sous_ses_formes_de_configuration(brut, attendu):
    taux, verdict = cout_reel.valider_taux_horaire(brut)

    assert (taux, verdict) == (attendu, None)


@pytest.mark.parametrize("duree", [
    pytest.param(None, id="absente"),
    pytest.param(0, id="nulle"),
    pytest.param(-15, id="negative"),
    pytest.param("180", id="texte"),
    pytest.param(True, id="booleen"),
    pytest.param(12.5, id="fractionnaire"),
])
def test_temps_pointe_absent_ou_illisible_donne_un_manque_jamais_une_duree_supposee(duree):
    cout = _cout(wct=_wct(duree_reelle_minutes=duree))

    assert cout["main_d_oeuvre"]["minutes"] is None and cout["main_d_oeuvre"]["cout"] is None
    assert _codes(cout) == ["REJ-COUT-TEMPS-POINTE-ABSENT"] and cout["complet"] is False


def test_une_duree_hors_de_toute_vraisemblance_est_illisible_pas_multipliee():
    cout = _cout(wct=_wct(duree_reelle_minutes=10**30))

    assert cout["main_d_oeuvre"]["minutes"] is None and cout["main_d_oeuvre"]["cout"] is None
    assert _codes(cout) == ["REJ-COUT-TEMPS-POINTE-ABSENT"]


def test_wct_recu_avant_t1_5_d_sans_la_cle_duree_est_dit_sans_temps_pointe():
    wct = _wct()
    del wct["duree_reelle_minutes"]

    assert _codes(_cout(wct=wct)) == ["REJ-COUT-TEMPS-POINTE-ABSENT"]


def test_aucun_wct_recu_donne_le_manque_de_temps():
    cout = cout_reel.calculer_cout_reel(None, _signal(), [_prix()], "50.00")

    assert _codes(cout) == ["REJ-COUT-TEMPS-POINTE-ABSENT"]


def test_temps_et_taux_absents_ensemble_les_deux_manques_sont_listes():
    cout = _cout(wct=_wct(duree_reelle_minutes=None), taux=None, livre=[])

    assert _codes(cout) == [
        "REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TEMPS-POINTE-ABSENT", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]
    assert cout["cout_total"] is None and cout["cout_total_connu"] == Decimal("0")


def test_un_second_travaux_termines_pour_le_meme_devis_rend_le_cout_partiel():
    cout = cout_reel.calculer_cout_reel(_wct(), _signal(), [_prix()], "50.00", autres_wct=["WCT-2", "WCT-2"])

    assert cout["complet"] is False and cout["cout_total"] is None
    assert cout["cout_total_connu"] == Decimal("486.00")  # celui du premier WCT, dit connu et jamais total
    (manque,) = cout["manque"]
    assert manque["code"] == "REJ-COUT-PLUSIEURS-WCT" and "2 travaux terminés" in manque["detail"]
    assert "WCT-2" in manque["detail"]
    assert cout["entrees"]["autres_wct"] == ["WCT-2"]  # dédoublonné, et compté dans la version des entrées


def test_l_absence_d_autre_wct_ne_change_ni_le_cout_ni_le_manque():
    assert _cout()["complet"] is True and _cout()["entrees"]["autres_wct"] == []


# =========================================================================================
# 5. Rentabilité partielle : jamais une marge quand le coût ne l'est pas
# =========================================================================================
def test_cout_partiel_pas_de_marge_reelle_seulement_un_plafond_dit_plafond():
    r = _rentabilite(cout=_cout(livre=[]))  # matériaux sans prix : coût connu = main-d'oeuvre, 150,00 $

    assert r["verdict"] == "PARTIELLE"
    assert r["marge_reelle"] is None and r["marge_reelle_pct_du_prix"] is None
    assert r["marge_partielle_plafond"] == Decimal("450.00")  # 600 - 150 : ce qui manque n'y est pas soustrait
    assert r["marge_partielle_plafond_pct_du_prix"] == Decimal("0.7500")
    assert r["ecart_marge"] is None and r["ecart_marge_points"] is None and r["en_perte"] is False
    assert "REJ-COUT-PRIX-NON-DISPONIBLE" in _codes(r)
    assert r["cout_reel"]["complet"] is False and r["cout_reel"]["cout_total"] is None


def test_sans_facture_le_prix_est_inconnu_et_aucune_marge_n_est_calculee():
    r = _rentabilite(facture=None)

    assert r["verdict"] == "PARTIELLE" and r["prix_facture"] is None and r["statut_facture"] is None
    assert r["marge_reelle"] is None and r["marge_partielle_plafond"] is None
    assert "REJ-RENTABILITE-FACTURE-ABSENTE" in _codes(r) and r["facture_id"] is None


def test_montant_de_facture_illisible_est_dit_illisible():
    r = _rentabilite(facture={"facture_id": "fac-X", "statut": "BROUILLON", "montant_avant_taxes": "beaucoup"})

    assert r["prix_facture"] is None and "REJ-RENTABILITE-FACTURE-ABSENTE" in _codes(r)
    assert "illisible" in next(e["detail"] for e in r["manque"] if e["code"] == "REJ-RENTABILITE-FACTURE-ABSENTE")


@pytest.mark.parametrize("devis", [
    pytest.param(None, id="devis_non_recu"),
    pytest.param(_devis(cout_total=None), id="sans_cout_total"),
    pytest.param(_devis(prix_total=None), id="sans_prix_total"),
    pytest.param(_devis(cout_total="beaucoup"), id="cout_total_illisible"),
])
def test_marge_prevue_absente_est_dite_absente_et_la_marge_reelle_reste_calculee(devis):
    r = _rentabilite(devis=devis)

    assert r["marge_prevue"] is None and r["cout_prevu"] is None and r["ecart_marge"] is None
    assert "REJ-RENTABILITE-MARGE-PREVUE-ABSENTE" in _codes(r)
    assert r["marge_reelle"] == Decimal("114.00")  # le réel ne dépend pas du prévu
    assert r["verdict"] == "CALCULEE"


def test_devis_recu_avant_t1_5_d_sans_cout_total_n_est_pas_recalcule_a_partir_des_lignes():
    devis = _devis()
    del devis["cout_total"], devis["taux_marge"]
    devis["lignes"] = [{"prix_unitaire": "10.00", "quantite": "40"}]  # ne sert à rien : jamais lu

    r = _rentabilite(devis=devis)

    assert r["marge_prevue"] is None and "REJ-RENTABILITE-MARGE-PREVUE-ABSENTE" in _codes(r)


# =========================================================================================
# 6. Aucune panne sur une pièce mal formée : elle devient un manque
# =========================================================================================
@pytest.mark.parametrize(("wct", "signal", "livre", "taux"), [
    pytest.param({}, {}, [], None, id="tout_vide"),
    pytest.param("wct", "signal", ["x"], "taux", id="pieces_textuelles"),
    pytest.param(_wct(), _signal(lignes="pas une liste"), [_prix()], "50", id="lignes_textuelles"),
    pytest.param(_wct(), _signal(lignes=[None, 5, "x", {}, {"materiau": 3}]), [_prix()], "50", id="lignes_delirantes"),
    pytest.param(_wct(duree_reelle_minutes=10**30), _signal(), [None, 4, {"materiau_id": MATERIAU}], 10**9,
                 id="valeurs_enormes"),
])
def test_une_piece_mal_formee_ne_leve_jamais_elle_devient_un_manque(wct, signal, livre, taux):
    wct_utilisable = wct if isinstance(wct, dict) else None
    signal_utilisable = signal if isinstance(signal, dict) else None

    cout = cout_reel.calculer_cout_reel(wct_utilisable, signal_utilisable, livre, taux)
    r = cout_reel.calculer_rentabilite(
        cout, {"statut": "BROUILLON"}, {"cout_total": [1]}, devis_id="D", chantier_id=None)

    assert isinstance(cout["complet"], bool) and isinstance(r["manque"], list)
    assert r["verdict"] in {"CALCULEE", "PARTIELLE"}


def test_tous_les_codes_de_manque_appartiennent_au_vocabulaire_de_validation():
    r = _rentabilite(cout=_cout(wct=_wct(duree_reelle_minutes=None), taux=None, livre=[]), facture=None, devis=None)

    assert {e["code"] for e in r["manque"]} <= validation.CODES_M5
    assert len({e["code"] for e in r["manque"]}) >= 4


# =========================================================================================
# 7. La version des entrées : ce qui change le calcul change la version, rien d'autre
# =========================================================================================
def test_meme_entrees_meme_version_et_resultat_rejouable():
    assert _rentabilite()["version_entrees"] == _rentabilite()["version_entrees"]
    assert _rentabilite() == _rentabilite()


@pytest.mark.parametrize("variante", [
    pytest.param(dict(cout=_cout(livre=[_prix(prix=8.5)])), id="prix_du_livre"),
    pytest.param(dict(cout=_cout(taux="55.00")), id="taux_horaire"),
    pytest.param(dict(cout=_cout(wct=_wct(duree_reelle_minutes=200))), id="temps_pointe"),
    pytest.param(dict(cout=_cout(signal=_signal([_ligne(reelle="43.0")]))), id="quantite_reelle"),
    pytest.param(dict(facture=_facture("ENVOYEE")), id="facture_envoyee"),
    pytest.param(dict(facture=_facture(montant="650.00")), id="prix_facture"),
    pytest.param(dict(devis=_devis(cout_total="470.00")), id="cout_prevu"),
    pytest.param(dict(facture=None), id="facture_absente"),
])
def test_une_entree_qui_change_change_la_version(variante):
    assert _rentabilite(**variante)["version_entrees"] != _rentabilite()["version_entrees"]


def test_une_entree_du_livre_pour_un_autre_materiau_ne_change_pas_la_version():
    de_base = _rentabilite()["version_entrees"]
    autre = _cout(livre=[_prix(), _prix("autre-materiau-fictif", prix=1.0)])

    assert _rentabilite(cout=autre)["version_entrees"] == de_base


def test_la_version_est_une_empreinte_sha256_de_l_encodage_canonique():
    version = _rentabilite()["version_entrees"]

    assert len(version) == 64 and int(version, 16) >= 0
    assert version != encodage.empreinte({})


# =========================================================================================
# 8. Trace, résumé et vue masquée
# =========================================================================================
def test_la_trace_est_un_maillon_derive_avec_la_version_et_le_calcul_complet():
    r = _rentabilite()

    trace = cout_reel.construire_trace(r, "2026-09-15T15:00:00+00:00")

    assert trace["type_entree"] == "rentabilite_calculee"
    assert (trace["devis_id"], trace["chantier_id"], trace["wct_id"]) == ("DEVIS-1", "CH-1", "WCT-1")
    assert trace["version_entrees"] == r["version_entrees"] and trace["verdict"] == "CALCULEE"
    assert trace["horodatage"] == "2026-09-15T15:00:00+00:00"  # celui du WCT : M5 n'a pas d'horloge
    assert trace["rentabilite"]["marge_reelle"] == Decimal("114.00")


def test_le_resume_d_une_liste_tient_en_une_ligne_de_chiffres_et_de_codes():
    resume = cout_reel.resumer(_rentabilite(cout=_cout(livre=[])))

    assert resume["verdict"] == "PARTIELLE" and resume["cout_reel_complet"] is False
    assert resume["cout_total"] is None and resume["cout_total_connu"] == Decimal("150.00")
    assert resume["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE"]
    assert "cout_reel" not in resume and "lignes" not in resume
    assert "devis_id" not in resume and "chantier_id" not in resume  # l'appelant les porte déjà


def test_la_vue_masquee_ne_porte_aucun_montant_ni_detail_de_manque():
    livre = [_prix(fournisseur="gentek-fictif", prix=8.0), _prix(fournisseur="kaycan-fictif", prix=9.0)]
    r = _rentabilite(cout=_cout(livre=livre))
    assert "9.0" in json.dumps(r, default=str)  # le détail complet, lui, cite bien les prix des fournisseurs

    masque = cout_reel.masquer_montants(r)

    assert masque["montants_masques"] is True and masque["manque"] == ["REJ-COUT-PRIX-AMBIGU"]
    assert not list(_tous_les_montants(masque))
    texte = json.dumps(masque, default=str)
    assert "8.0" not in texte and "9.0" not in texte and "gentek" not in texte and "kaycan" not in texte


# =========================================================================================
# 9. Pureté du module
# =========================================================================================
def test_le_module_est_pur_aucun_opsys_aucun_autre_departement_aucune_horloge():
    source = Path(cout_reel.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes |= {alias.name.split(".")[0] for alias in noeud.names}
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
            importes.add(noeud.module.split(".")[0])

    assert importes <= {"__future__", "collections", "decimal", "typing"}
    assert not any(nom.startswith("m") and nom[1:2].isdigit() for nom in importes)
