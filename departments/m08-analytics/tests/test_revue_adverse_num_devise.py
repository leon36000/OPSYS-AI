"""Revue adverse (num) : la garde « devise CAD seulement » (`dictionnaire.devise_non_autorisee`) ne se contourne pas
par une simple mise en forme de l'unité.

Défaut trouvé : la garde ne reconnaissait qu'un code ISO 4217 NU (« USD ») ou suivi de « /mot » (« USD/lead »).
`m8_enregistrer_definition_metrique` prend l'unité d'un agent en texte libre : « USD / lead », « EUR/1000 impressions »,
« lead (USD) », « € par lead » ou « dollars US » traversaient donc la garde et entraient au registre des métriques
surveillées comme si elles étaient en CAD. Données fictives.
"""

from __future__ import annotations

import pytest
from m8_analytics import dictionnaire, registre_metriques

FICTIF = True


@pytest.mark.parametrize("unite", [
    "USD / lead", "EUR/1000 impressions", "lead (USD)", "USD par lead", "GBP/ lead", "usd/lead\n", "CAD/USD",
    "€ par lead", "£/lead", "$US", "US$/lead", "dollars US", "dollar américain", "euros", "Euro/lead", "JPY",
    "coût en eur", "lead-USD",
])
def test_une_devise_etrangere_est_detectee_quelle_que_soit_la_mise_en_forme(unite):
    assert dictionnaire.devise_non_autorisee(unite) is not None


@pytest.mark.parametrize("unite", [
    "CAD", "cad", "CAD/lead", "CAD/soumission", "CAD / lead", "CAD par lead", "$ CAD", "CAD/1000 impressions",
    "ratio", "pourcentage", "entier", "dict {note: entier}", "float (jours)", "ratio (0.0–1.0)", "float (1.0–5.0)",
    "dict {categorie: entier}", "min", "%", "km", "h", "jours", "nb", "devis", "leads", "chantiers", "impressions",
    "minutes", "clics", "contenus",
    "madriers",  # « mad » (dirham marocain) n'est pas un mot entier dans « madriers » (bois de charpente)
    "tarif aux pieds carrés", "Jours ouvrables", "cadres",
])
def test_les_unites_legitimes_ne_sont_pas_des_devises_etrangeres(unite):
    assert dictionnaire.devise_non_autorisee(unite) is None


def _definition(unite):
    return {"metric_id": "m8_cout_lead_test", "source": "test", "departement_proprietaire": "m08-analytics",
            "unite": unite, "fraicheur_attendue_jours": 7, "regles_qualite": {"plage_min": None, "plage_max": None}}


@pytest.mark.parametrize("unite", ["USD / lead", "lead (EUR)", "€ par lead"])
def test_le_registre_durable_refuse_la_definition_en_devise_etrangere(unite):
    maillons = []
    reponse = registre_metriques.enregistrer_definition(_definition(unite), maillons)
    assert reponse["enregistree"] is False
    assert reponse["verdict"].startswith("REJ-DEFINITION-DEVISE-NON-AUTORISEE")
    assert maillons == []


def test_le_registre_durable_accepte_cad():
    maillons = []
    reponse = registre_metriques.enregistrer_definition(_definition("CAD / lead"), maillons)
    assert reponse["enregistree"] is True and len(maillons) == 1
