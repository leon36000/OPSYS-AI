"""Composition du dossier de paie préparatoire : moteurs réels, oracles indépendants, couverture et refus (fictif)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import getcontext, setcontext
from fractions import Fraction
from pathlib import Path

import pytest
from m5_financecore import dossier_paie_preparatoire as d

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures_dossier_paie import ADMISSION_OK, ADMISSION_REFUSEE, copie, entrees, entrees_periode_20  # noqa: E402

FICTIF = True


def _compose(e, brut="1002.00", admission=ADMISSION_OK):
    valides, verdict = d.valider_entrees(e)
    assert verdict is None, verdict
    return d.composer(valides, {"brut_brouillon": brut}, admission)


def _par_id(calcul):
    return {p["id"]: p for p in calcul["matrice"]}


def _cents(valeur: Fraction) -> Fraction:
    centimes = valeur * 100
    plancher = centimes.numerator // centimes.denominator
    return Fraction(plancher + (1 if centimes - plancher >= Fraction(1, 2) else 0), 100)


def test_p1_compose_les_postes_reels_et_les_totaux_justifies():
    calcul = _compose(entrees())
    assert calcul["etat"] == "COMPOSE_PREPARATOIRE" and calcul["refus"] is None
    assert calcul["mode"] == "PREPARATOIRE" and calcul["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert calcul["actions_financieres_bloquees"] is True and calcul["aucun_versement"] is True
    postes = _par_id(calcul)
    # Oracles calculés à la main depuis les formules officielles (RRQ, RQAP, AE) ; QC et fédéral = vecteurs des moteurs.
    exemption = Fraction(3500, 26)
    exemption = Fraction(int(exemption * 100), 100)  # tronqué au cent : 134.61
    assert postes["rrq_employe"]["montant"] == "54.65" == f"{float(_cents(Fraction('0.063') * (1002 - exemption))):.2f}"
    assert postes["rqap_employe"]["montant"] == "4.31" and postes["rqap_employeur"]["montant"] == "6.03"
    assert postes["ae_employe"]["montant"] == "13.03" and postes["ae_employeur"]["montant"] == "18.24"
    assert postes["impot_quebec"]["montant"] == "131.26" and postes["impot_federal"]["montant"] == "28.00"
    assert postes["rrq_employeur"]["montant"] == postes["rrq_employe"]["montant"]
    totaux = calcul["totaux"]
    assert totaux["retenues_employe"]["montant"] == "231.25"
    assert totaux["net_preparatoire"]["montant"] == "770.75"
    assert totaux["das_revenu_quebec"]["montant"] == "267.43" and totaux["das_arc"]["montant"] == "59.27"
    assert totaux["das_complete"]["montant"] == "326.70"
    assert totaux["cout_employeur_global"]["montant"] == "1113.48"
    assert all(t["etat"] == "CALCULE" and t["manques"] == [] for t in totaux.values())


def test_aucune_somme_partielle_et_aucun_float():
    calcul = _compose(entrees())
    texte = d.canonique(calcul)
    assert "float" not in texte
    for totaux in calcul["totaux"].values():
        assert totaux["montant"] is None or isinstance(totaux["montant"], str)


def test_periode_20_plafonds_atteints_oracle_independant():
    e = entrees_periode_20()
    calcul = _compose(e, brut="1000.00")
    postes = _par_id(calcul)
    # Palier 1 plafonné : 4479.30 − 4479.29 = 0.01 ; palier 2 : 4 % × (74 590 + 1 000 − 74 600) = 39.60 (oracle exact).
    assert postes["rrq_employe"]["montant"] == "39.61" == postes["rrq_employeur"]["montant"]
    assert calcul["moteurs"]["rrq"] == {"cotisation_palier1": "0.01", "cotisation_palier2": "39.60"}
    # RQAP 442.90−442.89 / 620.06−620.05 ; AE 895.70−895.69 / 1253.98−1253.97.
    assert postes["rqap_employe"]["montant"] == "0.01" and postes["rqap_employeur"]["montant"] == "0.01"
    assert postes["ae_employe"]["montant"] == "0.01" and postes["ae_employeur"]["montant"] == "0.01"
    assert calcul["etat"] == "COMPOSE_PREPARATOIRE"
    # Cumuls après : hypothétiques, ajoutés aux cumuls avant, jamais au-delà des maxima annuels.
    version_cumuls = d.cumuls_apres(d.valider_entrees(e)[0], calcul, "1000.00")
    assert version_cumuls["rrq_palier1_cumul_avant"] == "4479.30"
    assert (
        version_cumuls["rqap_salarie_cumul_avant"] == "442.90"
        and version_cumuls["ae_employeur_cumul_avant"] == "1253.98"
    )
    assert version_cumuls["salaire_rrq_cumul_avant"] == "75590.00"
    assert version_cumuls["rrq_palier2_cumul_avant"] == "39.60"


def test_cumuls_au_dela_du_plafond_sont_refuses_par_les_moteurs():
    e = entrees_periode_20()
    e["cumuls_avant"]["valeurs"]["rrq_palier1_cumul_avant"] = "4479.31"
    calcul = _compose(e, brut="1000.00")
    assert calcul["etat"] == "COMPOSANTE_REFUSEE"
    assert calcul["totaux"]["net_preparatoire"]["etat"] == "INCONNU"
    declares = {"brut_regulier", "autres_retenues_employe", "autres_couts_employeur"}
    assert all(p["etat"] == "INCONNU" for p in calcul["matrice"] if p["id"] not in declares)


def _chaine(brut: str, anchor=date(2026, 1, 2)):
    """26 périodes enchaînées par les cumuls hypothétiques de chaque version."""
    cumuls = dict.fromkeys(d.CHAMPS_CUMULS, "0.00")
    resultats = []
    for n in range(1, 27):
        paie = anchor + timedelta(days=14 * (n - 1))
        fin = paie - timedelta(days=1)
        e = entrees(
            n,
            premiere=anchor.isoformat(),
            debut=(fin - timedelta(days=13)).isoformat(),
            fin=fin.isoformat(),
            date_paie=paie.isoformat(),
            cumuls=copie(cumuls),
            origine="NUL_PERIODE_1" if n == 1 else "DECLARE_HISTORIQUE",
        )
        valides, verdict = d.valider_entrees(e)
        assert verdict is None, (n, verdict)
        calcul = d.composer(valides, {"brut_brouillon": brut}, ADMISSION_OK)
        assert calcul["etat"] == "COMPOSE_PREPARATOIRE", (n, calcul["refus"])
        cumuls = d.cumuls_apres(valides, calcul, brut)
        resultats.append((calcul, copie(cumuls)))
    return resultats


def test_chaine_26_periodes_plafonds_exacts_et_aucun_depassement():
    resultats = _chaine("5000.00")
    finals = resultats[-1][1]
    # Aux maxima annuels officiels 2026, sommes de montants arrondis par période.
    assert finals["rrq_palier1_cumul_avant"] == "4479.30"
    assert finals["rqap_salarie_cumul_avant"] == "442.90" and finals["rqap_employeur_cumul_avant"] == "620.06"
    assert finals["ae_salarie_cumul_avant"] == "895.70" and finals["ae_employeur_cumul_avant"] == "1253.98"
    assert finals["salaire_rrq_cumul_avant"] == "130000.00"
    # Oracle indépendant de la période 1 et du premier franchissement du plafond RRQ (période 15).
    exemption = Fraction(13461, 100)
    c1 = _cents(Fraction("0.063") * (5000 - exemption))
    assert _par_id(resultats[0][0])["rrq_employe"]["montant"] == f"{float(c1):.2f}" == "306.52"
    cumul, premiere_limite = Fraction(0), None
    for n in range(1, 27):
        montant = Fraction(_par_id(resultats[n - 1][0])["rrq_employe"]["montant"])
        palier2 = Fraction(_par_id(resultats[n - 1][0])["rrq_employeur"]["montant"])
        assert montant == palier2
        cumul += Fraction(resultats[n - 1][0]["moteurs"]["rrq"]["cotisation_palier1"])
        assert cumul <= Fraction("4479.30")
        if cumul == Fraction("4479.30") and premiere_limite is None:
            premiere_limite = n
    assert premiere_limite == 15
    # Après le plafond, les cotisations de plafond tombent à zéro mais les crédits fédéraux restent calculés.
    assert _par_id(resultats[20][0])["rrq_employe"]["montant"] is not None
    for calcul, _ in resultats:
        assert calcul["totaux"]["net_preparatoire"]["etat"] == "CALCULE"
        net = Fraction(calcul["totaux"]["net_preparatoire"]["montant"])
        retenues = Fraction(calcul["totaux"]["retenues_employe"]["montant"])
        assert net + retenues == 5000 and net > 0


def test_fss_cnesst_normes_suivent_le_cumul_annuel_dans_la_chaine():
    resultats = _chaine("5000.00")
    cnesst_total = sum(Fraction(_par_id(c)["cnesst"]["montant"]) for c, _ in resultats)
    normes_total = sum(Fraction(_par_id(c)["normes_travail"]["montant"]) for c, _ in resultats)
    # 103 000 $ assurables sur l'année : 20 périodes pleines (100 000 $) + 3 000 $ à la période 21.
    assert cnesst_total == _cents(Fraction(100000) * Fraction("1.54") / 100) + _cents(
        Fraction(3000) * Fraction("1.54") / 100
    ) or cnesst_total == 20 * _cents(Fraction(5000) * Fraction("1.54") / 100) + _cents(
        Fraction(3000) * Fraction("1.54") / 100
    )
    assert normes_total == 20 * _cents(Fraction(5000) * Fraction("0.06") / 100) + _cents(
        Fraction(3000) * Fraction("0.06") / 100
    )
    assert _par_id(resultats[21][0])["cnesst"]["montant"] == "0.00"


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda e: e["attestations"].update(assiettes_egales_au_brut=False), "assiettes distinctes"),
        (lambda e: e["attestations"].update(aucune_autre_remuneration_ni_avantage=False), "avantage"),
        (lambda e: e["attestations"].update(paiement_regulier_fixe=False), "régulier fixe"),
        (lambda e: e["attestations"].update(aucune_gratification_ni_retroactif=False), "gratification"),
        (lambda e: e["attestations"].update(taux_ae_normal=False), "AE réduit"),
        (lambda e: e["attestations"].update(pm_12=False), "PM"),
        (lambda e: e["classification"].update(regime_ccq="CCQ"), "CCQ"),
        (lambda e: e["credits_federal"].update(F="10.00"), "fédéral"),
        (lambda e: e["credits_qc"].update(L="5.00"), "QC"),
    ],
)
def test_cas_hors_domaine_ne_calcule_rien_et_garde_tout_inconnu(mutation, fragment, monkeypatch):
    def interdit(**_):
        pytest.fail("un moteur a été appelé pour un cas hors couverture")

    monkeypatch.setattr(d, "calculer_retenue_federale_qc_preparatoire", interdit)
    e = entrees()
    mutation(e)
    calcul = _compose(e)
    assert calcul["etat"] == "HORS_COUVERTURE"
    assert any(fragment in m["detail"] for m in calcul["motifs_hors_couverture"])
    assert all(t["etat"] == "INCONNU" and t["montant"] is None for t in calcul["totaux"].values())
    declares = {"brut_regulier", "autres_retenues_employe", "autres_couts_employeur"}
    assert all(p["etat"] == "INCONNU" for p in calcul["matrice"] if p["id"] not in declares)


def test_classification_ccq_inconnue_laisse_les_postes_calcules_mais_aucun_total():
    e = entrees()
    e["classification"]["regime_ccq"] = "INCONNU"
    calcul = _compose(e)
    assert calcul["etat"] == "COMPOSE_PREPARATOIRE"
    assert _par_id(calcul)["impot_federal"]["etat"] == "CALCULE"
    for cle in ("retenues_employe", "net_preparatoire", "das_complete", "cout_employeur_global"):
        assert calcul["totaux"][cle]["etat"] == "INCONNU" and calcul["totaux"][cle]["montant"] is None
        assert any("classification CCQ non établie" in m for m in calcul["totaux"][cle]["manques"])
    assert calcul["statut_ccq"] == "UNKNOWN"


def test_donnees_manquantes_ne_deviennent_jamais_zero():
    e = entrees()
    e["autres_retenues_employe"] = None
    calcul = _compose(e)
    assert calcul["totaux"]["retenues_employe"]["montant"] is None
    assert calcul["totaux"]["net_preparatoire"]["montant"] is None
    assert any("autres_retenues_employe" in m for m in calcul["totaux"]["net_preparatoire"]["manques"])
    e = entrees()
    e["autres_couts_employeur"] = None
    calcul = _compose(e)
    assert calcul["totaux"]["net_preparatoire"]["etat"] == "CALCULE"
    assert calcul["totaux"]["cout_employeur_global"]["montant"] is None
    e = entrees(employeur=False)
    calcul = _compose(e)
    assert calcul["totaux"]["net_preparatoire"]["etat"] == "CALCULE"
    for cle in ("das_revenu_quebec", "das_complete", "cout_employeur_global"):
        assert calcul["totaux"][cle]["montant"] is None
    assert calcul["totaux"]["das_arc"]["etat"] == "CALCULE"  # tous ses postes sont couverts
    assert any(m.startswith("fss:") for m in calcul["totaux"]["das_complete"]["manques"])


def test_admission_refusee_n_appelle_aucun_moteur(monkeypatch):
    def interdit(**_):
        pytest.fail("moteur appelé malgré une admission refusée")

    monkeypatch.setattr(d, "calculer_retenue_federale_qc_preparatoire", interdit)
    calcul = _compose(entrees(), admission=ADMISSION_REFUSEE)
    assert calcul["etat"] == "ADMISSION_REFUSEE"
    assert "CAPTURE_INDISPONIBLE_OU_LIEE" in calcul["refus"]["detail"]
    assert calcul["totaux"]["net_preparatoire"]["montant"] is None


def test_admission_absente_ou_mal_formee_refuse():
    for admission in (None, {}, {"admissible": "oui"}, {"admissible": 1}):
        assert _compose(entrees(), admission=admission)["etat"] == "ADMISSION_REFUSEE"


def test_brut_absent_ou_illisible_donne_source_refusee():
    valides = d.valider_entrees(entrees())[0]
    for brut in (None, {}, {"brut_brouillon": 62.5}, {"brut_brouillon": "62.5"}, {"brut_brouillon": "-1.00"}):
        calcul = d.composer(valides, brut, ADMISSION_OK)
        assert calcul["etat"] == "SOURCE_REFUSEE"
        assert all(t["montant"] is None for t in calcul["totaux"].values())


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda e: e["periode"].update(periode_annuelle=2), "CALENDRIER-INCOHERENT"),
        (lambda e: e["periode"].update(date_paie="2026-01-16"), "CALENDRIER-INCOHERENT"),
        (
            lambda e: e["periode"].update(
                premiere_date_paie_annee="2026-01-01", date_paie="2026-01-01", debut="2025-12-18", fin="2025-12-31"
            ),
            "HORS-COUVERTURE",
        ),  # 27 paies
        (lambda e: e["periode"].update(annee=2027), "HORS-COUVERTURE"),
        (lambda e: e["periode"].update(periode_annuelle=27), "PERIODE-INVALIDE"),
        (lambda e: e["periode"].update(fin="2026-01-13"), "HORS-COUVERTURE"),  # 13 jours
        (lambda e: e["periode"].update(fuseau="Mars/Olympus"), "PERIODE-INVALIDE"),
        (
            lambda e: e["periode"].update(date_paie="2026-01-10", premiere_date_paie_annee="2026-01-10"),
            "PERIODE-INVALIDE",
        ),
        (lambda e: e["periode"].update(date_paie="2027-01-15"), "PERIODE-INVALIDE"),
    ],
)
def test_calendrier_et_periode_refuses(mutation, code):
    e = entrees()
    mutation(e)
    valides, verdict = d.valider_entrees(e)
    assert verdict is None
    _, verdict_periode = d.valider_periode(valides["periode"])
    assert verdict_periode is not None and verdict_periode["code"] == f"REJ-DOSSIER-PAIE-{code}"
    calcul = d.composer(valides, {"brut_brouillon": "1002.00"}, ADMISSION_OK)
    assert calcul["etat"] == "HORS_COUVERTURE" and calcul["totaux"]["net_preparatoire"]["montant"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.pop("fictif"),
        lambda e: e.update(extra=1),
        lambda e: e.update(fictif="oui"),
        lambda e: e.update(employeur_reference="<script>"),
        lambda e: e["attestations"].update(emploi_continu=1),
        lambda e: e["attestations"].pop("pm_12"),
        lambda e: e["credits_federal"].update(TC=16452.0),
        lambda e: e["credits_federal"].update(TC="16452"),
        lambda e: e["credits_federal"].update(TC="-1.00"),
        lambda e: e["credits_qc"].update(K1_annuel="1e3"),
        lambda e: e["credits_qc"].update(J_determined_after_period_1="non"),
        lambda e: e["pieces"].update(td1_federal={"reference": "", "sha256": None}),
        lambda e: e["pieces"].update(td1_federal={"reference": "ok", "sha256": "ABC"}),
        lambda e: e["pieces"].pop("registre_cumuls"),
        lambda e: e["arrondi"].update(politique="arrondi_libre"),
        lambda e: e["classification"].update(regime_ccq="peut-etre"),
        lambda e: e["cumuls_avant"].update(origine="INVENTE"),
        lambda e: e["cumuls_avant"]["valeurs"].update(ae_salarie_cumul_avant="1.5"),
        lambda e: e["cumuls_avant"].update(source_simulee={"dossier_id": "x"}),
        lambda e: e["autres_retenues_employe"].update(montant=0),
        lambda e: e["periode"].update(periode_annuelle="1"),
    ],
)
def test_entrees_mal_formees_refusees_sans_valeur_par_defaut(mutation):
    e = entrees()
    mutation(e)
    valides, verdict = d.valider_entrees(e)
    assert valides is None and verdict["code"].startswith("REJ-DOSSIER-PAIE-")


def test_cumuls_simules_exigent_une_source_exacte():
    e = entrees(
        2,
        premiere="2026-01-02",
        debut="2025-12-20",
        fin="2026-01-02",
        date_paie="2026-01-16",
        origine="SIMULE_VERSION_PRECEDENTE",
    )
    assert d.valider_entrees(e)[0] is None  # source_simulee absente
    e["cumuls_avant"]["source_simulee"] = {"dossier_id": "a" * 32, "numero_version": 1, "hash_version": "b" * 64}
    assert d.valider_entrees(e)[1] is None
    e["cumuls_avant"]["reference_confirmation"] = "piece"
    assert d.valider_entrees(e)[0] is None
    e2 = entrees(origine="CONFIRME_AUTORITE_HUMAINE")
    assert d.valider_entrees(e2)[0] is None  # confirmation sans référence de pièce


def test_contexte_decimal_hostile_du_appelant_ne_change_rien():
    normal = d.canonique(_compose(entrees_periode_20(), brut="1234.56"))
    ancien = getcontext().copy()
    try:
        hostile = getcontext().copy()
        hostile.prec, hostile.rounding = 4, "ROUND_DOWN"
        setcontext(hostile)
        sous_hostile = d.canonique(_compose(entrees_periode_20(), brut="1234.56"))
    finally:
        setcontext(ancien)
    assert sous_hostile == normal


def test_provenance_des_pieces_distingue_piece_fournie_et_declaration_seule():
    e = entrees()
    e["pieces"]["td1_federal"]["sha256"] = "f" * 64
    calcul = _compose(e)
    assert calcul["provenance_pieces"]["td1_federal"] == {
        "reference": "piece-td1_federal-fictive",
        "sha256": "f" * 64,
        "origine_empreinte": "PIECE_FOURNIE",
    }
    assert calcul["provenance_pieces"]["tp1015_3_qc"]["origine_empreinte"] == "DECLARATION_SEULE"


def test_sortie_deterministe_et_sans_donnee_personnelle():
    a, b = d.canonique(_compose(entrees())), d.canonique(_compose(entrees()))
    assert a == b
    for interdit in ("nas", "iban", "adresse", "taux_horaire", "courriel"):
        assert interdit not in a.lower()


def test_retenues_superieures_au_brut_ne_donnent_jamais_un_net_negatif():
    e = entrees()
    e["autres_retenues_employe"] = {"montant": "99999.00", "reference": "retenue-fictive-excessive"}
    calcul = _compose(e)
    assert calcul["etat"] == "COMPOSE_PREPARATOIRE"
    assert calcul["totaux"]["retenues_employe"]["etat"] == "CALCULE"
    net = calcul["totaux"]["net_preparatoire"]
    assert net["etat"] == "INCONNU" and net["montant"] is None
    assert any("supérieures au brut" in m for m in net["manques"])


def test_brut_nul_donne_des_retenues_nulles_et_un_net_nul_sans_division():
    calcul = _compose(entrees(), brut="0.00")
    assert calcul["etat"] == "COMPOSE_PREPARATOIRE"
    assert calcul["totaux"]["net_preparatoire"]["montant"] == "0.00"
    assert calcul["totaux"]["retenues_employe"]["montant"] == "0.00"


def test_rapprochement_independant_sans_double_compte_sur_toute_l_annee():
    """Chaque poste n'est compté qu'une fois : DAS RQ et DAS ARC sont disjointes et leur somme est la DAS complète."""
    for calcul, _ in _chaine("1234.56"):
        par_id = _par_id(calcul)
        totaux = calcul["totaux"]
        rq = ("impot_quebec", "rrq_employe", "rrq_employeur", "rqap_employe", "rqap_employeur", "fss")
        arc = ("impot_federal", "ae_employe", "ae_employeur")
        assert set(totaux["das_revenu_quebec"]["postes"]) == set(rq) and set(totaux["das_arc"]["postes"]) == set(arc)
        assert not set(rq) & set(arc)
        somme_rq = sum(Fraction(par_id[i]["montant"]) for i in rq)
        somme_arc = sum(Fraction(par_id[i]["montant"]) for i in arc)
        assert Fraction(totaux["das_revenu_quebec"]["montant"]) == somme_rq
        assert Fraction(totaux["das_arc"]["montant"]) == somme_arc
        assert Fraction(totaux["das_complete"]["montant"]) == somme_rq + somme_arc
        employe = sum(
            Fraction(par_id[i]["montant"])
            for i in ("rrq_employe", "impot_quebec", "rqap_employe", "ae_employe", "impot_federal")
        )
        assert Fraction(totaux["retenues_employe"]["montant"]) == employe  # + 0.00 d'autres retenues déclarées
        assert Fraction(totaux["net_preparatoire"]["montant"]) == Fraction("1234.56") - employe
        cout = Fraction("1234.56") + sum(
            Fraction(par_id[i]["montant"] or "0")
            for i in ("rrq_employeur", "rqap_employeur", "ae_employeur", "fss", "cnesst", "normes_travail")
        )
        assert Fraction(totaux["cout_employeur_global"]["montant"]) == cout
