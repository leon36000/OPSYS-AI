import pytest
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import recommandation_gouvernee as rg


@pytest.mark.parametrize("source", ["-$8400.00", "$-8400", "−$8400.00", "$−8400"])
def test_signe_avant_ou_apres_symbole_dollar_est_conserve(source):
    assert conseil._nombre(source) < 0
    captures = list(conseil._MONTANT.finditer(source))
    assert len(captures) == 1
    assert captures[0].group(0) == source
    assert conseil._nombre(captures[0].group(0)) < 0


def test_montant_signe_avant_symbole_ne_reautorise_pas_la_valeur_positive_secondaire():
    source = "-$8400.00"
    texte_positif = "Solde positif 8400.00 $"
    assert conseil.chiffres_libres(texte_positif, [source]) == ["8400.00 $"]
    assert rg.nombres_libres(texte_positif, [source]) == ["8400.00"]
    assert conseil.chiffres_libres("Solde négatif -$8400.00", [source]) == []
    assert rg.nombres_libres("Solde négatif -$8400.00", [source]) == []


def test_admission_publique_refuse_la_reformulation_positive_de_la_source_negative():
    reference = "m5.faits#0:p0.resultat.solde"
    sortie = {
        "affirmations": [
            {"id": "A1", "nature": "observation_source", "reference": reference, "valeur": "-$8400.00"},
            {"id": "H1", "nature": "hypothese", "enonce": "Solde positif 8400.00 $"},
        ]
    }
    with pytest.raises(ValueError, match="REJ-CONSEIL-CHIFFRE-LIBRE"):
        conseil.admettre_proposition(sortie, sources={reference: "-$8400.00"})


def test_source_negative_et_texte_negatif_exact_reste_admissible():
    reference = "m5.faits#0:p0.resultat.solde"
    sortie = {
        "affirmations": [
            {"id": "A1", "nature": "observation_source", "reference": reference, "valeur": "$−8400"},
            {"id": "H1", "nature": "hypothese", "enonce": "Solde -$8400.00"},
        ]
    }
    assert conseil.admettre_proposition(sortie, sources={reference: "$−8400"})["type"] == "PROPOSITION_ADMISE"
    assert rg.nombres_libres("Solde -$8400.00", ["$−8400"]) == []


def test_dollar_prefixe_positif_dates_et_identifiants_restant_distincts():
    assert conseil.chiffres_libres("Solde 8400.00 $", ["$8400.00"]) == []
    assert rg.nombres_libres("Solde $8400.00", ["8400.00"]) == []
    assert conseil.chiffres_libres("Date 2026-11-09, ID option-$8400.00", ["2026-11-09"]) == []
    assert rg.nombres_libres("Date 2026-11-09, ID option-$8400.00", ["2026-11-09"]) == []
