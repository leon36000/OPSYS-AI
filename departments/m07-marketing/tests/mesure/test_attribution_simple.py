"""Attribution simple : parts exactes, sans_source visible, coût par conversion seulement si la dépense est CONNUE,
sources indistinguables sans classement, causalité jamais établie."""

from __future__ import annotations

import math
from datetime import date

import pytest
from m7_marketing.mesure import attribution_simple as at

DEBUT, FIN = date(2026, 10, 1), date(2026, 10, 31)


def _c(i, source, medium="cpc", jour="2026-10-15"):
    return {"conversion_id": f"c{i}", "convertie_le": jour, "utm_source": source, "utm_medium": medium}


def _depenses(google="CONNUE", meta="CONNUE"):
    def canal(nom, statut, montant):
        return {
            "canal": nom,
            "statut": statut,
            "montant_cad": montant if statut == "CONNUE" else None,
            "au_moins_cad": "100.00" if statut == "PARTIELLE" else None,
            "base_taxes": "HORS_TAXES",
        }

    return {"canaux": [canal("google_ads", google, "1000.00"), canal("meta", meta, "600.00")]}


def _wilson(k, n, z=1.959964):
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    d = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - d, c + d


def _jeu():
    return (
        [_c(i, "google") for i in range(60)]
        + [_c(100 + i, "facebook") for i in range(20)]
        + [_c(200 + i, "instagram") for i in range(5)]
        + [_c(300 + i, None, None) for i in range(15)]
    )


def test_parts_exactes_dont_sans_source_au_denominateur_et_jamais_redistribuee():
    r = at.attribuer(_jeu(), DEBUT, FIN, _depenses())
    assert r["accepte"] and r["statut"] == "CALCULEE" and r["total_conversions"] == 100
    par = {s["source"]: s for s in r["sources"]}
    assert (par["google"]["conversions"], par["google"]["part"]) == (60, "0.6")
    assert (par["facebook"]["conversions"], par["facebook"]["part"]) == (20, "0.2")
    assert (par["instagram"]["conversions"], par["instagram"]["part"]) == (5, "0.05")
    assert r["sans_source"] == {"conversions": 15, "part": "0.15"}
    assert sum(s["conversions"] for s in r["sources"]) + r["sans_source"]["conversions"] == 100
    for source, k in (("google", 60), ("facebook", 20), ("instagram", 5)):
        bas, haut = _wilson(k, 100)
        assert (
            abs(float(par[source]["borne_basse"]) - bas) < 1e-5 and abs(float(par[source]["borne_haute"]) - haut) < 1e-5
        )
    assert [s["source"] for s in r["sources"]] == ["google", "facebook", "instagram"]


def test_causalite_toujours_non_etablie_avec_le_texte_exige():
    for r in (at.attribuer(_jeu(), DEBUT, FIN), at.attribuer([], DEBUT, FIN)):
        assert r["causalite"] == "non_etablie"
        assert r["avertissement_causalite"] == (
            "Attribution descriptive : elle compte, elle n'explique pas. Sans test "
            "marche-arrêt ou géographique préenregistré, aucun effet causal "
            "n'est affirmé."
        )
        assert "Dernière source connue" in r["regle"]


def test_sources_aux_intervalles_qui_se_chevauchent_sont_indistinguables_sans_classement():
    jeu = (
        [_c(i, "google") for i in range(6)]
        + [_c(50 + i, "facebook") for i in range(5)]
        + [_c(90 + i, "linkedin", "referral") for i in range(2)]
    )
    r = at.attribuer(jeu, DEBUT, FIN)
    # 6, 5 et 2 conversions sur 13 : les trois intervalles de Wilson se recoupent
    assert r["niveaux"] == [{"rang": 1, "sources": ["google", "facebook", "linkedin"], "indistinguables": True}]
    assert r["lecture"] == "Aucune source ne se distingue des autres à ce niveau de confiance : pas de classement."


def test_une_source_nettement_devant_forme_son_propre_niveau():
    jeu = [_c(i, "google") for i in range(500)] + [_c(900 + i, "facebook") for i in range(20)]
    r = at.attribuer(jeu, DEBUT, FIN)
    assert [n["sources"] for n in r["niveaux"]] == [["google"], ["facebook"]]
    assert not any(n["indistinguables"] for n in r["niveaux"])


