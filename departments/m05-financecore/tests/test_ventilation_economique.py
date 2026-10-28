"""Calcul économique fictif ; les faits et sources sont validés en amont."""
from decimal import Decimal

from m5_financecore.ventilation_couts_visites import chiffrer_visites


def visite(identifiant, equipe, minutes, jour):
    return {"visite_id": identifiant, "equipe_pointee": {"statut": "identifiee", "identifiant": equipe},
            "minutes": {"travail": minutes}, "composition_declaree": {"jour": jour}}


def taux(equipe, valeur):
    return {"equipe_id": equipe, "taux": valeur, "unite": "heure-equipe", "devise": "CAD",
            "source": "tarif-fictif", "version": "1", "date_effet": "2030-01-01", "date_fin": "2030-12-31"}


def test_deux_visites_et_deux_tarifs_sommes_avec_provenance():
    resultat = chiffrer_visites([visite("v1", "A", 150, "2030-06-03"),
                                 visite("v2", "B", 240, "2030-06-07")],
                                [taux("A", "100"), taux("B", "120")])
    assert resultat["complet"] is True
    assert resultat["cout_total"] == Decimal("730.00")
    assert [ligne["cout"] for ligne in resultat["lignes"]] == [Decimal("250.00"), Decimal("480.00")]
    assert resultat["lignes"][1]["source"] == "tarif-fictif"


def test_taux_manquant_ou_ambigu_ne_devient_jamais_un_zero():
    visites = [visite("v1", "A", 150, "2030-06-03"), visite("v2", "B", 240, "2030-06-07")]
    for tarifs in ([taux("A", "100")], [taux("A", "100"), taux("B", "120"), taux("B", "121")]):
        resultat = chiffrer_visites(visites, tarifs)
        assert resultat["complet"] is False
        assert resultat["cout_total"] is None
        assert resultat["cout_connu"] == Decimal("250.00")
        assert resultat["lignes"][1]["cout"] is None
        assert resultat["raisons"]


def test_taux_hors_periode_ou_personne_refuse():
    v = [visite("v1", "A", 150, "2030-06-03")]
    for tarif in (taux("A", "100") | {"date_fin": "2030-06-02"},
                  taux("A", "100") | {"unite": "heure-personne"}):
        resultat = chiffrer_visites(v, [tarif])
        assert not resultat["complet"] and resultat["cout_total"] is None
        assert resultat["lignes"][0]["cout"] is None


def test_zero_atteste_par_les_faits_reste_un_montant_connu():
    resultat = chiffrer_visites([visite("v1", "A", 0, "2030-06-03")], [taux("A", "100")])
    assert resultat["complet"] is True
    assert resultat["cout_total"] == Decimal("0.00")