def test_cout_par_conversion_seulement_quand_la_depense_est_connue_et_conversions_payantes():
    r = at.attribuer(_jeu(), DEBUT, FIN, _depenses())
    couts = {c["canal"]: c for c in r["couts_par_conversion"]}
    assert (
        couts["google_ads"]["cout_par_conversion_cad"] == "16.67" and couts["google_ads"]["conversions_payantes"] == 60
    )
    assert couts["meta"]["conversions_payantes"] == 25 and couts["meta"]["cout_par_conversion_cad"] == "24.00"
    assert couts["google_ads"]["inconnu"] is None


@pytest.mark.parametrize("statut", ["PARTIELLE", "NON_BRANCHEE"])
def test_cout_inconnu_quand_la_depense_n_est_pas_connue(statut):
    r = at.attribuer(_jeu(), DEBUT, FIN, _depenses(google=statut))
    c = next(c for c in r["couts_par_conversion"] if c["canal"] == "google_ads")
    assert c["cout_par_conversion_cad"] is None and statut in c["inconnu"] and c["statut_depense"] == statut
    assert next(c for c in r["couts_par_conversion"] if c["canal"] == "meta")["cout_par_conversion_cad"] == "24.00"
    assert "au_moins" not in repr(c["cout_par_conversion_cad"])


def test_cout_inconnu_sans_depense_fournie_ou_sans_conversion_payante():
    sans = at.attribuer(_jeu(), DEBUT, FIN)
    assert all(
        c["cout_par_conversion_cad"] is None and c["statut_depense"] == "NON_BRANCHEE"
        for c in sans["couts_par_conversion"]
    )
    organique = [_c(i, "google", "organique") for i in range(10)]
    r = at.attribuer(organique, DEBUT, FIN, _depenses())
    g = next(c for c in r["couts_par_conversion"] if c["canal"] == "google_ads")
    assert g["conversions_payantes"] == 0 and g["cout_par_conversion_cad"] is None and "indéfini" in g["inconnu"]
    assert r["sources"][0]["conversions"] == 10  # elles comptent par source, pas pour le coût payant


def test_arrondi_du_cout_au_cent_superieur_a_partir_du_demi():
    d = {
        "canaux": [
            {
                "canal": "google_ads",
                "statut": "CONNUE",
                "montant_cad": "100.00",
                "au_moins_cad": None,
                "base_taxes": "HORS_TAXES",
            }
        ]
    }
    r = at.attribuer([_c(i, "google") for i in range(8)], DEBUT, FIN, d)
    assert (
        next(c for c in r["couts_par_conversion"] if c["canal"] == "google_ads")["cout_par_conversion_cad"] == "12.50"
    )
    r = at.attribuer([_c(i, "google") for i in range(3)], DEBUT, FIN, d)
    assert (
        next(c for c in r["couts_par_conversion"] if c["canal"] == "google_ads")["cout_par_conversion_cad"] == "33.33"
    )
    r = at.attribuer([_c(i, "google") for i in range(6)], DEBUT, FIN, d)
    assert (
        next(c for c in r["couts_par_conversion"] if c["canal"] == "google_ads")["cout_par_conversion_cad"] == "16.67"
    )


def test_periode_filtre_les_conversions_et_aucune_conversion_n_est_pas_une_absence_de_ventes():
    jeu = [
        _c(1, "google", jour="2026-09-30"),
        _c(2, "google", jour="2026-10-01"),
        _c(3, "google", jour="2026-10-31"),
        _c(4, "google", jour="2026-11-01"),
    ]
    assert at.attribuer(jeu, DEBUT, FIN)["total_conversions"] == 2
    vide = at.attribuer([], DEBUT, FIN)
    assert vide["statut"] == "AUCUNE_CONVERSION" and vide["sources"] == [] and "absence d'import" in vide["lecture"]


@pytest.mark.parametrize(
    "debut,fin,niveau", [(FIN, DEBUT, "0.95"), ("2026-10-01", FIN, "0.95"), (DEBUT, FIN, "0.97"), (DEBUT, FIN, None)]
)
def test_arguments_invalides(debut, fin, niveau):
    r = at.attribuer([], debut, fin, None, niveau)
    assert r["accepte"] is False and r["refus"][0]["code"] == "REJ-MESURE-ATTRIBUTION-INVALIDE"


def test_niveau_99_donne_des_intervalles_plus_larges():
    a = at.attribuer(_jeu(), DEBUT, FIN, None, "0.95")["sources"][0]
    b = at.attribuer(_jeu(), DEBUT, FIN, None, "0.99")["sources"][0]
    assert float(b["borne_haute"]) - float(b["borne_basse"]) > float(a["borne_haute"]) - float(a["borne_basse"])
